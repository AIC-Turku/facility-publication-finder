"""Shared types for the configurable strategy pipeline."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


METADATA_FIELDS = {"title", "journal", "type", "year", "publication_year", "publication_date"}


def _metadata_priority(source, row):
    """Higher-priority metadata can replace lower-priority values deterministically."""
    if row.get("reporting_year_authoritative") or row.get("local_candidate"):
        return 100
    if source in {"utucris_export", "abocris_export"}:
        return 100
    if source == "institutional":
        return 90
    if source == "europepmc_facility":
        return 75
    if source == "crossref_awards":
        return 70
    if source in {"known_users_orcid", "openalex_facility"}:
        return 60
    if source == "datacite":
        return 50
    return 40


@dataclass
class RunContext:
    year: int
    cfg: Any
    users: tuple = ()
    openalex_api_key: str | None = None
    crossref_mailto: str | None = None


@dataclass(frozen=True)
class TextAttempt:
    strategy: str
    status: str
    text: str | None = None
    source: str | None = None
    url: str | None = None
    license: str | None = None
    version: str | None = None
    quality: str | None = None
    scope: str | None = None
    reason: str | None = None

    @property
    def success(self):
        return self.status == "success" and bool(self.text)


@dataclass
class CandidateRecord:
    doi: str
    data: dict = field(default_factory=dict)
    discovery_sources: list[str] = field(default_factory=list)
    metadata_sources: dict[str, dict] = field(default_factory=dict)

    def merge(self, row, source):
        if source not in self.discovery_sources:
            self.discovery_sources.append(source)

        incoming_sources = list(row.get("sources") or [])
        authoritative = bool(row.get("reporting_year_authoritative")) or bool(
            {"utupub", "abo"} & set(incoming_sources)
        )
        asserted_year = row.get("authoritative_reporting_year") or row.get("year")
        if authoritative and asserted_year not in (None, ""):
            assertions = self.data.setdefault("reporting_year_assertions", [])
            assertion = {"source": source, "year": asserted_year}
            if assertion not in assertions:
                assertions.append(assertion)

        incoming_sources = list(row.get("sources") or [])
        if incoming_sources:
            existing = self.data.setdefault("sources", [])
            for item in incoming_sources:
                if item not in existing:
                    existing.append(item)

        evidence = self.data.get("discovery_evidence")
        for item in row.get("discovery_evidence") or []:
            if evidence is None:
                evidence = self.data.setdefault("discovery_evidence", [])
            enriched = dict(item)
            enriched.setdefault("source", source)
            if enriched not in evidence:
                evidence.append(enriched)

        inline_evidence = {
            key: row.get(key)
            for key in (
                "matched_query", "matched_award", "matched_funders",
                "expected_funder_verified", "related_dataset_doi",
                "relation_type", "openalex_id", "publication_year",
                "publication_date",
            )
            if row.get(key) is not None and row.get(key) != ""
        }
        if inline_evidence:
            if evidence is None:
                evidence = self.data.setdefault("discovery_evidence", [])
            inline_evidence["source"] = source
            if inline_evidence not in evidence:
                evidence.append(inline_evidence)

        priority = _metadata_priority(source, row)
        for key, value in row.items():
            if key in (
                "doi", "sources", "discovery_sources", "discovery_evidence",
                "discovery_source_label",
            ) or value is None:
                continue
            existing = self.data.get(key)
            missing = (
                key not in self.data
                or existing is None
                or existing == ""
                or existing == []
                or existing == {}
            )
            if key in METADATA_FIELDS:
                previous = self.metadata_sources.get(key)
                previous_priority = previous.get("priority", -1) if previous else -1
                if missing or priority > previous_priority:
                    self.data[key] = value
                    self.metadata_sources[key] = {
                        "source": source,
                        "priority": priority,
                    }
            elif missing:
                self.data[key] = value

    def as_dict(self):
        return {
            "doi": self.doi,
            **self.data,
            "discovery_sources": list(self.discovery_sources),
            "metadata_sources": {
                key: dict(value)
                for key, value in sorted(self.metadata_sources.items())
            },
        }
