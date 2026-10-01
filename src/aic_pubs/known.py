"""Public metadata for papers (Crossref, Europe PMC) and the facility-website import.

`aic-pubs import-website` adds every DOI on the facility's public publication page
(facility.yaml `website_publications`, all years) to the confirmed papers
(facilities/<facility>/papers/<year>.yaml, source "website"), with metadata from Crossref
and Europe PMC. Only for facilities that keep such a page; the AIC page is WordPress.
"""
from collections.abc import Callable, Iterable
import re
import urllib.parse

from . import sources
from .config import load
from .http import get_json


def _clean_title(title):
    """Crossref titles carry markup (<i>, <sub>, entities): plain text, single spaces."""
    import html
    return " ".join(html.unescape(re.sub(r"<[^>]+>", "", title or "")).split())


def _date(parts):
    p = ((parts or {}).get("date-parts") or [[None]])[0]
    return "-".join(f"{x:02d}" if i else str(x) for i, x in enumerate(p) if x) if p and p[0] else ""


def bibliographic(m: dict) -> dict:
    """The public metadata of a Crossref record ({} for an empty record)."""
    if not m:
        return {}
    return {
        "title": _clean_title((m.get("title") or [""])[0]),
        "journal": (m.get("container-title") or [""])[0],
        "publisher": m.get("publisher", ""),
        "type": m.get("type", ""),
        "issued_year": (_date(m.get("issued")) or "")[:4],
        "published_online": _date(m.get("published-online")),
        "published_print": _date(m.get("published-print")),
        "n_authors": len(m.get("author") or []),
        "license": ((m.get("license") or [{}])[0]).get("URL", ""),
    }


def europepmc_records(dois: Iterable[str], batch: int = 20) -> dict[str, dict]:
    """{doi: {pmid, pmcid, europepmc_id, europepmc_open_full_text}} for the DOIs Europe PMC knows."""
    out = {}
    dois = list(dois)
    for i in range(0, len(dois), batch):
        chunk = dois[i:i + batch]
        q = " OR ".join(f'DOI:"{d}"' for d in chunk)
        url = f"{sources.EPMC}/search?" + urllib.parse.urlencode(
            {"query": q, "format": "json", "resultType": "lite", "pageSize": 100})
        for r in ((get_json(url) or {}).get("resultList") or {}).get("result", []):
            d = (r.get("doi") or "").lower()
            if d in chunk and (d not in out or r.get("pmcid")):
                out[d] = {"pmid": r.get("pmid", ""), "pmcid": r.get("pmcid", ""),
                          "europepmc_id": r.get("id", "") if r.get("source") == "PPR" else "",
                          "europepmc_open_full_text": r.get("inEPMC") == "Y"}
    return out


def _website_all_years(first=2009, last=None):
    """{year: [doi, ...]} from the facility website, every year that has papers."""
    import datetime
    f = load().raw["facility"]
    last = last or datetime.date.today().year
    years = {}
    for y in range(first, last + 1):
        dois = sources.website_list(y, f["website_publications"], f["website_core_slug"])
        if dois:
            years[y] = dois
    return years


def import_website(first: int = 2009, last: int | None = None,
                   progress: Callable[[str], None] = print) -> dict:
    """Add the website lists of every year to the confirmed papers (source "website")."""
    from .papers import add_papers
    years = _website_all_years(first, last)
    if not years:
        progress("no papers on the website (facility.yaml website_publications)")
        return {}
    first_year = {}
    for y, dois in sorted(years.items()):     # a DOI listed in two years keeps the first
        for d in dois:
            first_year.setdefault(d, y)
    lines = "\n".join(f"{d} {y}" for d, y in first_year.items())
    progress(f"{len(first_year)} DOIs on the website, {min(years)}-{max(years)}")
    # never move a paper already filed (e.g. validated under another year)
    summary, leftover = add_papers(lines, source="website", allow_moves=False)
    for line in leftover:
        progress(f"  not filed: {line}")
    return summary
