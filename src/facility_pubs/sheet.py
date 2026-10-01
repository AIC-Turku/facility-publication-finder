"""The validation workbook of a year: what staff check, and the facility papers with contacts.

Tabs (plain data here; gsheets.py writes them to a Google Sheet, `facility-pubs sheet` to CSV):

  Validate         candidates to check, with the reason and evidence, and a verdict
                   (yes / likely / no) and note to fill in:
                   * new: acknowledges the facility (not yet a confirmed paper)
                   * new: facility instrument, no acknowledgement
                   * reads like facility papers (embedding check list, top N not yet flagged)
  Facility papers  every confirmed paper of the year plus those validated "yes"/"likely",
                   with corresponding author, e-mail (one per row, others in other_contacts),
                   whether the facility is acknowledged and the grant cited: the mail-merge list.
                   Contacts are looked up only for these papers (data minimisation).
  Search misses    confirmed papers the search did not flag, and why (to improve the rules).

Verdicts already given are always carried over (also for papers that left the list).
E-mail addresses live only in the facility's Sheet / working-data folder, never in the repo.
"""
from collections.abc import Callable, Iterable
from pathlib import Path
import csv
import re
from concurrent.futures import ThreadPoolExecutor

from .config import load
from .config import data_root
from .sweep import cached_text, load_screened

VERDICTS = ["yes", "likely", "no"]
VALIDATE_COLUMNS = ["why", "doi", "link", "title", "journal", "acknowledges_facility", "evidence",
                    "priority", "embedding_rank", "verdict", "note"]
PAPERS_COLUMNS = ["doi", "link", "title", "journal", "corresponding_author", "email", "other_contacts",
                  "acknowledges_facility", "grant_cited", "confirmed_by", "verdict", "note"]
MISSES_COLUMNS = ["doi", "link", "title", "why_missed", "priority", "category", "score_reasons"]
TABS = {"Validate": VALIDATE_COLUMNS, "Facility papers": PAPERS_COLUMNS, "Search misses": MISSES_COLUMNS}
WHY_ACK = "new: acknowledges the facility"
WHY_INSTRUMENT = "new: facility instrument, no acknowledgement"
WHY_SIMILAR = "reads like facility papers"
WHY_EARLIER = "earlier verdict (no longer a candidate)"


def _ranked(year):
    """{doi: rank} from data/<year>/embedding_ranked.csv (written by `facility-pubs embed`)."""
    path = data_root() / str(year) / "embedding_ranked.csv"
    if not path.exists():
        return {}
    with path.open(newline="", encoding="utf-8") as f:
        return {r["doi"]: int(r["rank"]) for r in csv.DictReader(f) if r.get("rank", "").isdigit()}


def _verdicts(rows):
    """{doi: (verdict, note)} from rows of an existing Validate tab."""
    out = {}
    for r in rows or []:
        v, n = str(r.get("verdict") or "").strip().lower(), str(r.get("note") or "").strip()
        if r.get("doi") and (v or n):
            out[str(r["doi"]).strip().lower()] = (v, n)
    return out


def _paper_text(year, doi):
    """Full text from the year's sweep cache, else the confirmed-paper cache (which may fetch it
    once from Europe PMC / Crossref and keep it)."""
    from .embeddings import _known_text
    return cached_text(year, doi)[0] or _known_text({"doi": doi, "year": year})


def _default_contacts(year, workers=8):
    """contacts(dois) -> {doi: [{"name", "email"}]} from the full text and the Crossref
    author list (network: one Crossref request per paper)."""
    from .contacts import author_names, corresponding_contacts
    from .sources import crossref_work
    rows = {r["doi"]: r for r in load_screened(year)} if (data_root() / str(year) / "screened.jsonl").exists() else {}

    def one(doi):
        text = _paper_text(year, doi)
        if not text:
            return doi, []
        authors = author_names(crossref_work(doi)) + list(rows.get(doi, {}).get("local_authors") or [])
        return doi, corresponding_contacts(text, authors)

    def contacts(dois):
        with ThreadPoolExecutor(max_workers=workers) as pool:
            return dict(pool.map(one, sorted(set(dois))))
    return contacts


