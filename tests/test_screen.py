"""Regression tests for the false positives and misses found on real 2024-2025 papers."""
import pytest

from aic_pubs.config import load
from aic_pubs.report import match_users
from aic_pubs.screen import screen

PAD = " Cells were imaged by confocal microscopy. " * 6  # enough microscopy terms


@pytest.fixture(scope="module")
def cfg():
    return load()


def test_pdf_hyphenation_is_undone(cfg):
    # 10.1016/j.devcel.2025.06.025 and 10.1111/nph.70114 were missed before
    r = screen("The Cell Imag- ing and Cyto- metry Core is acknowledged for services." + PAD, cfg)
    assert r["category"] == "A"


def test_flowing_software_citation_is_not_use(cfg):
    t = ("Data were analysed using Flowing software 2.5.1 (Cell Imaging Core, Turku Centre for "
         "Biotechnology, University of Turku).")
    r = screen(t, cfg)
    assert r["category"] != "A" and r["flowing_software_only"]


def test_affiliation_line_is_not_acknowledgement(cfg):
    t = "4Turku Bioimaging, University of Turku and Åbo Akademi University, Turku, Finland." + PAD
    assert screen(t, cfg)["category"] == "D"


def test_acknowledgement_that_mentions_turku_bioimaging(cfg):
    t = "We thank Turku Bioimaging, University of Turku and Åbo Akademi University for imaging support."
    assert screen(t + PAD, cfg)["category"] == "A"


def test_lsm880_is_a_strong_instrument_lead(cfg):
    r = screen("Images were acquired with a Zeiss LSM880 Fast AiryScan microscope." + PAD, cfg)
    assert r["category"] == "B"
    assert r["instruments_strong"] == ["scope-zeiss-lsm-880-with-airyscan"]


def test_airyscan2_is_not_the_lsm880(cfg):
    r = screen("A 63x objective was used in confocal mode with an Airyscan 2 detector on an LSM 980." + PAD, cfg)
    assert "scope-zeiss-lsm-880-with-airyscan" not in r["instruments_strong"]


def test_abberior_reagent_is_not_the_sted(cfg):
    r = screen("STAR Red Goat-anti-Rabbit Abberior Cat: #STRED-1007." + PAD, cfg)
    assert "scope-1e33f909" not in r["instruments_strong"]


def test_bare_3i_is_not_the_spinning_disk(cfg):
    r = screen("The 3i-phase sample was annealed at 900 C." + PAD, cfg)
    assert r["instruments_strong"] == []


def test_marianas_spinning_disk(cfg):
    r = screen("Images were captured using a 3i Marianas CSU-W1 spinning disk confocal microscope." + PAD, cfg)
    assert "scope-3i-csu-w1-spinning-disk" in r["instruments_strong"]


def test_no_text(cfg):
    assert screen(None, cfg)["category"] == "N"


def test_match_users_on_utupub_author_format():
    row = {"local_authors": ["Example, Erik", "Doe, Jane"]}
    assert match_users(row, ["Erik Example", "Tester, Anna"]) == ["Erik Example"]


def test_comma_variant_of_facility_name(cfg):
    # 10.1002/advs.202503569
    t = "We thank the Cell Imaging, Cytometry Core, the Genome Editing core (Turku Bioscience) for services."
    assert screen(t + PAD, cfg)["category"] == "A"


def test_superscript_letter_affiliation(cfg):
    # 10.1016/j.test.2025.000001
    t = "c Faculty of Science, Åbo Akademi University, Turku 20520, Finland d Euro-Bioimaging ERIC, Turku 20520, Finland."
    assert screen(t + PAD, cfg)["category"] != "A"


@pytest.mark.parametrize("text", [
    "Species included Botaurus stellaris and Cladonia stellaris.",   # not the Leica STELLARIS
    "Sum squared residuals 0.03 Schwarz criterion.",                  # not M Squared
    "Persson, A.A.E.; Lifa, H.M.; Falk-Delgado, A.",                  # not Lambert LIFA
])
def test_word_collisions_are_not_instruments(cfg, text):
    assert screen(text + PAD, cfg)["instruments_strong"] == []


