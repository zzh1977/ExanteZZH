"""FOMC 会议日程：抓官网，失败用 config 里的兜底日程。"""
import logging
import re
from datetime import date

import pandas as pd
from bs4 import BeautifulSoup

from . import http
from .config import DATA, FOMC_FALLBACK

log = logging.getLogger(__name__)
CAL_URL = "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"
MONTHS = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july",
     "august", "september", "october", "november", "december"], 1)}
MON_ABBR = {k[:3]: v for k, v in MONTHS.items()}


def _month_num(tok: str) -> int:
    tok = tok.strip().lower().rstrip(".")
    return MONTHS.get(tok) or MON_ABBR[tok[:3]]


def parse_calendar(html: str) -> pd.DataFrame:
    """解析日程页。返回列: start, end(决议日), sep(bool)。"""
    soup = BeautifulSoup(html, "lxml")
    rows = []
    for panel in soup.select("div.panel"):
        head = panel.find(["h4", "h3", "h5"])
        m = re.search(r"(\d{4})\s+FOMC Meetings", head.get_text(" ") if head else "")
        if not m:
            continue
        year = int(m.group(1))
        for mt in panel.select(".fomc-meeting"):
            mon_el = mt.select_one(".fomc-meeting__month")
            day_el = mt.select_one(".fomc-meeting__date")
            if not (mon_el and day_el):
                continue
            mon_txt = mon_el.get_text(" ", strip=True)
            day_txt = day_el.get_text(" ", strip=True)
            if re.search(r"unscheduled|notation|cancel", day_txt + mt.get_text(" "), re.I):
                continue
            sep = "*" in day_txt
            days = [int(d) for d in re.findall(r"\d+", day_txt)]
            mons = [_month_num(x) for x in re.split(r"[/\-]", mon_txt) if x.strip()]
            if not days or not mons:
                continue
            m1, m2 = mons[0], mons[-1]
            d1, d2 = days[0], days[-1]
            try:
                start = date(year, m1, d1)
                end = date(year, m2, d2)
            except ValueError:
                continue
            rows.append({"start": start, "end": end, "sep": sep})
    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.drop_duplicates("end").sort_values("end").reset_index(drop=True)
    return df


def fallback() -> pd.DataFrame:
    return pd.DataFrame(
        [{"start": date.fromisoformat(s), "end": date.fromisoformat(e), "sep": p}
         for s, e, p in FOMC_FALLBACK])


def update() -> pd.DataFrame:
    try:
        html = http.get(CAL_URL).text
        df = parse_calendar(html)
        if len(df) < 8:
            raise ValueError(f"只解析到 {len(df)} 场会议")
        src = "federalreserve.gov"
    except Exception as e:
        log.warning("FOMC 日程抓取失败（%s），使用兜底日程", e)
        df, src = fallback(), "fallback"
    df["source"] = src
    DATA.mkdir(exist_ok=True)
    df.to_csv(DATA / "fomc_calendar.csv", index=False)
    return df


def load() -> pd.DataFrame:
    p = DATA / "fomc_calendar.csv"
    df = pd.read_csv(p) if p.exists() else fallback()
    for c in ("start", "end"):
        df[c] = pd.to_datetime(df[c]).dt.date
    return df


def upcoming(today: date | None = None) -> pd.DataFrame:
    today = today or date.today()
    df = load()
    return df[df["end"] >= today].reset_index(drop=True)
