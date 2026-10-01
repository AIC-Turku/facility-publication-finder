"""Confirmed facility papers: facilities/<facility>/papers/<year>.yaml.

The public record of the project and the seed set of the embedding check list. One file
per year, one entry per DOI, sorted, with public metadata only (Crossref / Europe PMC):
no full text, abstracts, author names or e-mail addresses.

New papers are pasted into facilities/<facility>/inbox.txt (one DOI per line, optionally
followed by the reporting year; DOI URLs and surrounding text are fine) and filed by
`aic-pubs add-papers`, which a GitHub Action runs on every change to an inbox:
metadata is fetched, each paper goes to its year file, duplicates are merged, files are
sorted, and the inbox is emptied (lines it could not resolve stay, with a note).
"""
from collections.abc import Callable, Iterable
from pathlib import Path
import datetime
import re
from concurrent.futures import ThreadPoolExecutor

import yaml

from .config import facility_dir
from .sources import _norm_doi

FIELDS = ["doi", "title", "journal", "published", "type", "pmid", "pmcid", "europepmc_id",
          "source", "added"]
INBOX_HEADER = """\
# Paste confirmed papers below, one per line: a DOI (or DOI link), optionally followed by
# the reporting year, e.g.
#   10.1038/s41467-024-46868-7 2024
#   https://doi.org/10.1016/j.celrep.2024.114430
# Commit the file. The "add papers" GitHub Action (or `aic-pubs add-papers`) fetches the
# metadata, files each paper under papers/<year>.yaml, merges duplicates, sorts the files
# and empties this inbox. Lines it cannot resolve stay here with a note.
"""
_DOI = re.compile(r"10\.\d{4,9}/[^\s,;<>\"']+", re.I)
_YEAR = re.compile(r"\b(19[89]\d|20\d\d)\b")


def papers_dir(facility: str | None = None) -> Path:
    return facility_dir(facility) / "papers"


def inbox_path(facility: str | None = None) -> Path:
    return facility_dir(facility) / "inbox.txt"


def load_papers(facility: str | None = None) -> list[dict]:
    """Every confirmed paper, as dicts with a `year` key, sorted by year then DOI."""
    out = []
    folder = papers_dir(facility)
    for path in sorted(folder.glob("*.yaml")) if folder.exists() else []:
        if not path.stem.isdigit():
            continue
        for entry in yaml.safe_load(path.read_text(encoding="utf-8")) or []:
            doi = _norm_doi(entry.get("doi")) if isinstance(entry, dict) else ""
            if doi:                               # hand edits: DOIs normalised like pasted ones
                out.append({**entry, "doi": doi, "year": int(path.stem)})
    return out


def known_dois(year: int, facility: str | None = None) -> set[str]:
    """Confirmed DOIs of a year (papers/<year>.yaml)."""
    return {p["doi"] for p in load_papers(facility) if p["year"] == int(year)}


def write_papers(papers: list[dict], facility: str | None = None) -> None:
    """Rewrite the year files from a list of entries (with `year`): one entry per DOI,
    sorted by DOI, empty keys dropped. Years without papers lose their file."""
    folder = papers_dir(facility)
    folder.mkdir(parents=True, exist_ok=True)
    by_year = {}
    for p in papers:
        by_year.setdefault(int(p["year"]), {})[p["doi"]] = p
    name = _facility_name(facility)
    for path in folder.glob("*.yaml"):
        if path.stem.isdigit() and int(path.stem) not in by_year:
            path.unlink()
    for year, entries in by_year.items():
        # known fields first, then any key added by hand (kept, never silently deleted)
        rows = [{k: entries[d][k] for k in FIELDS + sorted(set(entries[d]) - set(FIELDS) - {"year"})
                 if entries[d].get(k) not in (None, "", False)}
                for d in sorted(entries)]
        body = yaml.safe_dump(rows, sort_keys=False, allow_unicode=True, width=200)
        (folder / f"{year}.yaml").write_text(
            f"# {name}: confirmed papers, {year} ({len(rows)}).\n"
            f"# Maintained by `aic-pubs add-papers`: paste new DOIs into ../inbox.txt.\n" + body,
            encoding="utf-8")


def _facility_name(facility=None):
    try:
        cfg = yaml.safe_load((facility_dir(facility) / "facility.yaml").read_text(encoding="utf-8"))
        return cfg["facility"]["name"]
    except (OSError, KeyError, TypeError):
        return facility_dir(facility).name


