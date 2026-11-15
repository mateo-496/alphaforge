"""Central configuration, read from environment variables (see .env.example)."""
import os

REGION = os.environ.get("AWS_REGION", "us-east-1")
BEDROCK_MODEL_ID = os.environ.get("BEDROCK_MODEL_ID", "us.anthropic.claude-sonnet-4-5-20250929-v1:0")
def _sec_identity(raw: str) -> str:
    """The SEC wants 'Name email' as the User-Agent VALUE. A value pasted with its header name
    ('User-Agent: Name email') would be sent as 'User-Agent: User-Agent: ...', which the SEC rejects."""
    import re
    return re.sub(r"^\s*user-agent\s*:\s*", "", raw.strip().strip('"\''), flags=re.I)


SEC_IDENTITY = _sec_identity(os.environ.get("SEC_IDENTITY", "AlphaForge Datathon alphaforge@example.com"))
if os.environ.get("SEC_IDENTITY"):
    os.environ["SEC_IDENTITY"] = SEC_IDENTITY   # every reader (tools/market_data) gets the clean value

# USE_MOCK=1: agents return mock outputs, no Bedrock / network calls.
USE_MOCK = os.environ.get("USE_MOCK", "1") == "1"
# STORAGE=local -> ./data/<key>;  STORAGE=s3 -> s3://S3_BUCKET/<key>
STORAGE = os.environ.get("STORAGE", "local")
S3_BUCKET = os.environ.get("S3_BUCKET", "")

# Scenario agent: real Bedrock agent by default, independent of USE_MOCK.
# SCENARIO_USE_MOCK=1 only for offline UI testing; mock sets are never shown or merged in real mode.
SCENARIO_USE_MOCK = os.environ.get("SCENARIO_USE_MOCK", "0") == "1"
SCENARIO_MODEL_ID = os.environ.get("SCENARIO_MODEL_ID", BEDROCK_MODEL_ID)   # model for the scenario writer
SUMMARY_MAX_CHARS = 350
SCENARIO_MAX_AGE_DAYS = int(os.environ.get("SCENARIO_MAX_AGE_DAYS", "7"))   # regenerate after this
SCENARIO_ALPHA = float(os.environ.get("SCENARIO_ALPHA", "0.35"))             # weight of the new run in the EMA
# Geopolitical agent: S3 bucket/prefix holding research documents, optional Bedrock Knowledge Base over it.

GEO_S3_BUCKET = "datathon-equipe-5-017820693871"
