"""Sentence splitting and the policy-relevance filter.

Only sentences that mention inflation, activity, the labor market or policy
are scored (the same idea as the keyword filter in Shah et al. 2023). This
drops boilerplate and cuts model run time several-fold.
"""
import re

ABBREV = ["U.S.", "U.K.", "Mr.", "Ms.", "Mrs.", "Dr.", "Jan.", "Feb.", "Aug.", "Sept.", "Oct.",
          "Nov.", "Dec.", "St.", "No.", "vs.", "e.g.", "i.e.", "a.m.", "p.m.", "Inc.", "Co."]
_PLACEHOLDER = "․"  # one-dot leader, never in source text

RELEVANT = re.compile(
    r"\b(inflation\w*|prices?|wages?|compensation|PCE|CPI|"
    r"growth|economy|economic activity|spending|demand|output|GDP|"
    r"employment|unemployment|labor market|jobs?|payrolls?|hiring|slack|"
    r"federal funds|target range|policy rate|interest rates?|monetary policy|policy stance|"
    r"accommodat\w*|tighten\w*|firming|restrictive|eas(e|ing)|"
    r"balance sheet|asset purchases|securities holdings|purchases)\b",
    re.I,
)


def split_sentences(text: str, min_words: int = 6, max_words: int = 120) -> list[str]:
    t = re.sub(r"\s+", " ", text)
    for a in ABBREV:
        t = t.replace(a, a.replace(".", _PLACEHOLDER))
    parts = re.split(r"(?<=[.!?])\s+(?=[\"'(\[]?[A-Z])", t)
    out = []
    for p in parts:
        s = p.replace(_PLACEHOLDER, ".").strip()
        n = len(s.split())
        if min_words <= n <= max_words:
            out.append(s)
    return out


def relevant(sentences: list[str]) -> list[str]:
    return [s for s in sentences if RELEVANT.search(s)]