def test_doi_normalisation():
    from aic_pubs.sources import _norm_doi
    assert _norm_doi("https://doi.org/10.1016/J.TEST.2024.000013,") == "10.1016/j.test.2024.000013"
    assert _norm_doi("doi: 10.1000/ABC") == "10.1000/abc"
    assert _norm_doi("<https://doi.org/10.1000/ABC>") == "10.1000/abc"
    assert _norm_doi("https://doi.org/10.1000/foo%28bar%29") == "10.1000/foo(bar)"
    assert _norm_doi("10.1000/foo(bar)") == "10.1000/foo(bar)"
    assert _norm_doi("See 10.1000/ABC).") == "10.1000/abc"


def test_specialist_technique_in_local_paper_is_a_lead(cfg):
    r = screen("3D-SIM images were acquired and reconstructed." + PAD, cfg, local=True)
    assert r["category"] == "C" and r["techniques_specialist"] == ["sim"]


def test_specialist_technique_outside_turku_is_not_a_lead(cfg):
    assert screen("3D-SIM images were acquired." + PAD, cfg, local=False)["category"] == "F"


def test_technique_acronyms_are_case_sensitive(cfg):
    r = screen("The sim card was sted in a palm-sized frap box." + PAD, cfg)
    assert r["techniques_specialist"] == []


def test_general_technique_is_counted_but_not_a_lead(cfg):
    r = screen("Images were taken on a spinning disk microscope." + PAD, cfg)
    assert "confocal_spinning_disk" in r["techniques"] and r["category"] == "F"


def test_config_covers_database():
    """Every active instrument and offered capability in AIC-Turku-database has a pattern."""
    import os
    from aic_pubs import coverage
    db = os.environ.get("AIC_DATABASE")
    if not db:
        pytest.skip("set AIC_DATABASE to a checkout of AIC-Turku-database")
    text = coverage.report(load(), db)
    assert "0 without a name pattern" in text and "0 without a technique pattern" in text


def test_component_fingerprint_raises_score(cfg):
    t = ("Images were acquired on a 3i Marianas spinning disk with a Photometrics Evolve EMCCD camera "
         "controlled by SlideBook 6.") + PAD
    r = screen(t, cfg)
    assert r["fingerprints"]["scope-3i-csu-w1-spinning-disk"] == ["Photometrics Evolve", "SlideBook"]
    assert r["score"] == 4 + 2 and r["priority"] == "check"


def test_weak_model_with_its_components_becomes_a_lead(cfg):
    t = "Cells were imaged on a Nikon Eclipse Ti2-E with a Lumencor Spectra X and a DS-Fi3 camera." + PAD
    r = screen(t, cfg)
    assert r["category"] == "B" and "scope-nikon-eclipse-ti2-e" in r["instruments_strong"]


def test_imaging_credited_elsewhere_lowers_priority(cfg):
    # 10.1093/test/000002: LSM880 used, microscopy credited to FIMM in Helsinki
    t = ("Confocal images were acquired using a Zeiss LSM880 Fast AiryScan microscope. For immunostainings "
         "and microscopy, we thank the FIMM High Content Imaging and Analysis core unit.") + PAD
    r = screen(t, cfg)
    assert r["credited_elsewhere"] and r["priority"] == "low"


def test_electron_microscopy_lab_is_not_competing_light_microscopy(cfg):
    t = ("Images were taken with a Zeiss LSM880. Electron microscopy samples were analysed at the Electron "
         "Microscopy Laboratory, Institute of Biomedicine.") + PAD
    assert screen(t, cfg)["credited_elsewhere"] == []


def test_acknowledgement_is_never_credited_elsewhere(cfg):
    t = ("We thank the Cell Imaging and Cytometry Core and the Biomedicum Imaging Unit for imaging.") + PAD
    r = screen(t, cfg)
    assert r["category"] == "A" and r["priority"] == "report"


def test_institute_of_biomedicine_imaging_center_is_aic(cfg):
    # 10.1038/s41598-025-92841-9
    t = "Biocenter Finland and Institute of Biomedicine Imaging Center are acknowledged for imaging instrumentation."
    assert screen(t + PAD, cfg)["category"] == "A"


