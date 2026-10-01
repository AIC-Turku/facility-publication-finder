import json

from aic_pubs import contacts, papers, sheet

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
    monkeypatch.setattr(sheet, "DATA", tmp_path)
    rows = [
        {"doi": "10.1000/ack", "title": "Acknowledges", "priority": "report", "category": "A", "has_text": True,
         "acknowledgement": ["We thank the facility"], "score_reasons": ["+10 acknowledgement"]},
        {"doi": "10.1000/instr", "title": "Instrument", "priority": "check", "category": "B", "has_text": True},
        {"doi": "10.1000/known", "title": "Known", "priority": "low", "category": "F", "has_text": True},
        {"doi": "10.1000/sim", "title": "Similar", "priority": "low", "category": "F", "has_text": True},
    ]
    monkeypatch.setattr(sheet, "load_screened", lambda year: rows)
    from aic_pubs import validation
    monkeypatch.setattr(validation, "load_screened", lambda year: rows)
    monkeypatch.setattr(validation, "DATA", tmp_path)
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


def test_workbook_tabs_reasons_contacts_and_carried_verdicts(monkeypatch, tmp_path):
    fake_contacts = _setup_year(monkeypatch, tmp_path)
    previous = [{"doi": "10.1000/sim", "verdict": "Yes", "note": "imaged on the LSM880"},
                {"doi": "10.1000/gone", "verdict": "no", "note": "not ours"}]
    tabs, inbox = sheet.build(2024, previous=previous, contacts=fake_contacts)
    v = {r["doi"]: r for r in tabs["Validate"]}
    assert v["10.1000/ack"]["why"] == sheet.WHY_ACK and v["10.1000/instr"]["why"] == sheet.WHY_INSTRUMENT
    assert v["10.1000/sim"]["why"].startswith(sheet.WHY_SIMILAR) and v["10.1000/sim"]["verdict"] == "yes"
    assert v["10.1000/gone"]["why"] == sheet.WHY_EARLIER and v["10.1000/gone"]["note"] == "not ours"
    assert "10.1000/known" not in v                              # confirmed papers are not re-validated
    assert "email" not in v["10.1000/ack"]                       # contacts only for facility papers
    p = {r["doi"]: r for r in tabs["Facility papers"]}
    assert set(p) == {"10.1000/known", "10.1000/sim"}               # confirmed + validated yes
    assert p["10.1000/known"]["confirmed_by"] == "website" and p["10.1000/sim"]["grant_cited"] == "yes"
    assert p["10.1000/sim"]["email"] == "bo@uni.example.org" and p["10.1000/sim"]["other_contacts"] == ""
    assert inbox == "10.1000/sim 2024"
    assert [m["doi"] for m in tabs["Search misses"]] == ["10.1000/known"]


def test_csv_round_trip_keeps_verdicts(monkeypatch, tmp_path):
    fake_contacts = _setup_year(monkeypatch, tmp_path)
    tabs, _ = sheet.build(2024, contacts=fake_contacts)
    for r in tabs["Validate"]:
        if r["doi"] == "10.1000/instr":
            r["verdict"], r["note"] = "likely", "ask the authors"
    sheet.write_csv(2024, tabs)
    again, _ = sheet.build(2024, previous=sheet.read_csv_validate(2024), contacts=fake_contacts)
    assert {r["doi"]: r["verdict"] for r in again["Validate"]}["10.1000/instr"] == "likely"
    assert "10.1000/instr" in {r["doi"] for r in again["Facility papers"]}


class FakeWorksheet:
    def __init__(self, title, rows=0, cols=0):
        self.title, self.id, self.values = title, abs(hash(title)) % 1000, []

    def get_all_values(self):
        return self.values

    def clear(self):
        self.values = []

    def resize(self, rows, cols):
        pass

    def update(self, range_name, values):
        self.values = values


