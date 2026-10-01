"""Turn screened rows into the review spreadsheet and benchmark numbers."""
import csv
import re
import unicodedata
from collections import Counter
from pathlib import Path

from .screen import CATEGORIES, LEADS
from .config import data_root
from .sweep import load_screened


def _norm_name(n):
    n = unicodedata.normalize("NFKD", n).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z ]", " ", n).split()


def match_users(row: dict, users: list[str]) -> list[str]:
    """Names from an optional user list that appear among UTU-affiliated authors.

    users: list of "Lastname, Firstname" or "Firstname Lastname" strings.
    Matching is on surname + first initial, so it is a hint, not proof.
    """
    authors = []
    for a in row.get("local_authors") or []:
        last, _, first = a.partition(",")
        authors.append((_norm_name(last), _norm_name(first)))
    hits = []
    for u in users:
        if "," in u:
            last, _, first = u.partition(",")
        else:
            parts = u.split()
            first, last = " ".join(parts[:-1]), parts[-1] if parts else ""
        L, F = _norm_name(last), _norm_name(first)
        if any(L and al == L and F and af and af[0][:1] == F[0][:1] for al, af in authors):
            hits.append(u)
    return hits


PUBLIC_COLUMNS = ["priority", "score", "score_reasons", "category", "category_meaning",
                  "confirmed", "doi", "title", "journal", "local_authors", "local_email",
                  "text_source", "instruments_strong", "instruments_weak", "techniques_specialist",
                  "microscopy_terms", "fingerprint", "credited_elsewhere", "other_local_imaging",
                  "acknowledgement", "evidence"]
PRIVATE_COLUMNS = ["private_priority", "private_score", "private_reasons", "known_user_match"]


def _public_values(r: dict, listed: set[str]) -> list:
    fp = r.get("fingerprints") or {}
    return [r.get("priority", ""), r.get("score", ""), "; ".join(r.get("score_reasons") or []),
            r["category"], CATEGORIES[r["category"]], r["doi"] in listed, r["doi"],
            r.get("title", ""), r.get("journal", ""), "; ".join(r.get("local_authors") or []),
            r.get("local_email", ""), r.get("text_source", ""),
            "; ".join(r.get("instruments_strong", [])), "; ".join(r.get("instruments_weak", [])),
            "; ".join(r.get("techniques_specialist", [])), r.get("microscopy_terms", ""),
            "; ".join(f"{k}: {', '.join(v)}" for k, v in fp.items())[:400],
            " | ".join(r.get("credited_elsewhere") or [])[:400], r.get("other_local_imaging", ""),
            " | ".join(r.get("acknowledgement") or r.get("affiliation_only") or [])[:800],
            " | ".join(r.get("evidence", []))[:2500]]


def write_review_csv(year: int, listed: set[str], users: list[str] = (), path: Path | None = None) -> Path:
    """Write the public review sheet and, when private inputs exist, a private one.

    The public sheet (committed) is computed without any private input: no booking,
    staff or user-list information, so it cannot reveal who uses the facility.
    The private sheet (next to the private inputs, see sweep.private_dir) adds the
    booking/staff score and a known_user_match flag for facility staff.
    """
    from .sweep import load_private, private_dir
    all_rows = load_screened(year)
    private = load_private(year)
    rows = [r for r in all_rows if r["category"] in LEADS or r["doi"] in listed]
    rows.sort(key=lambda r: (-r.get("score", 0), r["category"], r["doi"]))
    path = Path(path or data_root() / str(year) / "review.csv")
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(PUBLIC_COLUMNS)
        for r in rows:
            w.writerow(_public_values(r, listed))
    if not (users or any(p.get("reasons") for p in private.values())):
        return path
    prows = [r for r in all_rows if r["category"] in LEADS or r["doi"] in listed
             or private.get(r["doi"], {}).get("priority") in ("report", "check")]
    pscore = lambda r: private.get(r["doi"], {}).get("score", r.get("score", 0))
    prows.sort(key=lambda r: (-pscore(r), r["category"], r["doi"]))
    ppath = private_dir(year) / "review.csv"
    with ppath.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(PRIVATE_COLUMNS + PUBLIC_COLUMNS)
        for r in prows:
            p = private.get(r["doi"], {})
            w.writerow([p.get("priority", r.get("priority", "")), pscore(r),
                        "; ".join(p.get("reasons") or []), bool(match_users(r, users))]
                       + _public_values(r, listed))
    return path


def summary(year: int, listed: set[str]) -> str:
    rows = load_screened(year)
    listed = set(listed)
    by = {r["doi"]: r for r in rows}
    c = Counter(r["category"] for r in rows)
    lines = [f"{year}: {len(rows)} papers screened, full text for {sum(r['has_text'] for r in rows)}"]
    for k in CATEGORIES:
        if c[k]:
            on = sum(1 for r in rows if r["category"] == k and r["doi"] in listed)
            lines.append(f"  {k} {CATEGORIES[k]:60s} {c[k]:5d}" + (f"   on list: {on}" if listed else ""))
    if listed:
        missing = sorted(listed - set(by))
        lines.append(f"  confirmed papers not among the candidates: {len(missing)} {missing}")
    return "\n".join(lines)


def technique_table(year: int, listed: set[str], path: Path | None = None) -> tuple[list[dict], Path]:
    """Per technique: papers mentioning it, and how many of those credit the facility."""
    rows = [r for r in load_screened(year) if r.get("has_text")]
    listed = set(listed)
    from .config import load
    cfg = load()
    out = []
    for t in cfg.techniques:
        hit = [r for r in rows if t.id in (r.get("techniques") or {})]
        out.append({"technique": t.id, "vocab": t.vocab, "strength": t.strength,
                    "papers": len(hit),
                    "acknowledging_facility": sum(r["category"] == "A" for r in hit),
                    "confirmed": sum(r["doi"] in listed for r in hit),
                    "leads": sum(r["category"] in LEADS for r in hit)})
    out.sort(key=lambda x: (x["strength"], -x["papers"]))
    path = Path(path or data_root() / str(year) / "techniques.csv")
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0]))
        w.writeheader()
        w.writerows(out)
    return out, path
