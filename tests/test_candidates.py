from aic_pubs import candidates


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


def test_full_given_names_do_not_collapse_to_initial():
    from aic_pubs.identity import same_person

    assert same_person("Erik Example", "Example, Erik")
    assert same_person("Erik Example", "Example, E")
    assert not same_person("Anna Tester", "Antti Tester")


def test_name_match_strength_distinguishes_initial_only():
    from aic_pubs.identity import name_match_strength

    assert name_match_strength(
        "Erik Example",
        "Example, Erik",
    ) == "exact"
    assert name_match_strength(
        "Erik Example",
        "Example, E",
    ) == "initial"
    assert name_match_strength(
        "Anna Tester",
        "Antti Tester",
    ) is None
