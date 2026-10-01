from aic_pubs import diagnostics
from aic_pubs.pipeline.types import TextAttempt


def test_probe_doi_reports_each_strategy(monkeypatch):
    def fake_run(name, paper, context, options=None):
        return TextAttempt(
            strategy=name,
            status="success" if name == "europepmc" else "miss",
            text="x" * 2000 if name == "europepmc" else None,
            source=name if name == "europepmc" else None,
            quality="high" if name == "europepmc" else None,
            scope="full" if name == "europepmc" else None,
            reason=None if name == "europepmc" else "none",
        )

    monkeypatch.setattr(diagnostics.text_strategies, "run", fake_run)
    out = diagnostics.probe_doi("10.1000/x", year=2025)
    assert out["doi"] == "10.1000/x"
    assert [row["strategy"] for row in out["attempts"]] == [
        "europepmc",
        "publisher_html",
        "crossref_fulltext",
        "openalex_oa",
    ]
    assert out["attempts"][0]["status"] == "success"
    assert out["attempts"][0]["text_chars"] == 2000


def test_probe_orcid_returns_compact_work_metadata(monkeypatch):
    monkeypatch.setattr(
        diagnostics.discovery,
        "openalex_author_works",
        lambda orcid, from_year, to_year, api_key=None, timeout=20, max_pages=2: [{
            "doi": "10.1000/x",
            "title": "Paper X",
            "publication_year": 2025,
            "publication_date": "2025-04-01",
            "openalex_id": "https://openalex.org/W1",
            "openalex_type": "article",
            "openalex_primary_version": "publishedVersion",
            "is_retracted": False,
            "is_paratext": False,
        }],
    )
    out = diagnostics.probe_orcid("0000-0002-1825-0097", 2025)
    assert out["year"] == 2025
    assert out["works"] == [{
        "doi": "10.1000/x",
        "title": "Paper X",
        "publication_year": 2025,
        "publication_date": "2025-04-01",
        "openalex_id": "https://openalex.org/W1",
        "openalex_type": "article",
        "openalex_primary_version": "publishedVersion",
        "is_retracted": False,
        "is_paratext": False,
    }]
