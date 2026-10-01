"""Year sweep: collect candidates from UTUPub, ÅA and Europe PMC, fetch full
text, screen, and append one JSON line per paper to data/<year>/screened.jsonl.

Re-running skips DOIs already in that file, so an interrupted run (e.g. a
Colab disconnect) resumes where it stopped.
"""
import os
import gzip
import hashlib
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import sources
from . import candidates
from .config import load
from .bookings import load_bookings, load_staff
from .screen import screen
from .fulltext import resolve_text

# Working data (candidate sets, screening results, full-text cache, embeddings, sheets).
# Default: data/ in the checkout; the notebooks set PUBS_DATA to a Google Drive folder.
DATA = Path(os.environ.get("PUBS_DATA") or Path(__file__).resolve().parents[2] / "data")


def _log(*a):
    print(*a, file=sys.stderr, flush=True)


def collect(year, cfg):
    """Complete local DOI universe plus global acknowledgement/funding leads."""
    science_only = cfg.raw.get("institutional_fields", "science") != "all"
    papers = candidates.institutional_universe(year, science_only=science_only,
                                              institutional_sources=cfg.institutional_sources)
    _log(f"Institutional {year}: {len(papers)} DOI records ({' + '.join(sorted(cfg.local_sources))}; "
         f"{'science fields only' if science_only else 'all fields'})")

    epmc = sources.europepmc_ack_search(
        year,
        cfg.raw["europepmc_search_terms"],
        cfg.raw.get("europepmc_grant_numbers", ()),
    )
    _log(f"Europe PMC acknowledgement search {year}: {len(epmc)} papers")
    for hit in epmc:
        candidates.merge_candidate(papers, hit, "europepmc_ack")
        for key in ("pmcid", "epmc_id"):
            if hit.get(key):
                papers[hit["doi"]][key] = hit[key]
    return papers

def _cache_path(year, doi):
    return DATA / "cache" / str(year) / (hashlib.sha1(doi.encode()).hexdigest() + ".txt.gz")


def _cache_meta_path(year, doi):
    return DATA / "cache" / str(year) / (hashlib.sha1(doi.encode()).hexdigest() + ".meta.json")


def cached_text_metadata(year, doi):
    """Structured provenance for cached text, or {} for legacy/no metadata."""
    path = _cache_meta_path(year, doi)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def cached_text(year, doi):
    """(text, source) from the local full-text cache, or (None, None)."""
    path = _cache_path(year, doi)
    if not path.exists():
        return None, None
    with gzip.open(path, "rt", encoding="utf-8") as f:
        src, _, text = f.read().partition("\n")
    meta = cached_text_metadata(year, doi)
    return text, meta.get("source") or src


def _store(year, doi, text, src, metadata=None):
    """Cache text plus structured source provenance.

    The gzip format remains backward compatible; the JSON sidecar carries richer
    metadata for new cache entries.
    """
    path = _cache_path(year, doi)
    meta_path = _cache_meta_path(year, doi)
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as f:
        f.write(f"{src}\n{text}")
    meta = {"source": src, **(metadata or {})}
    meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")


def cache_is_reusable(year, doi):
    """Whether cached text is suitable to skip retrieval on a future sweep."""
    text, source = cached_text(year, doi)
    if not text:
        return False
    meta = cached_text_metadata(year, doi)
    scope = meta.get("scope")
    if scope == "partial":
        return False
    from .pipeline.validators import validate_article_text
    accepted, _, _ = validate_article_text(text)
    if not accepted:
        return False
    if scope == "full":
        return True
    # Legacy entries have no scope. Only sources that historically represented
    # complete article text are trusted as reusable.
    return source in {
        "utupub",
        "abo",
        "europepmc",
        "crossref_fulltext",
        "openalex_oa",
    }


