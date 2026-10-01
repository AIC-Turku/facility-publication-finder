"""Tests for the prototype multi-channel discovery helpers."""
import json

from aic_pubs import discovery


def test_dedupe_merges_provenance():
    rows = discovery._dedupe([
        {"doi": "10.1000/x", "title": "A", "discovery_sources": ["one"]},
        {"doi": "https://doi.org/10.1000/X", "journal": "J", "discovery_sources": ["two"]},
    ])
    assert rows == [{
        "doi": "10.1000/x",
        "discovery_sources": ["one", "two"],
        "title": "A",
        "journal": "J",
    }]


def test_europepmc_lookup_by_doi(monkeypatch):
    def fake(url, **kwargs):
        assert 'DOI%3A%2210.1000%2Fabc%22' in url
        return {"resultList": {"result": [{
            "doi": "10.1000/ABC",
            "pmcid": "PMC123",
            "title": "Paper",
            "journalTitle": "Journal",
        }]}}
    monkeypatch.setattr(discovery, "get_json", fake)
    row = discovery.europepmc_lookup_doi("https://doi.org/10.1000/ABC")
    assert row["doi"] == "10.1000/abc"
    assert row["pmcid"] == "PMC123"


def test_crossref_award_search(monkeypatch):
    def fake(url, **kwargs):
        assert "award.number%3A359073" in url
        return {"message": {"items": [{
            "DOI": "10.1000/A",
            "title": ["A paper"],
            "container-title": ["Journal"],
            "type": "journal-article",
            "funder": [{"name": "Research Council of Finland"}],
        }]}}
    monkeypatch.setattr(discovery, "get_json", fake)
    rows = discovery.crossref_award_search(
        2025,
        ["359073"],
        expected_funders=["Research Council of Finland"],
    )
    assert rows[0]["doi"] == "10.1000/a"
    assert rows[0]["matched_award"] == "359073"
    assert rows[0]["matched_funders"] == ["Research Council of Finland"]
    assert rows[0]["expected_funder_verified"] is True
    assert rows[0]["discovery_sources"] == ["crossref_award"]


def test_openalex_fulltext_search(monkeypatch):
    calls = []
    def fake(url, **kwargs):
        calls.append(url)
        return {
            "results": [{
                "doi": "https://doi.org/10.1000/B",
                "display_name": "B paper",
                "id": "https://openalex.org/W1",
                "primary_location": {"source": {"display_name": "J"}},
            }],
            "meta": {"next_cursor": None},
        }
    monkeypatch.setattr(discovery, "get_json", fake)
    rows = discovery.openalex_fulltext_search(2025, ["Advanced Imaging Core"], api_key="key")
    assert rows[0]["doi"] == "10.1000/b"
    assert rows[0]["matched_query"] == "Advanced Imaging Core"
    assert "fulltext.search.exact" in calls[0]
    assert "api_key=key" in calls[0]


def test_openalex_known_user_orcid(monkeypatch):
    def fake(url, **kwargs):
        assert "authorships.author.orcid" in url
        assert "2023-01-01" in url and "2026-12-31" in url
        return {
            "results": [{
                "doi": "https://doi.org/10.1000/C",
                "display_name": "C paper",
                "id": "https://openalex.org/W2",
                "primary_location": {"source": {"display_name": "J"}},
            }],
            "meta": {"next_cursor": None},
        }
    monkeypatch.setattr(discovery, "get_json", fake)
    rows = discovery.openalex_author_works("0000-0001-2345-6789", 2023, 2026)
    assert rows[0]["doi"] == "10.1000/c"
    assert rows[0]["discovery_sources"] == ["known_user_orcid"]


def test_datacite_dataset_to_publication(monkeypatch):
    def fake(url, **kwargs):
        return {"data": [{
            "id": "10.5281/zenodo.1",
            "attributes": {
                "doi": "10.5281/zenodo.1",
                "relatedIdentifiers": [{
                    "relatedIdentifierType": "DOI",
                    "relatedIdentifier": "10.1000/D",
                    "relationType": "IsSupplementTo",
                }],
            },
        }]}
    monkeypatch.setattr(discovery, "get_json", fake)
    rows = discovery.datacite_related_publications('"Advanced Imaging Core"', year=2025)
    assert rows[0]["doi"] == "10.1000/d"
    assert rows[0]["discovery_sources"] == ["datacite_related"]
    assert rows[0]["related_dataset_doi"] == "10.5281/zenodo.1"
    assert rows[0]["relation_type"] == "IsSupplementTo"
    assert rows[0]["discovery_evidence"] == [{
        "related_dataset_doi": "10.5281/zenodo.1",
        "relation_type": "IsSupplementTo",
        "sources": ["datacite_related"],
    }]


