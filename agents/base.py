"""Shared agent construction."""
from strands.models import BedrockModel

from core.config import BEDROCK_MODEL_ID, REGION


def build_model(temperature: float = 0.0, max_tokens: int = 4096, model_id: str | None = None) -> BedrockModel:
    return BedrockModel(model_id=model_id or BEDROCK_MODEL_ID, region_name=REGION,
                        temperature=temperature, max_tokens=max_tokens)
