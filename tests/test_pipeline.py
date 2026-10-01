import json

import pytest

from aic_pubs.identity import UserIdentity
from aic_pubs.pipeline import discovery_strategies, text_strategies
from aic_pubs.pipeline.plan import load_plan
from aic_pubs.pipeline.runner import run_plan
from aic_pubs.pipeline.types import TextAttempt
from aic_pubs.pipeline.validators import validate_article_text


def test_builtin_plans_load():
    for name in (
        "baseline",
        "public_discovery",
        "user_recall",
        "max_recall",
        "resolver_benchmark",
        "user_smoke",
    ):
        plan = load_plan(f"config/plans/{name}.yaml")
        assert plan["discovery"]
        assert plan["text"]["strategies"]


def test_known_user_strategy_queries_every_verified_orcid(monkeypatch):
    calls = []

    def fake(orcid, from_year, to_year, api_key=None, per_page=100,
             timeout=45, max_pages=20):
        calls.append((orcid, from_year, to_year))
        return [{"doi": f"10.1000/{orcid[-4:]}"}]

    monkeypatch.setattr(discovery_strategies.discovery, "openalex_author_works", fake)
    from aic_pubs.config import load
    from aic_pubs.pipeline.types import RunContext

    context = RunContext(
        year=2025,
        cfg=load(),
        users=(
            UserIdentity("Local User", "University of Turku", "0000-0001-0000-0001"),
            UserIdentity("External User", "Elsewhere", "0000-0002-0000-0002"),
            UserIdentity("No Orcid", "Elsewhere", ""),
        ),
    )
    rows = discovery_strategies.run(
        "known_users_orcid",
        context,
        {"year_pad": 0},
    )
    assert len(rows) == 2
    assert calls == [
        ("0000-0001-0000-0001", 2025, 2025),
        ("0000-0002-0000-0002", 2025, 2025),
    ]


def test_text_validator_rejects_access_page():
    text = (
        "Institutional access required. Sign in to access this article. "
        * 100
    )
    accepted, quality, reason = validate_article_text(text)
    assert not accepted
    assert quality is None
    assert reason == "access_page"


def test_text_validator_accepts_substantive_article():
    text = (
        "Methods. Cells were cultured and imaged by confocal microscopy. "
        "Results show reproducible measurements across independent experiments. "
        * 120
    )
    accepted, quality, reason = validate_article_text(text)
    assert accepted
    assert quality in ("medium", "high")
    assert reason is None


def test_text_mode_all_runs_every_strategy(monkeypatch, tmp_path):
    plan = tmp_path / "plan.yaml"
    plan.write_text(
        """
name: unit
discovery:
  - fake_discovery
text:
  mode: all
  cache_successes: false
  strategies:
    - fake_first
    - fake_second
screen: false
""",
        encoding="utf-8",
    )

    monkeypatch.setitem(
        discovery_strategies._DISCOVERY,
        "fake_discovery",
        lambda context, options: [{"doi": "10.1000/x", "title": "X"}],
    )
    calls = []
    monkeypatch.setitem(
        text_strategies._TEXT,
        "fake_first",
        lambda paper, context, options: calls.append("first") or TextAttempt(
            "fake_first", "success", text="a" * 12000, source="one", quality="high"
        ),
    )
    monkeypatch.setitem(
        text_strategies._TEXT,
        "fake_second",
        lambda paper, context, options: calls.append("second") or TextAttempt(
            "fake_second", "success", text="b" * 12000, source="two", quality="high"
        ),
    )

    summary, out = run_plan(plan, 2025, output_dir=tmp_path / "out")
    assert calls == ["first", "second"]
    assert summary["candidates"] == 1
    row = json.loads((out / "results.jsonl").read_text().strip())
    assert len(row["text_attempts"]) == 2


