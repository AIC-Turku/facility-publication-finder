"""Text normalisation, PDF extraction and evidence-sentence selection."""
import re

_HYPHEN_BREAK = re.compile(r"(\w)[-­]\s+(\w)")
_SPACE = re.compile(r"\s+")
_SENTENCE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9(])")


def normalise(text: str) -> str:
    """Undo PDF line-break hyphenation ("Cell Imag- ing") and collapse whitespace.

    Joining every "x- y" also joins genuine compounds split at a line end
    ("spinning- disk" -> "spinningdisk"), so patterns should allow optional
    separators rather than rely on hyphens.
    """
    if not text:
        return ""
    return _SPACE.sub(" ", _HYPHEN_BREAK.sub(r"\1\2", text)).strip()


def pdf_text(data):
    try:
        import pymupdf
    except ImportError:  # older PyMuPDF
        import fitz as pymupdf
    try:
        with pymupdf.open(stream=data, filetype="pdf") as doc:
            return "\n".join(page.get_text() for page in doc)
    except Exception:
        return None


def sentences(text: str) -> list[str]:
    return _SENTENCE.split(text)


_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(\.[\w-]+)+")
MAX_SENTENCE_CHARS = 600


def redact(sentence, limit=MAX_SENTENCE_CHARS):
    """What may be stored/published from a paper: no e-mail addresses, bounded length."""
    return _EMAIL.sub("[email]", sentence.strip())[:limit]


def evidence(text, patterns, max_sentences=14, max_chars=3500):
    """Sentences that match any pattern, in document order, de-duplicated.

    This is what a human or an LLM reviews, so it must be enough to decide
    "was the imaging done at the facility?" without the full paper.
    """
    picked, seen, total = [], set(), 0
    for s in sentences(text):
        if any(p.search(s) for p in patterns):
            s = redact(s)
            if s in seen:
                continue
            seen.add(s)
            picked.append(s)
            total += len(s)
            if len(picked) >= max_sentences or total >= max_chars:
                break
    return picked


def matches_paper(text: str, doi: str | None = None, title: str | None = None,
                  min_title_share: float = 0.5) -> bool:
    """False when the text is evidently another paper's: it contains neither the DOI
    nor at least half of the title's words. Unknown when there is no title (True).

    Found in 2025: UTUPub items whose TEXT file belongs to a different article, and ÅA
    records whose PDF was attached to every DOI of the record (datasets, cited DOIs).
    """
    if not text:
        return False
    if doi and doi.lower() in re.sub(r"\s+", "", text.lower()):
        return True
    words = re.findall(r"[a-z0-9]{4,}", (title or "").lower())
    if len(words) < 3:
        return True
    body = set(re.findall(r"[a-z0-9]{4,}", text[:30000].lower()))
    return sum(w in body for w in words) / len(words) >= min_title_share


# ------------------------------------------------------------- article check
ACCESS_MARKERS = (
    "institutional access",
    "sign in to access",
    "purchase this article",
    "subscribe to access",
    "access through your institution",
    "you do not have access",
    "enable javascript and cookies",
)


def validate_article_text(text: str | None, *, min_chars: int = 1500) -> tuple[bool, str | None, str | None]:
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
