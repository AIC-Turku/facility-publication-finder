"""`facility-pubs`: the command line of the yearly loop (see README and docs/protocol.md).

Every command takes `--facility` (a folder under facilities/, or a path). The working-data
and private folders come from $PUBS_DATA and $PUBS_PRIVATE (see config.py).
"""
import argparse
import csv
import os
import sys

from .config import data_root, facility_dir, load


def _swept(year: int) -> bool:
    return (data_root() / str(year) / "screened.jsonl").exists()


def _require_swept(years: list[int]) -> None:
    missing = [y for y in years if not _swept(y)]
    if missing:
        sys.exit(f"not swept yet: {', '.join(map(str, missing))} (no screened.jsonl in {data_root()}) - "
                 f"run `facility-pubs sweep --year <year>` first")


def _users(path: str | None) -> list[str]:
    if not path:
        return []
    with open(path, newline="", encoding="utf-8") as f:
        return [r.get("name") or next(iter(r.values())) for r in csv.DictReader(f)]


def cmd_check_facility(a) -> None:
    from .papers import load_papers
    cfg = load()
    print(f"facility folder: {facility_dir()}\nname: {cfg.raw['facility']['name']}")
    for src in cfg.institutional_sources:
        print(f"  source {src['name']}: {src.get('adapter')} {src.get('base_url')}")
    print(f"  {len(cfg.acknowledgement)} acknowledgement patterns, {len(cfg.instruments)} instruments, "
          f"{len(cfg.techniques)} techniques, e-mail domains {', '.join(cfg.email_domains)}")
    papers = load_papers()
    print(f"  {len(papers)} confirmed papers in {facility_dir() / 'papers'}")
    text = (facility_dir() / "facility.yaml").read_text(encoding="utf-8")
    todo = text.count("FILL IN") + text.count("example.edu") + text.count("Example City")
    if todo:
        print(f"  WARNING: {todo} template placeholders left (FILL IN / example.edu / Example City)")
    if not papers:
        print("  no confirmed papers yet: file the ones you know in an Add papers issue "
              "(they are the benchmark and the seed set of the check list)")


def cmd_sweep(a) -> None:
    from . import report, sweep
    from .papers import known_dois
    sweep.run(a.year, limit=a.limit, openalex_api_key=a.openalex_key)
    print(report.summary(a.year, known_dois(a.year)))


def cmd_rescreen(a) -> None:
    from . import report, sweep
    from .papers import known_dois
    _require_swept([a.year])
    sweep.rescreen(a.year)
    print(report.summary(a.year, known_dois(a.year)))


def cmd_validate(a) -> None:
    from .validation import format_summaries, year_summary
    _require_swept(a.years)
    print(format_summaries([year_summary(y) for y in a.years]))


def cmd_report(a) -> None:
    from . import report
    from .papers import known_dois
    _require_swept([a.year])
    listed = known_dois(a.year)
    print(report.summary(a.year, listed))
    print("wrote", report.write_review_csv(a.year, listed, users=_users(a.users)))
    table, path = report.technique_table(a.year, listed)
    print(f"\n{'technique':26s} {'strength':10s} {'papers':>6s} {'ack':>5s} {'confirmed':>9s}")
    for t in table:
        print(f"{t['technique']:26s} {t['strength']:10s} {t['papers']:6d} "
              f"{t['acknowledging_facility']:5d} {t['confirmed']:9d}")
    print("wrote", path)


def cmd_embed(a) -> None:
    from .embeddings import DEFAULT_MODEL, format_summary, run
    for summary in run(sorted(set(a.years)), model=a.model or DEFAULT_MODEL):
        print(format_summary(summary))


def cmd_tables(a) -> None:
    from .sheet import build, read_validate, write_tables
    _require_swept([a.year])
    tables, to_file = build(a.year, previous=read_validate(a.year), top_n=a.top)
    for path in write_tables(a.year, tables):
        print("wrote", path)
    print("\nconfirmed (verdict yes), to file in an Add papers issue:\n" + (to_file or "  none yet"))


def cmd_add_papers(a) -> None:
    from pathlib import Path
    from .papers import add_papers
    s, left = add_papers(Path(a.file).read_text(encoding="utf-8"), source=a.source)
    print(f"{a.file}: {len(s['added'])} added, {len(s['moved'])} moved to another year, "
          f"{len(s['already_filed'])} already filed, {s['not_filed']} not filed, "
          f"{s['dropped_lines']} lines without a DOI dropped; {s['total']} confirmed papers")
    for d in s["added"]:
        print(f"  + {d}")
    for line in left:
        print(f"  ! {line}")


