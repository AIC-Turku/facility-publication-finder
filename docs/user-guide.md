# Step-by-step protocol

How to find the publications that used the facility in a given year, confirm them, e-mail
their authors and file them in this repository. Written for facility staff; no programming
needed. [`protocol.md`](protocol.md) explains the method and what was measured;
[`AGENTS.md`](../AGENTS.md) the rules for changing the code.

**In short**: notebook 1 builds a year (once, slow) → notebook 2 ranks it, you review the papers
one by one, it writes the authors' e-mail list and the confirmed DOIs → an *Add papers* issue on
GitHub → a coding agent opens a pull request → you merge it.

| who | does | needs |
|---|---|---|
| **runner** | runs the two notebooks | a Google account with access to the facility's Drive folder |
| **reviewer** | decides yes / likely / no on each paper (often the same person as the runner) | the same Drive folder |
| **filer** | submits the *Add papers* issue, asks the agent, merges the pull request | write access to this GitHub repository |
| **maintainer** | turns the feedback into rule changes | a GitHub account; Python for testing changes |

---

## Part A · One-time setup

### A1. The Drive folder

1. In Google Drive, create a folder for the working data, e.g. `My Drive/AIC-publications`.
2. Share it with every colleague who will run or review (*Share → Editor*). Share it **only inside
   the facility**: it will hold full texts and corresponding-author e-mail addresses.
3. Its path is `DATA` at the top of both notebooks. For a folder in *My Drive* the path is
   `/content/drive/MyDrive/<folder name>`. For a folder a colleague shared with you, first
   *Add shortcut to Drive → My Drive*, then use the same form.

### A2. GitHub

1. The filers need **write access** to this repository (*Settings → Collaborators and teams*).
2. A **coding agent** files the papers. On GitHub: the Copilot coding agent (any model it offers,
   e.g. Claude); an organisation owner enables it for the repository in the organisation's
   Copilot settings. Any other agent that reads `AGENTS.md` works the same way. The
   file `.github/workflows/copilot-setup-steps.yml` installs the package for GitHub's agent;
   nothing else (no key, no secret) is needed in the repository.
3. Without an agent, a filer with Python can run the same command (D5).

### A3. Check the facility settings

Notebook setup cells print what the facility file loads (`facility-pubs check-facility`):

```
facility folder: /content/code/facilities/aic-turku
name: Advanced Imaging Core (AIC), Turku Bioscience Centre
  source utupub: dspace7 https://www.utupub.fi/server/api
  source abo: pure_oai https://research.abo.fi/ws/oai
  12 acknowledgement patterns, 25 instruments, 21 techniques, e-mail domains utu.fi, abo.fi, tuks.fi
  576 confirmed papers in /content/code/facilities/aic-turku/papers
```

Check that the name, the institutional repositories and the number of confirmed papers look
right. A `WARNING: template placeholders left` line means `facility.yaml` still has parts to
fill in (only for a new facility, Part J).

---

## Part B · Build a year (notebook 1)

Once per year, and again the following spring (repositories fill up with a delay). Slow but
resumable: an interrupted run continues where it stopped.

1. **Open** [notebook 1](../notebooks/1_build_corpus.ipynb) with its *Open in Colab* badge (README).
2. **Choose a GPU**: *Runtime → Change runtime type → T4 GPU*. Embedding then takes minutes
   instead of 30–40 minutes. (Free GPUs are not always available; the CPU works too.)
3. **Settings cell**: `FACILITY`, `YEARS` (default `[2025, 2024, 2023, 2022]`), `DATA` (A1),
   `REPO`. Run it.
4. **Setup cell**: run it; Colab asks to **connect to Google Drive**: accept with the account that
   sees the `DATA` folder. It downloads the code and installs it (a minute), then prints the
   facility settings (A3).
5. **Optional private inputs** (leave `UPLOAD_PRIVATE = False` if unsure): an OpenIRIS admin export
   (`.xlsx`) and/or `staff.csv`. They add a private score only; they never leave the Colab session
   and never change what is validated or published.
6. **Fetch, screen and embed**: run it. For each year it
   * collects every DOI-bearing record of the year in the institutional repositories, plus
     Europe PMC papers that name the facility or its grants;
   * fetches each paper's full text (repository copy, Europe PMC, publisher text-mining links)
     and checks it belongs to the paper;
   * screens it with the rules (acknowledgements, instruments, techniques);
   * finally embeds every built year for the similarity ranking.

   About 40–60 min per year for fetching and screening. Leave the tab open. If Colab disconnects
   (it does after a few hours, or when idle), run *Settings*, *Setup* and this cell again: work
   already done is skipped.
