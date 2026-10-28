"""FOMC-RoBERTa hawk/dove classifier (Shah, Paturi & Chava, ACL 2023).

Runs on CPU. The label order is checked on anchor sentences before scoring,
so a changed or misread label map stops the run instead of flipping signs.
Model licence (CC BY-NC 4.0 per its model card at the time of writing):
check it before any commercial use.
"""
MODEL_NAME = "gtfintechlab/FOMC-RoBERTa"
DOCUMENTED = {0: "dove", 1: "hawk", 2: "neutral"}  # LABEL_0/1/2 per the model card

ANCHORS = {
    "hawk": [
        "The Committee decided to raise the target range for the federal funds rate.",
        "Inflation remains elevated, and additional policy firming may be appropriate.",
        "Participants agreed that policy would need to remain restrictive for some time.",
    ],
    "dove": [
        "The Committee decided to lower the target range for the federal funds rate.",
        "With inflation subdued and unemployment rising, further rate cuts would be appropriate.",
        "The Committee will maintain a highly accommodative stance of monetary policy.",
    ],
}


def resolve_labels(id2label: dict[int, str], anchor_preds: dict[str, list[int]]) -> dict[int, str]:
    """Map model label ids to hawk/dove/neutral and confirm on anchors.

    Uses names when the model provides them, else the documented order.
    Raises if the anchors disagree with the mapping.
    """
    named = {}
    for i, name in id2label.items():
        n = str(name).lower()
        if "hawk" in n:
            named[int(i)] = "hawk"
        elif "dov" in n:
            named[int(i)] = "dove"
        elif "neutral" in n:
            named[int(i)] = "neutral"
    mapping = named if len(named) == 3 else dict(DOCUMENTED)
    for side, preds in anchor_preds.items():
        hits = sum(mapping.get(p) == side for p in preds)
        if hits < len(preds) - 1:  # allow one miss per side
            raise RuntimeError(f"Label check failed for {side}: predictions {preds} under {mapping}")
    return mapping


class RobertaScorer:
    def __init__(self, model_name: str = MODEL_NAME, batch_size: int = 32, max_length: int = 256):
        import torch
        from transformers import AutoModelForSequenceClassification, AutoTokenizer

        self.torch = torch
        self.tok = AutoTokenizer.from_pretrained(model_name)
        self.model = AutoModelForSequenceClassification.from_pretrained(model_name).eval()
        self.batch_size, self.max_length = batch_size, max_length
        preds = {side: self._predict(sents) for side, sents in ANCHORS.items()}
        self.labels = resolve_labels(self.model.config.id2label, preds)
        print(f"FOMC-RoBERTa labels: {self.labels}; anchors: {preds}")

    def _predict(self, sentences: list[str]) -> list[int]:
        out = []
        with self.torch.inference_mode():
            for i in range(0, len(sentences), self.batch_size):
                enc = self.tok(sentences[i:i + self.batch_size], padding=True, truncation=True,
                               max_length=self.max_length, return_tensors="pt")
                out += self.model(**enc).logits.argmax(-1).tolist()
        return out

    def score_sentences(self, sentences: list[str]) -> list[int]:
        """+1 dovish, -1 hawkish, 0 neutral."""
        sign = {"dove": 1, "hawk": -1, "neutral": 0}
        return [sign[self.labels[p]] for p in self._predict(sentences)]
