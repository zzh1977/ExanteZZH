"""FRED series used in step 1, with units, publication lags and sanity ranges.

Every USD amount is converted to billions of dollars. The unit of each series
is detected from its recent peak (see transform.to_billions), so a wrong guess
about millions vs billions fails loudly instead of silently skewing the index.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class Series:
    id: str
    desc: str
    kind: str  # "usd" (converted to billions), "pct" (percent), "index"
    lag_days: int  # days from observation date until the value is public
    plausible: tuple[float, float] | None = None  # 5-year peak, in billions or pct
    default_scale: float = 1e-3  # used for "usd" series without a plausible range


H41 = 1  # H.4.1 Wednesday data is released Thursday afternoon
DAILY = 1  # H.15 rates, SOFR, ON RRP and repo results come out the next business day

SERIES = {
    # Fed balance sheet (H.4.1)
    "WALCL": Series("WALCL", "Total assets, Wednesday level", "usd", H41, (3_000, 12_000)),
    "WRESBAL": Series("WRESBAL", "Reserve balances, week average", "usd", H41, (1_000, 6_000)),
    "WTREGEN": Series("WTREGEN", "Treasury General Account, Wednesday level", "usd", H41, (300, 3_000)),
    "RRPONTSYD": Series("RRPONTSYD", "Overnight reverse repo, daily", "usd", DAILY, (100, 3_500)),
    "WSHOSHO": Series("WSHOSHO", "Securities held outright, Wednesday level", "usd", H41, (3_000, 12_000)),
    "WSHOBL": Series("WSHOBL", "Treasury bills held outright, Wednesday level", "usd", H41, (50, 3_000)),
    "WSHOMCB": Series("WSHOMCB", "MBS held outright, Wednesday level", "usd", H41, (500, 5_000)),
    "WLCFLL": Series("WLCFLL", "Loans (discount window, BTFP, etc.), Wednesday level", "usd", H41, (10, 3_000)),
    "SWPT": Series("SWPT", "Central bank liquidity swaps, Wednesday level", "usd", H41, None, 1e-3),
    "RPONTSYD": Series("RPONTSYD", "Fed overnight repo incl. standing repo facility, daily", "usd", DAILY, (1, 1_500)),
    # Rates
    "DGS1": Series("DGS1", "1-year Treasury yield", "pct", DAILY, (-1, 20)),
    "DFF": Series("DFF", "Effective federal funds rate", "pct", DAILY, (-1, 20)),
    "SOFR": Series("SOFR", "Secured overnight financing rate", "pct", DAILY, (-1, 20)),
    "IORB": Series("IORB", "Interest on reserve balances (from 2021-07-29)", "pct", DAILY, (-1, 20)),
    "IOER": Series("IOER", "Interest on excess reserves (until 2021-07-28)", "pct", DAILY, None),
    # Scaling and validation
    "GDP": Series("GDP", "Nominal GDP, SAAR, quarterly", "usd_bn", 120, (15_000, 60_000)),
    "NFCI": Series("NFCI", "Chicago Fed National Financial Conditions Index", "index", 5, None),
}
# GDP is dated at the quarter start; the advance estimate comes ~30 days after
# quarter end, so ~120 days after the observation date.

# Reserve-management purchases: the Fed bought T-bills to keep reserves ample
# and said explicitly that this was not a change in policy stance. Inside these
# windows, bill and MBS changes are left out of the policy-purchase measure.
# End None = still running. Check the dates against FOMC implementation notes.
RMP_WINDOWS = [
    ("2019-10-15", "2020-03-14"),
    ("2025-12-12", None),
]

WEEK = "W-FRI"  # every weekly row holds what was public by Friday
Z_EXPANDING_MIN = 156  # weeks (3 years) before an expanding z-score starts
Z_ROLLING_WINDOW = 156
Z_ROLLING_MIN = 104
Z_CLIP = 4.0
