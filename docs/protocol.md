# Protocol: the facility publication finder

Read this before changing anything. It records the aim, the design decisions, how the yearly
loop runs, what was measured, and the traps. Detailed history with paper-level results is kept
privately by the facility (`notes/` in the facility's private copy; never published).

## 1. Aim

A core facility is evaluated on the publications that used it, but users forget to report them.
The goal is a yearly, mostly automatic list of papers that used the facility:

* papers that **acknowledge** the facility → report them;
* papers that **used its instruments without acknowledging it** → confirm, then contact the authors;
* with the evidence for every call, so a person confirms each one in seconds.

It is a **discovery** tool: it proposes, people confirm. Minimise human work; never publish
anything private.

## 2. Decisions (do not re-litigate)

* **Three places.**
  * **Public repository**: the code, the notebooks, the protocol, and one folder per facility
    (`facilities/<facility>/`) with the rules (`facility.yaml`), the **confirmed papers**
    (`papers/<year>.yaml`: DOI and public metadata only).
  * **The facility's Google Drive** (`PUBS_DATA`): candidate sets, screening results, full text,
    embeddings, and per year the decisions (`validate.csv`) and the corresponding-author
    e-mail addresses (`contacts.csv`).
  * **Temporary Colab disk** (`PUBS_PRIVATE`): private inputs (bookings export, staff list) and
    everything derived from them; never in Drive or git.
* **Never in the repository**: full text, text excerpts, e-mail addresses, author names of
  candidate papers, private inputs, rejected candidates, or which papers did not acknowledge
  the facility. Tests and code comments use synthetic text and synthetic DOIs (only confirmed
  papers may be named). The *Add papers* issues keep only DOIs and years.
* **Contacts, minimally**: corresponding authors and e-mail addresses are looked up only for
  confirmed and validated papers, and exist only in the facility's Drive (`contacts.csv`), for writing to the
  authors about their own paper (thanks, acknowledgement reminders). The addresses were not given
  by the authors: the first message says where the address comes from, why, and how to opt out;
  keep a do-not-contact list; delete the file after a campaign.
* **Transferable**: everything facility-specific is YAML in `facilities/<facility>/` (search words,
  instruments, techniques, institutional repositories, e-mail domains, postal patterns). Another
  facility copies `facilities/template/` and sets `PUBS_FACILITY`.
* **Rules are the core**; the embedding check list ranks what the rules rank low. Model output is
  never ground truth: staff verdicts are.
* **The confirmed papers are the known set**: the benchmark for each year and the seed set of the
  embedding ranking. They grow with every validation round.
* **Private inputs never change published or validated outputs**; they only add a private score
  (`data/<year>/private/`).
* **Measured defaults win over plausible ones.** A new source or resolver stays optional until it
  has shown extra facility papers on a real year.
* AIC-specific (owner's decisions): the Institute of Biomedicine Imaging Center and the Medisiina
  Imaging Centre are part of AIC; flow cytometry at the former Cell Imaging and Cytometry Core
  counts as AIC use.

## 3. The yearly loop

| step | where | command | output |
|---|---|---|---|
| 1. build the corpus | notebook 1 (once per year, slow, resumable) | `facility-pubs sweep --year Y`, `facility-pubs embed --years ...` | candidates, full text, screening, embeddings (Drive) |
| 2. search | notebook 2 | `facility-pubs rescreen --year Y`, `facility-pubs validate --years Y` | the year screened with the current rules |
| 3. rank | notebook 2 | `workflow.prepare` (top 200 of the check list) | `validate.csv`, most likely first: acknowledged, instrument, check list by rank |
| 4. review | notebook 2 | `review.start`: links to the published version and an open copy; yes (filed), likely (not filed; ask the authors), no, skip; optional reason and note; saved per click, resumable | decisions in `validate.csv` |
| 5. contacts | notebook 2 | `workflow.collect` | `contacts.csv` (one row per e-mail address) + the new "yes" DOIs |
| 6. file | GitHub | an *Add papers* issue with the DOIs (link printed by step 5), ask a coding agent to file it (e.g. assign it to Copilot); merge the pull request once *check papers* is green | `papers/<year>.yaml`, `source: staff-reviewed` |
| 7. learn | notebook 2 | `workflow.learn`: re-rank the other years ("yes" positives, "no" negatives); `workflow.feedback` | better check lists; `feedback.txt` |
| 8. improve the rules | maintainer | `feedback.txt`: "no" reasons → a test + a pattern fix in `facility.yaml`; papers only the check list found → new patterns; yes rate by rank → `TOP_N` | next year's run |

E-mail blast: `contacts.csv` lists the corresponding authors of every confirmed paper of the year
and of those validated yes or likely, one row per address, with their papers and whether each
acknowledges the facility and cites the grant.

## 4. Pipeline (what the code does)

1. **Candidates** (`candidates.py`, `sources.py`): every DOI-bearing record of the year in the
   facility's institutional repositories (`institutional_sources`: adapters `dspace7` and
   `pure_oai`), plus Europe PMC acknowledgement/methods hits for the facility names and grants
   (journal papers and preprints, any affiliation). Snapshot: `<data>/<year>/universe.json`.
2. **Full text** (`fulltext.py`): repository text, deposited PDF, Europe PMC (PMC or preprint),
   Crossref full-text links; OpenAlex only with `OPENALEX_API_KEY`. A text must look like an
   article and belong to the paper (its DOI or ≥ 50 % of the title words). Cached in
   `<data>/cache/`. A row with text is never downgraded by a failed re-fetch.
3. **Screen** (`screen.py`, patterns in `facility.yaml`): acknowledgement, instrument models,
   component fingerprints within ±600 characters of an instrument mention, techniques, credited
   elsewhere, affiliation only (incl. postal addresses), known false-positive contexts,
   paper-level rules (single local author, review, dataset, preprint, non-life-science field).
4. **Score**: a review-order signal with `score_reasons`; priority report (≥ 10 and
   acknowledged), check (≥ 5), low. Datasets are never above low.
5. **Embedding check list** (`embeddings.py`): per paper the 6 most imaging-heavy ~500-character
   chunks with acknowledgement and facility-name sentences removed (`facility_name_terms`);
   `BAAI/bge-small-en-v1.5` (GPU via sentence-transformers if present, else fastembed on the CPU;
   one store per model and backend). Score: logistic regression, confirmed papers of the **other**
   years vs the other swept years' papers (minus their known and rule-flagged papers); with no
   other swept year, mean cosine to the 5 nearest confirmed papers. A TF-IDF score is a second
   column. A year's own confirmed papers are never used to score it (held out); near-duplicates
   (cosine > 0.97, a preprint and its journal version) are left out of training. Saves are atomic
   and resumable; papers validated "yes" count straight away (`extra_known`), and papers validated
   "no" are negatives even when the rules flagged them (`rejected`).
6. **Validation tables** (`sheet.py`, `review.py`, `contacts.py`): see §3. Verdicts are always carried
   over, also for papers that leave the list. Corresponding authors: addresses printed in the
   paper near a correspondence marker, named from the Crossref and local author lists;
   publisher addresses dropped; ambiguous names left blank for staff to fill.
7. **Confirmed papers** (`papers.py`): `add-papers` parses pasted DOIs (links, years, junk lines
   tolerated), fetches metadata (Crossref, Europe PMC), files by year (a year given after the
   DOI wins; it also moves an already-filed paper), merges duplicates, sorts; unresolved DOIs
   are reported, not filed. `check-papers` is the pull-request check: files well formed, only the public
   fields (nothing about whether a paper acknowledged the facility, no notes, no e-mail
   addresses), every new DOI resolves in Crossref. A filed paper says only that the staff
   reviewed it (`source: staff-reviewed`).

Every check list carries `rules_version` (config sha256 + code commit). `validate` prints recall with
a 95 % Wilson interval.

## 5. Adapting to another facility

1. **Fork** the public repository (your facility folder and papers live in your fork; send code
   improvements back as pull requests). In the fork: *Actions* → enable workflows.
2. Create `facilities/<your-facility>/` with `facility.yaml` (copy `facilities/template/facility.yaml`
   and fill in the `FILL IN` parts; `facilities/aic-turku/facility.yaml` is a complete, commented
   example); set it as the default in `.github/ISSUE_TEMPLATE/add-papers.yml`.
3. `facility-pubs check-facility --facility <your-facility>` shows what was loaded and warns about
   template placeholders left. For DSpace, set `doi_fields` to where your repository keeps DOIs.
4. File the papers you already know in an *Add papers* issue (ask a coding agent to file it, merge).
   They are the benchmark and the seed set of the check list.
5. Set `FACILITY`, `REPO` and `DATA` at the top of both notebooks and run them.
6. Still AIC-specific in the code (optional parts): the OpenIRIS bookings import (resource map in
   `facility.yaml` `openiris_resources`) and the facility-website importer (`import-website`, a
   WordPress page).
7. A repository platform other than DSpace 7 or Pure OAI-PMH needs one adapter function in
   `sources.py` and a branch in `candidates.institutional_universe`.

## 6. What was measured (AIC, 2025, 40 papers on the facility website)

| approach | result | verdict |
|---|---|---|
| institutional repositories (green OA) | all 40 website papers have a record; 38 with text | **backbone** |
| instrument model names (from the instrument database) | contain 33 of 38 screenable website papers | high-yield |
| component fingerprints, techniques | supporting evidence; techniques alone score low | kept |
| "credited elsewhere", paper-level rules | removed most instrument false positives | kept |
| generic microscopy keywords | half of all papers | far too broad |
| corresponding e-mail at a local domain as a gate | only 30 of 40 have one | signal, never a gate |
| Europe PMC acknowledgement search alone | 12 of 40 | third net, not a backbone |
| Europe PMC methods search for host-institute names | 39 extra papers, none real (software citations) | not added |
| embedding check list, held out | 2024: top 200 held 19 of 20 known papers with text (TF-IDF 20, term count 17), all 4 rule misses in the top 125; 2025: top 200 held 37 of 38, the 2 rule misses at 110 and 146 | **in the protocol** |
| LLM second opinion (3B on CPU) | works; ~2.5 min per paper; says "yes" where rules say "likely" | removed (not benchmarked; heavy) |
| plan runner, extra discovery channels (Crossref awards, DataCite, OpenAlex), ORCID user recall | no extra facility papers measured (OpenAlex untestable without a key) | removed |

Rules on 2025: recall against the website list 36/40 = 0.90 (95 % CI 0.77–0.96); precision
among flagged papers 0.98 (0.90–1.00) counting "likely" as use, 0.67 (0.53–0.78) counting only
"yes". Labels were drafted, not yet reviewed by facility staff: provisional.

## 7. Traps (each cost time once)

Data access:
* UTUPub returns 403 to Python's default user agent: send a browser-like `User-Agent`.
* UTUPub query that works: `dc.year.issued:Y AND dc.relation.doi:[* TO *]`.
* UTUPub `dc.okm.affiliatedauthor` holds placeholder "Dataimport, …" entries: filter them.
* Pure OAI file links sit in `<dc:identifier type="...">` (with an attribute).
* DOIs come with trailing punctuation, URL suffixes and query strings: normalise them.
* A WordPress publication page may be cached with a stale AJAX nonce: load it with a
  cache-busting query first.
* Europe PMC: `nextCursorMark` can be missing on the last page; decode HTML entities in XML;
  preprint full text needs the PPR id.
* An exhausted API (OpenAlex without a key) must trip a circuit breaker, not retry for minutes.
* Colab: an editable install is importable only after `sys.path` includes the source folder;
  data written to Drive mid-save can be truncated (write atomically).

Text matching:
* Undo PDF line-break hyphenation before matching.
* Acronyms (SIM, STED, FRAP, FLIM, PALM, STORM) must be case-sensitive: `(?-i:...)`.
* False matches seen: software credited to a facility and cited worldwide, the facility as an
  author affiliation (incl. postal addresses and superscript letters), reagent vendors that are
  also microscope makers, newer instrument models with the same prefix, species names, "squared
  residuals", author surnames equal to a product name, "FCS" = fetal calf serum, key-resource
  tables read as one giant sentence.
* Every false match gets a regression test in `tests/test_screen.py` before the pattern changes,
  with synthetic text and a synthetic DOI (never a rejected paper's DOI or verbatim text).

## 8. Ideas not yet implemented (ranked)

1. **Section-aware matching**: keep the Europe PMC XML sections (acknowledgements, methods,
   references, affiliations) instead of stripping tags; count acknowledgements only in their
   section and weight methods above introduction and references.
2. A citable identifier for the facility (RRID) that users quote.
3. Pattern spot checks (10–20 random hits per weak pattern) instead of a large blind sample.
4. Learn the score weights from the accumulated verdicts; embedding and TF-IDF scores as features.
5. A public "what we recognise" page generated from `facility.yaml`, for acknowledgement campaigns.
6. Scopus / Web of Science funding-text search for paywalled papers.
7. Active-learning review order with a stopping rule (as in ASReview), using the verdicts in `validate.csv`.
