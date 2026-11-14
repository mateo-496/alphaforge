import argparse
import json
from agents.risk_agent import analyze_country
from agents.source_agent import discover_sources

def main():
    parser = argparse.ArgumentParser(description="PolyFinance prototype")
    sub = parser.add_subparsers(dest="command", required=True)

    risk = sub.add_parser("risk", help="Assess a country's national risk")
    risk.add_argument("country", help="Country name, e.g. Canada")
    risk.add_argument("--bank", default=None, help="Optional bank identifier")

    sources = sub.add_parser("sources", help="Discover trusted sources for a country")
    sources.add_argument("country")
    sources.add_argument("--limit", type=int, default=10)

    args = parser.parse_args()
    if args.command == "risk":
        result = analyze_country(args.country, bank=args.bank)
    else:
        result = discover_sources(args.country, limit=args.limit)

    print(json.dumps(result, indent=2, ensure_ascii=False))

if __name__ == "__main__":
    main()
