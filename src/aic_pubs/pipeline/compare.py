"""Compare completed strategy experiments for the same reporting year."""
from __future__ import annotations

import csv
import json
from pathlib import Path

from ..sweep import DATA




def _load_results(path):
    rows = []
    if not path.exists():
        return rows
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except ValueError:
            continue
    return rows

def _doi_set(rows, predicate=lambda row: True):
    return {
        row.get("doi")
        for row in rows
        if row.get("doi") and predicate(row)
    }


FIELDS = (
    "candidates",
    "target_year_candidates",
    "with_text",
    "with_full_text",
    "with_partial_text_only",
    "target_year_microscopy",
    "target_year_aic_leads",
    "known_user_candidates",
    "review_candidates",
    "seconds",
)


def _flatten_strategy_yield(row, summary):
    for item in (summary.get("discovery_yield") or {}).get("by_strategy") or []:
        name = item.get("strategy")
        if not name:
            continue
        row[f"discover_{name}_candidates"] = item.get("candidates", 0)
        row[f"discover_{name}_exclusive"] = item.get("exclusive", 0)

    for item in summary.get("text_strategy_yield") or []:
        name = item.get("strategy")
        if not name:
            continue
        row[f"text_{name}_successes"] = item.get("successes", 0)
        row[f"text_{name}_exclusive"] = item.get("exclusive_successes", 0)
        row[f"text_{name}_rejected"] = item.get("rejected", 0)
        row[f"text_{name}_errors"] = item.get("errors", 0)


def compare_experiments(year, plan_names, base_dir=None):
    base = Path(base_dir or DATA) / str(year) / "experiments"
    rows = []
    for name in plan_names:
        path = base / name / "summary.json"
        if not path.exists():
            raise FileNotFoundError(f"missing experiment summary: {path}")
        summary = json.loads(path.read_text(encoding="utf-8"))
        manifest_path = base / name / "run_manifest.json"
        manifest = (
            json.loads(manifest_path.read_text(encoding="utf-8"))
            if manifest_path.exists() else {}
        )
        result_rows = _load_results(base / name / "results.jsonl")
        row = {
            "plan": name,
            "incomplete_run": bool(summary.get("incomplete_run", False)),
            "selected_doi_set_sha256": manifest.get("selected_doi_set_sha256"),
            "discovered_doi_set_sha256": manifest.get("discovered_doi_set_sha256"),
            "source_tree_sha256": manifest.get("source_tree_sha256"),
            "facility_config_sha256": manifest.get("facility_config_sha256"),
            "manifest_year": manifest.get("year"),
            "discovered_candidate_count": manifest.get("discovered_candidate_count"),
            "selected_candidate_count": manifest.get("selected_candidate_count"),
            "_result_rows": result_rows,
        }
        for field in FIELDS:
            row[field] = summary.get(field, 0)
        _flatten_strategy_yield(row, summary)
        rows.append(row)

    baseline = rows[0] if rows else {}

    def same_if_known(left, right):
        if not left or not right:
            return None
        return left == right

    baseline_selected_hash = baseline.get("selected_doi_set_sha256")
    baseline_complete_selection = (
        baseline.get("discovered_candidate_count") is not None
        and baseline.get("selected_candidate_count") is not None
        and baseline.get("discovered_candidate_count") == baseline.get("selected_candidate_count")
    )
    baseline_results = baseline.get("_result_rows") or []
    baseline_sets = {
        "all": _doi_set(baseline_results),
        "target": _doi_set(
            baseline_results,
            lambda r: r.get("reporting_year_matches_target") is True,
        ),
        "microscopy": _doi_set(
            baseline_results,
            lambda r: (r.get("microscopy_terms") or 0) >= 5,
        ),
        "aic_leads": _doi_set(
            baseline_results,
            lambda r: (r.get("category") or None) in set("ABCDE"),
        ),
        "review": _doi_set(
            baseline_results,
            lambda r: bool(r.get("review_disposition")),
        ),
    }
    for row in rows:
        row["same_selected_candidate_set_as_baseline"] = (
            same_if_known(
                row.get("selected_doi_set_sha256"),
                baseline_selected_hash,
            )
        )
        row["same_code_as_baseline"] = same_if_known(
            row.get("source_tree_sha256"),
            baseline.get("source_tree_sha256"),
        )
        row["same_facility_config_as_baseline"] = same_if_known(
            row.get("facility_config_sha256"),
            baseline.get("facility_config_sha256"),
        )
        row["same_manifest_year_as_baseline"] = same_if_known(
            row.get("manifest_year"),
            baseline.get("manifest_year"),
        )
        explicit_environment_mismatch = any(
            flag is False
            for flag in (
                row["same_code_as_baseline"],
                row["same_facility_config_as_baseline"],
                row["same_manifest_year_as_baseline"],
            )
        )
        row["comparison_environment_compatible"] = not explicit_environment_mismatch
        row["resolver_metrics_comparable_to_baseline"] = (
            row["same_selected_candidate_set_as_baseline"] is True
            and row["comparison_environment_compatible"]
            and not row.get("incomplete_run")
            and not baseline.get("incomplete_run")
        )
        row_complete_selection = (
            row.get("discovered_candidate_count") is not None
            and row.get("selected_candidate_count") is not None
            and row.get("discovered_candidate_count") == row.get("selected_candidate_count")
        )
        row["complete_candidate_selection"] = row_complete_selection
        row["incremental_set_metrics_comparable_to_baseline"] = (
            baseline_complete_selection
            and row_complete_selection
            and row["comparison_environment_compatible"]
            and not row.get("incomplete_run")
            and not baseline.get("incomplete_run")
        )
        current_results = row.get("_result_rows") or []
        current_sets = {
            "all": _doi_set(current_results),
            "target": _doi_set(
                current_results,
                lambda r: r.get("reporting_year_matches_target") is True,
            ),
            "microscopy": _doi_set(
                current_results,
                lambda r: (r.get("microscopy_terms") or 0) >= 5,
            ),
            "aic_leads": _doi_set(
                current_results,
                lambda r: (r.get("category") or None) in set("ABCDE"),
            ),
            "review": _doi_set(
                current_results,
                lambda r: bool(r.get("review_disposition")),
            ),
        }
        if row["incremental_set_metrics_comparable_to_baseline"]:
            row["new_dois_vs_baseline"] = len(current_sets["all"] - baseline_sets["all"])
            row["lost_dois_vs_baseline"] = len(baseline_sets["all"] - current_sets["all"])
            row["new_target_year_dois_vs_baseline"] = len(
                current_sets["target"] - baseline_sets["target"]
            )
            row["new_microscopy_vs_baseline"] = len(
                current_sets["microscopy"] - baseline_sets["microscopy"]
            )
            row["new_aic_leads_vs_baseline"] = len(
                current_sets["aic_leads"] - baseline_sets["aic_leads"]
            )
            row["new_review_candidates_vs_baseline"] = len(
                current_sets["review"] - baseline_sets["review"]
            )
        else:
            for key in (
                "new_dois_vs_baseline",
                "lost_dois_vs_baseline",
                "new_target_year_dois_vs_baseline",
                "new_microscopy_vs_baseline",
                "new_aic_leads_vs_baseline",
                "new_review_candidates_vs_baseline",
            ):
                row[key] = None
    numeric_fields = {
        key
        for row in rows
        for key, value in row.items()
        if key not in (
            "plan", "seconds", "incomplete_run", "_result_rows",
            "selected_doi_set_sha256", "discovered_doi_set_sha256",
            "same_selected_candidate_set_as_baseline",
            "resolver_metrics_comparable_to_baseline",
            "same_code_as_baseline",
            "same_facility_config_as_baseline",
            "same_manifest_year_as_baseline",
            "comparison_environment_compatible",
            "source_tree_sha256",
            "facility_config_sha256",
            "manifest_year",
            "discovered_candidate_count",
            "selected_candidate_count",
            "complete_candidate_selection",
            "incremental_set_metrics_comparable_to_baseline",
        )
        and isinstance(value, (int, float))
        and not isinstance(value, bool)
    }
    for row in rows:
        for field in numeric_fields:
            value = row.get(field, 0)
            base_value = baseline.get(field, 0)
            if not (isinstance(value, (int, float)) and isinstance(base_value, (int, float))):
                continue
            if not row["comparison_environment_compatible"]:
                row[f"delta_{field}"] = None
            elif field.startswith("text_") and not row["resolver_metrics_comparable_to_baseline"]:
                row[f"delta_{field}"] = None
            else:
                row[f"delta_{field}"] = value - base_value
    for row in rows:
        row.pop("_result_rows", None)
    return rows


