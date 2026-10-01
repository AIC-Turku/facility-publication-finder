"""Small live diagnostics for external DOI and author services."""
from __future__ import annotations

from . import discovery
from .config import load
from .identity import normalise_orcid
from .pipeline import text_strategies
from .pipeline.types import RunContext


def probe_doi(doi, *, year=None, openalex_api_key=None):
    """Exercise DOI-level public metadata/text routes and return structured status."""
    cfg = load()
    context = RunContext(
        year=int(year or 0),
        cfg=cfg,
        openalex_api_key=openalex_api_key,
    )
    paper = {"doi": doi}
    attempts = []
    for name in ("europepmc", "publisher_html", "crossref_fulltext", "openalex_oa"):
        try:
            attempt = text_strategies.run(name, paper, context)
            attempts.append({
                "strategy": name,
                "status": attempt.status,
                "source": attempt.source,
                "url": attempt.url,
                "license": attempt.license,
                "version": attempt.version,
                "quality": attempt.quality,
                "scope": attempt.scope,
                "reason": attempt.reason,
                "text_chars": len(attempt.text or ""),
            })
        except Exception as exc:
            attempts.append({
                "strategy": name,
                "status": "error",
                "reason": f"{type(exc).__name__}: {exc}",
                "text_chars": 0,
            })
    return {"doi": doi, "attempts": attempts}


def probe_orcid(orcid, year, *, openalex_api_key=None, max_pages=2):
    """Exercise the verified-ORCID -> OpenAlex works route."""
    orcid = normalise_orcid(orcid)
    rows = discovery.openalex_author_works(
        orcid,
        from_year=year,
        to_year=year,
        api_key=openalex_api_key,
        timeout=20,
        max_pages=max_pages,
    )
    return {
        "year": int(year),
        "works": [
            {
                "doi": row.get("doi"),
                "title": row.get("title"),
                "publication_year": row.get("publication_year"),
                "publication_date": row.get("publication_date"),
                "openalex_id": row.get("openalex_id"),
                "openalex_type": row.get("openalex_type"),
                "openalex_primary_version": row.get("openalex_primary_version"),
                "is_retracted": row.get("is_retracted"),
                "is_paratext": row.get("is_paratext"),
            }
            for row in rows
        ],
    }