7. **Done** when the last line reports the ranking per year (`wrote …/embedding_ranked.csv`).

What it writes in `DATA`: `<year>/` (candidates, screening results), `cache/` (full texts),
`embeddings/` (one file per group of papers and model). All private; never in the repository.

---

## Part C · Review a year (notebook 2)

As often as you like; minutes plus the review itself.

### C1. Start

1. **Open** [notebook 2](../notebooks/2_find_and_validate.ipynb) in Colab (a GPU helps for the
   ranking step but is not needed).
2. **Settings**: `YEAR` (a year built in Part B), `TOP_N = 200` (how many papers of the
   similarity list to review), `AT_ONCE = 1` (papers shown at a time), `DATA`, `REPO`. Run it.
3. **1. Setup**: run it; accept the Drive connection. It always fetches the latest code, rules
   and confirmed papers (including papers merged since your last session).

### C2. Search (section 2)

Run it. It re-applies the current rules to the year (`rescreen`) and compares the result with
the papers already confirmed for that year (`validate`); an illustration:

```
year    listed  found  recall      95% CI  w/ text  new ack  new instr
2025        40     36    0.90   0.77-0.96   36/38        12         25
```

* **listed / found / recall**: of the confirmed papers of the year, how many the rules flag.
* **new ack / new instr**: papers not yet confirmed that acknowledge the facility, or name a
  facility instrument without acknowledging it: these come first in your review.

A year with no confirmed papers yet shows `n/a` for recall: normal for a first round.

### C3. Rank (section 3)

