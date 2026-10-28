"""Step 1 indicators: stock, rate-expectation and stress sub-indices.

Sign convention everywhere: positive = looser dollar liquidity.
"""
import numpy as np
import pandas as pd

from . import config, transform
from .config import SERIES

DAILY_MEAN = {"RRPONTSYD", "RPONTSYD", "DGS1", "DFF", "SOFR", "IORB", "IOER"}
FFILL_LIMIT = {"GDP": 20}  # weeks; everything else bridges at most 2 missing weeks

# Smallest standard deviation used when scoring. Units: % of GDP or bp.
STD_FLOOR = {
    "policy_13w_gdp": 0.1,   # ~ $30bn over 13 weeks
    "sofr_iorb_bp": 1.0,
}


def prepare(raw: dict[str, pd.Series]) -> pd.DataFrame:
    """Convert units, re-date to release day, and put every series on Friday rows."""
    cols = {}
    for sid, s in raw.items():
        spec = SERIES[sid]
        s = transform.to_billions(s, spec)
        transform.check_range(s, spec)
        cols[sid] = transform.to_weekly(s, spec.lag_days, "mean" if sid in DAILY_MEAN else "last")
    w = pd.DataFrame(cols).sort_index()
    # GDP (long release lag) and NFCI (validation only) must not add rows past the newest data.
    newest = max(w[c].last_valid_index() for c in w.columns if c not in ("GDP", "NFCI"))
    w = w.loc[:newest]
    for sid in w.columns:
        w[sid] = w[sid].ffill(limit=FFILL_LIMIT.get(sid, 2))
    return w


def build(w: pd.DataFrame, text_tone: pd.Series | None = None) -> pd.DataFrame:
    """text_tone: weekly hawk/dove tone (positive = dovish), from liquidity.text."""
    gdp = w["GDP"]
    out = pd.DataFrame(index=w.index)

    # Diagnostic only: popular "net liquidity" (TGA smoothed over 4 weeks).
    tga4 = w["WTREGEN"].rolling(4, min_periods=1).mean()
    out["net_liquidity_bn"] = w["WALCL"] - tga4 - w["RRPONTSYD"].fillna(0)

    # Stock 1: reserves as % of GDP (level).
    out["reserves_gdp"] = w["WRESBAL"] / gdp * 100

    # Stock 2: policy-driven securities purchases over 13 weeks, % of GDP.
    # Inside reserve-management windows, bill and MBS changes are excluded
    # (bill buying for reserves, and MBS runoff reinvested into bills).
    d_total = w["WSHOSHO"].diff()
    d_excluded = w["WSHOBL"].diff().fillna(0) + w["WSHOMCB"].diff().fillna(0)
    rmp = transform.in_windows(w.index, config.RMP_WINDOWS)
    policy_d = d_total - d_excluded.where(rmp, 0.0)
    out["policy_13w_gdp"] = policy_d.rolling(13).sum() / gdp * 100

    # Expectations: cuts priced over the next year, bp (positive = cuts priced).
    out["expected_easing_bp"] = -(w["DGS1"] - w["DFF"]) * 100

    # Stress 1: SOFR minus the interest paid on reserves, bp.
    ior = w["IORB"].combine_first(w["IOER"])
    out["sofr_iorb_bp"] = (w["SOFR"] - ior) * 100

    # Stress 2: Fed lending, swap lines and overnight repo (incl. SRF), % of GDP.
    facility = w["WLCFLL"].fillna(0) + w["SWPT"].fillna(0) + w["RPONTSYD"].fillna(0)
    out["facility_gdp"] = facility / gdp * 100

    # Scores (sign-adjusted so that positive = looser).
    regime = out.index >= pd.Timestamp(config.RESERVES_REGIME_START)
    out["z_reserves"] = transform.expanding_z(out["reserves_gdp"].where(regime))
    out["z_policy"] = transform.rolling_z(out["policy_13w_gdp"], std_floor=STD_FLOOR["policy_13w_gdp"])
    out["z_expected_easing"] = transform.expanding_z(out["expected_easing_bp"])
    out["z_sofr_iorb"] = -transform.rolling_z(out["sofr_iorb_bp"], std_floor=STD_FLOOR["sofr_iorb_bp"])
    # Log scale so 2008 (~10% of GDP) doesn't dwarf later episodes, and an
    # expanding window so the 2020 spike doesn't make the 2023 bank-run
    # lending look normal. 0.1% of GDP is roughly $30bn.
    out["z_facility"] = -transform.expanding_z(np.log1p(out["facility_gdp"] / 0.1))

    out["stock"] = out[["z_reserves", "z_policy"]].mean(axis=1)
    exp_cols = ["z_expected_easing"]
    if text_tone is not None:
        out["text_tone"] = text_tone.reindex(out.index).ffill(limit=2)
        out["z_text"] = transform.expanding_z(out["text_tone"])
        exp_cols.append("z_text")
    out["expectations"] = out[exp_cols].mean(axis=1)
    out["stress"] = out[["z_sofr_iorb", "z_facility"]].mean(axis=1)

    subs = out[["stock", "expectations", "stress"]]
    out["composite"] = subs.mean(axis=1).where(subs.notna().sum(axis=1) >= 2)
    return out


SUB_INDICES = ["stock", "expectations", "stress", "composite"]
