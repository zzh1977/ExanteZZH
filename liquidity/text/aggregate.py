"""Turn per-document tone into a weekly series.

Each Friday's value is a weighted average of the tone of every document
released on or before that day, with weights decaying by half every
HALF_LIFE_DAYS. Weeks with no document in the past STALE_DAYS are left empty.
"""
import numpy as np
import pandas as pd

from .. import config

HALF_LIFE_DAYS = 14
STALE_DAYS = 120
SPEECH_SHRINK = 10  # a speech with n policy sentences counts n / (n + 10) of its weight


def weekly_tone(docs: pd.DataFrame, tone_col: str, start=None, end=None,
                half_life: float = HALF_LIFE_DAYS) -> pd.Series:
    d = docs.dropna(subset=[tone_col]).copy()
    if d.empty:
        return pd.Series(dtype=float, name=tone_col)
    rel = pd.to_datetime(d["release_date"]).to_numpy("datetime64[D]")
    tone = d[tone_col].to_numpy(float)
    weight = d["weight"].to_numpy(float)
    if "n_relevant" in d and "kind" in d:
        n = d["n_relevant"].to_numpy(float)
        is_speech = (d["kind"] == "speech").to_numpy()
        weight = weight * (is_speech * (n / (n + SPEECH_SHRINK)) + ~is_speech)
    start = pd.Timestamp(start) if start else pd.Timestamp(rel.min())
    end = pd.Timestamp(end) if end else pd.Timestamp(rel.max()) + pd.Timedelta(days=7)
    fridays = pd.date_range(start, end, freq=config.WEEK)
    out = np.full(len(fridays), np.nan)
    for i, f in enumerate(fridays.to_numpy("datetime64[D]")):
        age = (f - rel).astype(float)
        mask = age >= 0
        if not mask.any() or age[mask].min() > STALE_DAYS:
            continue
        w = weight[mask] * 0.5 ** (age[mask] / half_life)
        out[i] = np.sum(w * tone[mask]) / np.sum(w)
    return pd.Series(out, index=fridays, name=tone_col)
