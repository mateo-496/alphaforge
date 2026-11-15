import os
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

def env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}

BASE_DIR = Path(__file__).resolve().parent

AWS_REGION = os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION", "us-east-1")
BEDROCK_MODEL_ID = os.getenv("BEDROCK_MODEL_ID", "global.anthropic.claude-haiku-5-5")
S3_BUCKET = os.getenv("S3_BUCKET", "datathon-equipe-5-017820693871")
USE_DEMO_DATA = env_bool("USE_DEMO_DATA", True)

# External API configs
COUNTRY_API_URL = os.getenv("COUNTRY_API_URL", "")
COUNTRY_API_KEY = os.getenv("COUNTRY_API_KEY", "")
BANK_API_URL = os.getenv("BANK_API_URL", "")
BANK_API_KEY = os.getenv("BANK_API_KEY", "")

# Search endpoint for source discovery
SEARCH_API_URL = os.getenv("SEARCH_API_URL", "")
SEARCH_API_KEY = os.getenv("SEARCH_API_KEY", "")

# Local trusted sources path
TRUSTED_SOURCES_PATH = BASE_DIR / "data" / "trusted_sources.json"
