"""免 key 的备用数据源。FRED 拿不到某个序列时，用这里补上，存成同名文件，
看板无感知。

- 纽约联储 API：EFFR、目标区间上下限、SOFR
- BLS 公共 API v1（免 key，每 IP 每天 25 次）：CPI、核心 CPI、PPI、失业率、非农、时薪
- 美国财政部收益率曲线 CSV：短端/2Y/10Y 名义收益率 + 实际收益率 → 盈亏平衡通胀
- 欧洲央行汇率 API：交叉换算出 DXY 所需的 6 个美元汇率
"""
import io
import logging
from datetime import date

import pandas as pd

from . import http
from .config import START_DATE
from .fred import FRED_DIR

log = logging.getLogger(__name__)
ALT_START = "2012-01-01"  # 备用源只补近十几年，控制请求量


def _save(sid: str, s: pd.Series, source: str):
    s = s.dropna().sort_index()
    s = s[~s.index.duplicated(keep="last")]
    if s.empty:
        return
    s.index.name = "date"
    FRED_DIR.mkdir(parents=True, exist_ok=True)
    s.rename("value").to_frame().to_csv(FRED_DIR / f"{sid}.csv")
    log.info("备用源 %s → %s: %d 条, 最新 %s", source, sid, len(s), s.index[-1].date())


# ---------- 纽约联储 ----------

def nyfed(need: set) -> set:
    got = set()
    end = date.today().isoformat()
    if need & {"EFFR", "DFEDTARU", "DFEDTARL"}:
        r = http.get("https://markets.newyorkfed.org/api/rates/unsecured/effr/search.json",
                     params={"startDate": START_DATE, "endDate": end})
        df = pd.DataFrame(r.json()["refRates"])
        df.index = pd.to_datetime(df["effectiveDate"])
        for sid, col in (("EFFR", "percentRate"), ("DFEDTARL", "targetRateFrom"), ("DFEDTARU", "targetRateTo")):
            if sid in need and col in df:
                _save(sid, pd.to_numeric(df[col], errors="coerce"), "纽约联储")
                got.add(sid)
    if "SOFR" in need:
        r = http.get("https://markets.newyorkfed.org/api/rates/secured/sofr/search.json",
                     params={"startDate": "2018-04-02", "endDate": end})
        df = pd.DataFrame(r.json()["refRates"])
        df.index = pd.to_datetime(df["effectiveDate"])
        _save("SOFR", pd.to_numeric(df["percentRate"], errors="coerce"), "纽约联储")
        got.add("SOFR")
    return got


# ---------- BLS ----------

BLS_MAP = {
    "CPIAUCSL": "CUSR0000SA0",
    "CPILFESL": "CUSR0000SA0L1E",
    "UNRATE": "LNS14000000",
    "U6RATE": "LNS13327709",
    "PAYEMS": "CES0000000001",
    "CES0500000003": "CES0500000003",
    "PPIFIS": "WPSFD4",
    "WPSFD4131": "WPSFD4131",
}


def parse_bls(payload: dict) -> dict:
    out = {}
    for s in payload.get("Results", {}).get("series", []):
        rows = {}
        for d in s.get("data", []):
            p = d.get("period", "")
            if not p.startswith("M") or p == "M13":
                continue
            v = pd.to_numeric(d.get("value"), errors="coerce")
            rows[pd.Timestamp(int(d["year"]), int(p[1:]), 1)] = v
        out[s["seriesID"]] = pd.Series(rows, dtype=float).sort_index()
    return out


def bls(need: set) -> set:
    ids = {BLS_MAP[k]: k for k in need if k in BLS_MAP}
    if not ids:
        return set()
    this = date.today().year
    parts = []
    # v1 每次最多 10 年；多拿一年用于算同比
    for y0 in range(this - 19, this + 1, 10):
        r = http.session().post("https://api.bls.gov/publicAPI/v1/timeseries/data/",
                                json={"seriesid": list(ids), "startyear": str(y0),
                                      "endyear": str(min(y0 + 9, this))}, timeout=(10, 40))
        r.raise_for_status()
        js = r.json()
        if js.get("status") != "REQUEST_SUCCEEDED":
            raise ValueError(f"BLS: {js.get('message')}")
        parts.append(parse_bls(js))
    got = set()
    for bid, fid in ids.items():
        s = pd.concat([p[bid] for p in parts if bid in p])
        if not s.empty:
            _save(fid, s, "BLS")
            got.add(fid)
    return got


