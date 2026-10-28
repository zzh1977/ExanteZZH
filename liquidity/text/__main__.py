"""Hawk/dove text scores:  python -m liquidity.text --scorers dict,model

1. find FOMC statements, minutes and Board speeches since --start;
2. download them (raw HTML cached under data/text/raw, not committed);
3. score policy-relevant sentences with the dictionary and/or FOMC-RoBERTa;
4. write per-document scores and a weekly decayed tone series.

Outputs (data/text/): doc_scores.csv, weekly_tone.csv, fetch_report.csv,
latest_sentences.csv (recent sentences with labels, for spot checks).
"""
import argparse
import time
from dataclasses import asdict
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from . import aggregate, dictionary, sentences, sources

KEY_COLS = ["doc_id", "kind", "url", "event_date", "release_date", "speaker", "role", "weight"]


def tone(scores: list[int]) -> float | None:
    if not scores:
        return None
    return (sum(s > 0 for s in scores) - sum(s < 0 for s in scores)) / len(scores)


def save(rows: dict, old: pd.DataFrame, path: Path) -> pd.DataFrame:
    """Write per-document scores, keeping earlier rows for documents not fetched this time."""
    new = pd.DataFrame(list(rows.values())).set_index("doc_id")
    if not old.empty:
        new = pd.concat([new, old.loc[~old.index.isin(new.index)]])
    new = new.sort_values(["release_date", "kind"])
    new.to_csv(path)
    return new


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--start", type=int, default=2008)
    p.add_argument("--data", default="data/text")
    p.add_argument("--scorers", default="dict,model")
    p.add_argument("--rescore", action="store_true", help="re-run the model on every document")
    args = p.parse_args(argv)
    data = Path(args.data)
    scorers = set(args.scorers.split(","))

    fetcher = sources.Fetcher(data / "raw")
    docs = sources.discover(fetcher, args.start)
    print(f"found {len(docs)} documents")
    texts = sources.fetch_texts(fetcher, docs)
    print(f"fetched {len(texts)} texts")
    rep = sources.report(docs, texts)
    rep.to_csv(data / "fetch_report.csv", index=False)
    print(rep.pivot_table(index="year", columns="group", values="fetched", aggfunc="sum").fillna(0).astype(int).to_string())

    old_path = data / "doc_scores.csv"
    old = pd.read_csv(old_path).set_index("doc_id") if old_path.exists() else pd.DataFrame()

    rows, todo = {}, []
    for d in docs:
        if d.doc_id not in texts:
            continue
        rel = sentences.relevant(sentences.split_sentences(texts[d.doc_id]))
        dict_scores = dictionary.score_sentences(rel)
        row = {**asdict(d), "event_date": d.event_date.isoformat(), "release_date": d.release_date.isoformat(),
               "weight": d.weight, "n_relevant": len(rel),
               "dict_hawk": sum(s < 0 for s in dict_scores), "dict_dove": sum(s > 0 for s in dict_scores),
               "dict_tone": tone(dict_scores)}
        prev = old.loc[d.doc_id] if d.doc_id in old.index else None
        if prev is not None and "model_tone" in prev and pd.notna(prev["model_tone"]) and not args.rescore:
            for c in ("model_hawk", "model_dove", "model_tone"):
                row[c] = prev[c]
        elif "model" in scorers and rel:
            todo.append((d.doc_id, rel))
        rows[d.doc_id] = row

    recent_cut = (date.today() - timedelta(days=60)).isoformat()
    sample = []
    scorer = None
    if todo:
        try:
            from .model import RobertaScorer
            scorer = RobertaScorer()
        except Exception as e:  # keep the dictionary results if the model can't run
            print(f"MODEL UNAVAILABLE, dictionary only: {type(e).__name__}: {e}")
    if scorer:
        total = sum(len(r) for _, r in todo)
        print(f"model: scoring {total} sentences in {len(todo)} documents")
        t0, done = time.time(), 0
        for k, (doc_id, rel) in enumerate(todo):
            ms = scorer.score_sentences(rel)
            rows[doc_id].update(model_hawk=sum(s < 0 for s in ms), model_dove=sum(s > 0 for s in ms),
                                model_tone=tone(ms))
            if rows[doc_id]["release_date"] >= recent_cut:
                ds = dictionary.score_sentences(rel)
                sample += [{"doc_id": doc_id, "sentence": s, "dict": a, "model": b} for s, a, b in zip(rel, ds, ms)]
            done += len(rel)
            if k % 100 == 99:
                save(rows, old, old_path)  # checkpoint in case the job times out
            if k % 50 == 49:
                rate = done / (time.time() - t0)
                print(f"  {done}/{total} sentences, {rate:.1f}/s, ~{(total - done) / rate / 60:.0f} min left")

    new = save(rows, old, old_path)
    if sample:
        pd.DataFrame(sample).to_csv(data / "latest_sentences.csv", index=False)

    weekly = pd.DataFrame({
        "tone_dict": aggregate.weekly_tone(new.reset_index(), "dict_tone"),
        "tone_model": aggregate.weekly_tone(new.reset_index(), "model_tone")
        if "model_tone" in new else pd.Series(dtype=float),
    })
    has_dict = new["dict_tone"].notna().sum()
    has_model = new["model_tone"].notna().sum() if "model_tone" in new else 0
    use = "tone_model" if has_dict and has_model >= 0.95 * has_dict else "tone_dict"
    weekly["text_tone"] = weekly[use]
    weekly["source"] = use
    weekly.rename_axis("week").to_csv(data / "weekly_tone.csv")
    print(f"documents scored: dict {has_dict}, model {has_model}; weekly series uses {use}")
    print(weekly.dropna(subset=["text_tone"]).tail(6).round(3).to_string())


if __name__ == "__main__":
    main()
