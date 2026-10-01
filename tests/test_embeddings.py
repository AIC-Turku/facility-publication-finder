import csv

import numpy as np
import pytest

from facility_pubs import embeddings as E

pytest.importorskip("sklearn")


class FakeEmbedder:
    """Deterministic 3-d 'embedding': counts of three marker words."""
    model_name = "fake|test"

    def embed(self, texts):
        return np.array([[t.lower().count("confocal") + 0.1, t.lower().count("mass spectrometry") + 0.1,
                          t.lower().count("zebrafish") + 0.1] for t in texts], dtype=np.float32)


def _unit(*x):
    x = np.array(x, dtype=np.float32)
    return x / np.linalg.norm(x)


def test_chunks_drop_acknowledgement_and_facility_sentences():
    text = ("Cells were imaged on a confocal microscope with a 63x objective. "
            "We thank the Cell Imaging and Cytometry Core, Turku Bioscience, for help. "
            "Imaging was supported by Biocenter Finland. "
            "Proteins were quantified by mass spectrometry.")
    out = " ".join(E.chunks(text, size=80))
    assert "confocal" in out
    assert "Cytometry Core" not in out and "Biocenter" not in out and "thank" not in out


def test_chunks_keep_the_most_imaging_heavy_parts():
    text = " ".join(["Samples were weighed and stored at room temperature for later use."] * 20 +
                     ["Live-cell imaging used a confocal microscope and fluorescence staining."])
    top = E.chunks(text, n=1, size=60)
    assert len(top) == 1 and "confocal" in top[0]


def test_chunks_are_capped_in_length():
    text = "Confocal imaging " + "x" * 5000 + "."
    assert all(len(c) <= int(E.CHUNK_CHARS * 1.2) for c in E.chunks(text))


def test_paper_vectors_are_unit_length_and_keep_the_chunk_text():
    v = E.paper_vectors({"a": "Confocal microscopy of cells, imaged live on a microscope.",
                         "b": "Mass spectrometry of plasma samples was used for imaging-free work."},
                        FakeEmbedder())
    assert set(v) == {"a", "b"}
    for vec, text in v.values():
        assert abs(np.linalg.norm(vec) - 1) < 1e-5 and text


def test_truncated_store_is_treated_as_missing_and_saves_are_atomic(tmp_path):
    path = tmp_path / "2024.npz"
    E._save(path, {"a": (_unit(1, 0, 0), "t")}, "m")
    assert not list(tmp_path.glob("*.tmp"))
    path.write_bytes(path.read_bytes()[:40])          # a Colab disconnect mid-save
    assert E._load(path, "m") == {}


def test_store_files_are_per_model_and_backend():
    assert E.store_path("2024", "BAAI/bge-small-en-v1.5|fastembed") != \
        E.store_path("2024", "BAAI/bge-small-en-v1.5|sentence-transformers")


def test_near_duplicate_known_papers_are_not_used_for_training():
    known_rows = [{"doi": "preprint", "year": "2023"}, {"doi": "other", "year": "2023"}]
    known_store = {"preprint": (_unit(1, 0, 0), "confocal"), "other": (_unit(0.6, 0.8, 0), "confocal imaging")}
    year_store = {"journal": (_unit(1, 0.01, 0), "confocal"), "x": (_unit(0, 0, 1), "zebrafish")}
    scores, method = E.score_year(2024, known_store, year_store, known_rows)
    assert "of 1 known" in method       # the preprint of the paper being scored was dropped


def test_known_paper_without_text_is_not_fetched_again(monkeypatch, tmp_path):
    monkeypatch.setenv("PUBS_DATA", str(tmp_path))
    import facility_pubs.fulltext as fulltext
    monkeypatch.setenv("PUBS_DATA", str(tmp_path))
    monkeypatch.setattr(E, "cached_text", lambda year, doi: (None, None))
    calls = []

    class Res:
        text, source = None, None

    monkeypatch.setattr(fulltext, "resolve_text", lambda paper: calls.append(paper) or Res())
    row = {"doi": "10.1/x", "year": "2020", "title": "T"}
    assert E._known_text(row) is None and E._known_text(row) is None
    assert len(calls) == 1


