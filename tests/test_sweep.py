"""Tests for sweep refresh semantics."""
import json

from aic_pubs import sweep
from aic_pubs.sweep import completed_dois


def test_no_text_rows_are_retried(tmp_path):
    path = tmp_path / "screened.jsonl"
    rows = [
        {"doi": "10.1000/complete", "has_text": True},
        {"doi": "10.1000/retry", "has_text": False, "category": "N"},
    ]
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    assert completed_dois(path) == {"10.1000/complete"}


def test_latest_row_wins_for_refresh_state(tmp_path):
    path = tmp_path / "screened.jsonl"
    rows = [
        {"doi": "10.1000/x", "has_text": False},
        {"doi": "10.1000/x", "has_text": True},
    ]
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    assert completed_dois(path) == {"10.1000/x"}


def test_cache_sidecar_preserves_provenance(monkeypatch, tmp_path):
    monkeypatch.setattr(sweep, "DATA", tmp_path)
    sweep._store(
        2025,
        "10.1000/x",
        "article text",
        "openalex_oa",
        metadata={
            "url": "https://example.org/x.pdf",
            "license": "cc-by",
            "version": "acceptedVersion",
            "quality": "high",
        },
    )
    text, source = sweep.cached_text(2025, "10.1000/x")
    meta = sweep.cached_text_metadata(2025, "10.1000/x")
    assert text == "article text"
    assert source == "openalex_oa"
    assert meta["url"] == "https://example.org/x.pdf"
    assert meta["license"] == "cc-by"
    assert meta["version"] == "acceptedVersion"
    assert meta["quality"] == "high"


def test_legacy_cache_without_sidecar_still_loads(monkeypatch, tmp_path):
    monkeypatch.setattr(sweep, "DATA", tmp_path)
    path = sweep._cache_path(2025, "10.1000/legacy")
    path.parent.mkdir(parents=True, exist_ok=True)
    import gzip
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        handle.write("utupub\nlegacy text")
    assert sweep.cached_text(2025, "10.1000/legacy") == ("legacy text", "utupub")
    assert sweep.cached_text_metadata(2025, "10.1000/legacy") == {}


def test_completed_dois_with_year_requires_reusable_cache(monkeypatch, tmp_path):
    monkeypatch.setattr(sweep, "DATA", tmp_path)
    screened = tmp_path / "2025" / "screened.jsonl"
    screened.parent.mkdir(parents=True, exist_ok=True)
    rows = [
        {"doi": "10.1000/full", "has_text": True},
        {"doi": "10.1000/partial", "has_text": True},
        {"doi": "10.1000/short", "has_text": True},
    ]
    screened.write_text(
        "\n".join(json.dumps(r) for r in rows) + "\n",
        encoding="utf-8",
    )

    sweep._store(
        2025,
        "10.1000/full",
        ("Methods and results from a complete article. " * 400),
        "europepmc",
        metadata={"scope": "full", "quality": "high"},
    )
    sweep._store(
        2025,
        "10.1000/partial",
        ("Article preview text. " * 300),
        "publisher_html",
        metadata={"scope": "partial", "quality": "low"},
    )
    sweep._store(
        2025,
        "10.1000/short",
        "too short",
        "europepmc",
        metadata={"scope": "full", "quality": "high"},
    )

    assert sweep.completed_dois(screened, year=2025) == {"10.1000/full"}


def test_legacy_trusted_full_source_can_be_reused(monkeypatch, tmp_path):
    monkeypatch.setattr(sweep, "DATA", tmp_path)
    path = sweep._cache_path(2025, "10.1000/legacy-full")
    path.parent.mkdir(parents=True, exist_ok=True)
    import gzip
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        handle.write("utupub\n" + ("Full article methods and results. " * 400))
    assert sweep.cache_is_reusable(2025, "10.1000/legacy-full") is True


ARTICLE = ("Images were acquired on a Zeiss LSM880. We thank the Cell Imaging and Cytometry Core. "
           + "Cells were imaged by confocal microscopy. " * 80)


def _fake_run(monkeypatch, tmp_path, papers, resolve):
    """Run sweep.run offline: fixed candidate list, fake resolver, no network."""
    from aic_pubs.fulltext import TextResult
    monkeypatch.setattr(sweep, "DATA", tmp_path)
    monkeypatch.setattr(sweep, "collect", lambda year, cfg: {p["doi"]: dict(p) for p in papers})
    monkeypatch.setattr(sweep, "resolve_text", lambda p, **k: TextResult(*resolve(p)))
    monkeypatch.setattr(sweep, "load_bookings", lambda: {})
    monkeypatch.setattr(sweep, "load_staff", lambda: set())
    sweep.run(2025, workers=2)
    return {r["doi"]: r for r in sweep.load_screened(2025)}


def test_failed_refetch_never_replaces_a_good_row(monkeypatch, tmp_path):
    papers = [{"doi": "10.1000/a", "sources": ["utupub"]}]
    first = _fake_run(monkeypatch, tmp_path, papers, lambda p: (ARTICLE, "utupub"))
    assert first["10.1000/a"]["category"] == "A"
    for f in (tmp_path / "cache").rglob("*"):   # cache lost (e.g. fresh Colab without Drive)
        if f.is_file():
            f.unlink()
    second = _fake_run(monkeypatch, tmp_path, papers, lambda p: (None, None))
    assert second["10.1000/a"]["category"] == "A"


def test_one_failing_paper_does_not_abort_the_sweep(monkeypatch, tmp_path):
    papers = [{"doi": f"10.1000/p{i}", "sources": ["utupub"]} for i in range(6)]

    def resolve(p):
        if p["doi"] == "10.1000/p2":
            raise KeyError("_embedded")
        return ARTICLE, "utupub"

    rows = _fake_run(monkeypatch, tmp_path, papers, resolve)
    assert set(rows) == {f"10.1000/p{i}" for i in range(6)} - {"10.1000/p2"}


def test_rows_outside_the_universe_are_dropped(monkeypatch, tmp_path):
    papers = [{"doi": "10.1000/keep", "sources": ["utupub"]}]
    (tmp_path / "2025").mkdir(parents=True)
    (tmp_path / "2025" / "screened.jsonl").write_text(
        json.dumps({"doi": "10.1000/stale&lt;br", "has_text": True, "category": "A"}) + "\n")
    rows = _fake_run(monkeypatch, tmp_path, papers, lambda p: (ARTICLE, "utupub"))
    assert set(rows) == {"10.1000/keep"}
