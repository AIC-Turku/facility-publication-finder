"""Validate a year in the notebook: one or a few papers at a time, with links to the published
version and to an open copy, and buttons for the verdict. Every click is saved at once in
<data>/<year>/validate.csv (sheet.set_verdict), so a session can stop at any time: running the
cell again continues with the papers that have no verdict yet.

    from facility_pubs import review
    review.start(2025, at_once=1)          # Colab / Jupyter (needs ipywidgets; Colab has it)
"""
from collections.abc import Callable, Iterable
import html

from . import sheet


# optional reason, picked before the verdict (sheet.REASONS: what each verdict's reasons mean)
REASON_OPTIONS = [""] + list(dict.fromkeys(r for rs in sheet.REASONS.values() for r in rs))


def pending(rows: list[dict], revisit: Iterable[str] = ()) -> list[dict]:
    """The rows still to decide, in the table's order (most likely first), plus those whose
    verdict is in `revisit` (e.g. ["likely"]: decide again once the authors have answered)."""
    again = {v.strip().lower() for v in revisit}
    unknown = again - set(sheet.VERDICTS)
    if unknown:
        raise ValueError(f"revisit: {', '.join(sorted(unknown))} is not one of {', '.join(sheet.VERDICTS)}")
    return [r for r in rows if r.get("doi") and str(r.get("verdict") or "").strip().lower() in again | {""}]


def links(doi: str, open_copy: str | None = None, pmcid: str | None = None,
          preprint: str | None = None) -> list[tuple[str, str]]:
    """[(label, url)]: the published version (DOI), then any open copy: the one the sweep read
    (repository record or open-access PDF), Europe PMC (PMC full text), a Europe PMC preprint."""
    out = [("published version (DOI)", f"https://doi.org/{doi}")]
    if open_copy:
        out.append(("open copy", open_copy))
    if pmcid:
        out.append(("Europe PMC full text", f"https://europepmc.org/article/PMC/{pmcid}"))
    if preprint:
        out.append(("Europe PMC preprint", f"https://europepmc.org/article/PPR/{preprint}"))
    seen, unique = set(), []
    for label, url in out:
        if url not in seen:
            seen.add(url)
            unique.append((label, url))
    return unique


def paper_links(year: int, doi: str) -> list[tuple[str, str]]:
    """links() for a paper of `year`: the open copy recorded by the sweep and a Europe PMC
    lookup (network: one request)."""
    from .sources import europepmc_lookup_doi
    from .sweep import cached_text_metadata
    epmc = europepmc_lookup_doi(doi) or {}
    return links(doi, cached_text_metadata(year, doi).get("url"), epmc.get("pmcid"), epmc.get("epmc_id"))


def _card_html(row: dict, found: list[tuple[str, str]], n: int, total: int) -> str:
    e = lambda v: html.escape(str(v or ""))
    a = " &nbsp;·&nbsp; ".join(f'<a href="{e(u)}" target="_blank" rel="noopener">{e(label)}</a>'
                               for label, u in found)
    rank = f" · embedding rank {e(row.get('embedding_rank'))}" if row.get("embedding_rank") else ""
    if row.get("verdict"):
        rank += f" · <b>now: {e(row['verdict'])}</b> {e(row.get('reason'))} {e(row.get('note'))}"
    return (f"<div style='margin-top:8px'><b>{n} of {total} to review</b> · {e(row.get('why'))}{rank}<br>"
            f"<span style='font-size:1.1em'><b>{e(row.get('title'))}</b></span><br>"
            f"<i>{e(row.get('journal'))}</i> · {e(row.get('doi'))} · acknowledges the facility: "
            f"{e(row.get('acknowledges_facility'))}<br>{a}<br>"
            f"<small>{e(row.get('evidence'))[:600]}</small></div>")


def start(year: int, at_once: int = 1, revisit: Iterable[str] = (),
          find_links: Callable[[int, str], list[tuple[str, str]]] = paper_links):
    """The review widget for `year` (display it, or leave it as a cell's last line).
    revisit: verdicts to decide again (e.g. ["likely"]); their current verdict is shown."""
    try:
        import ipywidgets as w
    except ImportError:
        raise SystemExit("the review needs ipywidgets (preinstalled in Colab; elsewhere: pip install ipywidgets)") \
            from None
    if at_once < 1:
        raise ValueError("at_once must be at least 1")
    rows = sheet.read_validate(year)
    if not rows:
        raise SystemExit(f"no {sheet.table_path(year, 'validate')}: run the 'Rank' step for {year} first")
    queue = pending(rows, revisit)
    total = len(queue)
    box, status = w.VBox(), w.HTML()
    state = {"done": 0}

    def card(row, n):
        out = w.HTML(_card_html(row, find_links(year, row["doi"]), n, total))
        reason = w.Dropdown(options=REASON_OPTIONS, description="reason", layout=w.Layout(width="460px"))
        note = w.Text(placeholder="note (optional)", layout=w.Layout(width="460px"))
        buttons = {v: w.Button(description=v, button_style=s, layout=w.Layout(width="90px"))
                   for v, s in (("yes", "success"), ("likely", "info"), ("no", "danger"), ("skip", ""))}
        message = w.HTML()
        panel = w.VBox([out, reason, note, w.HBox(list(buttons.values())), message])

        def pick(verdict):
            def click(_):
                if verdict == "skip":
                    finish(panel, f"<i>skipped (comes back next time)</i>: {html.escape(row['doi'])}")
                    return
                try:
                    sheet.set_verdict(year, row["doi"], verdict, reason.value, note.value)
                except Exception as exc:  # noqa: BLE001 - shown in the card, nothing is lost
                    message.value = f"<span style='color:red'>not saved: {html.escape(str(exc))}</span>"
                    return
                finish(panel, f"<b>{verdict}</b> saved: {html.escape(row.get('title') or row['doi'])}")
            return click
        for v, b in buttons.items():
            b.on_click(pick(v))
        return panel

    def finish(panel, text):
        panel.children = (w.HTML(text),)
        state["done"] += 1
        if all(len(c.children) == 1 for c in box.children):
            show_next()

    def show_next():
        batch = [queue.pop(0) for _ in range(min(at_once, len(queue)))]
        start_n = total - len(queue) - len(batch) + 1
        box.children = [card(r, start_n + i) for i, r in enumerate(batch)]
        status.value = (f"{len(queue) + len(batch)} of {total} left; decisions are saved to "
                        f"{html.escape(str(sheet.table_path(year, 'validate')))}" if batch else
                        f"<b>All {total} reviewed.</b> Run the next cell to update the contacts and "
                        f"file the confirmed papers.")
    show_next()
    return w.VBox([status, box])