def test_text_mode_first_success_stops(monkeypatch, tmp_path):
    plan = tmp_path / "plan.yaml"
    plan.write_text(
        """
name: unit
discovery:
  - fake_discovery
text:
  mode: first_success
  cache_successes: false
  strategies:
    - fake_first
    - fake_second
screen: false
""",
        encoding="utf-8",
    )

    monkeypatch.setitem(
        discovery_strategies._DISCOVERY,
        "fake_discovery",
        lambda context, options: [{"doi": "10.1000/x"}],
    )
    calls = []
    monkeypatch.setitem(
        text_strategies._TEXT,
        "fake_first",
        lambda paper, context, options: calls.append("first") or TextAttempt(
            "fake_first", "success", text="a" * 12000, source="one", quality="high"
        ),
    )
    monkeypatch.setitem(
        text_strategies._TEXT,
        "fake_second",
        lambda paper, context, options: calls.append("second") or TextAttempt(
            "fake_second", "success", text="b" * 12000, source="two", quality="high"
        ),
    )

    run_plan(plan, 2025, output_dir=tmp_path / "out")
    assert calls == ["first"]


def test_europepmc_registered_strategy_calls_sources(monkeypatch):
    from aic_pubs.config import load
    from aic_pubs.pipeline.types import RunContext

    calls = []
    def fake(year, aliases, grants, **kwargs):
        calls.append((year, tuple(aliases), tuple(grants), kwargs))
        return [{"doi": "10.1000/epmc"}]

    monkeypatch.setattr(
        discovery_strategies.sources,
        "europepmc_ack_search",
        fake,
    )
    context = RunContext(year=2025, cfg=load())
    rows = discovery_strategies.run(
        "europepmc_facility",
        context,
        {"timeout": 12, "max_pages": 3, "page_size": 50},
    )
    assert rows == [{"doi": "10.1000/epmc"}]
    assert calls and calls[0][0] == 2025
    assert calls[0][3] == {
        "timeout": 12,
        "max_pages": 3,
        "page_size": 50,
    }


def test_candidate_merge_preserves_repository_sources():
    from aic_pubs.pipeline.types import CandidateRecord

    record = CandidateRecord("10.1000/x")
    record.merge(
        {"doi": "10.1000/x", "sources": ["utupub"], "title": "X"},
        "institutional",
    )
    record.merge(
        {"doi": "10.1000/x", "sources": ["abo"]},
        "institutional",
    )
    row = record.as_dict()
    assert row["sources"] == ["utupub", "abo"]
    assert row["discovery_sources"] == ["institutional"]


def test_candidate_merge_preserves_explicit_false():
    from aic_pubs.pipeline.types import CandidateRecord

    record = CandidateRecord("10.1000/x")
    record.merge(
        {"doi": "10.1000/x", "expected_funder_verified": False},
        "crossref_awards",
    )
    assert record.as_dict()["expected_funder_verified"] is False


def test_doi_file_strategy_reads_private_csv(tmp_path):
    from aic_pubs.config import load
    from aic_pubs.pipeline.types import RunContext

    path = tmp_path / "cris.csv"
    path.write_text(
        "doi,title,year\n10.1000/a,Paper A,2025\n10.1000/b,Paper B,2025\n",
        encoding="utf-8",
    )
    context = RunContext(year=2025, cfg=load())
    rows = discovery_strategies.run(
        "doi_file",
        context,
        {"path": str(path), "source_name": "utucris_export"},
    )
    assert [row["doi"] for row in rows] == ["10.1000/a", "10.1000/b"]
    assert rows[0]["sources"] == ["utucris_export"]


def test_discovery_yield_is_order_independent():
    from aic_pubs.pipeline.runner import _discovery_yield

    rows = [
        {"doi": "a", "discovery_sources": ["one"]},
        {"doi": "b", "discovery_sources": ["two"]},
        {"doi": "c", "discovery_sources": ["one", "two"]},
    ]
    out = _discovery_yield(rows)
    by = {row["strategy"]: row for row in out["by_strategy"]}
    assert by["one"]["candidates"] == 2
    assert by["one"]["exclusive"] == 1
    assert by["two"]["candidates"] == 2
    assert by["two"]["exclusive"] == 1
    assert out["pairwise_overlap"] == [{"left": "one", "right": "two", "count": 1}]