def test_imaging_performed_at_another_core(cfg):
    # 10.1016/j.test.2025.000003 (false positive: STED at DaMBIC, Denmark)
    t = ("STED microscopy was performed on an Abberior Facility Line STED. Bioimaging was mainly performed at "
         "DaMBIC, a bioimaging research core facility at SDU.") + PAD
    r = screen(t, cfg)
    assert r["credited_elsewhere"] and r["priority"] == "low"


LSM = "Images were acquired with a Zeiss LSM880 confocal microscope." + PAD


def test_single_local_author_lowers_score(cfg):
    one = screen(LSM, cfg, meta={"local_authors": ["Virtanen, Anna"], "sources": ["utupub"]})
    many = screen(LSM, cfg, meta={"local_authors": ["A, a", "B, b", "C, c"], "sources": ["utupub"]})
    assert many["score"] - one["score"] == 3  # +1 many authors vs -2 single author
    assert any("single local author" in x for x in one["score_reasons"])


def test_single_utu_author_is_not_penalised_when_abo_also_lists_the_paper(cfg):
    r = screen(LSM, cfg, meta={"local_authors": ["Virtanen, Anna"], "sources": ["utupub", "abo"]})
    assert not any("single local author" in x for x in r["score_reasons"])


def test_non_life_science_field_and_review(cfg):
    r = screen(LSM, cfg, meta={"fields": ["115"], "title": "A review of galaxy surveys"})
    assert r["priority"] == "low"


def test_penalties_never_demote_an_acknowledgement(cfg):
    t = "The Cell Imaging and Cytometry Core is acknowledged." + LSM
    r = screen(t, cfg, meta={"local_authors": ["Virtanen, Anna"], "fields": ["115"], "type": "A2 Review"})
    assert r["priority"] == "report"


def test_dataset_is_not_a_paper(cfg):
    t = "The Cell Imaging and Cytometry Core is acknowledged." + LSM
    r = screen(t, cfg, meta={"doi": "10.4121/00000000-0000-0000-0000-000000000004.v2"})
    assert r["priority"] != "report"


def test_instrument_sentence_naming_another_institution(cfg):
    t = ("Confocal images were taken on a Leica STELLARIS 8 (Imaging Platform, Institut Jacques Monod).") + PAD
    r = screen(t, cfg)
    assert r["instrument_named_elsewhere"] and any("elsewhere" in x for x in r["score_reasons"])


def test_instrument_sentence_naming_turku(cfg):
    t = "Imaging was done on the 3i Marianas CSU-W1 at Turku Bioscience Centre." + PAD
    assert screen(t, cfg)["instrument_named_with_turku"]


def test_repeat_user(cfg):
    r = screen(LSM, cfg, meta={"local_authors": ["Doe, Jane"], "history": {"Doe, Jane"},
                               "sources": ["utupub", "abo"]})
    assert "+2 repeat facility user group" in r["score_reasons"]
    assert not any("Doe" in x for x in r["score_reasons"])  # never names in reasons


def test_placeholder_authors_are_dropped():
    from aic_pubs.sources import clean_authors
    assert clean_authors(["Dataimport, tyks, vsshp", "Doe, Jane"]) == ["Doe, Jane"]


def test_medisiina_imaging_centre_is_aic(cfg):
    t = "We thank the Medisiina Imaging Centre of the University of Turku for imaging support."
    assert screen(t + PAD, cfg)["category"] == "A"


def test_booking_and_staff_rules(cfg):
    bookings = {("doe", "j"): [(2024, "scope-zeiss-lsm-880-with-airyscan")]}
    meta = {"local_authors": ["Doe, Jane", "Roe, Richard"], "year": 2025,
            "bookings": bookings, "staff": {("roe", "r")}, "sources": ["utupub", "abo"]}
    r = screen(LSM, cfg, meta=meta)
    public = " | ".join(r["score_reasons"])
    private = " | ".join(r["private"]["reasons"])
    assert "booked" not in public and "staff" not in public  # private inputs never reach public output
    assert "group booked the facility" in private and "booked instrument named in paper" in private
    assert "facility staff among authors" in private
    assert "Doe" not in private
    assert r["private"]["score"] == r["score"] + 3 + 2 + 3


