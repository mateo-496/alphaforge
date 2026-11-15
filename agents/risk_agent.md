# Risk agent

[risk_agent.py](risk_agent.py) writes the 3–4 summary sentences at the top of the report from the computed
figures: the score, the top holdings and countries, the profile and the conflicts with it.

Code computes every number (`tools/risk_math`). `check()` drops any sentence containing a number that does not
appear in the supplied facts, so the model cannot add figures. If the call fails, the report uses a summary
built by code.
