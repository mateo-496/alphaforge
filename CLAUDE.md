# CLAUDE.md

AlphaForge: geopolitical risk of a portfolio, fitted to an investor profile. See README.md for the pipeline.

## Rules

- **No LLM number enters the score.** LLMs extract facts (verbatim quotes, country lists) or write prose;
  code verifies quotes and computes every number: Cedric's formula `tools/portfolio_score.py` fed by `web/scoring.py`
  (spec: `docs/risk-formula.md`).
- Country splits come from `agents/exposure_agent.py`: tiered fallback chain, every split tagged with its tier.
- **Every LLM call goes through `core/llm.py`** (`ask` or `run_tools`). Never call Bedrock directly: the Tracer
  (tokens, input, output → data/traces + CloudTrail Lake) depends on it. No `temperature`: newer Claude models reject it.
- `core/schemas.py` is the contract between agents, pipeline and templates. Change it deliberately.
- Any agent may fail: the pipeline degrades (factual fallback text, labelled estimates), never crashes.
- Point in time: agents only use data published on or before the analysis date.
- No mock data in the app. Test stubs live in tests/fakes.py and are never imported by the app.
- Do not modify the risk formula files (`tools/risk_math.py`, `risk_calculator.py`, `portfolio_score.py`,
  `portfolio_risk.py`, `weights.py`, `market_inputs.py`, `sovereign_risk.py`, `country_risk_inputs.py`) without being asked.

## Commands

```bash
pip install -r requirements.txt
uvicorn web.app:app --reload --port 8080            # needs .env (see .env.example)
pytest                                              # all tests are offline (stubs live in tests/ only)
python -m agents.filings_agent NVDA --as-of 2026-06-30
python -m pipelines.scenarios [--country TWN] [--force]
python -m agents.exposure_agent NVDA --as-of 2026-11-12   # --warm fills the peer library
python -m agents.filing_risk_agent NVDA --as-of 2026-06-30
python -m agents.country_risk_agent CAN CHN --as-of 2026-11-12
python -m agents.geopolitical_claims_agent TWN --as-of 2026-11-12
python -m agents.source_agent CAN
```

`data/` is gitignored: caches, run state, traces (`DATA_DIR`; on Vercel `/tmp/data`, seeded from the deployed
`data/`; see DEPLOY.md).

Agent answers are saved in `data/agent-cache/` (`core/llm.ask`: exact input incl. model and system prompt;
country notes and drivers: per country), so a rerun or a portfolio sharing countries skips those calls. Filings
(`firms/`, per company and month), exposure splits (`exposure-splits/`, per filing, late answers included) and
scenarios (weekly) have their own caches. `LLM_CACHE=0` forces fresh calls; delete `data/agent-cache/` to reset.

Whole analyses are reused too (`web/app.py`): the same holdings, profile, analysis date and scenario country within
`RUN_CACHE_DAYS` (7) redirect to the finished run (`data/runs/index/<key>.json`). Only complete runs are reused (no
filing still reading, no exposure timeout, no agent failure); a partial run is rerun on the next request. The run
page's "Run this analysis again" button forces a fresh run.

A run reads and saves everything it has not seen yet: no deadline on the filings agents or the filing-text pass by
default (`FILINGS_WAIT_S=0`, `EXPOSURE_TEXT_WAIT_S=0`), so the first run of a new company is slower and every later run
that needs it is instant. Concurrent runs share one read per company. With a positive deadline the rest finishes in
the background and is saved only if the server is still running (`--reload` restarts kill it).
