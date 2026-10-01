import pytest

from facility_pubs import workflow


def test_swept_years_are_the_years_with_screening_results(isolated_folders):
    for y in ("2023", "2025", "notes"):
        (isolated_folders / y).mkdir()
        (isolated_folders / y / "screened.jsonl").write_text("")
    (isolated_folders / "2024").mkdir()                       # built folder without results
    assert workflow.swept_years() == [2023, 2025]


def test_prepare_sheet_refuses_a_year_that_is_not_built():
    with pytest.raises(SystemExit, match="not built yet"):
        workflow.prepare_sheet(object(), 2024)


def test_drive_folder_id_outside_drive_is_none(tmp_path):
    assert workflow.drive_folder_id(tmp_path) is None


def test_learn_refreshes_only_the_other_years_with_a_sheet(monkeypatch, isolated_folders):
    for y in ("2023", "2024", "2025"):
        (isolated_folders / y).mkdir()
        (isolated_folders / y / "screened.jsonl").write_text("")
    calls = []
    monkeypatch.setattr(workflow.gsheets, "validated_dois", lambda gc, years: [])
    monkeypatch.setattr(workflow.embeddings, "run", lambda years, **kw: calls.append(years) or [])
    monkeypatch.setattr(workflow.gsheets, "has_sheet", lambda y: y in (2023, 2024))
    monkeypatch.setattr(workflow.gsheets, "sync", lambda gc, y, top_n=100: (f"url{y}", ""))
    assert workflow.learn(object(), 2024) == {2023: "url2023"}
    assert calls == [[2023, 2024, 2025]]


def test_issue_link_opens_the_add_papers_form_with_the_dois_filled_in():
    import urllib.parse
    link = workflow.issue_link("https://github.com/org/repo.git", "my-core", "10.1000/a\n10.1000/b 2025")
    base, query = link.split("?")
    assert base == "https://github.com/org/repo/issues/new"
    assert urllib.parse.parse_qs(query) == {"template": ["add-papers.yml"], "facility": ["my-core"],
                                            "dois": ["10.1000/a\n10.1000/b 2025"]}
