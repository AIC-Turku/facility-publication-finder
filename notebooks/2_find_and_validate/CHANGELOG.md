# Changelog - 2_find_and_validate

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

## [1.0.0] - 2026-10-01

### Added
- Steps in order: 1. install the code, 2. connect Google Drive (Colab only), 3. choose the
  settings in a form (facility, working-data folder, the year to review among the years built
  there, check-list size, papers per page, decided papers to show again).
- Runs in Google Colab and locally (JupyterLab, or an app packaged with LabConstrictor).
- Search with the current rules and recall against the confirmed papers; ranking, most likely
  first (acknowledged, facility instrument, then the top 200 of the similarity list).
- Review in the notebook: one or a few papers at a time, with the evidence, a link to the
  published version and to an open copy, buttons yes / likely / no / skip, an optional reason and
  note; saved at each click, resumable; papers marked likely can be shown again.
- `contacts.csv`: the corresponding authors of the confirmed and validated papers, one row per
  e-mail address, for an e-mail blast.
- A link that opens an *Add papers* issue with the confirmed DOIs filled in, for a coding agent to
  file them in a pull request.
- Learning from the decisions (yes as examples, no as counter-examples) and `feedback.txt`, a
  summary for improving the rules and the ranking.
