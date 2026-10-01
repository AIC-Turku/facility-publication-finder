"""Embedding check list: which papers of a year read like the known AIC papers?

The yearly check list next to the rules (docs/protocol.md §4 step 5), not a replacement. It orders the papers of a swept year
by similarity to the confirmed papers of the OTHER years (facilities/<facility>/papers/), so that
papers with little or no explicit facility evidence can still be checked, most AIC-like first.

* Text: the imaging-heavy chunks of each paper, after removing acknowledgement and
  facility-name sentences, so the score cannot just re-learn "acknowledges AIC".
* Model: a small free sentence-embedding model (BAAI/bge-small-en-v1.5): sentence-transformers
  on a GPU when there is one (Colab T4: minutes per year), else fastembed on the CPU
  (~17 chunks/s on 4 cores: ~20 min per year; about twice that on Colab's 2-core CPU).
* Scores: the embedding score orders the sheet; a TF-IDF word-similarity score on the same
  chunks is a second column (on 2024 held out it did as well, at a fraction of the cost).
  Both use logistic regression, known papers vs the other papers of the other swept years
  (minus those the rules flag: many are AIC papers not on the list); with no other year
  swept, the mean cosine to the 5 nearest known papers.
* The target year's own known papers are never used for training (leave-one-year-out),
  so `recovered in top N` for that year is an honest held-out number.

Embeddings and chunks are derived from full text: they live under data/embeddings/
(git-ignored). The ranked sheet holds titles and scores only.
"""
from collections.abc import Callable, Iterable
from pathlib import Path
import csv
import re
import time
from functools import lru_cache

import numpy as np

from .config import data_root
from .sweep import cached_text, load_screened
from .text import normalise, sentences

DEFAULT_MODEL = "BAAI/bge-small-en-v1.5"
CHUNK_CHARS = 500
CHUNKS_PER_PAPER = 6
NEAR_DUPLICATE = 0.97
NO_TEXT_RETRY_DAYS = 30  # a known paper without reachable text is tried again after this  # cosine above which two papers are treated as versions of one paper
_IMAGING = re.compile(r"microscop|confocal|imag|fluoresc|stain|live[- ]cell|objective|airyscan|"
                      r"super-?resolution", re.I)


def _facility_terms():
    from .config import config_path
    return _terms_for(str(config_path()))


@lru_cache(maxsize=4)
def _terms_for(path):
    from .config import load
    return load(path).facility_terms


def chunks(text: str, n: int = CHUNKS_PER_PAPER, size: int = CHUNK_CHARS,
           drop: re.Pattern | None = None) -> list[str]:
    """The n most imaging-heavy ~size-character chunks, without facility/thanks sentences
    (facility.yaml `facility_name_terms`)."""
    drop = drop or _facility_terms()
    kept = [s for s in sentences(normalise(text or "")) if not drop.search(s)]
    out, cur = [], ""
    for s in kept:
        cur = f"{cur} {s}".strip()
        if len(cur) >= size:
            out.append(cur)
            cur = ""
    if cur:
        out.append(cur)
    ranked = sorted(out, key=lambda c: -len(_IMAGING.findall(c)))
    # a PDF "sentence" can be a whole table: cap the length, embedding cost grows with it
    return [c[:int(size * 1.2)] for c in ranked[:n]]


class Embedder:
    """The embedding model; any object with .model_name and .embed(list[str]) -> array
    works in its place. backend: "auto" (GPU via sentence-transformers if available,
    else fastembed on the CPU), "sentence-transformers" or "fastembed"."""

    def __init__(self, model=DEFAULT_MODEL, backend="auto"):
        if backend == "auto":
            try:
                import torch
                import sentence_transformers  # noqa: F401
                backend = "sentence-transformers" if torch.cuda.is_available() else "fastembed"
            except ImportError:
                backend = "fastembed"
        if backend == "sentence-transformers":
            from sentence_transformers import SentenceTransformer
            import torch
            self._m = SentenceTransformer(model, device="cuda" if torch.cuda.is_available() else "cpu")
            self._embed = lambda t: self._m.encode(t, batch_size=128, normalize_embeddings=True,
                                                    convert_to_numpy=True, show_progress_bar=False)
        else:
            from fastembed import TextEmbedding
            m = TextEmbedding(model)
            self._embed = lambda t: np.array(list(m.embed(t, batch_size=64)))
        # vectors from different backends are close but not identical: never mix them
        self.model_name = f"{model}|{backend}"

    def embed(self, texts):
        return np.asarray(self._embed(list(texts)), dtype=np.float32)


