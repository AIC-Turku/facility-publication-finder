from aic_pubs.years import normalize_years


def test_institutional_year_is_authoritative():
    row = {
        "year": 2026,
        "publication_year": 2025,
        "sources": ["abo"],
    }
    out = normalize_years(row, 2025)
    assert out["reporting_year"] == 2026
    assert out["reporting_year_source"] == "institutional"
    assert out["reporting_year_provisional"] is False
    assert out["year_disagreement"] is True
    assert out["reporting_year_matches_target"] is False


def test_external_year_is_provisional():
    row = {
        "publication_year": 2025,
        "discovery_sources": ["known_users_orcid"],
    }
    out = normalize_years(row, 2025)
    assert out["reporting_year"] == 2025
    assert out["reporting_year_source"] == "external_provisional"
    assert out["reporting_year_provisional"] is True
    assert out["reporting_year_matches_target"] is True


def test_imported_cris_year_can_be_authoritative():
    row = {
        "year": 2026,
        "publication_year": 2025,
        "sources": ["utucris_export"],
        "reporting_year_authoritative": True,
    }
    out = normalize_years(row, 2025)
    assert out["reporting_year"] == 2026
    assert out["reporting_year_source"] == "institutional"
    assert out["reporting_year_provisional"] is False
    assert out["year_disagreement"] is True


def test_conflicting_authoritative_sources_are_exposed():
    row = {
        "reporting_year_assertions": [
            {"source": "institutional", "year": 2025},
            {"source": "utucris_export", "year": 2026},
        ],
        "publication_year": 2025,
    }
    out = normalize_years(row, 2025)
    assert out["reporting_year"] is None
    assert out["reporting_year_source"] == "authoritative_conflict"
    assert out["reporting_year_conflict"] is True
    assert out["reporting_year_matches_target"] is None
    assert {x["year"] for x in out["reporting_year_assertions"]} == {2025, 2026}


def test_conflicting_authoritative_years_do_not_depend_on_merge_order():
    row = {
        "reporting_year_assertions": [
            {"source": "utucris_export", "year": 2025},
            {"source": "abocris_export", "year": 2026},
        ],
        "publication_year": 2025,
    }
    out = normalize_years(row, 2025)
    assert out["reporting_year"] is None
    assert out["reporting_year_source"] == "authoritative_conflict"
    assert out["reporting_year_conflict"] is True
    assert out["reporting_year_matches_target"] is None
