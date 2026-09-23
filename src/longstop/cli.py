"""Command line entry point."""
from __future__ import annotations

import argparse
import json
import random
import sys

from longstop import docs, report
from longstop.edgar.client import ContactNotSet, EdgarClient
from longstop.universe.build import build_announcements, build_universe
from longstop.universe.episodes import DEFAULT_GAP_DAYS


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="longstop")
    sub = parser.add_subparsers(dest="command", required=True)

    build = sub.add_parser("universe", help="build or inspect the deal universe")
    build_sub = build.add_subparsers(dest="stage", required=True)

    stage1 = build_sub.add_parser("announcements", help="stage one, quarterly filing indexes")
    stage1.add_argument("--start", type=int, default=2001)
    stage1.add_argument("--end", type=int, default=2025)

    stage2 = build_sub.add_parser("outcomes", help="stage two, outcome labels from submissions")
    stage2.add_argument("--gap-days", type=int, default=DEFAULT_GAP_DAYS)

    build_sub.add_parser("report", help="write results/universe.json and sync the README")

    sample = build_sub.add_parser("sample", help="draw a validation sample for hand checking")
    sample.add_argument("--n", type=int, default=30)
    sample.add_argument("--seed", type=int, default=0)

    terms = sub.add_parser("terms", help="extract deal terms from announcement filings")
    terms_sub = terms.add_subparsers(dest="stage", required=True)
    extract = terms_sub.add_parser("extract", help="read each deal's announcement 8-K")
    extract.add_argument("--since", default="2007-01-01")
    extract.add_argument("--until", default=None)
    extract.add_argument("--limit", type=int, default=None)
    extract.add_argument("--source", choices=("8k", "proxy"), default="8k")
    extract.add_argument(
        "--extractor", choices=("deterministic", "model"), default="deterministic",
        help="deterministic needs no key and no spend. model reads the located "
             "passages with Claude and is measured by the same arithmetic check.",
    )
    extract.add_argument("--model", default=None, help="model id for --extractor model")
    terms_sub.add_parser("report", help="coverage and reconciliation, from what is extracted")

    breaks = sub.add_parser("breaks", help="confirm break candidates against their filings")
    breaks_sub = breaks.add_subparsers(dest="stage", required=True)
    confirm = breaks_sub.add_parser("confirm", help="read every break candidate's 8-K")
    confirm.add_argument(
        "--since",
        default=None,
        help="skip candidates announced before this date. Defaults to the first "
        "year the report found usable 8-K item coverage.",
    )

    args = parser.parse_args(argv)

    try:
        if args.command == "terms":
            from longstop.filings import deal_terms

            if args.stage == "extract":
                from longstop.filings import extractors

                if args.extractor == "model" and not extractors.has_credentials():
                    print(
                        "The model extractor needs credentials. Set ANTHROPIC_API_KEY, "
                        "or run `ant auth login`, then try again.\n"
                        "The deterministic extractor is the default and needs neither.",
                        file=sys.stderr,
                    )
                    return 2
                chosen = extractors.get_extractor(
                    args.extractor,
                    **({"model": args.model} if args.model and args.extractor == "model" else {}),
                )
                stats = deal_terms.extract_all(
                    EdgarClient(), since=args.since, until=args.until,
                    limit=args.limit, source=args.source, extractor=chosen,
                )
            else:
                rows = [
                    json.loads(line)
                    for line in deal_terms.TERMS.read_text().splitlines()
                    if line
                ]
                stats = deal_terms.summarise_terms(rows)
            print(json.dumps(stats, indent=2))
        elif args.command == "breaks" and args.stage == "confirm":
            from longstop.filings.confirm import confirm_all

            since = args.since
            if since is None:
                summary_path = report.RESULTS / "universe.json"
                if summary_path.exists():
                    window = json.loads(summary_path.read_text()).get(
                        "reliable_break_window", {}
                    )
                    year = window.get("first_usable_year")
                    since = f"{year}-01-01" if year else None
            print(json.dumps(confirm_all(EdgarClient(), since=since), indent=2))
        elif args.stage == "announcements":
            stats = build_announcements(EdgarClient(), args.start, args.end)
            print(json.dumps(stats, indent=2))
        elif args.stage == "outcomes":
            stats = build_universe(EdgarClient(), args.gap_days)
            print(json.dumps(stats, indent=2))
        elif args.stage == "report":
            summary = report.summarise(report.load())
            rendered = report.render(summary)
            paths = report.write(summary, rendered)
            print(rendered)
            changed = docs.sync()
            print("\nwritten to " + ", ".join(str(p) for p in paths))
            print("README " + ("updated" if changed else "already in step"))
        elif args.stage == "sample":
            episodes = report.load()
            rng = random.Random(args.seed)
            for episode in rng.sample(episodes, min(args.n, len(episodes))):
                print(json.dumps(episode))
    except ContactNotSet as exc:
        print(str(exc), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
