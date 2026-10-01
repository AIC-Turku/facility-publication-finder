"""Rule-based screening of one paper's full text."""
import re
from .bookings import booking_match, name_key
from .text import evidence, normalise, redact, sentences

CATEGORIES = {
    "A": "acknowledges the facility",
    "B": "names a distinctive facility instrument, no acknowledgement",
    "C": "local paper using a specialist facility technique, no acknowledgement",
    "D": "facility named only as an author affiliation",
    "E": "microscopy + Biocenter Finland / Euro-BioImaging, no facility name",
    "F": "microscopy, no facility evidence",
    "G": "little or no microscopy",
    "N": "no full text available",
}
LEADS = "ABCDE"  # categories a person (or the LLM) should look at
MICROSCOPY_MIN = 5  # generic microscopy-term hits to count as a microscopy paper


def screen(text: str | None, cfg, local: bool = True, meta: dict | None = None) -> dict:
    """Screen one paper's full text.

    local: the paper has UTU/ÅA authors (true for everything from the repositories).
    meta:  repository metadata used by the paper-level rules: doi, title, type, fields,
           units, local_authors, sources, and history (local authors of acknowledging
           papers from other years).
    """
    meta = meta or {}
    text = normalise(text)
    if not text:
        out = {"category": "N", "has_text": False}
        if "europepmc_ack" in (meta.get("sources") or []):
            # Europe PMC matched a facility acknowledgement but no full text was obtained
            # (2025: two preprints thanking the Cell Imaging and Cytometry Core sat here)
            out.update(priority="check", score=cfg.score["check"],
                       score_reasons=["Europe PMC acknowledgement match; full text unavailable"])
        return out
    ack, ack_affil, ack_flowing, elsewhere = [], [], [], []
    thanks = [x for x in sentences(text) if _acknowledging(x)]
    instruments = {}
    inst_turku, inst_elsewhere = False, []
    for s in sentences(text):
        if _credits_elsewhere(s, cfg):
            elsewhere.append(s)
        for p in cfg.acknowledgement:
            m = p.search(s)
            if not m:
                continue
            if cfg.flowing.search(s):
                ack_flowing.append(s)
            elif (cfg.affiliation.search(s) or cfg.postal.search(s)) and not _acknowledging(s):
                ack_affil.append(s)
            else:
                ack.append(s)
            break
        hit = False
        for inst in cfg.instruments:
            if inst.matches(s):
                instruments.setdefault(inst.id, inst.strength)
                hit = hit or inst.strength == "strong"
        if hit:
            if cfg.turku_words.search(s):
                inst_turku = True
            elif len(s) < 400 and cfg.other_institution.search(s):  # skip key-resource tables
                inst_elsewhere.append(s)
    # Components are only meaningful when they occur near an actual mention of
    # the instrument. Searching the whole paper can accidentally combine a camera
    # from one experiment with software from another and manufacture a fingerprint.
    window = int(cfg.raw.get("component_window_chars", 600))
    fingerprints = {}
    for inst in cfg.instruments:
        if not inst.components:
            continue
        found = {}
        for match in inst.pattern.finditer(text):
            lo, hi = max(0, match.start() - window), min(len(text), match.end() + window)
            context = text[lo:hi]
            if inst.exclude and inst.exclude.search(context):
                continue
            for index, component in enumerate(inst.components):
                m = component.search(context)
                if m and index not in found:  # count components, not spellings
                    found[index] = m.group(0)
        if found:
            fingerprints[inst.id] = sorted(found.values())
    # a common (weak) model becomes a real lead when >= 2 of its own components appear too
    for k, v in instruments.items():
        if v == "weak" and len(fingerprints.get(k, [])) >= 2:
            instruments[k] = "strong"
    strong = sorted(k for k, v in instruments.items() if v == "strong")
    techniques = {t.id: len(t.pattern.findall(text)) for t in cfg.techniques}
    techniques = {k: n for k, n in techniques.items() if n}
    specialist = sorted(t.id for t in cfg.techniques if t.strength == "specialist" and t.id in techniques)
    micro = len(cfg.microscopy.findall(text))
    network = any(p.search(text) for p in cfg.network)
    if ack:
        cat = "A"
    elif strong:
        cat = "B"
    elif specialist and local and micro >= MICROSCOPY_MIN:
        cat = "C"
    elif ack_affil:
        cat = "D"
    elif micro >= MICROSCOPY_MIN and network:
        cat = "E"
    elif micro >= MICROSCOPY_MIN:
        cat = "F"
    else:
        cat = "G"
    out = {
        "category": cat,
        "has_text": True,
        "microscopy_terms": micro,
        "instruments_strong": strong,
        "instruments_weak": sorted(k for k, v in instruments.items() if v == "weak"),
        "techniques": techniques,
        "techniques_specialist": specialist,
        "acknowledgement": [redact(x) for x in ack[:3]],
        "affiliation_only": [redact(x) for x in ack_affil[:2]],
        "flowing_software_only": bool(ack_flowing) and not ack,
        "network_named": network,
        "cytometry_only": bool(ack) and micro == 0 and bool(_CYTOMETRY.search(text)),
        "staff_thanked": _staff_thanked(thanks, cfg.staff),
        "_private_staff_thanked": _staff_thanked_keys(thanks, meta.get("staff")),
        "other_local_imaging": any(p.search(text) for p in cfg.other_local_imaging),
        "local_email": bool(cfg.email.search(text)),
        "fingerprints": fingerprints,
        "credited_elsewhere": [redact(x) for x in elsewhere[:3]],
        "instrument_named_with_turku": inst_turku,
        "instrument_named_elsewhere": [redact(x) for x in inst_elsewhere[:2]],
    }
    out["score"], out["priority"], out["score_reasons"], private = _score(out, meta, cfg)
    out.pop("_private_staff_thanked", None)  # private: never stored in the public row
    if private:
        out["private"] = private  # split off by the sweep into a git-ignored sidecar
    if cat in LEADS:  # keep reviewable evidence only for leads
        out["evidence"] = evidence(text, cfg.evidence_patterns)
    return out


