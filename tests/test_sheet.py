from facility_pubs import contacts, papers, sheet

# fictitious people and addresses only
TEXT = ("Title of the paper. Ada Example1, Bo Sample2* 1 University of Somewhere. "
        "*Correspondence: Bo Sample, bo.sample@uni.example.org. Received 2024. "
        "Abstract text ... Methods: images were acquired ... "
        "For permissions write to permissions@elsevier.com. Data: ada.example@lab.example.edu")


def test_corresponding_author_is_the_address_after_the_marker_and_named_from_the_authors():
    c = contacts.corresponding_contacts(TEXT, ["Ada Example", "Bo Sample"])
    assert c == [{"name": "Bo Sample", "email": "bo.sample@uni.example.org"}]


def test_publisher_addresses_are_dropped_and_ambiguous_names_left_blank():
    assert contacts.corresponding_contacts("Contact: permissions@elsevier.com") == []
    c = contacts.corresponding_contacts("Correspondence: j.smith@x.example.org",
                                        ["Ann Smith", "Bob Smith"])
    assert c[0]["name"] == "" or c[0]["name"] == "J Smith"   # never a wrong first name
    assert "Ann" not in c[0]["name"] and "Bob" not in c[0]["name"]


def test_lastname_firstname_lists_and_one_name_per_address():
    c = contacts.corresponding_contacts(
        "Correspondence to: zhang.h@a.example.org and zhang.y@b.example.org",
        ["Zhang, Hongbo", "Zhang, Yu"])
    assert [x["name"] for x in c] == ["Hongbo Zhang", "Yu Zhang"]


def _setup_year(monkeypatch, tmp_path):
    monkeypatch.setenv("PUBS_DATA", str(tmp_path))
    rows = [
        {"doi": "10.1000/ack", "title": "Acknowledges", "priority": "report", "category": "A", "has_text": True,
         "acknowledgement": ["We thank the facility"], "score_reasons": ["+10 acknowledgement"]},
        {"doi": "10.1000/instr", "title": "Instrument", "priority": "check", "category": "B", "has_text": True},
        {"doi": "10.1000/known", "title": "Known", "priority": "low", "category": "F", "has_text": True},
        {"doi": "10.1000/sim", "title": "Similar", "priority": "low", "category": "F", "has_text": True},
    ]
    monkeypatch.setattr(sheet, "load_screened", lambda year: rows)
    from facility_pubs import validation
    monkeypatch.setattr(validation, "load_screened", lambda year: rows)
    monkeypatch.setenv("PUBS_DATA", str(tmp_path))
    monkeypatch.setattr(sheet, "cached_text", lambda year, doi: ("text with grant 359073", "x"))
    (tmp_path / "2024").mkdir()
    (tmp_path / "2024" / "embedding_ranked.csv").write_text(
        "rank,doi\n1,10.1000/known\n2,10.1000/sim\n3,10.1000/ack\n")
    papers.write_papers([{"doi": "10.1000/known", "year": 2024, "title": "Known", "source": "website"}])
    asked = []

    def fake(dois):
        asked.extend(dois)
        return {d: [{"name": "Bo Sample", "email": "bo@uni.example.org"}] for d in dois}
    fake.asked = asked
    return fake


def test_tables_most_likely_first_contacts_and_carried_verdicts(monkeypatch, tmp_path):
    fake_contacts = _setup_year(monkeypatch, tmp_path)
    previous = [{"doi": "10.1000/sim", "verdict": "Yes", "reason": "staff know the project", "note": "LSM880"},
                {"doi": "10.1000/gone", "verdict": "no", "note": "not ours"}]
    tables, to_file = sheet.build(2024, previous=previous, contacts=fake_contacts)
    v = {r["doi"]: r for r in tables["validate"]}
    assert [r["doi"] for r in tables["validate"]] == ["10.1000/ack", "10.1000/instr", "10.1000/sim", "10.1000/gone"]
    assert v["10.1000/ack"]["why"] == sheet.WHY_ACK and v["10.1000/instr"]["why"] == sheet.WHY_INSTRUMENT
    assert v["10.1000/sim"]["why"].startswith(sheet.WHY_SIMILAR) and v["10.1000/sim"]["verdict"] == "yes"
    assert v["10.1000/sim"]["reason"] == "staff know the project"
    assert v["10.1000/gone"]["why"] == sheet.WHY_EARLIER and v["10.1000/gone"]["note"] == "not ours"
    assert "10.1000/known" not in v                              # confirmed papers are not re-validated
    assert "email" not in v["10.1000/ack"]                       # contacts only for facility papers
    (c,) = tables["contacts"]                                    # one row per address, both papers
    assert c["email"] == "bo@uni.example.org" and c["papers"] == 2 and c["status"] == "confirmed"
    assert c["dois"] == "10.1000/known; 10.1000/sim" and c["grant_cited"] == "yes; yes"
    assert to_file == "10.1000/sim 2024"
    assert [m["doi"] for m in tables["search_misses"]] == ["10.1000/known"]


