"""End-to-end mechanics on synthetic inputs shaped like FRED's (units included)."""
import numpy as np
import pandas as pd
import pytest

from liquidity import indicators

START, END = "2014-01-01", "2026-10-23"


def _wed(value):
    idx = pd.date_range(START, END, freq="W-WED")
    v = value(np.arange(len(idx))) if callable(value) else np.full(len(idx), value, dtype=float)
    return pd.Series(v, index=idx)


def _daily(value, noise=0.0, seed=2):
    idx = pd.bdate_range(START, END)
    jitter = noise * np.random.default_rng(seed).normal(size=len(idx)).cumsum()
    return pd.Series(value + jitter, index=idx, dtype=float)


def synthetic_raw(sofr_spike_bp=0.0, rmp_bills_per_week_mn=0.0):
    rng = np.random.default_rng(1)
    raw = {
        "WALCL": _wed(lambda i: 7_000_000 + 1_000 * i),           # millions
        "WRESBAL": _wed(lambda i: 3_000_000 + 2_000 * rng.normal(size=len(i)).cumsum()),
        "WTREGEN": _wed(lambda i: 700_000 + 50_000 * np.sin(i / 8)),
        "RRPONTSYD": _daily(500.0),                                 # billions
        "WSHOSHO": _wed(lambda i: 6_000_000 + 3_000 * rng.normal(size=len(i)).cumsum()),
        "WSHOBL": _wed(300_000),
        "WSHOMCB": _wed(2_000_000),
        "WLCFLL": _wed(20_000),
        "SWPT": _wed(100),
        "RPONTSYD": _daily(2.0),
        "DGS1": _daily(4.0, noise=0.01),
        "DFF": _daily(4.3),
        "SOFR": _daily(4.31),
        "IORB": _daily(4.40),
        "IOER": pd.Series([0.25, 0.25], index=pd.to_datetime(["2014-01-02", "2014-01-03"])),
        "GDP": pd.Series(28_000.0, index=pd.date_range(START, END, freq="QS")),
        "NFCI": pd.Series(rng.normal(size=670), index=pd.date_range(START, periods=670, freq="W-FRI")),
    }
    if sofr_spike_bp:
        raw["SOFR"].loc["2026-09-14":"2026-09-30"] += sofr_spike_bp / 100
    if rmp_bills_per_week_mn:
        wed = raw["WSHOBL"].index >= pd.Timestamp("2025-12-12")
        bump = np.cumsum(wed) * rmp_bills_per_week_mn
        raw["WSHOBL"] = raw["WSHOBL"] + bump
        raw["WSHOSHO"] = raw["WSHOSHO"] + bump
    return raw


def test_build_produces_all_columns_and_units():
    out = indicators.build(indicators.prepare(synthetic_raw()))
    for col in indicators.SUB_INDICES:
        assert out[col].notna().sum() > 300, col
    last = out.dropna(subset=["composite"]).iloc[-1]
    assert last["reserves_gdp"] == pytest.approx(3_000_000 / 1000 / 28_000 * 100, rel=0.2)
    assert last.name <= pd.Timestamp(END) + pd.Timedelta(days=7)  # no empty future rows
    assert last["expected_easing_bp"] == pytest.approx(-(raw_last_dgs1() - 4.3) * 100, abs=5)


def raw_last_dgs1():
    return synthetic_raw()["DGS1"].iloc[-5:].mean()


def test_funding_spike_reads_as_tighter():
    base = indicators.build(indicators.prepare(synthetic_raw()))
    hit = indicators.build(indicators.prepare(synthetic_raw(sofr_spike_bp=40)))
    wk = "2026-09-25"
    assert hit.loc[wk, "stress"] < base.loc[wk, "stress"] - 1


def test_reserve_management_bill_buying_is_not_counted_as_easing():
    base = indicators.build(indicators.prepare(synthetic_raw()))
    rmp = indicators.build(indicators.prepare(synthetic_raw(rmp_bills_per_week_mn=10_000)))
    after = base.index >= pd.Timestamp("2026-03-01")
    np.testing.assert_allclose(rmp.loc[after, "policy_13w_gdp"], base.loc[after, "policy_13w_gdp"])