def test_text_yield_counts_exclusive_successes():
    from aic_pubs.pipeline.runner import _text_yield

    rows = [
        {"text_attempts": [
            {"strategy": "a", "status": "success"},
            {"strategy": "b", "status": "miss"},
        ]},
        {"text_attempts": [
            {"strategy": "a", "status": "success"},
            {"strategy": "b", "status": "success"},
        ]},
    ]
    out = {row["strategy"]: row for row in _text_yield(rows)}
    assert out["a"]["successes"] == 2
    assert out["a"]["exclusive_successes"] == 1
    assert out["b"]["successes"] == 1
    assert out["b"]["exclusive_successes"] == 0
    assert out["a"]["selected"] == 0
    assert out["b"]["selected"] == 0


def test_cache_text_strategy_uses_sidecar(monkeypatch, tmp_path):
    from aic_pubs import sweep
    from aic_pubs.config import load
    from aic_pubs.pipeline.types import RunContext

    monkeypatch.setattr(sweep, "DATA", tmp_path)
    sweep._store(
        2025,
        "10.1000/cache",
        "Methods and results. " * 200,
        "openalex_oa",
        metadata={
            "url": "https://example.org/cache.pdf",
            "license": "cc-by",
            "version": "acceptedVersion",
            "quality": "high",
        },
    )
    context = RunContext(year=2025, cfg=load())
    attempt = text_strategies.run(
        "cache",
        {"doi": "10.1000/cache"},
        context,
    )
    assert attempt.success
    assert attempt.source == "openalex_oa"
    assert attempt.url == "https://example.org/cache.pdf"
    assert attempt.license == "cc-by"
    assert attempt.version == "acceptedVersion"


def test_custom_doi_file_label_survives_merge(tmp_path):
    from aic_pubs.config import load
    from aic_pubs.pipeline.runner import _merge
    from aic_pubs.pipeline.types import RunContext

    path = tmp_path / "cris.csv"
    path.write_text("doi,title,year\n10.1000/x,X,2025\n", encoding="utf-8")
    context = RunContext(year=2025, cfg=load())
    rows = discovery_strategies.run(
        "doi_file",
        context,
        {
            "path": str(path),
            "source_name": "utucris_export",
            "authoritative_year": True,
            "local": True,
        },
    )
    store = {}
    for row in rows:
        _merge(store, row, row.get("discovery_source_label") or "doi_file")
    merged = store["10.1000/x"].as_dict()
    assert merged["discovery_sources"] == ["utucris_export"]
    assert merged["local_candidate"] is True
    assert merged["reporting_year_assertions"] == [
        {"source": "utucris_export", "year": "2025"}
    ]


def test_resume_helpers_require_matching_inputs(tmp_path):
    from aic_pubs.pipeline.runner import _load_partial, _resume_allowed

    out = tmp_path / "run"
    out.mkdir()
    current = {
        "year": 2025,
        "resume_signature": "semantic-plan",
        "facility_config_sha256": "config-a",
        "users_file_sha256": "users-a",
        "source_tree_sha256": "code-a",
    }
    (out / "run_manifest.json").write_text(
        json.dumps(current),
        encoding="utf-8",
    )
    (out / "results.partial.jsonl").write_text(
        json.dumps({"doi": "10.1000/a", "has_text": False}) + "\n"
        + json.dumps({"doi": "10.1000/other", "has_text": False}) + "\n",
        encoding="utf-8",
    )
    assert _resume_allowed(out, current)
    rows = _load_partial(out / "results.partial.jsonl", {"10.1000/a"})
    assert set(rows) == {"10.1000/a"}

    changed_config = {**current, "facility_config_sha256": "config-b"}
    assert not _resume_allowed(out, changed_config)

    changed_users = {**current, "users_file_sha256": "users-b"}
    assert not _resume_allowed(out, changed_users)

    changed_code = {**current, "source_tree_sha256": "code-b"}
    assert not _resume_allowed(out, changed_code)

    changed_plan = {**current, "resume_signature": "other-plan"}
    assert not _resume_allowed(out, changed_plan)


