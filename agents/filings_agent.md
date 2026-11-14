# Filings agent

The [filings agent](filings_agent.py) analyzes one ticker's latest SEC annual
filing on or before a requested date. It asks a Strands agent to extract
geopolitical claims and supporting quotations using the filing tools in
[tools/filings.py](../tools/filings.py).

## Input and output

- Input: a ticker and optional `--as-of` date; the default is today.
- Output: an `AgentOutput` from [core/schemas.py](../core/schemas.py), with
  claim IDs, sources and a `quote_verified` flag. The flag records a
  normalized substring check against text retrieved during the run; a false
  value is not automatically rejected.
- The command-line entry point checks summary citations and writes the report
  under `outputs/`.

## Running

From the repository root, with AWS Bedrock credentials and access to the
configured model:

Set `SEC_IDENTITY` to an application name and real contact email in the
environment. This agent does not itself load `.env`. The filing tools require
`edgartools` (`edgar`), which is not currently listed in `requirements.txt`.

```powershell
.\.venv\Scripts\python.exe -m pip install edgartools
$env:SEC_IDENTITY = "Application name contact@your-domain.com"
.\.venv\Scripts\python.exe -m agents.filings_agent NVDA --as-of 2025-06-30
```

`AWS_REGION` and `BEDROCK_MODEL_ID` can override the default region
(`us-east-1`) and model (`us.anthropic.claude-sonnet-4-5-20250929-v1:0`).

## Limitations

The agent uses local Strands tools, not the shared MCP server. Its report is
not yet integrated with the legacy chain, and the market-stress agent retrieves
country exposures independently. Citations and extracted values should be
reviewed against the filing.
