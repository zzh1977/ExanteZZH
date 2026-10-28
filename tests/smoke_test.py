#!/usr/bin/env python3
"""端到端冒烟测试：用假 Ollama 服务跑一遍 scan → apply → verify → undo，并检查文档工具。

用工具的 Python 环境运行（需要 file_organizer/requirements.txt 里的包）：
  venv/bin/python tests/smoke_test.py          # macOS / Linux
  venv\\Scripts\\python.exe tests\\smoke_test.py  # Windows

全部通过时最后一行是 “全部通过”，返回 0；任何一项失败会说明原因并返回 1。
不需要真模型，也不需要联网。
"""
import csv
import json
import shutil
import subprocess
import sys
import tempfile
import threading
import http.server
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ORG = ROOT / "file_organizer" / "organize.py"
sys.path.insert(0, str(Path(__file__).resolve().parent))
from fake_ollama import Handler  # noqa: E402

failures = []


def check(cond, what):
    print(("  通过  " if cond else "  失败  ") + what)
    if not cond:
        failures.append(what)


def run(*args):
    r = subprocess.run([sys.executable, str(ORG), *args], capture_output=True, text=True, encoding="utf-8")
    if r.returncode != 0:
        print(r.stdout, r.stderr)
    return r


def make_samples(src):
    (src / "sub").mkdir(parents=True)
    (src / "会议.txt").write_text("本周例会纪要：讨论了项目进度和下一步安排。", encoding="utf-8")
    (src / "report.txt").write_text("The quarterly report shows that revenue for the third quarter grew.", encoding="utf-8")
    (src / "brief.txt").write_text("Sehr geehrte Damen und Herren, anbei die Rechnung für den Monat März.", encoding="utf-8")
    (src / "sub" / "copy.txt").write_text("本周例会纪要：讨论了项目进度和下一步安排。", encoding="utf-8")  # 重复文件
    (src / "scan_001.pdf").write_bytes(b"%PDF-1.4\n%%EOF")  # 读不出文字 -> 未识别语言
    (src / "movie.mp4").write_bytes(b"\0" * 1000)
    (src / ".DS_Store").write_bytes(b"x")  # 应被跳过
    (src / "._brief.txt").write_bytes(b"x")  # 应被跳过
    from PIL import Image
    exif = Image.Exif()
    exif[306] = "2023:08:15 10:00:00"
    Image.new("RGB", (1600, 1200), (200, 100, 50)).save(src / "IMG_0001.jpg", exif=exif)
    import docx
    d = docx.Document()
    d.add_paragraph("Der Vertrag zwischen der Firma und dem Kunden ist gültig.")
    d.save(src / "vertrag.docx")


def main():
    srv = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    tmp = Path(tempfile.mkdtemp(prefix="organizer_test_"))
    try:
        cfg = json.loads((ROOT / "file_organizer" / "config.json").read_text(encoding="utf-8"))
        cfg["ollama_url"] = f"http://127.0.0.1:{srv.server_port}"
        cfg_path = tmp / "config.json"
        cfg_path.write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
        src, dst, plan = tmp / "待整理", tmp / "已整理", tmp / "plan.csv"
        make_samples(src)

        print("整理工具：")
        r = run("--config", str(cfg_path), "scan", str(src), "--out", str(plan))
        check(r.returncode == 0, "scan 运行成功")
        rows = list(csv.DictReader(plan.open(encoding="utf-8-sig")))
        by_name = {Path(x["source"]).name: x for x in rows}
        check(len(rows) == 8, f"计划表 8 行（隐藏文件被跳过），实际 {len(rows)}")
        check(by_name["会议.txt"]["category"] == "中文文档", "中文文档只分流")
        check(by_name["copy.txt"]["action"] == "skip" and by_name["copy.txt"]["duplicate_of"], "重复文件标为 skip")
        check(by_name["brief.txt"]["language"] == "德文", "德文识别")
        check(by_name["report.txt"]["language"] == "英文", "英文识别")
        check(by_name["scan_001.pdf"]["category"] == "未识别语言", "读不出文字的文件进“未识别语言”")
        check(by_name["movie.mp4"]["category"] == "音视频", "按扩展名归类")
        check(by_name["IMG_0001.jpg"]["new_name"].startswith("2023-08-15_"), "照片按拍摄日期命名")
        check(by_name["vertrag.docx"]["category"] == "英文德文文档/合同协议", "文件名关键词规则优先")

        r = run("--config", str(cfg_path), "apply", str(plan), "--target", str(dst))
        check(r.returncode == 0 and "已移动 7 + 跳过 1 + 失败 0" in r.stdout, "apply 对账：移动 7、跳过 1")
        check(any((dst / "_归档索引").glob("归档汇总_*.xlsx")), "生成 Excel 归档汇总表")
        r = run("--config", str(cfg_path), "verify", str(dst))
        check("完好 7，不存在 0，内容已变 0" in r.stdout, "verify 全部完好")
        undo = next(tmp.glob("undo_*.csv"))
        r = run("--config", str(cfg_path), "undo", str(undo))
        check("已还原 7 个文件" in r.stdout and (src / "brief.txt").exists(), "undo 全部还原")

        print("文档工具：")
        docs = sorted((ROOT / "docs").glob("*.md")) + [ROOT / "README.md"]
        r = subprocess.run([sys.executable, str(ROOT / "tools" / "md_toc.py"), *map(str, docs), "--check"],
                           capture_output=True, text=True, encoding="utf-8")
        check(r.returncode == 0, "所有文档的目录都是最新的（md_toc.py --check）")
        try:
            import markdown_it  # noqa: F401
        except ImportError:
            print("  跳过  build_html.py（没装 markdown-it-py）")
        else:
            r = subprocess.run([sys.executable, str(ROOT / "tools" / "build_html.py"), *map(str, docs),
                                "-o", str(tmp / "page.html")], capture_output=True, text=True, encoding="utf-8")
            check(r.returncode == 0 and "无遗漏" in r.stdout, "build_html.py 生成网页且核对无遗漏")
    finally:
        srv.shutdown()
        shutil.rmtree(tmp, ignore_errors=True)

    print("\n" + ("全部通过" if not failures else f"{len(failures)} 项失败：" + "；".join(failures)))
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