def test_candidate_limit_uses_deterministic_hash_sample():
    from aic_pubs.pipeline.runner import _select_candidates

    rows = [{"doi": f"10.1000/{i:02d}"} for i in range(20)]
    first = _select_candidates(rows, 5)
    second = _select_candidates(list(reversed(rows)), 5)
    assert [r["doi"] for r in first] == [r["doi"] for r in second]
    assert [r["doi"] for r in first] != [r["doi"] for r in rows[:5]]


def test_summary_separates_target_and_adjacent_years(monkeypatch, tmp_path):
    plan = tmp_path / "plan.yaml"
    plan.write_text(
        """
name: years
discovery:
  - fake_years
text:
  mode: first_success
  cache_successes: false
  strategies:
    - metadata_only
screen: false
""",
        encoding="utf-8",
    )
    monkeypatch.setitem(
        discovery_strategies._DISCOVERY,
        "fake_years",
        lambda context, options: [
            {"doi": "10.1000/a", "publication_year": 2025},
            {"doi": "10.1000/b", "publication_year": 2026},
        ],
    )
    summary, _ = run_plan(plan, 2025, output_dir=tmp_path / "out-years")
    assert summary["target_year_candidates"] == 1
    assert summary["adjacent_or_conflicting_year_candidates"] == 1


def test_partial_text_is_not_counted_as_full(monkeypatch, tmp_path):
    plan = tmp_path / "partial.yaml"
    plan.write_text(
        """
name: partial
discovery:
  - fake_partial
text:
  mode: first_success
  cache_successes: false
  strategies:
    - fake_partial_text
screen: false
""",
        encoding="utf-8",
    )
    monkeypatch.setitem(
        discovery_strategies._DISCOVERY,
        "fake_partial",
        lambda context, options: [{"doi": "10.1000/p", "publication_year": 2025}],
    )
    monkeypatch.setitem(
        text_strategies._TEXT,
        "fake_partial_text",
        lambda paper, context, options: TextAttempt(
            "fake_partial_text",
            "success",
            text="article preview " * 1000,
            source="publisher_html",
            quality="low",
            scope="partial",
        ),
    )
    summary, out = run_plan(plan, 2025, output_dir=tmp_path / "partial-out")
    assert summary["with_text"] == 1
    assert summary["with_full_text"] == 0
    assert summary["with_partial_text_only"] == 1
    row = json.loads((out / "results.jsonl").read_text().strip())
    assert row["text_scope"] == "partial"


def test_candidate_merge_keeps_evidence_from_multiple_sources():
    from aic_pubs.pipeline.types import CandidateRecord

    record = CandidateRecord("10.1000/x")
    record.merge(
        {
            "doi": "10.1000/x",
            "matched_award": "359073",
            "expected_funder_verified": True,
        },
        "crossref_awards",
    )
    record.merge(
        {
            "doi": "10.1000/x",
            "matched_query": "Advanced Imaging Core",
        },
        "openalex_facility",
    )
    evidence = record.as_dict()["discovery_evidence"]
    assert any(
        item.get("source") == "crossref_awards"
        and item.get("matched_award") == "359073"
        for item in evidence
    )
    assert any(
        item.get("source") == "openalex_facility"
        and item.get("matched_query") == "Advanced Imaging Core"
        for item in evidence
    )


def test_candidate_without_match_reason_has_no_empty_evidence():
    from aic_pubs.pipeline.types import CandidateRecord

    record = CandidateRecord("10.1000/simple")
    record.merge({"doi": "10.1000/simple", "title": "Simple"}, "institutional")
    assert "discovery_evidence" not in record.as_dict()


