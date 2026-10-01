import json

import pytest

from aic_pubs import papers, validation


def test_summarize_recall_misses_and_new_finds():
    rows = {
        "10.1000/a": {"priority": "report", "has_text": True, "category": "A"},
        "10.1000/b": {"priority": "low", "has_text": True, "category": "F"},
        "10.1000/c": {"has_text": False, "category": "N"},
        "10.1000/new": {"priority": "check", "has_text": True, "category": "B"},
    }
    confirmed = {"10.1000/a", "10.1000/b", "10.1000/c", "10.1000/gone"}
    s = validation.summarize(2023, confirmed, rows, universe=set(rows))
    assert s["found"] == 1 and s["listed"] == 4 and s["recall"] == 0.25
    assert s["missed"]["10.1000/gone"].startswith("not among")
    assert s["missed"]["10.1000/c"] == "no full text"
    assert "ranked low" in s["missed"]["10.1000/b"]
    assert s["new_check"] == ["10.1000/new"] and s["new_report"] == []
    lo, hi = s["recall_ci"]
    assert 0 < lo < 0.25 < hi < 1


def test_year_summary_reads_the_swept_year_and_the_confirmed_papers(monkeypatch, isolated_folders):
    papers.write_papers([{"doi": "10.1000/a", "year": 2023}])
    rows = [{"doi": "10.1000/a", "priority": "report", "has_text": True, "category": "A"}]
    monkeypatch.setattr(validation, "load_screened", lambda year: rows)
    (isolated_folders / "2023").mkdir()
    (isolated_folders / "2023" / "universe.json").write_text(json.dumps(["10.1000/a"]))
    s = validation.year_summary(2023)
    assert s["recall"] == 1.0 and "2023" in validation.format_summaries([s])


def test_cli_refuses_years_that_were_not_swept(capsys):
    from aic_pubs import cli
    with pytest.raises(SystemExit, match="not swept yet: 2019"):
        cli.main(["validate", "--years", "2019"])
    with pytest.raises(SystemExit, match="not swept yet: 2019"):
        cli.main(["report", "--year", "2019"])


def test_cli_requires_its_arguments():
    from aic_pubs import cli
    with pytest.raises(SystemExit):
        cli.main(["sheet"])                    # --year is required
