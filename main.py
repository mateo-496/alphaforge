import argparse
import json
import sys
from typing import Any

from agents.risk_agent import analyze_country
from agents.source_agent import discover_sources
from output_example import CountryReport

def main(argv: list[str] | None = None) -> CountryReport | dict[str, Any]:
    parser = argparse.ArgumentParser(description="AlphaForge Sovereign & Financial Risk Engine")
    sub = parser.add_subparsers(dest="command")

    # Risk command
    risk_parser = sub.add_parser("risk", help="Assess national risk and generate CountryReport")
    risk_parser.add_argument("country", help="Target country name (e.g. Canada, United States, Germany)")
    risk_parser.add_argument("--bank", default=None, help="Optional bank identifier")

    # Sources command
    sources_parser = sub.add_parser("sources", help="Discover candidate sources for a country")
    sources_parser.add_argument("country", help="Target country name")
    sources_parser.add_argument("--limit", type=int, default=10, help="Max candidates to retrieve")

    # Support shorthand invocation: `python main.py Canada`
    if argv is None:
        argv = sys.argv[1:]

    # If first arg is not a recognized command or flag, treat it as country for risk assessment
    if argv and argv[0] not in {"risk", "sources", "-h", "--help"}:
        argv = ["risk"] + argv

    args = parser.parse_args(argv)

    if args.command == "sources":
        result = discover_sources(args.country, limit=args.limit)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return result

    # Default to risk assessment producing CountryReport
    country = getattr(args, "country", "Canada")
    bank = getattr(args, "bank", None)
    report: CountryReport = analyze_country(country, bank=bank)
    print(report.model_dump_json(indent=2))
    return report

if __name__ == "__main__":
    main()
