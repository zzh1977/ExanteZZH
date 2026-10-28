"""美元指数 DXY。

主来源：雅虎 DX-Y.NYB（ICE 美元指数）。
兜底：用 FRED 的 6 个货币对按 ICE 官方公式自己算（纽约中午汇率，与收盘略有差异）。
输出 data/dxy.csv: date, dxy_ice, dxy_calc
"""
import logging

import numpy as np
import pandas as pd

from . import fred, yahoo
from .config import DATA

log = logging.getLogger(__name__)
OUT = DATA / "dxy.csv"

# ICE 公式：50.14348112 × EURUSD^-0.576 × USDJPY^0.136 × GBPUSD^-0.119
#           × USDCAD^0.091 × USDSEK^0.042 × USDCHF^0.036
WEIGHTS = {"DEXUSEU": -0.576, "DEXJPUS": 0.136, "DEXUSUK": -0.119,
           "DEXCAUS": 0.091, "DEXSDUS": 0.042, "DEXSZUS": 0.036}
CONST = 50.14348112


def compute(fx: pd.DataFrame) -> pd.Series:
    """fx 列为 WEIGHTS 中的 FRED 代码。任一货币缺失的日期不计算。"""
    fx = fx[list(WEIGHTS)].dropna()
    logv = sum(np.log(fx[c]) * w for c, w in WEIGHTS.items())
    return (CONST * np.exp(logv)).rename("dxy_calc")


def update() -> pd.DataFrame:
    calc = compute(pd.concat({c: fred.load(c) for c in WEIGHTS}, axis=1))
    try:
        ice = yahoo.history("DX-Y.NYB", "max").rename("dxy_ice")
    except Exception as e:
        log.warning("雅虎 DXY 失败: %s，只用自算值", e)
        ice = pd.Series(dtype=float, name="dxy_ice")
    df = pd.concat([ice, calc], axis=1).sort_index()
    df = df[df.index >= "2007-01-01"]
    df.index.name = "date"
    DATA.mkdir(exist_ok=True)
    df.round(3).to_csv(OUT)
    return df


def load() -> pd.DataFrame:
    if not OUT.exists():
        return pd.DataFrame(columns=["dxy_ice", "dxy_calc"])
    return pd.read_csv(OUT, parse_dates=["date"], index_col="date")
