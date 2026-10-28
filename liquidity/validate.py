"""Compare the sub-indices with the Chicago Fed NFCI.

NFCI is positive when conditions are tighter than average, so it is flipped:
loose = -NFCI. Correlations on overlapping weekly data are descriptive only;
they are heavily autocorrelated and carry no significance test.
"""
import pandas as pd

HORIZONS = (4, 13)
LAGS = range(-26, 27, 2)


def summary(index: pd.DataFrame, nfci: pd.Series, cols) -> pd.DataFrame:
    loose = -nfci.reindex(index.index)
    rows = []
    for c in cols:
        x = index[c]
        row = {"series": c, "weeks": int((x.notna() & loose.notna()).sum()),
               "corr_same_week": x.corr(loose)}
        for h in HORIZONS:
            row[f"corr_next_{h}w_change"] = x.corr(loose.shift(-h) - loose)
        rows.append(row)
    return pd.DataFrame(rows).set_index("series").round(3)


def lead_lag(index: pd.DataFrame, nfci: pd.Series, cols) -> pd.DataFrame:
    """Row k > 0: the index k weeks earlier vs NFCI now (index leads)."""
    loose = -nfci.reindex(index.index)
    return pd.DataFrame({c: {k: index[c].shift(k).corr(loose) for k in LAGS} for c in cols}).round(3)
