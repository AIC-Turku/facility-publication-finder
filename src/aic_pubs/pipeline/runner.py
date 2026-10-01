"""Execute configurable discovery -> text -> screening plans."""
from __future__ import annotations

import csv
import hashlib
import json
import os
import platform
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from . import discovery_strategies, text_strategies
from .plan import load_plan
from .types import CandidateRecord, RunContext, TextAttempt
from ..bookings import load_bookings, load_staff
from ..config import load
from ..identity import load_users, paper_user_match_strength
from ..screen import screen
from ..sources import _norm_doi
from ..sweep import DATA, _store, acknowledging_authors
from ..years import normalize_years


QUALITY = {None: 0, "low": 1, "medium": 2, "high": 3}
SCOPE = {None: 1, "partial": 1, "full": 2}


def _sha256_bytes(value):
    return hashlib.sha256(value).hexdigest()


def _json_hash(value):
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return _sha256_bytes(payload.encode("utf-8"))


def _resume_signature(plan):
    semantic = dict(plan)
    semantic.pop("workers", None)
    semantic.pop("resume", None)
    return _json_hash(semantic)


def _source_tree_hash():
    src_root = Path(__file__).resolve().parents[1]
    digest = hashlib.sha256()
    for path in sorted(src_root.rglob("*.py")):
        digest.update(str(path.relative_to(src_root)).encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _run_manifest(plan, cfg, year, users_path):
    from ..config import config_path as _facility_config
    config_path = _facility_config()
    config_bytes = config_path.read_bytes() if config_path.exists() else b""
    user_file_hash = None
    if users_path:
        user_path = Path(users_path)
        if user_path.exists():
            user_file_hash = _sha256_bytes(user_path.read_bytes())
    return {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "year": int(year),
        "plan_name": plan["name"],
        "plan_sha256": _json_hash(plan),
        "resume_signature": _resume_signature(plan),
        "facility_config_sha256": _sha256_bytes(config_bytes),
        "users_file_sha256": user_file_hash,
        "source_tree_sha256": _source_tree_hash(),
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "github_sha": os.getenv("GITHUB_SHA"),
        "strategies": {
            "discovery": [step["strategy"] for step in plan["discovery"]],
            "text": [step["strategy"] for step in plan["text"]["strategies"]],
        },
    }


def _merge(store, row, source):
    doi = _norm_doi(row.get("doi"))
    if not doi:
        return
    record = store.setdefault(doi, CandidateRecord(doi))
    record.merge(row, source)


def _annotate_users(papers, users):
    if not users:
        return
    for record in papers.values():
        row = record.as_dict()
        strengths = {
            paper_user_match_strength(row, user)
            for user in users
        }
        if "exact" in strengths:
            record.data["known_aic_user"] = True
            record.data["known_aic_user_match"] = "exact_name"
        elif "initial" in strengths:
            record.data["known_aic_user_ambiguous"] = True
            record.data["known_aic_user_match"] = "initial_only"


def _review_disposition(row):
    category = row.get("category") or ""
    if category and category in set("ABCDE"):
        return f"lead_{category.lower()}"
    if row.get("known_aic_user") and not row.get("has_text"):
        return "known_user_no_text"
    if row.get("text_scope") == "partial" and not (
        (row.get("category") or None) in set("ABCDE")
    ):
        return "partial_text_review"
    if row.get("known_aic_user") and (row.get("microscopy_terms") or 0) >= 5:
        if row.get("credited_elsewhere") or row.get("instrument_named_elsewhere"):
            return "known_user_microscopy_ambiguous"
        return "known_user_microscopy"
    if row.get("known_aic_user_ambiguous") and (row.get("microscopy_terms") or 0) >= 5:
        return "possible_user_identity_microscopy"
    return None


def _attempt_dict(attempt):
    return {
        "strategy": attempt.strategy,
        "status": attempt.status,
        "source": attempt.source,
        "url": attempt.url,
        "license": attempt.license,
        "version": attempt.version,
        "quality": attempt.quality,
        "scope": attempt.scope,
        "reason": attempt.reason,
    }


def _recover_text(paper, context, text_plan, on_error="fail"):
    attempts = []
    best = None
    for step in text_plan["strategies"]:
        try:
            attempt = text_strategies.run(
                step["strategy"],
                paper,
                context,
                step["options"],
            )
        except Exception as exc:
            if on_error == "fail":
                raise
            attempt = TextAttempt(
                strategy=step["strategy"],
                status="error",
                reason=f"{type(exc).__name__}: {exc}",
            )
        attempts.append(attempt)
        if attempt.success:
            attempt_rank = (
                SCOPE.get(attempt.scope, 0),
                QUALITY.get(attempt.quality, 0),
            )
            best_rank = (
                SCOPE.get(best.scope, 0),
                QUALITY.get(best.quality, 0),
            ) if best else (-1, -1)
            if best is None or attempt_rank > best_rank:
                best = attempt

        if attempt.success and text_plan["mode"] == "first_success" and attempt.scope != "partial":
            preferred = text_plan.get("prefer_quality")
            if not preferred or QUALITY.get(attempt.quality, 0) >= QUALITY.get(preferred, 0):
                break
    return best, attempts


def _discovery_yield(rows):
    counts = Counter()
    exclusive = Counter()
    with_text = Counter()
    microscopy = Counter()
    aic_leads = Counter()
    review = Counter()
    exclusive_microscopy = Counter()
    exclusive_aic_leads = Counter()
    target_year = Counter()
    pairs = Counter()

    for row in rows:
        sources = sorted(set(row.get("discovery_sources") or []))
        is_microscopy = (row.get("microscopy_terms") or 0) >= 5
        is_aic_lead = (row.get("category") or None) in set("ABCDE")
        is_review = bool(row.get("review_disposition"))
        is_target = row.get("reporting_year_matches_target") is True

        for source in sources:
            counts[source] += 1
            if row.get("has_text"):
                with_text[source] += 1
            if is_microscopy:
                microscopy[source] += 1
            if is_aic_lead:
                aic_leads[source] += 1
            if is_review:
                review[source] += 1
            if is_target:
                target_year[source] += 1

        if len(sources) == 1:
            source = sources[0]
            exclusive[source] += 1
            if is_microscopy:
                exclusive_microscopy[source] += 1
            if is_aic_lead:
                exclusive_aic_leads[source] += 1

        for i, left in enumerate(sources):
            for right in sources[i + 1:]:
                pairs[(left, right)] += 1

    return {
        "by_strategy": [
            {
                "strategy": source,
                "candidates": counts[source],
                "exclusive": exclusive[source],
                "target_year": target_year[source],
                "with_text": with_text[source],
                "microscopy": microscopy[source],
                "aic_leads": aic_leads[source],
                "review_candidates": review[source],
                "exclusive_microscopy": exclusive_microscopy[source],
                "exclusive_aic_leads": exclusive_aic_leads[source],
            }
            for source in sorted(counts)
        ],
        "pairwise_overlap": [
            {"left": left, "right": right, "count": count}
            for (left, right), count in sorted(pairs.items())
        ],
    }


def _csv_value(value):
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return value


def _write_review_csv(rows, path):
    fields = (
        "doi", "title", "journal", "reporting_year", "reporting_year_source",
        "reporting_year_provisional", "year_disagreement", "reporting_year_conflict",
        "known_aic_user", "known_aic_user_ambiguous", "known_aic_user_match",
        "discovery_sources", "discovery_evidence",
        "text_source", "text_strategy", "text_scope", "text_quality", "text_url",
        "category", "review_disposition", "priority", "score",
        "instruments_strong", "techniques_specialist", "acknowledgement",
        "credited_elsewhere", "instrument_named_elsewhere", "evidence",
    )
    review = [row for row in rows if row.get("review_disposition")]
    review.sort(
        key=lambda row: (
            row.get("review_disposition") or "",
            -(row.get("score") or 0),
            row.get("doi") or "",
        )
    )
    with Path(path).open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in review:
            writer.writerow({
                field: _csv_value(row.get(field))
                for field in fields
            })
    return len(review)


def _text_yield(rows):
    success = Counter()
    exclusive = Counter()
    selected = Counter()
    selected_microscopy = Counter()
    selected_aic_leads = Counter()
    rejected = Counter()
    errors = Counter()

    for row in rows:
        attempts = row.get("text_attempts") or []
        successful = [
            attempt["strategy"]
            for attempt in attempts
            if attempt.get("status") == "success"
        ]
        for strategy in successful:
            success[strategy] += 1
        if len(successful) == 1:
            exclusive[successful[0]] += 1

        chosen = row.get("text_strategy")
        if chosen:
            selected[chosen] += 1
            if (row.get("microscopy_terms") or 0) >= 5:
                selected_microscopy[chosen] += 1
            if (row.get("category") or None) in set("ABCDE"):
                selected_aic_leads[chosen] += 1

        for attempt in attempts:
            if attempt.get("status") == "rejected":
                rejected[attempt["strategy"]] += 1
            elif attempt.get("status") == "error":
                errors[attempt["strategy"]] += 1

    strategies = sorted(
        set(success) | set(selected) | set(rejected) | set(errors)
    )
    return [
        {
            "strategy": strategy,
            "successes": success[strategy],
            "exclusive_successes": exclusive[strategy],
            "selected": selected[strategy],
            "selected_microscopy": selected_microscopy[strategy],
            "selected_aic_leads": selected_aic_leads[strategy],
            "rejected": rejected[strategy],
            "errors": errors[strategy],
        }
        for strategy in strategies
    ]


def _source_health(rows):
    """Aggregate resolver outcomes and reasons for operational diagnostics."""
    by_strategy = {}
    for row in rows:
        for attempt in row.get("text_attempts") or []:
            strategy = attempt.get("strategy") or "unknown"
            entry = by_strategy.setdefault(
                strategy,
                {
                    "attempted": 0,
                    "success": 0,
                    "miss": 0,
                    "rejected": 0,
                    "error": 0,
                    "reasons": Counter(),
                },
            )
            entry["attempted"] += 1
            status = attempt.get("status") or "miss"
            if status in ("success", "miss", "rejected", "error"):
                entry[status] += 1
            reason = attempt.get("reason")
            if reason:
                entry["reasons"][reason] += 1

    out = []
    for strategy in sorted(by_strategy):
        entry = by_strategy[strategy]
        out.append({
            "strategy": strategy,
            "attempted": entry["attempted"],
            "success": entry["success"],
            "miss": entry["miss"],
            "rejected": entry["rejected"],
            "error": entry["error"],
            "success_rate": (
                round(entry["success"] / entry["attempted"], 4)
                if entry["attempted"] else 0.0
            ),
            "reasons": [
                {"reason": reason, "count": count}
                for reason, count in sorted(
                    entry["reasons"].items(),
                    key=lambda item: (-item[1], item[0]),
                )
            ],
        })
    return out


def _doi_set_hash(rows):
    dois = sorted({row.get("doi") for row in rows if row.get("doi")})
    return _sha256_bytes("\n".join(dois).encode("utf-8"))


def _select_candidates(rows, limit, seed="aic-pubs"):
    """Deterministic hash sample; avoids alphabetical DOI bias."""
    if limit is None or limit >= len(rows):
        return list(rows)
    ranked = sorted(
        rows,
        key=lambda row: hashlib.sha256(
            f"{seed}|{row.get('doi', '')}".encode("utf-8")
        ).hexdigest(),
    )
    return ranked[:limit]


def _load_partial(path, allowed_dois):
    rows = {}
    if not path.exists():
        return rows
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except ValueError:
            continue
        doi = row.get("doi")
        if doi in allowed_dois:
            rows[doi] = row
    return rows


def _resume_allowed(out_dir, current_manifest):
    manifest_path = out_dir / "run_manifest.json"
    partial_path = out_dir / "results.partial.jsonl"
    if not manifest_path.exists() or not partial_path.exists():
        return False
    try:
        previous = json.loads(manifest_path.read_text(encoding="utf-8"))
    except ValueError:
        return False

    keys = (
        "year",
        "resume_signature",
        "facility_config_sha256",
        "users_file_sha256",
        "source_tree_sha256",
    )
    return all(previous.get(key) == current_manifest.get(key) for key in keys)


def _validate_registered_strategies(plan):
    discovery_available = set(discovery_strategies.names())
    text_available = set(text_strategies.names())

    unknown_discovery = [
        step["strategy"]
        for step in plan["discovery"]
        if step["strategy"] not in discovery_available
    ]
    unknown_text = [
        step["strategy"]
        for step in plan["text"]["strategies"]
        if step["strategy"] not in text_available
    ]
    if unknown_discovery or unknown_text:
        parts = []
        if unknown_discovery:
            parts.append(
                "unknown discovery strategies: " + ", ".join(sorted(set(unknown_discovery)))
            )
        if unknown_text:
            parts.append(
                "unknown text strategies: " + ", ".join(sorted(set(unknown_text)))
            )
        raise ValueError("; ".join(parts))


def run_plan(plan_path, year, *, users_path=None, openalex_api_key=None,
             crossref_mailto=None, limit=None, output_dir=None):
    """Execute a YAML plan and return (summary, output directory)."""
    plan = load_plan(plan_path)
    _validate_registered_strategies(plan)
    cfg = load()
    users = tuple(load_users(users_path)) if users_path else ()
    context = RunContext(
        year=year,
        cfg=cfg,
        users=users,
        openalex_api_key=openalex_api_key,
        crossref_mailto=crossref_mailto,
    )
    screen_context = {
        "history": acknowledging_authors(exclude_year=year),
        "bookings": load_bookings(),
        "staff": load_staff(),
    }

    papers = {}
    discovery_metrics = []
    started = time.monotonic()

    for step in plan["discovery"]:
        t0 = time.monotonic()
        try:
            rows = discovery_strategies.run(
                step["strategy"],
                context,
                step["options"],
            )
            error = None
        except Exception as exc:
            if plan["on_error"] == "fail":
                raise
            rows = []
            error = f"{type(exc).__name__}: {exc}"
        before = len(papers)
        for row in rows:
            source_label = row.get("discovery_source_label") or step["strategy"]
            _merge(papers, row, source_label)
        discovery_metrics.append({
            "strategy": step["strategy"],
            "returned": len(rows),
            "unique_added": len(papers) - before,
            "truncated": any(bool(row.get("discovery_truncated")) for row in rows),
            "error": error,
            "seconds": round(time.monotonic() - t0, 3),
        })

    _annotate_users(papers, users)
    ordered = [record.as_dict() for _, record in sorted(papers.items())]
    ordered = _select_candidates(ordered, limit)

    out_dir = Path(output_dir or DATA / str(year) / "experiments" / plan["name"])
    out_dir.mkdir(parents=True, exist_ok=True)
    rows_path = out_dir / "results.jsonl"
    partial_path = out_dir / "results.partial.jsonl"

    manifest = _run_manifest(plan, cfg, year, users_path)
    manifest["discovered_candidate_count"] = len(papers)
    manifest["discovered_doi_set_sha256"] = _doi_set_hash(
        [record.as_dict() for record in papers.values()]
    )
    manifest["selected_candidate_count"] = len(ordered)
    manifest["selected_doi_set_sha256"] = _doi_set_hash(ordered)
    manifest_path = out_dir / "run_manifest.json"

    allowed_dois = {row["doi"] for row in ordered}
    resumed = {}
    if plan["resume"] and _resume_allowed(out_dir, manifest):
        resumed = _load_partial(partial_path, allowed_dois)
    else:
        partial_path.write_text("", encoding="utf-8")

    manifest["resumed_rows"] = len(resumed)
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    pending = [row for row in ordered if row["doi"] not in resumed]

    def process_one(paper):
        best, attempts = _recover_text(
            paper,
            context,
            plan["text"],
            on_error=plan["on_error"],
        )

        row = dict(paper)
        row.update(normalize_years(row, year))
        row["text_attempts"] = [_attempt_dict(attempt) for attempt in attempts]

        text = best.text if best else None
        if best:
            row.update({
                "text_source": best.source,
                "text_strategy": best.strategy,
                "text_url": best.url,
                "text_license": best.license,
                "text_version": best.version,
                "text_quality": best.quality,
                "text_scope": best.scope,
            })
            if plan["text"]["cache_successes"]:
                _store(
                    year,
                    row["doi"],
                    best.text,
                    best.source,
                    metadata={
                        "url": best.url,
                        "license": best.license,
                        "version": best.version,
                        "quality": best.quality,
                        "scope": best.scope,
                        "strategy": best.strategy,
                    },
                )

        if plan["screen"]:
            local = bool(row.get("local_candidate")) or bool(
                {"institutional", "utupub", "abo", "utucris_export", "abocris_export"}
                & set(row.get("discovery_sources") or [])
            )
            row.update(screen(text, cfg, local=local, meta={**row, **screen_context}))
        else:
            row["has_text"] = bool(text)

        row["review_disposition"] = _review_disposition(row) if plan["screen"] else None
        return row, attempts

    results_by_doi = dict(resumed)
    text_metrics = Counter()
    with partial_path.open("a", encoding="utf-8") as checkpoint:
        with ThreadPoolExecutor(max_workers=plan["workers"]) as pool:
            for row, attempts in pool.map(process_one, pending):
                for attempt in attempts:
                    text_metrics[(attempt.strategy, attempt.status)] += 1
                results_by_doi[row["doi"]] = row
                checkpoint.write(json.dumps(row, ensure_ascii=False) + "\n")
                checkpoint.flush()

    results = [
        results_by_doi[row["doi"]]
        for row in ordered
        if row["doi"] in results_by_doi
    ]
    with rows_path.open("w", encoding="utf-8") as handle:
        for row in results:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    review_count = _write_review_csv(results, out_dir / "review.csv")
    partial_path.unlink(missing_ok=True)

    # Recompute attempt metrics from all final rows so resumed rows are included.
    text_metrics = Counter()
    for row in results:
        for attempt in row.get("text_attempts") or []:
            text_metrics[(attempt.get("strategy"), attempt.get("status"))] += 1

    discovery_yield = _discovery_yield(results)
    text_yield = _text_yield(results)
    source_health = _source_health(results)

    target_rows = [r for r in results if r.get("reporting_year_matches_target") is True]
    provisional_rows = [
        r for r in results
        if r.get("reporting_year_provisional") and r.get("reporting_year_matches_target") is not False
    ]
    adjacent_rows = [r for r in results if r.get("reporting_year_matches_target") is False]

    discovery_errors = [
        {"strategy": item["strategy"], "error": item["error"]}
        for item in discovery_metrics
        if item.get("error")
    ]
    discovery_truncations = [
        item["strategy"]
        for item in discovery_metrics
        if item.get("truncated")
    ]
    text_error_count = sum(
        count
        for (strategy, status), count in text_metrics.items()
        if status == "error"
    )
    incomplete_run = bool(
        discovery_errors or discovery_truncations or text_error_count
    )

    summary = {
        "plan": plan["name"],
        "incomplete_run": incomplete_run,
        "discovery_errors": discovery_errors,
        "discovery_truncations": discovery_truncations,
        "text_error_count": text_error_count,
        "year": year,
        "candidates": len(results),
        "target_year_candidates": len(target_rows),
        "provisional_target_year_candidates": len(provisional_rows),
        "adjacent_or_conflicting_year_candidates": len(adjacent_rows),
        "known_user_candidates": sum(bool(r.get("known_aic_user")) for r in results),
        "ambiguous_known_user_candidates": sum(
            bool(r.get("known_aic_user_ambiguous")) for r in results
        ),
        "with_text": sum(bool(r.get("has_text")) for r in results),
        "with_full_text": sum(
            bool(r.get("has_text")) and r.get("text_scope") == "full" for r in results
        ),
        "with_partial_text_only": sum(
            bool(r.get("has_text")) and r.get("text_scope") == "partial" for r in results
        ),
        "microscopy": sum((r.get("microscopy_terms") or 0) >= 5 for r in results),
        "target_year_microscopy": sum(
            (r.get("microscopy_terms") or 0) >= 5 for r in target_rows
        ),
        "aic_leads": sum((r.get("category") or None) in set("ABCDE") for r in results),
        "target_year_aic_leads": sum(
            (r.get("category") or None) in set("ABCDE") for r in target_rows
        ),
        "review_candidates": review_count,
        "review_dispositions": dict(sorted(Counter(
            r.get("review_disposition")
            for r in results
            if r.get("review_disposition")
        ).items())),
        "known_user_microscopy_review": sum(
            (r.get("review_disposition") or "").startswith("known_user_microscopy")
            for r in results
        ),
        "known_user_no_text": sum(
            r.get("review_disposition") == "known_user_no_text" for r in results
        ),
        "discovery": discovery_metrics,
        "discovery_yield": discovery_yield,
        "text_strategy_yield": text_yield,
        "source_health": source_health,
        "text_attempts": [
            {"strategy": strategy, "status": status, "count": count}
            for (strategy, status), count in sorted(text_metrics.items())
        ],
        "seconds": round(time.monotonic() - started, 3),
    }
    (out_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    (out_dir / "plan.json").write_text(
        json.dumps(plan, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    manifest["summary_sha256"] = _json_hash(summary)
    manifest["incomplete_run"] = incomplete_run
    manifest["completed_rows"] = len(results)
    manifest["completed_at_utc"] = datetime.now(timezone.utc).isoformat()
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return summary, out_dir
