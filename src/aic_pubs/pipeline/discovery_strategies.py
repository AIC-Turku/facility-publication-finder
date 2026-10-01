"""Composable DOI discovery strategies."""
from __future__ import annotations

import csv
import json
from pathlib import Path

from .types import RunContext
from .. import candidates, discovery, sources


_DISCOVERY = {}


def register(name):
    def deco(func):
        if name in _DISCOVERY:
            raise ValueError(f"duplicate discovery strategy: {name}")
        _DISCOVERY[name] = func
        return func
    return deco


def names():
    return sorted(_DISCOVERY)


def run(name, context: RunContext, options=None):
    try:
        func = _DISCOVERY[name]
    except KeyError as exc:
        raise ValueError(f"unknown discovery strategy {name!r}; available: {names()}") from exc
    return func(context, options or {})


@register("institutional")
def institutional(context, options):
    return list(candidates.institutional_universe(context.year).values())


@register("europepmc_facility")
def europepmc_facility(context, options):
    names_ = options.get("aliases") or context.cfg.raw.get("europepmc_search_terms", ())
    grants = options.get("grants") or context.cfg.raw.get("europepmc_grant_numbers", ())
    return sources.europepmc_ack_search(
        context.year,
        names_,
        grants,
        timeout=int(options.get("timeout", 60)),
        max_pages=int(options.get("max_pages", 20)),
        page_size=int(options.get("page_size", 1000)),
    )


@register("crossref_awards")
def crossref_awards(context, options):
    grants = options.get("grants") or context.cfg.raw.get("europepmc_grant_numbers", ())
    expected_funders = options.get("expected_funders") or (
        "Research Council of Finland",
        "Academy of Finland",
    )
    return discovery.crossref_award_search(
        context.year,
        grants,
        rows=int(options.get("page_size", 1000)),
        mailto=context.crossref_mailto,
        expected_funders=expected_funders,
        timeout=int(options.get("timeout", 60)),
        max_pages=int(options.get("max_pages", 20)),
    )


@register("openalex_facility")
def openalex_facility(context, options):
    queries = options.get("queries")
    if not queries:
        aliases = context.cfg.raw.get("europepmc_search_terms", ())
        grants = context.cfg.raw.get("europepmc_grant_numbers", ())
        queries = [*aliases, *grants]
    return discovery.openalex_fulltext_search(
        context.year,
        queries,
        api_key=context.openalex_api_key,
        timeout=int(options.get("timeout", 45)),
        max_pages=int(options.get("max_pages", 20)),
    )


@register("known_users_orcid")
def known_users_orcid(context, options):
    """Search every supplied user with a verified ORCID.

    This intentionally does not suppress users already matched in institutional
    metadata. The independent DOI set is needed to measure institutional misses.
    """
    rows = []
    year_pad = int(options.get("year_pad", 1))
    include_types = {
        str(value).strip().casefold()
        for value in options.get("include_types") or []
        if str(value).strip()
    }
    exclude_types = {
        str(value).strip().casefold()
        for value in options.get("exclude_types") or []
        if str(value).strip()
    }
    exclude_retracted = bool(options.get("exclude_retracted", False))
    exclude_paratext = bool(options.get("exclude_paratext", False))

    seen_orcids = set()
    for user in context.users:
        orcid = user.orcid
        if not orcid or orcid in seen_orcids:
            continue
        seen_orcids.add(orcid)
        works = discovery.openalex_author_works(
            orcid,
            from_year=context.year - year_pad,
            to_year=context.year + year_pad,
            api_key=context.openalex_api_key,
            timeout=int(options.get("timeout", 45)),
            max_pages=int(options.get("max_pages", 20)),
        )
        for row in works:
            work_type = str(row.get("openalex_type") or "").casefold()
            if include_types and work_type not in include_types:
                continue
            if exclude_types and work_type in exclude_types:
                continue
            if exclude_retracted and row.get("is_retracted"):
                continue
            if exclude_paratext and row.get("is_paratext"):
                continue

            item = dict(row)
            item["known_aic_user"] = True
            item["target_year"] = context.year
            evidence = list(item.get("discovery_evidence") or [])
            evidence.append({
                "kind": "verified_user_orcid",
                "matched": True,
            })
            item["discovery_evidence"] = evidence
            rows.append(item)
    return rows


