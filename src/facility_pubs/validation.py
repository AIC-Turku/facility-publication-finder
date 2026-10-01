"""How well a year's search recovers the confirmed papers, and what it finds besides.

`summarize` is pure; `year_summary` loads a swept year and calls it. The per-year check of
the results by staff happens in the notebook (review.py, saved by sheet.py); `feedback`
summarises those decisions for improving the rules and the ranking.
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


_GROUPS = (("acknowledges", "new: acknowledges"), ("instrument", "new: facility instrument"),
           ("check list", "reads like"), ("earlier", "earlier verdict"))
_BANDS = ((1, 50), (51, 100), (101, 200), (201, 10**9))


def _group(why: str) -> str:
    return next((g for g, prefix in _GROUPS if why.startswith(prefix)), "other")


def feedback(decisions: list[dict]) -> dict:
    """What the staff's decisions say about the search (pure; decisions: sheet.decisions).

    groups: per reason a paper was listed, how many were judged yes / likely / no (the rules'
    precision); bands: yes / reviewed of the check list by embedding rank (where to set TOP_N);
    no_reasons: why papers were not facility use, per group (which rule to fix first);
    rules_missed: check-list papers judged yes (the rules did not flag them: new patterns?)."""
    groups, bands, no_reasons, missed = {}, {}, {}, []
    for d in decisions:
        g = _group(d.get("why", ""))
        c = groups.setdefault(g, {"yes": 0, "likely": 0, "no": 0})
        c[d["verdict"]] = c.get(d["verdict"], 0) + 1
        if d["verdict"] == "no":
            key = d.get("reason") or "(no reason given)"
            no_reasons.setdefault(g, {}).setdefault(key, 0)
            no_reasons[g][key] += 1
        if g == "check list" and str(d.get("embedding_rank", "")).isdigit():
            rank = int(d["embedding_rank"])
            band = next(f"{lo}-{hi}" if hi < 10**9 else f"{lo}+" for lo, hi in _BANDS if lo <= rank <= hi)
            b = bands.setdefault(band, {"reviewed": 0, "yes": 0})
            b["reviewed"] += 1
            b["yes"] += d["verdict"] == "yes"
            if d["verdict"] == "yes":
                missed.append({"year": d["year"], "doi": d["doi"], "rank": rank, "reason": d.get("reason", "")})
    return {"decisions": len(decisions), "groups": groups, "bands": bands, "no_reasons": no_reasons,
            "rules_missed": sorted(missed, key=lambda m: (m["year"], m["rank"]))}


def format_feedback(f: dict) -> str:
    lines = [f"{f['decisions']} decisions"]
    for g, c in f["groups"].items():
        n = sum(c.values())
        lines.append(f"  {g:<13} {n:>4} reviewed: {c['yes']} yes, {c['likely']} likely, {c['no']} no"
                     f"  (yes {c['yes'] / n:.0%})")
    if f["bands"]:
        lines.append("check list, yes by embedding rank (where to set TOP_N):")
        for band, b in sorted(f["bands"].items(), key=lambda kv: int(kv[0].split("-")[0].rstrip("+"))):
            lines.append(f"  rank {band:<8} {b['yes']:>3} yes of {b['reviewed']:>3} reviewed")
    for g, reasons in f["no_reasons"].items():
        lines.append(f"why not facility use ({g}): " + ", ".join(f"{k} {v}" for k, v in
                                                               sorted(reasons.items(), key=lambda kv: -kv[1])))
    if f["rules_missed"]:
        lines.append(f"{len(f['rules_missed'])} facility papers found only by the check list (rules to add?):")
        lines += [f"  {m['year']} rank {m['rank']:>4}  {m['doi']}  {m['reason']}" for m in f["rules_missed"]]
    return "\n".join(lines)