def test_old_booking_outside_window_does_not_count(cfg):
    meta = {"local_authors": ["Doe, Jane"], "year": 2025,
            "bookings": {("doe", "j"): [(2019, "")]}}
    assert not any("booked" in x for x in screen(LSM, cfg, meta=meta)["score_reasons"])


def test_booking_alone_does_not_make_a_lead(cfg):
    # before this rule, 121 epidemiology/chemistry papers of groups that book the facility became "check"
    meta = {"local_authors": ["Doe, Jane"], "year": 2025, "bookings": {("doe", "j"): [(2024, "")]}}
    r = screen("A registry study of 10,000 patients with atrial fibrillation.", cfg, meta=meta)
    assert not any("booked" in x for x in r["score_reasons"]) and r["priority"] == "low"


def test_booking_never_outweighs_imaging_elsewhere(cfg):
    # 10.1091/test.000005: LSM880 used, imaging credited to Colorado State University
    t = ("Images were taken on a Zeiss LSM 880. The authors are grateful for access to the Microscope Imaging "
         "Network Core Facility at Colorado State University.") + PAD
    meta = {"local_authors": ["Doe, Jane", "Roe, Richard"], "year": 2025,
            "bookings": {("doe", "j"): [(2024, "scope-zeiss-lsm-880-with-airyscan")]}}
    assert not any("booked" in x for x in screen(t, cfg, meta=meta)["score_reasons"])


def test_report_priority_requires_acknowledgement(cfg):
    t = ("Images were acquired on a 3i Marianas CSU-W1 spinning disk with a Photometrics Evolve camera "
         "controlled by SlideBook at Turku Bioscience.") + PAD
    meta = {"local_authors": ["Doe, Jane", "A, a", "B, b"], "year": 2025, "sources": ["utupub"],
            "bookings": {("doe", "j"): [(2024, "scope-3i-csu-w1-spinning-disk")]}}
    r = screen(t, cfg, meta=meta)
    assert r["private"]["score"] >= 10 and r["private"]["priority"] == "check"


def test_slidebook_alone_is_not_a_strong_instrument(cfg):
    r = screen("Images were processed in SlideBook 6." + PAD, cfg)
    assert r["instruments_strong"] == []


def test_components_far_from_instrument_do_not_form_fingerprint(cfg):
    t = (
        "Images were acquired on a Nikon Eclipse Ti2-E microscope. "
        + ("Unrelated methods text without instrument details. " * 80)
        + "A Lumencor Spectra X source and DS-Fi3 camera were used in a separate setup."
        + PAD
    )
    r = screen(t, cfg)
    assert "scope-nikon-eclipse-ti2-e" not in r["instruments_strong"]


def test_components_near_instrument_still_promote_weak_model(cfg):
    t = (
        "Images were acquired on a Nikon Eclipse Ti2-E microscope with a "
        "Lumencor Spectra X light source and DS-Fi3 camera."
        + PAD
    )
    r = screen(t, cfg)
    assert "scope-nikon-eclipse-ti2-e" in r["instruments_strong"]


def test_report_user_list_does_not_write_private_names(monkeypatch, tmp_path):
    from aic_pubs import report

    monkeypatch.setattr(
        report,
        "load_screened",
        lambda year: [{
            "doi": "10.1000/x",
            "title": "X",
            "journal": "J",
            "category": "A",
            "priority": "report",
            "score": 10,
            "score_reasons": [],
            "local_authors": ["Example, Erik"],
            "local_email": False,
            "text_source": "utupub",
            "instruments_strong": [],
            "instruments_weak": [],
            "techniques_specialist": [],
            "microscopy_terms": 5,
            "fingerprints": {},
            "credited_elsewhere": [],
            "other_local_imaging": False,
            "acknowledgement": ["AIC acknowledged"],
            "evidence": ["AIC acknowledged"],
        }],
    )
    monkeypatch.setenv("PUBS_DATA", str(tmp_path))
    path = tmp_path / "review.csv"
    report.write_review_csv(2025, set(), users=["Erik Example"], path=path)
    public = path.read_text(encoding="utf-8")
    assert "known_user_match" not in public and "matched_users" not in public
    from aic_pubs.sweep import private_dir
    private = (private_dir(2025) / "review.csv").read_text(encoding="utf-8")
    assert "known_user_match" in private
    assert "Erik Example" not in public + private.split("\n", 1)[0]


