"""Turn screened rows into the review spreadsheet and benchmark numbers."""
import csv
import json
import re
import unicodedata
from collections import Counter
from pathlib import Path

from .screen import CATEGORIES, LEADS
from .sweep import DATA, load_screened



def _norm_name(n):
    n = unicodedata.normalize("NFKD", n).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z ]", " ", n).split()


def match_users(row, users):
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
                  "on_facility_list", "doi", "title", "journal", "local_authors", "local_email",
                  "text_source", "instruments_strong", "instruments_weak", "techniques_specialist",
                  "microscopy_terms", "fingerprint", "credited_elsewhere", "other_local_imaging",
                  "acknowledgement", "evidence", "llm_used_facility", "llm_confidence", "llm_reason"]
PRIVATE_COLUMNS = ["private_priority", "private_score", "private_reasons", "known_user_match"]


def _public_values(r, listed, llm):
    v = llm.get(r["doi"], {})
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
            " | ".join(r.get("evidence", []))[:2500],
            v.get("used_facility", ""), v.get("confidence", ""), v.get("reason", "")]


def write_review_csv(year, path=None, listed=(), users=(), llm=None):
    """Write the public review sheet and, when private inputs exist, a private one.

    The public sheet (committed) is computed without any private input: no booking,
    staff or user-list information, so it cannot reveal who uses the facility.
    The private sheet (data/<year>/private/review.csv, git-ignored) adds the
    booking/staff score and a known_user_match flag for facility staff.
    """
    from .sweep import load_private, private_dir
    llm = llm or {}
    all_rows = load_screened(year)
    private = load_private(year)
    rows = [r for r in all_rows if r["category"] in LEADS or r["doi"] in listed]
    rows.sort(key=lambda r: (-r.get("score", 0), r["category"], r["doi"]))
    path = Path(path or DATA / str(year) / "review.csv")
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(PUBLIC_COLUMNS)
        for r in rows:
            w.writerow(_public_values(r, listed, llm))
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
                       + _public_values(r, listed, llm))
    return path


def summary(year, listed=()):
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
        lines.append(f"  facility-list papers not found by the sweep: {len(missing)} {missing}")
        lines += capture_recapture(year, rows, listed)
    return "\n".join(lines)


def capture_recapture(year, rows, listed):
    """Exploratory overlap estimate from the facility list and sweep.

    Uses Chapman's Lincoln-Petersen estimator for context only. The two sources are
    not independent: users who report papers may also be more likely to acknowledge
    the facility, while the sweep explicitly searches acknowledgement evidence.
    Therefore the population estimate and derived coverage percentages are not
    calibrated estimates and must not be described as a lower bound.
    """
    from .config import load
    cfg = load()
    not_paper = cfg.dataset_prefixes + cfg.preprint_prefixes
    papers = [r for r in rows if not r["doi"].startswith(not_paper)]  # datasets/preprints are not papers
    caught = {r["doi"] for r in papers if r.get("priority") in ("report", "check")}
    labels_path = DATA / str(year) / "reference_labels.csv"
    basis = "report/check papers"
    if labels_path.exists():
        labels = load_labels(labels_path)
        caught = {d for d in caught if labels.get(d, {}).get("used_facility") in ("yes", "likely")}
        basis = "report/check papers confirmed in reference_labels.csv"
    acked = {r["doi"] for r in papers if r.get("acknowledgement")}
    out = []
    for label, keep in (("all", None), ("acknowledged", True), ("not acknowledged", False)):
        L = listed if keep is None else {d for d in listed if (d in acked) == keep}
        C = caught if keep is None else {d for d in caught if (d in acked) == keep}
        n1, n2, m = len(L), len(C), len(L & C)
        if not (n1 and n2):
            continue
        total = (n1 + 1) * (n2 + 1) / (m + 1) - 1
        out.append(f"  overlap estimate, {label} ({basis}): list {n1}, sweep {n2}, both {m} "
                   f"-> Chapman {total:.0f}")
    if out:
        out.append("    sources are not independent (users who report papers also acknowledge more, and the "
                   "sweep searches acknowledgements): context only, not a calibrated coverage figure")
    return out


def load_labels(path):
    with open(path, newline="", encoding="utf-8") as f:
        return {r["doi"]: r for r in csv.DictReader(f)}


def save_json(obj, path):
    Path(path).write_text(json.dumps(obj, indent=1, ensure_ascii=False), encoding="utf-8")


def technique_table(year, listed=(), path=None):
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
                    "on_facility_list": sum(r["doi"] in listed for r in hit),
                    "leads": sum(r["category"] in LEADS for r in hit)})
    out.sort(key=lambda x: (x["strength"], -x["papers"]))
    path = Path(path or DATA / str(year) / "techniques.csv")
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0]))
        w.writeheader()
        w.writerows(out)
    return out, path
