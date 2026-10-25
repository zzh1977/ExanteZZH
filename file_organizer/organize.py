#!/usr/bin/env python3
"""离线本地文件整理工具（调用本机 Ollama 模型，不联网）。

三步走，所有改动都可撤销：
  1. scan  : 扫描目录 -> 读取文件内容 -> 本地模型给出分类/新文件名 -> 写入计划表 plan.csv
  2. apply : 人工检查/修改 plan.csv 后，按计划移动（或复制）文件，并生成撤销日志
  3. undo  : 根据撤销日志把文件放回原处

用法示例（Windows PowerShell）：
  python organize.py scan  "D:\\待整理" --out plan.csv
  python organize.py apply plan.csv --target "D:\\已整理"
  python organize.py undo  undo_20261025_103000.csv
"""

import argparse
import csv
import datetime as dt
import hashlib
import json
import os
import re
import shutil
import sys
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
PLAN_FIELDS = ["action", "source", "category", "new_name", "summary", "tags",
               "duplicate_of", "note"]
TEXT_EXTS = {".txt", ".md", ".csv", ".json", ".log", ".ini", ".xml", ".html",
             ".htm", ".yaml", ".yml", ".py", ".js", ".ts", ".java", ".c", ".cpp",
             ".h", ".cs", ".go", ".sql", ".sh", ".bat", ".ps1", ".css", ".rtf"}
CODE_EXTS = {".py", ".js", ".ts", ".java", ".c", ".cpp", ".h", ".cs", ".go",
             ".sql", ".sh", ".bat", ".ps1"}
ILLEGAL_CHARS = re.compile(r'[\\/:*?"<>|\r\n\t]')


# ---------------------------------------------------------------- 配置

def load_config(path):
    with open(path, encoding="utf-8") as f:
        cfg = json.load(f)
    if "其他" not in cfg["categories"]:
        cfg["categories"].append("其他")
    ext_map = {}
    for cat, exts in cfg.get("ext_rules", {}).items():
        for e in exts:
            ext_map[e.lower()] = cat
    cfg["_ext_map"] = ext_map
    cfg["_skip_dirs"] = {d.lower() for d in cfg.get("skip_dirs", [])}
    cfg["_skip_files"] = {f.lower() for f in cfg.get("skip_files", [])}
    return cfg


# ---------------------------------------------------------------- 文本提取

def read_text_file(p, limit):
    raw = p.open("rb").read(limit * 4)
    for enc in ("utf-8-sig", "gb18030", "utf-16"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="ignore")


def extract_text(p, limit):
    """尽量取出文件开头的文字内容；不支持或出错时返回空串。"""
    ext = p.suffix.lower()
    try:
        if ext in TEXT_EXTS:
            return read_text_file(p, limit)[:limit]
        if ext == ".pdf":
            from pypdf import PdfReader
            reader = PdfReader(str(p))
            parts = []
            for page in reader.pages[:5]:
                parts.append(page.extract_text() or "")
                if sum(map(len, parts)) >= limit:
                    break
            return "\n".join(parts)[:limit]
        if ext == ".docx":
            import docx
            d = docx.Document(str(p))
            parts = [para.text for para in d.paragraphs if para.text.strip()]
            for table in d.tables[:3]:
                for row in table.rows[:10]:
                    parts.append(" | ".join(c.text for c in row.cells))
            return "\n".join(parts)[:limit]
        if ext == ".xlsx":
            import openpyxl
            wb = openpyxl.load_workbook(str(p), read_only=True, data_only=True)
            parts = []
            for ws in wb.worksheets[:3]:
                parts.append(f"[工作表] {ws.title}")
                for row in ws.iter_rows(max_row=30, values_only=True):
                    cells = [str(c) for c in row if c is not None]
                    if cells:
                        parts.append(" | ".join(cells))
            wb.close()
            return "\n".join(parts)[:limit]
        if ext == ".pptx":
            from pptx import Presentation
            prs = Presentation(str(p))
            parts = []
            for slide in list(prs.slides)[:15]:
                for shape in slide.shapes:
                    if shape.has_text_frame and shape.text_frame.text.strip():
                        parts.append(shape.text_frame.text)
            return "\n".join(parts)[:limit]
    except ImportError as e:
        print(f"  [提示] 缺少解析库 {e.name}，只按文件名判断: {p.name}")
    except Exception as e:  # 文件损坏/加密等
        print(f"  [提示] 读取内容失败({type(e).__name__})，只按文件名判断: {p.name}")
    return ""


# ---------------------------------------------------------------- 本地模型