def test_booking_needs_an_instrument_or_technique_in_the_paper(cfg):
    # 10.1186/test-000006: PET study, no microscope named
    meta = {"local_authors": ["Doe, Jane"], "year": 2025, "bookings": {("doe", "j"): [(2024, "")]}}
    t = "Sections were stained and imaged by immunofluorescence microscopy. " * 6
    assert not any("booked" in x for x in screen(t, cfg, meta=meta)["score_reasons"])


def test_other_evos_models_are_not_the_aic_evos(cfg):
    # 10.1002/test.000007
    r = screen("The disks were viewed using the Evos 5000 and an EVOS M7000 (Invitrogen)." + PAD, cfg)
    assert "scope-evos-fl" not in r["instruments_weak"]
    assert "scope-evos-fl" in screen("Imaged on an EVOS FL microscope." + PAD, cfg)["instruments_weak"]


def test_stored_sentences_have_no_email_and_are_bounded(cfg):
    t = ("We thank the Cell Imaging and Cytometry Core. Correspondence: jane.doe@utu.fi. "
         + "Images were acquired on a Zeiss LSM880 " + "with care " * 200 + ".") + PAD
    r = screen(t, cfg)
    stored = " ".join(r["acknowledgement"] + r.get("evidence", []) + r["credited_elsewhere"])
    assert "@" not in stored
    assert all(len(x) <= 600 for x in r["acknowledgement"] + r.get("evidence", []))


def test_europepmc_entities_are_decoded(monkeypatch):
    from aic_pubs import sources
    monkeypatch.setattr(sources, "fetch", lambda url, **k: "<p>Cell Imaging &amp; Cytometry Core, Turku</p>")
    assert "Cell Imaging & Cytometry Core" in sources.europepmc_text("PMC1")


@pytest.mark.parametrize("raw, doi", [
    ("10.1007/s00000-025-00011-y?utm_source=rct&amp;utm_medium=email", "10.1007/s00000-025-00011-y"),
    ("https://doi.org/10.1108/TST-09-2024-0014/full/pdf?title=x", "10.1108/tst-09-2024-0014"),
    ("10.1016/j.test.2022.000012&lt;br/&gt;&lt;br/&gt;biography", "10.1016/j.test.2022.000012"),
    ("10.1016/j.test.2025.000003", "10.1016/j.test.2025.000003"),
])
def test_doi_url_junk_is_stripped(raw, doi):
    from aic_pubs.sources import _norm_doi
    assert _norm_doi(raw) == doi


@pytest.mark.parametrize("text, instrument", [
    ("Virtanen A, Kesti2 B and Smith C wrote this.", "scope-nikon-eclipse-ti2-e"),       # author + superscript
    ("Epoxidized vegetable oils (EVOs) were blended.", "scope-evos-fl"),
    ("Sites were ranked by DMRE and DMRB indices.", "scope-leica-dmre"),
    ("Abberior STAR RED (Abberior) was used as suggested by the supplier.", "scope-1e33f909"),
])
def test_weak_and_reagent_pattern_misfires(cfg, text, instrument):
    r = screen(text + PAD, cfg)
    assert instrument not in r["instruments_strong"] + r["instruments_weak"]


def test_nikon_ti2_still_matches(cfg):
    r = screen("Images were taken with a Nikon Eclipse Ti2-E widefield microscope." + PAD, cfg)
    assert "scope-nikon-eclipse-ti2-e" in r["instruments_weak"]


