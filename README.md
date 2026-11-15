# AlphaForge

AlphaForge analyses a portfolio's geopolitical exposure in the context of an investor's profile. It combines public data, company filings and agent-generated explanations with a risk score computed by code. The resulting report includes country and holding exposure, scenarios, profile conflicts and simulated portfolio changes.

This project is a datathon prototype, not investment advice.

## Deployed Demo

The deployed version only supports the provided default portfolios, and its sliders cannot be changed. It displays cached responses rather than running the agents live. The setup and analysis instructions below apply to the local version, which supports editable inputs and live agent calls.

## Prerequisites

- Python 3.12 or newer and pip.
- Internet access for public data sources, including SEC filings, Yahoo Finance, the World Bank and the Geopolitical Risk index.
- An AWS account with credentials available to the standard AWS credential provider chain and permission to invoke the configured Amazon Bedrock model. The account must have access to that model in the chosen region. Bedrock usage may incur charges.
- A name and email address for the SEC's required `User-Agent` identity.

Node.js is not needed; the web interface has no frontend build step.

## Installation

Open a terminal in the project root and create a virtual environment.

**Windows PowerShell**

```powershell
py -3 --version
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

If the version shown is below 3.12, install a supported Python version and use it to create the environment. If PowerShell blocks activation, use the interpreter directly for the remaining commands, for example `.\.venv\Scripts\python.exe -m pip install -r requirements.txt`.

**macOS / Linux**

```bash
python3 --version
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

## Configuration

Set the following in a `.env` file in the project root, replacing the SEC identity with your own name and email:

```dotenv
SEC_IDENTITY="Your Name your.email@example.com"
AWS_REGION=us-east-1
BEDROCK_MODEL_ID=global.anthropic.claude-sonnet-5-5
STORAGE=local
```

The model ID above is the application's default. If your AWS account has access to a different compatible Bedrock model, set `BEDROCK_MODEL_ID` to that model's ID. `SCENARIO_MODEL_ID` is optional and defaults to the same model.

Authenticate with AWS using an existing credential profile, IAM role or AWS CLI configuration. For example, with the [AWS CLI](https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html) installed, use `aws configure` or your organisation's AWS SSO procedure. The configured identity needs `bedrock:InvokeModel` permission for the chosen model. Do not commit credentials or `.env` to the repository.

Local storage is the default: caches, run records and LLM traces are written under `data/`, which is gitignored. Traces can contain prompts and portfolio details. S3 and CloudTrail Lake are optional; they are not required for a local run.

## Start The App

With the virtual environment active, run:

```bash
python -m uvicorn web.app:app --port 8080
```

Open [http://127.0.0.1:8080](http://127.0.0.1:8080). Stop the server with `Ctrl+C`. If port 8080 is already in use, choose another port with `--port`.

## Run A Local Analysis

1. Select a showcase or sample portfolio, enter holdings manually, or upload a CSV. The portfolio form links to a CSV template.
2. Select or edit the investor profile, preferences and limits. Showcase labels describe examples, not guaranteed scores.
3. Choose an analysis date within the form's supported window, currently 2021-11-12 through 2026-11-12.
4. Select **Run analysis** and follow the progress page. Live calls may take several minutes.
5. Review the report's objective risk, personalised concern, exposure estimates, sources and simulated recommendations.

The headline is personalised concern relative to the investor's risk tolerance; it is not the probability or size of a financial loss. Objective risk is shown separately. Scores and source availability can change with the analysis date and data.

### Optional Starter Price Data

The app can run with portfolio weights without the starter price files. If provided, place `prices_daily.csv` and `fx_usdcad_daily.csv` in `data/alphaforge_starter/`, or set `STARTER_DIR` to the directory containing both files. These files are not included in the repository.

Without them, the app may use Yahoo Finance and FRED for price and currency conversion; quantity-based inputs can fail if those sources are unavailable. The profile's historical volatility checks also require the starter price data.

## Troubleshooting

- **Bedrock access or credentials fail:** check the AWS identity, region, model ID and `bedrock:InvokeModel` permission. Restart the server after changing environment settings. The pipeline attempts to continue with fallback information when an agent fails, but results may be incomplete.
- **SEC lookups fail or are refused:** set `SEC_IDENTITY` to a real name and email, check network access and respect SEC request limits. Country splits may fall back to labelled estimates.
- **Price or currency data is unavailable:** use portfolio weights, or provide the optional starter files. Reports identify missing or estimated data.
- **A run takes longer than expected:** external downloads and agent calls can take several minutes. Progress and failures are shown on the run page; previously fetched public data may be cached locally.
- **An old report will not open:** run the analysis again; reports produced by older versions may not match the current report format.

## Tests

Run the offline test suite from the project root:

```bash
python -m pytest -q
```

Tests stub external services; a passing suite does not verify your AWS access or live data connectivity.

## How It Works

1. The exposure agent builds country splits from filings or labelled fallback estimates.
2. Filing, scenario and country agents collect disclosures, geopolitical context and source evidence.
3. Code computes objective risk from country, geopolitical and verified filing inputs, then calculates concern relative to the investor's tolerance. See [the risk formula](docs/risk-formula.md).
4. Code proposes and re-scores profile-fitted changes. The remediation agent can suggest alternatives, which code sizes and validates.

LLM-written numbers do not enter the score. Quotes used as evidence are checked against source material. Public data and generated explanations can be incomplete, and estimated exposures are labelled in the report.

## Project Layout

```text
agents/     Evidence extraction and explanation agents
core/       Configuration, schemas, storage and Bedrock tracing
tools/      Data access and risk calculations
pipelines/  Scenario generation
web/        FastAPI application, templates and static assets
tests/      Offline tests and service fakes
```

Each Bedrock call goes through `core/llm.py` and is traced locally. Setting `CLOUDTRAIL_CHANNEL_ARN` additionally enables CloudTrail Lake tracing and requires `cloudtrail-data:PutAuditEvents`. To use S3-backed caches instead of local storage, set `STORAGE=s3` and `S3_BUCKET` and grant the AWS identity appropriate S3 permissions. Run records and local LLM traces are still written under `data/`.
