"""雅虎财经行情（免费、无需 key）。"""
import pandas as pd

from . import http

CHART = "https://query1.finance.yahoo.com/v8/finance/chart/{sym}"


def last_price(sym: str) -> float:
    r = http.get(CHART.format(sym=sym), params={"range": "5d", "interval": "1d"}, retries=2)
    res = r.json()["chart"]["result"][0]
    p = res["meta"].get("regularMarketPrice")
    if p is None:
        raise ValueError(f"{sym} 无价格")
    return float(p)


def history(sym: str, rng: str = "max") -> pd.Series:
    r = http.get(CHART.format(sym=sym), params={"range": rng, "interval": "1d"}, retries=2)
    res = r.json()["chart"]["result"][0]
    idx = pd.to_datetime(res["timestamp"], unit="s").normalize()
    close = res["indicators"]["quote"][0]["close"]
    s = pd.Series(close, index=idx, name=sym).dropna()
    s.index.name = "date"
    return s[~s.index.duplicated(keep="last")]
