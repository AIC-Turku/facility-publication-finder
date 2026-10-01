import pytest

from facility_pubs import review, sheet


def test_links_published_version_first_then_open_copies_without_duplicates():
    assert review.links("10.1000/a", "https://repo.example.org/items/1", "PMC9", "PPR7") == [
        ("published version (DOI)", "https://doi.org/10.1000/a"),
        ("open copy", "https://repo.example.org/items/1"),
        ("Europe PMC full text", "https://europepmc.org/article/PMC/PMC9"),
        ("Europe PMC preprint", "https://europepmc.org/article/PPR/PPR7")]
    assert review.links("10.1000/a", "https://doi.org/10.1000/a") == [
        ("published version (DOI)", "https://doi.org/10.1000/a")]


def test_pending_keeps_the_order_and_skips_decided_rows():
    rows = [{"doi": "10.1000/a", "verdict": "yes"}, {"doi": "10.1000/b", "verdict": ""}, {"doi": "10.1000/c"}]
    assert [r["doi"] for r in review.pending(rows)] == ["10.1000/b", "10.1000/c"]


def test_revisit_brings_back_chosen_verdicts_and_refuses_unknown_ones():
    rows = [{"doi": "10.1000/a", "verdict": "likely"}, {"doi": "10.1000/b", "verdict": "no"}, {"doi": "10.1000/c"}]
    assert [r["doi"] for r in review.pending(rows, ["Likely"])] == ["10.1000/a", "10.1000/c"]
    with pytest.raises(ValueError, match="revisit: maybe"):
        review.pending(rows, ["maybe"])


def test_every_reason_is_offered():
    assert set(review.REASON_OPTIONS) == {""} | {r for rs in sheet.REASONS.values() for r in rs}


def _table(isolated_folders, n=3):
    rows = [{"why": sheet.WHY_ACK, "doi": f"10.1000/p{i}", "title": f"Paper {i}"} for i in range(n)]
    sheet._write(sheet.table_path(2025, "validate"), sheet.VALIDATE_COLUMNS, rows)


def _buttons(widget):
    status, box = widget.children
    cards = box.children
    return [{b.description: b for b in c.children[3].children} for c in cards], cards


def test_the_widget_saves_each_click_and_moves_on(isolated_folders):
    pytest.importorskip("ipywidgets")
    _table(isolated_folders)
    ui = review.start(2025, find_links=lambda y, d: review.links(d))
    (buttons,), (card,) = _buttons(ui)
    card.children[1].value = "acknowledges the facility"            # reason
    card.children[2].value = "seen on the LSM880"                  # note
    buttons["yes"].click()
    rows = {r["doi"]: r for r in sheet.read_validate(2025)}
    assert (rows["10.1000/p0"]["verdict"], rows["10.1000/p0"]["reason"]) == ("yes", "acknowledges the facility")
    (buttons,), _ = _buttons(ui)
    buttons["skip"].click()                                         # p1 skipped: not saved
    (buttons,), _ = _buttons(ui)
    buttons["no"].click()
    assert [r["verdict"] for r in sheet.read_validate(2025)] == ["yes", "", "no"]
    assert "All 3 reviewed" in ui.children[0].value
    again = review.start(2025, find_links=lambda y, d: review.links(d))    # reloaded: only p1 is left
    assert "1 of 1 left" in again.children[0].value


def test_the_widget_shows_several_papers_at_once(isolated_folders):
    pytest.importorskip("ipywidgets")
    _table(isolated_folders, n=5)
    ui = review.start(2025, at_once=2, find_links=lambda y, d: review.links(d))
    buttons, cards = _buttons(ui)
    assert len(cards) == 2
    buttons[0]["likely"].click()
    assert len(ui.children[1].children) == 2 and "5 of 5 left" in ui.children[0].value   # waits for the second
    buttons[1]["no"].click()
    assert "3 of 5 left" in ui.children[0].value


def test_the_widget_needs_the_table(isolated_folders):
    pytest.importorskip("ipywidgets")
    with pytest.raises(SystemExit, match="run the 'Rank' step"):
        review.start(2024)
