# AlphaForge

Geopolitical risk review of an investment portfolio, fitted to the investor's profile (PolyFinances Datathon 2026).
A web form takes the portfolio and profile; agents gather facts; code computes every number
([docs/risk-formula.md](docs/risk-formula.md)); the report explains the score and proposes profile-fitted changes.

## Run

```bash
python -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env          # AWS credentials, model ids, SEC_IDENTITY with a real email
uvicorn web.app:app --reload --port 8080
pytest                        # offline: network, SEC and Bedrock are stubbed in tests/ only
```

No mock data: every figure comes from a live source (SEC, Yahoo, GPR, World Bank, the four risk reports). When a
source fails, the report says so. Each holding's country split is tagged with the tier that produced it.

## Score

Cedric's two-stage formula (`tools/portfolio_score.py`, unchanged), fed only with measured inputs by
`web/scoring.py`: national risk (World Bank → `tools/risk_calculator.py`), geopolitical hazard (GPR percentile),
company disclosures (verified filing flags) and the profile's tolerance. Headline = personalised concern; objective
risk shown next to it; the same formula scores every holding and every country. Details: [docs/risk-formula.md](docs/risk-formula.md).

## Pipeline (`web/pipeline.py`)

| Step | Agents / code | Output | In the score? |
|---|---|---|---|
| 1. Market data & filings | `web/market.py`; **exposure agent** (`agents/exposure_agent.py`, `tools/exposure_priors.py`) | prices; country split w_ic by tier: XBRL → filing text → last year → sector prior → home-bias prior → returns-based, blended with λ | yes (weights) |
| 2. Company disclosures | **filings agent** (tool loop), **filing-risk agent**, via `web/firms.py` | verified channels → f_i; every disclosed risk with a verified quote | A3 yes; risks no |
| 3. Scenarios | **scenario agent** via `pipelines/scenarios.py` (weekly) | what-if E_s, signposts | no |
| 4. Macro & sources | **country risk agent** (World Bank + `tools/risk_calculator.py`), **source agent** | macro M_c per country; notes, official sources | A1 yes |
| 5. Country risk | **geopolitical agent**, **geopolitical claims agent**, `tools/gpr.py` | g_c (code) + driver; verified claims on the GPR history | A2 yes |
| 6. Portfolio risk | `web/scoring.py`; **risk agent** | concern, objective risk, verdict; summary with numbers checked | — |
| 7. Recommendations | `web/recommend.py`; **remediation agent** | code swaps; agent alternatives, validated and re-scored | — |

Steps 2–4 run in parallel. Every agent fails independently; LLM text is never a number in the score, and numbers
an LLM writes in prose are checked against the facts it was given (`agents/risk_agent.check`).
Each agent also runs alone, e.g. `python -m agents.exposure_agent NVDA --as-of 2026-11-12`;
`python -m agents.exposure_agent --warm --as-of 2026-11-12` fills the peer library behind the sector prior.

## LLM calls and audit trail (`core/llm.py`)

Every LLM call goes through `core.llm.ask` (structured output) or `core.llm.run_tools` (tool loop), both on
Bedrock Converse. Each call produces a `Tracer(token_in, token_out, input, output, …)`:

- appended to `data/traces/<day>.jsonl`;
- sent to **CloudTrail Lake** as a custom event (`PutAuditEvents`) when `CLOUDTRAIL_CHANNEL_ARN` is set;
- linked to CloudTrail's own `Converse` management event (logged by AWS by default, without prompt text)
  through `request_id` = the event's `requestID`.

CloudTrail Lake query example:

```sql
SELECT eventData.userIdentity.principalId AS agent, eventData.additionalEventData.tokenIn,
       eventData.additionalEventData.tokenOut, eventData.additionalEventData.bedrockRequestId
FROM <event-data-store-id> WHERE eventData.eventSource = 'alphaforge.llm'
```

IAM: `bedrock:InvokeModel` on the models, `cloudtrail-data:PutAuditEvents` on the channel, S3 read/write if `STORAGE=s3`.

## Layout

```
core/      config, schemas, storage (local | S3, 24 h cache), llm (Bedrock + Tracer)
agents/    exposure, filings, filing_risk, scenario, country_risk, source, geopolitical,
           geopolitical_claims, risk (explanation), remediation
tools/     data access (SEC, Yahoo, FRED/OFR, GPR, World Bank, scenario sources) and risk formulas
pipelines/ scenarios.py: weekly scenario set, merged with last week's
web/       FastAPI + Jinja + htmx + D3 map, no build step
```

Risk formulas kept as they were: `tools/portfolio_score.py` (Cedric's formula, the score), `tools/risk_calculator.py`
(macro score), `tools/risk_math.py` (filing flags f_i and the what-if; its v2 score is no longer the headline),
`tools/portfolio_risk.py`, `tools/weights.py`, `tools/market_inputs.py`, `tools/sovereign_risk.py`,
`tools/country_risk_inputs.py` (tested, not called by the app).
