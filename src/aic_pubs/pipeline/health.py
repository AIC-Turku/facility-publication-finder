"""Summarize discovery/text source health from a completed experiment."""
from __future__ import annotations

import json
from pathlib import Path

from ..sweep import DATA


def experiment_health(year, plan_name, base_dir=None):
    base = Path(base_dir or DATA) / str(year) / "experiments" / plan_name
    summary_path = base / "summary.json"
    if not summary_path.exists():
        raise FileNotFoundError(f"missing experiment summary: {summary_path}")
    summary = json.loads(summary_path.read_text(encoding="utf-8"))

    discovery = []
    for item in summary.get("discovery") or []:
        returned = int(item.get("returned") or 0)
        error = item.get("error")
        truncated = bool(item.get("truncated"))
        if error:
            status = "error"
        elif truncated:
            status = "truncated"
        elif returned == 0:
            status = "empty"
        else:
            status = "ok"
        discovery.append({
            "strategy": item.get("strategy"),
            "status": status,
            "returned": returned,
            "unique_added": int(item.get("unique_added") or 0),
            "truncated": truncated,
            "seconds": item.get("seconds"),
            "error": error,
        })

    text = []
    health_by_strategy = {
        item.get("strategy"): item
        for item in summary.get("source_health") or []
        if item.get("strategy")
    }
    by_strategy = {
        item.get("strategy"): dict(item)
        for item in summary.get("text_strategy_yield") or []
        if item.get("strategy")
    }
    attempt_counts = {}
    for item in summary.get("text_attempts") or []:
        attempt_counts.setdefault(item.get("strategy"), {})[item.get("status")] = int(
            item.get("count") or 0
        )

    for strategy in sorted(set(by_strategy) | set(attempt_counts) | set(health_by_strategy)):
        metrics = by_strategy.get(strategy, {})
        health = health_by_strategy.get(strategy, {})
        counts = attempt_counts.get(strategy, {})
        errors = int(metrics.get("errors") or counts.get("error") or 0)
        successes = int(metrics.get("successes") or counts.get("success") or 0)
        rejected = int(metrics.get("rejected") or counts.get("rejected") or 0)
        misses = int(counts.get("miss") or 0)
        attempted = successes + rejected + errors + misses
        if errors:
            status = "error"
        elif attempted and not successes and (rejected or misses):
            status = "no_success"
        elif successes:
            status = "ok"
        else:
            status = "not_attempted"
        text.append({
            "strategy": strategy,
            "status": status,
            "attempted": attempted,
            "successes": successes,
            "selected": int(metrics.get("selected") or 0),
            "exclusive_successes": int(metrics.get("exclusive_successes") or 0),
            "rejected": rejected,
            "errors": errors,
            "misses": misses,
            "success_rate": health.get("success_rate"),
            "reasons": health.get("reasons") or [],
        })

    return {
        "plan": plan_name,
        "year": int(year),
        "incomplete_run": bool(summary.get("incomplete_run", False)),
        "discovery": discovery,
        "text": text,
    }
