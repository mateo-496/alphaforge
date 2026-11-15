# Web

FastAPI + Jinja templates + htmx + D3 for the map. No JS build step. htmx, D3, topojson, the world map and the fonts are bundled in `static/`, so the demo works offline.

    uvicorn web.app:app --reload      # from the repo root -> http://localhost:8000

Needs the starter data in `data/alphaforge_starter/` (or set `STARTER_DIR`).

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

## Agents and mocks
`live.py` calls the real agents for equities with an SEC filing: geographic revenue (SEC), market risk (Yahoo Finance),
filing risk (`agents/filing_risk_agent`, needs the MCP server: `python -m tools.mcp_server`) and country risk
(`agents/country_risk_agent`: World Bank, GPR, financial stress). ETFs, funds, crypto and non-SEC issuers, or any agent
failure, fall back to `mock.py` through `_mock_asset_report` and `_mock_country_report`, and the report then shows the
placeholder note. `USE_REAL_AGENTS=0` forces the mocks, `USE_FILING_RISK_AGENT=0` skips the slow filing-risk agent.
Reports are cached per `<ticker or ISO3>_<as_of>`, so delete `data/cache/` to refresh a day already mocked.
Risk numbers come from `tools/risk_math` in every case.