def test_saved_store_round_trips_and_is_not_reused_across_models(tmp_path):
    path = tmp_path / "2024.npz"
    E._save(path, {"a": (_unit(1, 0, 0), "confocal text")}, "bge|fastembed")
    loaded = E._load(path, "bge|fastembed")
    assert set(loaded) == {"a"} and loaded["a"][1] == "confocal text"
    assert E._load(path, "bge|sentence-transformers") == {}


def test_training_never_uses_the_target_years_known_papers_or_flagged_negatives():
    known_rows = [{"doi": "k24", "year": "2024"}, {"doi": "k23", "year": "2023"},
                  {"doi": "k22", "year": "2022"}]
    known_store = {"k24": 1, "k23": 1, "k22": 1}
    year_store = {"k24": 1, "x": 1, "k22": 1}       # k22 also sits in the 2024 universe
    other = {"n1": 1, "flag": 1, "k23": 1}
    pos, neg = E.training_sets(2024, known_store, year_store, known_rows, other, other_flagged={"flag"})
    assert pos == ["k23"]          # not the held-out k24, not k22 (it is being scored)
    assert neg == ["n1"]           # not a known paper, not a rule-flagged paper


def test_score_year_ranks_aic_like_papers_first_with_both_scores():
    known_rows = [{"doi": f"k{i}", "year": "2023"} for i in range(5)]
    known_store = {f"k{i}": (_unit(1, 0.05 * i, 0), f"confocal microscope airyscan imaging cells {i}")
                   for i in range(5)}
    year_store = {"aic_like": (_unit(1, 0.5, 0.4), "confocal microscope airyscan imaging tissue"),
                  "other": (_unit(0.1, 1, 0.2), "mass spectrometry plasma proteomics samples")}
    scores, method = E.score_year(2024, known_store, year_store, known_rows)
    assert scores["aic_like"][0] > scores["other"][0]   # embedding
    assert scores["aic_like"][1] > scores["other"][1]   # TF-IDF
    assert method.startswith("mean cosine")
    negatives = {f"n{i}": (_unit(0.05 * i, 1, 0), f"mass spectrometry proteomics plasma {i}") for i in range(10)}
    scores, method = E.score_year(2024, known_store, year_store, known_rows, negatives)
    assert scores["aic_like"][0] > scores["other"][0] and method.startswith("logistic regression")


def test_rank_year_writes_the_check_list(monkeypatch, tmp_path):
    monkeypatch.setenv("PUBS_DATA", str(tmp_path))
    rows = [{"doi": "a", "title": "A", "priority": "low", "category": "F", "microscopy_terms": 9, "has_text": True},
            {"doi": "b", "title": "B", "priority": "report", "category": "A", "microscopy_terms": 2, "has_text": True}]
    monkeypatch.setattr(E, "load_screened", lambda year: rows)
    (tmp_path / "2024").mkdir()
    E._save(E.store_path("2024", "fake|test"),
            {"a": (_unit(1, 0.5, 0.4), "confocal imaging microscope"), "b": (_unit(0, 1, 0), "mass spectrometry")},
            "fake|test")
    known_rows = [{"doi": "k", "year": "2023"}, {"doi": "b", "year": "2024"}]   # b: confirmed in 2024
    known_store = {"k": (_unit(1, 0.1, 0), "confocal imaging microscope airyscan")}
    s = E.rank_year(2024, known_store, known_rows, model="fake|test")
    with open(s["path"], newline="") as f:
        sheet = list(csv.DictReader(f))
    assert list(sheet[0]) == E.SHEET_COLUMNS
    assert [r["doi"] for r in sheet] == ["a", "b"]           # the AIC-like low paper comes first
    assert sheet[0]["rules_version"].startswith("config ") and sheet[0]["model"] == "fake|test"
    assert s["known_with_text"] == 1 and s["rules_flagged_known"] == 1
    assert s["top"][50]["embedding_new_unflagged"] == 1
    assert "top 50" in E.format_summary(s)
    assert sheet[1]["confirmed"] == "True"


