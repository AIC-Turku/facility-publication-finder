from facility_pubs import candidates


def test_institutional_universe_science_gate_is_configurable(monkeypatch):
    monkeypatch.setattr(
        candidates.sources,
        "utupub_items",
        lambda year, **kw: [{
            "doi": "10.1000/x",
            "title": "Interdisciplinary paper",
            "year": year,
            "fields": ["6"],
            "local_authors": ["Example, Erik"],
        }],
    )
    monkeypatch.setattr(candidates.sources, "abo_items", lambda year, **kw: {})
    # default: humanities-only item (field 6) is skipped (2025: 993 such papers, 0 AIC leads)
    assert "10.1000/x" not in candidates.institutional_universe(2025)
    # institutional_fields: all
    assert "10.1000/x" in candidates.institutional_universe(2025, science_only=False)
