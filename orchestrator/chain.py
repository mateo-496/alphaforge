from agents import filings_agent, geopolitical_agent, remediation_agent, risk_agent
from agents.base import timed
from core.schemas import ChainResult, InvestorProfile, Portfolio, Scenario, Step


def run(portfolio: Portfolio, profile: InvestorProfile, scenario: Scenario) -> ChainResult:
    steps: list[Step] = []

    def step(name, fn, inputs: dict, *args):
        out, ms = timed(fn, *args)
        steps.append(Step(agent=name, input=inputs, output=out.model_dump(), ms=ms))
        return out

    exp = step("filings", filings_agent.run, portfolio.model_dump(), portfolio)
    geo = step("geopolitical", geopolitical_agent.run, {"scenario": scenario.model_dump()}, exp, scenario)
    risk = step("risk", risk_agent.run, {}, portfolio, exp, geo)
    plan = step("remediation", remediation_agent.run, profile.model_dump(), portfolio, risk, profile)
    return ChainResult(steps=steps, final=plan)


if __name__ == "__main__":
    p = Portfolio(holdings=[{"ticker": "NVDA", "weight": 0.6}, {"ticker": "AAPL", "weight": 0.4}])
    s = Scenario(name="Taiwan Strait blockade", description="Naval blockade of Taiwan", countries=["TWN", "CHN"])
    print(run(p, InvestorProfile(), s).model_dump_json(indent=2))