def test_continue_mode_marks_run_incomplete(monkeypatch, tmp_path):
    plan = tmp_path / "incomplete.yaml"
    plan.write_text(
        """
name: incomplete
on_error: continue
discovery:
  - broken_discovery
  - good_discovery
text:
  mode: first_success
  cache_successes: false
  strategies:
    - metadata_only
screen: false
""",
        encoding="utf-8",
    )
    monkeypatch.setitem(
        discovery_strategies._DISCOVERY,
        "broken_discovery",
        lambda context, options: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    monkeypatch.setitem(
        discovery_strategies._DISCOVERY,
        "good_discovery",
        lambda context, options: [{"doi": "10.1000/x", "publication_year": 2025}],
    )
    summary, out = run_plan(plan, 2025, output_dir=tmp_path / "incomplete-out")
    assert summary["incomplete_run"] is True
    assert summary["discovery_errors"][0]["strategy"] == "broken_discovery"
    manifest = json.loads((out / "run_manifest.json").read_text())
    assert manifest["incomplete_run"] is True


def test_first_success_continues_past_partial_text(monkeypatch, tmp_path):
    plan = tmp_path / "partial-then-full.yaml"
    plan.write_text(
        """
name: partial_then_full
discovery:
  - fake_discovery
text:
  mode: first_success
  cache_successes: false
  strategies:
    - fake_partial
    - fake_full
screen: false
""",
        encoding="utf-8",
    )
    monkeypatch.setitem(
        discovery_strategies._DISCOVERY,
        "fake_discovery",
        lambda context, options: [{"doi": "10.1000/x", "publication_year": 2025}],
    )
    calls = []
    monkeypatch.setitem(
        text_strategies._TEXT,
        "fake_partial",
        lambda paper, context, options: calls.append("partial") or TextAttempt(
            "fake_partial",
            "success",
            text="partial " * 400,
            source="publisher_html",
            quality="low",
            scope="partial",
        ),
    )
    monkeypatch.setitem(
        text_strategies._TEXT,
        "fake_full",
        lambda paper, context, options: calls.append("full") or TextAttempt(
            "fake_full",
            "success",
            text="full article " * 1000,
            source="europepmc",
            quality="high",
            scope="full",
        ),
    )
    summary, out = run_plan(plan, 2025, output_dir=tmp_path / "out-partial-full")
    assert calls == ["partial", "full"]
    row = json.loads((out / "results.jsonl").read_text().strip())
    assert row["text_source"] == "europepmc"
    assert row["text_scope"] == "full"
    assert summary["with_full_text"] == 1


def test_review_csv_contains_only_review_candidates(tmp_path):
    from aic_pubs.pipeline.runner import _write_review_csv

    rows = [
        {
            "doi": "10.1000/a",
            "title": "A",
            "review_disposition": "known_user_microscopy",
            "score": 7,
            "discovery_sources": ["institutional", "known_users_orcid"],
            "evidence": ["Microscopy evidence sentence."],
        },
        {
            "doi": "10.1000/b",
            "title": "B",
            "review_disposition": None,
            "score": 0,
        },
    ]
    path = tmp_path / "review.csv"
    count = _write_review_csv(rows, path)
    text = path.read_text(encoding="utf-8")
    assert count == 1
    assert "10.1000/a" in text
    assert "10.1000/b" not in text
    assert "known_user_microscopy" in text


def test_metadata_precedence_is_independent_of_strategy_order():
    from aic_pubs.pipeline.types import CandidateRecord

    weak = {
        "doi": "10.1000/x",
        "title": "External title",
        "journal": "External journal",
        "publication_year": 2025,
    }
    strong = {
        "doi": "10.1000/x",
        "title": "Institutional title",
        "journal": "Institutional journal",
        "year": 2026,
        "sources": ["abo"],
    }

    first = CandidateRecord("10.1000/x")
    first.merge(weak, "openalex_facility")
    first.merge(strong, "institutional")

    second = CandidateRecord("10.1000/x")
    second.merge(strong, "institutional")
    second.merge(weak, "openalex_facility")

    a = first.as_dict()
    b = second.as_dict()
    assert a["title"] == b["title"] == "Institutional title"
    assert a["journal"] == b["journal"] == "Institutional journal"
    assert a["metadata_sources"]["title"]["source"] == "institutional"
    assert b["metadata_sources"]["title"]["source"] == "institutional"


def test_legacy_unknown_cache_is_not_assumed_full(monkeypatch, tmp_path):
    from aic_pubs import sweep
    from aic_pubs.config import load
    from aic_pubs.pipeline.types import RunContext

    monkeypatch.setattr(sweep, "DATA", tmp_path)
    path = sweep._cache_path(2025, "10.1000/legacy-unknown")
    path.parent.mkdir(parents=True, exist_ok=True)
    import gzip
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        handle.write("publisher_html\n" + ("article preview " * 300))
    context = RunContext(year=2025, cfg=load())
    attempt = text_strategies.run(
        "cache",
        {"doi": "10.1000/legacy-unknown"},
        context,
    )
    assert attempt.success
    assert attempt.scope == "partial"


def test_known_user_strategy_deduplicates_orcids(monkeypatch):
    from aic_pubs.config import load
    from aic_pubs.pipeline.types import RunContext

    calls = []
    monkeypatch.setattr(
        discovery_strategies.discovery,
        "openalex_author_works",
        lambda orcid, from_year, to_year, api_key=None, per_page=100,
               timeout=45, max_pages=20: calls.append(orcid) or [{
            "doi": "10.1000/x"
        }],
    )
    context = RunContext(
        year=2025,
        cfg=load(),
        users=(
            UserIdentity("One", "A", "0000-0001-0000-0001"),
            UserIdentity("Duplicate", "B", "0000-0001-0000-0001"),
        ),
    )
    rows = discovery_strategies.run(
        "known_users_orcid",
        context,
        {"year_pad": 0},
    )
    assert calls == ["0000-0001-0000-0001"]
    assert len(rows) == 1
    assert rows[0]["known_aic_user"] is True


def test_discovery_yield_reports_downstream_value():
    from aic_pubs.pipeline.runner import _discovery_yield

    rows = [
        {
            "doi": "10.1000/a",
            "discovery_sources": ["institutional"],
            "has_text": True,
            "microscopy_terms": 8,
            "category": "B",
            "review_disposition": "lead_b",
            "reporting_year_matches_target": True,
        },
        {
            "doi": "10.1000/b",
            "discovery_sources": ["known_users_orcid"],
            "has_text": True,
            "microscopy_terms": 6,
            "category": "F",
            "review_disposition": "known_user_microscopy",
            "reporting_year_matches_target": True,
        },
    ]
    out = _discovery_yield(rows)
    by = {row["strategy"]: row for row in out["by_strategy"]}
    assert by["institutional"]["aic_leads"] == 1
    assert by["institutional"]["exclusive_aic_leads"] == 1
    assert by["known_users_orcid"]["microscopy"] == 1
    assert by["known_users_orcid"]["review_candidates"] == 1
    assert by["known_users_orcid"]["exclusive_microscopy"] == 1


def test_text_yield_reports_selected_resolver_outcome():
    from aic_pubs.pipeline.runner import _text_yield

    rows = [{
        "text_strategy": "europepmc",
        "microscopy_terms": 7,
        "category": "A",
        "text_attempts": [
            {"strategy": "publisher_html", "status": "success"},
            {"strategy": "europepmc", "status": "success"},
        ],
    }]
    out = {row["strategy"]: row for row in _text_yield(rows)}
    assert out["europepmc"]["selected"] == 1
    assert out["europepmc"]["selected_microscopy"] == 1
    assert out["europepmc"]["selected_aic_leads"] == 1
    assert out["publisher_html"]["selected"] == 0


def test_truncated_discovery_marks_run_incomplete(monkeypatch, tmp_path):
    plan = tmp_path / "truncated.yaml"
    plan.write_text(
        """
name: truncated
on_error: continue
discovery:
  - truncated_discovery
text:
  mode: first_success
  cache_successes: false
  strategies:
    - metadata_only
screen: false
""",
        encoding="utf-8",
    )
    monkeypatch.setitem(
        discovery_strategies._DISCOVERY,
        "truncated_discovery",
        lambda context, options: [{
            "doi": "10.1000/x",
            "publication_year": 2025,
            "discovery_truncated": True,
        }],
    )
    summary, _ = run_plan(plan, 2025, output_dir=tmp_path / "out")
    assert summary["incomplete_run"] is True
    assert summary["discovery_truncations"] == ["truncated_discovery"]


def test_unknown_strategy_fails_before_continue_mode(monkeypatch, tmp_path):
    plan = tmp_path / "bad.yaml"
    plan.write_text(
        """
name: bad
on_error: continue
discovery:
  - typo_discovery
text:
  mode: first_success
  cache_successes: false
  strategies:
    - metadata_only
screen: false
""",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="unknown discovery strategies"):
        run_plan(plan, 2025, output_dir=tmp_path / "out")


def test_unknown_text_strategy_fails_before_discovery(monkeypatch, tmp_path):
    plan = tmp_path / "bad-text.yaml"
    plan.write_text(
        """
name: bad_text
on_error: continue
discovery:
  - institutional
text:
  mode: first_success
  cache_successes: false
  strategies:
    - typo_text
screen: false
""",
        encoding="utf-8",
    )
    called = []
    monkeypatch.setitem(
        discovery_strategies._DISCOVERY,
        "institutional",
        lambda context, options: called.append(True) or [],
    )
    with pytest.raises(ValueError, match="unknown text strategies"):
        run_plan(plan, 2025, output_dir=tmp_path / "out")
    assert called == []


def test_local_initial_match_stays_ambiguous():
    from aic_pubs.pipeline.runner import _annotate_users
    from aic_pubs.pipeline.types import CandidateRecord

    papers = {"10.1000/x": CandidateRecord("10.1000/x")}
    papers["10.1000/x"].data["local_authors"] = ["Example, E"]
    users = (UserIdentity("Erik Example", "Abo Akademi University"),)

    _annotate_users(papers, users)
    row = papers["10.1000/x"].as_dict()
    assert row.get("known_aic_user") is not True
    assert row["known_aic_user_ambiguous"] is True
    assert row["known_aic_user_match"] == "initial_only"


def test_local_exact_match_is_confirmed_user_annotation():
    from aic_pubs.pipeline.runner import _annotate_users
    from aic_pubs.pipeline.types import CandidateRecord

    papers = {"10.1000/x": CandidateRecord("10.1000/x")}
    papers["10.1000/x"].data["local_authors"] = ["Example, Erik"]
    users = (UserIdentity("Erik Example", "Abo Akademi University"),)

    _annotate_users(papers, users)
    row = papers["10.1000/x"].as_dict()
    assert row["known_aic_user"] is True
    assert row["known_aic_user_match"] == "exact_name"


def test_prefer_high_quality_continues_past_medium_full(monkeypatch, tmp_path):
    plan = tmp_path / "upgrade.yaml"
    plan.write_text(
        """
name: upgrade
discovery:
  - fake_discovery
text:
  mode: first_success
  prefer_quality: high
  cache_successes: false
  strategies:
    - fake_medium
    - fake_high
screen: false
""",
        encoding="utf-8",
    )
    monkeypatch.setitem(
        discovery_strategies._DISCOVERY,
        "fake_discovery",
        lambda context, options: [{"doi": "10.1000/x", "publication_year": 2025}],
    )
    calls = []
    monkeypatch.setitem(
        text_strategies._TEXT,
        "fake_medium",
        lambda paper, context, options: calls.append("medium") or TextAttempt(
            "fake_medium", "success",
            text="medium article " * 1000,
            source="crossref_fulltext",
            quality="medium",
            scope="full",
        ),
    )
    monkeypatch.setitem(
        text_strategies._TEXT,
        "fake_high",
        lambda paper, context, options: calls.append("high") or TextAttempt(
            "fake_high", "success",
            text="high article " * 1000,
            source="europepmc",
            quality="high",
            scope="full",
        ),
    )
    _, out = run_plan(plan, 2025, output_dir=tmp_path / "upgrade-out")
    row = json.loads((out / "results.jsonl").read_text().strip())
    assert calls == ["medium", "high"]
    assert row["text_strategy"] == "fake_high"
    assert row["text_quality"] == "high"


def test_baseline_first_success_stops_at_medium_full(monkeypatch, tmp_path):
    plan = tmp_path / "fast.yaml"
    plan.write_text(
        """
name: fast
discovery:
  - fake_discovery
text:
  mode: first_success
  cache_successes: false
  strategies:
    - fake_medium
    - fake_high
screen: false
""",
        encoding="utf-8",
    )
    monkeypatch.setitem(
        discovery_strategies._DISCOVERY,
        "fake_discovery",
        lambda context, options: [{"doi": "10.1000/x", "publication_year": 2025}],
    )
    calls = []
    monkeypatch.setitem(
        text_strategies._TEXT,
        "fake_medium",
        lambda paper, context, options: calls.append("medium") or TextAttempt(
            "fake_medium", "success",
            text="medium article " * 1000,
            source="crossref_fulltext",
            quality="medium",
            scope="full",
        ),
    )
    monkeypatch.setitem(
        text_strategies._TEXT,
        "fake_high",
        lambda paper, context, options: calls.append("high") or TextAttempt(
            "fake_high", "success",
            text="high article " * 1000,
            source="europepmc",
            quality="high",
            scope="full",
        ),
    )
    run_plan(plan, 2025, output_dir=tmp_path / "fast-out")
    assert calls == ["medium"]


def test_source_health_preserves_failure_reasons():
    from aic_pubs.pipeline.runner import _source_health

    rows = [{
        "text_attempts": [
            {"strategy": "publisher_html", "status": "rejected", "reason": "access_page"},
            {"strategy": "openalex_oa", "status": "miss", "reason": "http_403"},
        ]
    }]
    health = {row["strategy"]: row for row in _source_health(rows)}
    assert health["publisher_html"]["rejected"] == 1
    assert health["publisher_html"]["reasons"] == [{"reason": "access_page", "count": 1}]
    assert health["openalex_oa"]["miss"] == 1
    assert health["openalex_oa"]["reasons"] == [{"reason": "http_403", "count": 1}]


def test_legacy_crossref_cache_is_not_assumed_full(monkeypatch, tmp_path):
    from aic_pubs import sweep
    from aic_pubs.config import load
    from aic_pubs.pipeline.types import RunContext
    import gzip

    monkeypatch.setattr(sweep, "DATA", tmp_path)
    path = sweep._cache_path(2025, "10.1000/crossref-legacy")
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        handle.write("crossref_fulltext\n" + ("article body " * 500))
    attempt = text_strategies.run(
        "cache",
        {"doi": "10.1000/crossref-legacy"},
        RunContext(year=2025, cfg=load()),
    )
    assert attempt.success
    assert attempt.scope == "partial"


def test_crossref_html_is_partial(monkeypatch):
    from aic_pubs.config import load
    from aic_pubs.pipeline.types import RunContext

    monkeypatch.setattr(
        text_strategies,
        "crossref_text_links",
        lambda doi: [{
            "url": "https://example.org/article",
            "content_type": "text/html",
        }],
    )
    class Result:
        text = "article body " * 500
        final_url = "https://example.org/article"
        reason = None
    monkeypatch.setattr(text_strategies, "download_text", lambda url: Result())
    attempt = text_strategies.run(
        "crossref_fulltext",
        {"doi": "10.1000/x"},
        RunContext(year=2025, cfg=load()),
    )
    assert attempt.success
    assert attempt.scope == "partial"
    assert attempt.quality == "low"


def test_known_user_strategy_can_filter_openalex_work_types(monkeypatch):
    from aic_pubs.config import load
    from aic_pubs.pipeline.types import RunContext

    monkeypatch.setattr(
        discovery_strategies.discovery,
        "openalex_author_works",
        lambda *args, **kwargs: [
            {"doi": "10.1000/article", "openalex_type": "article"},
            {"doi": "10.1000/preprint", "openalex_type": "preprint"},
            {"doi": "10.1000/retracted", "openalex_type": "article", "is_retracted": True},
        ],
    )
    context = RunContext(
        year=2025,
        cfg=load(),
        users=(UserIdentity("User", "A", "0000-0001-0000-0001"),),
    )
    rows = discovery_strategies.run(
        "known_users_orcid",
        context,
        {
            "year_pad": 0,
            "include_types": ["article"],
            "exclude_retracted": True,
        },
    )
    assert [row["doi"] for row in rows] == ["10.1000/article"]


def test_new_strategy_plans_load():
    for name in ("quality_upgrade", "user_articles_only", "user_smoke"):
        plan = load_plan(f"config/plans/{name}.yaml")
        assert plan["discovery"]
        assert plan["text"]["strategies"]