def completed_dois(path, year=None):
    """DOIs with usable reusable full text.

    Rows without text are intentionally *not* considered complete. Repository
    deposits often appear months after publication, so a later sweep must retry
    them rather than permanently freezing the first failed fetch.
    """
    path = Path(path)
    if not path.exists():
        return set()
    latest = {}
    for line in path.open(encoding="utf-8"):
        if line.strip():
            row = json.loads(line)
            latest[row["doi"]] = row
    complete = {doi for doi, row in latest.items() if row.get("has_text")}
    if year is None:
        return complete
    return {doi for doi in complete if cache_is_reusable(year, doi)}


def run(year, config_path=None, workers=4, limit=None, openalex_api_key=None):
    cfg = load(config_path) if config_path else load()
    out_dir = DATA / str(year)
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / "screened.jsonl"
    done = completed_dois(out, year=year)
    papers = collect(year, cfg)
    todo = [p for d, p in sorted(papers.items()) if d not in done][:limit]
    _log(f"{len(papers)} candidate DOIs, {len(done)} complete, {len(todo)} to fetch/screen")
    # the year's DOI universe: rows outside it (e.g. junk DOIs from older parsers) are ignored
    (out_dir / "universe.json").write_text(json.dumps(sorted(papers), indent=0), encoding="utf-8")
    previous = {r["doi"]: r for r in load_screened(year)} if out.exists() else {}

    history = acknowledging_authors(exclude_year=year)
    private = {"bookings": load_bookings(), "staff": load_staff()}

    def work(p):
        try:
            return _work(p)
        except Exception as exc:  # one bad record must not abort the whole sweep
            _log(f"  error on {p.get('doi')}: {type(exc).__name__}: {exc}")
            return None

    def _work(p):
        cached, cached_src = cached_text(year, p["doi"])
        text, src = (cached, cached_src) if cached is not None and cache_is_reusable(year, p["doi"]) \
            else (None, None)
        if text is None:
            result = resolve_text(p, openalex_api_key=openalex_api_key)
            text, src = result.text, result.source
            if not text and cached:  # a failed re-fetch falls back to what we already had
                text, src = cached, cached_src
            if not text and previous.get(p["doi"], {}).get("has_text"):
                return None  # never replace a screened row that had text with a "no text" row
            if text:
                _store(
                    year,
                    p["doi"],
                    text,
                    src,
                    metadata={
                        "url": result.url,
                        "license": result.license,
                        "version": result.version,
                    },
                )
        row = {k: p.get(k) for k in ("doi", "title", "journal", "year", "type", "fields",
                                     "local_authors", "units", "sources")}
        row["text_source"] = src
        row.update(screen(text, cfg, local=bool(cfg.local_sources & set(p["sources"])),
                          meta={**row, "history": history, **private}))
        return row

    side = private_dir(year) / "scores.jsonl"
    with ThreadPoolExecutor(workers) as ex, out.open("a", encoding="utf-8") as f, \
            side.open("a", encoding="utf-8") as fp:
        for n, row in enumerate(ex.map(work, todo), 1):
            if row is None:
                continue
            row, priv = _split_private(row)
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
            f.flush()
            fp.write(json.dumps(priv or {"doi": row["doi"]}, ensure_ascii=False) + "\n")
            fp.flush()
            if n % 100 == 0:
                _log(f"  screened {n}/{len(todo)}")
    # re-apply the rules to every cached paper with today's repository metadata
    # (author lists, units and field codes change after the first harvest)
    rescreen(year, config_path=config_path, fresh=papers)
    return out


def private_dir(year):
    """Folder for anything derived from private inputs: next to the private inputs themselves
    ($PUBS_PRIVATE, the temporary Colab disk in the notebooks; private/ otherwise), never in
    the working-data folder in Drive."""
    from .bookings import PRIVATE
    d = PRIVATE / "derived" / str(year)
    d.mkdir(parents=True, exist_ok=True)
    return d


def _split_private(row):
    """Remove the private-input part of a screened row (never goes to screened.jsonl)."""
    private = row.pop("private", None)
    return row, ({"doi": row["doi"], **private} if private else None)


