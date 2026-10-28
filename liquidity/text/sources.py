"""Find and download Fed documents: FOMC statements, minutes, Board speeches.

Links are found by URL pattern rather than page layout, so a redesign of
the listing pages does not silently drop documents. Every run writes a
fetch report (counts per type, year and role) so gaps are visible.
"""
import re
import time
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import requests
from bs4 import BeautifulSoup

BASE = "https://www.federalreserve.gov"
USER_AGENT = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
MINUTES_LAG_DAYS = 21  # minutes come out three weeks after the decision

STATEMENT_RE = re.compile(r'href="([^"]*?monetary/?(\d{8})a\.htm)"', re.I)
MINUTES_RE = re.compile(r'href="([^"]*?fomcminutes(\d{8})\.htm)"', re.I)
SPEECH_RE = re.compile(r'(/newsevents/speech/([a-z]+)(\d{8})([a-z]?)\.htm)', re.I)

# Document weights: committee texts carry the most information, then the
# Chair, Vice Chair, other Board members.
WEIGHTS = {"statement": 4.0, "minutes": 2.0, "chair": 3.0, "vice_chair": 2.0,
           "vice_chair_supervision": 1.5, "governor": 1.0}


@dataclass
class Doc:
    doc_id: str
    kind: str  # statement / minutes / speech
    url: str
    event_date: date
    release_date: date
    speaker: str = ""
    role: str = ""

    @property
    def weight(self) -> float:
        return WEIGHTS[self.kind] if self.kind != "speech" else WEIGHTS.get(self.role, 1.0)


class Fetcher:
    def __init__(self, cache_dir: Path, delay: float = 0.3):
        self.cache_dir = Path(cache_dir)
        self.delay = delay
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT, "Accept-Language": "en-US,en;q=0.9"})

    def get(self, url: str, cache: bool = True) -> str | None:
        path = self.cache_dir / re.sub(r"[^A-Za-z0-9._-]", "_", url.replace(BASE, ""))
        if cache and path.exists():
            return path.read_text(encoding="utf-8")
        for attempt in range(3):
            try:
                r = self.session.get(url, timeout=(10, 40))
                time.sleep(self.delay)
                if r.status_code == 404:
                    return None
                r.raise_for_status()
                if cache:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(r.text, encoding="utf-8")
                return r.text
            except requests.RequestException:
                if attempt == 2:
                    return None
                time.sleep(2 * (attempt + 1))
        return None


def _abs(href: str) -> str:
    return href if href.startswith("http") else BASE + (href if href.startswith("/") else "/" + href)


def _d(s: str) -> date:
    return date(int(s[:4]), int(s[4:6]), int(s[6:8]))


def parse_calendar_links(html: str) -> tuple[dict, dict]:
    """Statement and minutes links on an FOMC calendar page, keyed by date."""
    statements = {m.group(2): _abs(m.group(1)) for m in STATEMENT_RE.finditer(html)}
    minutes = {m.group(2): _abs(m.group(1)) for m in MINUTES_RE.finditer(html)}
    return statements, minutes


def parse_speech_links(html: str) -> dict:
    """Speech links keyed by path; works on HTML or JSON listings."""
    out = {}
    for m in SPEECH_RE.finditer(html):
        out[m.group(1).lower()] = (m.group(2).lower(), m.group(3))
    return out


def page_text(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "nav", "header", "footer", "noscript"]):
        tag.decompose()
    main = soup.select_one("#article") or soup.select_one("#content") or soup.find("main") or soup.body or soup
    text = main.get_text("\n")
    return re.sub(r"\n\s*\n+", "\n\n", text).strip()


ROLE_PATTERNS = [
    ("vice_chair_supervision", re.compile(r"Vice Chair(?:man)? for Supervision", re.I)),
    ("vice_chair", re.compile(r"\bVice Chair(?:man)?\b", re.I)),
    ("chair", re.compile(r"\bChair(?:man|woman)?\b", re.I)),
    ("governor", re.compile(r"\bGovernor\b", re.I)),
]


def speaker_role(text: str, head_chars: int = 600) -> str:
    """Role from the speech header, e.g. 'Chair Jerome H. Powell'."""
    head = text[:head_chars]
    for role, pat in ROLE_PATTERNS:
        if pat.search(head):
            return role
    return "governor"


def discover(fetcher: Fetcher, start_year: int, end_year: int | None = None) -> list[Doc]:
    end_year = end_year or date.today().year
    statements, minutes = {}, {}
    pages = [f"{BASE}/monetarypolicy/fomccalendars.htm"]
    pages += [f"{BASE}/monetarypolicy/fomchistorical{y}.htm" for y in range(start_year, end_year + 1)]
    for url in pages:
        html = fetcher.get(url, cache=False)
        if html:
            s, m = parse_calendar_links(html)
            statements.update(s)
            minutes.update(m)

    speeches = {}
    listing = [f"{BASE}/json/ne-speeches.json"]
    for y in range(start_year, end_year + 1):
        listing += [f"{BASE}/newsevents/speech/{y}-speeches.htm", f"{BASE}/newsevents/speech/{y}speech.htm"]
    for url in listing:
        html = fetcher.get(url, cache=False)
        if html:
            speeches.update(parse_speech_links(html))

    docs = []
    for ds, url in statements.items():
        d = _d(ds)
        if d.year >= start_year:
            docs.append(Doc(f"statement-{ds}", "statement", url, d, d))
    for ds, url in minutes.items():
        d = _d(ds)
        if d.year >= start_year:
            docs.append(Doc(f"minutes-{ds}", "minutes", url, d, d + timedelta(days=MINUTES_LAG_DAYS)))
    for path, (name, ds) in speeches.items():
        d = _d(ds)
        if d.year >= start_year:
            docs.append(Doc(f"speech-{Path(path).stem}", "speech", BASE + path, d, d, speaker=name))
    return sorted(docs, key=lambda x: (x.release_date, x.doc_id))


def fetch_texts(fetcher: Fetcher, docs: list[Doc]) -> dict[str, str]:
    texts = {}
    for doc in docs:
        html = fetcher.get(doc.url)
        if not html:
            continue
        texts[doc.doc_id] = page_text(html)
        if doc.kind == "speech":
            doc.role = speaker_role(texts[doc.doc_id])
    return texts


def report(docs: list[Doc], texts: dict[str, str]) -> pd.DataFrame:
    rows = [{**asdict(d), "year": d.event_date.year, "fetched": d.doc_id in texts,
             "chars": len(texts.get(d.doc_id, ""))} for d in docs]
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df["group"] = df["kind"].where(df["kind"] != "speech", "speech:" + df["role"].replace("", "unknown"))
    return (df.groupby(["year", "group"])
              .agg(found=("doc_id", "size"), fetched=("fetched", "sum"), median_chars=("chars", "median"))
              .reset_index())
