"""Confirmed facility papers: facilities/<facility>/papers/<year>.yaml.

The public record of the project and the seed set of the embedding check list. One file
per year, one entry per DOI, sorted, with public metadata only (Crossref / Europe PMC):
no full text, abstracts, author names or e-mail addresses.

New papers come from an "Add papers" issue: an agent files them with `facility-pubs
add-papers <file>` and opens a pull request. DOIs (DOI URLs and surrounding text are fine,
optionally followed by the reporting year) get their metadata, each paper goes to its year
file, duplicates are merged and files are sorted. `check_papers` is the pull-request check:
well-formed files, nothing but public metadata, every new DOI resolves.
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
_DOI = re.compile(r"10\.\d{4,9}/[^\s,;<>\"']+", re.I)
_YEAR = re.compile(r"\b(19[89]\d|20\d\d)\b")


def papers_dir(facility: str | None = None) -> Path:
    return facility_dir(facility) / "papers"


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
            f"# Maintained by `facility-pubs add-papers` (an Add papers issue); do not edit by hand.\n" + body,
            encoding="utf-8")


def _facility_name(facility=None):
    try:
        cfg = yaml.safe_load((facility_dir(facility) / "facility.yaml").read_text(encoding="utf-8"))
        return cfg["facility"]["name"]
    except (OSError, KeyError, TypeError):
        return facility_dir(facility).name


def parse_dois(text: str) -> list[tuple[str, str | None, int | None]]:
    """[(line, doi or None, year or None)] for the non-comment lines of a pasted text: one entry per
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


def add_papers(lines: str, source: str = "staff-reviewed", facility: str | None = None,
               fetch: Callable[[set[str]], dict[str, dict]] | None = None, today: str | None = None,
               allow_moves: bool = True) -> tuple[dict, list[str]]:
    """File new confirmed papers. `lines`: pasted text. Returns (summary, lines not filed).

    A DOI already filed is kept where it is, unless a year is given with it (a correction: it
    moves; not with allow_moves=False). A DOI Crossref does not know is not filed: it comes
    back with a note. Lines without a DOI are dropped (only DOIs and years are ever repeated,
    as issues are public)."""
    today = today or datetime.date.today().isoformat()
    fetch = fetch or metadata
    papers = {p["doi"]: p for p in load_papers(facility)}
    parsed = parse_dois(lines)
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
    summary = {"added": added, "moved": moved, "already_filed": already, "not_filed": len(leftover),
               "dropped_lines": dropped, "total": len(papers)}
    return summary, leftover


_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")


def check_papers(base: set[str], facility: str | None = None,
                 resolves: Callable[[str], bool] | None = None) -> tuple[list[dict], list[str]]:
    """The pull-request check of papers/<year>.yaml: (new papers, problems).

    `base`: the DOIs filed before the change. Every file must be a sorted list of entries with
    normalised, unique DOIs and only the public fields (FIELDS: nothing about how a paper
    acknowledged the facility, no notes, no e-mail addresses); every DOI not in `base` must
    resolve (`resolves`, default: Crossref knows it) and say how it was confirmed (`source`)."""
    if resolves is None:
        from .sources import crossref_work

        def resolves(doi: str) -> bool:
            return bool(crossref_work(doi))
    folder = papers_dir(facility)
    problems, seen, new = [], {}, []
    for path in sorted(folder.glob("*.yaml")) if folder.exists() else []:
        if not path.stem.isdigit():
            problems.append(f"{path.name}: year files are named <year>.yaml")
            continue
        try:
            entries = yaml.safe_load(path.read_text(encoding="utf-8")) or []
        except yaml.YAMLError as e:
            problems.append(f"{path.name}: not valid YAML ({e.__class__.__name__})")
            continue
        if not isinstance(entries, list) or not all(isinstance(e, dict) for e in entries):
            problems.append(f"{path.name}: must be a list of entries (- doi: ...)")
            continue
        dois = [str(e.get("doi") or "") for e in entries]
        if dois != sorted(dois):
            problems.append(f"{path.name}: entries are not sorted by DOI")
        for e, doi in zip(entries, dois):
            if not doi or _norm_doi(doi) != doi:
                problems.append(f"{path.name}: {doi or 'an entry'} is not a normalised DOI (lower case, no link)")
                continue
            if doi in seen:
                problems.append(f"{doi}: filed twice ({seen[doi]} and {path.stem})")
            seen[doi] = path.stem
            extra = sorted(set(e) - set(FIELDS))
            if extra:
                problems.append(f"{doi}: only public metadata may be filed, not {', '.join(extra)}")
            if any(_EMAIL.search(str(v)) for v in e.values()):
                problems.append(f"{doi}: looks like it holds an e-mail address")
            if doi not in base:
                new.append({**e, "year": int(path.stem)})
    for e in new:
        if not e.get("source"):
            problems.append(f"{e['doi']}: new paper without a source (how it was confirmed)")
        if not resolves(e["doi"]):
            problems.append(f"{e['doi']}: does not resolve in Crossref")
    return new, problems