def paper_vectors(texts: dict[str, str], embedder) -> dict[str, tuple[np.ndarray, str]]:
    """{doi: (unit vector, chunk text)}: mean of the chunk embeddings of each paper."""
    items = [(d, chunks(t)) for d, t in texts.items()]
    items = [(d, c) for d, c in items if c]
    flat = [c for _, cs in items for c in cs]
    if not flat:
        return {}
    E = np.asarray(embedder.embed(flat), dtype=np.float32)
    out, i = {}, 0
    for d, cs in items:
        v = E[i:i + len(cs)].mean(0)
        i += len(cs)
        out[d] = (v / (np.linalg.norm(v) or 1.0), " ".join(cs))
    return out


def _existing_backend(model):
    """The backend whose stores already exist for `model` (most papers wins), so a notebook run
    on another runtime type (GPU vs CPU) reuses them instead of re-embedding every year."""
    best = (0, None)
    for backend in ("sentence-transformers", "fastembed"):
        n = sum(len(_load(p, f"{model}|{backend}")) for p in _emb_dir().glob(f"*__*{re.sub(r'[^A-Za-z0-9.-]+', '-', backend)}*.npz"))
        best = max(best, (n, backend), key=lambda x: x[0])
    return best[1]


def _emb_dir():
    return data_root() / "embeddings"


def store_path(name: str, model: str) -> Path:
    """data/embeddings/<name>__<model>.npz: one file per model and backend, so switching between
    the GPU and the CPU (or trying another model) never throws the other's vectors away."""
    import hashlib
    slug = re.sub(r"[^A-Za-z0-9.-]+", "-", model).strip("-")[:60]
    return _emb_dir() / f"{name}__{slug}-{hashlib.sha1(model.encode()).hexdigest()[:8]}.npz"


def _load_store(name, model):
    return _load(store_path(name, model), model)


def _replace(path, write):
    """Write through a temporary file, then rename: an interrupted save never leaves a
    truncated file behind (on Drive a Colab disconnect mid-save is common)."""
    import os
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    with open(tmp, "wb") as f:
        write(f)
    os.replace(tmp, path)


def _save(path, store, model):
    path.parent.mkdir(parents=True, exist_ok=True)
    dois = sorted(store)
    _replace(path, lambda f: np.savez_compressed(
        f, dois=np.array(dois, dtype=str), vectors=np.array([store[d][0] for d in dois], dtype=np.float32),
        texts=np.array([store[d][1] for d in dois], dtype=str), model=np.array(model)))


def _load(path, model=None):
    """{doi: (vector, chunk text)}, or {} when missing, unreadable (e.g. truncated) or made by
    another model/backend."""
    import zipfile
    if not path.exists():
        return {}
    try:
        z = np.load(path, allow_pickle=False)
        if model and str(z["model"]) != model:
            return {}
        dois = z["dois"].tolist()
        texts = z["texts"].tolist() if "texts" in z.files else [""] * len(dois)
        return {d: (v, t) for d, v, t in zip(dois, z["vectors"], texts)}
    except (OSError, ValueError, KeyError, EOFError, zipfile.BadZipFile):
        return {}


