"""The validation tables of a year, as CSV files in the working-data folder (<data>/<year>/).

  validate.csv       the papers to check, most likely first, with the reason and evidence:
                     * new: acknowledges the facility (not yet a confirmed paper)
                     * new: facility instrument, no acknowledgement
                     * reads like facility papers (embedding check list, top N not yet flagged)
                     and the staff's verdict (yes / likely / no), reason and note, filled in the
                     notebook (review.py) or by hand.
  contacts.csv       the corresponding authors of the facility's papers of the year (confirmed,
                     or validated yes / likely): one row per e-mail address, with its papers,
                     whether each acknowledges the facility and cites the grant. For an e-mail
                     blast. Rewritten on every refresh (edit a copy).
                     Contacts are looked up only for these papers (data minimisation).
  search_misses.csv  confirmed papers the search did not flag, and why (to improve the rules).

Verdicts already given are always carried over (also for papers that left the list).
E-mail addresses live only in the facility's working-data folder (Drive), never in the repo.
"""
from collections.abc import Callable, Iterable
from pathlib import Path
import csv
import os
import re
from concurrent.futures import ThreadPoolExecutor

from .config import load
from .config import data_root
from .sweep import cached_text, load_screened

VERDICTS = ["yes", "likely", "no"]
REASONS = {     # why staff decided; feeds `validation.feedback` (how to improve rules and ranking)
    "yes": ["acknowledges the facility", "facility instrument or staff named", "staff know the project",
            "authors confirmed", "other"],
    "likely": ["instrument matches, not credited", "imaging matches the facility", "other"],
    "no": ["no imaging", "imaging done elsewhere", "only an affiliation or name match",
           "review or no new data", "other"],
}
VALIDATE_COLUMNS = ["why", "doi", "link", "title", "journal", "acknowledges_facility", "evidence",
                    "priority", "embedding_rank", "verdict", "reason", "note"]
CONTACT_COLUMNS = ["name", "email", "status", "papers", "dois", "titles", "acknowledges_facility",
                   "grant_cited"]
MISSES_COLUMNS = ["doi", "link", "title", "why_missed", "priority", "category", "score_reasons"]
TABLES = {"validate": VALIDATE_COLUMNS, "contacts": CONTACT_COLUMNS, "search_misses": MISSES_COLUMNS}
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
    """{doi: (verdict, reason, note)} from rows of an existing validate table. A verdict other
    than yes / likely / no is an error (never guessed)."""
    out = {}
    for r in rows or []:
        v, why, n = (str(r.get(k) or "").strip() for k in ("verdict", "reason", "note"))
        v = v.lower()
        if v and v not in VERDICTS:
            raise ValueError(f"{r.get('doi')}: verdict {v!r} is not one of {', '.join(VERDICTS)}")
        if r.get("doi") and (v or why or n):
            out[str(r["doi"]).strip().lower()] = (v, why, n)
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


