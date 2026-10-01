"""Load and validate YAML experiment plans."""
from __future__ import annotations

from pathlib import Path

import yaml


VALID_TEXT_MODES = {"first_success", "all"}
VALID_ERROR_MODES = {"fail", "continue"}
VALID_QUALITY = {"low", "medium", "high"}


def load_plan(path):
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    name = raw.get("name") or Path(path).stem
    discovery = _steps(raw.get("discovery") or [])
    on_error = raw.get("on_error", "fail")
    if on_error not in VALID_ERROR_MODES:
        raise ValueError(f"invalid on_error {on_error!r}; expected one of {sorted(VALID_ERROR_MODES)}")
    text = raw.get("text") or {}
    text_steps = _steps(text.get("strategies") or [])
    mode = text.get("mode", "first_success")
    prefer_quality = str(text.get("prefer_quality", "") or "").lower() or None
    if prefer_quality not in ({None} | VALID_QUALITY):
        raise ValueError(
            f"invalid prefer_quality {prefer_quality!r}; expected one of {sorted(VALID_QUALITY)}"
        )
    if mode not in VALID_TEXT_MODES:
        raise ValueError(f"invalid text mode {mode!r}; expected one of {sorted(VALID_TEXT_MODES)}")
    if not discovery:
        raise ValueError("plan must enable at least one discovery strategy")
    if not text_steps:
        raise ValueError("plan must enable at least one text strategy")
    return {
        "name": name,
        "on_error": on_error,
        "workers": max(1, int(raw.get("workers", 4))),
        "resume": bool(raw.get("resume", False)),
        "discovery": discovery,
        "text": {
            "mode": mode,
            "strategies": text_steps,
            "cache_successes": bool(text.get("cache_successes", True)),
            "prefer_quality": prefer_quality,
        },
        "screen": bool(raw.get("screen", True)),
    }


def _steps(values):
    out = []
    for value in values:
        if isinstance(value, str):
            value = {"strategy": value}
        if not value.get("enabled", True):
            continue
        name = value.get("strategy")
        if not name:
            raise ValueError(f"strategy step is missing a name: {value!r}")
        out.append({"strategy": name, "options": value.get("options") or {}})
    return out
