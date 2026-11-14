"""AgentCore Runtime entrypoint wrapping chain.run."""
from bedrock_agentcore.runtime import BedrockAgentCoreApp

from core.schemas import InvestorProfile, Portfolio, Scenario
from orchestrator import chain

app = BedrockAgentCoreApp()


@app.entrypoint
def invoke(payload: dict) -> dict:
    result = chain.run(Portfolio(**payload["portfolio"]), InvestorProfile(**payload.get("profile", {})),
                       Scenario(**payload["scenario"]))
    return result.model_dump()


if __name__ == "__main__":
    app.run()