def test_crossref_award_keeps_unverified_funder_hit(monkeypatch):
    monkeypatch.setattr(
        discovery,
        "get_json",
        lambda url, **kwargs: {"message": {"items": [{
            "DOI": "10.1000/x",
            "title": ["X"],
            "container-title": ["J"],
            "type": "journal-article",
            "funder": [{"name": "Unrelated Foundation"}],
        }]}},
    )
    rows = discovery.crossref_award_search(
        2025,
        ["359073"],
        expected_funders=["Research Council of Finland", "Academy of Finland"],
    )
    assert rows[0]["expected_funder_verified"] is False


def test_dedupe_preserves_multiple_match_reasons():
    rows = discovery._dedupe([
        {
            "doi": "10.1000/x",
            "matched_query": "Advanced Imaging Core",
            "discovery_sources": ["openalex_fulltext"],
        },
        {
            "doi": "10.1000/x",
            "matched_query": "359073",
            "discovery_sources": ["openalex_fulltext"],
        },
    ])
    assert len(rows) == 1
    evidence = rows[0]["discovery_evidence"]
    assert {item["matched_query"] for item in evidence} == {
        "Advanced Imaging Core",
        "359073",
    }


def test_datacite_paginates_and_respects_max_pages(monkeypatch):
    calls = []
    def fake(url, **kwargs):
        calls.append(url)
        if "page%5Bnumber%5D=1" in url:
            return {
                "data": [{
                    "id": "10.5281/zenodo.1",
                    "attributes": {
                        "doi": "10.5281/zenodo.1",
                        "relatedIdentifiers": [{
                            "relatedIdentifierType": "DOI",
                            "relatedIdentifier": "10.1000/a",
                            "relationType": "IsSupplementTo",
                        }],
                    },
                }],
                "meta": {"totalPages": 3},
            }
        return {
            "data": [{
                "id": "10.5281/zenodo.2",
                "attributes": {
                    "doi": "10.5281/zenodo.2",
                    "relatedIdentifiers": [{
                        "relatedIdentifierType": "DOI",
                        "relatedIdentifier": "10.1000/b",
                        "relationType": "IsSupplementTo",
                    }],
                },
            }],
            "meta": {"totalPages": 3},
        }

    monkeypatch.setattr(discovery, "get_json", fake)
    rows = discovery.datacite_related_publications(
        '"Advanced Imaging Core"',
        year=2025,
        page_size=1,
        max_pages=2,
    )
    assert {row["doi"] for row in rows} == {"10.1000/a", "10.1000/b"}
    assert len(calls) == 2
    assert all(row["discovery_truncated"] is True for row in rows)


def test_crossref_award_cursor_paginates_and_marks_truncation(monkeypatch):
    calls = []
    def fake(url, **kwargs):
        calls.append(url)
        if "cursor=%2A" in url:
            return {"message": {
                "items": [{
                    "DOI": "10.1000/a",
                    "title": ["A"],
                    "container-title": ["J"],
                    "type": "journal-article",
                    "funder": [{"name": "Research Council of Finland"}],
                }],
                "next-cursor": "cursor-2",
            }}
        return {"message": {
            "items": [{
                "DOI": "10.1000/b",
                "title": ["B"],
                "container-title": ["J"],
                "type": "journal-article",
                "funder": [{"name": "Research Council of Finland"}],
            }],
            "next-cursor": "cursor-3",
        }}

    monkeypatch.setattr(discovery, "get_json", fake)
    rows = discovery.crossref_award_search(
        2025,
        ["359073"],
        rows=1,
        expected_funders=["Research Council of Finland"],
        max_pages=2,
        timeout=5,
    )
    assert {row["doi"] for row in rows} == {"10.1000/a", "10.1000/b"}
    assert len(calls) == 2
    assert all("award.number%3A359073" in url for url in calls)
    assert all("rows=1" in url for url in calls)
    assert "cursor=cursor-2" in calls[1]
    assert all(row["discovery_truncated"] is True for row in rows)
