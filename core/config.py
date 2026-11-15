"""All settings, read once from the environment (.env is loaded here). See .env.example."""
import os
import re

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

REGION = os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
BEDROCK_MODEL_ID = os.environ.get("BEDROCK_MODEL_ID", "global.anthropic.claude-sonnet-5-5")
SCENARIO_MODEL_ID = os.environ.get("SCENARIO_MODEL_ID", BEDROCK_MODEL_ID)

# S3 copy of the GPR index read by tools/country_risk_inputs.py (v1 country risk, kept but not called by the app)
GEO_S3_BUCKET = os.environ.get("GEO_S3_BUCKET", "datathon-equipe-5-017820693871")

# STORAGE=local -> ./data/<key>;  STORAGE=s3 -> s3://S3_BUCKET/<key>
STORAGE = os.environ.get("STORAGE", "local")
S3_BUCKET = os.environ.get("S3_BUCKET", "")

# LLM traces: always appended to data/traces/<day>.jsonl; also sent to CloudTrail Lake when a channel is set.
CLOUDTRAIL_CHANNEL_ARN = os.environ.get("CLOUDTRAIL_CHANNEL_ARN", "")

# The SEC wants "Name email" as the User-Agent value; strip a pasted "User-Agent:" prefix.
SEC_IDENTITY = re.sub(r"^\s*user-agent\s*:\s*", "", os.environ.get("SEC_IDENTITY", "").strip().strip("\"'"), flags=re.I)
if SEC_IDENTITY:
    os.environ["SEC_IDENTITY"] = SEC_IDENTITY

# Scenario agent
SUMMARY_MAX_CHARS = 350
SCENARIO_MAX_AGE_DAYS = int(os.environ.get("SCENARIO_MAX_AGE_DAYS", "7"))
SCENARIO_ALPHA = float(os.environ.get("SCENARIO_ALPHA", "0.35"))   # EMA weight of the newest run

# Filings agent (web/firms.py)
FILINGS_TOP_N = int(os.environ.get("FILINGS_TOP_N", "5"))
FILINGS_PARALLEL = int(os.environ.get("FILINGS_PARALLEL", "3"))
FILINGS_WAIT_S = int(os.environ.get("FILINGS_WAIT_S", "45"))
EXPOSURE_TEXT_WAIT_S = int(os.environ.get("EXPOSURE_TEXT_WAIT_S", "60"))   # per holding, then the prior is used
