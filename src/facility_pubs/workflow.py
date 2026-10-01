"""The steps of notebook 2, as functions the notebook calls (no logic lives in notebooks).

`gc` is an authorised gspread client (Colab: `gspread.authorize(google.auth.default()[0])`).
"""
import os
from collections.abc import Callable
from pathlib import Path

from . import embeddings, gsheets
from .config import data_root


def swept_years() -> list[int]:
    """Years with screening results in the working-data folder."""
    return sorted(int(p.parent.name) for p in data_root().glob("*/screened.jsonl") if p.parent.name.isdigit())


def drive_folder_id(path: Path) -> str | None:
    """The Google Drive id of a folder mounted in Colab (None outside Drive)."""
    try:
        return os.getxattr(str(path), "user.drive.id").decode()
    except (OSError, AttributeError):
        return None


def _rank(gc, years: list[int], progress: Callable[[str], None]) -> list[dict]:
    """Embedding check lists for `years`, learning also from Sheet verdicts not yet filed."""
    extra = gsheets.validated_dois(gc, swept_years())
    return embeddings.run(sorted(set(years) | set(swept_years())), extra_known=extra, progress=progress)


def prepare_sheet(gc, year: int, top_n: int = 100, folder_id: str | None = None,
                  progress: Callable[[str], None] = print) -> str:
    """Rank the year and create or refresh its validation Sheet. Returns the Sheet's URL."""
    if year not in swept_years():
        raise SystemExit(f"{year} is not built yet: run notebook 1 (facility-pubs sweep --year {year}) first")
    for s in _rank(gc, [year], progress):
        if s["year"] == year:
            progress(embeddings.format_summary(s))
    url, _ = gsheets.sync(gc, year, top_n=top_n, folder_id=folder_id or drive_folder_id(data_root()))
    return url


def collect(gc, year: int, top_n: int = 100) -> tuple[str, str]:
    """After validating: refresh the Sheet; returns (URL, the new "yes" DOIs for the inbox)."""
    return gsheets.sync(gc, year, top_n=top_n)


def learn(gc, year: int, top_n: int = 100, progress: Callable[[str], None] = lambda _: None) -> dict[int, str]:
    """Re-rank every swept year with the new verdicts and refresh the other years' Sheets."""
    _rank(gc, [], progress)
    return {y: gsheets.sync(gc, y, top_n=top_n)[0] for y in swept_years()
            if y != year and gsheets.has_sheet(y)}
