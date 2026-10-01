"""Prototype candidate-discovery channels that are independent of the local repositories.

These functions deliberately return DOI-level candidate records only. They do not
decide whether AIC was used; the normal full-text screen remains authoritative.
"""
from __future__ import annotations

import os
import urllib.parse

from .http import get_json
from .sources import _norm_doi

CROSSREF = "https://api.crossref.org/works"
OPENALEX = "https://api.openalex.org/works"
DATACITE = "https://api.datacite.org/dois"
EPMC = "https://www.ebi.ac.uk/europepmc/webservices/rest"


EVIDENCE_KEYS = (
    "matched_query",
    "matched_award",
    "matched_funders",
    "expected_funder_verified",
    "related_dataset_doi",
    "relation_type",
    "openalex_id",
    "publication_year",
    "publication_date",
    "openalex_type",
    "openalex_primary_version",
    "is_retracted",
    "is_paratext",
)


def _row_evidence(row):
    evidence = {
        key: row.get(key)
        for key in EVIDENCE_KEYS
        if row.get(key) is not None and row.get(key) != ""
    }
    if not evidence:
        return None
    sources = list(row.get("discovery_sources") or [])
    if sources:
        evidence["sources"] = sources
    return evidence


def _dedupe(rows):
    """Merge candidate records by DOI while preserving all discovery evidence."""
    out = {}
    for row in rows:
        doi = _norm_doi(row.get("doi"))
        if not doi:
            continue
        current = out.setdefault(
            doi,
            {"doi": doi, "discovery_sources": []},
        )
        evidence = _row_evidence(row)
        if evidence:
            bucket = current.setdefault("discovery_evidence", [])
            if evidence not in bucket:
                bucket.append(evidence)
        for existing_evidence in row.get("discovery_evidence") or []:
            bucket = current.setdefault("discovery_evidence", [])
            if existing_evidence not in bucket:
                bucket.append(existing_evidence)

        for key, value in row.items():
            if key in ("doi", "discovery_sources", "discovery_evidence") or value is None:
                continue
            existing = current.get(key)
            missing = key not in current or existing is None or existing == "" or existing == [] or existing == {}
            if missing:
                current[key] = value
        for source in row.get("discovery_sources", []):
            if source not in current["discovery_sources"]:
                current["discovery_sources"].append(source)
    return list(out.values())


def europepmc_lookup_doi(doi):
    """Resolve a DOI to a Europe PMC record/PMCID even when it was not found by
    the acknowledgement search.
    """
    q = urllib.parse.urlencode({
        "query": f'DOI:"{_norm_doi(doi)}"',
        "format": "json",
        "pageSize": 5,
        "resultType": "lite",
    })
    data = get_json(f"{EPMC}/search?{q}", timeout=60) or {}
    hits = data.get("resultList", {}).get("result", [])
    if not hits:
        return None
    hit = hits[0]
    return {
        "doi": _norm_doi(hit.get("doi") or doi),
        "pmcid": hit.get("pmcid"),
        "epmc_id": hit.get("id") if hit.get("source") == "PPR" else None,
        "title": hit.get("title", ""),
        "journal": hit.get("journalTitle", ""),
        "discovery_sources": ["europepmc_doi"],
    }


def crossref_award_search(year, award_numbers, rows=1000, mailto=None,
                          expected_funders=(), *, timeout=60, max_pages=20):
    """Find works whose Crossref funding metadata names one of the award numbers.

    Award-number matches generate candidates only: award numbers are not globally
    unique, so downstream evidence/funder checks still matter. Cursor pagination
    is bounded; rows are marked truncated when the configured page cap is hit.
    """
    expected = tuple(str(x).casefold() for x in expected_funders if x)
    page_size = max(1, min(int(rows), 1000))
    found = []

    for award in award_numbers:
        base_params = {
            "filter": (
                f"award.number:{award},"
                f"from-pub-date:{year}-01-01,until-pub-date:{year}-12-31"
            ),
            "rows": page_size,
            "select": "DOI,title,container-title,published,funder,type",
        }
        if mailto:
            base_params["mailto"] = mailto

        cursor = "*"
        pages = 0
        award_rows = []
        while cursor and pages < int(max_pages):
            pages += 1
            params = {**base_params, "cursor": cursor}
            data = get_json(
                f"{CROSSREF}?{urllib.parse.urlencode(params)}",
                timeout=timeout,
            ) or {}
            message = data.get("message") or {}
            items = message.get("items") or []

            for item in items:
                doi = _norm_doi(item.get("DOI"))
                if not doi:
                    continue
                funders = [
                    str(f.get("name") or "").strip()
                    for f in item.get("funder") or []
                    if str(f.get("name") or "").strip()
                ]
                verified = (
                    any(term in name.casefold() for term in expected for name in funders)
                    if expected else None
                )
                award_rows.append({
                    "doi": doi,
                    "title": (item.get("title") or [""])[0],
                    "journal": (item.get("container-title") or [""])[0],
                    "type": item.get("type", ""),
                    "matched_award": str(award),
                    "matched_funders": funders,
                    "expected_funder_verified": verified,
                    "discovery_sources": ["crossref_award"],
                })

            nxt = message.get("next-cursor")
            if len(items) < page_size or not nxt or nxt == cursor:
                cursor = None
                break
            cursor = nxt

        if cursor and pages >= int(max_pages):
            for row in award_rows:
                row["discovery_truncated"] = True
        found.extend(award_rows)

    return _dedupe(found)


