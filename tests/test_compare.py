import json

import pytest

from aic_pubs.pipeline.compare import compare_experiments, write_comparison


def _write_summary(base, year, name, **values):
    path = base / str(year) / "experiments" / name
    path.mkdir(parents=True, exist_ok=True)
    payload = {
        "candidates": 0,
        "target_year_candidates": 0,
        "with_text": 0,
        "with_full_text": 0,
        "with_partial_text_only": 0,
        "target_year_microscopy": 0,
        "target_year_aic_leads": 0,
        "known_user_candidates": 0,
        "review_candidates": 0,
        "seconds": 0,
        **values,
    }
    (path / "summary.json").write_text(json.dumps(payload), encoding="utf-8")


def test_compare_experiments_uses_first_plan_as_baseline(tmp_path):
    _write_summary(
        tmp_path, 2025, "baseline",
        target_year_candidates=100,
        with_full_text=80,
        target_year_aic_leads=10,
    )
    _write_summary(
        tmp_path, 2025, "max",
        target_year_candidates=120,
        with_full_text=95,
        target_year_aic_leads=14,
    )
    rows = compare_experiments(2025, ["baseline", "max"], base_dir=tmp_path)
    assert rows[0]["delta_target_year_candidates"] == 0
    assert rows[1]["delta_target_year_candidates"] == 20
    assert rows[1]["delta_with_full_text"] == 15
    assert rows[1]["delta_target_year_aic_leads"] == 4


def test_write_comparison_creates_csv(tmp_path):
    _write_summary(tmp_path, 2025, "baseline", candidates=10)
    _write_summary(tmp_path, 2025, "user", candidates=12)
    rows, path = write_comparison(
        2025,
        ["baseline", "user"],
        base_dir=tmp_path,
    )
    assert path.exists()
    assert rows[1]["delta_candidates"] == 2


def test_compare_missing_summary_fails_explicitly(tmp_path):
    with pytest.raises(FileNotFoundError):
        compare_experiments(2025, ["missing"], base_dir=tmp_path)


def test_compare_deltas_include_strategy_only_in_later_plan(tmp_path):
    _write_summary(
        tmp_path,
        2025,
        "baseline",
        discovery_yield={"by_strategy": [
            {"strategy": "institutional", "candidates": 100, "exclusive": 100}
        ]},
    )
    _write_summary(
        tmp_path,
        2025,
        "max",
        discovery_yield={"by_strategy": [
            {"strategy": "institutional", "candidates": 100, "exclusive": 90},
            {"strategy": "known_users_orcid", "candidates": 15, "exclusive": 5},
        ]},
    )
    rows = compare_experiments(2025, ["baseline", "max"], base_dir=tmp_path)
    assert rows[1]["discover_known_users_orcid_exclusive"] == 5
    assert rows[1]["delta_discover_known_users_orcid_exclusive"] == 5


def test_compare_flags_candidate_set_mismatch(tmp_path):
    _write_summary(tmp_path, 2025, "baseline", candidates=10)
    _write_summary(tmp_path, 2025, "other", candidates=10)
    base = tmp_path / "2025" / "experiments"
    (base / "baseline" / "run_manifest.json").write_text(
        json.dumps({
            "selected_doi_set_sha256": "aaa",
            "discovered_doi_set_sha256": "all-a",
        }),
        encoding="utf-8",
    )
    (base / "other" / "run_manifest.json").write_text(
        json.dumps({
            "selected_doi_set_sha256": "bbb",
            "discovered_doi_set_sha256": "all-b",
        }),
        encoding="utf-8",
    )
    rows = compare_experiments(2025, ["baseline", "other"], base_dir=tmp_path)
    assert rows[0]["same_selected_candidate_set_as_baseline"] is True
    assert rows[1]["same_selected_candidate_set_as_baseline"] is False


def test_compare_suppresses_resolver_deltas_for_different_candidate_sets(tmp_path):
    _write_summary(
        tmp_path,
        2025,
        "baseline",
        text_strategy_yield=[{
            "strategy": "europepmc",
            "successes": 5,
            "exclusive_successes": 2,
            "rejected": 0,
            "errors": 0,
        }],
    )
    _write_summary(
        tmp_path,
        2025,
        "other",
        text_strategy_yield=[{
            "strategy": "europepmc",
            "successes": 9,
            "exclusive_successes": 4,
            "rejected": 0,
            "errors": 0,
        }],
    )
    base = tmp_path / "2025" / "experiments"
    (base / "baseline" / "run_manifest.json").write_text(
        json.dumps({"selected_doi_set_sha256": "aaa"}),
        encoding="utf-8",
    )
    (base / "other" / "run_manifest.json").write_text(
        json.dumps({"selected_doi_set_sha256": "bbb"}),
        encoding="utf-8",
    )
    rows = compare_experiments(2025, ["baseline", "other"], base_dir=tmp_path)
    assert rows[1]["resolver_metrics_comparable_to_baseline"] is False
    assert rows[1]["delta_text_europepmc_successes"] is None


