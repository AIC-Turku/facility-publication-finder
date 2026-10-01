import csv
import json

from aic_pubs import labelling


def test_recall_estimate_scales_sample_to_stratum(monkeypatch, tmp_path):
    monkeypatch.setattr(labelling, "DATA", tmp_path)
    base = tmp_path / "2025"
    base.mkdir()
    rows = [{"doi": f"10.1/f{i}", "priority": "report", "has_text": True} for i in range(9)]
    monkeypatch.setattr(labelling, "load_screened", lambda year: rows)
    with (base / "reference_labels.csv").open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["doi", "used_facility", "cytometry_only", "note"])
        w.writerows([[r["doi"], "yes", "false", ""] for r in rows])
    # 10 of 100 'life_science' papers sampled; 1 positive -> ~10 missed
    sample = [{"doi": f"10.1/s{i}", "staff_verdict": "yes" if i == 0 else "no"} for i in range(10)]
    with (base / "blind_sample.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["doi", "staff_verdict"])
        w.writeheader()
        w.writerows(sample)
    key = {"strata": {"life_science": {"size": 100, "sampled": 10}},
           "stratum_of": {r["doi"]: "life_science" for r in sample},
           "not_sampled": {"other_unflagged_with_text": 0, "without_text": 0}}
    (base / "blind_sample_key.json").write_text(json.dumps(key))
    out = labelling.recall_estimate(2025)
    assert "estimated recall from the blind sample: 0.47" in out  # 9 / (9 + 10)
    assert "~10.0 missed of 100" in out


def test_no_estimate_until_labelled(monkeypatch, tmp_path):
    monkeypatch.setattr(labelling, "DATA", tmp_path)
    assert labelling.recall_estimate(2025) is None
