"""Composable full-text recovery strategies."""
from __future__ import annotations

from .types import RunContext, TextAttempt
from .. import discovery, sources
from ..fulltext import crossref_landing_url, crossref_text_links, download_text, openalex_oa_locations
from .validators import validate_article_text


_TEXT = {}


def register(name):
    def deco(func):
        if name in _TEXT:
            raise ValueError(f"duplicate text strategy: {name}")
        _TEXT[name] = func
        return func
    return deco


def names():
    return sorted(_TEXT)


def run(name, paper, context: RunContext, options=None):
    try:
        func = _TEXT[name]
    except KeyError as exc:
        raise ValueError(f"unknown text strategy {name!r}; available: {names()}") from exc
    attempt = func(paper, context, options or {})
    if attempt.text:
        from ..text import matches_paper  # same wrong-paper check as the sweep path
        if not matches_paper(attempt.text, paper.get("doi"), paper.get("title")):
            return TextAttempt(strategy=attempt.strategy, status="rejected", text=None,
                               source=attempt.source, url=attempt.url, license=attempt.license,
                               version=attempt.version, quality=None, scope=attempt.scope,
                               reason="text_of_another_paper")
    return attempt


def _attempt(name, text=None, source=None, url=None, license=None, version=None,
             quality=None, scope=None, reason=None, validate=True):
    if text and validate:
        ok, detected_quality, rejected = validate_article_text(text)
        if not ok:
            return TextAttempt(
                strategy=name,
                status="rejected",
                text=None,
                source=source,
                url=url,
                license=license,
                version=version,
                quality=None,
                scope=scope,
                reason=rejected,
            )
        quality = quality or detected_quality
    return TextAttempt(
        strategy=name,
        status="success" if text else "miss",
        text=text,
        source=source,
        url=url,
        license=license,
        version=version,
        quality=quality,
        scope=scope,
        reason=reason,
    )


@register("cache")
def cache(paper, context, options):
    from ..sweep import cached_text, cached_text_metadata

    doi = paper.get("doi")
    if not doi:
        return _attempt("cache", reason="no_doi")
    text, source = cached_text(context.year, doi)
    if not text:
        return _attempt("cache", reason="cache_miss")
    meta = cached_text_metadata(context.year, doi)
    trusted_full_sources = {
        "utupub",
        "abo",
        "europepmc",
        "openalex_oa",
    }
    scope = meta.get("scope")
    if not scope:
        scope = "full" if source in trusted_full_sources else "partial"
    return _attempt(
        "cache",
        text,
        source or "cache",
        url=meta.get("url"),
        license=meta.get("license"),
        version=meta.get("version"),
        quality=meta.get("quality"),
        scope=scope,
    )


@register("utupub")
def utupub(paper, context, options):
    uuid = paper.get("utupub_uuid")
    if not uuid:
        return _attempt("utupub", reason="no_utupub_uuid")
    text = sources.utupub_text(uuid)
    return _attempt("utupub", text, "utupub", quality="high", scope="full",
                    reason=None if text else "no_text_bundle")


@register("abo_pdf")
def abo_pdf(paper, context, options):
    files = paper.get("abo_files") or []
    if not files:
        return _attempt("abo_pdf", reason="no_abo_files")
    text = sources.abo_text(files)
    return _attempt("abo_pdf", text, "abo", quality="high", scope="full",
                    reason=None if text else "no_readable_pdf")


@register("europepmc")
def europepmc(paper, context, options):
    pmcid, ppr = paper.get("pmcid"), paper.get("epmc_id")
    if not (pmcid or ppr) and paper.get("doi"):
        match = discovery.europepmc_lookup_doi(paper["doi"]) or {}
        pmcid, ppr = match.get("pmcid"), match.get("epmc_id")
    if not (pmcid or ppr):
        return _attempt("europepmc", reason="no_pmcid")
    text = sources.europepmc_text(pmcid) if pmcid else None
    if not text and ppr:  # preprint full text is served under the PPR id
        pmcid, text = ppr, sources.europepmc_text(ppr)
    return _attempt(
        "europepmc",
        text,
        "europepmc",
        url=f"https://europepmc.org/articles/{pmcid}",
        quality="high",
        scope="full",
        reason=None if text else "xml_unavailable",
    )


@register("publisher_html")
def publisher_html(paper, context, options):
    doi = paper.get("doi")
    if not doi:
        return _attempt("publisher_html", reason="no_doi")
    url = crossref_landing_url(doi)
    if not url:
        return _attempt("publisher_html", reason="no_publisher_url")
    result = download_text(url, timeout=int(options.get("timeout", 45)))
    if result.text:
        return _attempt(
            "publisher_html",
            result.text,
            "publisher_html",
            url=result.final_url or url,
            quality="low",
            scope="partial",
        )
    return _attempt("publisher_html", reason=result.reason or "publisher_unavailable")


@register("crossref_fulltext")
def crossref_fulltext(paper, context, options):
    doi = paper.get("doi")
    if not doi:
        return _attempt("crossref_fulltext", reason="no_doi")
    reasons = []
    for link in crossref_text_links(doi):
        result = download_text(link["url"])
        if result.text:
            content_type = (link.get("content_type") or "").lower()
            is_html = "html" in content_type
            return _attempt(
                "crossref_fulltext",
                result.text,
                "crossref_fulltext",
                url=result.final_url or link["url"],
                quality="low" if is_html else "medium",
                scope="partial" if is_html else "full",
            )
        reasons.append(result.reason or "unknown")
    reason = "no_crossref_link" if not reasons else " | ".join(dict.fromkeys(reasons))
    return _attempt("crossref_fulltext", reason=reason)


@register("openalex_oa")
def openalex_oa(paper, context, options):
    doi = paper.get("doi")
    if not doi:
        return _attempt("openalex_oa", reason="no_doi")
    reasons = []
    for location in openalex_oa_locations(doi, api_key=context.openalex_api_key):
        result = download_text(location["url"])
        if result.text:
            return _attempt(
                "openalex_oa",
                result.text,
                "openalex_oa",
                url=result.final_url or location["url"],
                license=location.get("license"),
                version=location.get("version"),
                quality="high",
                scope="full",
            )
        reasons.append(result.reason or "unknown")
    reason = "no_oa_pdf" if not reasons else " | ".join(dict.fromkeys(reasons))
    return _attempt("openalex_oa", reason=reason)


@register("metadata_only")
def metadata_only(paper, context, options):
    """Discovery-only runs: do not attempt full-text retrieval."""
    return _attempt("metadata_only", reason="discovery_only", validate=False)
