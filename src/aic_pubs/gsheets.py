"""Google Sheets for the validation workbook (Colab: gspread is preinstalled).

    from google.colab import auth; auth.authenticate_user()
    import google.auth, gspread
    gc = gspread.authorize(google.auth.default()[0])
    url, inbox = gsheets.sync(gc, 2024)

`sync` reads the verdicts already in the year's Sheet, rebuilds every tab (sheet.build) with
those verdicts carried over, and writes it back: run it to create the Sheet, and again after
validating to refresh the Facility papers tab and get the DOIs to paste into the repository.
The Sheet's id is kept in <data>/<year>/sheet.json, so every run updates the same Sheet.
"""
import json

from . import sheet
from .sweep import DATA

VERDICT_COLUMN = "verdict"


def _store(year):
    return DATA / str(year) / "sheet.json"


def open_or_create(gc, year, title=None, folder_id=None, create=True):
    """The year's spreadsheet: reopened from sheet.json, else created (in folder_id if given).

    A Sheet recorded in sheet.json that cannot be opened is an error, never silently replaced
    by an empty one (that would lose the verdicts): share it with this Google account, or
    delete <data>/<year>/sheet.json to start a new Sheet. create=False returns None instead
    of creating one."""
    path = _store(year)
    if path.exists():
        info = json.loads(path.read_text())
        try:
            return gc.open_by_key(info["id"])
        except Exception as exc:  # noqa: BLE001 - not shared, in the bin, network, quota ...
            raise SystemExit(f"Cannot open the {year} Sheet {info.get('url', info['id'])} "
                             f"({type(exc).__name__}). Share it with this Google account (or restore it "
                             f"from the bin), or delete {path} to start a new Sheet.") from None
    if not create:
        return None
    from .config import load
    title = title or f"{load().raw['facility']['name']} - publications {year}"
    sh = gc.create(title, folder_id=folder_id) if folder_id else gc.create(title)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"id": sh.id, "url": sh.url, "title": title}))
    return sh


def read_tab(sh, name):
    """Rows of a tab as dicts (header row = keys), or [] when the tab does not exist yet."""
    try:
        ws = sh.worksheet(name)
    except Exception:  # noqa: BLE001 - gspread.WorksheetNotFound
        return []
    values = ws.get_all_values()
    if not values:
        return []
    header = values[0]
    return [dict(zip(header, row + [""] * (len(header) - len(row)))) for row in values[1:]]


def write_tab(sh, name, columns, rows):
    """Replace a tab's content; header bold and frozen; a yes/likely/no dropdown on `verdict`."""
    values = [columns] + [[_cell(r.get(c, "")) for c in columns] for r in rows]
    try:
        ws = sh.worksheet(name)
        ws.clear()
        ws.resize(rows=max(len(values), 2), cols=len(columns))
    except Exception:  # noqa: BLE001 - gspread.WorksheetNotFound
        ws = sh.add_worksheet(title=name, rows=max(len(values), 2), cols=len(columns))
    ws.update(range_name="A1", values=values)
    requests = [
        {"updateSheetProperties": {"properties": {"sheetId": ws.id, "gridProperties": {"frozenRowCount": 1}},
                                   "fields": "gridProperties.frozenRowCount"}},
        {"repeatCell": {"range": {"sheetId": ws.id, "startRowIndex": 0, "endRowIndex": 1},
                        "cell": {"userEnteredFormat": {"textFormat": {"bold": True}}},
                        "fields": "userEnteredFormat.textFormat.bold"}},
    ]
    if VERDICT_COLUMN in columns and len(values) > 1:
        col = columns.index(VERDICT_COLUMN)
        requests.append({"setDataValidation": {
            "range": {"sheetId": ws.id, "startRowIndex": 1, "endRowIndex": len(values),
                      "startColumnIndex": col, "endColumnIndex": col + 1},
            "rule": {"condition": {"type": "ONE_OF_LIST",
                                   "values": [{"userEnteredValue": v} for v in sheet.VERDICTS]},
                     "showCustomUi": True, "strict": False}}})
    sh.batch_update({"requests": requests})
    return ws


def _cell(value):
    text = "" if value is None else str(value)
    return text if len(text) < 49000 else text[:49000]   # Sheets limit: 50,000 characters per cell


def sync(gc, year, top_n=100, folder_id=None, contacts=None):
    """Create or refresh the year's Sheet. Returns (url, inbox block of new "yes" DOIs)."""
    sh = open_or_create(gc, year, folder_id=folder_id)
    tabs, inbox = sheet.build(year, previous=read_tab(sh, "Validate"), top_n=top_n, contacts=contacts,
                              previous_papers=read_tab(sh, "Facility papers"))
    for name, columns in sheet.TABS.items():
        write_tab(sh, name, columns, tabs[name])
    for ws in list(sh.worksheets()):  # the empty first tab of a new Sheet ("Sheet1", "Taulukko1", ...)
        if ws.title not in sheet.TABS and not ws.get_all_values():
            sh.del_worksheet(ws)
    return sh.url, inbox


def validated_dois(gc, years):
    """[{doi, year}] marked "yes" in the Sheets of `years`: extra positives for `embed`
    before they reach the repository."""
    out = []
    for y in years:
        sh = open_or_create(gc, y, create=False)
        if sh is None:
            continue
        for d, (v, _) in sheet._verdicts(read_tab(sh, "Validate")).items():
            if v == "yes":
                out.append({"doi": d, "year": int(y)})
    return out
