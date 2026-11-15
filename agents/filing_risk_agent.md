# Annual-filing risk agent

The [filing-risk agent](filing_risk_agent.py) reads a portfolio CSV and produces
one Pydantic report per holding, using only the Risk Factors section of its
latest SEC annual filing. It covers risks of any type and is independent of the
web pipeline. The JSON contains common `AgentOutput` reports under `reports`
and filing metadata and review status under `companies`.

Claims use the `filing_risk` channel. The model's severity (`score`, 0-5) and
confidence (0-1) are subjective estimates, not measured facts or investment
advice. No objective severity formula follows from qualitative disclosures
alone. `value` and `unit` remain null; verified quotations and SEC sources are
attached to each claim. No portfolio risk calculation is performed.

## Run

Install `requirements.txt` and configure AWS credentials, access to the
configured Bedrock model, and `SEC_IDENTITY` (application name and real contact
email). The server and agent load `.env` without overriding existing environment
variables. From the repository root, start the shared MCP server:

```powershell
.\.venv\Scripts\python.exe -m tools.mcp_server
```

In another terminal:

```powershell
.\.venv\Scripts\python.exe -m agents.filing_risk_agent .\portefeuille-test.csv
```

The CSV requires `ticker` and `weight` columns, with positive weights summing
to 1. It is converted in memory through MCP; no portfolio JSON file is created.
The report is printed as JSON. `MCP_SERVER_URL` changes the default server URL
`http://127.0.0.1:8000/mcp`.

The agent processes up to three passages concurrently per company. Bedrock quotas
and retries can affect latency and cost; results are returned in source order.

## Optional Knowledge Base

Set `ENABLE_FILING_RAG=1` (or `ENABLE_FILINGS_RAG=1`), `KB_ID` and `KB_DATA_SOURCE_ID` in the environment or
`.env` used by the agent and MCP server. The configured data source must use S3.
Filings are archived in the `S3_BUCKET` bucket (the Knowledge Base data source must
point to it) under `KB_S3_PREFIX`, default `alphaforge_filings/`. If the data source has an
inclusion prefix, include it in `KB_S3_PREFIX`.

When enabled, the server archives each complete primary annual filing as text and
its metadata in S3, then starts one Knowledge Base ingestion job without waiting
for it. The JSON `indexing` field includes the job ID, initial status and SEC
accession numbers. `started` does not mean ingestion has completed. The shared
MCP tool `filing_index_status(ingestion_job_id)` reports progress, failures and
statistics. Once complete, `search_indexed_filing(ticker, accession, query)`
retrieves passages from that filing and checks them against its S3 archive.
Only exact archive substrings are returned. Retrieval is semantic and does not
guarantee exhaustive results. A 40-F's
separate annual information form is not included in the primary filing archive.

The AWS identity needs `bedrock:GetDataSource`, `bedrock:StartIngestionJob`,
`bedrock:GetIngestionJob`, `bedrock:Retrieve`, `s3:GetObject` and `s3:PutObject`
permissions for the relevant resources. The Knowledge Base service role also
needs access to its source. Indexing and storage may incur AWS costs. No
portfolio weights are stored in the archive. Restart the MCP server after
changing its configuration or code.

## Sources and limitations

The tools select the latest non-amended 10-K, 20-F or 40-F filed on or before
today. They extract the risk section, split it into overlapping passages, and
verify that each model quotation occurs in its passage. Each finding cites the
filing or, for a 40-F, its annual information form. This initial verification
normalizes whitespace, case and certain quotation marks. For rejected quotations, the
model may select up to three adjacent source segments per risk, twice; the
quotation is reconstructed directly from the passage and verified again.
Invalid segment selections are retried within the same limit. If any quotation
still cannot be verified, the company is marked `manual_review` with a reason
and no partial risks, and the other companies are processed. Retries can incur
additional Bedrock costs.

If section boundaries cannot be verified, or a 40-F risk section refers to
other documents, the company receives `manual_review` and no extracted risks;
other holdings continue. For example, the current SEC parser cannot reliably
bound ASML's 2025 20-F risk section. Extraction is not guaranteed exhaustive:
the model's category and selected quotation should be reviewed against the
filing. Long sections require multiple model calls and may incur Bedrock costs.