def parse_inbox(text: str) -> list[tuple[str, str | None, int | None]]:
    """[(line, doi or None, year or None)] for the non-comment lines of an inbox: one entry per
    DOI (a line may hold several), the year only when it directly follows its DOI
    ("10.1000/x 2024"), so a citation year elsewhere on the line is never taken."""
    out = []
    for line in text.splitlines():
        line = line.split("    #")[0]           # an earlier note is replaced, not repeated
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        matches = list(_DOI.finditer(line))
        if not matches:
            out.append((line, None, None))
        for m in matches:
            doi = _norm_doi(m.group(0)) or None
            y = re.match(r"\s+((?:19[89]|20\d)\d)\b", line[m.end():])
            out.append((line, doi, int(y.group(1)) if y else None))
    return out


def metadata(dois: Iterable[str]) -> dict[str, dict]:
    """{doi: public metadata} from Crossref (bibliographic) and Europe PMC (identifiers)."""
    from .known import bibliographic, europepmc_records
    from .sources import crossref_work
    dois = sorted(set(dois))
    with ThreadPoolExecutor(max_workers=8) as pool:
        cross = {d: bibliographic(w) for d, w in zip(dois, pool.map(crossref_work, dois))}
    epmc = europepmc_records(dois) if dois else {}
    out = {}
    for d in dois:
        c = cross.get(d) or {}
        if not c:
            continue
        e = epmc.get(d, {})
        out[d] = {"doi": d, "title": c.get("title", ""), "journal": c.get("journal", ""),
                  "published": c.get("published_online") or c.get("published_print") or "",
                  "issued_year": c.get("issued_year", ""), "type": c.get("type", ""),
                  "pmid": e.get("pmid", ""), "pmcid": e.get("pmcid", ""),
                  "europepmc_id": e.get("europepmc_id", "")}
    return out


def add_papers(lines: str, source: str = "validated", facility: str | None = None,
               fetch: Callable[[set[str]], dict[str, dict]] = metadata, today: str | None = None,
               allow_moves: bool = True) -> tuple[dict, list[str]]:
    """File new confirmed papers. `lines`: inbox text. Returns (summary, leftover lines).

    A DOI already filed is kept where it is, unless a year is given with it (a correction: it
    moves; not with allow_moves=False). A DOI Crossref does not know stays in the inbox with a
    note. Lines without a DOI are dropped (only DOIs and years are ever kept in the inbox,
    which is public)."""
    today = today or datetime.date.today().isoformat()
    papers = {p["doi"]: p for p in load_papers(facility)}
    parsed = parse_inbox(lines)
    todo = {d for _, d, _ in parsed if d and d not in papers}
    meta = fetch(todo) if todo else {}
    added, moved, already, leftover, dropped = [], [], [], [], 0
    for _, doi, year in parsed:
        if not doi:
            dropped += 1
            continue
        keep = f"{doi} {year}" if year else doi
        if doi in papers:
            if year and allow_moves and papers[doi]["year"] != year:
                papers[doi]["year"] = year
                moved.append(doi)
            else:
                already.append(doi)
            continue
        m = meta.get(doi)
        if not m:
            leftover.append(f"{keep}    # not found in Crossref: check the DOI")
            continue
        y = year or (int(m["issued_year"]) if str(m.get("issued_year", "")).isdigit() else None)
        if not y:
            leftover.append(f"{keep}    # no publication year known: add the year after the DOI")
            continue
        papers[doi] = {**{k: v for k, v in m.items() if k != "issued_year"},
                       "year": y, "source": source, "added": today}
        added.append(doi)
    write_papers(list(papers.values()), facility)
    summary = {"added": added, "moved": moved, "already_filed": already, "left_in_inbox": len(leftover),
               "dropped_lines": dropped, "total": len(papers)}
    return summary, leftover


def process_inbox(facility: str | None = None, source: str = "validated",
                  fetch: Callable[[set[str]], dict[str, dict]] = metadata) -> dict:
    """Run add_papers on the facility's inbox and rewrite it (header + unresolved lines)."""
    path = inbox_path(facility)
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    summary, leftover = add_papers(text, source=source, facility=facility, fetch=fetch)
    path.write_text(INBOX_HEADER + "".join(f"{l}\n" for l in leftover), encoding="utf-8")
    return summary
