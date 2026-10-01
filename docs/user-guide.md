# Step-by-step protocol

How to find the publications that used the facility in a given year, confirm them, e-mail their
authors and file them in this repository. Written for facility staff: **no programming needed**;
every step says what to click and what you should see. [`protocol.md`](protocol.md) explains the
method and what was measured; [`AGENTS.md`](../AGENTS.md) holds the rules for changing the code.

**In short**

```
Notebook 1 (once per year, ~1 h)    build the year: find candidate papers, read them, rank them
        │
Notebook 2 (whenever you want)      review the papers one by one: yes / likely / no
        │                           → contacts.csv: the authors to e-mail
        │                           → a link to file the confirmed papers
GitHub                              submit the issue → the agent prepares the change → you merge
```

| who | does | needs |
|---|---|---|
| **runner** | runs the two notebooks | a Google account that can open the facility's Drive folder |
| **reviewer** | decides yes / likely / no on each paper (often the runner) | the same |
| **filer** | submits the *Add papers* issue, asks the agent, merges | a GitHub account with write access to this repository |
| **maintainer** | turns the feedback into rule changes | a GitHub account; Python |

Contents: [A · one-time setup](#part-a--one-time-setup) ·
[B · build a year](#part-b--build-a-year-notebook-1) ·
[C · review a year](#part-c--review-a-year-notebook-2) ·
[D · file the papers](#part-d--file-the-confirmed-papers-github) ·
[E · e-mail the authors](#part-e--e-mail-the-authors) ·
[F · learn and improve](#part-f--learn-and-improve) · [G · calendar](#part-g--calendar) ·
[H · troubleshooting](#part-h--troubleshooting) · [I · what is where](#part-i--what-is-where) ·
[J · another facility](#part-j--another-facility)

---

## Colab in two minutes

Both notebooks run in **Google Colab**, in your web browser (Chrome or Firefox work best). They also
run on your own computer in JupyterLab (see [Running locally](#running-locally)).

* A notebook is a list of **cells**. Text cells explain; each step is a **code cell** with a title
  such as *1. Install the code* (Colab hides the code; *Show code* reveals it, you never need to
  edit it).
* **Run a cell**: click the round **▶** button at the left of its title, or click the cell and
  press **Shift + Enter**. While it runs, the button spins; when it is done, a green tick appears
  and the output is shown below it.
* **Run the steps in order, top to bottom**, waiting for each one to finish. Do not use
  *Runtime → Run all*: some steps ask you to click something.
* **Settings are chosen with buttons and lists** (step 3 of each notebook), not by editing code.
* Colab gives you a temporary computer (a *runtime*). It is **reset** when you close the tab for
  a while, after about 90 minutes without activity, or after a few hours in total. Nothing is
  lost: the results are in your Google Drive. You just run steps 1–3 again (and click
  *Use these settings* again).
* You do not need to save the notebook.

### Running locally

1. Install Python 3.11 or newer and git.
2. In a terminal:

   ```bash
   git clone https://github.com/AIC-Turku/facility-publication-finder
   cd facility-publication-finder
   pip install -e ".[embed,openiris,notebook]" jupyterlab
   jupyter lab notebooks/
   ```

3. Open a notebook and follow the same steps: step 1 checks the installation, step 2 does
   nothing (no Google Drive), and in step 3 you choose a folder on your computer. To update the
   code later: `git pull` in the repository folder.

An **installed app** (e.g. packaged with LabConstrictor) needs no clone: step 1 downloads the
latest rules and confirmed papers from GitHub into `~/.facility_pubs/` every time (offline, it
uses the last download). Private inputs then go to `~/.facility_pubs/private/`.

---

## Part A · One-time setup

### A1. Create the Drive folder

1. Go to [drive.google.com](https://drive.google.com), signed in with your work Google account.
2. Click **+ New → New folder**, name it e.g. `AIC-publications`, click **Create**. (You can also
   create it from notebook 1, step 3: **Create folder here**.)
3. Share it with the colleagues who will run or review: right-click the folder → **Share** →
   add their addresses as **Editor** → **Send**. Share it **only inside the facility**: it will
   hold full texts and corresponding-author e-mail addresses.
4. A colleague who received the folder: open **Shared with me**, right-click the folder →
   **Organize → Add shortcut** → **My Drive** → **Add**. (Colab only sees *My Drive* and
   *Shared drives*.)

This folder is the **working-data folder**: you choose it in step 3 of both notebooks.

### A2. GitHub (filers only)

1. Create a GitHub account at [github.com](https://github.com) if you do not have one, and ask
   the repository owner for **write access** to this repository.
2. The owner (organisation owner) enables **GitHub's coding agent** (Copilot) for the repository
   in the organisation's Copilot settings. It can use Claude or another model. Any other coding
   agent that reads `AGENTS.md` works the same way. No key or secret is needed in the repository.

---

## Part B · Build a year (notebook 1)

Once per year, and again the following spring (repositories fill up with a delay). It takes
about an hour per year; it can be interrupted and continued.

### B1. Open the notebook and choose a GPU

1. Open this repository's front page on GitHub and click the **Open in Colab** badge next to
   **1 · Build the corpus**. Colab opens the notebook in a new tab.
2. Sign in to Google if asked (top right, **Sign in**), with the account that sees the
   working-data folder.
3. **Before running anything**, choose a GPU (it makes the last step 10× faster): menu
   **Runtime → Change runtime type** → under *Hardware accelerator* select **T4 GPU** → **Save**.
   * If Colab later says *Cannot connect to GPU backend* (free GPUs are sometimes all taken),
     click **Connect without GPU**: everything works, the last step just takes 30–40 min longer.

### B2. Step 1 · Install the code

4. Run **1. Install the code** (▶).
   * The first time, Colab may say **Warning: This notebook was not authored by Google** → click
     **Run anyway**.
   * It downloads the code, the rules and the confirmed papers, and installs them: about a
     minute. It ends with `✅ Code ready: /content/code`.
   * If Colab shows a **Restart session** button or message, click it, then run step 1 again.

### B3. Step 2 · Connect your Google Drive

5. Run **2. Connect your Google Drive**. A window asks **Permit this notebook to access your
   Google Drive files?** → click **Connect to Google Drive** → choose your work account → on the
   permissions page click **Select all** (if offered) → **Continue**. The cell ends with
   `✅ Google Drive connected`.

### B4. Step 3 · Choose the settings

6. Run **3. Choose the settings**. A form appears:

   ```
   Facility        [ aic-turku        ▼]
   Working-data folder …
   Folder  /content/drive/MyDrive
   ┌──────────────────────────────┐
   │ .. (up one level)            │
   │ AIC-publications             │
   │ Documents                    │
   └──────────────────────────────┘
   [ new folder name ] [ + Create folder here ]
   Years to build  [2026 2025 2024 2023 2022 …]   (2025–2022 selected)
   [ ✓ Use these settings ]
   ```

7. **Facility**: keep `aic-turku`.
8. **Working-data folder**: **click** your folder in the list (e.g. `AIC-publications`) to open
   it; the *Folder* line shows where you are. Click **.. (up one level)** to go back. First time
   and no folder yet: type a name next to **Create folder here** and click it.
   * A folder shared by a colleague appears in *MyDrive* once you added the shortcut (A1 step 4).
   * You can also paste a path into the *Folder* line and press Enter.
9. **Years to build**: click a year; **Ctrl-click** (Cmd-click on a Mac) to add or remove years.
   By default the last four years are selected.
10. Click **Use these settings**. You should see `✅ Settings saved: run the next cells.` and
    the facility summary:

    ```
    facility folder: /content/code/facilities/aic-turku
    name: Advanced Imaging Core (AIC), Turku Bioscience Centre
      source utupub: dspace7 https://www.utupub.fi/server/api
      source abo: pure_oai https://research.abo.fi/ws/oai
      12 acknowledgement patterns, 25 instruments, 21 techniques, e-mail domains utu.fi, abo.fi, tuks.fi
      576 confirmed papers in /content/code/facilities/aic-turku/papers
    ```

    Check the facility name and that the number of confirmed papers is not 0. A red message
    says what to fix (e.g. no year chosen). A ⚠️ *not in your Google Drive* warning means you
    picked a folder outside `/content/drive`: its content would be lost; pick a Drive folder.
    If you change a choice later, click **Use these settings** again.

### B5. Step 4 · Optional private inputs

11. Run **4. Optional private inputs** as is (it prints the private folder, *empty*), unless you
    have an **OpenIRIS admin export** (`.xlsx`) or a **staff list** (`staff.csv`, one
    "Lastname, Firstname" per line). They only add a private score; they stay on the temporary
    computer and never reach Drive or GitHub.
    * To use them: **Show code**, change `UPLOAD_PRIVATE = False` to `True`, run the cell, click
      **Choose Files** and select the files. (Locally: copy them into the printed folder first.)

### B6. Step 5 · Fetch, screen and embed

12. Run **5. Fetch, screen and embed**. For each year it prints `=================== 2025` and its
    progress:
    * the candidate papers found (institutional repositories, Europe PMC);
    * fetching and reading their full texts (the longest part, ~40–60 min per year);
    * then the embedding of every built year.
13. **Keep the tab open** and come back now and then (Colab may stop a session nobody looks at).
    You can use other tabs meanwhile.
14. **If it stops** (the runtime was reset, or you see *Runtime disconnected*): click
    **Reconnect** (top right), then run steps **1**, **2**, **3** (click *Use these settings*)
    and **5** again. Work already done is skipped: it continues where it stopped.
15. **Done** when the last lines show, for each year, a summary of the ranking ending with
    `wrote …/<year>/embedding_ranked.csv`. You can close the tab.

Your working-data folder now holds a folder per year, `cache/` (full texts) and `embeddings/`.
Do not move or rename them.

---

## Part C · Review a year (notebook 2)

As often as you like. Setup and ranking take a few minutes; the review takes as long as you want
and can be spread over several days.

### C1. Steps 1–3 · Install, Drive, settings

1. On the repository's front page click the **Open in Colab** badge next to **2 · Find and
   validate**. (No GPU needed.)
2. Run **1. Install the code** and **2. Connect your Google Drive**, as in B2–B3.
3. Run **3. Choose the settings**. Open the **same working-data folder as in notebook 1** (click it
   in the list). The **Year to review** list then shows the years built in that folder; pick
   one (the latest is preselected). If it says *no year is built in this folder yet*, you are in
   the wrong folder or the year still needs notebook 1.
4. Usually keep the other values:
   * **Check-list papers** (200): how many "reads like facility papers" to include;
   * **Papers per page** (1): papers shown at a time in the review (e.g. 3);
   * **Show again**: none (see the tips in C3).
5. Click **Use these settings** and check the summary (as in B4 step 10). Step 1 always takes the
   latest rules and confirmed papers, including those merged since your last session.

### C2. Steps 4–5 · Search and rank

6. Run **4. Search the year**. It applies the current rules and prints a line like this
   (an illustration):

   ```
   year    listed  found  recall      95% CI  w/ text  new ack  new instr
   2025        40     36    0.90   0.77-0.96   36/38        12         25
   ```

   *listed / found / recall*: of the papers already confirmed for the year, how many the rules
   find. *new ack / new instr*: new papers that acknowledge the facility, or name one of its
   instruments: these come first in your review. A year without confirmed papers shows `n/a`.
7. Run **5. Rank**. After a few minutes it prints a summary and `wrote …/2025/validate.csv` (and
   `contacts.csv`, `search_misses.csv`).

### C3. Step 6 · Review

8. Run **6. Review**. A card appears:

   ```
   1 of 214 to review · new: acknowledges the facility · embedding rank 4
   Title of the paper
   Journal · 10.xxxx/xxxxx · acknowledges the facility: yes
   published version (DOI) · open copy · Europe PMC full text
   evidence: the rule hits and the matching sentences …
   reason [            ▼]
   note   [                    ]
   [ yes ]  [ likely ]  [ no ]  [ skip ]
   ```

9. Read **why** the paper is listed (top line) and the **evidence** (the matching instrument or
   sentence).
10. Click a **link**; the paper opens in a **new tab**:
    * **open copy** or **Europe PMC full text** when present: free to read;
    * **published version (DOI)**: the journal's page (may need the university network or VPN).

    In the paper, look at the **Methods** (microscopes, imaging, cytometry, image analysis) and
    the **Acknowledgements** (the facility, its former names, its infrastructure grants). Your
    browser's search (**Ctrl+F**, or **Cmd+F** on a Mac) helps: try the facility's name,
    "imaging", an instrument name.
11. Go back to the **notebook tab** and decide:

    | click | when | what happens |
    |---|---|---|
    | **yes** | the work used the facility: acknowledged, or a facility instrument or staff member named, or you know the project | filed in the repository (Part D); its authors go to `contacts.csv` |
    | **likely** | probably, but you are not sure (e.g. an instrument the facility owns, not credited) | not filed; its authors go to `contacts.csv` as *likely*, so you can ask them |
    | **no** | not facility use | not filed; teaches the ranking |
    | **skip** | you want to decide later | nothing saved; it comes back next time |

12. Optional but very useful: **before** clicking, choose a **reason** in the drop-down and type
    a short **note**. They are what improves the rules and the ranking (Part F).

    | verdict | reasons in the drop-down |
    |---|---|
    | yes | acknowledges the facility · facility instrument or staff named · staff know the project · authors confirmed · other |
    | likely | instrument matches, not credited · imaging matches the facility · other |
    | no | no imaging · imaging done elsewhere · only an affiliation or name match · review or no new data · other |

13. The card shows **saved**, and the next paper appears. Every click is saved in the
    working-data folder at once.
14. **Stop whenever you like**: just close the tab. To continue later: open notebook 2, run steps
    **1**, **2**, **3** (*Use these settings*) and **6** (4 and 5 are not needed again): only the
    papers without a decision come back.
15. When everything is decided the review says **All … reviewed**.

Tips:

* **Most likely first**: the first papers acknowledge the facility and are quick. The deeper you
  go into "reads like facility papers", the more *no*: Part F tells you how far it is worth
  going.
* **Several papers at once**: *Papers per page* 3 in step 3, *Use these settings*, then step 6.
* **Two reviewers** can work on the same year from their own sessions; avoid deciding the same
  paper at the same moment.
* **Changed your mind, or the authors answered about a *likely* paper**: in step 3 select
  **Show again: likely** (or *no* / *yes*), *Use these settings*, run step 6: those papers come
  back with their current decision shown, to decide again. Next time leave *Show again* empty.

### C4. Step 7 · Contacts and the filing link

16. Run **7. Contacts and filing** (after a full review, or after a batch). It shows:

    ```
    Corresponding authors: /content/drive/MyDrive/AIC-publications/2025/contacts.csv
    ➡️ Open the Add papers issue (DOIs filled in)
    10.xxxx/aaaa 2025
    10.xxxx/bbbb 2025
    ```

    * `contacts.csv`: see Part E.
    * The **➡️ link**: see Part D. If it says *no new "yes" verdicts to file*, there is nothing
      to file.
17. Run **8. Learn and improve** (Part F).

---

## Part D · File the confirmed papers (GitHub)

1. **Click the ➡️ link** shown in step 7 (C4). Sign in to
   GitHub if asked.
2. The **Add papers** form opens with the *Facility* and the *DOIs* filled in. Check that the box
   holds **only DOIs** (and years): the issue is **public**. Click **Create** (or **Submit new
   issue**).
   * Papers known from elsewhere (an annual report, an e-mail) can be filed the same way:
     *Issues → New issue → Add papers*, paste the DOIs; links and surrounding text are fine.
3. **Ask the agent**: on the issue page, in the right-hand column, click **Assignees** (the gear)
   → select **Copilot**. (Another agent: follow how your organisation calls it, e.g. a comment
   "please file the papers in this issue".) After a minute the agent reacts on the issue and
   starts a **pull request** (a proposed change). It takes a few minutes; GitHub notifies you
   when it is ready.
4. **Open the pull request** (linked from the issue, or the **Pull requests** tab). Then:
   * If GitHub shows **Workflows awaiting approval** (it does for changes made by the agent),
     click **Approve and run workflows**: this starts the **check papers** check.
   * Wait for the checks: a **green tick** next to *check papers* means every new DOI resolves
     and the files hold nothing but public metadata. A **red cross**: click **Details** to read
     why (Part H).
   * Click the **Files changed** tab: only `facilities/<facility>/papers/<year>.yaml` should
     change, with one entry per new paper (DOI, title, journal, date, `source: staff-reviewed`).
5. **Merge**: if the pull request is a *draft*, click **Ready for review** first; then **Merge
   pull request** → **Confirm merge**. The issue closes by itself.
6. The next notebook session (its step 1) uses the new papers: they count as confirmed and
   train the ranking.

**Without an agent** (someone with Python 3.11 and a clone of the repository):

```bash
pip install -e .
facility-pubs add-papers --facility aic-turku dois.txt   # dois.txt: the DOIs, one or more per line
git switch -c add-papers && git add facilities && git commit -m "Add staff-reviewed papers"
git push -u origin add-papers                             # then open the pull request on GitHub
```

Never edit `papers/*.yaml` by hand, and never put names, e-mail addresses or remarks about a
paper in an issue or a pull request.

---

## Part E · E-mail the authors

1. Go to [drive.google.com](https://drive.google.com) → your working-data folder → the year (e.g.
   `2025`) → **contacts.csv**.
2. Right-click → **Download** (opens in Excel), or right-click → **Open with → Google Sheets**
   (makes a Google Sheets copy next to it). The original is rewritten every time notebook 2
   step 7 runs: **work in your copy**.
3. One row per e-mail address:

   | column | content |
   |---|---|
   | `name`, `email` | the corresponding author (found in the paper near the correspondence marker, named from the author list) |
   | `status` | *confirmed* (one of their papers is confirmed or marked yes) or *likely* |
   | `papers`, `dois`, `titles` | their papers of the year: an author of several papers appears once |
   | `acknowledges_facility`, `grant_cited` | per paper, in the same order: yes / no / unknown |

   A row with an empty `email` is a paper where no address was found: look in the paper if you
   want to write to its authors.
4. Filter (in Sheets: **Data → Create a filter**) for the campaign you want:
   * `status` = *confirmed*: thank-you messages, a request to send the paper;
   * `acknowledges_facility` contains *no*: a friendly reminder of the acknowledgement text;
   * `status` = *likely*: ask whether the work used the facility (then revisit, C3 tip).
5. Send with a mail merge (e.g. Gmail's mail merge in Google Workspace, or an add-on), using
   `name`, `titles` and `dois` as fields.
6. **Data protection**: the authors did not give their address to the facility. The first
   message should say where the address comes from (their published paper), why you write, and
   how to opt out. Keep a do-not-contact list, delete downloaded copies after the campaign, and
   check third-party mail-merge add-ons with your data protection officer.

---

## Part F · Learn and improve

1. Run notebook 2 step **8. Learn and improve** after a review. It re-ranks the other built
   years with your decisions (*yes* as examples, *no* as counter-examples), then prints a report
   and saves it as `feedback.txt` in the working-data folder (an illustration):

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

2. Read it:

   | part | question it answers | what to do |
   |---|---|---|
   | per kind of candidate | how reliable is each kind? | a low *yes* rate for *instrument*: some instrument patterns are too broad (maintainer) |
   | yes by rank | how far down the list are facility papers still found? | no *yes* in the last band: lower *Check-list papers* next time; several: raise it |
   | why not facility use | which mistake is most common? | e.g. many *only an affiliation or name match*: the maintainer tightens that rule |
   | found only by the check list | what did the rules miss? | the maintainer reads these papers and adds patterns (an instrument, a former name, a grant) |

3. Send `feedback.txt` to the maintainer **privately** (e-mail or Drive): it lists DOIs of
   rejected candidates, which must never be published (not in a GitHub issue).

**Maintainer**: for each rule change, first a test with synthetic text in `tests/test_screen.py`,
then the pattern in `facilities/<facility>/facility.yaml`, in a pull request. After the merge,
run notebook 2 steps 1–5 again (notebook 1 is not needed). A new instrument goes under
`instruments:`; `facility-pubs coverage` lists instruments of the instrument database that have
no pattern yet.

---

## Part G · Calendar

| when | what |
|---|---|
| January–February | notebook 1 for the year just ended (select it in step 3); notebook 2: review, e-mail, file |
| any time | notebook 2 again after new papers were filed or the rules changed (decisions are kept) |
| when authors answer | notebook 2: *Show again: likely* in step 3, review (step 6), then steps 7–8 |
| spring | notebook 1 again for last year (late repository records), then notebook 2 |
| after each round | step 8; `feedback.txt` to the maintainer |

---

## Part H · Troubleshooting

| what you see | what it means | what to do |
|---|---|---|
| *Warning: This notebook was not authored by Google* | normal for notebooks opened from GitHub | **Run anyway** |
| *Cannot connect to GPU backend* | no free GPU right now | **Connect without GPU** (slower embedding only) |
| *Restart session* after the installation | Colab updated a package | click it; run step **1** again, then 2 and 3 |
| *Runtime disconnected* / cells lost their ticks | the temporary computer was reset | **Reconnect**; run steps **1–3** (*Use these settings*), then the step you were at; nothing is lost |
| `NameError: name 'settings' is not defined` (or `ui`, `cli`, `CODE`) | a step was run before steps 1–3 | run steps **1**, **2** and **3** first |
| `Choose the settings and click 'Use these settings' (step 3) first.` | step 3 was run but its button not clicked, or a choice changed since | click **Use these settings** in step 3 |
| `Not installed: …` (locally) | the package is not installed in this Python | run the `pip install` line of *Running locally*, restart the notebook |
| Drive errors in step 2, or your folder is not in the list of step 3 | Drive access refused, another account chosen, or a shared folder without a shortcut | run step 2 again and allow access with the right account; add the shortcut (A1 step 4) |
| ⚠️ *this folder is not in your Google Drive* | the chosen folder is on the temporary computer | choose a folder under `/content/drive/MyDrive` |
| *no year is built in this folder yet* (step 3 of notebook 2) | wrong folder, or the year was not built | choose the folder used by notebook 1, or build the year (Part B) |
| `no …/validate.csv: run the 'Rank' step` | the review list does not exist yet | run step **5. Rank** first |
| `not saved: …` on a card | the file in Drive could not be written (connection) | click again; if it persists, run step 2 again |
| the review shows no papers | everything is decided | *Show again: likely* in step 3, or more *Check-list papers* and step 5 again |
| *check papers*: `does not resolve in Crossref` | a mistyped or very new DOI | correct it in the issue and ask the agent again; new DOIs can take a few days to register |
| *check papers*: `filed twice` | the same DOI under two years | ask the agent to keep one |
| *check papers*: `only public metadata may be filed` | the change added other fields | ask the agent to remove them |
| a paper is filed under the wrong year | the publication year differs from the reporting year | new *Add papers* issue with the year after the DOI: `10.xxxx/yyy 2024` (it moves the paper) |
| `contacts.csv` lacks an author's address | no address printed in the paper, or not recognised | look in the paper; add it in your copy |

---

## Part I · What is where

| where | what | who sees it |
|---|---|---|
| this repository (public) | code, notebooks, rules (`facility.yaml`), the confirmed papers (`papers/<year>.yaml`: DOI and public metadata, `source: staff-reviewed`) | everyone |
| *Add papers* issues and pull requests (public) | DOIs and years only | everyone |
| the working-data folder in Drive (private) | per year: candidates, screening results, `validate.csv` (your decisions), `contacts.csv` (e-mail addresses), `search_misses.csv`; `cache/` (full texts), `embeddings/`, `feedback.txt` | the people it is shared with |
| the Colab computer (temporary) | the code, private inputs (bookings, staff list) | you, until the session ends |

Never published: full texts, e-mail addresses, private inputs, rejected candidates, or which
papers did not acknowledge the facility.

---

## Part J · Another facility

Fork the repository and follow *Adapting to another facility* in the [README](../README.md):
copy `facilities/template/`, fill in `facility.yaml` (names, grants, instruments, institutional
repositories), check it with `facility-pubs check-facility`, file the papers you already know in
an *Add papers* issue (they are the benchmark and the seed of the ranking), and change `REPO` in
step 1 of both notebooks to your fork. Your facility then appears in the *Facility* list of
step 3. Then start at Part A.
