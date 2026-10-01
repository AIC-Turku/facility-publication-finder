"""Keep facilities/<facility>/facility.yaml in step with the AIC-Turku-database instrument records.

Reports active instruments without a name pattern and capability terms
(imaging modes, readouts, assay operations, workflows, non-optical
capabilities, and technique-bearing modules) used by an active instrument but
without a technique pattern.
"""
import subprocess
import tempfile
from pathlib import Path

import yaml

CAPABILITY_KEYS = ("imaging_modes", "readouts", "assay_operations", "workflows", "non_optical")
# modules that name a technique (others, e.g. incubation or stages, do not)
TECHNIQUE_MODULES = {"frap": "frap", "photoactivation": "photoactivation", "fcs": "fcs",
                     "flim": "flim", "airyscan": "ism", "3d_sim": "sim", "sim_module": "sim",
                     "tirf": "tirf", "ring_tirf": "tirf", "easy3d_sted": "sted",
                     "rescue_sted": "sted", "afm_module": "afm", "optogenetics": "optogenetics",
                     "impedance_module": "impedance_cytometry"}
# capabilities too generic to search for in text
IGNORE = {"transmitted_brightfield", "optical_sectioning", "super_resolution", "single_molecule"}


def database_path(path_or_url):
    p = Path(path_or_url)
    if p.exists():
        return p
    tmp = Path(tempfile.mkdtemp()) / "AIC-Turku-database"
    subprocess.run(["git", "clone", "--depth", "1", "-q", path_or_url, str(tmp)], check=True)
    return tmp


def _instrument_capabilities(db):
    out = {}
    for f in sorted(Path(db, "instruments").glob("*.yaml")):
        d = yaml.safe_load(f.read_text(encoding="utf-8"))
        iid = d["instrument"]["instrument_id"]
        caps = d.get("capabilities") or {}
        terms = {t for k in CAPABILITY_KEYS for t in (caps.get(k) or []) if isinstance(t, str)}
        terms |= {TECHNIQUE_MODULES[m["type"]] for m in d.get("modules") or []
                  if isinstance(m, dict) and m.get("type") in TECHNIQUE_MODULES}
        out[iid] = {"name": d["instrument"].get("display_name", iid), "terms": terms - IGNORE}
    return out


def report(cfg, db):
    inst = _instrument_capabilities(db)
    known_inst = {i.id for i in cfg.instruments}
    known_tech = {t.id for t in cfg.techniques}
    lines = []
    missing_inst = sorted(set(inst) - known_inst)
    lines.append(f"{len(inst)} active instruments; {len(missing_inst)} without a name pattern")
    lines += [f"  - {i} ({inst[i]['name']})" for i in missing_inst]
    no_fp = sorted(i.id for i in cfg.instruments if i.id in inst and not i.components)
    lines.append(f"{len(no_fp)} active instruments without component fingerprints (optional)")
    lines += [f"  - {i}" for i in no_fp]
    offered = {}
    for iid, v in inst.items():
        for t in v["terms"]:
            offered.setdefault(t, []).append(iid)
    missing_tech = sorted(set(offered) - known_tech)
    lines.append(f"{len(offered)} capability terms offered; {len(missing_tech)} without a technique pattern")
    lines += [f"  - {t} (on {', '.join(offered[t])})" for t in missing_tech]
    unused = sorted(known_tech - set(offered))
    if unused:
        lines.append("technique patterns for terms no active instrument lists: " + ", ".join(unused))
    return "\n".join(lines)
