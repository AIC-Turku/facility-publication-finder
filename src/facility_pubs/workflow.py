"""The steps of notebook 2, as functions the notebook calls (no logic lives in notebooks).

Everything a step writes is in the working-data folder (<data>/<year>/: validate.csv,
contacts.csv, search_misses.csv; <data>/feedback.txt), i.e. the facility's Google Drive.
"""
from collections.abc import Callable
from pathlib import Path
import urllib.parse

from . import embeddings, sheet
from .config import data_root


def swept_years() -> list[int]:
    """Years with screening results in the working-data folder."""
    return sorted(int(p.parent.name) for p in data_root().glob("*/screened.jsonl") if p.parent.name.isdigit())


def _rank(years: list[int], progress: Callable[[str], None]) -> list[dict]:
    """Embedding check lists for `years`, learning also from the decisions not yet filed:
    "yes" as positives, "no" as negatives."""
    done = sheet.decisions(swept_years())
    extra = [{"doi": d["doi"], "year": d["year"]} for d in done if d["verdict"] == "yes"]
    rejected = {d["doi"] for d in done if d["verdict"] == "no"}
    return embeddings.run(sorted(set(years) | set(swept_years())), extra_known=extra, rejected=rejected,
                          progress=progress)


def _refresh(year: int, top_n: int) -> tuple[list[Path], str]:
    tables, to_file = sheet.build(year, previous=sheet.read_validate(year), top_n=top_n)
    return sheet.write_tables(year, tables), to_file


def prepare(year: int, top_n: int = 200, progress: Callable[[str], None] = print) -> list[Path]:
    """Rank the year and write its tables (decisions already made are kept)."""
    if year not in swept_years():
        raise SystemExit(f"{year} is not built yet: run notebook 1 (facility-pubs sweep --year {year}) first")
    for s in _rank([year], progress):
        if s["year"] == year:
            progress(embeddings.format_summary(s))
    return _refresh(year, top_n)[0]


def collect(year: int, top_n: int = 200) -> tuple[Path, str]:
    """After reviewing: refresh the tables. Returns (contacts.csv, the new "yes" DOIs to file)."""
    _, to_file = _refresh(year, top_n)
    return sheet.table_path(year, "contacts"), to_file


def issue_link(repo: str, facility: str, dois: str) -> str:
    """A link that opens a new "Add papers" issue (.github/ISSUE_TEMPLATE/add-papers.yml) with
    the facility and the DOIs filled in."""
    query = urllib.parse.urlencode({"template": "add-papers.yml", "facility": facility, "dois": dois})
    return f"{repo.removesuffix('.git').rstrip('/')}/issues/new?{query}"


def learn(year: int, top_n: int = 200, progress: Callable[[str], None] = lambda _: None) -> list[int]:
    """Re-rank every swept year with the new decisions and refresh the other years' tables.
    Returns the years refreshed."""
    _rank([], progress)
    again = [y for y in swept_years() if y != year and sheet.table_path(y, "validate").exists()]
    for y in again:
        _refresh(y, top_n)
    return again


def feedback(years: list[int] | None = None) -> tuple[str, Path]:
    """What the decisions of `years` (default: every swept year) say about the rules and the
    ranking; also written to <data>/feedback.txt. Returns (report, path)."""
    from .validation import feedback as summarise, format_feedback
    text = format_feedback(summarise(sheet.decisions(years or swept_years())))
    path = data_root() / "feedback.txt"
    path.write_text(text + "\n", encoding="utf-8")
    return text, path
