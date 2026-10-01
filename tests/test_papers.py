import re

import yaml

from facility_pubs import papers
from facility_pubs.config import FACILITIES, load


def fake_fetch(dois):
    known = {
        "10.1000/a": {"doi": "10.1000/a", "title": "Paper A", "journal": "J", "published": "2024-05-01",
                      "issued_year": "2024", "type": "journal-article", "pmcid": "PMC1"},
        "10.1000/b": {"doi": "10.1000/b", "title": "Paper B", "journal": "J", "published": "2025-01-02",
                      "issued_year": "2025", "type": "journal-article"},
    }
    return {d: known[d] for d in dois if d in known}


def test_inbox_accepts_dois_links_years_and_junk():
    parsed = papers.parse_inbox("# a comment\n10.1000/A 2023\nhttps://doi.org/10.1000/b\n"
                                "see doi:10.1000/c, thanks\nno doi here\n\n")
    assert [(d, y) for _, d, y in parsed] == [("10.1000/a", 2023), ("10.1000/b", None),
                                              ("10.1000/c", None), (None, None)]


def test_add_papers_files_by_year_dedupes_sorts_and_keeps_unresolved_lines(empty_confirmed_papers):
    summary, left = papers.add_papers("10.1000/b\n10.1000/a\n10.1000/a\n10.1000/zzz\nnothing",
                                      fetch=fake_fetch, today="2026-10-01")
    assert sorted(summary["added"]) == ["10.1000/a", "10.1000/b"] and summary["already_filed"] == ["10.1000/a"]
    assert left == ["10.1000/zzz    # not found in Crossref: check the DOI"]
    assert summary["dropped_lines"] == 1                 # "nothing": no DOI, not kept
    y24 = yaml.safe_load((empty_confirmed_papers / "2024.yaml").read_text())
    assert y24 == [{"doi": "10.1000/a", "title": "Paper A", "journal": "J", "published": "2024-05-01",
                    "type": "journal-article", "pmcid": "PMC1", "source": "staff-reviewed", "added": "2026-10-01"}]
    assert (empty_confirmed_papers / "2025.yaml").read_text().startswith("# ")   # header comment


def test_a_year_given_with_a_filed_doi_moves_it(empty_confirmed_papers):
    papers.add_papers("10.1000/a", fetch=fake_fetch)
    summary, _ = papers.add_papers("10.1000/a 2023", fetch=fake_fetch)
    assert summary["moved"] == ["10.1000/a"]
    assert [p["year"] for p in papers.load_papers()] == [2023]
    assert not (empty_confirmed_papers / "2024.yaml").exists()


def test_process_inbox_empties_the_inbox_but_keeps_its_instructions(empty_confirmed_papers):
    inbox = papers.inbox_path()
    inbox.write_text(papers.INBOX_HEADER + "10.1000/b\n10.1000/unknown\n")
    s = papers.process_inbox(fetch=fake_fetch)
    text = inbox.read_text()
    assert s["added"] == ["10.1000/b"] and text.startswith(papers.INBOX_HEADER)
    assert "10.1000/b" not in text.replace(papers.INBOX_HEADER, "") and "10.1000/unknown" in text


def test_known_dois_are_the_confirmed_papers_of_the_year(empty_confirmed_papers):
    papers.write_papers([{"doi": "10.1000/a", "year": 2024}, {"doi": "10.1000/b", "year": 2023}])
    assert papers.known_dois(2024) == {"10.1000/a"}


def test_the_aic_papers_files_are_valid_and_unique():
    seen = set()
    for path in sorted((FACILITIES / "aic-turku" / "papers").glob("*.yaml")):
        entries = yaml.safe_load(path.read_text())
        dois = [e["doi"] for e in entries]
        assert dois == sorted(dois) and not seen & set(dois), path
        seen |= set(dois)
        assert all(set(e) <= set(papers.FIELDS) for e in entries)
        email = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")                  # ("core@shell" is a title)
        assert not any(email.search(str(v)) for e in entries for v in e.values())
    assert len(seen) >= 576


def test_template_facility_loads():
    cfg = load(FACILITIES / "template" / "facility.yaml")
    assert cfg.institutional_sources[0]["adapter"] == "dspace7" and cfg.instruments


def test_an_unresolved_line_keeps_one_note(empty_confirmed_papers):
    _, left = papers.add_papers("10.1000/zzz", fetch=fake_fetch)
    _, left = papers.add_papers("\n".join(left), fetch=fake_fetch)
    assert left == ["10.1000/zzz    # not found in Crossref: check the DOI"]


