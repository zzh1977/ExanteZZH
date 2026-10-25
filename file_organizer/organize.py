#!/usr/bin/env python3
"""离线本地文件整理工具（调用本机 Ollama 模型，不联网）。

模型只负责“给建议”，所有文件操作由本程序按固定规则完成，保证不丢文件：
  1. scan   : 扫描目录 -> 读取内容 -> 本地模型给出分类/新文件名 -> 写入计划表 plan.csv（不动文件）
  2. apply  : 人工检查 plan.csv 后执行。每个文件先复制、核对 SHA-256 一致后才删除原文件；
              生成撤销日志、归档清单（CSV）和归档汇总表（Excel），最后对账
  3. verify : 按归档清单重新核对每个归档文件是否存在、内容是否完好
  4. undo   : 根据撤销日志把文件放回原处

用法示例（Windows PowerShell）：
  python organize.py scan   "D:\\待整理" --out plan.csv
  python organize.py apply  plan.csv --target "D:\\已整理"
  python organize.py verify "D:\\已整理\\_归档索引\\归档清单_20261025_103000.csv"
  python organize.py undo   undo_20261025_103000.csv
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
               "confidence", "duplicate_of", "note", "sha256"]
INDEX_DIR = "_归档索引"
INDEX_FIELDS = ["类别", "归档路径", "原路径", "摘要", "标签", "大小KB", "SHA256", "归档时间"]
REVIEW_NOTE = "建议人工确认"
UNDO_LOG = re.compile(r"^undo_\d{8}_\d{6}\.csv$")
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
    cfg["_kw_rules"] = [(kw.lower(), cat) for cat, kws in cfg.get("keyword_rules", {}).items()
                        for kw in kws]
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
            "confidence": {"type": "string", "enum": ["高", "中", "低"]},
        },
        "required": ["category", "title", "summary", "tags", "date", "confidence"],
    }
    prompt = (
        "你是文件整理助手。根据下面的文件信息，完成：\n"
        f"1. category：从这些类别中选一个最合适的：{'、'.join(cats)}。拿不准就选“其他”。\n"
        "2. title：给文件起一个简短、准确的中文标题（不超过20字，不要扩展名，不要日期）。\n"
        "3. summary：一句话概括内容（不超过40字）。\n"
        "4. tags：1到3个关键词。\n"
        "5. date：如果内容中能看出文件对应的日期，写成 YYYY-MM-DD，否则留空字符串。\n"
        "6. confidence：你对类别判断的把握，高/中/低。内容读不到或模棱两可时填“低”。\n"
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
        dirnames[:] = [d for d in dirnames if d.lower() not in cfg["_skip_dirs"]
                       and not d.startswith(".") and d != INDEX_DIR]
        for name in filenames:
            if (name.lower() in cfg["_skip_files"] or name.startswith("~$")
                    or name.endswith(".part") or UNDO_LOG.match(name)):
                continue
            p = Path(dirpath) / name
            if str(p) not in cfg.get("_exclude", ()):
                yield p


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
    cfg["_exclude"] = {str(out.resolve())}  # 计划表放在待整理目录里时，不扫描它自己
    if not args.no_llm:
        check_ollama(cfg)

    done = set()
    seen_hash = {}
    if out.exists():  # 断点续跑：已处理的文件跳过，查重记录也接上
        with out.open(encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f):
                done.add(row["source"])
                if row.get("sha256") and not row.get("duplicate_of"):
                    seen_hash.setdefault(row["sha256"], row["source"])
        print(f"发现已有计划表，跳过已处理的 {len(done)} 个文件。")

    files = [p for p in iter_files(root, cfg) if str(p) not in done]
    print(f"待处理 {len(files)} 个文件，模型：{'不使用' if args.no_llm else cfg['model']}")
    new_file = not out.exists()
    with out.open("a", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=PLAN_FIELDS)
        if new_file:
            w.writeheader()
        for i, p in enumerate(files, 1):
            row = scan_one(p, cfg, seen_hash, args.no_llm)
            w.writerow(row)
            f.flush()
            flag = "  ⚠" + REVIEW_NOTE if REVIEW_NOTE in row["note"] else ""
            print(f"[{i}/{len(files)}] {p.name} -> {row['category']}/{row['new_name']}{flag}")

    # 扫描汇总：计划表行数必须等于目录里的文件数，一个都不能漏
    with out.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    total_now = sum(1 for _ in iter_files(root, cfg))
    in_plan = {r["source"] for r in rows}
    missing = [str(p) for p in iter_files(root, cfg) if str(p) not in in_plan]
    counts = {}
    for r in rows:
        counts[r["category"]] = counts.get(r["category"], 0) + 1
    print(f"\n===== 扫描汇总 =====\n目录中文件 {total_now} 个，计划表 {len(rows)} 行。")
    for cat, n in sorted(counts.items(), key=lambda x: -x[1]):
        print(f"  {cat:<8} {n}")
    print(f"  需人工确认 {sum(REVIEW_NOTE in r['note'] for r in rows)} 个，"
          f"重复文件 {sum(bool(r['duplicate_of']) for r in rows)} 个（默认不动）")
    if missing:
        print(f"[注意] 有 {len(missing)} 个文件不在计划表中（可能是扫描途中新增的），再运行一次 scan 即可补上。")
    print(f"\n请用 Excel 打开检查：{out.resolve()}")
    print("  action 列：move=整理，skip=不动。可直接修改 category / new_name。")
    print("  建议优先看 note 列标了“建议人工确认”的行。")


def match_keyword(name, cfg):
    low = name.lower()
    for kw, cat in cfg["_kw_rules"]:
        if kw in low:
            return cat
    return ""


def scan_one(p, cfg, seen_hash, no_llm):
    row = dict.fromkeys(PLAN_FIELDS, "")
    row["source"] = str(p)
    row["action"] = "move"
    ext = p.suffix.lower()
    try:
        st = p.stat()
        digest = file_hash(p)
    except OSError as e:
        row.update(action="skip", category="其他", new_name=p.name, note=f"无法读取，未处理: {e}")
        return row
    row["sha256"] = digest

    if digest in seen_hash:
        row.update(action="skip", category="重复文件", new_name=p.name,
                   duplicate_of=seen_hash[digest], note="内容与另一文件完全相同，默认不动")
        return row
    seen_hash[digest] = str(p)

    mdate = dt.date.fromtimestamp(st.st_mtime).isoformat()
    title, date = p.stem, mdate
    kw_cat = match_keyword(p.name, cfg)

    if ext in cfg["_ext_map"]:  # 图片/视频/安装包等按扩展名直接分类，不调用模型
        row.update(category=cfg["_ext_map"][ext], confidence="规则")
    elif no_llm:
        cat = kw_cat or ("代码脚本" if ext in CODE_EXTS else "")
        row.update(category=cat or "其他", confidence="规则" if cat else "低")
    else:
        content = extract_text(p, cfg["max_chars"])
        meta = f"扩展名：{ext or '无'}  大小：{st.st_size // 1024} KB  修改日期：{mdate}"
        try:
            ans = ask_model(cfg, p.name, meta, content)
            row["category"] = ans["category"]
            row["confidence"] = ans.get("confidence", "")
            row["summary"] = ans.get("summary", "")
            row["tags"] = "、".join(ans.get("tags", [])[:3])
            title = ans.get("title") or p.stem
            date = valid_date(ans.get("date")) or mdate
        except Exception as e:
            row.update(category="其他", confidence="低", note=f"模型调用失败: {type(e).__name__}")
        if kw_cat and kw_cat != row["category"]:  # 文件名关键词规则优先于模型
            row["note"] = (row["note"] + f" 模型判为{row['category']}，按关键词规则改为{kw_cat}").strip()
            row.update(category=kw_cat, confidence="规则")
        if not content.strip() and row["confidence"] != "规则":
            row["note"] = (row["note"] + " 未读到内容，仅按文件名判断").strip()
            row["confidence"] = "低"

    if row["category"] == "其他" or row["confidence"] == "低":
        row["note"] = (row["note"] + " " + REVIEW_NOTE).strip()

    stem = cfg["name_template"].format(date=date, title=clean_name(title, cfg["max_name_len"]))
    row["new_name"] = clean_name(stem, cfg["max_name_len"] + 12) + ext
    return row


# ---------------------------------------------------------------- 命令：apply / verify / undo

def safe_transfer(src, dest, copy_only):
    """把 src 放到 dest，并核对内容一致。返回文件的 SHA-256。

    - 同一磁盘移动：直接改名（不复制数据，瞬间完成，不会出现半个文件）。
    - 跨磁盘移动 / 复制：先复制成 .part 临时文件 -> 核对 SHA-256 -> 改成正式名
      -> （移动模式）最后才删除原文件。任何一步出错，原文件都保持不动。
    """
    before = file_hash(src)
    dest.parent.mkdir(parents=True, exist_ok=True)
    if not copy_only:
        try:
            os.rename(src, dest)
        except OSError:
            pass  # 跨磁盘等情况，改用“复制-核对-删除”
        else:
            if file_hash(dest) != before:
                raise OSError("改名后内容校验不一致（文件仍在目标位置，请检查）")
            return before
    tmp = dest.with_name(dest.name + ".part")
    try:
        shutil.copy2(src, tmp)
        if file_hash(tmp) != before:
            raise OSError("复制后内容校验不一致，已放弃，原文件未动")
        os.rename(tmp, dest)
    except BaseException:
        if tmp.exists():
            tmp.unlink()
        raise
    if not copy_only:
        os.remove(src)
    return before


def write_index(target, stamp, archived, problems):
    """写归档清单（本次 + 累计总索引）和 Excel 汇总表。"""
    idx_dir = target / INDEX_DIR
    idx_dir.mkdir(parents=True, exist_ok=True)
    run_csv = idx_dir / f"归档清单_{stamp}.csv"
    with run_csv.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=INDEX_FIELDS)
        w.writeheader()
        w.writerows(archived)
    master = idx_dir / "归档总索引.csv"
    new_master = not master.exists()
    with master.open("a", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=INDEX_FIELDS)
        if new_master:
            w.writeheader()
        w.writerows(archived)

    summary = {}
    for r in archived:
        n, kb = summary.get(r["类别"], (0, 0))
        summary[r["类别"]] = (n + 1, kb + int(r["大小KB"]))
    xlsx = idx_dir / f"归档汇总_{stamp}.xlsx"
    try:
        import openpyxl
        from openpyxl.styles import Font
    except ImportError:
        print("  [提示] 未安装 openpyxl，跳过 Excel 汇总表（CSV 清单已生成）")
        return run_csv, None
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "汇总"
    ws.append(["类别", "文件数", "总大小(MB)"])
    for cat, (n, kb) in sorted(summary.items(), key=lambda x: -x[1][0]):
        ws.append([cat, n, round(kb / 1024, 2)])
    ws.append(["合计", len(archived), round(sum(kb for _, kb in summary.values()) / 1024, 2)])
    ws2 = wb.create_sheet("明细")
    ws2.append(INDEX_FIELDS)
    for r in archived:
        ws2.append([r[k] for k in INDEX_FIELDS])
    ws3 = wb.create_sheet("未归档")
    ws3.append(["原路径", "原因"])
    for p in problems:
        ws3.append(p)
    for sheet in (ws, ws2, ws3):
        for c in sheet[1]:
            c.font = Font(bold=True)
        sheet.freeze_panes = "A2"
        for col in sheet.columns:
            width = max(len(str(c.value or "")) for c in col[:200])
            sheet.column_dimensions[col[0].column_letter].width = min(max(width * 1.6, 8), 80)
    wb.save(xlsx)
    return run_csv, xlsx


def cmd_apply(args, cfg):
    target = Path(args.target).resolve()
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    undo_path = Path(args.plan).resolve().parent / f"undo_{stamp}.csv"
    with open(args.plan, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))

    archived, problems, skipped = [], [], 0
    uf = None if args.dry_run else undo_path.open("w", encoding="utf-8-sig", newline="")
    try:
        if uf:
            uw = csv.writer(uf)
            uw.writerow(["new_path", "original_path", "mode", "sha256"])
        for row in rows:
            src = Path(row["source"])
            if row["action"].strip().lower() != "move":
                skipped += 1
                problems.append([str(src), "计划中标为 skip：" + (row.get("note") or "")])
                continue
            if not src.exists():
                print(f"  [跳过] 源文件不存在：{src}")
                problems.append([str(src), "源文件不存在（可能已被移走）"])
                continue
            cat = clean_name(row["category"], 40)
            name = clean_name(row["new_name"], 120)
            if not Path(name).suffix and src.suffix:
                name += src.suffix
            dest = unique_path(target / cat / name)
            if args.dry_run:
                print(f"  [预览] {src}  ->  {dest}")
                archived.append(None)
                continue
            try:
                size_kb = src.stat().st_size // 1024
                digest = safe_transfer(src, dest, args.copy)
            except OSError as e:
                print(f"  [失败，原文件未动] {src}: {e}")
                problems.append([str(src), f"处理失败，原文件未动：{e}"])
                continue
            uw.writerow([str(dest), str(src), "copy" if args.copy else "move", digest])
            uf.flush()
            archived.append({
                "类别": cat, "归档路径": str(dest), "原路径": str(src),
                "摘要": row.get("summary", ""), "标签": row.get("tags", ""),
                "大小KB": size_kb, "SHA256": digest,
                "归档时间": dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            })
    finally:
        if uf:
            uf.close()

    failed = len(problems) - skipped
    verb = "预览" if args.dry_run else ("复制" if args.copy else "移动")
    print(f"\n===== 对账 =====")
    print(f"计划表 {len(rows)} 个 = 已{verb} {len(archived)} + 跳过 {skipped} + 失败 {failed}")
    if len(rows) != len(archived) + skipped + failed:  # 理论上不会发生
        print("[警告] 对账不平，请保留 plan.csv 和 undo 日志并人工检查！")
    if failed:
        print(f"失败的 {failed} 个文件仍在原位置，没有丢失，详见汇总表“未归档”页。")
    if args.dry_run:
        return
    if not archived:
        undo_path.unlink()
        return
    run_csv, xlsx = write_index(target, stamp, archived, problems)
    print(f"归档清单：{run_csv}")
    if xlsx:
        print(f"归档汇总表：{xlsx}")
    print(f"撤销日志：{undo_path}")
    print(f"核对归档：python organize.py verify \"{run_csv}\"")
    print(f"如需还原：python organize.py undo \"{undo_path}\"")


def cmd_verify(args, cfg):
    path = Path(args.index)
    if path.is_dir():  # 传入整理目录时，核对累计总索引
        path = path / INDEX_DIR / "归档总索引.csv"
    with path.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    ok, missing, changed = 0, [], []
    for i, r in enumerate(rows, 1):
        p = Path(r["归档路径"])
        if not p.exists():
            missing.append(r)
        elif file_hash(p) != r["SHA256"]:
            changed.append(r)
        else:
            ok += 1
        if i % 200 == 0:
            print(f"  已核对 {i}/{len(rows)} ...")
    print(f"\n===== 核对结果 =====\n清单 {len(rows)} 个：完好 {ok}，不存在 {len(missing)}，内容已变 {len(changed)}")
    for r in missing:
        print(f"  [不存在] {r['归档路径']}（原路径 {r['原路径']}）")
    for r in changed:
        print(f"  [内容已变] {r['归档路径']}（归档后被修改过，或磁盘出错）")
    if not missing and not changed:
        print("全部完好。")
    print("（执行过 undo 或之后自己挪动过文件，也会显示为“不存在”。）")


def cmd_undo(args, cfg):
    with open(args.log, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    ok = kept = 0
    for row in reversed(rows):
        new, orig = Path(row["new_path"]), Path(row["original_path"])
        if not new.exists():
            print(f"  [跳过] 已不存在：{new}")
            continue
        try:
            if row.get("mode") == "copy":
                # 复制模式：只有原文件还在、且副本没被改过，才删除副本
                if orig.exists() and file_hash(new) == file_hash(orig):
                    new.unlink()
                else:
                    print(f"  [保留] 副本与原文件不一致或原文件不在，未删除：{new}")
                    kept += 1
                    continue
            else:
                safe_transfer(new, unique_path(orig), copy_only=False)
        except OSError as e:
            print(f"  [失败，文件未动] {new}: {e}")
            kept += 1
            continue
        ok += 1
    print(f"已还原 {ok} 个文件，保留 {kept} 个。（整理后产生的空文件夹可手动删除）")


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

    v = sub.add_parser("verify", help="按归档清单核对文件是否完好")
    v.add_argument("index", help="归档清单 CSV，或整理后的目标目录（核对累计总索引）")

    u = sub.add_parser("undo", help="按撤销日志还原")
    u.add_argument("log")

    args = ap.parse_args()
    cfg = load_config(args.config)
    if args.model:
        cfg["model"] = args.model
    {"scan": cmd_scan, "apply": cmd_apply, "verify": cmd_verify, "undo": cmd_undo}[args.cmd](args, cfg)


if __name__ == "__main__":
    main()
