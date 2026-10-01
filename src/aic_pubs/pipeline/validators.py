"""Validation helpers for recovered article text."""
from __future__ import annotations

import re

ACCESS_MARKERS = (
    "institutional access",
    "sign in to access",
    "purchase this article",
    "subscribe to access",
    "access through your institution",
    "you do not have access",
    "enable javascript and cookies",
)


def validate_article_text(text, *, min_chars=1500):
    """Return (accepted, quality, reason) for candidate article text.

    This is intentionally conservative. Short or obvious access/navigation pages
    are not promoted to completed full text.
    """
    if not text:
        return False, None, "empty"
    compact = re.sub(r"\s+", " ", text).strip()
    lower = compact.lower()
    if any(marker in lower for marker in ACCESS_MARKERS) and len(compact) < 10000:
        return False, None, "access_page"
    if len(compact) < min_chars:
        return False, None, "too_short"
    words = re.findall(r"[A-Za-z]{3,}", compact)
    if len(words) < 200:
        return False, None, "low_text_density"
    quality = "high" if len(compact) >= 10000 else "medium"
    return True, quality, None