def _credits_elsewhere(s, cfg):
    """Sentence thanks/credits a light-microscopy facility that is not AIC."""
    if any(p.search(s) for p in cfg.acknowledgement) or cfg.not_light_microscopy.search(s):
        return False
    named = any(p.search(s) for p in cfg.other_facilities)
    return named or (bool(cfg.generic_facility.search(s)) and _acknowledging(s))


def _score(r, meta, cfg):
    """Additive score with the reason for every term, so each ranking can be explained."""
    w = cfg.score
    reasons = []

    def add(key, value=None, why=None):
        v = w[key] if value is None else value
        if v:
            reasons.append(f"{v:+d} {why or key.replace('_', ' ')}")
        return v

    acked = bool(r["acknowledgement"])
    best = max((len(v) for k, v in r["fingerprints"].items()
                if k in r["instruments_strong"] + r["instruments_weak"]), default=0)
    score = 0
    if acked:
        score += add("acknowledgement")
    if r["instruments_strong"]:
        score += add("strong_instrument", why="instrument: " + ", ".join(r["instruments_strong"]))
    if best:
        score += add("component", min(best * w["component"], w["component_max"]),
                     f"{best} instrument component(s)")
    if r["techniques_specialist"]:
        score += add("specialist_technique",
                     min(len(r["techniques_specialist"]) * w["specialist_technique"],
                         w["specialist_technique_max"]),
                     "technique: " + ", ".join(r["techniques_specialist"]))
    if r["local_email"]:
        score += add("local_email", why=f"{'/'.join(cfg.email_domains)} e-mail")
    if r["instrument_named_with_turku"]:
        score += add("instrument_named_with_turku")

    authors = meta.get("local_authors") or []
    sources = set(meta.get("sources") or [])
    if len(authors) >= 3:
        score += add("many_local_authors", why=f"{len(authors)} UTU authors")
    if any(cfg.life_science_units.search(u) for u in meta.get("units") or []):
        score += add("life_science_unit")
    history = meta.get("history") or set()
    if history & set(authors):
        # generic on purpose: never put personal names in published score reasons
        score += add("repeat_user", why="repeat facility user group")

    # Rules fed by PRIVATE inputs (staff list, OpenIRIS bookings) are kept apart:
    # they never change the published score/priority, only the private view.
    private_reasons = []

    def add_private(key, why):
        v = w[key]
        if v:
            private_reasons.append(f"{v:+d} {why}")
        return v

    private_delta = 0
    staff = {name_key(n) for n in cfg.staff} | set(meta.get("staff") or ())
    if staff and {name_key(a) for a in authors} & staff:
        private_delta += add_private("staff_author", "facility staff among authors")
    if r.get("_private_staff_thanked") and not r.get("staff_thanked"):
        private_delta += add_private("staff_thanked", "facility staff thanked")
    booked, same = booking_match(authors, meta.get("year"),
                                 r["instruments_strong"] + r["instruments_weak"], meta.get("bookings"))
    # a booking is circumstantial: it never outweighs explicit evidence of imaging elsewhere,
    # and it only corroborates: the paper must name an AIC instrument or technique itself
    against = (r["credited_elsewhere"] or r["instrument_named_elsewhere"]
               or (len(authors) == 1 and not (set(sources) & cfg.sources_without_author_lists)))
    named = r["instruments_strong"] or r["instruments_weak"] or r["techniques_specialist"]
    if booked and named and r["microscopy_terms"] >= MICROSCOPY_MIN and (acked or not against):
        private_delta += add_private("group_booked", "group booked the facility")
        if same:
            private_delta += add_private("booked_instrument_used", "booked instrument named in paper")

    if r.get("staff_thanked"):
        score += add("staff_thanked", why="facility staff thanked")
    if not acked:  # penalties never demote an acknowledging paper
        if r["credited_elsewhere"]:
            score += add("credited_elsewhere")
        if r["instrument_named_elsewhere"]:
            score += add("instrument_named_elsewhere")
        if len(authors) == 1 and not (set(sources) & cfg.sources_without_author_lists):
            score += add("single_local_author")
        fields = meta.get("fields") or []
        if fields and not any(f.startswith(cfg.life_science_fields) for f in fields):
            score += add("non_life_science_field")
        if (meta.get("type") or "").startswith("A2") or cfg.review_title.search(meta.get("title") or ""):
            score += add("review")
    doi = meta.get("doi") or ""
    if doi.startswith(cfg.preprint_prefixes):
        score += add("preprint")
    if doi.startswith(cfg.dataset_prefixes):
        score += add("not_a_paper", why="dataset, not a paper")

    dataset = doi.startswith(cfg.dataset_prefixes)
    # Owner's decision (2026-09-28): cytometry at the former Cell Imaging and Cytometry
    # Core counts as AIC use. The flag stays as information for the reviewer.
    if r.get("cytometry_only"):
        reasons.append("cytometry only (no microscopy in the text)")

    def prio(value):
        if dataset:
            return "low"  # a dataset is never a publication to report
        p = "report" if value >= w["report"] else "check" if value >= w["check"] else "low"
        if p == "report" and not acked:
            p = "check"  # "report" means acknowledged; the rest is for follow-up
        return p

    private = None
    if private_reasons:
        private = {"score": score + private_delta, "priority": prio(score + private_delta),
                   "reasons": private_reasons}
    return score, prio(score), reasons, private


