#!/usr/bin/env python3
"""离线本地文件整理工具（调用本机 Ollama 模型，不联网）。

先分流，再分别处理（每类文件可用不同的模型）：
  - 照片           -> 看图模型（默认 qwen3-vl:4b）按画面分类
  - 中文文档       -> 默认只单独分出来，不读内容、不调用模型（可在 config.json 里给它配 Qwen 再细分）
  - 英文/德文文档  -> 英德文模型（默认 llama3.1:8b）读内容分类
  - 音视频/安装包/压缩包/代码等 -> 按扩展名直接分，不用模型
  - 认不出语言的文档 -> 单独放一个文件夹，等人工处理
分流（判断是否中文、是否照片）由程序按字符和扩展名完成，不用模型，又快又稳定。

模型只负责“给建议”，所有文件操作由本程序按固定规则完成，保证不丢文件：
  1. scan   : 扫描 -> 分流 -> 按类别分批调用对应模型 -> 写入计划表 plan.csv（不动文件）
  2. apply  : 人工检查 plan.csv 后执行。每个文件先复制、核对 SHA-256 一致后才删除原文件；
              生成撤销日志、归档清单（CSV）和归档汇总表（Excel），最后对账
  3. verify : 按归档清单重新核对每个归档文件是否存在、内容是否完好
  4. undo   : 根据撤销日志把文件放回原处

用法示例（Windows PowerShell）：
  python organize.py scan   "D:\\待整理" --out plan.csv
  python organize.py apply  plan.csv --target "D:\\已整理"
  python organize.py verify "D:\\已整理"
  python organize.py undo   undo_20261025_103000.csv
"""

import argparse
import base64
import csv
import datetime as dt
import hashlib
import io
import json
import os
import re
import shutil
import sys
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
PLAN_FIELDS = ["action", "source", "language", "category", "new_name", "summary", "tags",
               "confidence", "duplicate_of", "note", "sha256"]
INDEX_DIR = "_归档索引"
INDEX_FIELDS = ["类别", "语言", "归档路径", "原路径", "摘要", "标签", "大小KB", "SHA256", "归档时间"]
REVIEW_NOTE = "建议人工确认"
UNDO_LOG = re.compile(r"^undo_\d{8}_\d{6}\.csv$")
TEXT_EXTS = {".txt", ".md", ".csv", ".json", ".log", ".ini", ".xml", ".html",
             ".htm", ".yaml", ".yml", ".py", ".js", ".ts", ".java", ".c", ".cpp",
             ".h", ".cs", ".go", ".sql", ".sh", ".bat", ".ps1", ".css", ".rtf"}
ILLEGAL_CHARS = re.compile(r'[\\/:*?"<>|\r\n\t]')

LANG_NAMES = {"zh": "中文", "en": "英文", "de": "德文", "latin": "英/德",
              "unknown": "未知", "photo": "照片", "-": "-"}
ROUTE_ORDER = ["en_de", "zh", "photo"]  # 分批处理顺序：同一模型的文件集中处理，避免反复切换模型

CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]")
WORD_RE = re.compile(r"[A-Za-zÄÖÜäöüß]+")
UMLAUT_RE = re.compile(r"[äöüßÄÖÜ]")
EN_WORDS = set("the and of to in is that for with on are this be as by from at or you "
               "your we our it not have has will was were which please dear regards".split())
DE_WORDS = set("der die das und ist nicht mit von zu den dem ein eine einen für auf sich des "
               "im auch wir sie bei oder werden wird sind ihr ihre uns zur zum nach über "
               "sehr geehrte geehrter herr frau mit freundlichen grüßen".split())


# ---------------------------------------------------------------- 配置