def write_comparison(year, plan_names, base_dir=None, output_path=None):
    rows = compare_experiments(year, plan_names, base_dir=base_dir)
    base = Path(base_dir or DATA) / str(year) / "experiments"
    path = Path(output_path or base / "plan_comparison.csv")
    path.parent.mkdir(parents=True, exist_ok=True)

    dynamic = sorted({
        key
        for row in rows
        for key in row
        if key not in {
            "plan", "incomplete_run", "_result_rows", "selected_doi_set_sha256",
            "discovered_doi_set_sha256",
            "same_selected_candidate_set_as_baseline",
            "resolver_metrics_comparable_to_baseline",
            "same_code_as_baseline",
            "same_facility_config_as_baseline",
            "same_manifest_year_as_baseline",
            "comparison_environment_compatible",
            "source_tree_sha256",
            "facility_config_sha256",
            "manifest_year", "discovered_candidate_count", "selected_candidate_count",
            "complete_candidate_selection", "incremental_set_metrics_comparable_to_baseline",
            *FIELDS
        } and not key.startswith("delta_")
    })
    delta_fields = sorted({
        key
        for row in rows
        for key in row
        if key.startswith("delta_")
    })
    fields = [
        "plan",
        "incomplete_run",
        "same_selected_candidate_set_as_baseline",
        "resolver_metrics_comparable_to_baseline",
        "same_code_as_baseline",
        "same_facility_config_as_baseline",
        "same_manifest_year_as_baseline",
        "comparison_environment_compatible",
        "source_tree_sha256",
        "facility_config_sha256",
        "manifest_year",
        "discovered_candidate_count",
        "selected_candidate_count",
        "complete_candidate_selection",
        "incremental_set_metrics_comparable_to_baseline",
        "selected_doi_set_sha256",
        "discovered_doi_set_sha256",
        *FIELDS,
        *dynamic,
        *delta_fields,
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    return rows, path
