"""Transparent rule-based hawk/dove scorer.

A sentence is hawkish or dovish when a topic word appears with a direction
word, in the spirit of Gorodnichenko, Pham & Talavera (2023):
  inflation / activity rising        -> hawkish;  falling -> dovish
  unemployment / slack rising        -> dovish;   falling -> hawkish
plus explicit policy phrases (raise vs lower the target range, etc.).
It is a baseline and fallback for the model, not a replacement.
"""
import re

PRICE = r"inflation\w*|prices?|wages?|compensation|PCE|CPI"
ACTIVITY = (r"growth|economy|economic activity|spending|demand|output|GDP|employment|"
            r"hiring|payrolls?|job gains|labor market|labor demand")
SLACK = r"unemployment|jobless\w*|slack|layoffs?"
UP = (r"ris(e|es|ing)|rose|increas\w*|higher|high|elevated|accelerat\w*|strong\w*|robust|solid|"
      r"pick(s|ed)? up|(moved|edged|ticked|went|gone) up|firm|tight\w*|upward|surg\w*|persist\w*|above|hot")
DOWN = (r"declin\w*|fall(s|ing)?|fell|lower|low|decreas\w*|slow\w*|weak\w*|soft\w*|moderat\w*|"
        r"eased|easing|subdued|below|downward|cool\w*|contract\w*|(moved|edged|ticked|went|come) down|deteriorat\w*")

HAWK_PHRASES = re.compile(
    r"rais(e|ed|ing) the target range|increas\w* (in )?the target range|further (policy )?tightening|"
    r"additional (policy )?firming|policy firming|sufficiently restrictive|more restrictive|"
    r"reduc\w* (its |the )?(securities )?holdings|balance sheet reduction|remov\w* (policy )?accommodation|"
    r"reduc\w* (in )?(the degree of )?(policy )?accommodation|upside risks? to inflation|higher for longer",
    re.I)
DOVE_PHRASES = re.compile(
    r"lower(ed|ing)? the target range|reduc\w* the target range|cut(s|ting)? (in )?(the )?(policy |interest )?rates?|"
    r"rate cuts?|remain(s)? accommodative|highly accommodative|additional accommodation|"
    r"asset purchases|increas\w* (its )?holdings|be patient|downside risks?|support the economy|"
    r"provide (additional )?support",
    re.I)


def _pair(topic: str, direction: str) -> re.Pattern:
    # topic and direction within ~6 words of each other, in either order
    gap = r"(?:\W+\w+){0,6}?\W+"
    return re.compile(rf"\b({topic})\b{gap}\b({direction})\b|\b({direction})\b{gap}\b({topic})\b", re.I)


RULES = [
    (_pair(PRICE, UP), "hawk"), (_pair(PRICE, DOWN), "dove"),
    (_pair(ACTIVITY, UP), "hawk"), (_pair(ACTIVITY, DOWN), "dove"),
    (_pair(SLACK, UP), "dove"), (_pair(SLACK, DOWN), "hawk"),
]


def score_sentence(s: str) -> int:
    """+1 dovish, -1 hawkish, 0 neutral or mixed."""
    if HAWK_PHRASES.search(s) and not DOVE_PHRASES.search(s):
        return -1
    if DOVE_PHRASES.search(s) and not HAWK_PHRASES.search(s):
        return 1
    hawk = sum(1 for pat, side in RULES if side == "hawk" and pat.search(s))
    dove = sum(1 for pat, side in RULES if side == "dove" and pat.search(s))
    return (dove > hawk) - (hawk > dove)


def score_sentences(sentences: list[str]) -> list[int]:
    return [score_sentence(s) for s in sentences]
