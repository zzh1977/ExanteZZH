"""FRED 数据下载。

有环境变量 FRED_API_KEY 就走官方 API，否则走无需 key 的 fredgraph.csv。
每个序列存一个 CSV：data/fred/<ID>.csv，列为 date,value。
"""
import io
import logging
import os

import pandas as pd

from . import http
from .config import DATA, FRED_SERIES, START_DATE

log = logging.getLogger(__name__)
FRED_DIR = DATA / "fred"


def _via_api(sid: str, key: str) -> pd.Series:
    r = http.get(
        "https://api.stlouisfed.org/fred/series/observations",
        params={"series_id": sid, "api_key": key, "file_type": "json",
                "observation_start": START_DATE},
    )
    obs = r.json()["observations"]
    df = pd.DataFrame(obs)[["date", "value"]]
    return _clean(df.rename(columns={"value": sid}), sid)


def _via_graph(sid: str) -> pd.Series:
    r = http.get("https://fred.stlouisfed.org/graph/fredgraph.csv",
                 params={"id": sid, "cosd": START_DATE})
    df = pd.read_csv(io.StringIO(r.text))
    return _clean(df, sid)


def _clean(df: pd.DataFrame, sid: str) -> pd.Series:
    # fredgraph 的日期列以前叫 DATE，现在叫 observation_date，两种都兼容
    date_col = next(c for c in df.columns if c.lower() in ("date", "observation_date"))
    s = pd.to_numeric(df[sid].replace(".", None), errors="coerce")
    s.index = pd.to_datetime(df[date_col])
    s.index.name = "date"
    return s.dropna().rename(sid)


def fetch(sid: str) -> pd.Series:
    key = os.environ.get("FRED_API_KEY")
    if key:
        try:
            return _via_api(sid, key)
        except Exception as e:  # API 出错时退回 fredgraph
            log.warning("FRED API 失败 %s: %s，改用 fredgraph", sid, e)
    return _via_graph(sid)


def update_all() -> dict:
    """下载全部序列。返回 {id: 'ok'|错误信息}。单个失败不影响其他。"""
    FRED_DIR.mkdir(parents=True, exist_ok=True)
    status = {}
    streak = 0  # 连续失败次数：一个站点整体不通时不要每个序列都等超时
    for sid in FRED_SERIES:
        if streak >= (4 if os.environ.get("FRED_API_KEY") else 1):
            status[sid] = "跳过（前面连续失败）"
            continue
        try:
            s = fetch(sid)
            s.to_frame("value").to_csv(FRED_DIR / f"{sid}.csv")
            status[sid] = "ok"
            streak = 0
            log.info("FRED %s: %d 条, 最新 %s", sid, len(s), s.index[-1].date())
        except Exception as e:
            status[sid] = f"失败: {e}"
            streak += 1
            log.error("FRED %s 失败: %s", sid, e)
    return status


def load(sid: str) -> pd.Series:
    """读取本地已下载的序列；不存在返回空序列。"""
    p = FRED_DIR / f"{sid}.csv"
    if not p.exists():
        return pd.Series(dtype=float, name=sid)
    df = pd.read_csv(p, parse_dates=["date"], index_col="date")
    return df["value"].rename(sid)


def transform(s: pd.Series, how: str) -> pd.Series:
    """按配置做同比 / 环比 / 差分。月度及以上频率数据用 12 期同比。"""
    if s.empty or how == "level":
        return s
    if how == "yoy":
        return (s / s.shift(12) - 1).mul(100).dropna()
    if how == "mom":
        return (s / s.shift(1) - 1).mul(100).dropna()
    if how == "diff":
        return s.diff().dropna()
    raise ValueError(how)
