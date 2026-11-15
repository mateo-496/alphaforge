"""Shared agent construction and utilities."""
import time
from typing import Any, Callable, TypeVar

from strands.models import BedrockModel

from core.config import BEDROCK_MODEL_ID, REGION

T = TypeVar("T")


def build_model(temperature: float = 0.0, max_tokens: int = 4096, model_id: str | None = None) -> BedrockModel:
    return BedrockModel(model_id=model_id or BEDROCK_MODEL_ID, region_name=REGION,
                        temperature=temperature, max_tokens=max_tokens)


def timed(fn: Callable[..., T], *args: Any, **kwargs: Any) -> tuple[T, float]:
    """Call fn(*args, **kwargs) and return (result, elapsed_ms)."""
    t0 = time.perf_counter()
    result = fn(*args, **kwargs)
    return result, (time.perf_counter() - t0) * 1000.0
