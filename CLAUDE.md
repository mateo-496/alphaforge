# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Architecture

AlphaForge evaluates the geopolitical risk of a portfolio under a scenario and proposes remediation trades. Chain: `Portfolio + InvestorProfile + Scenario -> filings -> geopolitical -> risk -> remediation` (`orchestrator/chain.py`), and each step is recorded as a `Step` (input, output, ms) in a `ChainResult`.

- `core/schemas.py` is the contract. One agent's output schema is the next agent's input, and the web renders the same JSON. Change it deliberately.
- Logic lives in `tools/` and `agents/`. `lambdas/` handlers only parse the event, call a function and return.
- Agents explain, `tools/risk_math.py` computes. Scores are deterministic, and the risk agent overwrites any LLM-produced numbers.
- Mock first: with `USE_MOCK=1` (the default), every agent returns hard-coded valid schemas, so the chain and web work without AWS.
- Request flow: web (Amplify) -> API Gateway -> `lambdas/api` -> `orchestrator/app.py` (AgentCore Runtime) -> agents -> AgentCore Gateway -> `lambdas/gateway_tools` -> `tools/*`.
- Most of `tools/*`, `pipelines/`, `infra/` and `web/` are stubs (`NotImplementedError` / README only).

## Environment & commands

```bash
conda create -n alphaforge python=3.12 -y
pip install -r requirements.txt
python -m orchestrator.chain   # run the mock chain
pytest                         # all tests; single: pytest tests/test_chain.py::test_mock_chain
python test_bedorck.py   # verifies AWS Bedrock access; prints a short reply from the model
```

- LLM access goes through **AWS Bedrock** (`boto3` `bedrock-runtime`, region `us-east-1`, `converse` API). The smoke test uses the model ID `global.anthropic.claude-haiku-5-5`. You need AWS credentials to run it; `.aws/` and `.env` are gitignored, so keep credentials there.
- `requirements.txt` sets the intended stack: `strands-agents` / `strands-agents-tools` (agent framework), `bedrock-agentcore`, `mcp`, `slack_bolt` / `slack_sdk` (Slack bot interface), `starlette` / `uvicorn` (HTTP serving), plus `pydantic` and `rich`.

## Data

`data/` and `*.parquet` files are gitignored. Datasets live locally and are never committed.