def build(year: int, previous: Iterable[dict] = (), top_n: int = 200,
          contacts: Callable[[list[str]], dict[str, list[dict]]] | None = None,
          confirmed: list[dict] | None = None,
          text: Callable[[str], str | None] | None = None) -> tuple[dict[str, list[dict]], str]:
    """({table: [row dicts]}, the new "yes" DOIs to file, one "doi year" per line) for `year`.

    previous: rows of the existing validate table (verdicts are carried over).
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
    kept = _verdicts(previous)
    text = text or (lambda d: _paper_text(year, d))
    summary = year_summary(year) if rows else {"new_report": [], "new_check": [], "missed": {}}
    flagged = {d for d, r in rows.items() if r.get("priority") in ("report", "check")}
    ranked = _ranked(year)
    by_rank = lambda ds: sorted(ds, key=lambda d: (ranked.get(d, 10**9), d))

    # most likely first: acknowledged, then instrument evidence, then the check list by rank
    cand = [(WHY_ACK, d) for d in by_rank(summary["new_report"]) if d not in all_confirmed]
    cand += [(WHY_INSTRUMENT, d) for d in by_rank(summary["new_check"]) if d not in all_confirmed]
    similar = [d for d in by_rank(ranked) if d not in all_confirmed and d not in flagged]
    cand += [(f"{WHY_SIMILAR} (rank {ranked[d]})", d) for d in similar[:top_n]]
    listed = {d for _, d in cand}
    in_validate = {r.get("doi", "").strip().lower() for r in previous or []}
    for d in sorted((set(kept) & in_validate) - listed - all_confirmed):
        cand.append((WHY_EARLIER, d))

    validated = {d: v for d, (v, _, _) in kept.items() if v in ("yes", "likely") and d not in all_confirmed}
    contacts = contacts or _default_contacts(year)
    who = contacts(list(conf) + list(validated))      # contacts only for facility papers
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
        v, reason, n = kept.get(d, ("", "", ""))
        validate.append({"why": why, "doi": d, "link": f"https://doi.org/{d}", "title": r.get("title", ""),
                         "journal": r.get("journal", ""), "acknowledges_facility": ack(d),
                         "evidence": evidence, "priority": r.get("priority", ""),
                         "embedding_rank": ranked.get(d, ""), "verdict": v, "reason": reason, "note": n})

    facility_papers = []
    for d in sorted(set(conf) | set(validated)):
        p, r = conf.get(d, {}), rows.get(d, {})
        facility_papers.append({"doi": d, "title": p.get("title") or r.get("title", ""),
                                "status": "likely" if validated.get(d) == "likely" else "confirmed",
                                "acknowledges_facility": ack(d), "grant_cited": grant(d),
                                "contacts": who.get(d, [])})

    misses = [{"doi": d, "link": f"https://doi.org/{d}", "title": (conf.get(d) or rows.get(d) or {}).get("title", ""),
               "why_missed": why, "priority": rows.get(d, {}).get("priority", ""),
               "category": rows.get(d, {}).get("category", ""),
               "score_reasons": "; ".join(rows.get(d, {}).get("score_reasons") or [])}
              for d, why in sorted(summary["missed"].items())]

    to_file = "\n".join(f"{d} {year}" for d, v in sorted(validated.items()) if v == "yes")
    return {"validate": validate, "contacts": contact_rows(facility_papers), "search_misses": misses}, to_file


def contact_rows(facility_papers: list[dict]) -> list[dict]:
    """One row per e-mail address (an author of several papers is written to once), with that
    address's papers; a paper without any address found gets a row with an empty e-mail, for
    staff to fill in. status: "confirmed" when one of the papers is, else "likely"."""
    by_email, out = {}, []
    for p in facility_papers:
        found = [c for c in p["contacts"] if c.get("email")]
        if not found:
            out.append({"name": "", "email": "", "status": p["status"], "papers": 1, "dois": p["doi"],
                        "titles": p["title"], "acknowledges_facility": p["acknowledges_facility"],
                        "grant_cited": p["grant_cited"]})
        for c in found:
            e = by_email.setdefault(c["email"].lower(), {"name": "", "email": c["email"], "papers": []})
            e["name"] = e["name"] or c.get("name", "")
            e["papers"].append(p)
    for e in sorted(by_email.values(), key=lambda e: e["email"].lower()):
        ps = e["papers"]
        out.append({"name": e["name"], "email": e["email"],
                    "status": "confirmed" if any(p["status"] == "confirmed" for p in ps) else "likely",
                    "papers": len(ps), **{k: "; ".join(p[f] for p in ps) for k, f in
                                          (("dois", "doi"), ("titles", "title"),
                                           ("acknowledges_facility", "acknowledges_facility"),
                                           ("grant_cited", "grant_cited"))}})
    return sorted(out, key=lambda r: (r["email"] == "", r["status"] != "confirmed", r["email"].lower()))


def table_path(year: int, name: str) -> Path:
    """<data>/<year>/<name>.csv (name: validate, contacts or search_misses)."""
    if name not in TABLES:
        raise ValueError(f"unknown table {name!r}: one of {', '.join(TABLES)}")
    return data_root() / str(year) / f"{name}.csv"


def _write(path: Path, columns: list[str], rows: list[dict]) -> None:
    """Atomic: a reader (or a crash) never sees half a file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".csv.tmp")
    with tmp.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    os.replace(tmp, path)


def write_tables(year: int, tables: dict[str, list[dict]]) -> list[Path]:
    """Write the tables of `year` (build's first value); returns the paths."""
    paths = []
    for name, rows in tables.items():
        _write(table_path(year, name), TABLES[name], rows)
        paths.append(table_path(year, name))
    return paths


def read_validate(year: int) -> list[dict]:
    """Rows of the year's validate.csv ([] before the first `build`)."""
    path = table_path(year, "validate")
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def set_verdict(year: int, doi: str, verdict: str, reason: str = "", note: str = "") -> None:
    """Record one decision in validate.csv (re-read first, so decisions saved meanwhile from
    another session are kept). verdict "" clears it."""
    verdict = verdict.strip().lower()
    if verdict and verdict not in VERDICTS:
        raise ValueError(f"verdict {verdict!r} is not one of {', '.join(VERDICTS)}")
    rows = read_validate(year)
    hit = [r for r in rows if r.get("doi", "").strip().lower() == doi.strip().lower()]
    if not hit:
        raise ValueError(f"{doi} is not in {table_path(year, 'validate')}")
    hit[0].update(verdict=verdict, reason=reason, note=note)
    _write(table_path(year, "validate"), VALIDATE_COLUMNS, rows)


def decisions(years: Iterable[int]) -> list[dict]:
    """Every decision of `years`: [{year, doi, why, embedding_rank, verdict, reason, note}]."""
    out = []
    for y in years:
        for r in read_validate(y):
            v = str(r.get("verdict") or "").strip().lower()
            if v:
                out.append({"year": int(y), "doi": r["doi"].strip().lower(), "why": r.get("why", ""),
                            "embedding_rank": r.get("embedding_rank", ""), "verdict": v,
                            "reason": r.get("reason", ""), "note": r.get("note", "")})
    return out
