# Facility publication finder

Find the publications that used a core facility, so it can report them without relying on users
to send DOIs. Built for the **Advanced Imaging Core (AIC), Turku Bioscience Centre**; everything
facility-specific is YAML, so another facility can reuse it (see *Adapting*).

It is a **discovery** tool: it proposes papers with their evidence, staff confirm them in a
Google Sheet, and the confirmed DOIs are filed in this repository.

| notebook | what | when |
|---|---|---|
| [1 · Build the corpus](notebooks/1_build_corpus.ipynb) [![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/AIC-Turku/facility-publication-finder/blob/main/notebooks/1_build_corpus.ipynb) | fetch every candidate paper of the chosen years, its full text, screen it, embed it (all in your Google Drive) | once per year; slow, resumable |
| [2 · Find and validate](notebooks/2_find_and_validate.ipynb) [![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/AIC-Turku/facility-publication-finder/blob/main/notebooks/2_find_and_validate.ipynb) | search one year with the current rules, rank it, create the validation Sheet; after validating, collect the confirmed DOIs and re-rank | as often as needed; minutes |

## First time on Colab

* `DATA` (top of each notebook) is a folder in your Google Drive; share it with colleagues who
  run the notebooks, and share the Sheets with the staff who validate.
* The validation Sheet is created in the `DATA` folder (or `SHEETS_FOLDER_ID`).

## The loop

1. **Notebook 1** builds a year: candidates from the institutional repositories and Europe PMC,
   full text, screening with the rules in `facility.yaml`, embeddings. Data stays in Drive.
2. **Notebook 2** creates the year's **Google Sheet**:
   * **Validate**: new papers that acknowledge the facility, papers that name a facility
     instrument without acknowledging it, and the top papers that *read like* facility papers
     (embedding check list), each with the evidence, the corresponding author and e-mail, and a
     `verdict` dropdown (yes / likely / no) and `note`;
   * **Facility papers**: every confirmed paper of the year plus those marked yes/likely, with
     corresponding author, e-mail, and whether the facility and the grant are acknowledged:
     ready for mail merge (Gmail mail merge in Sheets, or the YAMM add-on);
   * **Search misses**: confirmed papers the search did not flag, and why.
3. **Staff validate** in the Sheet: **yes** = filed; **likely** = not filed, e-mail the authors
   and change to yes when they confirm; **no** = not facility use (the note helps the rules).
4. **Notebook 2, section 4** refreshes the Sheet and prints the new confirmed DOIs. **Paste them
   into `facilities/<facility>/inbox.txt`** on GitHub and commit: the *add papers* Action fetches
   their metadata and files them under `papers/<year>.yaml` (duplicates merged, sorted). The other
   years are re-ranked with what was just confirmed.
5. A developer turns "no" verdicts and misses into rule fixes (a test, then a pattern).

## What is where

| | contents |
|---|---|
| this repository (public) | code, notebooks, protocol, and `facilities/<facility>/`: `facility.yaml` (search words, instruments, techniques, repositories), `papers/<year>.yaml` (confirmed DOIs with public metadata), `inbox.txt` |
| your Google Drive (private) | candidate sets, screening results, full-text cache, embeddings, the validation Sheets (with e-mail addresses) |
| the temporary Colab disk | optional private inputs (bookings export, staff list) |

Never in the repository: full text, e-mail addresses, private inputs, rejected candidates, or
which papers did not acknowledge the facility. Contacts are looked up only for confirmed and
validated papers; when writing to authors, say where the address comes from and how to opt out.

## How a paper is found

* **Candidates**: every DOI-bearing record of the year in the institutional repositories (DSpace 7
  or Pure OAI-PMH; UTUPub and Åbo Akademi for AIC) and Europe PMC hits for the facility names and
  grant numbers.
* **Full text**: repository text or PDF, Europe PMC, Crossref links; it must belong to the paper.
* **Rules** (plain term search): acknowledgements (current and historical names, grants),
  instrument models and their component fingerprints (scanner, cameras, lasers, software),
  techniques, imaging credited to another facility, affiliation-only mentions, known false matches,
  paper-level signals (single local author, review, dataset, preprint).
* **Priority**: *report* (acknowledged), *check* (strong instrument evidence, no
  acknowledgement), *low*; every score comes with its reasons.
* **Check list**: a small free embedding model ranks the year's papers by similarity to the
  confirmed papers of the other years (acknowledgement sentences removed), with a word-similarity
  score next to it. Held out on AIC 2024 and 2025, a top-200 list held 19/20 and 37/38 of the
  known papers with text, including every paper the rules missed.

## Command line

```bash
pip install -e ".[embed]"
export PUBS_DATA=/path/to/working-data PUBS_FACILITY=aic-turku
aic-pubs check-facility              # what facility.yaml loads
aic-pubs sweep    --year 2024        # candidates, full text, screening (resumable)
aic-pubs embed    --years 2024 2025  # check list (rank with other swept years)
aic-pubs sheet    --year 2024        # the workbook as CSV (the notebook writes a Google Sheet)
aic-pubs add-papers                  # file the DOIs pasted into the inbox
aic-pubs rescreen --year 2024        # after a rule change
aic-pubs validate --years 2024       # recall against the confirmed papers, with a 95 % interval
aic-pubs coverage                    # rules still cover every instrument in the instrument database?
```

## Adapting to another facility

1. Fork this repository; in the fork enable Actions and give workflows *Read and write*
   permission (*Settings → Actions → General*), so the inbox Action can file papers.
2. Create `facilities/<your-facility>/facility.yaml` from `facilities/template/facility.yaml` (fill
   in the `FILL IN` parts; `facilities/aic-turku/` is a complete example) and an empty `inbox.txt`.
3. `aic-pubs check-facility --facility <your-facility>` (warns about placeholders left).
4. Paste the papers you already know into its `inbox.txt` and commit: they are the benchmark and
   the seed set.
5. Set `FACILITY`, `REPO` and `DATA` at the top of both notebooks.

A repository platform other than DSpace 7 or Pure OAI-PMH needs one small adapter in `sources.py`.

## Maintaining the rules

* New instrument: add its id and a name pattern under `instruments:` (`strong` = distinctive model;
  `weak` = common model, needs ≥ 2 of its components nearby). `aic-pubs coverage` lists instruments
  in the instrument database that have no pattern yet.
* New false match: add a test in `tests/test_screen.py` first (synthetic text and DOI), then fix
  the pattern.
* Repositories fill up with a delay: rebuild a year the following spring.

[`docs/protocol.md`](docs/protocol.md) is the protocol (decisions, the loop, what was measured, traps); [`AGENTS.md`](AGENTS.md) the rules for contributing.
Optional experiment tooling (plan runner, LLM second opinion) is in
[`docs/experiments.md`](docs/experiments.md).
