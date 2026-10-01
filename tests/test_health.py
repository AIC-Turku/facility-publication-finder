import json

from aic_pubs.pipeline.health import experiment_health


def test_experiment_health_distinguishes_empty_and_error_sources(tmp_path):
    path = tmp_path / "2025" / "experiments" / "test"
    path.mkdir(parents=True)
    summary = {
        "incomplete_run": True,
        "discovery": [
            {
                "strategy": "institutional",
                "returned": 100,
                "unique_added": 100,
                "seconds": 1.2,
                "error": None,
            },
            {
                "strategy": "openalex_facility",
                "returned": 0,
                "unique_added": 0,
                "seconds": 10,
                "error": "TimeoutError: timed out",
            },
            {
                "strategy": "crossref_awards",
                "returned": 0,
                "unique_added": 0,
                "seconds": 0.5,
                "error": None,
            },
            {
                "strategy": "datacite",
                "returned": 100,
                "unique_added": 5,
                "seconds": 2.0,
                "error": None,
                "truncated": True,
            },
        ],
        "text_strategy_yield": [
            {
                "strategy": "europepmc",
                "successes": 5,
                "exclusive_successes": 2,
                "selected": 5,
                "rejected": 0,
                "errors": 0,
            },
            {
                "strategy": "publisher_html",
                "successes": 0,
                "exclusive_successes": 0,
                "selected": 0,
                "rejected": 3,
                "errors": 0,
            },
        ],
        "source_health": [
            {
                "strategy": "publisher_html",
                "attempted": 10,
                "success": 0,
                "miss": 7,
                "rejected": 3,
                "error": 0,
                "success_rate": 0.0,
                "reasons": [
                    {"reason": "access_page", "count": 3},
                    {"reason": "no_publisher_url", "count": 7},
                ],
            },
        ],
        "text_attempts": [
            {"strategy": "europepmc", "status": "success", "count": 5},
            {"strategy": "publisher_html", "status": "rejected", "count": 3},
            {"strategy": "publisher_html", "status": "miss", "count": 7},
        ],
    }
    (path / "summary.json").write_text(json.dumps(summary), encoding="utf-8")

    out = experiment_health(2025, "test", base_dir=tmp_path)
    discovery = {row["strategy"]: row for row in out["discovery"]}
    text = {row["strategy"]: row for row in out["text"]}

    assert discovery["institutional"]["status"] == "ok"
    assert discovery["openalex_facility"]["status"] == "error"
    assert discovery["crossref_awards"]["status"] == "empty"
    assert discovery["datacite"]["status"] == "truncated"
    assert discovery["datacite"]["truncated"] is True
    assert text["europepmc"]["status"] == "ok"
    assert text["publisher_html"]["status"] == "no_success"
    assert text["publisher_html"]["attempted"] == 10
    assert text["publisher_html"]["success_rate"] == 0.0
    assert text["publisher_html"]["reasons"][0] == {
        "reason": "access_page",
        "count": 3,
    }


def test_experiment_health_missing_summary_fails(tmp_path):
    import pytest
    with pytest.raises(FileNotFoundError):
        experiment_health(2025, "missing", base_dir=tmp_path)
