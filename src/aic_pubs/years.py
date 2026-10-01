"""Normalize publication/reporting years without conflating discovery sources."""
from __future__ import annotations


LOCAL_SOURCES = {"utupub", "abo"}


def normalize_years(row, target_year):
    """Return reporting-year provenance for one merged DOI record.

    Explicit authoritative assertions are preferred. Built-in institutional
    metadata remains authoritative when no assertion list is available.
    External publication dates stay provisional.
    """
    assertions = []
    for item in row.get("reporting_year_assertions") or []:
        year = _as_int(item.get("year"))
        source = item.get("source")
        if year is not None and source:
            assertions.append({"source": source, "year": year})

    sources = set(row.get("sources") or ())
    local = bool(LOCAL_SOURCES & sources)
    fallback_authoritative = local or bool(row.get("reporting_year_authoritative"))

    if assertions:
        authoritative_years = sorted({item["year"] for item in assertions})
        reporting_year_conflict = len(authoritative_years) > 1
        if reporting_year_conflict:
            reporting_year = None
            reporting_source = "authoritative_conflict"
            institutional_year = None
        else:
            reporting_year = authoritative_years[0]
            matching_sources = sorted({
                item["source"] for item in assertions
                if item["year"] == reporting_year
            })
            reporting_source = "+".join(matching_sources)
            institutional_year = reporting_year
        provisional = False
    else:
        explicit = _as_int(row.get("authoritative_reporting_year"))
        institutional_year = (
            explicit
            if explicit is not None
            else _as_int(row.get("year")) if fallback_authoritative else None
        )
        reporting_year = institutional_year
        reporting_source = "institutional" if institutional_year is not None else None
        reporting_year_conflict = False
        provisional = institutional_year is None

    discovered_year = _as_int(row.get("publication_year"))
    if (
        reporting_year is None
        and discovered_year is not None
        and not reporting_year_conflict
    ):
        reporting_year = discovered_year
        reporting_source = "external_provisional"
        provisional = True

    return {
        "target_year": int(target_year),
        "institutional_year": institutional_year,
        "discovered_publication_year": discovered_year,
        "reporting_year": reporting_year,
        "reporting_year_source": reporting_source,
        "reporting_year_provisional": provisional,
        "reporting_year_matches_target": (
            reporting_year == int(target_year) if reporting_year is not None else None
        ),
        "year_disagreement": (
            institutional_year is not None
            and discovered_year is not None
            and institutional_year != discovered_year
        ),
        "reporting_year_conflict": reporting_year_conflict,
        "reporting_year_assertions": assertions,
    }


def _as_int(value):
    try:
        return int(value) if value is not None and value != "" else None
    except (TypeError, ValueError):
        return None
