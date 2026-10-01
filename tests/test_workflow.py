import pytest

from facility_pubs import workflow


def test_swept_years_are_the_years_with_screening_results(isolated_folders):
    for y in ("2023", "2025", "notes"):
        (isolated_folders / y).mkdir()
        (isolated_folders / y / "screened.jsonl").write_text("")
    (isolated_folders / "2024").mkdir()                       # built folder without results
    assert workflow.swept_years() == [2023, 2025]


def test_prepare_refuses_a_year_that_is_not_built():
    with pytest.raises(SystemExit, match="not built yet"):
        workflow.prepare(2024)


def test_learn_uses_the_decisions_and_refreshes_only_the_other_reviewed_years(monkeypatch, isolated_folders):
    for y in ("2023", "2024", "2025"):
        (isolated_folders / y).mkdir()
        (isolated_folders / y / "screened.jsonl").write_text("")
    (isolated_folders / "2023" / "validate.csv").write_text(
        "why,doi,verdict\nx,10.1000/yes,yes\nx,10.1000/no,no\nx,10.1000/open,\n")
    (isolated_folders / "2024" / "validate.csv").write_text("why,doi,verdict\n")
    calls, refreshed = [], []
    monkeypatch.setattr(workflow.embeddings, "run", lambda years, **kw: calls.append((years, kw)) or [])
    monkeypatch.setattr(workflow, "_refresh", lambda y, top_n: refreshed.append(y) or ([], ""))
    assert workflow.learn(2024) == [2023] and refreshed == [2023]
    years, kw = calls[0]
    assert years == [2023, 2024, 2025] and kw["extra_known"] == [{"doi": "10.1000/yes", "year": 2023}]
    assert kw["rejected"] == {"10.1000/no"}


def test_feedback_is_written_to_the_data_folder(isolated_folders):
    (isolated_folders / "2024").mkdir()
    (isolated_folders / "2024" / "screened.jsonl").write_text("")
    (isolated_folders / "2024" / "validate.csv").write_text(
        "why,doi,embedding_rank,verdict,reason\nreads like facility papers (rank 7),10.1000/a,7,yes,\n")
    text, path = workflow.feedback()
    assert "1 decisions" in text and path.read_text().startswith("1 decisions")


def test_issue_link_opens_the_add_papers_form_with_the_dois_filled_in():
    import urllib.parse
    link = workflow.issue_link("https://github.com/org/repo.git", "my-core", "10.1000/a\n10.1000/b 2025")
    base, query = link.split("?")
    assert base == "https://github.com/org/repo/issues/new"
    assert urllib.parse.parse_qs(query) == {"template": ["add-papers.yml"], "facility": ["my-core"],
                                            "dois": ["10.1000/a\n10.1000/b 2025"]}
