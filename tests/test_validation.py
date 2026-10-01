import json

from aic_pubs import validation


def test_year_summary_recall_misses_and_new_finds(monkeypatch, tmp_path):
    monkeypatch.setattr(validation, "DATA", tmp_path)
    base = tmp_path / "2023"
    base.mkdir()
    (base / "facility_list.json").write_text(json.dumps(["10.1/a", "10.1/b", "10.1/c", "10.1/gone"]))
    (base / "universe.json").write_text(json.dumps(["10.1/a", "10.1/b", "10.1/c", "10.1/new"]))
    rows = [
        {"doi": "10.1/a", "priority": "report", "has_text": True, "category": "A"},
        {"doi": "10.1/b", "priority": "low", "has_text": True, "category": "F"},
        {"doi": "10.1/c", "has_text": False, "category": "N"},
        {"doi": "10.1/new", "priority": "check", "has_text": True, "category": "B"},
    ]
    monkeypatch.setattr(validation, "load_screened", lambda year: rows)
    s = validation.year_summary(2023)
    assert s["found"] == 1 and s["listed"] == 4 and s["recall"] == 0.25
    assert s["missed"]["10.1/gone"].startswith("not in")
    assert s["missed"]["10.1/c"] == "no full text"
    assert "ranked low" in s["missed"]["10.1/b"]
    assert s["new_check"] == ["10.1/new"] and s["new_report"] == []
    sheet = (base / "validation.csv").read_text()
    assert "missed listed paper" in sheet and "new: AIC instrument" in sheet


def test_cli_skips_years_that_were_not_swept(monkeypatch, tmp_path, capsys):
    from aic_pubs import cli, sweep
    monkeypatch.setattr(cli, "DATA", tmp_path)
    monkeypatch.setattr(sweep, "DATA", tmp_path)
    cli.main(["validate", "--years", "2019"])
    cli.main(["report", "--year", "2019"])
    out = capsys.readouterr().out
    assert out.count("2019: not swept yet") == 2


def test_rerunning_validate_keeps_staff_verdicts_and_stamps_the_rules(monkeypatch, tmp_path):
    import csv
    monkeypatch.setattr(validation, "DATA", tmp_path)
    base = tmp_path / "2023"
    base.mkdir()
    (base / "facility_list.json").write_text(json.dumps(["10.1/a"]))
    rows = [{"doi": "10.1/new", "priority": "check", "has_text": True, "category": "B"}]
    monkeypatch.setattr(validation, "load_screened", lambda year: rows)
    validation.year_summary(2023)
    path = base / "validation.csv"
    sheet = list(csv.DictReader(path.open(newline="")))
    assert sheet[0]["rules_version"].startswith("config ")
    for r in sheet:
        if r["doi"] == "10.1/new":
            r["your_verdict"], r["your_note"] = "no", "imaged in Helsinki"
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=validation.SHEET_COLUMNS)
        w.writeheader()
        w.writerows(sheet)
    validation.year_summary(2023)
    again = {r["doi"]: r for r in csv.DictReader(path.open(newline=""))}
    assert (again["10.1/new"]["your_verdict"], again["10.1/new"]["your_note"]) == ("no", "imaged in Helsinki")


def test_verdicts_survive_excel_resaves_and_papers_leaving_the_sheet(monkeypatch, tmp_path):
    import csv
    from aic_pubs.provenance import previous_verdicts
    p = tmp_path / "s.csv"
    p.write_bytes("﻿kind;doi;your_verdict;your_note\nnew;10.1/a;yes;Excel (semicolons)\n".encode("utf-8"))
    assert previous_verdicts(p) == {"10.1/a": ("yes", "Excel (semicolons)")}
    p.write_bytes("kind;doi;your_verdict;your_note\nnew;10.1/a;no;Pétri dish\n".encode("cp1252"))
    assert previous_verdicts(p)["10.1/a"][1] == "Pétri dish"
    p.write_text("something else entirely\nx\n")
    import pytest
    with pytest.raises(SystemExit):
        previous_verdicts(p)

    monkeypatch.setattr(validation, "DATA", tmp_path)
    base = tmp_path / "2023"
    base.mkdir()
    (base / "facility_list.json").write_text(json.dumps([]))
    (base / "validation.csv").write_text("kind,doi,your_verdict,your_note\nnew,10.1/gone,no,not AIC\n")
    monkeypatch.setattr(validation, "load_screened", lambda year: [])
    validation.year_summary(2023)
    rows = list(csv.DictReader((base / "validation.csv").open(newline="")))
    assert rows[0]["kind"].startswith("earlier verdict") and rows[0]["your_note"] == "not AIC"
