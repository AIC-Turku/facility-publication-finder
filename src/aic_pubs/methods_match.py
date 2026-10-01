"""Small, explainable near-duplicate matcher for Methods text.

This is a prototype for detecting lightly edited text generated from canonical AIC
Methods descriptions. It intentionally uses character n-grams and Jaccard similarity
rather than embeddings so every score is deterministic and dependency-free.
"""
from __future__ import annotations

import re
import unicodedata


def normalize_methods_text(text):
    text = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode().lower()
    text = re.sub(r"https?://\S+|doi:\s*\S+", " ", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split())


def char_ngrams(text, n=5):
    text = normalize_methods_text(text)
    compact = text.replace(" ", "_")
    if not compact:
        return set()
    if len(compact) <= n:
        return {compact}
    return {compact[i:i + n] for i in range(len(compact) - n + 1)}


def jaccard_methods_similarity(a, b, n=5):
    """0..1 similarity between two Methods passages."""
    left, right = char_ngrams(a, n=n), char_ngrams(b, n=n)
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def best_methods_match(passage, references, threshold=0.45, n=5):
    """Return the best canonical match if it clears the review threshold.

    references can be either {id: text} or an iterable of (id, text).
    """
    items = references.items() if hasattr(references, "items") else references
    best = None
    for ref_id, ref_text in items:
        score = jaccard_methods_similarity(passage, ref_text, n=n)
        if best is None or score > best["score"]:
            best = {"reference_id": ref_id, "score": score, "reference_text": ref_text}
    return best if best and best["score"] >= threshold else None