def ask_model(cfg, filename, meta, content):
    cats = cfg["categories"]
    schema = {
        "type": "object",
        "properties": {
            "category": {"type": "string", "enum": cats},
            "title": {"type": "string"},
            "summary": {"type": "string"},
            "tags": {"type": "array", "items": {"type": "string"}},
            "date": {"type": "string"},
        },
        "required": ["category", "title", "summary", "tags", "date"],
    }
    prompt = (
        "你是文件整理助手。根据下面的文件信息，完成：\n"
        f"1. category：从这些类别中选一个最合适的：{'、'.join(cats)}。拿不准就选“其他”。\n"
        "2. title：给文件起一个简短、准确的中文标题（不超过20字，不要扩展名，不要日期）。\n"
        "3. summary：一句话概括内容（不超过40字）。\n"
        "4. tags：1到3个关键词。\n"
        "5. date：如果内容中能看出文件对应的日期，写成 YYYY-MM-DD，否则留空字符串。\n"
        "只输出 JSON。\n\n"
        f"文件名：{filename}\n{meta}\n"
        f"文件内容（开头部分）：\n{content if content.strip() else '（无法读取内容，请仅根据文件名判断）'}"
    )
    body = {
        "model": cfg["model"],
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "format": schema,
        "options": {"temperature": 0, "num_ctx": cfg["num_ctx"]},
    }
    if "qwen3" in cfg["model"].lower():
        body["think"] = False  # 关闭思考模式，速度快很多

    def post(b):
        req = urllib.request.Request(
            cfg["ollama_url"].rstrip("/") + "/api/chat",
            data=json.dumps(b).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=cfg["request_timeout"]) as r:
            return json.loads(r.read().decode("utf-8"))

    try:
        resp = post(body)
    except urllib.error.HTTPError:
        if "think" not in body:
            raise
        body.pop("think")  # 旧版 Ollama 不认识 think 参数时重试
        resp = post(body)
    data = json.loads(resp["message"]["content"])
    if data.get("category") not in cats:
        data["category"] = "其他"
    return data


def check_ollama(cfg):
    url = cfg["ollama_url"].rstrip("/") + "/api/tags"
    try:
        with urllib.request.urlopen(url, timeout=5) as r:
            models = [m["name"] for m in json.loads(r.read())["models"]]
    except Exception:
        sys.exit(f"连不上 Ollama（{cfg['ollama_url']}）。请先启动 Ollama 再运行。")
    want = cfg["model"] if ":" in cfg["model"] else cfg["model"] + ":latest"
    if want not in models:
        sys.exit(f"本机没有模型 {cfg['model']}。已有模型：{', '.join(models) or '无'}")


# ---------------------------------------------------------------- 工具函数

def clean_name(s, max_len):
    s = ILLEGAL_CHARS.sub("_", s or "").strip().strip("._ ")
    s = re.sub(r"\s+", " ", s)
    return s[:max_len] or "未命名"


def file_hash(p):
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def iter_files(root, cfg):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames
                       if d.lower() not in cfg["_skip_dirs"] and not d.startswith(".")]
        for name in filenames:
            if name.lower() in cfg["_skip_files"] or name.startswith("~$"):
                continue
            yield Path(dirpath) / name


def unique_path(p):
    if not p.exists():
        return p
    i = 1
    while True:
        cand = p.with_name(f"{p.stem}({i}){p.suffix}")
        if not cand.exists():
            return cand
        i += 1


def valid_date(s):
    try:
        dt.date.fromisoformat((s or "").strip())
        return s.strip()
    except ValueError:
        return ""


# ---------------------------------------------------------------- 命令：scan

def cmd_scan(args, cfg):
    root = Path(args.folder).resolve()
    if not root.is_dir():
        sys.exit(f"目录不存在：{root}")
    out = Path(args.out)
    if not args.no_llm:
        check_ollama(cfg)

    done = set()
    seen_hash = {}
    if out.exists():  # 断点续跑：已处理的文件跳过
        with out.open(encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f):
                done.add(row["source"])
        print(f"发现已有计划表，跳过已处理的 {len(done)} 个文件。")

    files = [p for p in iter_files(root, cfg) if str(p) not in done]
    print(f"待处理 {len(files)} 个文件，模型：{cfg['model']}")
    new_file = not out.exists()
    with out.open("a", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=PLAN_FIELDS)
        if new_file:
            w.writeheader()
        for i, p in enumerate(files, 1):
            row = scan_one(p, cfg, seen_hash, args.no_llm)
            w.writerow(row)
            f.flush()
            print(f"[{i}/{len(files)}] {p.name} -> {row['category']}/{row['new_name']}")
    print(f"\n完成。请用 Excel 打开检查：{out.resolve()}")
    print("  action 列：move=整理，skip=不动。可直接修改 category / new_name。")


