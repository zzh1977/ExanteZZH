"""市场隐含利率，三层来源，按顺序尝试：

1. CME FedWatch 网页抓取（Playwright 无头浏览器）——口径最权威，但网页结构可能变
2. 联邦基金期货 ZQ（雅虎财经报价）+ 按 FedWatch 公式自己算
3. 国库券 / 短端美债减 EFFR 的粗略代理（只有期限点，没有逐次会议）

结果写入 data/implied.json，并把每天的路径追加到 data/implied_history.csv，
这样能看到市场预期随时间怎么漂移。
"""
import calendar
import io
import json
import logging
import math
import re
from datetime import date, datetime, timedelta, timezone

import pandas as pd

from . import fomc_calendar, fred, yahoo
from .config import DATA, RAW

log = logging.getLogger(__name__)
OUT = DATA / "implied.json"
HIST = DATA / "implied_history.csv"
MONTH_CODES = "FGHJKMNQUVXZ"
FEDWATCH_URLS = [
    "https://cmegroup-tools.quikstrike.net/User/QuikStrikeView.aspx?viewitemid=IntegratedFedWatchTool",
    "https://www.cmegroup.com/markets/interest-rates/cme-fedwatch-tool.html",
]


# ---------- 公共：概率树 ----------

def range_label(lower_bp: int) -> str:
    return f"{lower_bp / 100:.2f}-{(lower_bp + 25) / 100:.2f}"


def prob_tree(lower_bp_now: int, steps: list[float]) -> list[dict]:
    """FedWatch 式概率树。steps 为每次会议的预期变动（单位：25bp 的倍数）。
    每次会议只在相邻两档之间分配概率。返回每次会议后的 {区间下限bp: 概率}。"""
    dist = {lower_bp_now: 1.0}
    out = []
    for d in steps:
        k = math.floor(d + 1e-9)
        f = d - k
        nd = {}
        for lvl, p in dist.items():
            for move, w in ((k, 1 - f), (k + 1, f)):
                if w > 1e-9:
                    key = lvl + 25 * move
                    nd[key] = nd.get(key, 0.0) + p * w
        dist = nd
        out.append(dict(sorted(dist.items())))
    return out


def _now_state():
    upper = fred.load("DFEDTARU")
    lower = fred.load("DFEDTARL")
    effr = fred.load("EFFR")
    if lower.empty or effr.empty:
        raise ValueError("缺少 FRED 政策利率数据，先跑 fred 更新")
    return int(round(lower.iloc[-1] * 100)), float(upper.iloc[-1]), float(effr.iloc[-1])


# ---------- 第 2 层：ZQ 期货 ----------

def zq_symbol(y: int, m: int) -> str:
    return f"ZQ{MONTH_CODES[m - 1]}{y % 100:02d}.CBT"


def _add_month(y, m, k=1):
    m += k
    return y + (m - 1) // 12, (m - 1) % 12 + 1


def implied_from_zq(prices: dict, meetings: list[date], effr_now: float, today: date) -> list[dict]:
    """prices: {(年, 月): ZQ 价格}；meetings: 未来决议日（升序）。
    返回每次会议的 {date, r_pre, r_post}。"""
    # 决议次日生效；若生效日跨月，把会议归到下个月的第 1 天
    eff = {}
    for d in meetings:
        e = d + timedelta(days=1)
        eff[(e.year, e.month)] = (d, e.day)
    avg = {k: 100 - v for k, v in prices.items()}
    res = []
    r = effr_now
    y, m = today.year, today.month
    for _ in range(24):
        if not any((yy, mm) >= (y, m) for yy, mm in eff):
            break
        if (y, m) in eff:
            d, e = eff[(y, m)]
            n = calendar.monthrange(y, m)[1]
            nxt = _add_month(y, m)
            if nxt not in eff and nxt in avg:
                r_post = avg[nxt]  # 下个月没会议：直接用下月合约，更稳
            elif (y, m) in avg and n - e + 1 > 0:
                r_post = (avg[(y, m)] * n - r * (e - 1)) / (n - e + 1)
            else:
                break  # 缺价格就停在这里，只返回已算出的会议
            res.append({"date": d, "r_pre": r, "r_post": r_post})
            r = r_post
        elif (y, m) in avg and (y, m) != (today.year, today.month):
            r = avg[(y, m)]  # 无会议月份：用该月合约校准起点
        y, m = _add_month(y, m)
    return res


