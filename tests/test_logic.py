"""计算逻辑的单元测试（不联网）。网页解析用的是手写的简化 HTML，
真实网页格式要靠 GitHub Actions 上的实跑来验证。"""
from datetime import date

import numpy as np
import pandas as pd
import pytest

from fedmon import dotplot, dxy, fomc_calendar, implied


def test_median_odd_and_even():
    df = pd.DataFrame({"rate": [3.375, 3.625, 3.875], "count": [5, 9, 5]})
    assert dotplot.median_of(df) == 3.625
    df = pd.DataFrame({"rate": [3.375, 3.625], "count": [9, 9]})
    assert dotplot.median_of(df) == pytest.approx(3.5)


def test_parse_sep_table():
    html = """<table><thead><tr><th>Midpoint of target range or target level (percent)</th>
    <th>2025</th><th>2026</th><th>Longer run</th></tr></thead><tbody>
    <tr><td>3.875</td><td>2</td><td></td><td></td></tr>
    <tr><td>3.625</td><td>17</td><td>5</td><td>1</td></tr>
    <tr><td>3.125</td><td></td><td>14</td><td>3</td></tr>
    <tr><td>3.000</td><td></td><td></td><td>15</td></tr></tbody></table>"""
    df = dotplot.parse_sep(html)
    assert df.groupby("horizon")["count"].sum().to_dict() == {"2025": 19, "2026": 19, "Longer run": 19}
    df.insert(0, "sep_date", "2025-09-17")
    med = dotplot.medians(df).set_index("horizon")["median"]
    assert med["2025"] == 3.625 and med["2026"] == 3.125 and med["Longer run"] == 3.0


def test_prob_tree():
    # 当前 400-425；第一次会议预期 -0.4 档 → 40% 降 25bp
    t = implied.prob_tree(400, [-0.4, -1.0])
    assert t[0] == pytest.approx({375: 0.4, 400: 0.6})
    assert t[1] == pytest.approx({350: 0.4, 375: 0.6})


def test_zq_math_roundtrip():
    # 构造：EFFR 4.08，12/10 会议降 25bp → 12 月均值可反推
    effr = 4.08
    n, e = 31, 11  # 12 月 11 日生效
    dec_avg = (effr * (e - 1) + (effr - 0.25) * (n - e + 1)) / n
    prices = {(2025, 12): 100 - dec_avg, (2026, 1): 100 - (effr - 0.25)}
    path = implied.implied_from_zq(prices, [date(2025, 12, 10)], effr, date(2025, 12, 1))
    assert path[0]["r_post"] == pytest.approx(effr - 0.25)
    # 下个月没有会议时用下月合约
    prices2 = {(2025, 12): 100 - dec_avg}
    path2 = implied.implied_from_zq(prices2, [date(2025, 12, 10)], effr, date(2025, 12, 1))
    assert path2[0]["r_post"] == pytest.approx(effr - 0.25)


def test_zq_symbol():
    assert implied.zq_symbol(2026, 12) == "ZQZ26.CBT"
    assert implied.zq_symbol(2027, 1) == "ZQF27.CBT"


def test_dxy_formula():
    # 2024-01-02 左右的近似汇率，DXY 约 102.2
    fx = pd.DataFrame({"DEXUSEU": [1.0956], "DEXJPUS": [141.9], "DEXUSUK": [1.2620],
                       "DEXCAUS": [1.3327], "DEXSDUS": [10.12], "DEXSZUS": [0.8497]})
    v = dxy.compute(fx).iloc[0]
    assert 101 < v < 103.5


def test_parse_calendar():
    html = """<div class="panel"><div class="panel-heading"><h4>2026 FOMC Meetings</h4></div>
    <div class="row fomc-meeting"><div class="fomc-meeting__month"><strong>January</strong></div>
      <div class="fomc-meeting__date">27-28</div></div>
    <div class="row fomc-meeting"><div class="fomc-meeting__month"><strong>March</strong></div>
      <div class="fomc-meeting__date">17-18*</div></div>
    <div class="row fomc-meeting"><div class="fomc-meeting__month"><strong>Apr/May</strong></div>
      <div class="fomc-meeting__date">30-1</div></div></div>"""
    df = fomc_calendar.parse_calendar(html)
    assert list(df["end"]) == [date(2026, 1, 28), date(2026, 3, 18), date(2026, 5, 1)]
    assert list(df["sep"]) == [False, True, False]


def test_fedwatch_matrix():
    html = """<table><tr><th>MEETING DATE</th><th>350-375</th><th>375-400</th></tr>
    <tr><td>12/9/2026</td><td>62.5%</td><td>37.5%</td></tr></table>"""
    rows = implied.parse_fedwatch_matrix(html)
    assert rows == [{"date": "2026-12-09", "probs": {"3.50-3.75": 0.625, "3.75-4.00": 0.375}}]


def test_parse_bls():
    from fedmon import altsources
    js = {"Results": {"series": [{"seriesID": "LNS14000000", "data": [
        {"year": "2026", "period": "M09", "value": "4.4"},
        {"year": "2026", "period": "M08", "value": "4.3"},
        {"year": "2025", "period": "M13", "value": "4.2"}]}]}}
    s = altsources.parse_bls(js)["LNS14000000"]
    assert list(s.values) == [4.3, 4.4]
    assert s.index[-1] == pd.Timestamp(2026, 9, 1)