def load_config(path):
    try:
        with open(path, encoding="utf-8-sig") as f:
            cfg = json.load(f)
    except FileNotFoundError:
        sys.exit(f"找不到配置文件：{path}")
    except UnicodeDecodeError:
        sys.exit(f"配置文件 {path} 不是 UTF-8 编码。请用记事本打开，另存为时“编码”选 UTF-8。")
    except json.JSONDecodeError as e:
        sys.exit(f"配置文件 {path} 格式有误：第 {e.lineno} 行第 {e.colno} 个字符附近（{e.msg}）。\n"
                 "常见原因：少了逗号、多了逗号、引号用成了中文引号。")
    for key, r in cfg["routes"].items():
        r.setdefault("model", "")
        cats = r.setdefault("categories", {})
        if isinstance(cats, list):
            r["categories"] = cats = {c: "" for c in cats}
        if cats and key != "photo" and "其他" not in cats:
            cats["其他"] = ""
    ext_map = {}
    for cat, exts in cfg.get("ext_rules", {}).items():
        for e in exts:
            ext_map[e.lower()] = cat
    cfg["_ext_map"] = ext_map
    cfg["_photo_exts"] = {e.lower() for e in cfg.get("photo_exts", [])}
    cfg["_kw_rules"] = [(kw.lower(), cat) for cat, kws in cfg.get("keyword_rules", {}).items()
                        for kw in kws]
    cfg["_skip_dirs"] = {d.lower() for d in cfg.get("skip_dirs", [])}
    cfg["_skip_files"] = {f.lower() for f in cfg.get("skip_files", [])}
    return cfg


# ---------------------------------------------------------------- 语言判断（不用模型）

def detect_language(stem, text):
    """按字符统计判断语言：zh / en / de / latin（英德之一，分不清）/ unknown。

    先看内容开头，内容读不到或太少再看文件名。只数字符，不理解内容。
    """
    for sample, min_cjk, min_hits in ((text or "", 5, 2), (stem, 1, 1)):
        cjk = len(CJK_RE.findall(sample))
        words = [w.lower() for w in WORD_RE.findall(sample)]
        if cjk >= min_cjk and cjk >= len(words) * 0.5:
            return "zh"
        de = sum(w in DE_WORDS for w in words) + len(UMLAUT_RE.findall(sample))
        en = sum(w in EN_WORDS for w in words)
        if max(de, en) >= min_hits:
            return "de" if de > en else "en"
        if len(words) >= 3:
            return "latin"
    return "unknown"  # 读不到内容、文件名也看不出来：不猜，交给人工


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

def call_ollama(cfg, model, prompt, schema, images=None):
    msg = {"role": "user", "content": prompt}
    if images:
        msg["images"] = images
    body = {
        "model": model,
        "messages": [msg],
        "stream": False,
        "format": schema,
        "options": {"temperature": 0, "num_ctx": cfg["num_ctx"]},
    }
    if "qwen3" in model.lower():
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
        body.pop("think")  # 模型或旧版 Ollama 不支持 think 参数时重试
        resp = post(body)
    return json.loads(resp["message"]["content"])


def check_models(cfg, models):
    url = cfg["ollama_url"].rstrip("/") + "/api/tags"
    try:
        with urllib.request.urlopen(url, timeout=5) as r:
            have = [m["name"] for m in json.loads(r.read())["models"]]
    except Exception:
        sys.exit(f"连不上 Ollama（{cfg['ollama_url']}）。请先启动 Ollama 再运行。")
    lacking = [m for m in models if (m if ":" in m else m + ":latest") not in have]
    if lacking:
        sys.exit(f"本机缺少模型：{', '.join(lacking)}\n已有模型：{', '.join(have) or '无'}\n"
                 "请导入缺少的模型，或在 config.json 的 routes 里把对应 model 改成已有模型（留空=不用模型）。")


def doc_schema(cats, with_lang):
    props = {
        "category": {"type": "string", "enum": list(cats)},
        "title": {"type": "string"},
        "summary": {"type": "string"},
        "tags": {"type": "array", "items": {"type": "string"}},
        "date": {"type": "string"},
        "confidence": {"type": "string", "enum": ["高", "中", "低"]},
    }
    if with_lang:
        props["language"] = {"type": "string", "enum": ["en", "de"]}
    return {"type": "object", "properties": props, "required": list(props)}


def ask_zh(cfg, route, filename, meta, content):
    cats = route["categories"]
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
    return call_ollama(cfg, route["model"], prompt, doc_schema(cats, False))