def build(year: int, previous: Iterable[dict] = (), top_n: int = 100,
          contacts: Callable[[list[str]], dict[str, list[dict]]] | None = None,
          confirmed: list[dict] | None = None, previous_papers: Iterable[dict] = (),
          text: Callable[[str], str | None] | None = None) -> tuple[dict[str, list[dict]], str]:
    """{tab: [row dicts]} and the inbox block for `year`.

    previous: rows of the existing Validate tab (verdicts are carried over).
    previous_papers: rows of the existing Facility papers tab (its notes are carried over;
    the Validate tab wins where both have a verdict).
    text: function(doi) -> full text or None (default: _paper_text(year, doi)).
    contacts: function(dois) -> {doi: [{"name", "email"}]} (default: _default_contacts(year)).
    confirmed: [{doi, year, source, title, journal}] (default: the facility's papers)."""
    from .papers import load_papers
    from .validation import year_summary
    cfg = load()
    rows = {r["doi"]: r for r in load_screened(year)}
    if confirmed is None:
        confirmed = load_papers()
    conf = {p["doi"]: p for p in confirmed if int(p["year"]) == int(year)}
    all_confirmed = {p["doi"] for p in confirmed}
    kept = {**_verdicts(previous_papers), **_verdicts(previous)}
    text = text or (lambda d: _paper_text(year, d))
    summary = year_summary(year) if rows else {"new_report": [], "new_check": [], "missed": {}}
    flagged = {d for d, r in rows.items() if r.get("priority") in ("report", "check")}
    ranked = _ranked(year)

    cand = []
    for d in summary["new_report"]:
        if d not in all_confirmed:
            cand.append((WHY_ACK, d))
    for d in summary["new_check"]:
        if d not in all_confirmed:
            cand.append((WHY_INSTRUMENT, d))
    similar = [d for d in sorted(ranked, key=ranked.get) if d not in all_confirmed and d not in flagged]
    for d in similar[:top_n]:
        cand.append((f"{WHY_SIMILAR} (rank {ranked[d]})", d))
    listed = {d for _, d in cand}
    in_validate = {r.get("doi", "").strip().lower() for r in previous or []}
    for d in sorted((set(kept) & in_validate) - listed - all_confirmed):
        cand.append((WHY_EARLIER, d))

    validated = [d for d, (v, _) in kept.items() if v in ("yes", "likely") and d not in all_confirmed]
    contacts = contacts or _default_contacts(year)
    who = contacts(list(conf) + validated)          # contacts only for facility papers
    grants = [g for g in cfg.raw.get("europepmc_grant_numbers") or []]
    grant_rx = re.compile(r"\b(" + "|".join(map(re.escape, grants)) + r")\b") if grants else None

    from .text import normalise

    def ack(d):
        r = rows.get(d)
        if r and r.get("has_text"):
            return "yes" if r.get("acknowledgement") else "no"
        t = text(d)                                   # a confirmed paper outside the sweep
        if not t:
            return "unknown (no full text)"
        t = normalise(t)
        return "yes" if any(p.search(t) for p in cfg.acknowledgement) else "no"

    def grant(d):
        if not grant_rx:
            return ""
        t = text(d)
        if not t:
            return "unknown"
        return "yes" if grant_rx.search(t) else "no"

    validate = []
    for why, d in cand:
        r = rows.get(d, {})
        evidence = " | ".join(list(r.get("score_reasons") or []) + list(r.get("acknowledgement") or [])
                              + list(r.get("evidence") or []))[:1500]
        v, n = kept.get(d, ("", ""))
        validate.append({"why": why, "doi": d, "link": f"https://doi.org/{d}", "title": r.get("title", ""),
                         "journal": r.get("journal", ""), "acknowledges_facility": ack(d),
                         "evidence": evidence, "priority": r.get("priority", ""),
                         "embedding_rank": ranked.get(d, ""), "verdict": v, "note": n})

    papers = []
    for d in sorted(set(conf) | set(validated)):
        p, r = conf.get(d, {}), rows.get(d, {})
        v, n = kept.get(d, ("", ""))
        c = who.get(d, [])
        papers.append({"doi": d, "link": f"https://doi.org/{d}", "title": p.get("title") or r.get("title", ""),
                       "journal": p.get("journal") or r.get("journal", ""),
                       "corresponding_author": c[0]["name"] if c else "", "email": c[0]["email"] if c else "",
                       "other_contacts": "; ".join(f"{x['name']} <{x['email']}>".strip() for x in c[1:]),
                       "acknowledges_facility": ack(d), "grant_cited": grant(d),
                       "confirmed_by": p.get("source") or f"this sheet ({v})", "verdict": v, "note": n})

    misses = [{"doi": d, "link": f"https://doi.org/{d}", "title": (conf.get(d) or rows.get(d) or {}).get("title", ""),
               "why_missed": why, "priority": rows.get(d, {}).get("priority", ""),
               "category": rows.get(d, {}).get("category", ""),
               "score_reasons": "; ".join(rows.get(d, {}).get("score_reasons") or [])}
              for d, why in sorted(summary["missed"].items())]

    inbox = "\n".join(f"{d} {year}" for d, (v, _) in sorted(kept.items()) if v == "yes" and d not in all_confirmed)
    return {"Validate": validate, "Facility papers": papers, "Search misses": misses}, inbox


def write_csv(year: int, tabs: dict[str, list[dict]], folder: Path | None = None) -> list[Path]:
    """The tabs as CSV files in the working-data folder (data/<year>/sheet_*.csv)."""
    folder = folder or data_root() / str(year)
    folder.mkdir(parents=True, exist_ok=True)
    paths = []
    for name, rows in tabs.items():
        path = folder / f"sheet_{name.lower().replace(' ', '_')}.csv"
        with path.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=TABS[name])
            w.writeheader()
            w.writerows(rows)
        paths.append(path)
    return paths


def read_csv_validate(year: int, folder: Path | None = None) -> list[dict]:
    path = (folder or data_root() / str(year)) / "sheet_validate.csv"
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))
