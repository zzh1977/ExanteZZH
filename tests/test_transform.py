import numpy as np
import pandas as pd
import pytest

from liquidity import transform
from liquidity.config import SERIES


def test_wednesday_h41_value_lands_in_same_friday_row():
    s = pd.Series([100.0], index=[pd.Timestamp("2026-01-07")])  # Wednesday
    w = transform.to_weekly(s, lag_days=1)
    assert w.index[0] == pd.Timestamp("2026-01-09")  # that Friday


def test_friday_daily_value_waits_for_next_week():
    s = pd.Series([1.0, 2.0], index=pd.to_datetime(["2026-01-08", "2026-01-09"]))  # Thu, Fri
    w = transform.to_weekly(s, lag_days=1, how="mean")
    assert w.loc["2026-01-09"] == 1.0
    assert w.loc["2026-01-16"] == 2.0


@pytest.mark.parametrize("scale", [1.0, 1000.0])
def test_unit_detection_handles_millions_and_billions(scale):
    idx = pd.date_range("2021-01-06", periods=260, freq="W-WED")
    raw = pd.Series(np.linspace(7000, 6500, 260) * scale, index=idx)
    out = transform.to_billions(raw, SERIES["WALCL"])
    assert out.iloc[-1] == pytest.approx(6500)


def test_unit_detection_rejects_nonsense():
    idx = pd.date_range("2021-01-06", periods=10, freq="W-WED")
    with pytest.raises(transform.UnitError):
        transform.to_billions(pd.Series(42.0, index=idx), SERIES["WALCL"])


def test_zscores_do_not_look_ahead():
    rng = np.random.default_rng(0)
    s = pd.Series(rng.normal(size=400), index=pd.date_range("2015-01-02", periods=400, freq="W-FRI"))
    changed = s.copy()
    changed.iloc[300:] += 50
    for fn in (transform.expanding_z, transform.rolling_z):
        assert fn(s).iloc[:300].equals(fn(changed).iloc[:300])


def test_std_floor_caps_noise_in_flat_series():
    s = pd.Series(1e-6 * np.sin(np.arange(300)), index=pd.date_range("2015-01-02", periods=300, freq="W-FRI"))
    assert transform.rolling_z(s, std_floor=0.05).abs().max() < 0.01


def test_in_windows_open_ended():
    idx = pd.date_range("2025-11-07", periods=8, freq="W-FRI")
    mask = transform.in_windows(idx, [("2025-12-12", None)])
    assert not mask.loc["2025-12-05"] and mask.loc["2025-12-12"] and mask.iloc[-1]
