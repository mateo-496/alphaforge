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

## Mocks
Everything the agents will produce is in `mock.py`, and `pipeline.py` calls it through `_mock_asset_report` and `_mock_country_report`. Replace those with `agents/*.run` and keep the same shapes. Risk numbers come from `tools/risk_math` in every case.
