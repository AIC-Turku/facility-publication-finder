# Facility publication finder

Find the publications that used a core facility, so it can report them without relying on users
to send DOIs. Built for the **Advanced Imaging Core (AIC), Turku Bioscience Centre**; everything
facility-specific is YAML, so another facility can reuse it (see *Adapting*).

It is a **discovery** tool: it proposes papers with their evidence, staff review them one by one
in a notebook, and the confirmed DOIs are filed in this repository through a pull request.

| notebook | what | when |
|---|---|---|
| [1 · Build the corpus](notebooks/1_build_corpus.ipynb) [![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/AIC-Turku/facility-publication-finder/blob/main/notebooks/1_build_corpus.ipynb) | fetch every candidate paper of the chosen years, its full text, screen it, embed it (all in your Google Drive) | once per year; slow, resumable |
| [2 · Find and validate](notebooks/2_find_and_validate.ipynb) [![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/AIC-Turku/facility-publication-finder/blob/main/notebooks/2_find_and_validate.ipynb) | search one year with the current rules, rank it, review the papers one by one, write the corresponding authors to a CSV, file the confirmed DOIs, learn | as often as needed; minutes plus the review |

## First time

* `DATA` (top of each notebook) is a folder in your Google Drive; share it with the colleagues
  who run the notebooks. Colab asks once per session for access to Drive; nothing else needs a
  login.
* To file papers, the repository needs the [Claude GitHub App](https://github.com/apps/claude)
  installed and one secret (*Settings → Secrets and variables → Actions*):
  `CLAUDE_CODE_OAUTH_TOKEN` (a Claude subscription: `claude setup-token`) or `ANTHROPIC_API_KEY`
  (API, paid per run). Whoever files papers needs write access to the repository.

## The loop

1. **Notebook 1** builds a year: candidates from the institutional repositories and Europe PMC,
   full text, screening with the rules in `facility.yaml`, embeddings. Data stays in Drive.
2. **Notebook 2, rank**: lists the papers to review, **most likely first**: new papers that
   acknowledge the facility, then papers naming a facility instrument without acknowledging it,
   then the top 200 that *read like* facility papers (embedding check list).
3. **Notebook 2, review**: one paper (or a few) at a time, with its evidence, a link to the
   published version and to an open copy (repository record, Europe PMC); open them, come back,
   click **yes** (used the facility: filed), **likely** (not filed; ask the authors),
   **no**, or **skip**, with an optional reason and note. Each click is saved in Drive
   (`<year>/validate.csv`): stop any time, run the cell again to continue.
4. **Notebook 2, contacts and filing**: writes `<year>/contacts.csv`, the corresponding authors of
   the confirmed papers and of those marked yes or likely, one row per e-mail address, for an
   e-mail blast. Prints a link to a new **Add papers** issue with the new "yes" DOIs filled in:
   submit it and comment **`@claude file these`**. The agent files them under
   `papers/<year>.yaml` with their public metadata, marked `source: staff-reviewed`, and opens
   a pull request; its **check papers** check confirms every new DOI resolves (and the files hold
   nothing but public metadata); **merge it** and the issue closes.
5. **Notebook 2, learn**: re-ranks the other years with the decisions ("yes" as examples, "no"
   as counter-examples) and writes `feedback.txt`: how often each kind of candidate was a
   facility paper, how far down the check list papers were still found (to choose `TOP_N`), why
   papers were not facility use, and the papers only the check list found. A maintainer turns
   it into rule fixes (a test, then a pattern).

## What is where

| | contents |
|---|---|
| this repository (public) | code, notebooks, protocol, and `facilities/<facility>/`: `facility.yaml` (search words, instruments, techniques, repositories), `papers/<year>.yaml` (confirmed DOIs with public metadata) |
| your Google Drive (private) | candidate sets, screening results, full-text cache, embeddings; per year `validate.csv` (decisions), `contacts.csv` (e-mail addresses), `search_misses.csv`; `feedback.txt` |
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
facility-pubs check-facility              # what facility.yaml loads
facility-pubs sweep    --year 2024        # candidates, full text, screening (resumable)
facility-pubs embed    --years 2024 2025  # check list (rank with other swept years)
facility-pubs tables   --year 2024        # validate.csv, contacts.csv, search_misses.csv (verdicts kept)
facility-pubs add-papers dois.txt         # file the confirmed DOIs listed in a file
facility-pubs check-papers --base <dir>   # the pull-request check: new DOIs resolve, public metadata only
facility-pubs rescreen --year 2024        # after a rule change
facility-pubs validate --years 2024       # recall against the confirmed papers, with a 95 % interval
facility-pubs coverage                    # rules still cover every instrument in the instrument database?
```

## Adapting to another facility

1. Fork this repository; in the fork enable Actions, install the
   [Claude GitHub App](https://github.com/apps/claude) and add the secret (see *First time*).
2. Create `facilities/<your-facility>/facility.yaml` from `facilities/template/facility.yaml` (fill
   in the `FILL IN` parts; `facilities/aic-turku/` is a complete example), and set your facility
   as the default in `.github/ISSUE_TEMPLATE/add-papers.yml`.
3. `facility-pubs check-facility --facility <your-facility>` (warns about placeholders left).
4. File the papers you already know in an *Add papers* issue: they are the benchmark and the
   seed set.
5. Set `FACILITY`, `REPO` and `DATA` at the top of both notebooks.

A repository platform other than DSpace 7 or Pure OAI-PMH needs one small adapter in `sources.py`.

## Maintaining the rules

* New instrument: add its id and a name pattern under `instruments:` (`strong` = distinctive model;
  `weak` = common model, needs ≥ 2 of its components nearby). `facility-pubs coverage` lists instruments
  in the instrument database that have no pattern yet.
* New false match: add a test in `tests/test_screen.py` first (synthetic text and DOI), then fix
  the pattern.
* Repositories fill up with a delay: rebuild a year the following spring.

[`docs/protocol.md`](docs/protocol.md) is the protocol (decisions, the loop, what was measured,
traps); [`AGENTS.md`](AGENTS.md) holds the rules for contributing.
