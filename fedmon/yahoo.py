"""雅虎财经行情（免费、无需 key）。云服务器 IP 常被限流（429），失败要有兜底。"""
import pandas as pd

from . import http

HOSTS = ("query2", "query1")
_crumb = None


def _prime():
    """先访问一次拿 cookie 和 crumb，降低 429 概率。"""
    global _crumb
    if _crumb is not None:
        return _crumb
    _crumb = ""
    try:
        http.session().get("https://fc.yahoo.com", timeout=(10, 20))
        r = http.session().get("https://query2.finance.yahoo.com/v1/test/getcrumb", timeout=(10, 20))
        if r.status_code == 200 and len(r.text) < 50:
            _crumb = r.text.strip()
    except Exception:
        pass
    return _crumb


def _chart(sym: str, rng: str):
    crumb = _prime()
    params = {"range": rng, "interval": "1d"}
    if crumb:
        params["crumb"] = crumb
    last = None
    for h in HOSTS:
        try:
            r = http.get(f"https://{h}.finance.yahoo.com/v8/finance/chart/{sym}", params=params, retries=1)
            return r.json()["chart"]["result"][0]
        except Exception as e:
            last = e
    raise last


def last_price(sym: str) -> float:
    p = _chart(sym, "5d")["meta"].get("regularMarketPrice")
    if p is None:
        raise ValueError(f"{sym} 无价格")
    return float(p)


def history(sym: str, rng: str = "max") -> pd.Series:
    res = _chart(sym, rng)
    idx = pd.to_datetime(res["timestamp"], unit="s").normalize()
    close = res["indicators"]["quote"][0]["close"]
    s = pd.Series(close, index=idx, name=sym).dropna()
    s.index.name = "date"
    return s[~s.index.duplicated(keep="last")]