# ---------- 财政部收益率曲线 ----------

TSY_URL = ("https://home.treasury.gov/resource-center/data-chart-center/interest-rates/"
           "daily-treasury-rates.csv/{y}/all")


def _tsy_year(y: int, kind: str) -> pd.DataFrame:
    r = http.get(TSY_URL.format(y=y), params={"type": kind, "field_tdr_date_value": y,
                                              "page": "", "_format": "csv"})
    df = pd.read_csv(io.StringIO(r.text))
    df.columns = [c.strip().upper() for c in df.columns]
    df.index = pd.to_datetime(df.pop("DATE"))
    return df.apply(pd.to_numeric, errors="coerce")


def treasury(need: set) -> set:
    want_nom = need & {"DTB3", "DTB6", "DGS1", "DGS2", "DGS10"}
    want_be = need & {"T5YIE", "T10YIE", "T5YIFR"}
    if not (want_nom or want_be):
        return set()
    years = range(int(ALT_START[:4]), date.today().year + 1)
    nom = pd.concat([_tsy_year(y, "daily_treasury_yield_curve") for y in years]).sort_index()
    got = set()
    for sid, col in (("DTB3", "3 MO"), ("DTB6", "6 MO"), ("DGS1", "1 YR"), ("DGS2", "2 YR"), ("DGS10", "10 YR")):
        if sid in want_nom and col in nom:
            _save(sid, nom[col], "财政部")
            got.add(sid)
    if want_be:
        real = pd.concat([_tsy_year(y, "daily_treasury_real_yield_curve") for y in years]).sort_index()
        be5 = (nom["5 YR"] - real["5 YR"]).dropna()
        be10 = (nom["10 YR"] - real["10 YR"]).dropna()
        fwd = (((1 + be10 / 100) ** 10 / (1 + be5 / 100) ** 5) ** (1 / 5) - 1) * 100
        for sid, s in (("T5YIE", be5), ("T10YIE", be10), ("T5YIFR", fwd)):
            if sid in want_be:
                _save(sid, s, "财政部")
                got.add(sid)
    return got


# ---------- 欧洲央行汇率 ----------

def ecb_fx(need: set) -> set:
    fx_ids = {"DEXUSEU", "DEXJPUS", "DEXUSUK", "DEXCAUS", "DEXSDUS", "DEXSZUS"}
    if not (need & fx_ids):
        return set()
    r = http.get("https://data-api.ecb.europa.eu/service/data/EXR/D.USD+JPY+GBP+CAD+SEK+CHF.EUR.SP00.A",
                 params={"startPeriod": ALT_START, "format": "csvdata"})
    df = pd.read_csv(io.StringIO(r.text))
    w = df.pivot_table(index="TIME_PERIOD", columns="CURRENCY", values="OBS_VALUE")
    w.index = pd.to_datetime(w.index)
    usd = w["USD"]  # 1 EUR = x USD
    conv = {"DEXUSEU": usd, "DEXJPUS": w["JPY"] / usd, "DEXUSUK": usd / w["GBP"],
            "DEXCAUS": w["CAD"] / usd, "DEXSDUS": w["SEK"] / usd, "DEXSZUS": w["CHF"] / usd}
    got = set()
    for sid in need & fx_ids:
        _save(sid, conv[sid], "欧洲央行")
        got.add(sid)
    return got


def fill_missing(status: dict) -> dict:
    """对 FRED 失败的序列尝试备用源。返回更新后的 status。"""
    need = {k for k, v in status.items() if v != "ok"}
    if not need:
        return status
    for name, fn in (("纽约联储", nyfed), ("BLS", bls), ("财政部", treasury), ("欧洲央行", ecb_fx)):
        try:
            for sid in fn(need):
                status[sid] = f"ok（备用源：{name}）"
                need.discard(sid)
        except Exception as e:
            log.warning("备用源 %s 失败: %s", name, e)
    return status