def from_zq() -> dict:
    lower_bp, _, effr = _now_state()
    today = date.today()
    meetings = [d for d in fomc_calendar.upcoming(today)["end"]][:10]
    prices = {}
    y, m = today.year, today.month
    misses = 0
    for _ in range(16):
        if misses >= 3:
            break
        try:
            prices[(y, m)] = yahoo.last_price(zq_symbol(y, m))
            misses = 0
        except Exception as e:
            misses += 1
            log.info("ZQ %s 无报价: %s", zq_symbol(y, m), e)
        y, m = _add_month(y, m)
    if len(prices) < 4:
        raise ValueError(f"ZQ 报价太少（{len(prices)} 个）")
    path = implied_from_zq(prices, meetings, effr, today)
    if not path:
        raise ValueError("ZQ 未能算出任何会议")
    steps = [(p["r_post"] - p["r_pre"]) / 0.25 for p in path]
    trees = prob_tree(lower_bp, steps)
    return {
        "source": "ZQ 期货（雅虎报价，自算 FedWatch 公式）",
        "effr_now": effr,
        "meetings": [{
            "date": p["date"].isoformat(),
            "exp_rate": round(p["r_post"], 4),
            "chg_bp_vs_now": round((p["r_post"] - effr) * 100, 1),
            "chg_bp_this_meeting": round((p["r_post"] - p["r_pre"]) * 100, 1),
            "probs": {range_label(k): round(v, 4) for k, v in t.items() if v >= 0.001},
        } for p, t in zip(path, trees)],
    }


# ---------- 第 1 层：FedWatch 抓取 ----------

RANGE_RE = re.compile(r"^\s*(\d{3,4})\s*-\s*(\d{3,4})\s*$")
PCT_RE = re.compile(r"(-?\d+(?:\.\d+)?)\s*%")


def parse_fedwatch_matrix(html: str) -> list[dict]:
    """解析 FedWatch 的 Probabilities 矩阵表：行 = 会议日期，列 = 目标区间(bps)。"""
    out = []
    for t in pd.read_html(io.StringIO(html)):
        cols = [" ".join(map(str, c)) if isinstance(c, tuple) else str(c) for c in t.columns]
        rng_cols = {}
        for i, c in enumerate(cols):
            m = re.search(r"(\d{3,4})\s*-\s*(\d{3,4})", c)
            if m:
                rng_cols[i] = int(m.group(1))
        if len(rng_cols) < 2:
            continue
        for _, row in t.iterrows():
            dt = pd.to_datetime(str(row.iloc[0]), errors="coerce")
            if pd.isna(dt):
                continue
            probs = {}
            for i, lo in rng_cols.items():
                m = PCT_RE.search(str(row.iloc[i]))
                if m and float(m.group(1)) > 0:
                    probs[range_label(lo)] = round(float(m.group(1)) / 100, 4)
            if probs:
                out.append({"date": dt.date().isoformat(), "probs": probs})
        if out:
            break
    return out


def _exp_rate(probs: dict) -> float:
    return sum((float(k.split("-")[0]) + 0.125) * p for k, p in probs.items()) / max(sum(probs.values()), 1e-9)