def ask_en_de(cfg, route, filename, meta, content):
    cats = route["categories"]
    cat_lines = "\n".join(f"   - {k}  ({v})" if v else f"   - {k}" for k, v in cats.items())
    prompt = (
        "You are a file organizing assistant. The document below is written in English or German.\n"
        "Return JSON with these fields:\n"
        "1. category: exactly one folder name from this list (the meaning is in brackets). "
        "If unsure, choose 其他.\n"
        f"{cat_lines}\n"
        "2. language: \"en\" for English, \"de\" for German.\n"
        "3. title: a short, precise title in the document's own language "
        "(max 8 words, no date, no file extension).\n"
        "4. summary: one sentence in Simplified Chinese (简体中文, max 40 characters).\n"
        "5. tags: 1 to 3 keywords in the document's own language.\n"
        "6. date: the document's date as YYYY-MM-DD if it is visible in the content, otherwise \"\".\n"
        "7. confidence: 高 (high), 中 (medium) or 低 (low). Use 低 if the content is missing or ambiguous.\n\n"
        f"File name: {filename}\n{meta}\n"
        f"Content (beginning):\n{content if content.strip() else '(content not readable, judge by file name only)'}"
    )
    return call_ollama(cfg, route["model"], prompt, doc_schema(cats, True))


def ask_photo(cfg, route, image_b64):
    cats = route["categories"]
    schema = {
        "type": "object",
        "properties": {
            "category": {"type": "string", "enum": list(cats)},
            "title": {"type": "string"},
            "summary": {"type": "string"},
            "tags": {"type": "array", "items": {"type": "string"}},
            "confidence": {"type": "string", "enum": ["高", "中", "低"]},
        },
        "required": ["category", "title", "summary", "tags", "confidence"],
    }
    prompt = (
        "请看这张照片，完成：\n"
        f"1. category：从这些类别中选一个最合适的：{'、'.join(cats)}。拿不准就选“{list(cats)[-1]}”。\n"
        "2. title：用中文简短描述画面（不超过12字），用作文件名。\n"
        "3. summary：一句话描述画面内容（不超过40字）。\n"
        "4. tags：1到3个关键词。\n"
        "5. confidence：你对类别判断的把握，高/中/低。\n"
        "只输出 JSON。"
    )
    return call_ollama(cfg, route["model"], prompt, schema, images=[image_b64])


# ---------------------------------------------------------------- 照片

def _pil():
    try:
        from PIL import Image, ImageOps
    except ImportError:
        return None, None
    try:  # 苹果手机的 HEIC 照片（装了 pillow-heif 才支持）
        from pillow_heif import register_heif_opener
        register_heif_opener()
    except ImportError:
        pass
    return Image, ImageOps


def load_photo(p, max_side):
    """缩小后转成 JPEG 的 base64（大图直接送模型会很慢、很占内存）。读不了返回 None。"""
    Image, ImageOps = _pil()
    if Image is None:
        if p.suffix.lower() in {".jpg", ".jpeg", ".png"}:
            return base64.b64encode(p.read_bytes()).decode()
        return None
    try:
        with Image.open(p) as im:
            im = ImageOps.exif_transpose(im)
            im.thumbnail((max_side, max_side))
            buf = io.BytesIO()
            im.convert("RGB").save(buf, "JPEG", quality=85)
        return base64.b64encode(buf.getvalue()).decode()
    except Exception:
        return None


def photo_date(p):
    """读取照片的拍摄日期（EXIF），读不到返回空串。"""
    Image, _ = _pil()
    if Image is None:
        return ""
    try:
        with Image.open(p) as im:
            exif = im.getexif()
            v = exif.get_ifd(0x8769).get(36867) or exif.get(306) or ""
        return valid_date(str(v)[:10].replace(":", "-"))
    except Exception:
        return ""


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