def scan_one(p, cfg, seen_hash, no_llm):
    row = dict.fromkeys(PLAN_FIELDS, "")
    row["source"] = str(p)
    row["action"] = "move"
    ext = p.suffix.lower()
    try:
        st = p.stat()
        digest = file_hash(p)
    except OSError as e:
        row.update(action="skip", category="其他", new_name=p.name, note=f"无法读取: {e}")
        return row

    if digest in seen_hash:
        row.update(action="skip", category="重复文件", new_name=p.name,
                   duplicate_of=seen_hash[digest], note="内容与另一文件完全相同")
        return row
    seen_hash[digest] = str(p)

    mdate = dt.date.fromtimestamp(st.st_mtime).isoformat()
    title, date = p.stem, mdate

    if ext in cfg["_ext_map"]:  # 图片/视频/安装包等按扩展名直接分类，不调用模型
        row["category"] = cfg["_ext_map"][ext]
    elif no_llm:
        row["category"] = "代码脚本" if ext in CODE_EXTS else "其他"
    else:
        content = extract_text(p, cfg["max_chars"])
        meta = f"扩展名：{ext or '无'}  大小：{st.st_size // 1024} KB  修改日期：{mdate}"
        try:
            ans = ask_model(cfg, p.name, meta, content)
            row["category"] = ans["category"]
            row["summary"] = ans.get("summary", "")
            row["tags"] = "、".join(ans.get("tags", [])[:3])
            title = ans.get("title") or p.stem
            date = valid_date(ans.get("date")) or mdate
        except Exception as e:
            row.update(category="其他", note=f"模型调用失败: {type(e).__name__}")

    stem = cfg["name_template"].format(date=date, title=clean_name(title, cfg["max_name_len"]))
    row["new_name"] = clean_name(stem, cfg["max_name_len"] + 12) + ext
    return row


# ---------------------------------------------------------------- 命令：apply / undo

def cmd_apply(args, cfg):
    target = Path(args.target).resolve()
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    undo_path = Path(args.plan).resolve().parent / f"undo_{stamp}.csv"
    op = shutil.copy2 if args.copy else shutil.move
    moved = skipped = failed = 0

    with open(args.plan, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    with undo_path.open("w", encoding="utf-8-sig", newline="") as uf:
        uw = csv.writer(uf)
        uw.writerow(["new_path", "original_path", "mode"])
        for row in rows:
            if row["action"].strip().lower() != "move":
                skipped += 1
                continue
            src = Path(row["source"])
            if not src.exists():
                print(f"  [跳过] 源文件不存在：{src}")
                failed += 1
                continue
            cat = clean_name(row["category"], 40)
            name = clean_name(row["new_name"], 120)
            if not Path(name).suffix and src.suffix:
                name += src.suffix
            dest = unique_path(target / cat / name)
            if args.dry_run:
                print(f"  [预览] {src}  ->  {dest}")
                moved += 1
                continue
            try:
                dest.parent.mkdir(parents=True, exist_ok=True)
                op(str(src), str(dest))
                uw.writerow([str(dest), str(src), "copy" if args.copy else "move"])
                uf.flush()
                moved += 1
            except OSError as e:
                print(f"  [失败] {src}: {e}")
                failed += 1

    verb = "预览" if args.dry_run else ("复制" if args.copy else "移动")
    print(f"\n{verb} {moved} 个，跳过 {skipped} 个，失败 {failed} 个。")
    if args.dry_run:
        undo_path.unlink()
    else:
        print(f"撤销日志：{undo_path}\n如需还原：python organize.py undo \"{undo_path}\"")


def cmd_undo(args, cfg):
    with open(args.log, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    ok = 0
    for row in reversed(rows):
        new, orig = Path(row["new_path"]), Path(row["original_path"])
        if not new.exists():
            print(f"  [跳过] 已不存在：{new}")
            continue
        if row.get("mode") == "copy":
            new.unlink()  # 复制模式：原文件还在，只删副本
        else:
            orig.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(new), str(unique_path(orig)))
        ok += 1
    print(f"已还原 {ok} 个文件。（整理后产生的空文件夹可手动删除）")


# ---------------------------------------------------------------- 入口

def main():
    ap = argparse.ArgumentParser(description="离线本地文件整理（Ollama）")
    ap.add_argument("--config", default=str(HERE / "config.json"), help="配置文件路径")
    ap.add_argument("--model", help="临时指定模型，如 qwen3:4b")
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("scan", help="扫描并生成整理计划（不动任何文件）")
    s.add_argument("folder")
    s.add_argument("--out", default="plan.csv")
    s.add_argument("--no-llm", action="store_true", help="不用模型，只按扩展名分类+查重")

    a = sub.add_parser("apply", help="按计划表整理文件")
    a.add_argument("plan")
    a.add_argument("--target", required=True, help="整理后的目标目录")
    a.add_argument("--copy", action="store_true", help="复制而不是移动（更保险）")
    a.add_argument("--dry-run", action="store_true", help="只预览，不动文件")

    u = sub.add_parser("undo", help="按撤销日志还原")
    u.add_argument("log")

    args = ap.parse_args()
    cfg = load_config(args.config)
    if args.model:
        cfg["model"] = args.model
    {"scan": cmd_scan, "apply": cmd_apply, "undo": cmd_undo}[args.cmd](args, cfg)


if __name__ == "__main__":
    main()
