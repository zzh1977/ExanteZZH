import pandas as pd

from liquidity import fred


def test_parse_fredgraph_csv_drops_missing_dots():
    text = "observation_date,DGS1\n2026-01-01,.\n2026-01-02,3.61\n"
    s = fred.parse_fredgraph_csv(text, "DGS1")
    assert list(s.index) == [pd.Timestamp("2026-01-02")] and s.iloc[0] == 3.61


def test_parse_api_json():
    payload = {"observations": [{"date": "2026-01-02", "value": "3.61"}, {"date": "2026-01-05", "value": "."}]}
    s = fred.parse_api_json(payload, "DGS1")
    assert len(s) == 1 and s.iloc[0] == 3.61


def test_cache_round_trip(tmp_path):
    s = pd.Series([1.0, 2.0], index=pd.to_datetime(["2026-01-01", "2026-01-02"]), name="X")
    s.to_frame().to_csv(tmp_path / "X.csv")
    got = fred.fetch_series("X", cache_dir=tmp_path)
    assert got.equals(s.rename("X")) or (got.values == s.values).all()
