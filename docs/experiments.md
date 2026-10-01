# Optional tooling: strategy experiments and the LLM

None of this is needed for the yearly run (notebooks 1 and 2: sweep → embed → Sheet → inbox; see the
README). It exists to test whether another source or text route adds AIC papers **before** it is
made a default. Rule of the project: a channel stays optional until it has shown incremental AIC
papers on a real year (see `docs/protocol.md` §6 for what was measured).

## Plan runner

Discovery and text recovery are modular. A YAML plan in `config/plans/` chooses which strategies
run, in which order, and whether text resolution stops at the first validated text
(`first_success`) or tries every resolver (`all`).

| plan | what it adds |
|---|---|
| `baseline.yaml` | institutional records + Europe PMC facility search (≈ the sweep) |
| `public_discovery.yaml` | candidates only, no screening: Europe PMC, Crossref FIRI award numbers, OpenAlex full-text search (`aic-pubs discover`) |
| `user_recall.yaml` | works of every verified user ORCID via OpenAlex (`aic-pubs user-recall`; needs `private/users.csv`) |
| `user_articles_only.yaml` | as above, articles/preprints only, no retracted records |
| `user_smoke.yaml` | fast metadata-only ORCID check |
| `max_recall.yaml` | broader user-year window, DataCite, publisher HTML |
| `resolver_benchmark.yaml` | every text resolver on the same candidates |
| `quality_upgrade.yaml` | keeps searching until a high-quality full text is found |

```bash
aic-pubs strategies                                     # registered modules
aic-pubs validate-users --users private/users.csv       # checks the file, prints no names
aic-pubs run-plan --year 2025 --plan config/plans/baseline.yaml
aic-pubs run-plan --year 2025 --plan config/plans/user_recall.yaml --users private/users.csv
aic-pubs source-health --year 2025 --experiment user_recall   # empty, truncated or failing?
aic-pubs compare-plans --year 2025 --plans baseline user_recall
aic-pubs probe-doi --doi 10.xxxx/...                    # all routes for one DOI
```

Each run writes `data/<year>/experiments/<plan>/` (git-ignored: it is derived from private inputs):
`results.jsonl`, `summary.json`, `plan.json` and `run_manifest.json` (config, plan and input
hashes; completion status).

Rules for fair comparisons:

* Compare with the order-independent `exclusive` and overlap metrics, not `unique_added` (it
  depends on plan order).
* Runs with `--limit` are samples: they cannot claim incremental recall. Resolver metrics can still
  be compared on the same DOI sample.
* A strategy that hits its page cap is marked **incomplete**, never a complete low-yield search.
* Unknown strategy names fail before any network call.
* A private CRIS or green-portal export can be added with the `doi_file` strategy; set
  `authoritative_year: true` only when that export's reporting year is authoritative.
* OpenAlex routes need a free API key (`OPENALEX_API_KEY`); without it they are skipped.
* Publisher landing-page text is validated like any other text; there is no authentication or
  paywall bypass.

Adding a strategy: register one small function in `pipeline/discovery_strategies.py` (returns
DOI-bearing rows, does not screen) or `pipeline/text_strategies.py` (returns one `TextAttempt`),
with a unit test. Text strategies share the sweep's checks (article-like text, belongs to the
paper, Europe PMC preprints).

## LLM second opinion

`aic-pubs review --year Y` (`pip install -e ".[llm]"`) runs a free local model (default `Qwen/Qwen2.5-7B-Instruct`, 4-bit on a
Colab T4) over the leads and writes `data/<year>/llm_review.json` (git-ignored); `report` then adds
its verdict as a column. It is a second opinion only, never ground truth, and has not been
benchmarked against the labels yet (a 3B CPU smoke test took ~2.5 min per lead).

## Embedding check list

Now part of the yearly protocol (`aic-pubs embed`, notebooks 1 and 2): see the README and
`docs/protocol.md` §4 step 5. Options for experiments: `--model` takes another sentence-embedding model
(each model and backend has its own store file, so switching back costs nothing; on the CPU only
models supported by fastembed load); the score functions are in
`aic_pubs/embeddings.py` (`score_year`, `training_sets`).

## Methods near-duplicate matcher

`aic_pubs.methods_match.best_methods_match` compares a methods paragraph with reference texts
(character n-gram Jaccard), for a future comparison with the AIC Methods Generator text. It is not
used in classification.

## Ideas not implemented

Euro-BioImaging access exports, BioImage Archive / IDR, OME metadata, publisher supplementary
material, collaborator graphs, embedding retrieval of methods sections. Add one only if it shows
measured incremental recall.
