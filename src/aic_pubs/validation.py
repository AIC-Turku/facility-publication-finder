"""Discovery check against the facility's own website lists.

This is a discovery aid, not an evaluation: for each year, which known (listed) AIC
papers the sweep recovers, why the others are missed, and which additional papers it
finds. The per-year validation sheet
(data/<year>/validation.csv) lists the new finds and the missed listed papers for a
person to check; their verdicts feed back into better rules and labels.
"""
import csv
import json

from .provenance import wilson
from .sweep import DATA, load_screened

SHEET_COLUMNS = ["kind", "doi", "link", "title", "journal", "priority", "score", "score_reasons",
                 "acknowledgement", "evidence", "rules_version", "your_verdict", "your_note"]


def _listed(year):
    from .papers import known_dois
    return known_dois(year, data=DATA)


def year_summary(year, write_sheet=True):
    listed = _listed(year)
    rows = {r["doi"]: r for r in load_screened(year)}
    universe_path = DATA / str(year) / "universe.json"
    universe = set(json.loads(universe_path.read_text())) if universe_path.exists() else set(rows)
    flagged = {d for d, r in rows.items() if r.get("priority") in ("report", "check")}

    missed = {}
    for d in sorted(listed - flagged):
        r = rows.get(d)
        if d not in universe or r is None:
            missed[d] = "not in UTUPub/ÅA/Europe PMC for this year"
        elif not r.get("has_text"):
            missed[d] = "no full text"
        else:
            missed[d] = f"text found, ranked {r.get('priority') or 'low'} (category {r.get('category')})"
    new = sorted(flagged - listed)
    new_report = [d for d in new if rows[d].get("priority") == "report"]
    new_check = [d for d in new if rows[d].get("priority") == "check"]

    if write_sheet:
        from .provenance import previous_verdicts, rules_version
        version = rules_version()
        path = DATA / str(year) / "validation.csv"
        kept = previous_verdicts(path)
        with path.open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(SHEET_COLUMNS)
            for kind, dois in (("new: acknowledges AIC", new_report),
                               ("new: AIC instrument, no acknowledgement", new_check),
                               ("missed listed paper", sorted(missed))):
                for d in dois:
                    r = rows.get(d, {})
                    reasons = "; ".join(r.get("score_reasons") or [])
                    if kind == "missed listed paper":
                        reasons = missed[d] + (f" | {reasons}" if reasons else "")
                    w.writerow([kind, d, f"https://doi.org/{d}", r.get("title", ""), r.get("journal", ""),
                                r.get("priority", ""), r.get("score", ""), reasons,
                                " | ".join(r.get("acknowledgement") or [])[:600],
                                " | ".join(r.get("evidence") or [])[:1200], version, *kept.get(d, ("", ""))])
            # verdicts on papers that left the sheet (e.g. no longer flagged) are kept, not lost
            written = set(new_report) | set(new_check) | set(missed)
            for d in sorted(set(kept) - written):
                r = rows.get(d, {})
                w.writerow(["earlier verdict (no longer on this sheet)", d, f"https://doi.org/{d}",
                            r.get("title", ""), r.get("journal", ""), r.get("priority", ""), r.get("score", ""),
                            "", "", "", version, *kept[d]])

    found = len(listed & flagged)
    return {
        "year": year, "listed": len(listed), "found": found,
        "recall": found / len(listed) if listed else None,
        "recall_ci": wilson(found, len(listed)) if listed else None,
        "listed_in_universe": len(listed & universe),
        "listed_with_text": sum(1 for d in listed if rows.get(d, {}).get("has_text")),
        "found_with_text": sum(1 for d in listed & flagged if rows[d].get("has_text")),
        "missed": missed, "new_report": new_report, "new_check": new_check,
        "screened": len(rows),
    }


def format_summaries(summaries):
    lines = [f"{'year':6s}{'listed':>8s}{'found':>7s}{'recall':>8s}{'95% CI':>12s}{'w/ text':>9s}"
             f"{'new ack':>9s}{'new instr':>11s}"]
    tot = {"listed": 0, "found": 0, "wt": 0, "fwt": 0, "nr": 0, "nc": 0}
    for s in summaries:
        lo, hi = s["recall_ci"] or (0, 0)
        lines.append(f"{s['year']:<6d}{s['listed']:>8d}{s['found']:>7d}{s['recall'] or 0:>8.2f}"
                     f"{(f'{lo:.2f}-{hi:.2f}' if s['recall_ci'] else 'n/a'):>12s}"
                     f"{s['found_with_text']:>4d}/{s['listed_with_text']:<4d}"
                     f"{len(s['new_report']):>9d}{len(s['new_check']):>11d}")
        tot["listed"] += s["listed"]; tot["found"] += s["found"]
        tot["wt"] += s["listed_with_text"]; tot["fwt"] += s["found_with_text"]
        tot["nr"] += len(s["new_report"]); tot["nc"] += len(s["new_check"])
    if len(summaries) > 1:
        lo, hi = wilson(tot["found"], tot["listed"])
        lines.append(f"{'all':6s}{tot['listed']:>8d}{tot['found']:>7d}"
                     f"{tot['found'] / max(tot['listed'], 1):>8.2f}{f'{lo:.2f}-{hi:.2f}':>12s}"
                     f"{tot['fwt']:>4d}/{tot['wt']:<4d}{tot['nr']:>9d}{tot['nc']:>11d}")
    for s in summaries:
        if s["missed"]:
            lines.append(f"\n{s['year']} missed listed papers:")
            lines += [f"  {d}: {why}" for d, why in s["missed"].items()]
    return "\n".join(lines)
