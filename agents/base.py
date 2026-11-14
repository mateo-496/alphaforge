import time

from core import config


def build_model():
    from strands.models import BedrockModel
    return BedrockModel(model_id=config.BEDROCK_MODEL_ID, region_name=config.AWS_REGION)


def run_agent(system_prompt: str, user_prompt: str, output_model, tools: list | None = None):
    """Real run: a Strands agent returning a validated pydantic object."""
    from strands import Agent
    agent = Agent(model=build_model(), system_prompt=system_prompt, tools=tools or [])
    return agent(user_prompt, structured_output_model=output_model).structured_output


def timed(fn, *args):
    t = time.perf_counter()
    out = fn(*args)
    return out, int((time.perf_counter() - t) * 1000)