# ------------------------------------------------------------------ building
def _known_text(r):
    """Full text of one known paper: sweep cache of its year, then data/cache/known/, then the
    resolver (Europe PMC, Crossref), whose result is cached under data/cache/known/. A paper with
    no reachable text gets a `.none` marker there and is not fetched again (delete the markers
    to retry). Never raises: one failing paper never stops the build."""
    import gzip
    from .fulltext import resolve_text
    from .sweep import _cache_path
    d = r["doi"]
    try:
        for y in sorted({str(r.get("year") or ""), str(r.get("published") or "")[:4]} - {""}):
            text = cached_text(int(y), d)[0]
            if text:
                return text
        kpath = _cache_path("known", d)
        none = kpath.with_name(kpath.name.replace(".txt.gz", ".none"))
        if kpath.exists():
            with gzip.open(kpath, "rt", encoding="utf-8") as f:
                return f.read().partition("\n")[2] or None
        if none.exists() and time.time() - none.stat().st_mtime < NO_TEXT_RETRY_DAYS * 86400:
            return None
        paper = {"doi": d, "title": r.get("title", ""), "pmcid": r.get("pmcid") or None,
                 "epmc_id": r.get("europepmc_id") or None}
        res = resolve_text(paper)
        kpath.parent.mkdir(parents=True, exist_ok=True)
        if not res.text:
            from .http import _EXHAUSTED
            if not _EXHAUSTED:  # a host out of budget is not evidence that there is no text
                none.touch()
            return None
        _replace(kpath, lambda f: f.write(gzip.compress(f"{res.source}\n{res.text}".encode())))
        return res.text
    except Exception:  # noqa: BLE001 - truncated cache file, network error, ...
        return None


def _known_texts(known, progress=print, workers=8):
    """{doi: full text} for the known papers that have reachable text."""
    from concurrent.futures import ThreadPoolExecutor
    out = {}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for n, (r, text) in enumerate(zip(known, pool.map(_known_text, known)), 1):
            if text:
                out[r["doi"]] = text
            if n % 50 == 0:
                progress(f"  known papers: {n}/{len(known)} read, {len(out)} with text")
    return out


def build_known(embedder, progress: Callable[[str], None] = print, batch: int = 100,
                known: list[dict] | None = None) -> dict:
    """Embed the known papers; saved every `batch` papers, so an interrupted run resumes."""
    from .papers import load_papers
    known = load_papers() if known is None else known
    if not known:
        progress("no confirmed papers yet (facilities/<facility>/papers/): no check list. Paste the papers "
                 "you know into inbox.txt; the rules-based candidates are still listed.")
        return {}
    path = store_path("known", embedder.model_name)
    store = _load_store("known", embedder.model_name)
    current = {r["doi"] for r in known}
    store = {d: v for d, v in store.items() if d in current and v[1]}  # drop removed / text-less entries
    todo = [r for r in known if r["doi"] not in store]
    if store and not path.exists():  # migrated from the older layout: save under the new name
        _save(path, store, embedder.model_name)
    for i in range(0, len(todo), batch):
        store.update(paper_vectors(_known_texts(todo[i:i + batch], progress), embedder))
        _save(path, store, embedder.model_name)
    progress(f"known papers embedded: {len(store)}/{len(known)} (the rest have no reachable full text)")
    return store


def build_year(year: int, embedder, progress: Callable[[str], None] = print, batch: int = 200) -> dict:
    """Embed every paper of a swept year that has cached text; saved every `batch` papers."""
    path = store_path(str(year), embedder.model_name)
    store = _load_store(str(year), embedder.model_name)
    with_text = [r["doi"] for r in load_screened(year) if r.get("has_text")]
    keep = set(with_text)
    store = {d: v for d, v in store.items() if d in keep and v[1]}  # papers gone from the sweep, old stores
    todo = [d for d in with_text if d not in store]
    if store and not path.exists():  # migrated from the older layout: save under the new name
        _save(path, store, embedder.model_name)
    if todo:
        progress(f"{year}: embedding {len(todo)} papers")
    for i in range(0, len(todo), batch):
        texts = {d: t for d in todo[i:i + batch] if (t := cached_text(year, d)[0])}
        store.update(paper_vectors(texts, embedder))
        _save(path, store, embedder.model_name)
        progress(f"  {year}: {min(i + batch, len(todo))}/{len(todo)}")
    progress(f"{year}: {len(store)} papers embedded")
    return store


