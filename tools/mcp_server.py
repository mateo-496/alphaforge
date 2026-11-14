"""Shared local MCP server. Run with python -m tools.mcp_server."""
from typing import Any

from dotenv import load_dotenv
from mcp.server.mcpserver import MCPServer

load_dotenv()

from tools import market_data, market_stress, portfolio_csv
from tools.market_cache import cached

server = MCPServer("AlphaForge shared tools")
COUNTRY_SERIES = {
    "US": "DGS10", "CN": "DEXCHUS", "JP": "DEXJPUS", "CA": "DEXCAUS", "GB": "DEXUSUK",
    "AT": "DEXUSEU", "BE": "DEXUSEU", "DE": "DEXUSEU", "ES": "DEXUSEU",
    "FI": "DEXUSEU", "FR": "DEXUSEU", "IE": "DEXUSEU", "IT": "DEXUSEU",
    "NL": "DEXUSEU", "PT": "DEXUSEU",
}


@server.tool(structured_output=True)
def get_market_series(series_id: str, as_of: str, lookback_days: int = 90) -> dict[str, Any]:
    """Fetch a supported market series, filtered by observation date."""
    return cached("market-series", {"series_id": series_id, "as_of": as_of, "days": lookback_days},
                  lambda: market_stress.get_market_series(series_id, as_of, lookback_days))


@server.tool(structured_output=True)
def get_price_history(ticker: str, as_of: str, lookback_days: int = 90) -> dict[str, Any]:
    """Fetch adjusted daily stock prices for a Yahoo Finance ticker."""
    return market_data.get_price_history(ticker, as_of, lookback_days)


@server.tool(structured_output=True)
def get_country_exposures(ticker: str) -> dict[str, Any]:
    """Get disclosed country revenue shares from the latest SEC annual filing."""
    return market_data.get_country_exposures(ticker)


@server.tool(structured_output=True)
def get_country_market_series(country: str, as_of: str) -> dict[str, Any]:
    """Fetch an available country or currency-area indicator, with explicit coverage."""
    series_id = COUNTRY_SERIES.get(country)
    if series_id is None:
        return {"country": country, "status": "unsupported"}
    return {"country": country, "status": "available",
            "series": get_market_series(series_id, as_of)}


@server.tool(structured_output=True)
def calculate_variation(series: dict) -> dict[str, Any]:
    """Calculate changes between the last two observations."""
    return market_stress.calculate_variation(series)


@server.tool(structured_output=True)
def decompose_portfolio(request: dict) -> dict[str, Any]:
    """Decompose portfolio weights by ticker and revenue country."""
    return market_stress.decompose_portfolio(request)


@server.tool(structured_output=True)
def convert_portfolio_csv(csv_text: str) -> dict[str, Any]:
    """Convert portfolio CSV text to a validated portfolio object."""
    return portfolio_csv.convert_portfolio_csv(csv_text)


if __name__ == "__main__":
    server.run(transport="streamable-http", host="127.0.0.1", port=8000, streamable_http_path="/mcp")
