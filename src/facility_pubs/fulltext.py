"""Resolve searchable article text from legitimate DOI-linked sources.

Resolution order is deliberate:
1. university/repository files already attached to harvested metadata;
2. Europe PMC XML;
3. Crossref-deposited full-text/TDM links;
4. OpenAlex open-access PDF locations.

The resolver returns provenance with the text and never treats a failed request as
proof that no text exists.
"""
from __future__ import annotations

import html
import os
import re
import urllib.parse
from dataclasses import dataclass

from . import sources
from .http import fetch_result, get_json
from .text import pdf_text

OPENALEX = "https://api.openalex.org/works"


@dataclass(frozen=True)
class TextResult:
    text: str | None
    source: str | None
    url: str | None = None
    license: str | None = None
    version: str | None = None


@dataclass(frozen=True)
class DownloadTextResult:
    text: str | None
    final_url: str | None
    status: int | None
    content_type: str | None
    reason: str | None = None


def _html_text(value):
    if not value:
        return None
    value = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", value)
    value = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</li>|</h[1-6]>", "\n", value)
    value = re.sub(r"<[^>]+>", " ", value)
    value = html.unescape(value)
    value = re.sub(r"[ \t\r\f\v]+", " ", value)
    value = re.sub(r"\n\s*\n+", "\n", value)
    return value.strip() or None


def _download_text(url, timeout=90):
    """Download and validate article-like text with explicit failure provenance."""
    fetched = fetch_result(url, timeout=timeout)
    if not fetched.ok:
        return DownloadTextResult(
            None,
            fetched.final_url,
            fetched.status,
            fetched.content_type,
            fetched.error or "fetch_failed",
        )
    data = fetched.body or b""
    text = pdf_text(data) if data[:4] == b"%PDF" else _html_text(data.decode("utf-8", "ignore"))
    if not text:
        return DownloadTextResult(
            None,
            fetched.final_url,
            fetched.status,
            fetched.content_type,
            "parse_empty",
        )
    from .text import validate_article_text
    accepted, _, reason = validate_article_text(text)
    if not accepted:
        return DownloadTextResult(
            None,
            fetched.final_url,
            fetched.status,
            fetched.content_type,
            reason or "validation_failed",
        )
    return DownloadTextResult(
        text,
        fetched.final_url,
        fetched.status,
        fetched.content_type,
        None,
    )


def _download_text(url):
    """Compatibility wrapper returning only validated text."""
    return _download_text(url).text


def crossref_landing_url(doi):
    """Publisher landing URL deposited in Crossref metadata."""
    return (sources.crossref_work(doi).get("URL") or "").strip() or None


def crossref_text_links(doi):
    """Unique full-text/TDM links deposited by the publisher in Crossref metadata."""
    record = sources.crossref_work(doi)
    out = []
    seen = set()
    for link in record.get("link") or []:
        url = (link.get("URL") or "").strip()
        if not url or url in seen:
            continue
        content_type = (link.get("content-type") or "").lower()
        intended = (link.get("intended-application") or "").lower()
        if intended == "similarity-checking":
            continue
        if not any(kind in content_type for kind in ("pdf", "xml", "html", "text")):
            continue
        seen.add(url)
        out.append({
            "url": url,
            "content_type": content_type,
            "intended_application": intended or None,
        })
    return out


def openalex_record(doi, api_key=None):
    """Return an OpenAlex work using the DOI filter."""
    api_key = api_key or os.getenv("OPENALEX_API_KEY")
    params = {
        "filter": f"doi:https://doi.org/{sources._norm_doi(doi)}",
        "per-page": 1,
    }
    if api_key:
        params["api_key"] = api_key
    data = get_json(f"{OPENALEX}?{urllib.parse.urlencode(params)}", timeout=60) or {}
    results = data.get("results") or []
    return results[0] if results else {}


def openalex_oa_locations(doi, api_key=None):
    """Unique OA PDF locations ordered by preferred article version."""
    work = openalex_record(doi, api_key=api_key)
    version_rank = {
        "publishedVersion": 3,
        "acceptedVersion": 2,
        "submittedVersion": 1,
    }
    out = []
    seen = set()
    for location in work.get("locations") or []:
        pdf = (location.get("pdf_url") or "").strip()
        if not pdf or not location.get("is_oa") or pdf in seen:
            continue
        seen.add(pdf)
        out.append({
            "url": pdf,
            "license": location.get("license"),
            "version": location.get("version"),
            "landing_page_url": location.get("landing_page_url"),
        })
    out.sort(
        key=lambda item: (
            -version_rank.get(item.get("version"), 0),
            item.get("url") or "",
        )
    )
    return out


def _usable(text, paper=None):
    """Repository text is only accepted when it looks like an article: UTUPub serves
    whitespace-only TEXT files for some items (10.1016/j.matdes.2025.114920 was 12
    newlines), which used to stop resolution before the ÅA PDF was tried."""
    from .text import validate_article_text
    from .text import matches_paper
    if not (text and text.strip()) or not validate_article_text(text)[0]:
        return False
    return paper is None or matches_paper(text, paper.get("doi"), paper.get("title"))


def resolve_text(paper: dict, openalex_api_key: str | None = None) -> TextResult:
    """Resolve searchable text for one DOI-bearing paper."""
    if paper.get("utupub_uuid"):
        text = sources.utupub_text(paper["utupub_uuid"], paper.get("dspace_base"))
        if _usable(text, paper):   # the repository's item page: the open copy staff can read
            base = (paper.get("dspace_base") or sources.UTUPUB).removesuffix("/server/api")
            return TextResult(text, "utupub", url=f"{base}/items/{paper['utupub_uuid']}")

    if paper.get("abo_files"):
        text = sources.abo_text(paper["abo_files"])
        if _usable(text, paper):
            return TextResult(text, "abo", url=paper["abo_files"][0])

    pmcid, ppr = paper.get("pmcid"), paper.get("epmc_id")
    if not (pmcid or ppr) and paper.get("doi"):
        match = sources.europepmc_lookup_doi(paper["doi"]) or {}
        pmcid, ppr = match.get("pmcid"), match.get("epmc_id")
    for epmc in (pmcid, ppr):  # journal version first, then the preprint (PPR…) full text
        if epmc:
            text = sources.europepmc_text(epmc)
            if _usable(text, paper):
                return TextResult(text, "europepmc", url=f"https://europepmc.org/article/{epmc}")

    doi = paper.get("doi")
    if not doi:
        return TextResult(None, None)

    for link in crossref_text_links(doi):
        text = _download_text(link["url"])
        if text:
            return TextResult(text, "crossref_fulltext", url=link["url"])

    # OpenAlex needs a key: anonymous use shares a daily budget that is routinely
    # exhausted (HTTP 429 "Insufficient budget"), which only slows the run down.
    openalex_key = openalex_api_key or os.getenv("OPENALEX_API_KEY")
    for location in (openalex_oa_locations(doi, api_key=openalex_key) if openalex_key else []):
        text = _download_text(location["url"])
        if text:
            return TextResult(
                text,
                "openalex_oa",
                url=location["url"],
                license=location.get("license"),
                version=location.get("version"),
            )

    return TextResult(None, None)