# ------------------------------------------------------------------ ranking
def _scores(X, pos, neg=None, k=5):
    """Logistic regression pos vs neg when neg is given, else mean cosine to the k nearest
    positives. X, pos, neg: row-normalised dense arrays or sparse matrices."""
    if neg is not None and neg.shape[0]:
        from scipy.sparse import issparse, vstack
        from sklearn.linear_model import LogisticRegression
        train = vstack([pos, neg]) if issparse(pos) else np.vstack([pos, neg])
        clf = LogisticRegression(C=1.0, class_weight="balanced", max_iter=2000)
        clf.fit(train, np.r_[np.ones(pos.shape[0]), np.zeros(neg.shape[0])])
        return np.asarray(clf.decision_function(X)), f"logistic regression ({pos.shape[0]} known vs {neg.shape[0]} other papers)"
    sims = X @ pos.T
    sims = sims.toarray() if hasattr(sims, "toarray") else np.asarray(sims)
    kk = min(k, sims.shape[1])
    return np.sort(sims, axis=1)[:, -kk:].mean(1), f"mean cosine to the {kk} nearest of {pos.shape[0]} known papers"


def training_sets(year, known_store, year_store, known_rows, other_stores=None, other_flagged=()):
    """(positive dois, negative dois) for scoring `year`, never using that year's known papers.

    other_stores: {doi: ...} of other swept years; their known and rule-flagged papers are
    left out of the negatives (a flagged paper is often an AIC paper missing from the list)."""
    target_known = {r["doi"] for r in known_rows if str(r.get("year")) == str(year)}
    pos = sorted(d for d in known_store if d not in target_known and d not in year_store)
    excluded = set(known_store) | {r["doi"] for r in known_rows} | set(other_flagged)
    neg = sorted(d for d in (other_stores or {}) if d not in excluded and d not in year_store)
    return pos, neg


def score_year(year, known_store, year_store, known_rows, other_stores=None, other_flagged=()):
    """{doi: (embedding score, tfidf score)} for the target year, and a method note."""
    pos, neg = training_sets(year, known_store, year_store, known_rows, other_stores, other_flagged)
    D = sorted(year_store)
    if not pos or not D:
        return {}, "none"
    other_stores = other_stores or {}
    vec = lambda store, ds: np.array([store[d][0] for d in ds], dtype=np.float32)
    # a known paper that is nearly the same text as a paper being scored (a preprint and its
    # journal version) would leak the answer: leave it out of the training set
    near = (vec(known_store, pos) @ vec(year_store, D).T).max(1) > NEAR_DUPLICATE
    pos = [d for d, n in zip(pos, near) if not n]
    if not pos:
        return {}, "none"
    s_emb, method = _scores(vec(year_store, D), vec(known_store, pos),
                            vec(other_stores, neg) if neg else None)
    from sklearn.feature_extraction.text import TfidfVectorizer
    txt = lambda store, ds: [store[d][1] for d in ds]
    corpus = txt(year_store, D) + txt(known_store, pos) + (txt(other_stores, neg) if neg else [])
    big = len(corpus) >= 50  # rare/ubiquitous-word cut-offs only make sense on a real corpus
    tf = TfidfVectorizer(min_df=2 if big else 1, max_df=0.5 if big else 1.0, sublinear_tf=True,
                         stop_words="english")
    try:
        tf.fit(corpus)
        s_tf, _ = _scores(tf.transform(txt(year_store, D)), tf.transform(txt(known_store, pos)),
                          tf.transform(txt(other_stores, neg)) if neg else None)
    except ValueError:  # no usable vocabulary (e.g. chunk texts missing from an old store)
        s_tf = np.zeros(len(D))
    return {d: (float(a), float(b)) for d, a, b in zip(D, s_emb, s_tf)}, method


SHEET_COLUMNS = ["rank", "doi", "link", "title", "embedding_score", "tfidf_score", "tfidf_rank",
                 "confirmed", "priority", "category", "microscopy_terms", "model", "rules_version"]


