"""aic-pubs sweep|rescreen|sheet|report|evaluate --year Y;  validate|embed --years Y ...;
aic-pubs add-papers | import-website | check-facility | coverage | export-public (see README)."""
import argparse
import csv
import json
from pathlib import Path

from . import report, sources, sweep
from .config import load
from .sweep import DATA


def _listed(year):
    from .papers import known_dois
    return known_dois(year, data=DATA)


def _users(path):
    if not path:
        return []
    with open(path, newline="", encoding="utf-8") as f:
        return [r.get("name") or next(iter(r.values())) for r in csv.DictReader(f)]


def main(argv=None):
    ap = argparse.ArgumentParser(prog="aic-pubs")
    ap.add_argument("command", choices=["sweep", "website", "report", "review", "evaluate", "coverage", "rescreen", "discover", "user-recall", "run-plan", "compare-plans", "source-health", "probe-doi", "probe-orcid", "validate-users", "strategies", "import-openiris", "label-sheets", "validate", "import-website", "embed", "check-facility", "add-papers", "sheet", "export-public"])
    ap.add_argument("--year", type=int)
    ap.add_argument("--years", type=int, nargs="+", help="years for `validate` and `embed`")
    ap.add_argument("--database", default=None,
                    help="path or git URL of the instrument database, for `coverage` "
                         "(default: facility.yaml facility.instrument_database)")
    ap.add_argument("--users", help="optional CSV with a 'name' column (never commit it)")
    ap.add_argument("--model", default=None, help="model id for `review` (LLM) or `embed` (sentence embedding)")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--crossref-mailto", default=None,
                    help="optional contact email for Crossref polite-pool requests")
    ap.add_argument("--openalex-key", default=None,
                    help="optional OpenAlex API key (or set OPENALEX_API_KEY)")
    ap.add_argument("--plan", help="YAML strategy plan for run-plan")
    ap.add_argument("--plans", nargs="+", help="experiment plan names for compare-plans")
    ap.add_argument("--experiment", help="experiment plan name for source-health")
    ap.add_argument("--output-dir", help="optional output directory for run-plan")
    ap.add_argument("--doi", help="DOI for probe-doi")
    ap.add_argument("--orcid", help="verified ORCID for probe-orcid")
    ap.add_argument("--xlsx", help="OpenIRIS admin export, for `import-openiris`")
    ap.add_argument("--top", type=int, default=100,
                    help="`sheet`: how many embedding check-list papers to include")
    ap.add_argument("--source", default="validated",
                    help="how pasted papers were confirmed, for `add-papers` (validated, website, ...)")
    ap.add_argument("--facility", help="facility folder name under facilities/ or a path "
                                       "(default: $PUBS_FACILITY, else aic-turku)")
    a = ap.parse_args(argv)
    if a.facility:
        import os
        os.environ["PUBS_FACILITY"] = a.facility
        if not os.environ.get("PUBS_DATA") and a.command not in ("add-papers", "check-facility", "export-public"):
            print(f"note: PUBS_DATA is not set, so working data goes to {DATA} - set PUBS_DATA to keep "
                  f"each facility's data apart")
    cfg = load()
    if a.command == "check-facility":
        from .config import facility_dir
        print(f"facility folder: {facility_dir()}")
        print(f"name: {cfg.raw['facility']['name']}")
        for src in cfg.institutional_sources:
            print(f"  source {src['name']}: {src.get('adapter')} {src.get('base_url')}")
        print(f"  {len(cfg.acknowledgement)} acknowledgement patterns, {len(cfg.instruments)} instruments, "
              f"{len(cfg.techniques)} techniques, e-mail domains {', '.join(cfg.email_domains)}")
        from .papers import load_papers
        papers = load_papers()
        print(f"  {len(papers)} confirmed papers in {facility_dir() / 'papers'}")
        text = (facility_dir() / "facility.yaml").read_text(encoding="utf-8")
        todo = text.count("FILL IN") + text.count("example.edu") + text.count("Example City")
        if todo:
            print(f"  WARNING: {todo} template placeholders left (FILL IN / example.edu / Example City)")
        if not papers:
            print("  no confirmed papers yet: paste the ones you know into inbox.txt (they are the benchmark "
                  "and the seed set of the check list)")
        return
    if a.command == "validate":
        from .validation import format_summaries, year_summary
        done, skipped = [], []
        for y in (a.years or [a.year]):
            if (DATA / str(y) / "screened.jsonl").exists():
                done.append(year_summary(y, write_sheet=False))   # the workbook (`sheet`) replaces the old CSV
            else:
                skipped.append(y)
        if done:
            print(format_summaries(done))
        for y in skipped:
            print(f"{y}: not swept yet (no data/{y}/screened.jsonl) - run `aic-pubs sweep --year {y}`")
        return
    if a.command == "import-website":
        from .known import import_website
        print(import_website())
        return
    if a.command == "export-public":
        from .export import export
        if not a.output_dir:
            ap.error("export-public needs --output-dir (a new folder)")
        files = export(a.output_dir)
        print(f"{len(files)} files copied to {a.output_dir}")
        return
    if a.command == "sheet":
        from .sheet import build, read_csv_validate, write_csv
        if a.year is None:
            ap.error("sheet needs --year")
        tabs, inbox = build(a.year, previous=read_csv_validate(a.year), top_n=a.top)
        for path in write_csv(a.year, tabs):
            print("wrote", path)
        print("\nconfirmed (verdict yes), to paste into the inbox:\n" + (inbox or "  none yet"))
        return
    if a.command == "add-papers":
        from .papers import inbox_path, process_inbox
        s = process_inbox(source=a.source)
        print(f"{inbox_path()}: {len(s['added'])} added, {len(s['moved'])} moved to another year, "
              f"{len(s['already_filed'])} already filed, {s['left_in_inbox']} left in the inbox; "
              f"{s['total']} confirmed papers")
        for d in s["added"]:
            print(f"  + {d}")
        return
    if a.command == "embed":
        from .embeddings import DEFAULT_MODEL, format_summary, run
        years = sorted(set((a.years or []) + ([a.year] if a.year else [])))
        if not years:
            ap.error("embed needs --years (or --year)")
        for summary in run(years, model=a.model or DEFAULT_MODEL):
            print(format_summary(summary))
        return
    if a.command == "import-openiris":
        from .bookings import import_openiris
        print(import_openiris(a.xlsx))
        return
    if a.command not in ("coverage", "strategies", "probe-doi", "validate-users") and a.year is None:
        ap.error("--year is required")
    if a.command in ("report", "rescreen", "evaluate", "label-sheets") and \
            not (DATA / str(a.year) / "screened.jsonl").exists():
        print(f"{a.year}: not swept yet (no data/{a.year}/screened.jsonl) - run `aic-pubs sweep --year {a.year}` first")
        return

    if a.command == "validate-users":
        if not a.users:
            ap.error("--users is required for validate-users")
        from .identity import audit_users
        result = audit_users(a.users)
        print(json.dumps(result, indent=2))
        if not result["ok"]:
            raise SystemExit(2)
    elif a.command == "strategies":
        from .pipeline import discovery_strategies, text_strategies
        print("discovery:")
        for name in discovery_strategies.names():
            print(f"  {name}")
        print("text:")
        for name in text_strategies.names():
            print(f"  {name}")
    elif a.command == "probe-doi":
        if not a.doi:
            ap.error("--doi is required for probe-doi")
        from .diagnostics import probe_doi
        print(json.dumps(
            probe_doi(
                a.doi,
                year=a.year,
                openalex_api_key=a.openalex_key,
            ),
            indent=2,
        ))
    elif a.command == "probe-orcid":
        if not a.orcid:
            ap.error("--orcid is required for probe-orcid")
        from .diagnostics import probe_orcid
        print(json.dumps(
            probe_orcid(
                a.orcid,
                a.year,
                openalex_api_key=a.openalex_key,
            ),
            indent=2,
        ))
    elif a.command == "source-health":
        if not a.experiment:
            ap.error("--experiment is required for source-health")
        from .pipeline.health import experiment_health
        print(json.dumps(
            experiment_health(a.year, a.experiment),
            indent=2,
        ))
    elif a.command == "compare-plans":
        if not a.plans:
            ap.error("--plans is required for compare-plans")
        from .pipeline.compare import write_comparison
        rows, path = write_comparison(a.year, a.plans)
        fields = (
            "plan", "target_year_candidates", "with_full_text",
            "target_year_microscopy", "target_year_aic_leads",
            "new_dois_vs_baseline", "new_microscopy_vs_baseline",
            "new_aic_leads_vs_baseline", "new_review_candidates_vs_baseline",
            "seconds",
        )
        print("  ".join(f"{field:>24s}" for field in fields))
        for row in rows:
            print("  ".join(f"{str(row.get(field, '')):>24s}" for field in fields))
        print("wrote", path)
    elif a.command == "run-plan":
        if not a.plan:
            ap.error("--plan is required for run-plan")
        from .pipeline.runner import run_plan
        summary, path = run_plan(
            a.plan,
            a.year,
            users_path=a.users,
            openalex_api_key=a.openalex_key,
            crossref_mailto=a.crossref_mailto,
            limit=a.limit,
            output_dir=a.output_dir,
        )
        print(json.dumps(summary, indent=2))
        print("wrote", path)
    elif a.command == "user-recall":
        if not a.users:
            ap.error("--users is required for user-recall")
        from .pipeline.runner import run_plan
        plan = Path(__file__).resolve().parents[2] / "config" / "plans" / "user_recall.yaml"
        summary, path = run_plan(
            plan,
            a.year,
            users_path=a.users,
            openalex_api_key=a.openalex_key,
            crossref_mailto=a.crossref_mailto,
            limit=a.limit,
            output_dir=a.output_dir,
        )
        print(json.dumps(summary, indent=2))
        print("wrote", path)
    elif a.command == "sweep":
        sweep.run(a.year, limit=a.limit, openalex_api_key=a.openalex_key)
        print(report.summary(a.year, _listed(a.year)))
    elif a.command == "rescreen":
        sweep.rescreen(a.year)
        print(report.summary(a.year, _listed(a.year)))
    elif a.command == "discover":
        from .pipeline.runner import run_plan
        plan = Path(__file__).resolve().parents[2] / "config" / "plans" / "public_discovery.yaml"
        summary, experiment_dir = run_plan(
            plan,
            a.year,
            openalex_api_key=a.openalex_key,
            crossref_mailto=a.crossref_mailto,
            limit=a.limit,
            output_dir=a.output_dir,
        )
        rows = []
        results_path = experiment_dir / "results.jsonl"
        if results_path.exists():
            for line in results_path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    rows.append(json.loads(line))
        legacy_dir = DATA / str(a.year)
        legacy_dir.mkdir(parents=True, exist_ok=True)
        legacy_path = legacy_dir / "discovery_candidates.json"
        report.save_json(rows, legacy_path)
        print(json.dumps(summary, indent=2))
        print("wrote", experiment_dir)
        print("compatibility copy:", legacy_path)
    elif a.command == "website":
        f = cfg.raw["facility"]
        dois = sources.website_list(a.year, f["website_publications"], f["website_core_slug"])
        (DATA / str(a.year)).mkdir(parents=True, exist_ok=True)
        report.save_json(dois, DATA / str(a.year) / "facility_list.json")
        print(f"{len(dois)} DOIs on the facility website for {a.year}")
    elif a.command == "report":
        print(report.summary(a.year, _listed(a.year)))
        llm_path = DATA / str(a.year) / "llm_review.json"
        llm = json.loads(llm_path.read_text()) if llm_path.exists() else None
        print("wrote", report.write_review_csv(a.year, listed=_listed(a.year),
                                               users=_users(a.users), llm=llm))
        table, path = report.technique_table(a.year, _listed(a.year))
        print(f"\n{'technique':26s} {'strength':10s} {'papers':>6s} {'ack AIC':>7s} {'on list':>7s}")
        for t in table:
            print(f"{t['technique']:26s} {t['strength']:10s} {t['papers']:6d} "
                  f"{t['acknowledging_facility']:7d} {t['on_facility_list']:7d}")
        print("wrote", path)
    elif a.command == "review":
        from . import llm
        path = llm.review_year(a.year, model_id=a.model or llm.DEFAULT_MODEL, limit=a.limit)
        print("wrote", path)
    elif a.command == "coverage":
        from . import coverage
        db = a.database or cfg.raw.get("facility", {}).get("instrument_database")
        if not db:
            ap.error("coverage needs --database or facility.instrument_database in facility.yaml")
        print(coverage.report(cfg, coverage.database_path(db)))
    elif a.command == "evaluate":
        from . import llm
        from .labelling import recall_estimate
        print(llm.evaluate(a.year))
        est = recall_estimate(a.year)
        print(est or "  blind sample not filled in yet: `aic-pubs label-sheets` and ask staff to label it")
    elif a.command == "label-sheets":
        from .labelling import write_label_sheets
        review, blind, key = write_label_sheets(a.year)
        print(f"wrote {review}\nwrote {blind} ({sum(v['sampled'] for v in key['strata'].values())} papers, "
              f"strata {key['strata']})")


if __name__ == "__main__":
    main()
