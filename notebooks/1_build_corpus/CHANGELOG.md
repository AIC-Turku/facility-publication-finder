# Changelog - 1_build_corpus

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

## [1.0.0] - 2026-10-01

### Added
- Steps in order: 1. install the code, 2. connect Google Drive (Colab only), 3. choose the
  settings in a form (facility, working-data folder browsed by clicking, years to build).
- Runs in Google Colab and locally (JupyterLab, or an app packaged with LabConstrictor); an
  installed app downloads the latest rules and confirmed papers from GitHub at each start.
- For each year: candidate papers from the institutional repositories and Europe PMC, their full
  text, screening with the facility's rules, and the embedding for the similarity ranking.
  Resumable: an interrupted run continues where it stopped.
- Optional private inputs (OpenIRIS admin export, staff list), kept off Drive and GitHub.
- Default years: the last four (2025–2022).
