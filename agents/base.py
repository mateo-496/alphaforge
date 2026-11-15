"""Shared agent construction."""
import os

from botocore.config import Config
from strands.models import BedrockModel

from core.config import BEDROCK_MODEL_ID, REGION

# Without a read timeout a stalled Bedrock stream blocks the run forever (botocore default is 60 s per
# read, with silent retries that can stack up). Fail fast instead; the caller records the error.
BOTO_CONFIG = Config(connect_timeout=10, read_timeout=int(os.environ.get("BEDROCK_READ_TIMEOUT", "90")),
                     retries={"max_attempts": 2, "mode": "standard"})


# Newer Claude models on Bedrock reject `temperature` ("temperature is deprecated for this model").
# It is sent only when MODEL_TEMPERATURE is set, for older models that still accept it.
_TEMPERATURE = os.environ.get("MODEL_TEMPERATURE")


def build_model(temperature: float | None = None, max_tokens: int = 4096, model_id: str | None = None) -> BedrockModel:
    extra = {}
    t = temperature if temperature is not None else (float(_TEMPERATURE) if _TEMPERATURE else None)
    if t is not None:
        extra["temperature"] = t
    return BedrockModel(model_id=model_id or BEDROCK_MODEL_ID, region_name=REGION, boto_client_config=BOTO_CONFIG,
                        max_tokens=max_tokens, **extra)