@register("datacite")
def datacite(context, options):
    queries = options.get("queries") or []
    rows = []
    for query in queries:
        rows.extend(discovery.datacite_related_publications(
            query,
            year=context.year,
            page_size=int(options.get("page_size", 100)),
            timeout=int(options.get("timeout", 60)),
            max_pages=int(options.get("max_pages", 10)),
        ))
    return rows


@register("doi_file")
def doi_file(context, options):
    """Load DOI candidates from a local CSV, JSON, JSONL, or text file.

    Intended for private CRIS/green-portal exports and manual benchmark lists.
    The file is read at run time and should normally live under private/.
    """
    path = Path(options.get("path") or "")
    if not path.exists():
        raise FileNotFoundError(f"DOI file not found: {path}")
    suffix = path.suffix.lower()
    rows = []

    if suffix == ".csv":
        with path.open(newline="", encoding="utf-8-sig") as handle:
            for record in csv.DictReader(handle):
                doi = record.get("doi") or record.get("DOI") or ""
                if doi:
                    rows.append({
                        "doi": doi,
                        "title": record.get("title") or record.get("Title") or "",
                        "year": record.get("year") or record.get("Year") or context.year,
                        "sources": [options.get("source_name", "doi_file")],
                        "discovery_source_label": options.get("source_name", "doi_file"),
                        "local_candidate": bool(options.get("local", False)),
                        "reporting_year_authoritative": bool(options.get("authoritative_year", False)),
                        "authoritative_reporting_year": (
                            record.get("year") or record.get("Year") or context.year
                            if options.get("authoritative_year", False) else None
                        ),
                    })
    elif suffix == ".json":
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            payload = payload.get("items") or payload.get("dois") or []
        for item in payload:
            if isinstance(item, str):
                rows.append({
                    "doi": item,
                    "sources": [options.get("source_name", "doi_file")],
                    "discovery_source_label": options.get("source_name", "doi_file"),
                    "local_candidate": bool(options.get("local", False)),
                    "reporting_year_authoritative": bool(options.get("authoritative_year", False)),
                    "authoritative_reporting_year": context.year
                    if options.get("authoritative_year", False) else None,
                })
            elif isinstance(item, dict) and item.get("doi"):
                row = dict(item)
                row.setdefault("sources", [options.get("source_name", "doi_file")])
                row.setdefault("discovery_source_label", options.get("source_name", "doi_file"))
                row.setdefault("local_candidate", bool(options.get("local", False)))
                row.setdefault("reporting_year_authoritative", bool(options.get("authoritative_year", False)))
                if options.get("authoritative_year", False):
                    row.setdefault("authoritative_reporting_year", row.get("year") or context.year)
                rows.append(row)
    elif suffix == ".jsonl":
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            item = json.loads(line)
            if isinstance(item, dict) and item.get("doi"):
                item.setdefault("sources", [options.get("source_name", "doi_file")])
                item.setdefault("discovery_source_label", options.get("source_name", "doi_file"))
                item.setdefault("local_candidate", bool(options.get("local", False)))
                item.setdefault("reporting_year_authoritative", bool(options.get("authoritative_year", False)))
                if options.get("authoritative_year", False):
                    item.setdefault("authoritative_reporting_year", item.get("year") or context.year)
                rows.append(item)
    else:
        for line in path.read_text(encoding="utf-8").splitlines():
            doi = line.strip()
            if doi and not doi.startswith("#"):
                rows.append({
                    "doi": doi,
                    "sources": [options.get("source_name", "doi_file")],
                    "discovery_source_label": options.get("source_name", "doi_file"),
                    "local_candidate": bool(options.get("local", False)),
                    "reporting_year_authoritative": bool(options.get("authoritative_year", False)),
                    "authoritative_reporting_year": context.year
                    if options.get("authoritative_year", False) else None,
                })
    return rows
