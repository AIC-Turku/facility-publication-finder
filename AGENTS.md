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
  and what to do (e.g. a Sheet that cannot be opened is an error, not a new empty Sheet; an
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
* Corresponding-author contacts exist only in the facility's Google Sheet, and only for
  confirmed and validated papers.
* Working data lives in `PUBS_DATA` (the facility's Drive), private inputs in `PUBS_PRIVATE`
  (the temporary Colab disk); neither is ever inside the repository.

## Map

| area | modules |
|---|---|
| facility settings | `config.py` (facility folder, `facility.yaml`) |
| candidates and text | `sources.py`, `candidates.py`, `fulltext.py`, `http.py`, `text.py` |
| screening | `screen.py`, `sweep.py` (resumable year run, cache) |
| confirmed papers | `papers.py` (YAML, inbox), `known.py` (Crossref / Europe PMC metadata) |
| check list | `embeddings.py` |
| validation workbook | `sheet.py` (tables), `contacts.py`, `gsheets.py` (Google Sheets), `validation.py` |
| reports | `report.py` (review sheet, techniques), `provenance.py` (rules version, intervals) |
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
* Never edit `papers/*.yaml` by hand: paste DOIs into `inbox.txt` (the *add papers* Action files them).
