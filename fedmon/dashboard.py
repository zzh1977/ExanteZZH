"""生成静态看板 docs/index.html（数据内嵌为 JSON，图表用 Plotly）。"""
import json
import logging
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd

from . import dotplot, dxy, fomc_calendar, fred, implied
from .config import DOCS, FRED_SERIES

log = logging.getLogger(__name__)
TEMPLATE = Path(__file__).with_name("dashboard_template.html")


def _compact(s: pd.Series, daily_years: int = 3) -> pd.Series:
    """日频数据：近 N 年保留日度，更早的改为周度，控制页面体积。"""
    if len(s) < 2 or (s.index[1] - s.index[0]).days > 7:
        return s
    cut = s.index[-1] - pd.DateOffset(years=daily_years)
    old = s[s.index < cut].resample("W-FRI").last().dropna()
    return pd.concat([old, s[s.index >= cut]])


def _ser(s: pd.Series, nd: int = 3) -> dict:
    s = s.dropna()
    return {"x": [d.strftime("%Y-%m-%d") for d in s.index], "y": [round(float(v), nd) for v in s]}


def _last(s: pd.Series):
    s = s.dropna()
    if s.empty:
        return None
    return {"v": round(float(s.iloc[-1]), 3), "d": s.index[-1].strftime("%Y-%m-%d"),
            "prev": round(float(s.iloc[-2]), 3) if len(s) > 1 else None}


def build() -> Path:
    series, kpi = {}, {}
    for sid, (name, group, how) in FRED_SERIES.items():
        if group in ("fx_raw", "sep"):
            continue
        s = fred.transform(fred.load(sid), how)
        if s.empty:
            continue
        series[sid] = {"name": name, "group": group, **_ser(_compact(s))}
        kpi[sid] = _last(s)

    # 政策利率中值（目标区间中点）
    up, lo = fred.load("DFEDTARU"), fred.load("DFEDTARL")
    if not up.empty and not lo.empty:
        mid = ((up + lo) / 2).dropna()
        series["TARGET_MID"] = {"name": "目标区间中点", "group": "policy", **_ser(_compact(mid))}

    d = dxy.load()
    for c, name in (("dxy_ice", "DXY（ICE）"), ("dxy_calc", "DXY（按公式自算）")):
        if c in d and d[c].notna().any():
            series[c.upper()] = {"name": name, "group": "fx", **_ser(_compact(d[c]))}
            kpi[c.upper()] = _last(d[c])

    # 点阵图
    dots = dotplot.load()
    dot_payload = {"latest": None, "history": []}
    if not dots.empty:
        med = dotplot.medians(dots)
        dot_payload["history"] = med.to_dict("records")
        last = dots["sep_date"].max()
        dot_payload["latest"] = {
            "sep_date": last,
            "dots": dots[dots["sep_date"] == last][["horizon", "rate", "count"]].to_dict("records"),
            "median": med[med["sep_date"] == last][["horizon", "median"]].to_dict("records"),
        }
    else:  # 网页版解析失败时，至少用 FRED 的最新中位数
        md = fred.load("FEDTARMD")
        if not md.empty:
            dot_payload["fred_median"] = [{"horizon": str(i.year), "median": float(v)} for i, v in md.items()]

    cal = fomc_calendar.load()
    imp = implied.load()
    hist = []
    if implied.HIST.exists():
        hist = pd.read_csv(implied.HIST).to_dict("records")

    payload = {
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "series": series,
        "kpi": kpi,
        "dots": dot_payload,
        "implied": imp,
        "implied_history": hist,
        "calendar": [{"end": r.end.isoformat(), "sep": bool(r.sep)} for r in cal.itertuples()],
        "today": date.today().isoformat(),
    }
    html = TEMPLATE.read_text(encoding="utf-8").replace(
        "/*__DATA__*/null", json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
    DOCS.mkdir(exist_ok=True)
    out = DOCS / "index.html"
    out.write_text(html, encoding="utf-8")
    log.info("看板已生成 %s（%.0f KB）", out, out.stat().st_size / 1024)
    return out