def openalex_fulltext_search(year, queries, api_key=None, per_page=100, timeout=45, max_pages=20):
    """Search OpenAlex title/abstract/full text for exact phrases.

    Useful queries are facility aliases, grant numbers, canonical acknowledgement
    fragments, and distinctive hardware combinations. Set OPENALEX_API_KEY or
    pass api_key explicitly when required by the service.
    """
    api_key = api_key or os.getenv("OPENALEX_API_KEY")
    found = []
    for query in queries:
        cursor = "*"
        pages = 0
        query_rows = []
        while cursor and pages < max_pages:
            pages += 1
            filters = f'publication_year:{year},fulltext.search.exact:"{query}"'
            params = {"filter": filters, "per-page": per_page, "cursor": cursor}
            if api_key:
                params["api_key"] = api_key
            data = get_json(f"{OPENALEX}?{urllib.parse.urlencode(params)}", timeout=timeout) or {}
            for work in data.get("results", []):
                doi = _norm_doi(work.get("doi"))
                if not doi:
                    continue
                primary = work.get("primary_location") or {}
                source = primary.get("source") or {}
                query_rows.append({
                    "doi": doi,
                    "title": work.get("display_name", ""),
                    "journal": source.get("display_name", ""),
                    "openalex_id": work.get("id", ""),
                    "publication_year": work.get("publication_year"),
                    "publication_date": work.get("publication_date"),
                    "openalex_type": work.get("type"),
                    "openalex_primary_version": primary.get("version"),
                    "is_retracted": bool(work.get("is_retracted")),
                    "is_paratext": bool(work.get("is_paratext")),
                    "matched_query": query,
                    "discovery_sources": ["openalex_fulltext"],
                })
            nxt = (data.get("meta") or {}).get("next_cursor")
            cursor = nxt if nxt and nxt != cursor else None
        truncated = bool(cursor and pages >= max_pages)
        if truncated:
            for row in query_rows:
                row["discovery_truncated"] = True
        found.extend(query_rows)
    return _dedupe(found)


def openalex_author_works(orcid, from_year, to_year=None, api_key=None, per_page=100,
                          timeout=45, max_pages=20):
    """Candidate publications for a privately resolved user ORCID.

    This is intended for OpenIRIS/user discovery: identity resolution happens
    outside the public outputs, then only DOI candidates and a generic provenance
    flag are passed into the publication finder.
    """
    api_key = api_key or os.getenv("OPENALEX_API_KEY")
    to_year = to_year or from_year
    cursor = "*"
    found = []
    pages = 0
    while cursor and pages < max_pages:
        pages += 1
        filters = (
            f"authorships.author.orcid:{orcid},"
            f"from_publication_date:{from_year}-01-01,"
            f"to_publication_date:{to_year}-12-31"
        )
        params = {"filter": filters, "per-page": per_page, "cursor": cursor}
        if api_key:
            params["api_key"] = api_key
        data = get_json(f"{OPENALEX}?{urllib.parse.urlencode(params)}", timeout=timeout) or {}
        for work in data.get("results", []):
            doi = _norm_doi(work.get("doi"))
            if not doi:
                continue
            primary = work.get("primary_location") or {}
            source = primary.get("source") or {}
            found.append({
                "doi": doi,
                "title": work.get("display_name", ""),
                "journal": source.get("display_name", ""),
                "openalex_id": work.get("id", ""),
                "publication_year": work.get("publication_year"),
                "publication_date": work.get("publication_date"),
                "openalex_type": work.get("type"),
                "openalex_primary_version": primary.get("version"),
                "is_retracted": bool(work.get("is_retracted")),
                "is_paratext": bool(work.get("is_paratext")),
                "discovery_sources": ["known_user_orcid"],
            })
        nxt = (data.get("meta") or {}).get("next_cursor")
        cursor = nxt if nxt and nxt != cursor else None
    if cursor and pages >= max_pages:
        for row in found:
            row["discovery_truncated"] = True
    return _dedupe(found)


def datacite_related_publications(query, year=None, page_size=100, *, timeout=60,
                                  max_pages=10):
    """Search DataCite metadata and follow related DOI links with bounded pagination."""
    found = []
    page_size = max(1, min(int(page_size), 1000))
    page = 1
    truncated = False

    while page <= int(max_pages):
        params = {
            "query": query,
            "page[size]": page_size,
            "page[number]": page,
            "detail": "true",
        }
        if year:
            params["query"] = f"({query}) AND publicationYear:{year}"

        data = get_json(f"{DATACITE}?{urllib.parse.urlencode(params)}", timeout=timeout) or {}
        items = data.get("data") or []
        for item in items:
            attrs = item.get("attributes") or {}
            source_doi = _norm_doi(attrs.get("doi") or item.get("id"))
            for rel in attrs.get("relatedIdentifiers") or []:
                if str(rel.get("relatedIdentifierType", "")).upper() != "DOI":
                    continue
                doi = _norm_doi(rel.get("relatedIdentifier"))
                if not doi:
                    continue
                found.append({
                    "doi": doi,
                    "related_dataset_doi": source_doi,
                    "relation_type": rel.get("relationType", ""),
                    "discovery_sources": ["datacite_related"],
                })

        meta = data.get("meta") or {}
        total_pages = meta.get("totalPages")
        if not items:
            break
        if total_pages is not None and page >= int(total_pages):
            break
        if len(items) < page_size and total_pages is None:
            break
        if page >= int(max_pages):
            truncated = (
                (total_pages is not None and page < int(total_pages))
                or (total_pages is None and len(items) >= page_size)
            )
            break
        page += 1

    if truncated:
        for row in found:
            row["discovery_truncated"] = True
    return _dedupe(found)
