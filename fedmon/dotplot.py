"""历史点阵图：解析美联储 SEP 网页版（accessible materials）的 Figure 2 表格。

网页版 SEP 地址形如 monetarypolicy/fomcprojtabl20250917.htm。
较早的 SEP 只有 PDF，暂不解析（见 PLAN.md 待办）。
历史 SEP 不会再变，所以只抓本地还没有的那几期。
输出 data/dotplot.csv（长表）: sep_date, horizon, rate, count
"""
import io
import logging
import re
from datetime import date

import pandas as pd

from . import http
from .config import DATA

log = logging.getLogger(__name__)
BASE = "https://www.federalreserve.gov/monetarypolicy/"
DOT_CSV = DATA / "dotplot.csv"
SEP_RE = re.compile(r"fomcprojtabl(\d{8})\.htm")
FIRST_YEAR = 2012  # 点阵图从 2012 年 1 月开始发布


def discover_sep_dates() -> list[str]:
    """从日程页 + 历年历史页收集所有网页版 SEP 的日期（YYYYMMDD）。"""
    found = set()
    try:
        found |= set(SEP_RE.findall(http.get(BASE + "fomccalendars.htm").text))
    except Exception as e:
        log.warning("日程页读取失败: %s", e)
    covered = {int(d[:4]) for d in found}
    candidates = set()
    fails = 0
    for y in range(FIRST_YEAR, date.today().year):
        if y in covered or fails >= 3:
            continue
        try:
            page = http.get(BASE + f"fomchistorical{y}.htm").text
            found |= set(SEP_RE.findall(page))
            # 历史页不直接链接网页版 SEP：用会议声明日期去试 fomcprojtabl<日期>.htm
            for d in sorted(set(re.findall(r"monetary(\d{8})a\.htm", page))):
                if int(d[4:6]) in (1, 3, 4, 6, 9, 11, 12):
                    candidates.add(d)
            fails = 0
        except Exception as e:
            fails += 1
            log.info("%d 历史页读取失败: %s", y, e)
    for d in sorted(candidates - found):
        try:
            http.get(BASE + f"fomcprojtabl{d}.htm", retries=1)
            found.add(d)
        except Exception:
            pass  # 这次会议没有 SEP，或只有 PDF
    return sorted(found)


def _flat_cols(df: pd.DataFrame) -> list[str]:
    cols = []
    for c in df.columns:
        if isinstance(c, tuple):
            c = " ".join(str(x) for x in c if not str(x).startswith("Unnamed"))
        cols.append(str(c).strip())
    return cols


def _horizon(col: str) -> str | None:
    if re.search(r"longer", col, re.I):
        return "Longer run"
    m = re.search(r"(20\d{2})", col)
    return m.group(1) if m else None


def parse_sep(html: str) -> pd.DataFrame:
    """从一期 SEP 网页中提取点阵分布。返回列 horizon, rate, count。"""
    tables = pd.read_html(io.StringIO(html))
    for t in tables:
        cols = _flat_cols(t)
        if not cols or not re.search(r"midpoint|target level", cols[0], re.I):
            continue
        horizons = {c: _horizon(c) for c in cols[1:]}
        if not any(horizons.values()):
            continue
        t.columns = cols
        rows = []
        for _, r in t.iterrows():
            rate = pd.to_numeric(str(r[cols[0]]).strip(), errors="coerce")
            if pd.isna(rate):
                continue
            for c, h in horizons.items():
                if not h:
                    continue
                n = pd.to_numeric(str(r[c]).strip(), errors="coerce")
                if pd.notna(n) and n > 0:
                    rows.append({"horizon": h, "rate": float(rate), "count": int(n)})
        if rows:
            return pd.DataFrame(rows)
    raise ValueError("没找到点阵图表格（Figure 2）")


def median_of(dots: pd.DataFrame) -> float:
    """按美联储口径求中位数：偶数个点时取中间两点的平均。"""
    vals = sorted(v for v, n in zip(dots["rate"], dots["count"]) for _ in range(int(n)))
    k = len(vals)
    if k == 0:
        return float("nan")
    return vals[k // 2] if k % 2 else (vals[k // 2 - 1] + vals[k // 2]) / 2


def medians(df: pd.DataFrame) -> pd.DataFrame:
    """每期 SEP、每个年份的中位数、最高、最低、人数。"""
    out = []
    for (d, h), g in df.groupby(["sep_date", "horizon"]):
        out.append({"sep_date": d, "horizon": h, "median": median_of(g),
                    "high": g["rate"].max(), "low": g["rate"].min(),
                    "n": int(g["count"].sum())})
    return pd.DataFrame(out).sort_values(["sep_date", "horizon"])


def update() -> pd.DataFrame:
    old = pd.read_csv(DOT_CSV, dtype={"sep_date": str, "horizon": str}) \
        if DOT_CSV.exists() else pd.DataFrame(columns=["sep_date", "horizon", "rate", "count"])
    have = set(old["sep_date"].astype(str))
    new = []
    for d in discover_sep_dates():
        iso = f"{d[:4]}-{d[4:6]}-{d[6:]}"
        if iso in have:
            continue
        try:
            dots = parse_sep(http.get(BASE + f"fomcprojtabl{d}.htm").text)
            dots.insert(0, "sep_date", iso)
            new.append(dots)
            log.info("SEP %s: %d 个点", iso, dots["count"].sum())
        except Exception as e:
            log.error("SEP %s 解析失败: %s", iso, e)
    df = pd.concat([old, *new], ignore_index=True) if new else old
    if not df.empty:
        df = df.sort_values(["sep_date", "horizon", "rate"]).reset_index(drop=True)
        DATA.mkdir(exist_ok=True)
        df.to_csv(DOT_CSV, index=False)
    return df


def load() -> pd.DataFrame:
    if not DOT_CSV.exists():
        return pd.DataFrame(columns=["sep_date", "horizon", "rate", "count"])
    return pd.read_csv(DOT_CSV, dtype={"sep_date": str, "horizon": str})
