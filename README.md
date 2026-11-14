# AlphaForge
Multi-agent geopolitical risk evaluation of a portfolio, with scenario-based remediation, on AWS (Bedrock, AgentCore).

Chain: Portfolio + InvestorProfile + Scenario -> Filings -> Geopolitical -> Risk -> Remediation.
Contract between all layers: `core/schemas.py`. Logic lives in `tools/` and `agents/`, never in `lambdas/`.

    pip install -r requirements.txt && cp .env.example .env
    python -m orchestrator.chain      # runs the mock chain
    pytest