class FakeSpreadsheet:
    id, url = "sheet-id", "https://docs.google.com/spreadsheets/d/sheet-id"

    def __init__(self):
        self.tabs, self.requests = {"Taulukko1": FakeWorksheet("Taulukko1")}, []   # Finnish default tab

    def worksheet(self, name):
        if name not in self.tabs:
            raise KeyError(name)
        return self.tabs[name]

    def add_worksheet(self, title, rows, cols):
        self.tabs[title] = FakeWorksheet(title)
        return self.tabs[title]

    def del_worksheet(self, ws):
        self.tabs.pop(ws.title)

    def worksheets(self):
        return list(self.tabs.values())

    def batch_update(self, body):
        self.requests += body["requests"]


class FakeClient:
    def __init__(self):
        self.sh = FakeSpreadsheet()

    def create(self, title, folder_id=None):
        return self.sh

    def open_by_key(self, key):
        return self.sh


def test_google_sheet_sync_creates_tabs_with_a_dropdown_and_keeps_verdicts(monkeypatch, tmp_path):
    from aic_pubs import gsheets
    fake_contacts = _setup_year(monkeypatch, tmp_path)
    monkeypatch.setattr(gsheets, "DATA", tmp_path)
    gc = FakeClient()
    url, inbox = gsheets.sync(gc, 2024, contacts=fake_contacts)
    assert set(gc.sh.tabs) == set(sheet.TABS) and inbox == ""
    assert any("setDataValidation" in r for r in gc.sh.requests)
    assert json.loads((tmp_path / "2024" / "sheet.json").read_text())["id"] == "sheet-id"
    ws = gc.sh.tabs["Validate"]                                   # staff fill a verdict
    header = ws.values[0]
    for row in ws.values[1:]:
        if row[header.index("doi")] == "10.1000/ack":
            row[header.index("verdict")] = "yes"
    url, inbox = gsheets.sync(gc, 2024, contacts=fake_contacts)
    assert inbox == "10.1000/ack 2024"
    assert "10.1000/ack" in [r[0] for r in gc.sh.tabs["Facility papers"].values[1:]]
    assert gsheets.validated_dois(gc, [2024]) == [{"doi": "10.1000/ack", "year": 2024}]


def test_contacts_are_only_looked_up_for_facility_papers(monkeypatch, tmp_path):
    fake_contacts = _setup_year(monkeypatch, tmp_path)
    sheet.build(2024, previous=[{"doi": "10.1000/sim", "verdict": "likely"}], contacts=fake_contacts)
    assert sorted(fake_contacts.asked) == ["10.1000/known", "10.1000/sim"]   # not the candidates


def test_notes_typed_in_facility_papers_survive_a_refresh(monkeypatch, tmp_path):
    fake_contacts = _setup_year(monkeypatch, tmp_path)
    tabs, _ = sheet.build(2024, contacts=fake_contacts,
                          previous_papers=[{"doi": "10.1000/known", "verdict": "", "note": "e-mailed 1.10."}])
    assert {r["doi"]: r["note"] for r in tabs["Facility papers"]}["10.1000/known"] == "e-mailed 1.10."


def test_a_recorded_sheet_that_cannot_be_opened_is_never_replaced(monkeypatch, tmp_path):
    import pytest
    from aic_pubs import gsheets
    monkeypatch.setattr(gsheets, "DATA", tmp_path)
    (tmp_path / "2024").mkdir()
    (tmp_path / "2024" / "sheet.json").write_text(json.dumps({"id": "gone", "url": "https://x"}))

    class NoAccess(FakeClient):
        def open_by_key(self, key):
            raise PermissionError("403")
    with pytest.raises(SystemExit, match="Share it"):
        gsheets.open_or_create(NoAccess(), 2024)
    assert json.loads((tmp_path / "2024" / "sheet.json").read_text())["id"] == "gone"
    assert gsheets.open_or_create(FakeClient(), 2023, create=False) is None


def test_marker_words_and_institutions_are_never_taken_for_names():
    for text in ("Corresponding author. E-mail address: m.virtanen@uni.example.org",
                 "Correspondence to Department Of Biology, x.y@uni.example.org",
                 "Contact: Jyväskylä University, info2@uni.example.org"):
        c = contacts.corresponding_contacts(text)
        assert c and c[0]["name"] == "", (text, c)
    assert contacts.corresponding_contacts("Correspondence: Maria Virtanen, mv@uni.example.org")[0]["name"] == "Maria Virtanen"
    assert contacts.corresponding_contacts("see logo@2x.png") == []
