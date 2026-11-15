# Market-stress agent

The [market-stress agent](market_stress_agent.py) analyzes a portfolio using
shared MCP tools and returns sourced market observations and a portfolio
breakdown. It runs independently of the legacy orchestration chain.

## Setup and execution

Set `S3_BUCKET` to a bucket you can read and write, `SEC_IDENTITY` to an
application name and real contact email, and configure AWS credentials for S3
and Bedrock. Install the dependencies in `requirements.txt`. The server and
agent load `.env` at startup without overriding existing environment variables.
`AWS_REGION` and `BEDROCK_MODEL_ID` can override the default region
(`us-east-1`) and model (`us.anthropic.claude-sonnet-4-5-20250929-v1:0`).

From the repository root, start the shared MCP server in one terminal:

```powershell
.\.venv\Scripts\python.exe -m tools.mcp_server
```

The server listens only on `127.0.0.1:8000` at `/mcp`; it has no authentication
and is intended for local development, not direct exposure to a network.
The agent connects to this URL by default; `MCP_SERVER_URL` can override it.

In another terminal, convert the example [portefeuille-test.csv](../portefeuille-test.csv)
and run the agent:

```powershell
.\.venv\Scripts\python.exe -m tools.portfolio_csv .\portefeuille-test.csv .\portefeuille-test.json
.\.venv\Scripts\python.exe -m agents.market_stress_agent .\portefeuille-test.json
```

The CSV requires `ticker` and `weight` columns. Weights must sum to 1 and use a
decimal point; tickers must be Yahoo Finance symbols. The MCP tool
`convert_portfolio_csv` also accepts CSV text and returns a validated portfolio.
The agent consumes the resulting JSON, analyzes the current date and fetches
the latest 90 days of prices and OFR/FRED indicators. Network access and access
to the configured Bedrock model are required. Source, S3 and authorization
errors are reported rather than silently replaced.

## Reports and calculations

The result contains `AgentOutput` reports for global indicators, countries with
available indicators, and each holding, plus a separate portfolio breakdown.
Country reports use synthetic `COUNTRY-XX` entity tickers and ISO alpha-2
country codes. Every claim has a source; numerical values and changes come
from tools. The LLM only assesses claim severity and confidence, which are
subjective, not a calibrated risk score. Changes compare the last two available
observations, which can be days or weeks apart. A relative change is expressed
as a fraction, not a percentage.

Country exposure is the holding weight multiplied by its revenue share, **not**
country market stress. The SEC tool uses the latest 10-K or 20-F and
heuristically parses geographic revenue tables from the filing's XBRL viewer.
Check the cited filing before relying on these results: extraction can miss or
misidentify disclosures. A region is not split into invented country shares;
unreported shares remain unknown. The breakdown includes an `exposure_status`
per ticker. Tables with the oldest year first are skipped because the parser
cannot safely select their latest-year column; if no usable table remains, the
status is `unsupported_fiscal_year_order` and exposure remains unknown.
Conflicting usable tables still require manual review. SEC coverage is limited
to symbols present in its issuer list;
international Yahoo symbols may not match the corresponding SEC ticker.
Global indicators are not attributed to individual countries or companies.

## Sources and cache

The MCP tools retrieve adjusted daily prices through `yfinance`, an unofficial
Yahoo Finance client. Verify that your Yahoo Finance data rights permit the
intended use and S3 storage; the yfinance project describes the API as intended
for personal use. Prices may be delayed or revised; the current day's daily
value can still change while its market is open.

The OFR FSI comes from [OFR](https://www.financialresearch.gov/financial-stress-index/);
STLFSI4 and VIXCLS come from [FRED](https://fred.stlouisfed.org/). Country
indicator coverage is limited to the US 10-year Treasury yield, exchange rates
for CN, JP, CA and GB, and the shared EUR/USD rate for selected euro-area
countries. The breakdown reports unsupported countries explicitly. EUR/USD
represents the currency area, not the individual country's risk.

Public source results are cached in S3 for 24 hours, with timestamps and source
metadata. Identical queries can be reused by different agents; portfolio
weights are not stored in the cache. Restrict bucket access and configure S3
lifecycle rules if old objects must be physically deleted: the 24-hour expiry
only controls reuse. Country market indicators are fetched once per distinct
country, whereas filings-based revenue exposures are specific to each issuer.

Feeds provide current, potentially revised values rather than historical
publication vintages. Publication delays and revised prices mean the result is
**not** suitable for a point-in-time backtest.

## On the website

`web/market.py` runs the same tools in-process (no MCP server needed) and reuses this agent's
`_claims_from_facts`, `_evaluate` and `_reports`. Differences, required for a live page:
- **Tolerant failures:** a failing ticker, series or SEC lookup is recorded and shown, and never fails the run.
  If LLM scoring fails, the observed values are shown unscored.
- **Parallel holdings:** holdings are fetched in parallel. SEC requests remain rate-limited by the tool's lock.
- **Ticker mapping:** Yahoo symbols are mapped to SEC tickers for the filings lookup (`RY.TO` → `RY`,
  `CNR.TO` → `CNI`). ETFs, gold and crypto are skipped.
- **Analysis date:** prices use the user's analysis date with a one-year window, for return, drawdown and volatility.
- **Exposures feed the risk score:** disclosed SEC country revenue replaces the estimated exposure, and the
  unreported share stays as "Other". Each filing appears in the report's annexes.
- **Cache:** with no `S3_BUCKET`, `tools/market_cache.py` caches on local disk with the same 24-hour rule.
  Set `MARKET_CACHE=s3` to make S3 mandatory.
