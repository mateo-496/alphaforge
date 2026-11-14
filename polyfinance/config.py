import os

def env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}

AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
BEDROCK_MODEL_ID = os.getenv("BEDROCK_MODEL_ID", "")  # Set to a model available in your AWS account.
S3_BUCKET = os.getenv("S3_BUCKET", "")
USE_DEMO_DATA = env_bool("USE_DEMO_DATA", True)

# Configure these to match the APIs you are given.
COUNTRY_API_URL = os.getenv("COUNTRY_API_URL", "")
COUNTRY_API_KEY = os.getenv("COUNTRY_API_KEY", "")
BANK_API_URL = os.getenv("BANK_API_URL", "")
BANK_API_KEY = os.getenv("BANK_API_KEY", "")

# Optional search endpoint for source discovery. Must return JSON.
SEARCH_API_URL = os.getenv("SEARCH_API_URL", "")
SEARCH_API_KEY = os.getenv("SEARCH_API_KEY", "")