def test_run_skips_years_that_were_not_swept(monkeypatch, tmp_path):
    monkeypatch.setenv("PUBS_DATA", str(tmp_path))
    monkeypatch.setattr(E, "build_known", lambda embedder, progress, **kw: {"k": (_unit(1, 0, 0), "t")})
    import facility_pubs.papers as known
    monkeypatch.setattr(known, "load_papers", lambda: [])
    said = []
    assert E.run([1999], embedder=FakeEmbedder(), progress=said.append) == []
    assert any("not swept" in s for s in said)


def test_run_skips_swept_years_without_cached_text(monkeypatch, tmp_path):
    monkeypatch.setenv("PUBS_DATA", str(tmp_path))
    monkeypatch.setattr(E, "build_known", lambda embedder, progress, **kw: {"k": (_unit(1, 0, 0), "t")})
    monkeypatch.setattr(E, "build_year", lambda year, embedder, progress: {})
    import facility_pubs.papers as known
    monkeypatch.setattr(known, "load_papers", lambda: [])
    (tmp_path / "2025").mkdir()
    (tmp_path / "2025" / "screened.jsonl").write_text("")
    said = []
    assert E.run([2025], embedder=FakeEmbedder(), progress=said.append) == []
    assert any("no cached full text" in s for s in said)


def test_store_names_never_collide():
    assert E.store_path("2024", "a/b|x") != E.store_path("2024", "a-b|x")


def test_rank_year_leaves_an_existing_sheet_alone_when_there_is_nothing_to_rank(monkeypatch, tmp_path):
    monkeypatch.setenv("PUBS_DATA", str(tmp_path))
    monkeypatch.setattr(E, "load_screened", lambda year: [])
    (tmp_path / "2024").mkdir()
    sheet = tmp_path / "2024" / "embedding_ranked.csv"
    sheet.write_text("rank,doi,your_verdict,your_note\n1,10.1/x,yes,keep me\n")
    s = E.rank_year(2024, {}, [], model="m|cpu")
    assert s["papers"] == 0 and "keep me" in sheet.read_text()
    with pytest.raises(ValueError):
        E.rank_year(2024, {}, [], model=None)


def test_no_text_marker_is_not_written_when_a_host_is_out_of_budget(monkeypatch, tmp_path):
    import facility_pubs.fulltext as fulltext
    import facility_pubs.http as http
    monkeypatch.setenv("PUBS_DATA", str(tmp_path))
    monkeypatch.setattr(E, "cached_text", lambda year, doi: (None, None))
    calls = []

    class Res:
        text, source = None, None

    monkeypatch.setattr(fulltext, "resolve_text", lambda paper: calls.append(1) or Res())
    monkeypatch.setattr(http, "_EXHAUSTED", {"www.ebi.ac.uk"})
    row = {"doi": "10.1/y", "year": "2020", "title": "T"}
    E._known_text(row), E._known_text(row)
    assert len(calls) == 2          # no marker: tried again next time


def test_no_confirmed_papers_gives_no_check_list_but_no_crash(monkeypatch, tmp_path):
    monkeypatch.setenv("PUBS_DATA", str(tmp_path))
    import facility_pubs.papers as known
    monkeypatch.setattr(known, "load_papers", lambda: [])
    said = []
    assert E.run([2025], embedder=FakeEmbedder(), progress=said.append) == []
    assert any("no confirmed papers" in s for s in said)


def test_existing_stores_decide_the_backend():
    model = "BAAI/bge-small-en-v1.5"
    E._save(E.store_path("2024", f"{model}|fastembed"), {"a": (_unit(1, 0, 0), "t")}, f"{model}|fastembed")
    assert E._existing_backend(model) == "fastembed"
    assert E._existing_backend("other/model") is None
