# Remediation agent

[remediation_agent.py](remediation_agent.py) proposes up to 3 hypothetical swaps: sell part of one holding and buy
one candidate fund. The candidates are filtered by the profile's exclusions, ESG level and objective
(`web/pipeline._candidates`).

The model only chooses and explains. Code (`web/pipeline._evaluate_swaps`) then:
- drops proposals with unknown tickers, duplicates, or a holding pushed past the single-holding limit;
- computes the new risk score and each side's past-year return from Yahoo prices.

The page labels the result as a simulation, not advice.