# a postal address marks an author-affiliation line (10.1002/test.000010:
# "... Cell imaging and Cytometry (CIC) Core Turku Bioscience ... FI-20520 Turku, Finland")
# (the postal patterns are facility.yaml `postal_patterns`)
_CYTOMETRY = re.compile(r"flow cytomet|cell sort|FACS|Fortessa|NovoCyte|CytoFLEX|Accuri", re.I)


def _staff_thanked(sentences_, staff):
    """Facility staff named in acknowledging sentences (surname + first initial)."""
    if not staff:
        return False
    keys = []
    for n in staff:
        last, _, first = n.partition(",")
        if last.strip():
            keys.append(re.compile(rf"\b{re.escape(first.strip()[:1])}\w*\.?\s+{re.escape(last.strip())}\b"
                                   if first.strip() else rf"\b{re.escape(last.strip())}\b"))
    return any(k.search(s) for k in keys for s in sentences_)


def _staff_thanked_keys(sentences_, keys):
    """Like _staff_thanked, for private staff given as (surname, first initial) keys."""
    if not keys:
        return False
    pats = [re.compile(rf"\b{re.escape(first)}\w*\.?\s+{re.escape(last)}\b", re.I)
            for last, first in keys if last and first]
    return any(p.search(s) for p in pats for s in sentences_)


def _acknowledging(sentence):
    s = sentence.lower()
    return any(w in s for w in ("acknowledg", "thank", "grateful", "performed", "carried out at",
                                "conducted at", "support", "imaged at", "facility"))
