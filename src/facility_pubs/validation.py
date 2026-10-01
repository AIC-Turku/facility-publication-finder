"""How well a year's search recovers the confirmed papers, and what it finds besides.

`summarize` is pure; `year_summary` loads a swept year and calls it. The per-year check of
the results by staff happens in the validation workbook (sheet.py), not here.
"""
import json
from typing import Any

from .config import data_root
from .papers import known_dois
from .provenance import wilson
from .sweep import load_screened

FLAGGED = ("report", "check")


def summarize(year: int, confirmed: set[str], rows: dict[str, dict], universe: set[str]) -> dict[str, Any]:
    """Recall against the confirmed papers, why the others were missed, and the new finds.

    rows: screening results by DOI; universe: the year's candidate DOIs."""
    flagged = {d for d, r in rows.items() if r.get("priority") in FLAGGED}
    missed = {}
    for d in sorted(confirmed - flagged):
        r = rows.get(d)
        if d not in universe or r is None:
            missed[d] = "not among the year's candidates (institutional sources, Europe PMC)"
        elif not r.get("has_text"):
            missed[d] = "no full text"
        else:
            missed[d] = f"text found, ranked {r.get('priority') or 'low'} (category {r.get('category')})"
    new = sorted(flagged - confirmed)
    found = len(confirmed & flagged)
    return {
        "year": year, "listed": len(confirmed), "found": found,
        "recall": found / len(confirmed) if confirmed else None,
        "recall_ci": wilson(found, len(confirmed)) if confirmed else None,
        "listed_in_universe": len(confirmed & universe),
        "listed_with_text": sum(1 for d in confirmed if rows.get(d, {}).get("has_text")),
        "found_with_text": sum(1 for d in confirmed & flagged if rows[d].get("has_text")),
        "missed": missed,
        "new_report": [d for d in new if rows[d].get("priority") == "report"],
        "new_check": [d for d in new if rows[d].get("priority") == "check"],
        "screened": len(rows),
    }


def year_summary(year: int) -> dict[str, Any]:
    """summarize() for a swept year (data/<year>/screened.jsonl, universe.json)."""
    rows = {r["doi"]: r for r in load_screened(year)}
    path = data_root() / str(year) / "universe.json"
    universe = set(json.loads(path.read_text())) if path.exists() else set(rows)
    return summarize(year, known_dois(year), rows, universe)


def format_summaries(summaries: list[dict[str, Any]]) -> str:
    lines = [f"{'year':6s}{'listed':>8s}{'found':>7s}{'recall':>8s}{'95% CI':>12s}{'w/ text':>9s}"
             f"{'new ack':>9s}{'new instr':>11s}"]
    tot = {"listed": 0, "found": 0, "wt": 0, "fwt": 0, "nr": 0, "nc": 0}
    for s in summaries:
        lo, hi = s["recall_ci"] or (0, 0)
        lines.append(f"{s['year']:<6d}{s['listed']:>8d}{s['found']:>7d}{s['recall'] or 0:>8.2f}"
                     f"{(f'{lo:.2f}-{hi:.2f}' if s['recall_ci'] else 'n/a'):>12s}"
                     f"{s['found_with_text']:>4d}/{s['listed_with_text']:<4d}"
                     f"{len(s['new_report']):>9d}{len(s['new_check']):>11d}")
        tot["listed"] += s["listed"]
        tot["found"] += s["found"]
        tot["wt"] += s["listed_with_text"]
        tot["fwt"] += s["found_with_text"]
        tot["nr"] += len(s["new_report"])
        tot["nc"] += len(s["new_check"])
    if len(summaries) > 1:
        lo, hi = wilson(tot["found"], tot["listed"])
        lines.append(f"{'all':6s}{tot['listed']:>8d}{tot['found']:>7d}"
                     f"{tot['found'] / max(tot['listed'], 1):>8.2f}{f'{lo:.2f}-{hi:.2f}':>12s}"
                     f"{tot['fwt']:>4d}/{tot['wt']:<4d}{tot['nr']:>9d}{tot['nc']:>11d}")
    for s in summaries:
        if s["missed"]:
            lines.append(f"\n{s['year']} confirmed papers the search did not flag:")
            lines += [f"  {d}: {why}" for d, why in s["missed"].items()]
    return "\n".join(lines)