Run it. It ranks the year's papers by how much they read like the facility's confirmed papers
(learning also from your earlier decisions: yes as examples, no as counter-examples; never from
this year's own confirmed papers), then writes the review list `<year>/validate.csv`:

1. new papers that **acknowledge the facility** (best first),
2. new papers that **name a facility instrument** without acknowledging it,
3. the **top `TOP_N`** of the similarity list that the rules did not flag,
4. papers you decided earlier that are no longer candidates (kept with their decision).

Decisions already made are always kept, also when the list changes.

### C4. Review (section 4)

Run the cell. One card per paper:

```
3 of 214 to review · new: facility instrument, no acknowledgement · embedding rank 12
<Title of the paper>
<Journal> · 10.xxxx/xxxxx · acknowledges the facility: no
published version (DOI) · open copy · Europe PMC full text
<evidence: the rule hits and the matching sentences>
reason [ … ]   note [ … ]
[ yes ] [ likely ] [ no ] [ skip ]
```

For each paper:

1. **Read the card**: why it is listed and the evidence (which instrument, which sentence).
2. **Open a link** (new tab): *open copy* or *Europe PMC full text* when present (free to
   read), otherwise *published version*. Look at the **methods** (microscopes, imaging,
   cytometry, image analysis) and the **acknowledgements** (the facility, its former names,
   its infrastructure grants).
3. **Come back and decide**:

   | click | when | effect |
   |---|---|---|
   | **yes** | the work used the facility: acknowledged, or a facility instrument / staff member named, or you know the project | filed in the repository (D); authors in `contacts.csv` |
   | **likely** | probably, but not certain (e.g. an instrument the facility owns, not credited) | not filed; authors in `contacts.csv` with status *likely*, so you can ask them |
   | **no** | not facility use | not filed; teaches the ranking |
   | **skip** | decide later | nothing saved; it comes back next time |

4. Optionally, **before** clicking, pick a **reason** and type a **note**. They are what improves
   the rules and the ranking (Part F):

   | verdict | reasons |
   |---|---|
   | yes | acknowledges the facility · facility instrument or staff named · staff know the project · authors confirmed · other |
   | likely | instrument matches, not credited · imaging matches the facility · other |
   | no | no imaging · imaging done elsewhere · only an affiliation or name match · review or no new data · other |

5. The next paper appears. Every click is **saved in Drive at once**. Stop whenever you like;
   to continue later, run *Settings*, *1. Setup* and this cell again: only undecided papers
   come back.

Tips:

* Several papers at a time: `AT_ONCE = 3` in *Settings*; the next batch appears when all
  three are decided.
* The list is ordered most likely first: the first papers are quick (they acknowledge the
  facility). Deep in the similarity list, most papers are *no*; the feedback (Part F) tells you
  how far down it is still worth going (`TOP_N`).
* Two people can review the same year from two sessions: each click re-reads the file before
  saving. Avoid deciding the same paper twice at the same time.
* **Revisit the *likely* papers** when authors answer: in the review cell set
  `REVISIT = ['likely']` and run it; those papers come back with their current verdict shown.
  Click **yes** if the authors confirmed (reason *authors confirmed*) or **no**.

### C5. Contacts and filing (section 5)

Run it when you have reviewed (all, or a batch). It

1. writes **`<year>/contacts.csv`**: the corresponding authors of every confirmed paper of the
   year and of the papers you marked yes or likely (Part E);
2. prints a **link to a new *Add papers* issue** with the new "yes" DOIs filled in, and the DOIs
   themselves. Continue with Part D.

---

## Part D · File the confirmed papers (GitHub)

1. **Open the printed link** (signed in to GitHub). The *Add papers* form opens with the facility
   and the DOIs filled in. The issue is **public**: it must hold DOIs only (a year after a DOI
   sets its reporting year). Click **Create** (or *Submit new issue*).

   Papers known from elsewhere (an annual report, an e-mail) can be filed the same way:
   *Issues → New issue → Add papers*, paste the DOIs (links and surrounding text are fine).
2. **Ask a coding agent to file it**: on the issue, *Assignees → Copilot* (or mention the agent
   your organisation uses, e.g. "file the papers in this issue"). Following `AGENTS.md`, it
   * runs `facility-pubs add-papers` on the DOIs: fetches public metadata (title, journal, date,
     PubMed / PMC ids) and files each paper under `facilities/<facility>/papers/<year>.yaml`,
     marked `source: staff-reviewed`;
   * opens a **pull request** "Add *N* staff-reviewed papers" (closes the issue on merge);
   * replies on the issue: added, already filed, and DOIs it could not resolve.
3. **Check the pull request**:
   * the **check papers** check must be green: every new DOI resolves in Crossref, the files are
     well formed, and they hold nothing but public metadata;
   * the *Files changed* tab shows only `papers/<year>.yaml` changes, with the right titles.

   If the check is red, its log says why, e.g. `10.xxxx/yyy: does not resolve in Crossref`
   (a typo: correct the DOI in the issue and ask the agent again) or `only public metadata may
   be filed` (the agent added a field: ask it to remove it).
4. **Merge** the pull request. The issue closes. The next notebook session (its *Setup* cell)
   picks up the new papers: they count as confirmed and train the ranking.
5. **Without an agent** (Python 3.11 and a clone of the repository):

   ```bash
   pip install -e .
   facility-pubs add-papers --facility aic-turku dois.txt   # dois.txt: the DOIs, one or more per line
   git switch -c add-papers && git add facilities && git commit -m "Add staff-reviewed papers"
   git push -u origin add-papers                             # then open the pull request on GitHub
   ```

Never edit `papers/*.yaml` by hand, and never put names, e-mail addresses or remarks about a
paper in an issue or pull request.

---

## Part E · E-mail the authors

`<year>/contacts.csv` in the Drive folder, one row per e-mail address:

| column | content |
|---|---|
| `name`, `email` | the corresponding author (found in the paper near the correspondence marker, named from the author list) |
| `status` | *confirmed* (at least one of their papers is confirmed or yes) or *likely* |
| `papers`, `dois`, `titles` | their papers of the year (an author of several papers appears once) |
| `acknowledges_facility`, `grant_cited` | per paper, in the same order: yes / no / unknown |

Rows with an empty `email` are papers where no address was found: look it up in the paper if
you want to write to them.

1. **Download** the file (or *Open with → Google Sheets*, which makes a copy). The file is
   rewritten on every refresh (C5): keep your edits in the copy.
2. Filter as needed: e.g. `status = confirmed` for thank-you messages; `acknowledges_facility`
   containing *no* for acknowledgement reminders; *likely* to ask whether they used the facility.
3. Send with your mail-merge tool (Gmail mail merge in Google Workspace, or an add-on).
4. **Data protection**: the addresses were not given to the facility by the authors. The first
   message should say where the address comes from (the published paper), why it is used, and
   how to opt out. Keep a do-not-contact list, delete the downloaded copies after the campaign,
   and check third-party add-ons with your data protection officer.

---

## Part F · Learn and improve (section 6 of notebook 2)

Run it after a review. It re-ranks the other built years with your decisions, then writes
`feedback.txt` in `DATA`:

```
214 decisions
  acknowledges    12 reviewed: 12 yes, 0 likely, 0 no  (yes 100%)
  instrument      25 reviewed: 6 yes, 9 likely, 10 no  (yes 24%)
  check list     177 reviewed: 9 yes, 4 likely, 164 no  (yes 5%)
check list, yes by embedding rank (where to set TOP_N):
  rank 1-50       6 yes of  50 reviewed
  rank 51-100     2 yes of  50 reviewed
  rank 101-200    1 yes of  77 reviewed
why not facility use (instrument): imaging done elsewhere 6, no imaging 3, (no reason given) 1
9 facility papers found only by the check list (rules to add?):
  2025 rank    3  10.xxxx/...  staff know the project
```

(The numbers above are an illustration.) How to use it:

| part | question it answers | action |
|---|---|---|
| per kind of candidate | how reliable is each kind? | a low *yes* rate for *instrument* means some instrument patterns are too broad |
| yes by rank | how far down the similarity list are facility papers still found? | lower `TOP_N` if the last band has no *yes*; raise it if it still has several |
| why not facility use | which mistakes are most common? | e.g. many *only an affiliation or name match* → the maintainer tightens that rule |
| found only by the check list | what did the rules miss? | the maintainer reads these papers and adds patterns (an instrument, a former facility name, a new grant number) |

Send `feedback.txt` to the maintainer. It contains DOIs of rejected candidates: share it
privately (e-mail, Drive), never in a public issue.

**Maintainer**: for each rule change, add a test with synthetic text in `tests/test_screen.py`,
then change the pattern in `facilities/<facility>/facility.yaml`, open a pull request; after the
merge, run notebook 2 sections 2–3 again (no need to rebuild with notebook 1). New instrument:
add it under `instruments:` (`facility-pubs coverage` lists instruments of the instrument
database without a pattern).

---

## Part G · Calendar

| when | what |
|---|---|
| January–February | notebook 1 for the year just ended; notebook 2: review, e-mail, file |
| any time | notebook 2 again after new papers were filed or rules changed (decisions are kept) |
| when authors answer | notebook 2 with `REVISIT = ['likely']` |
| spring | notebook 1 again for last year (late repository records), then notebook 2 |
| after each round | section 6; feedback to the maintainer |

---

## Part H · Troubleshooting

| message or problem | meaning | what to do |
|---|---|---|
| `<year> is not built yet: run notebook 1` | no screening results for that year in `DATA` | run notebook 1 with that year in `YEARS`; check `DATA` is the same folder in both notebooks |
| `no …/validate.csv: run the 'Rank' step` | the review list was not created yet | run section 3 first |
| `not saved: …` in a card | the Drive file could not be written (connection) | click again; if it persists, re-run *1. Setup* |
| Colab disconnected | session limits | run *Settings*, *Setup* and the cell again; nothing done is lost |
| the review shows no papers | everything is decided | `REVISIT = ['likely']` to go over the likely ones; or raise `TOP_N` and run section 3 |
| Drive errors in *Setup*, or `DATA` looks empty | the Drive connection was refused, or another Google account was chosen | re-run *Setup* and accept with the account that sees the `DATA` folder |
| *check papers* red: `does not resolve in Crossref` | a mistyped or not-yet-registered DOI | correct it in the issue and ask the agent again; very recent DOIs may take a few days |
| *check papers* red: `filed twice` | the same DOI under two years | ask the agent to keep one (give the year after the DOI in the issue) |
| a confirmed paper is filed under the wrong year | Crossref's year differs from the reporting year | new *Add papers* issue with `10.xxxx/yyy 2024` (the year after the DOI moves it) |
| `contacts.csv` lacks an author | no address printed in the paper or not recognised | look it up in the paper; edit your copy |

---

## Part I · What is where

| where | what | who sees it |
|---|---|---|
| this repository (public) | code, notebooks, rules (`facility.yaml`), confirmed papers (`papers/<year>.yaml`: DOI and public metadata, `source: staff-reviewed`) | everyone |
| *Add papers* issues and pull requests (public) | DOIs and years only | everyone |
| the Drive folder `DATA` (private) | candidates, screening results, full texts, embeddings, `validate.csv` (decisions), `contacts.csv` (e-mail addresses), `search_misses.csv`, `feedback.txt` | the people it is shared with |
| the Colab session disk (temporary) | the code, private inputs (bookings, staff list) | you, until the session ends |

Never published: full texts, e-mail addresses, private inputs, rejected candidates, or which
papers did not acknowledge the facility.

---

## Part J · Another facility

Fork the repository and follow *Adapting to another facility* in the [README](../README.md):
copy `facilities/template/`, fill in `facility.yaml` (names, grants, instruments, institutional
repositories), check it with `facility-pubs check-facility`, file the papers you already know
in an *Add papers* issue (they are the benchmark and the seed of the ranking), and set
`FACILITY`, `REPO` and `DATA` in both notebooks. Then start at Part A.