def read_csv(path, need=()):
    """读 CSV。兼容 Excel 另存为“CSV（逗号分隔）”时的 GBK 编码。"""
    try:
        raw = Path(path).read_bytes()
    except FileNotFoundError:
        sys.exit(f"找不到文件：{path}")
    for enc in ("utf-8-sig", "gb18030"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    rows = list(csv.DictReader(io.StringIO(text, newline="")))
    header = rows[0].keys() if rows else ()
    lacking = [c for c in need if rows and c not in header]
    if lacking:
        sys.exit(f"{path} 缺少列：{', '.join(lacking)}。请不要删除或改名表头。")
    return rows


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
    routes = cfg["routes"]

    done = set()
    seen_hash = {}
    if out.exists():  # 断点续跑：已处理的文件跳过，查重记录也接上
        for row in read_csv(out):
            done.add(row["source"])
            if row.get("sha256") and not row.get("duplicate_of"):
                seen_hash.setdefault(row["sha256"], row["source"])
        print(f"发现已有计划表，跳过已处理的 {len(done)} 个文件。")

    files = [p for p in iter_files(root, cfg) if str(p) not in done]

    def model_of(key):
        return "" if args.no_llm else routes[key].get("model", "")

    new_file = not out.exists()
    with out.open("a", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=PLAN_FIELDS)
        if new_file:
            w.writeheader()

        def emit(row, prefix=""):
            w.writerow(row)
            f.flush()
            flag = "  ⚠" + REVIEW_NOTE if REVIEW_NOTE in row["note"] else ""
            print(f"{prefix}{Path(row['source']).name} -> {row['category']}/{row['new_name']}{flag}")

        # 第 1 步：分流。只看扩展名和字符，不用模型
        print(f"第 1 步：分流 {len(files)} 个文件（不用模型）...")
        pending = {k: [] for k in ROUTE_ORDER}
        for p in files:
            row, job = route_one(p, cfg, seen_hash)
            if job is None:
                emit(row, "  ")
            elif model_of(job[0]):
                pending[job[0]].append((p, row, job[1]))
            else:
                finish_without_model(p, row, job[0], job[1], cfg)
                emit(row, "  ")

        # 第 2 步：按类别分批调用各自的模型（同一模型集中处理，16GB 内存一次只装一个模型）
        needed = sorted({model_of(k) for k in ROUTE_ORDER if pending[k]})
        if needed:
            check_models(cfg, needed)
        for key in ROUTE_ORDER:
            items = pending[key]
            if not items:
                continue
            print(f"\n第 2 步：{routes[key]['folder']} {len(items)} 个，模型 {model_of(key)}")
            for i, (p, row, ctx) in enumerate(items, 1):
                finish_with_model(p, row, key, ctx, cfg)
                emit(row, f"  [{i}/{len(items)}] ")

    print_scan_summary(root, out, cfg)


def print_scan_summary(root, out, cfg):
    """计划表行数必须等于目录里的文件数，一个都不能漏。"""
    rows = read_csv(out)
    in_plan = {r["source"] for r in rows}
    all_files = [str(p) for p in iter_files(root, cfg)]
    missing = [p for p in all_files if p not in in_plan]
    by_lang, by_cat = {}, {}
    for r in rows:
        by_lang[r["language"]] = by_lang.get(r["language"], 0) + 1
        by_cat[r["category"]] = by_cat.get(r["category"], 0) + 1
    print(f"\n===== 扫描汇总 =====\n目录中文件 {len(all_files)} 个，计划表 {len(rows)} 行。")
    print("按语言：" + "，".join(f"{k} {v}" for k, v in sorted(by_lang.items(), key=lambda x: -x[1])))
    for cat, n in sorted(by_cat.items()):
        print(f"  {cat:<16} {n}")
    print(f"需人工确认 {sum(REVIEW_NOTE in r['note'] for r in rows)} 个，"
          f"重复文件 {sum(bool(r['duplicate_of']) for r in rows)} 个（默认不动）")
    if missing:
        print(f"[注意] 有 {len(missing)} 个文件不在计划表中（扫描中断或途中新增），再运行一次 scan 即可补上。")
    print(f"\n请用 Excel 打开检查：{out.resolve()}")
    print("  action 列：move=整理，skip=不动。category 是目标文件夹（可写多级，如 英文德文文档/合同协议）。")
    print("  建议优先看 note 列标了“建议人工确认”的行。")


def match_keyword(name, cfg, cats):
    low = name.lower()
    for kw, cat in cfg["_kw_rules"]:
        if kw in low and cat in cats:
            return cat
    return ""


def route_one(p, cfg, seen_hash):
    """分流。返回 (计划行, 任务)。任务为 None 表示这一行已经定好；否则是 (路线, 附加信息)。"""
    row = dict.fromkeys(PLAN_FIELDS, "")
    row.update(source=str(p), action="move", language="-")
    ext = p.suffix.lower()
    try:
        st = p.stat()
        digest = file_hash(p)
    except OSError as e:
        row.update(action="skip", category="其他", new_name=p.name, note=f"无法读取，未处理: {e}")
        return row, None
    row["sha256"] = digest
    if digest in seen_hash:
        row.update(action="skip", category="重复文件", new_name=p.name,
                   duplicate_of=seen_hash[digest], note="内容与另一文件完全相同，默认不动")
        return row, None
    seen_hash[digest] = str(p)
    mdate = dt.date.fromtimestamp(st.st_mtime).isoformat()

    if ext in cfg["_photo_exts"]:
        row["language"] = LANG_NAMES["photo"]
        return row, ("photo", {"mdate": mdate})
    if ext in cfg["_ext_map"]:  # 音视频、安装包、压缩包、代码等
        row.update(category=cfg["_ext_map"][ext], new_name=p.name, confidence="规则")
        return row, None

    if cfg.get("language_detect", "content") == "filename":
        text = None
        lang = detect_language(p.stem, "")
        if lang == "unknown" and WORD_RE.search(p.stem):
            lang = "latin"
    else:
        text = extract_text(p, cfg["max_chars"])
        lang = detect_language(p.stem, text)
    row["language"] = LANG_NAMES[lang]
    if lang == "unknown":
        row.update(category=cfg["routes"]["unknown"]["folder"], new_name=p.name, confidence="低",
                   note="读不到文字、文件名也看不出语言（可能是扫描件） " + REVIEW_NOTE)
        return row, None
    key = "zh" if lang == "zh" else "en_de"
    return row, (key, {"text": text, "mdate": mdate, "lang": lang, "size": st.st_size})


def finish_without_model(p, row, key, ctx, cfg):
    route = cfg["routes"][key]
    row.update(new_name=p.name, confidence="规则")
    if key == "zh":  # 中文：只分出来，不读内容、不改名
        row["category"] = route["folder"]
    elif key == "photo":  # 没配看图模型：按拍摄年份分
        d = photo_date(p) or ctx["mdate"]
        row["category"] = f"{route['folder']}/{d[:4]}"
    else:
        kw = match_keyword(p.name, cfg, route["categories"])
        row["category"] = f"{route['folder']}/{kw}" if kw else route["folder"]
        if not kw:
            row["note"] = "未用模型，只按语言分出"


def finish_with_model(p, row, key, ctx, cfg):
    route = cfg["routes"][key]
    cats = route["categories"]
    fallback = "其他" if "其他" in cats else list(cats)[-1]  # 拿不准时归入的类
    title, date = p.stem, ctx["mdate"]
    try:
        if key == "photo":
            img = load_photo(p, cfg.get("photo_max_side", 1024))
            if img is None:
                finish_without_model(p, row, key, ctx, cfg)
                row.update(confidence="低", note="图片打不开（HEIC 需安装 pillow-heif） " + REVIEW_NOTE)
                return
            ans = ask_photo(cfg, route, img)
            date = photo_date(p) or date
        else:
            content = ctx["text"] if ctx["text"] is not None else extract_text(p, cfg["max_chars"])
            meta = (f"扩展名 / extension: {p.suffix.lower() or '-'}  大小 / size: {ctx['size'] // 1024} KB  "
                    f"修改日期 / modified: {ctx['mdate']}")
            ask = ask_zh if key == "zh" else ask_en_de
            ans = ask(cfg, route, p.name, meta, content)
            date = valid_date(ans.get("date")) or date
            if key == "en_de" and ctx["lang"] == "latin" and ans.get("language") in ("en", "de"):
                row["language"] = LANG_NAMES[ans["language"]]
            if not content.strip():
                row["note"] = "未读到内容，仅按文件名判断"
                ans["confidence"] = "低"
    except Exception as e:
        finish_without_model(p, row, key, ctx, cfg)
        row.update(confidence="低", note=f"模型调用失败({type(e).__name__}) " + REVIEW_NOTE)
        return

    cat = ans.get("category") if ans.get("category") in cats else fallback
    row["confidence"] = ans.get("confidence", "")
    kw = match_keyword(p.name, cfg, cats) if key != "photo" else ""
    if kw and kw != cat:  # 文件名关键词规则优先于模型
        row["note"] = (row["note"] + f" 模型判为{cat}，按关键词规则改为{kw}").strip()
        cat, row["confidence"] = kw, "规则"
    row["category"] = f"{route['folder']}/{cat}"
    row["summary"] = ans.get("summary", "")
    row["tags"] = "、".join(ans.get("tags", [])[:3])
    title = ans.get("title") or title
    if cat == fallback or row["confidence"] == "低":
        row["note"] = (row["note"] + " " + REVIEW_NOTE).strip()
    stem = cfg["name_template"].format(date=date, title=clean_name(title, cfg["max_name_len"]))
    row["new_name"] = clean_name(stem, cfg["max_name_len"] + 12) + p.suffix.lower()


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

    def group(key):
        out = {}
        for r in archived:
            n, kb = out.get(key(r), (0, 0))
            out[key(r)] = (n + 1, kb + int(r["大小KB"]))
        return sorted(out.items())
    by_top = group(lambda r: r["类别"].split("/")[0])
    by_cat = group(lambda r: r["类别"])
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
    ws.append(["大类", "文件数", "总大小(MB)"])
    for top, (n, kb) in by_top:
        ws.append([top, n, round(kb / 1024, 2)])
    ws.append(["合计", len(archived), round(sum(kb for _, (n, kb) in by_top) / 1024, 2)])
    ws.append([])
    ws.append(["细分类别", "文件数", "总大小(MB)"])
    ws.cell(ws.max_row, 1).font = Font(bold=True)
    for cat, (n, kb) in by_cat:
        ws.append([cat, n, round(kb / 1024, 2)])
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
    rows = read_csv(args.plan, need=("action", "source", "category", "new_name"))

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
            parts = [clean_name(x, 40) for x in re.split(r"[\\/]+", row["category"]) if x.strip()]
            parts = parts or ["其他"]
            cat = "/".join(parts)
            name = clean_name(row["new_name"], 120)
            if not Path(name).suffix and src.suffix:
                name += src.suffix
            dest = unique_path(target.joinpath(*parts) / name)
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
                "类别": cat, "语言": row.get("language", ""), "归档路径": str(dest), "原路径": str(src),
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
    rows = read_csv(path, need=("归档路径", "SHA256"))
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
    rows = read_csv(args.log, need=("new_path", "original_path"))
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
    ap = argparse.ArgumentParser(description="离线本地文件整理（Ollama，多模型分流）")
    ap.add_argument("--config", default=str(HERE / "config.json"), help="配置文件路径")
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("scan", help="扫描、分流并生成整理计划（不动任何文件）")
    s.add_argument("folder")
    s.add_argument("--out", default="plan.csv")
    s.add_argument("--no-llm", action="store_true", help="完全不用模型：只分流（中文/英德文/照片/其他）+ 查重")
    s.add_argument("--zh-model", help="临时指定中文文档模型；none 表示只分出来不细分")
    s.add_argument("--en-de-model", help="临时指定英文/德文文档模型；none 表示只按语言分出")
    s.add_argument("--photo-model", help="临时指定照片模型；none 表示只按拍摄年份分")

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
    for key, opt in (("zh", "zh_model"), ("en_de", "en_de_model"), ("photo", "photo_model")):
        val = getattr(args, opt, None)
        if val is not None:  # none / 无 / 空 = 这条线不用模型
            cfg["routes"][key]["model"] = "" if val.strip().lower() in ("", "none", "无") else val.strip()
    {"scan": cmd_scan, "apply": cmd_apply, "verify": cmd_verify, "undo": cmd_undo}[args.cmd](args, cfg)


if __name__ == "__main__":
    main()
