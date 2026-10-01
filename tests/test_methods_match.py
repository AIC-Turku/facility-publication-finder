from aic_pubs.methods_match import best_methods_match, jaccard_methods_similarity


def test_methods_similarity_survives_light_editing():
    canonical = (
        "Images were acquired using the 3i Marianas spinning disk confocal microscope "
        "with a Yokogawa CSU-W1 scanner and Photometrics Evolve camera."
    )
    edited = (
        "Images were acquired on a 3i Marianas spinning-disk confocal system equipped "
        "with a Yokogawa CSU-W1 scanner and a Photometrics Evolve camera."
    )
    assert jaccard_methods_similarity(canonical, edited) > 0.55


def test_methods_similarity_rejects_unrelated_text():
    canonical = "Images were acquired using a Zeiss LSM 880 confocal microscope with Airyscan."
    unrelated = "RNA was isolated with TRIzol and sequenced on an Illumina NovaSeq instrument."
    assert jaccard_methods_similarity(canonical, unrelated) < 0.15


def test_best_methods_match_reports_reference():
    refs = {
        "scope-a": "Images were acquired using a Zeiss LSM 880 confocal microscope with Airyscan.",
        "scope-b": "Images were acquired using a 3i Marianas spinning disk confocal microscope.",
    }
    match = best_methods_match(
        "Images were acquired on a Zeiss LSM880 confocal microscope using Airyscan.",
        refs,
        threshold=0.35,
    )
    assert match["reference_id"] == "scope-a"