def test_candidates_within_a_group_follow_the_embedding_rank(monkeypatch, tmp_path):
    fake_contacts = _setup_year(monkeypatch, tmp_path)
    from facility_pubs import validation
    monkeypatch.setattr(validation, "year_summary", lambda year: {
        "new_report": ["10.1000/instr", "10.1000/ack"], "new_check": [], "missed": {}})
    monkeypatch.setattr(sheet, "_ranked", lambda year: {"10.1000/ack": 3, "10.1000/sim": 2})
    tables, _ = sheet.build(2024, contacts=fake_contacts)
    assert [r["doi"] for r in tables["validate"]][:2] == ["10.1000/ack", "10.1000/instr"]   # unranked last


def test_verdicts_saved_one_by_one_survive_a_rebuild(monkeypatch, tmp_path):
    fake_contacts = _setup_year(monkeypatch, tmp_path)
    tables, _ = sheet.build(2024, contacts=fake_contacts)
    sheet.write_tables(2024, tables)
    sheet.set_verdict(2024, "10.1000/instr", "Likely", "instrument matches, not credited", "ask the authors")
    again, to_file = sheet.build(2024, previous=sheet.read_validate(2024), contacts=fake_contacts)
    row = {r["doi"]: r for r in again["validate"]}["10.1000/instr"]
    assert (row["verdict"], row["reason"], row["note"]) == ("likely", "instrument matches, not credited",
                                                             "ask the authors")
    assert "10.1000/instr" in again["contacts"][0]["dois"] and to_file == ""     # likely: contact, not filed
    assert sheet.decisions([2024]) == [{"year": 2024, "doi": "10.1000/instr", "why": sheet.WHY_INSTRUMENT,
                                        "embedding_rank": "", "verdict": "likely",
                                        "reason": "instrument matches, not credited", "note": "ask the authors"}]


def test_set_verdict_refuses_unknown_verdicts_and_papers(monkeypatch, tmp_path):
    import pytest
    fake_contacts = _setup_year(monkeypatch, tmp_path)
    sheet.write_tables(2024, sheet.build(2024, contacts=fake_contacts)[0])
    with pytest.raises(ValueError, match="not one of"):
        sheet.set_verdict(2024, "10.1000/ack", "maybe")
    with pytest.raises(ValueError, match="is not in"):
        sheet.set_verdict(2024, "10.1000/elsewhere", "yes")
    with pytest.raises(ValueError, match="not one of"):
        sheet.build(2024, previous=[{"doi": "10.1000/ack", "verdict": "perhaps"}], contacts=fake_contacts)


def test_contacts_are_only_looked_up_for_facility_papers(monkeypatch, tmp_path):
    fake_contacts = _setup_year(monkeypatch, tmp_path)
    sheet.build(2024, previous=[{"doi": "10.1000/sim", "verdict": "likely"}], contacts=fake_contacts)
    assert sorted(fake_contacts.asked) == ["10.1000/known", "10.1000/sim"]   # not the candidates


def test_contact_rows_one_per_address_and_a_row_for_papers_without_one():
    p = lambda doi, status, contacts: {"doi": doi, "title": doi.upper(), "status": status,
                                       "acknowledges_facility": "yes", "grant_cited": "", "contacts": contacts}
    rows = sheet.contact_rows([
        p("10.1000/a", "likely", [{"name": "Bo Sample", "email": "Bo@uni.example.org"},
                                  {"name": "Ada Example", "email": "ada@lab.example.edu"}]),
        p("10.1000/b", "confirmed", [{"name": "", "email": "bo@uni.example.org"}]),
        p("10.1000/c", "confirmed", []),
    ])
    assert [(r["email"], r["status"], r["papers"]) for r in rows] == [
        ("Bo@uni.example.org", "confirmed", 2), ("ada@lab.example.edu", "likely", 1), ("", "confirmed", 1)]
    assert rows[0]["name"] == "Bo Sample" and rows[0]["dois"] == "10.1000/a; 10.1000/b"


def test_marker_words_and_institutions_are_never_taken_for_names():
    for text in ("Corresponding author. E-mail address: m.virtanen@uni.example.org",
                 "Correspondence to Department Of Biology, x.y@uni.example.org",
                 "Contact: Jyväskylä University, info2@uni.example.org"):
        c = contacts.corresponding_contacts(text)
        assert c and c[0]["name"] == "", (text, c)
    assert contacts.corresponding_contacts("Correspondence: Maria Virtanen, mv@uni.example.org")[0]["name"] == "Maria Virtanen"
    assert contacts.corresponding_contacts("see logo@2x.png") == []