def cmd_check_papers(a) -> None:
    from .papers import check_papers, load_papers
    base = {p["doi"] for p in load_papers(a.base)} if a.base else set()
    new, problems = check_papers(base)
    print(f"{len(new)} new papers")
    for e in new:
        print(f"  + {e['doi']}  {e['year']}  {e.get('source', '')}  {e.get('title', '')}")
    if problems:
        sys.exit("problems:\n" + "\n".join(f"  - {p}" for p in problems))
    print("every new DOI resolves; the files are well formed")


def cmd_import_website(a) -> None:
    from .known import import_website
    print(import_website())


def cmd_import_openiris(a) -> None:
    from .bookings import import_openiris
    print(import_openiris(a.xlsx))


def cmd_coverage(a) -> None:
    from . import coverage
    cfg = load()
    db = a.database or cfg.raw.get("facility", {}).get("instrument_database")
    if not db:
        sys.exit("coverage needs --database or facility.instrument_database in facility.yaml")
    print(coverage.report(cfg, coverage.database_path(db)))


def parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--facility", help="folder under facilities/ or a path (default: $PUBS_FACILITY, "
                                           "else aic-turku)")
    ap = argparse.ArgumentParser(prog="facility-pubs", parents=[common])
    sub = ap.add_subparsers(dest="command", required=True)

    def add(name, func, help_):
        p = sub.add_parser(name, parents=[common], help=help_)
        p.set_defaults(func=func)
        return p

    add("check-facility", cmd_check_facility, "show what facility.yaml loads")
    p = add("sweep", cmd_sweep, "candidates, full text and screening of a year (resumable)")
    p.add_argument("--year", type=int, required=True)
    p.add_argument("--limit", type=int, help="screen only the first N candidates (testing)")
    p.add_argument("--openalex-key", help="OpenAlex API key (or set OPENALEX_API_KEY)")
    add("rescreen", cmd_rescreen, "re-apply the current rules to a swept year").add_argument(
        "--year", type=int, required=True)
    add("validate", cmd_validate, "recall against the confirmed papers, with a 95%% interval").add_argument(
        "--years", type=int, nargs="+", required=True)
    p = add("report", cmd_report, "review sheet (and the private one with private inputs), techniques")
    p.add_argument("--year", type=int, required=True)
    p.add_argument("--users", help="private CSV with a 'name' column (OpenIRIS users)")
    p = add("embed", cmd_embed, "embedding check list of swept years (rank several together)")
    p.add_argument("--years", type=int, nargs="+", required=True)
    p.add_argument("--model", help="sentence-embedding model (default BAAI/bge-small-en-v1.5)")
    p = add("tables", cmd_tables, "the validation tables of a year (validate, contacts, search misses) as CSV")
    p.add_argument("--year", type=int, required=True)
    p.add_argument("--top", type=int, default=200, help="check-list papers to include (default 200)")
    p = add("add-papers", cmd_add_papers, "file the confirmed DOIs listed in a text file")
    p.add_argument("file", help="text with the DOIs (links and other text are fine; a year after a DOI sets it)")
    p.add_argument("--source", default="staff-reviewed", help="how they were confirmed (default: staff-reviewed)")
    add("check-papers", cmd_check_papers, "pull-request check of papers/*.yaml (new DOIs resolve)").add_argument(
        "--base", help="the facility folder before the change (its DOIs are not re-checked)")
    add("import-website", cmd_import_website, "add the facility website's publication lists (AIC)")
    add("import-openiris", cmd_import_openiris, "private OpenIRIS admin export -> bookings").add_argument(
        "--xlsx", required=True)
    add("coverage", cmd_coverage, "rules vs the instrument database").add_argument(
        "--database", help="path or git URL (default: facility.instrument_database)")
    return ap


def main(argv: list[str] | None = None) -> None:
    a = parser().parse_args(argv)
    if a.facility:                        # the one place a command-line setting becomes the environment
        os.environ["PUBS_FACILITY"] = a.facility
    a.func(a)


if __name__ == "__main__":
    main()
