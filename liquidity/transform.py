"""Unit conversion, weekly alignment without look-ahead, and z-scores."""
import pandas as pd

from . import config
from .config import Series


class UnitError(ValueError):
    pass


def to_billions(raw: pd.Series, spec: Series) -> pd.Series:
    """Convert a USD series to billions, detecting millions vs billions.

    The 5-year peak must fall inside spec.plausible at exactly one of the two
    scales; otherwise the series is rejected so a bad unit can't slip through.
    """
    if spec.kind != "usd":
        return raw
    if spec.plausible is None:
        return raw * spec.default_scale
    recent = raw[raw.index >= raw.index.max() - pd.DateOffset(years=5)]
    peak = recent.abs().max()
    lo, hi = spec.plausible
    fits = [scale for scale in (1.0, 1e-3) if lo <= peak * scale <= hi]
    if len(fits) != 1:
        raise UnitError(f"{spec.id}: 5-year peak {peak:,.1f} does not match billions or millions "
                        f"for the range {spec.plausible}; check the series on FRED")
    return raw * fits[0]


def check_range(s: pd.Series, spec: Series) -> None:
    if spec.kind in ("pct", "usd_bn") and spec.plausible is not None:
        recent = s[s.index >= s.index.max() - pd.DateOffset(years=5)]
        lo, hi = spec.plausible
        if recent.min() < lo or recent.max() > hi:
            raise UnitError(f"{spec.id}: recent values {recent.min():.2f}..{recent.max():.2f} "
                            f"outside {spec.plausible}")


def to_weekly(s: pd.Series, lag_days: int, how: str = "last") -> pd.Series:
    """Re-date each observation to the day it became public, then bucket by week.

    A row dated Friday F only holds values released on or before F.
    """
    shifted = s.copy()
    shifted.index = shifted.index + pd.Timedelta(days=lag_days)
    grouped = shifted.resample(config.WEEK)
    return grouped.mean() if how == "mean" else grouped.last()


def expanding_z(s: pd.Series, min_periods: int = config.Z_EXPANDING_MIN,
                clip: float = config.Z_CLIP, std_floor: float = 0.0) -> pd.Series:
    """For level series: compares today with all history up to today."""
    mean = s.expanding(min_periods).mean()
    std = s.expanding(min_periods).std().clip(lower=std_floor)
    return ((s - mean) / std).clip(-clip, clip)


def rolling_z(s: pd.Series, window: int = config.Z_ROLLING_WINDOW,
              min_periods: int = config.Z_ROLLING_MIN, clip: float = config.Z_CLIP,
              std_floor: float = 0.0) -> pd.Series:
    """For flow / change series: compares today with the last few years.

    std_floor stops a near-constant stretch (e.g. years of zero facility use)
    from turning tiny wiggles into extreme scores.
    """
    mean = s.rolling(window, min_periods).mean()
    std = s.rolling(window, min_periods).std().clip(lower=std_floor)
    return ((s - mean) / std).clip(-clip, clip)


def in_windows(index: pd.DatetimeIndex, windows) -> pd.Series:
    mask = pd.Series(False, index=index)
    for start, end in windows:
        end_ts = pd.Timestamp(end) if end else index.max()
        mask |= (index >= pd.Timestamp(start)) & (index <= end_ts)
    return mask
