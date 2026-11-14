# AlphaForge

AlphaForge is a multi-agent prototype for evaluating geopolitical and market
risk in an investment portfolio and proposing remediation trades.

## Architecture

The intended workflow combines portfolio and investor information with
specialist analysis, risk calculation and remediation. The current code is
mid-migration: the standalone filings and market-stress agents use the
`AgentOutput` report contract in [core/schemas.py](core/schemas.py), while the
older orchestration chain and its other agents still reference removed schemas
and helpers. The chain is therefore not currently runnable end to end.

- [agents/](agents/) contains agent logic and specialist documentation.
- [tools/](tools/) contains data retrieval, calculations and the shared MCP
  server. Market stress uses MCP; the filings agent currently uses local
  Strands tools.
- [core/](core/) contains data contracts, configuration and citation helpers.
- [orchestrator/](orchestrator/) and [lambdas/](lambdas/) contain the intended
  runtime integration.

## Specialist agents

| Agent | Role | Current status |
| --- | --- | --- |
| [Filings](agents/filings_agent.md) | Extract cited exposures from company filings | Standalone implementation; dependency and integration caveats |
| [Market stress](agents/market_stress_agent.md) | Analyze market indicators and portfolio exposures | Standalone implementation using MCP |
| [Geopolitical](agents/geopolitical_agent.md) | Assess country risk under a scenario | Legacy code; requires migration |
| [Risk](agents/risk_agent.md) | Calculate portfolio and ticker risk | Legacy code; requires migration |
| [Remediation](agents/remediation_agent.md) | Propose portfolio trades | Legacy code; requires migration |

## Setup

The project setup uses Python 3.12. From the repository root on Windows:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Individual agents document their required AWS credentials, configuration,
data sources and execution commands. Do not commit credentials or local data.
