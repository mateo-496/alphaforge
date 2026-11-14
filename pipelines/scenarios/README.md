# Scenario pipeline

Kept deliberately small, so a run is fast and predictable:
1. Code fetches 4 ranked risk reports (Eurasia Group Top Risks, BlackRock Geopolitical Risk Dashboard, the CFR
   Preventive Priorities Survey, Atlantic Council Global Foresight). It keeps the paragraphs that discuss risks,
   up to 7,000 characters per source.
2. Code downloads the Caldara–Iacoviello GPR index and keeps a 15-row table of the countries with the highest
   z-score against their own history.
3. One Bedrock call (`agents/scenario_agent.py`, no tool loop) writes the 12 global scenarios, or the 5 most
   dangerous for one country. The input is about 30k characters.
4. Code checks every quote word for word against its source text, and drops scenarios without a verified quote.

Speed: the 4 sources and the GPR download run in parallel. During a run, the global and country sets are written
in parallel. Output is kept short: summaries are capped at 350 characters (clipped by code if needed), with at most
4 sector shocks and 2 signposts per scenario. The scenario writer has its own model setting, `SCENARIO_MODEL_ID`,
which defaults to `BEDROCK_MODEL_ID`. Each query file records `llm_seconds`, so you can compare models.

Citations: each scenario keeps up to 3 verified quotes, one per source. In the report, every source appears once
under "Annexes: sources" with a letter, and the scenario cards link to those letters.

Source texts and the GPR table are cached per week in `scenarios/inputs/<week>/`, so regenerating does not
download them again. Edit `SOURCES` in `tools/scenario_sources.py` to change sources.

## When it runs
- **Weekly:** an EventBridge Scheduler rule runs `python -m pipelines.scenarios.run --scope global`.
- **On demand:** a portfolio run regenerates a scope if its `latest.json` is older than `SCENARIO_MAX_AGE_DAYS` (7) or missing. This covers the first request for a country.

## Moving average
Each run is merged into the previous set:

$$x_t = \alpha\, x_{\text{new}} + (1-\alpha)\, x_{t-1}, \quad \alpha = 0.35 \ (\texttt{SCENARIO\_ALPHA})$$

This applies to likelihood, impact, country intensities and sector shocks.
- **Identity:** the agent is given last week's ids and told to reuse them. A name-similarity fallback catches renames.
- **New scenarios:** they enter at their fresh values.
- **Missing scenarios:** they decay by $(1-\alpha)$ per week and are dropped after 3 weeks.
- **Text fields:** the name, summary and signposts come from the newest run.

## Storage (every query is kept)
```
scenarios/queries/<UTC>_<scope>.json   full prompt (what the model saw), sources status, GPR table, raw draft, merged result
scenarios/inputs/<week>/*.json         fetched source texts + GPR table
scenarios/<scope>/<YYYY-Www>.json      merged set for the week
scenarios/<scope>/latest.json
```
`STORAGE=s3 S3_BUCKET=<bucket>` writes to S3. Otherwise files go to `./data/`.

## Real agent by default
Scenarios always come from the Bedrock agent (`SCENARIO_USE_MOCK=0`, the default), even when `USE_MOCK=1` keeps
company and country data mocked. `SCENARIO_USE_MOCK=1` is an offline test mode only. Its sets are tagged, and real
mode never shows, reuses or merges them.

If the agent fails during a portfolio run, the report still renders: it uses the newest earlier set, or shows none
with the error in the progress log. Use "Regenerate scenarios" under the map to retry.

## Run
```bash
USE_MOCK=0 python -m pipelines.scenarios.run --force                # global, real agent (Bedrock + web)
USE_MOCK=0 python -m pipelines.scenarios.run --country TWN
USE_MOCK=0 STORAGE=s3 S3_BUCKET=alphaforge-data python -m pipelines.scenarios.run
pytest tests/test_scenarios_merge.py
```

## Point in time
Sources are fetched live, so a set reflects the week it was generated. A portfolio analysed at a past date uses the newest set generated on or before that date. If no such set exists, the page uses the latest set and flags the look-ahead.
