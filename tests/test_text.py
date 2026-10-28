from datetime import date

import pandas as pd
import pytest

from liquidity.text import aggregate, dictionary, model, sentences, sources


def test_calendar_links_cover_old_and_new_url_patterns():
    html = ('<a href="/newsevents/pressreleases/monetary20240131a.htm">HTML</a>'
            '<a href="/newsevents/press/monetary/20080130a.htm">Statement</a>'
            '<a href="/newsevents/pressreleases/monetary20240131a1.htm">Implementation note</a>'
            '<a href="/monetarypolicy/fomcminutes20240131.htm">Minutes</a>')
    st, mi = sources.parse_calendar_links(html)
    assert set(st) == {"20240131", "20080130"}
    assert st["20080130"] == "https://www.federalreserve.gov/newsevents/press/monetary/20080130a.htm"
    assert set(mi) == {"20240131"}


def test_speech_links_from_html_or_json():
    raw = '{"l":"/newsevents/speech/powell20240131a.htm"} <a href="/newsevents/speech/waller20231128a.htm">'
    assert sources.parse_speech_links(raw) == {
        "/newsevents/speech/powell20240131a.htm": ("powell", "20240131"),
        "/newsevents/speech/waller20231128a.htm": ("waller", "20231128")}


@pytest.mark.parametrize("head,role", [
    ("Speech\nChair Jerome H. Powell\nAt the Economic Club", "chair"),
    ("Speech\nVice Chair Philip N. Jefferson\nAt ...", "vice_chair"),
    ("Speech\nVice Chair for Supervision Michael S. Barr\n", "vice_chair_supervision"),
    ("Speech\nGovernor Christopher J. Waller\n", "governor"),
])
def test_speaker_role(head, role):
    assert sources.speaker_role(head) == role


def test_page_text_prefers_article():
    html = "<html><nav>Menu inflation rising</nav><div id='article'><p>Body text.</p></div></html>"
    assert sources.page_text(html) == "Body text."


def test_minutes_release_lag():
    doc = sources.Doc("minutes-20240131", "minutes", "u", date(2024, 1, 31), date(2024, 2, 21))
    assert doc.weight == sources.WEIGHTS["minutes"]


def test_split_sentences_keeps_abbreviations():
    text = "U.S. inflation rose in Sept. last year. The Committee decided to keep rates unchanged today."
    out = sentences.split_sentences(text, min_words=3)
    assert out == ["U.S. inflation rose in Sept. last year.", "The Committee decided to keep rates unchanged today."]


@pytest.mark.parametrize("s,expected", [
    ("The Committee decided to raise the target range for the federal funds rate to 5 percent.", -1),
    ("The Committee decided to lower the target range for the federal funds rate.", 1),
    ("Inflation remains elevated.", -1),
    ("Inflation has moderated substantially over the past year.", 1),
    ("The unemployment rate has moved up and job gains have slowed.", 1),
    ("The unemployment rate remains low.", -1),
    ("The unemployment rate has moved up.", 1),
    ("Inflation has come down over the past year.", 1),
    ("The Committee seeks to achieve maximum employment and inflation at the rate of 2 percent.", 0),
])
def test_dictionary_rules(s, expected):
    assert dictionary.score_sentence(s) == expected


def test_label_resolution_uses_documented_order_and_checks_anchors():
    ids = {0: "LABEL_0", 1: "LABEL_1", 2: "LABEL_2"}
    ok = model.resolve_labels(ids, {"hawk": [1, 1, 1], "dove": [0, 0, 2]})
    assert ok == {0: "dove", 1: "hawk", 2: "neutral"}
    with pytest.raises(RuntimeError):
        model.resolve_labels(ids, {"hawk": [0, 0, 0], "dove": [1, 1, 1]})


def test_label_resolution_prefers_names():
    ids = {0: "Hawkish", 1: "Dovish", 2: "Neutral"}
    assert model.resolve_labels(ids, {"hawk": [0, 0, 0], "dove": [1, 1, 1]})[0] == "hawk"


def test_weekly_tone_decays_and_has_no_lookahead():
    docs = pd.DataFrame({
        "release_date": ["2026-01-07", "2026-01-21"], "dict_tone": [1.0, -1.0], "weight": [1.0, 1.0]})
    w = aggregate.weekly_tone(docs, "dict_tone", start="2026-01-02", end="2026-01-30")
    assert pd.isna(w.loc["2026-01-02"])            # nothing released yet
    assert w.loc["2026-01-09"] == 1.0             # only the first document
    assert w.loc["2026-01-16"] == 1.0
    # two weeks older = half the weight: (0.5 * 1 + 1 * -1) / 1.5
    assert w.loc["2026-01-23"] == pytest.approx(-1 / 3)
