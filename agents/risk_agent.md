# Risk agent

The intended role of the [risk agent](risk_agent.py) is to combine country
exposures, geopolitical scores and portfolio weights into per-ticker and
portfolio risk measures. Its numerical calculations are delegated to
[tools/risk_math.py](../tools/risk_math.py); the intended model call supplies
an explanation rather than overriding those calculations.

## Current status

This is legacy code and is not currently runnable: it imports removed schemas
and the removed `run_agent` helper, and references the removed `USE_MOCK`
configuration. It needs migration to the current data contracts before it
can be used in the chain.
