"""Run step 1:  python -m liquidity --out output

Downloads the FRED series, builds the weekly sub-indices, compares them with
NFCI and writes CSVs (plus a chart if matplotlib is installed).
"""
import argparse
import os
from pathlib import Path

from . import fred, indicators, validate
from .config import SERIES


def main(argv=None):
    p = argparse.ArgumentParser(description="USD liquidity index, step 1 (FRED data)")
    p.add_argument("--start", default="2008-01-01", help="first date kept in the output")
    p.add_argument("--out", default="output")
    p.add_argument("--cache", default="data/raw")
    p.add_argument("--refresh", action="store_true", help="re-download instead of using the cache")
    p.add_argument("--api-key", default=os.environ.get("FRED_API_KEY"))
    args = p.parse_args(argv)

    raw = fred.fetch_all(SERIES, api_key=args.api_key, cache_dir=Path(args.cache), refresh=args.refresh)
    weekly = indicators.prepare(raw)
    idx = indicators.build(weekly).loc[args.start:]
    idx = idx.dropna(how="all", subset=indicators.SUB_INDICES)

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    idx.to_csv(out / "liquidity_index.csv", float_format="%.4f")
    summ = validate.summary(idx, weekly["NFCI"], indicators.SUB_INDICES)
    summ.to_csv(out / "validation_nfci.csv")
    validate.lead_lag(idx, weekly["NFCI"], indicators.SUB_INDICES).to_csv(out / "lead_lag_nfci.csv")

    last = idx.dropna(subset=["composite"]).iloc[-1]
    print(f"Latest week: {last.name.date()}")
    print(last[indicators.SUB_INDICES].round(2).to_string())
    print("\nVersus -NFCI (positive = moves with looser conditions):")
    print(summ.to_string())
    _chart(idx, out / "liquidity_index.png")
    print(f"\nWritten to {out.resolve()}")


def _chart(idx, path):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return
    fig, ax = plt.subplots(figsize=(11, 5))
    for col, color in [("stock", "#2a6fdb"), ("expectations", "#e08a1e"), ("stress", "#2b9a66")]:
        ax.plot(idx.index, idx[col], lw=1, color=color, alpha=0.8, label=col)
    ax.plot(idx.index, idx["composite"], lw=2, color="#222", label="composite")
    ax.axhline(0, color="#999", lw=0.8)
    ax.set_ylabel("z-score (positive = looser)")
    ax.set_title("USD liquidity sub-indices (step 1)")
    ax.legend(frameon=False, ncol=4)
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)


if __name__ == "__main__":
    main()