def load_private(year):
    """{doi: {"score", "priority", "reasons"}} from the private sidecar, or {}."""
    path = DATA / str(year) / "private" / "scores.jsonl"
    out = {}
    if path.exists():
        for line in path.open(encoding="utf-8"):
            if line.strip():
                r = json.loads(line)
                out[r["doi"]] = r
    return out


def acknowledging_authors(exclude_year):
    """UTU authors of acknowledging papers in every other screened year."""
    names = set()
    for f in DATA.glob("*/screened.jsonl"):
        if f.parent.name == str(exclude_year):
            continue
        for line in f.open(encoding="utf-8"):
            r = json.loads(line)
            if r.get("category") == "A":
                names.update(sources.clean_authors(r.get("local_authors")))
    return names


META_KEYS = ("title", "journal", "year", "type", "fields", "local_authors", "units", "sources")


def _rescreen_one(args):
    year, r, config_path, history, private, fresh = args
    if fresh:
        r = {**r, **{k: fresh[k] for k in META_KEYS if fresh.get(k)}}
    cfg = load(config_path) if config_path else load()
    text, _ = cached_text(year, r["doi"])
    if text is None:
        return r, False
    from .text import matches_paper
    if not matches_paper(text, r["doi"], (fresh or {}).get("title") or r.get("title")):
        text = ""  # cached text belongs to another paper: screen as "no usable text"
    keep = ("doi", "title", "journal", "year", "type", "fields", "local_authors", "units",
            "sources", "text_source")
    base = {k: r.get(k) for k in keep}
    base["local_authors"] = sources.clean_authors(base.get("local_authors"))
    local = bool(cfg.local_sources & set(r.get("sources") or []))
    return {**base, **screen(text, cfg, local=local,
                             meta={**base, "history": history, **private})}, True


def rescreen(year, config_path=None, processes=None, fresh=None):
    """Re-apply the rules to every paper using cached full text (no downloads).

    Papers whose text is not cached keep their previous result.
    """
    from multiprocessing import Pool
    path = DATA / str(year) / "screened.jsonl"
    rows = load_screened(year)
    history = acknowledging_authors(exclude_year=year)
    private = {"bookings": load_bookings(), "staff": load_staff()}
    with Pool(processes) as pool:
        res = pool.map(_rescreen_one,
                       [(year, r, config_path, history, private, (fresh or {}).get(r["doi"]))
                        for r in rows], chunksize=20)
    n = sum(ok for _, ok in res)
    old_private = load_private(year)
    split = [_split_private(dict(r)) if ok else (dict(r), old_private.get(r["doi"]))
             for r, ok in res]  # rows without cached text keep their previous private entry
    with path.open("w", encoding="utf-8") as f, \
            (private_dir(year) / "scores.jsonl").open("w", encoding="utf-8") as fp:
        for r, priv in split:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
            if priv:
                fp.write(json.dumps(priv, ensure_ascii=False) + "\n")
    _log(f"re-screened {n}/{len(rows)} papers from the cache")
    return path


def load_screened(year):
    """Current screened rows for a year.

    * Later rows win, except that a row without text never replaces one with text.
    * When a DOI universe snapshot exists (written by `sweep`), rows outside it are
      dropped (stale DOIs from older harvests or parsers).
    """
    path = DATA / str(year) / "screened.jsonl"
    rows = {}
    for line in path.open(encoding="utf-8"):
        if line.strip():
            r = json.loads(line)
            old = rows.get(r["doi"])
            if old and old.get("has_text") and not r.get("has_text"):
                continue
            rows[r["doi"]] = r
    universe = DATA / str(year) / "universe.json"
    if universe.exists():
        keep = set(json.loads(universe.read_text(encoding="utf-8")))
        rows = {d: r for d, r in rows.items() if d in keep}
    return list(rows.values())
