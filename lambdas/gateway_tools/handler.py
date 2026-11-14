"""AgentCore Gateway target: dispatch to tools/*. Parse, call, return only."""
from tools import filings, geopolitics, market

TOOLS = {
    "get_filing_sections": filings.get_filing_sections,
    "get_country_news": geopolitics.get_country_news,
    "get_prices": market.get_prices,
}


def handler(event, context):
    return TOOLS[event["tool"]](**event.get("args", {}))
