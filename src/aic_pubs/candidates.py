"""Build and merge institutional publication candidate sets."""
from __future__ import annotations

from . import sources


def merge_candidate(target, incoming, source):
    doi = sources._norm_doi(incoming.get("doi"))
    if not doi:
        return
    row = target.setdefault(doi, {"doi": doi, "sources": []})
    if source not in row["sources"]:
        row["sources"].append(source)
    for key, value in incoming.items():
        if key in ("doi", "sources"):
            continue
        if value and not row.get(key):
            row[key] = value


def institutional_universe(year, science_only=True, institutional_sources=None):
    """DOI-bearing records of the year from the facility's institutional sources
    (facility.yaml `institutional_sources`; default: UTUPub and Åbo Akademi).

    science_only keeps DSpace items in field-of-science groups 1-4 (or without a field
    code) for sources with `science_fields_only`. Measured on 2025 (UTUPub): the 993 excluded
    papers held 0 AIC leads, and screening them costs ~30 % more downloads. Set
    `institutional_fields: all` in facility.yaml to include everything.
    """
    if institutional_sources is None:
        from .config import load
        institutional_sources = load().institutional_sources
    if not institutional_sources:
        raise ValueError("facility.yaml has no institutional_sources: the candidate backbone is empty")
    papers = {}
    for src in institutional_sources:
        name, adapter = src["name"], src.get("adapter")
        if adapter == "dspace7":
            gate = science_only and src.get("science_fields_only", False)
            kw = {k: src[k] for k in ("base_url", "query") if src.get(k)}
            if src.get("doi_fields"):
                kw["doi_fields"] = tuple(src["doi_fields"])
            for item in sources.utupub_items(year, **kw):
                if item.get("doi") and (not gate or sources.is_science(item)):
                    merge_candidate(papers, item, name)
        elif adapter == "pure_oai":
            kw = {k2: src[k] for k, k2 in (("base_url", "base_url"), ("set", "set_spec"),
                                            ("file_prefix", "file_prefix")) if src.get(k)}
            for doi, item in sources.abo_items(year, **kw).items():
                merge_candidate(
                    papers,
                    {
                        "doi": doi,
                        "title": item.get("title", ""),
                        "year": year,
                        "abo_files": item.get("files") or [],
                        "authors": item.get("authors") or [],
                    },
                    name,
                )
        else:
            raise ValueError(f"institutional source {name!r}: unknown adapter {adapter!r} "
                             f"(dspace7 or pure_oai; add one in sources.py)")
    return papers