def test_compare_suppresses_all_deltas_when_code_differs(tmp_path):
    _write_summary(
        tmp_path,
        2025,
        "baseline",
        target_year_candidates=100,
        target_year_aic_leads=10,
    )
    _write_summary(
        tmp_path,
        2025,
        "other",
        target_year_candidates=120,
        target_year_aic_leads=14,
    )
    base = tmp_path / "2025" / "experiments"
    (base / "baseline" / "run_manifest.json").write_text(
        json.dumps({
            "selected_doi_set_sha256": "same",
            "source_tree_sha256": "code-a",
            "facility_config_sha256": "cfg-a",
            "year": 2025,
        }),
        encoding="utf-8",
    )
    (base / "other" / "run_manifest.json").write_text(
        json.dumps({
            "selected_doi_set_sha256": "same",
            "source_tree_sha256": "code-b",
            "facility_config_sha256": "cfg-a",
            "year": 2025,
        }),
        encoding="utf-8",
    )
    rows = compare_experiments(2025, ["baseline", "other"], base_dir=tmp_path)
    assert rows[1]["same_code_as_baseline"] is False
    assert rows[1]["comparison_environment_compatible"] is False
    assert rows[1]["delta_target_year_candidates"] is None
    assert rows[1]["delta_target_year_aic_leads"] is None


def test_compare_allows_deltas_when_manifest_hashes_missing(tmp_path):
    _write_summary(tmp_path, 2025, "baseline", candidates=10)
    _write_summary(tmp_path, 2025, "other", candidates=12)
    rows = compare_experiments(2025, ["baseline", "other"], base_dir=tmp_path)
    assert rows[1]["comparison_environment_compatible"] is True
    assert rows[1]["delta_candidates"] == 2


def _write_results(base, year, name, rows):
    path = base / str(year) / "experiments" / name
    path.mkdir(parents=True, exist_ok=True)
    (path / "results.jsonl").write_text(
        "\n".join(json.dumps(row) for row in rows) + "\n",
        encoding="utf-8",
    )


def _write_manifest(base, year, name, *, count=1, selected=None,
                    code="same-code", config="same-config"):
    path = base / str(year) / "experiments" / name
    path.mkdir(parents=True, exist_ok=True)
    (path / "run_manifest.json").write_text(
        json.dumps({
            "selected_doi_set_sha256": name,
            "discovered_doi_set_sha256": name,
            "source_tree_sha256": code,
            "facility_config_sha256": config,
            "year": year,
            "discovered_candidate_count": count,
            "selected_candidate_count": count if selected is None else selected,
        }),
        encoding="utf-8",
    )


def test_compare_reports_incremental_doi_and_downstream_value(tmp_path):
    baseline = [
        {
            "doi": "10.1000/a",
            "reporting_year_matches_target": True,
            "microscopy_terms": 0,
            "category": "G",
        },
        {
            "doi": "10.1000/b",
            "reporting_year_matches_target": True,
            "microscopy_terms": 0,
            "category": "G",
        },
    ]
    alternative = [
        baseline[1],
        {
            "doi": "10.1000/c",
            "reporting_year_matches_target": True,
            "microscopy_terms": 7,
            "category": "B",
            "review_disposition": "lead_b",
        },
    ]
    _write_summary(tmp_path, 2025, "baseline", candidates=2)
    _write_summary(tmp_path, 2025, "alternative", candidates=2)
    _write_results(tmp_path, 2025, "baseline", baseline)
    _write_results(tmp_path, 2025, "alternative", alternative)
    _write_manifest(tmp_path, 2025, "baseline", count=2)
    _write_manifest(tmp_path, 2025, "alternative", count=2)

    rows = compare_experiments(
        2025,
        ["baseline", "alternative"],
        base_dir=tmp_path,
    )
    alt = rows[1]
    assert alt["new_dois_vs_baseline"] == 1
    assert alt["lost_dois_vs_baseline"] == 1
    assert alt["new_target_year_dois_vs_baseline"] == 1
    assert alt["new_microscopy_vs_baseline"] == 1
    assert alt["new_aic_leads_vs_baseline"] == 1
    assert alt["new_review_candidates_vs_baseline"] == 1
    assert "_result_rows" not in alt


def test_compare_suppresses_incremental_sets_when_code_differs(tmp_path):
    rows = [{"doi": "10.1000/a", "reporting_year_matches_target": True}]
    _write_summary(tmp_path, 2025, "baseline", candidates=1)
    _write_summary(tmp_path, 2025, "other", candidates=1)
    _write_results(tmp_path, 2025, "baseline", rows)
    _write_results(tmp_path, 2025, "other", rows)
    _write_manifest(tmp_path, 2025, "baseline", code="code-a")
    _write_manifest(tmp_path, 2025, "other", code="code-b")

    compared = compare_experiments(
        2025,
        ["baseline", "other"],
        base_dir=tmp_path,
    )
    assert compared[1]["comparison_environment_compatible"] is False
    assert compared[1]["new_dois_vs_baseline"] is None


def test_compare_suppresses_incremental_sets_for_sampled_runs(tmp_path):
    rows = [{"doi": "10.1000/a", "reporting_year_matches_target": True}]
    _write_summary(tmp_path, 2025, "baseline", candidates=1)
    _write_summary(tmp_path, 2025, "sampled", candidates=1)
    _write_results(tmp_path, 2025, "baseline", rows)
    _write_results(tmp_path, 2025, "sampled", rows)
    _write_manifest(tmp_path, 2025, "baseline", count=10, selected=1)
    _write_manifest(tmp_path, 2025, "sampled", count=12, selected=1)

    compared = compare_experiments(
        2025,
        ["baseline", "sampled"],
        base_dir=tmp_path,
    )
    assert compared[1]["complete_candidate_selection"] is False
    assert compared[1]["incremental_set_metrics_comparable_to_baseline"] is False
    assert compared[1]["new_dois_vs_baseline"] is None
