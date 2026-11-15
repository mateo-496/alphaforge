# Web

FastAPI + Jinja templates + htmx + D3 for the map. No JS build step. htmx, D3, topojson, the world map and the fonts are bundled in `static/`, so the demo works offline.

    uvicorn web.app:app --reload --port 8080      # from the repo root -> http://localhost:8080

Port 8080 because the shared MCP server (`python -m tools.mcp_server`) uses 8000. The website does not need the
MCP server: it calls the same tool functions in-process.

Settings (`.env`):
- `SEC_IDENTITY="AlphaForge Datathon you@yourdomain.com"`: a real email, which the SEC requires. Without it, every
  exposure falls back to "estimated".
- `S3_BUCKET`: optional. With it, market data is cached in S3 for 24 h; without it, under `data/market-cache/`.
- `BEDROCK_MODEL_ID` (market-stress scoring), `SCENARIO_MODEL_ID` (scenario writer).

Needs the starter data in `data/alphaforge_starter/` (or set `STARTER_DIR`).

## Agent chain (no synthetic data)
| Step | Agent / source |
|---|---|
| 1. Market data & filings | Yahoo prices (1 y) and country revenue from the latest SEC 10-K or 20-F (market-stress tools) |
| 2. Company disclosures | Filings agent: a Strands tool loop over each of the largest equity holdings' SEC filings, `FILINGS_TOP_N` of them (default 5), cached per company and month |
| 3. Market stress | OFR FSI, STLFSI4 and VIX, plus FRED country indicators, scored by the market-stress agent |
| 4. Scenarios | Scenario agent, run weekly |
| 5. Country risk | Geopolitical agent: the score is computed from GPR and the scenarios, and the LLM writes the drivers |
| 6. Portfolio risk | `tools/risk_math`, explained by the risk agent (numbers checked by code) |
| 7. Remediation | The remediation agent proposes swaps; code validates and scores them |

Steps 2–4 run in parallel. Each agent fails independently, and the report says what is missing.
Exposure without a filing-based split is an equal split over the countries recorded in
`examples/portfolios.json`, or the listing country, and is marked "estimated" (`web/estimates.py`).

First run of a 25-holding portfolio: roughly 3–5 minutes, mostly SEC lookups and the filings agent.
Repeat runs reuse the caches.

Offline demo / tests: `tests/fakes.py` stubs the network, the SEC and Bedrock (`pytest tests/test_pipeline_agents.py`).

## Flow
1. `GET /`: portfolio (CSV or table), persona, preferences, analysis date.
2. `POST /runs`: validates into `AnalysisRequest`, runs profile checks, creates a run, starts `pipeline.run` in the background, redirects to the run page.
3. `GET /runs/{id}`: the page polls `GET /runs/{id}/events?after=<seq>` every 400 ms and animates each asset and country as it is analysed.
4. When the status is `done`: it loads `GET /runs/{id}/result` (report HTML) and `GET /runs/{id}/scenarios.json` (map data).

## Where data lives (`store.py`)
| Data | Lifetime | Local | AWS |
|---|---|---|---|
| Run: request, status, event log, result | one per request | `data/runs/<id>/run.json` | DynamoDB |
| Asset and country reports from the agents | shared across runs, keyed `<ticker or ISO3>_<as_of>` | `data/cache/{assets,countries}/` | S3 `cache/` |
| Scenarios | recomputed weekly | `data/cache/scenarios/latest.json` | S3 `scenarios/<week>.json` + EventBridge |

## Mocks
Everything the agents will produce is in `mock.py`, and `pipeline.py` calls it through `_mock_asset_report` and `_mock_country_report`. Replace those with `agents/*.run` and keep the same shapes. Risk numbers come from `tools/risk_math` in every case.