def rank_year(year, known_store, known_rows, other_years=(), out=None, model=None):
    """Write data/<year>/embedding_ranked.csv; return a summary for the held-out year."""
    from .provenance import rules_version
    if not model:
        raise ValueError("rank_year needs the model name of the stores (Embedder.model_name)")
    year_store = _load_store(str(year), model)
    other_stores, other_flagged = {}, set()
    for y in other_years:
        if y != year:
            other_stores.update(_load_store(str(y), model))
            other_flagged |= {r["doi"] for r in load_screened(y) if r.get("priority") in ("report", "check")}
    scores, method = score_year(year, known_store, year_store, known_rows, other_stores, other_flagged)
    out = out or data_root() / str(year) / "embedding_ranked.csv"
    if not scores:  # nothing to rank: leave an existing sheet (and its verdicts) alone
        return {"year": year, "method": method, "papers": 0, "known_with_text": 0,
                "rules_flagged_known": 0, "path": f"{out} (not rewritten: nothing to rank)",
                "top": {n: {"embedding": 0, "tfidf": 0, "microscopy_terms": 0,
                            "embedding_new_unflagged": 0} for n in (50, 100, 200, 300, 500)}}
    rows = {r["doi"]: r for r in load_screened(year)}
    listed = {r["doi"] for r in known_rows if str(r.get("year")) == str(year)}   # confirmed (+ Sheet "yes")
    order = sorted(scores, key=lambda d: (-scores[d][0], d))
    tf_order = sorted(scores, key=lambda d: (-scores[d][1], d))
    tf_rank = {d: i for i, d in enumerate(tf_order, 1)}
    version = rules_version()
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(SHEET_COLUMNS)
        for i, d in enumerate(order, 1):
            r = rows.get(d, {})
            w.writerow([i, d, f"https://doi.org/{d}", r.get("title", ""), round(scores[d][0], 4),
                        round(scores[d][1], 4), tf_rank[d], d in listed, r.get("priority", ""),
                        r.get("category", ""), r.get("microscopy_terms", ""), model or "", version])
    flagged = {d for d, r in rows.items() if r.get("priority") in ("report", "check")}
    terms_order = sorted(scores, key=lambda d: (-(rows.get(d, {}).get("microscopy_terms") or 0), d))
    known_here = set(order) & listed
    summary = {"year": year, "method": method, "papers": len(order), "known_with_text": len(known_here),
               "rules_flagged_known": len(flagged & known_here), "path": str(out), "top": {}}
    for n in (50, 100, 200, 300, 500):
        summary["top"][n] = {"embedding": len(set(order[:n]) & listed),
                             "tfidf": len(set(tf_order[:n]) & listed),
                             "microscopy_terms": len(set(terms_order[:n]) & listed),
                             "embedding_new_unflagged": sum(d not in listed and d not in flagged
                                                            for d in order[:n])}
    return summary


def format_summary(s: dict) -> str:
    lines = [f"{s['year']}: {s['papers']} papers with text, {s['known_with_text']} of them confirmed "
             f"(the rules flag {s['rules_flagged_known']}); {s['method']}",
             f"  known papers in the top N by:  {'embedding':>9}  {'TF-IDF':>6}  {'microscopy terms':>16}"
             f"  | to check (not known, not flagged)"]
    for n, v in s["top"].items():
        lines.append(f"  top {n:<4}{'':22}{v['embedding']:>9}  {v['tfidf']:>6}  {v['microscopy_terms']:>16}"
                     f"  | {v['embedding_new_unflagged']}")
    lines.append(f"  wrote {s['path']}")
    return "\n".join(lines)


def run(years: Iterable[int], model: str = DEFAULT_MODEL, embedder=None,
        progress: Callable[[str], None] = print, extra_known: Iterable[dict] = ()) -> list[dict]:
    """Embed the known papers and every swept year, then rank each year held-out.

    extra_known: [{doi, year}] validated "yes" in the Sheets but not yet in the repository,
    so the ranking learns from them straight away."""
    from .papers import load_papers
    embedder = embedder or Embedder(model, backend=_existing_backend(model) or "auto")
    known_rows = load_papers()
    filed = {r["doi"] for r in known_rows}
    known_rows += [dict(r) for r in extra_known if r["doi"] not in filed]
    known_store = build_known(embedder, progress, known=known_rows)
    if not known_store:
        return []
    swept = [y for y in years if (data_root() / str(y) / "screened.jsonl").exists()]
    for y in sorted(set(years) - set(swept)):
        progress(f"{y}: not swept yet (no data/{y}/screened.jsonl) - skipped")
    ready = []
    for y in swept:
        if build_year(y, embedder, progress):
            ready.append(y)
        else:
            progress(f"{y}: no cached full text here (data/cache/{y}/) - run `facility-pubs sweep --year {y}` "
                     f"in this folder first; skipped")
    return [rank_year(y, known_store, known_rows, other_years=ready, model=embedder.model_name)
            for y in ready]
