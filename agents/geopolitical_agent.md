# Geopolitical agent

[geopolitical_agent.py](geopolitical_agent.py) scores country risk on the analysis date. It is used by the website's
"Country risk" step.

## How it works
1. **Code computes the score** (`tools/risk_math.country_score`, 0–100):
   - **GPR index:** the Caldara–Iacoviello GPR value for the country, as a z-score against its own history
     (`tools/gpr.py`). It uses only months that ended before the analysis date, mapped to 50 + 15z.
   - **Scenario hit:** the largest expected shock a scenario puts on the country,
     max(likelihood × impact/5 × intensity), where 0.2 maps to 100.
   - **Combination:** the mean of the parts that exist. Countries without GPR coverage use the scenarios only,
     and the method is shown in the report.
2. **One Bedrock call writes a driver line** for each of the 25 most exposed countries, using only those facts
   and the market indicator where one exists. If the call fails, each driver is a factual line built by code.

## Output
`{iso3: {R, gpr, hit, scenarios, market, driver, method}}`, plus metadata with the GPR source for the annexes.
