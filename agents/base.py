"""Shared agent construction."""
from strands.models import BedrockModel

from core.config import BEDROCK_MODEL_ID, REGION


def build_model(temperature: float = 0.0, max_tokens: int = 4096) -> BedrockModel:
    return BedrockModel(model_id=BEDROCK_MODEL_ID, region_name=REGION,
                        temperature=temperature, max_tokens=max_tokens)