def from_fedwatch() -> dict:
    from playwright.sync_api import sync_playwright  # 只在需要时导入

    htmls = []
    with sync_playwright() as pw:
        br = pw.chromium.launch()
        pg = br.new_page(extra_http_headers={"Referer": "https://www.cmegroup.com/"}, user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                                    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
        for url in FEDWATCH_URLS:
            try:
                pg.goto(url, timeout=30000, wait_until="domcontentloaded")
                pg.wait_for_timeout(8000)
                # 切到“Probabilities”矩阵视图（按钮文字可能变化，尽量宽松匹配）
                for fr in [pg.main_frame, *pg.frames]:
                    try:
                        el = fr.get_by_text(re.compile(r"^\s*Probabilities\s*$", re.I)).first
                        if el.count():
                            el.click(timeout=5000)
                            pg.wait_for_timeout(5000)
                            break
                    except Exception:
                        pass
                for fr in pg.frames:
                    c = fr.content()
                    htmls.append(c)
                    txt = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", c))
                    log.info("FedWatch 诊断 frame=%s len=%d tables=%d 文本: %s", fr.url[:120], len(c),
                             c.lower().count("<table"), txt[:300])
                rows = []
                for h in htmls:
                    rows = parse_fedwatch_matrix(h)
                    if rows:
                        break
                if rows:
                    br.close()
                    lower_bp, _, effr = _now_state()
                    return {
                        "source": "CME FedWatch（网页抓取）",
                        "effr_now": effr,
                        "meetings": [{
                            "date": r["date"],
                            "exp_rate": round(_exp_rate(r["probs"]), 4),
                            "chg_bp_vs_now": round((_exp_rate(r["probs"]) - (lower_bp / 100 + 0.125)) * 100, 1),
                            "probs": r["probs"],
                        } for r in rows],
                    }
            except Exception as e:
                log.warning("FedWatch %s 失败: %s", url, e)
        br.close()
    RAW.mkdir(parents=True, exist_ok=True)
    for i, h in enumerate(htmls):
        (RAW / f"fedwatch_{i}.html").write_text(h, encoding="utf-8")
    raise ValueError("FedWatch 页面中没解析到概率矩阵（原始页面已存到 data/raw/）")


# ---------- 第 3 层：短端美债代理 ----------

def from_bills() -> dict:
    _, _, effr = _now_state()
    pts = []
    for sid, label, months in (("DTB3", "3个月", 3), ("DTB6", "6个月", 6),
                               ("DGS1", "1年", 12), ("DGS2", "2年", 24)):
        s = fred.load(sid)
        if not s.empty:
            pts.append({"horizon": label, "months": months, "yield": float(s.iloc[-1]),
                        "spread_bp_vs_effr": round((s.iloc[-1] - effr) * 100, 1)})
    if not pts:
        raise ValueError("没有短端美债数据")
    return {"source": "短端美债减 EFFR（粗略代理，含期限溢价）", "effr_now": effr,
            "meetings": [], "bill_proxy": pts}


# ---------- 汇总 ----------

def update() -> dict:
    errors = {}
    result = None
    for name, fn in (("fedwatch", from_fedwatch), ("zq", from_zq), ("bills", from_bills)):
        try:
            result = fn()
            break
        except Exception as e:
            errors[name] = str(e)[:300]
            log.warning("隐含利率来源 %s 失败: %s", name, e)
    if result is None:
        result = {"source": "无", "meetings": []}
    # 第 3 层的期限代理总是附带，方便对照
    if "bill_proxy" not in result:
        try:
            result["bill_proxy"] = from_bills()["bill_proxy"]
        except Exception:
            pass
    result["asof"] = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    result["errors"] = errors
    DATA.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    _append_history(result)
    return result


def _append_history(result: dict):
    if not result.get("meetings"):
        return
    day = result["asof"][:10]
    rows = pd.DataFrame([{"asof": day, "source": result["source"], "meeting": m["date"],
                          "exp_rate": m["exp_rate"]} for m in result["meetings"]])
    if HIST.exists():
        old = pd.read_csv(HIST)
        old = old[old["asof"] != day]  # 同一天重跑只保留最后一次
        rows = pd.concat([old, rows], ignore_index=True)
    rows.to_csv(HIST, index=False)


def load() -> dict:
    return json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {"meetings": []}