def test_several_dois_per_line_and_only_a_year_right_after_its_doi(empty_confirmed_papers):
    parsed = papers.parse_inbox("10.1000/a 10.1000/b 2025\nSmith et al. 2023, Nature, https://doi.org/10.1000/c\n"
                                "10.1038/a 10.1016/j.x.2024.01.002")
    assert [(d, y) for _, d, y in parsed] == [("10.1000/a", None), ("10.1000/b", 2025), ("10.1000/c", None),
                                              ("10.1038/a", None), ("10.1016/j.x.2024.01.002", None)]


def test_leftover_lines_keep_only_the_doi_never_pasted_personal_data(empty_confirmed_papers):
    _, left = papers.add_papers("10.1000/zzz Jane Doe jane.doe@uni.example.org", fetch=fake_fetch)
    assert left == ["10.1000/zzz    # not found in Crossref: check the DOI"]


def test_hand_edits_are_normalised_and_extra_keys_kept(empty_confirmed_papers):
    (empty_confirmed_papers / "2024.yaml").write_text("- doi: 10.1000/HAND\n  note: from the annual report\n")
    papers.add_papers("10.1000/hand", fetch=fake_fetch)
    entries = papers.load_papers()
    assert len(entries) == 1 and entries[0]["doi"] == "10.1000/hand" and entries[0]["note"] == "from the annual report"


def test_website_import_never_moves_a_filed_paper(empty_confirmed_papers):
    papers.add_papers("10.1000/a 2023", fetch=fake_fetch, source="staff-reviewed")
    s, _ = papers.add_papers("10.1000/a 2024", fetch=fake_fetch, source="website", allow_moves=False)
    assert s["moved"] == [] and papers.load_papers()[0]["year"] == 2023


def test_inboxes_never_hold_e_mail_addresses():
    for inbox in FACILITIES.glob("*/inbox.txt"):
        assert not re.search(r"[\w.+-]+@[\w-]+\.[\w.]+", inbox.read_text()), inbox


def test_facility_yaml_errors_name_the_problem(tmp_path):
    import pytest
    good = (FACILITIES / "template" / "facility.yaml").read_text()
    for broken, message in ((good.replace("institutional_fields: all", "institutional_fields: scince"), "institutional_fields"),
                            (good.replace("adapter: dspace7", "adapter: eprints"), "adapter"),
                            (good.replace("local_email_domains:", "local_email_domainz:"), "missing local_email_domains")):
        path = tmp_path / "facility.yaml"
        path.write_text(broken)
        with pytest.raises(ValueError, match=message):
            load(path)


def test_check_papers_reports_new_dois_and_whether_they_resolve(empty_confirmed_papers):
    papers.add_papers("10.1000/a\n10.1000/b", fetch=fake_fetch)
    new, problems = papers.check_papers({"10.1000/a"}, resolves=lambda d: d != "10.1000/b")
    assert [e["doi"] for e in new] == ["10.1000/b"] and new[0]["source"] == "staff-reviewed"
    assert problems == ["10.1000/b: does not resolve in Crossref"]
    assert papers.check_papers({"10.1000/a"}, resolves=lambda d: True) == (new, [])


def test_check_papers_refuses_anything_but_public_metadata(empty_confirmed_papers):
    (empty_confirmed_papers / "2024.yaml").write_text(
        "- doi: 10.1000/z\n  acknowledges: no\n- doi: https://doi.org/10.1000/B\n"
        "- doi: 10.1000/c\n  title: write to x.y@uni.example.org\n  source: staff-reviewed\n")
    (empty_confirmed_papers / "2025.yaml").write_text("- doi: 10.1000/c\n  source: staff-reviewed\n")
    _, problems = papers.check_papers(set(), resolves=lambda d: True)
    text = "\n".join(problems)
    assert "not sorted" in text and "10.1000/z: only public metadata may be filed, not acknowledges" in text
    assert "https://doi.org/10.1000/B is not a normalised DOI" in text
    assert "10.1000/c: looks like it holds an e-mail address" in text
    assert "10.1000/c: filed twice (2024 and 2025)" in text
    assert "10.1000/z: new paper without a source (how it was confirmed)" in text


def test_add_papers_from_a_file_leaves_the_inbox_alone(empty_confirmed_papers, tmp_path, monkeypatch, capsys):
    from facility_pubs import cli
    monkeypatch.setattr(papers, "metadata", fake_fetch)
    papers.inbox_path().write_text(papers.INBOX_HEADER + "10.1000/a\n")
    issue = tmp_path / "issue.txt"
    issue.write_text("Reviewed by staff:\nhttps://doi.org/10.1000/b\n10.1000/zzz\n")
    cli.main(["add-papers", "--from", str(issue)])
    out = capsys.readouterr().out
    assert "+ 10.1000/b" in out and "! 10.1000/zzz    # not found in Crossref" in out
    assert [p["doi"] for p in papers.load_papers()] == ["10.1000/b"]
    assert papers.inbox_path().read_text().endswith("10.1000/a\n")
