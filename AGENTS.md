# AGENTS.md: how to work on this repository

For coding agents and human contributors. Read [`docs/protocol.md`](docs/protocol.md) before
changing rules or behaviour: it holds the aim, the decisions, the yearly loop, what was measured
and the traps.

## Coding rules

* **Prefer small pure functions with typed inputs/outputs.** Network, disk and Google calls sit at
  the edges and are passed in (e.g. `fetch=`, `contacts=`, `embedder=`), so the logic is testable
  without them.
* **Keep public APIs minimal.** A module exposes what the CLI and the notebooks call; helpers are
  `_private`. Do not add a command, option or module for a one-off need.
* **Raise clear errors on ambiguous or invalid input; never silently guess.** Say what is wrong
  and what to do (e.g. an unknown verdict in validate.csv is an error, not a blank; an
  unknown source adapter is an error, not an empty candidate set).
* **Avoid hidden state and global configuration.** Pass the facility, data folder and config
  explicitly; environment variables (`PUBS_FACILITY`, `PUBS_DATA`, `PUBS_PRIVATE`) are read in
  one place, at the edge, never deep inside logic.
* **Avoid heavyweight dependencies unless they provide demonstrated value.** Core: PyYAML and
  PyMuPDF (deposited PDFs). Extras: `embed` (fastembed, scikit-learn; earned its place on held-out
  years) and `openiris` (openpyxl, for the private bookings import).
* **Notebooks consume package APIs; they are never homes for production algorithms.** A notebook
  cell sets parameters, calls a package function or CLI command, and shows the result.
* **Make the smallest coherent change needed for the task.** No drive-by refactors; one concern
  per commit, with tests.

## Privacy rules (never break these)

* Never commit full text or text excerpts beyond short evidence quotes, e-mail addresses,
  private inputs (bookings, staff or user lists), rejected candidates, or which papers did not
  acknowledge the facility.
* Tests and comments use synthetic text and synthetic DOIs; only confirmed papers
  (`facilities/<facility>/papers/`) may be named.
* Corresponding-author contacts exist only in the facility's Drive (`contacts.csv`), and only for
  confirmed and validated papers.
* Working data lives in `PUBS_DATA` (the facility's Drive), private inputs in `PUBS_PRIVATE`
  (the temporary Colab disk); neither is ever inside the repository.

## Map

| area | modules |
|---|---|
| facility settings | `config.py` (facility folder, `facility.yaml`) |
| candidates and text | `sources.py`, `candidates.py`, `fulltext.py`, `http.py`, `text.py` |
| screening | `screen.py`, `sweep.py` (resumable year run, cache) |
| confirmed papers | `papers.py` (YAML, filing, pull-request check), `known.py` (Crossref / Europe PMC metadata) |
| check list | `embeddings.py` |
| validation | `sheet.py` (validate / contacts / search-misses CSV), `review.py` (notebook review widget), `contacts.py`, `validation.py` (recall, feedback) |
| reports | `report.py` (review table, techniques), `provenance.py` (rules version, intervals) |
| notebook steps | `workflow.py` (what notebook 2 calls) |
| optional | `bookings.py` (private OpenIRIS import), `coverage.py` (rules vs the instrument database) |
| entry points | `cli.py` (`facility-pubs`), `notebooks/1_build_corpus.ipynb`, `notebooks/2_find_and_validate.ipynb` |

Settings come from `config.py` only: `facility_dir()`, `data_root()`, `private_root()` read
`PUBS_FACILITY`, `PUBS_DATA`, `PUBS_PRIVATE` at call time; `load()` validates `facility.yaml`.
The one deliberate piece of process state is the HTTP circuit breaker in `http.py` (a host that
said it is out of budget is not asked again during the run).

## Working

* `pip install -e ".[test]"` then `pytest -q`; CI runs the same on every push.
* A new false match: a regression test in `tests/test_screen.py` first (synthetic text), then the
  pattern in `facilities/<facility>/facility.yaml`.
* Facility-specific values belong in `facility.yaml`, never in code.
* Never edit `papers/*.yaml` by hand: file papers with `facility-pubs add-papers` (below).

## Filing papers from an issue

An *Add papers* issue (`.github/ISSUE_TEMPLATE/add-papers.yml`) holds DOIs the facility staff
have already reviewed and confirmed. When asked to file them (`@claude file these`):

1. Copy the issue's *DOIs* field into a file outside the repository (e.g. `/tmp/issue-<n>.txt`).
   The *Facility* field names the folder under `facilities/`.
2. `facility-pubs add-papers --facility <facility> /tmp/issue-<n>.txt` (it fetches the
   public metadata and files each paper by year, `source: staff-reviewed`; it prints what was
   added, already filed, and any DOI it could not resolve).
3. Commit only `facilities/<facility>/papers/*.yaml` on a new branch and open a pull request
   titled `Add <N> staff-reviewed papers`, with `Closes #<n>` and the list of DOIs, years and
   titles. The *check papers* check then confirms every new DOI resolves; a person merges it.
4. Reply on the issue: added (with years), already filed, and DOIs that did not resolve (ask for
   a corrected DOI; do not guess one).

Do not judge the papers: the staff already did. Never write, in the files, the pull request or
the issue, whether or how a paper acknowledges the facility, or any note, name or e-mail address;
do not open the papers' full text. If the issue holds anything but DOIs and years (a name, an
address, a remark), do not repeat it, and ask the author to edit it out.
