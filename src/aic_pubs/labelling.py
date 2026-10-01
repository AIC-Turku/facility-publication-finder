"""Label sheets for facility staff and the recall estimate they make possible.

Two sheets per year (the label protocol is in the facility's private notes):

labels_to_review.csv  every labelled paper with the draft verdict and its evidence;
                      staff fill `staff_verdict` (yes / likely / no) and `staff_note`.
blind_sample.csv      papers the rules did NOT flag, shown without any rule output:
                      all unflagged microscopy/weak-instrument papers (stratum "risk")
                      plus a seeded random sample of unflagged life-science papers
                      (stratum "life_science"). Rows are shuffled; the stratum of each row
                      is kept in blind_sample_key.json, which the labeller should not open.

Once `staff_verdict` is filled in, `recall_estimate` scales the positives found in each
stratum to the stratum's size (Horvitz-Thompson) and reports recall with a range.
"""
import csv
import json
import math
import random
import re

from .sweep import DATA, cached_text, load_screened
from .text import normalise, redact, sentences

VERDICTS = ("yes", "likely", "no")
_RELEVANT = re.compile(r"microscop|confocal|spinning|imag(ed|ing)|acknowledg|thank|grateful|"
                       r"facilit|core\b|cytomet", re.I)


def _sentences_for_labeller(doi, year, limit=12):
    text, _ = cached_text(year, doi)
    out = []
    for s in sentences(normalise(text or "")):
        if _RELEVANT.search(s) and len(s) < 900:
            out.append(redact(s, 400))
            if len(out) >= limit:
                break
    return " | ".join(out)


def _flagged(r):
    return r.get("priority") in ("report", "check")


def _life_science(r, cfg):
    fields = r.get("fields") or []
    units = r.get("units") or []
    return (any(str(f).startswith(cfg.life_science_fields) for f in fields)
            or any(cfg.life_science_units.search(u) for u in units))


def write_label_sheets(year, sample_size=150, seed=None):
    from .config import load
    cfg = load()
    rows = load_screened(year)
    labels_path = DATA / str(year) / "reference_labels.csv"
    labels = {}
    if labels_path.exists():
        with labels_path.open(newline="", encoding="utf-8") as f:
            labels = {r["doi"]: r for r in csv.DictReader(f)}
    by = {r["doi"]: r for r in rows}

    review = DATA / str(year) / "labels_to_review.csv"
    with review.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["doi", "link", "title", "draft_verdict", "draft_note", "acknowledgement",
                    "evidence", "staff_verdict", "staff_note"])
        for doi, lab in sorted(labels.items()):
            r = by.get(doi, {})
            w.writerow([doi, f"https://doi.org/{doi}", r.get("title", ""), lab.get("used_facility", ""),
                        lab.get("note", ""), " | ".join(r.get("acknowledgement") or [])[:800],
                        " | ".join(r.get("evidence") or [])[:1500], "", ""])

    unflagged = [r for r in rows if r.get("has_text") and not _flagged(r) and r["doi"] not in labels]
    risk = [r for r in unflagged if r.get("category") in ("C", "F") or r.get("instruments_weak")]
    risk_dois = {r["doi"] for r in risk}
    life = [r for r in unflagged if r["doi"] not in risk_dois and _life_science(r, cfg)]
    seed = year if seed is None else seed
    rng = random.Random(seed)
    life_sample = rng.sample(life, min(sample_size, len(life)))
    sample = [("risk", r) for r in risk] + [("life_science", r) for r in life_sample]
    rng.shuffle(sample)

    blind = DATA / str(year) / "blind_sample.csv"
    with blind.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["doi", "link", "title", "journal", "relevant_sentences", "staff_verdict", "staff_note"])
        for _, r in sample:
            w.writerow([r["doi"], f"https://doi.org/{r['doi']}", r.get("title", ""), r.get("journal", ""),
                        _sentences_for_labeller(r["doi"], year), "", ""])
    key = {"seed": seed, "strata": {"risk": {"size": len(risk), "sampled": len(risk)},
                                    "life_science": {"size": len(life), "sampled": len(life_sample)}},
           "stratum_of": {r["doi"]: st for st, r in sample},
           "not_sampled": {"other_unflagged_with_text": len(unflagged) - len(risk) - len(life),
                           "without_text": sum(1 for r in rows if not r.get("has_text"))}}
    (DATA / str(year) / "blind_sample_key.json").write_text(json.dumps(key, indent=1), encoding="utf-8")
    return review, blind, key


def recall_estimate(year):
    """Recall of the rules estimated from the filled blind sample, or None if not filled."""
    base = DATA / str(year)
    blind, key_path = base / "blind_sample.csv", base / "blind_sample_key.json"
    if not (blind.exists() and key_path.exists()):
        return None
    key = json.loads(key_path.read_text(encoding="utf-8"))
    with blind.open(newline="", encoding="utf-8") as f:
        done = [r for r in csv.DictReader(f) if r["staff_verdict"].strip().lower() in VERDICTS]
    if not done:
        return None
    labels = {}
    lp = base / "reference_labels.csv"
    if lp.exists():
        with lp.open(newline="", encoding="utf-8") as f:
            labels = {r["doi"]: r["used_facility"] for r in csv.DictReader(f)}
    rows = {r["doi"]: r for r in load_screened(year)}
    found = sum(1 for d, v in labels.items() if v in ("yes", "likely") and _flagged(rows.get(d, {})))
    missed, var, lines = 0.0, 0.0, []
    for stratum, info in key["strata"].items():
        judged = [r for r in done if key["stratum_of"].get(r["doi"]) == stratum]
        if not judged:
            continue
        pos = sum(r["staff_verdict"].strip().lower() in ("yes", "likely") for r in judged)
        p = pos / len(judged)
        missed += p * info["size"]
        var += info["size"] ** 2 * p * (1 - p) / len(judged) * (1 - len(judged) / max(info["size"], 1))
        lines.append(f"    {stratum}: {pos}/{len(judged)} positive -> ~{p * info['size']:.1f} missed of {info['size']}")
    sd = math.sqrt(var)
    rec = found / (found + missed) if found + missed else float("nan")
    lo = found / (found + missed + 1.96 * sd) if found else 0.0
    hi = found / (found + max(missed - 1.96 * sd, 0)) if found else 0.0
    return "\n".join([f"  estimated recall from the blind sample: {rec:.2f} (≈95% range {lo:.2f}-{hi:.2f}); "
                      f"{found} flagged true positives, ~{missed:.1f} missed"] + lines +
                     [f"    not covered: {key['not_sampled']['other_unflagged_with_text']} other papers with text, "
                      f"{key['not_sampled']['without_text']} without text"])
