"""Private facility inputs: OpenIRIS booking export and staff list.

Both live in private/ (git-ignored). They never influence published outputs:
their score contributions go to git-ignored data/<year>/private/ files only.

private/bookings.csv  (one row per booking, or per group+instrument+year)
    group_leader   "Lastname, Firstname" (as in UTUPub author lists)
    instrument     instrument_id from AIC-Turku-database, or its name (optional)
    date           YYYY-MM-DD (or just YYYY)

private/staff.csv
    name           "Lastname, Firstname"
"""
import csv
import os
import re
import unicodedata
from pathlib import Path

# Private inputs: $PUBS_PRIVATE (the notebooks: the temporary Colab disk), else private/ in the checkout.
PRIVATE = Path(os.environ.get("PUBS_PRIVATE") or Path(__file__).resolve().parents[2] / "private")
BOOKINGS = PRIVATE / "bookings.csv"
STAFF = PRIVATE / "staff.csv"
WINDOW_YEARS = 3  # a booking counts for papers published in the same or the next 3 years ...
GRACE_YEARS = 1   # ... and for papers published up to 1 year before it (user still active)


def name_key(name):
    """'Lastname, Firstname' / 'Firstname Lastname' -> ('lastname', 'f')."""
    n = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower().strip()
    if "," in n:
        last, _, first = n.partition(",")
    else:
        parts = n.split()
        last, first = (parts[-1], " ".join(parts[:-1])) if parts else ("", "")
    last = re.sub(r"[^a-z]", "", last)
    first = re.sub(r"[^a-z]", "", first)
    return last, first[:1]


def load_bookings(path=BOOKINGS):
    """{name_key: [(year, instrument), ...]} or {} when there is no export.

    group_leader may be any person linked to a booking (trainee or group head)."""
    out = {}
    if not Path(path).exists():
        return out
    with open(path, newline="", encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            leader = (r.get("group_leader") or "").strip()
            year = re.match(r"\d{4}", (r.get("date") or "").strip())
            if leader and year:
                out.setdefault(name_key(leader), []).append(
                    (int(year.group(0)), (r.get("instrument") or "").strip().lower()))
    return out


def load_staff(path=STAFF):
    if not Path(path).exists():
        return set()
    with open(path, newline="", encoding="utf-8-sig") as f:
        return {name_key(r["name"]) for r in csv.DictReader(f) if r.get("name")}


def booking_match(local_authors, paper_year, instruments_found, bookings):
    """(group_booked, booked_instrument_used) for one paper."""
    if not bookings or not paper_year:
        return False, False
    group, same_instrument = False, False
    found = {i.lower() for i in instruments_found}
    for a in local_authors or []:
        for year, inst in bookings.get(name_key(a), []):
            if -GRACE_YEARS <= int(paper_year) - year <= WINDOW_YEARS:
                group = True
                if inst and any(inst == f or inst in f or f in inst for f in found):
                    same_instrument = True
    return group, same_instrument


def openiris_resources():
    """[(resource-name substring, instrument_id)] from facility.yaml `openiris_resources`."""
    from .config import load
    return [(str(k).lower(), v) for k, v in (load().raw.get("openiris_resources") or {}).items()]


def openiris_resource_id(resource, mapping=None):
    r = (resource or "").strip().lower()
    mapping = openiris_resources() if mapping is None else mapping
    return next((iid for key, iid in mapping if key in r), r)


def import_openiris(xlsx, out_dir=PRIVATE):
    """Convert an OpenIRIS admin export (sheets 'Users', 'Training Requests') into
    private/bookings.csv and private/users.csv. Returns counts; prints no personal data.

    Each completed training gives a row for the trainee and for the head(s) of the
    trainee's group; each user's 'Latest use' gives a row without an instrument.
    """
    import openpyxl
    wb = openpyxl.load_workbook(xlsx, read_only=True)

    def sheet(name):
        rows = list(wb[name].iter_rows(values_only=True))
        return [dict(zip(rows[0], r)) for r in rows[1:]] if rows else []

    users, trainings = sheet("Users"), sheet("Training Requests")
    mapping = openiris_resources()
    split = lambda s: [x.strip() for x in str(s or "").split(",") if x.strip()]
    heads_of_group = {}
    for u in users:
        if u.get("Group"):
            heads_of_group.setdefault(str(u["Group"]), set()).update(split(u.get("Group head(s) (name)")))

    def person(first, last):
        return f"{str(last).strip()}, {str(first).strip()}"

    rows, people = [], set()
    for t in trainings:
        if t.get("Training request status") != "Completed":
            continue
        date = str(t.get("Training request created") or "")[:10]
        inst = openiris_resource_id(t.get("Resource"), mapping)
        who = person(t.get("First name"), t.get("Last name"))
        rows.append((who, inst, date))
        people.add(who)
        for head in heads_of_group.get(str(t.get("Training request group") or ""), ()):
            rows.append((head, inst, date))
            people.add(head)
    for u in users:
        date = str(u.get("Latest use") or "")[:10]
        who = person(u.get("First name"), u.get("Last name"))
        people.add(who)
        rows.append((who, "", date))
        for head in split(u.get("Group head(s) (name)")):
            rows.append((head, "", date))
            people.add(head)

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    with (out_dir / "bookings.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["group_leader", "instrument", "date"])
        w.writerows(sorted(set(rows)))
    with (out_dir / "users.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["name"])
        w.writerows([p] for p in sorted(people))
    return {"trainings": len(trainings), "users": len(users), "groups": len(heads_of_group),
            "booking_rows": len(set(rows)), "people": len(people)}
