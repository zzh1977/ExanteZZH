"""Download FRED series, with a local CSV cache.

Without an API key the public fredgraph.csv endpoint is used. With a key
(env FRED_API_KEY or --api-key) the official API is used instead.
"""
import io
import time
from pathlib import Path

import pandas as pd
import requests

FREDGRAPH_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv"
API_URL = "https://api.stlouisfed.org/fred/series/observations"


def parse_fredgraph_csv(text: str, series_id: str) -> pd.Series:
    df = pd.read_csv(io.StringIO(text), na_values=["."])
    if df.shape[1] < 2:
        raise ValueError(f"{series_id}: unexpected CSV from FRED: {text[:200]!r}")
    values = df[series_id] if series_id in df.columns else df.iloc[:, 1]
    s = pd.Series(pd.to_numeric(values, errors="coerce").to_numpy(),
                  index=pd.to_datetime(df.iloc[:, 0]), name=series_id)
    return s.dropna().sort_index()


def parse_api_json(payload: dict, series_id: str) -> pd.Series:
    obs = payload.get("observations")
    if obs is None:
        raise ValueError(f"{series_id}: FRED API error: {payload.get('error_message', payload)}")
    s = pd.Series({pd.Timestamp(o["date"]): pd.to_numeric(o["value"], errors="coerce") for o in obs},
                  name=series_id, dtype=float)
    return s.dropna().sort_index()


def _download(series_id: str, api_key: str | None, session: requests.Session) -> pd.Series:
    if api_key:
        r = session.get(API_URL, params={"series_id": series_id, "api_key": api_key,
                                         "file_type": "json"}, timeout=60)
        r.raise_for_status()
        return parse_api_json(r.json(), series_id)
    r = session.get(FREDGRAPH_URL, params={"id": series_id}, timeout=60)
    r.raise_for_status()
    return parse_fredgraph_csv(r.text, series_id)


def fetch_series(series_id: str, api_key: str | None = None, cache_dir: Path | None = None,
                 refresh: bool = False, session: requests.Session | None = None,
                 retries: int = 3) -> pd.Series:
    cache = Path(cache_dir) / f"{series_id}.csv" if cache_dir else None
    if cache and cache.exists() and not refresh:
        s = pd.read_csv(cache, index_col=0, parse_dates=True).iloc[:, 0]
        s.name = series_id
        return s
    session = session or requests.Session()
    for attempt in range(retries + 1):
        try:
            s = _download(series_id, api_key, session)
            break
        except requests.RequestException:
            if attempt == retries:
                raise
            time.sleep(2 ** (attempt + 1))
    if s.empty:
        raise ValueError(f"{series_id}: FRED returned no observations")
    if cache:
        cache.parent.mkdir(parents=True, exist_ok=True)
        s.to_frame().to_csv(cache)
    return s


def fetch_all(ids, **kwargs) -> dict[str, pd.Series]:
    return {sid: fetch_series(sid, **kwargs) for sid in ids}
