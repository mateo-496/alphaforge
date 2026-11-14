"""Convert a CSV portfolio to the agent's validated JSON format."""
import argparse
import csv
import io
import json
from pathlib import Path
from typing import Any

from core.market_stress import MarketStressRequest


def convert_portfolio_csv(csv_text: str) -> dict[str, Any]:
    """Convert CSV text with ticker and weight columns to a portfolio object."""
    reader = csv.DictReader(io.StringIO(csv_text.lstrip("\ufeff"), newline=""), strict=True)
    if reader.fieldnames is None or len(reader.fieldnames) != 2 or set(reader.fieldnames) != {"ticker", "weight"}:
        raise ValueError("CSV must have exactly the columns ticker and weight")
    holdings = []
    for row in reader:
        if None in row or any(value is None for value in row.values()):
            raise ValueError(f"Invalid CSV row at line {reader.line_num}")
        holdings.append({"ticker": row["ticker"].strip().upper(), "weight": row["weight"].strip()})
    return MarketStressRequest.model_validate({"holdings": holdings}).model_dump(mode="json")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Convert a portfolio CSV to JSON")
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    if args.input.resolve() == args.output.resolve():
        parser.error("Input and output must be different files")
    portfolio = convert_portfolio_csv(args.input.read_text(encoding="utf-8-sig"))
    args.output.write_text(json.dumps(portfolio, indent=2) + "\n", encoding="utf-8")