def test_components_counted_once_regardless_of_spelling(cfg):
    t = ("Images were taken on a Nikon Eclipse Ti2-E with Perfect Focus. Later the Ti2-E perfect focus "
         "system was recalibrated.") + PAD
    r = screen(t, cfg)
    assert len(r["fingerprints"].get("scope-nikon-eclipse-ti2-e", [])) == 1
    assert "scope-nikon-eclipse-ti2-e" not in r["instruments_strong"]


@pytest.mark.parametrize("text", [
    "Z-sections were obtained using Zeiss 880 LSM using the 63X oil objective.",   # 10.1002/cbic.202400908
    "Imaging was done on an 880 LSM confocal.",
])
def test_lsm880_word_order_variants(cfg, text):
    assert "scope-zeiss-lsm-880-with-airyscan" in screen(text + PAD, cfg)["instruments_strong"]


def test_cic_abbreviation_in_facility_name(cfg):
    t = "We thank the Cell imaging and Cytometry (CIC) Core, Turku Bioscience, for support."
    assert screen(t + PAD, cfg)["category"] == "A"


def test_cytometry_only_acknowledgement_counts(cfg):
    # 10.1038/s41598-024-83954-8: only flow cytometry (BD LSR Fortessa), CIC thanked
    t = ("Cell Imaging and Cytometry Core and Biocenter Finland are acknowledged for providing research "
         "infrastructures. Samples were analysed by flow cytometry on a BD LSR Fortessa.")
    r = screen(t, cfg)
    assert r["cytometry_only"] and r["priority"] == "report"  # owner: cytometry counts as AIC use


def test_dataset_is_never_above_low(cfg):
    t = "The Cell Imaging and Cytometry Core is acknowledged." + LSM
    r = screen(t, cfg, meta={"doi": "10.4121/00000000-0000-0000-0000-000000000004.v2"})
    assert r["priority"] == "low"


def test_europepmc_ack_hit_without_text_is_check(cfg):
    r = screen(None, cfg, meta={"sources": ["europepmc_ack"]})
    assert r["category"] == "N" and r["priority"] == "check"


def test_staff_thanked_in_acknowledgements(cfg):
    cfg.staff.append("Roe, Richard")
    try:
        t = "We acknowledge Anna Tester and Richard Roe for their assistance in the experiments." + PAD
        assert "+4 facility staff thanked" in screen(t, cfg)["score_reasons"]
        assert "facility staff thanked" not in " ".join(screen("We thank Mark Roe." + PAD, cfg)["score_reasons"])
    finally:
        cfg.staff.remove("Roe, Richard")


def test_text_of_another_paper_is_rejected():
    from aic_pubs.text import matches_paper
    other = "Hydrogen flame simulations with reduced chemistry " * 50
    assert not matches_paper(other, "10.1016/j.test.2025.000008",
                             "Liquid-liquid phase separation of ATXN2L enhances stress granule formation")
    assert matches_paper("see https://doi.org/10.1016/j.test.2025.000008 " + other,
                         "10.1016/j.test.2025.000008", "Liquid-liquid phase separation of ATXN2L")
    assert matches_paper(other, "10.1/x", "")  # unknown title: cannot tell, keep


def test_facility_in_a_postal_affiliation_is_not_an_acknowledgement(cfg):
    # 10.1002/test.000010 (work done in Oxford/Jena)
    t = ("A. Researcher Cell imaging and Cytometry (CIC) Core Turku Bioscience University of Turku and "
         "Åbo Akademi University FI-20520 Turku, Finland.") + PAD
    assert screen(t, cfg)["category"] == "D"


def test_acknowledgement_with_address_still_counts(cfg):
    t = ("We thank the Cell Imaging and Cytometry Core, Tykistökatu 6, FI-20520 Turku, for imaging support.") + PAD
    assert screen(t, cfg)["category"] == "A"


def test_private_staff_thanked_only_in_private_view(cfg):
    t = "We acknowledge Anna Tester and Richard Roe for their assistance in the experiments." + PAD
    r = screen(t, cfg, meta={"staff": {("roe", "r")}})
    assert "facility staff thanked" not in " ".join(r["score_reasons"])
    assert "+4 facility staff thanked" in r["private"]["reasons"]
    assert "_private_staff_thanked" not in r
