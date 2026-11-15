"""Load sample portfolios from examples/portfolios.json (demo / test fixtures)."""
import json
from pathlib import Path

PATH = Path(__file__).resolve().parent.parent / "examples" / "portfolios.json"


def load(path: Path = PATH) -> dict:
    return json.loads(path.read_text())


def get(portfolio_id: str, path: Path = PATH) -> dict:
    """One portfolio: {id, label, profile, holdings[{ticker, weight}], geo_angle, scenarios}."""
    return next(p for p in load(path)["portfolios"] if p["id"] == portfolio_id)


def asset_countries(asset: dict) -> set[str]:
    """Home country + operating countries + ETF look-through hints (ISO3)."""
    return {c for c in [asset.get("country"), *asset.get("ops", []), *asset.get("primary_countries", [])] if c}


def countries(portfolio: dict, assets: dict) -> set[str]:
    return set().union(*(asset_countries(assets[h["ticker"]]) for h in portfolio["holdings"]))


def regions(portfolio: dict, data: dict) -> set[str]:
    cs = countries(portfolio, data["assets"])
    return {r for r, members in data["regions"].items() if cs & set(members)}


def em_weight(portfolio: dict, assets: dict) -> float:
    return sum(h["weight"] for h in portfolio["holdings"] if assets[h["ticker"]]["em"])
