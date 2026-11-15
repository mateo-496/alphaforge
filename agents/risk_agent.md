# Risk agent

The [risk agent](risk_agent.py) computes the final portfolio risk. It gathers measured inputs and
[tools/portfolio_risk.py](../tools/portfolio_risk.py) computes the score with
[tools/risk_math.py](../tools/risk_math.py); no number comes from an LLM. Every score is on [0, 1].

```bash
.\.venv\Scripts\python.exe -m agents.risk_agent .\portefeuille-test.csv [--filings filing_risk_output.json]
```

## Formula

- **Country risk** `R_c` (country risk agent, then measured inputs alone for countries the World Bank lacks): mean of the percentile of the country GPR (own last ten years, 12-month mean) and the
  percentile of the global OFR financial stress index and the claim quality of the World Bank macro claims. EPU is not sourced. Missing inputs are reported and the
  weights renormalised, never replaced by invented values (see [tools/country_risk_inputs.py](../tools/country_risk_inputs.py)).
- **Exposure** `E_i = sum_c w_ic R_c` from the SEC geographic revenue split; the unknown share (including "Other")
  takes the mean `R_c` of the scored countries. With no known split, the term is missing.
- **Filing risk** `F_i`: half the confidence-weighted mean severity of the filing-risk claims, half that of the
  three most severe (severity x confidence), scaled from 0-5 to [0, 1]. Requires the filing-risk agent output (`--filings`).
- **Market risk** `M_i`: mean of annualised one-year volatility scaled between 10% and 60% and beta against SPY
  scaled between 0.5 and 2.0 (fixed bounds, Yahoo Finance prices).
- **Asset risk** `G_i = a E_i + b F_i + c M_i`, equal weights by default, renormalised over available terms.
- **Portfolio risk** `P = sum_i w_i G_i`; under a scenario `min(1, P + L * sum_i w_i sum_c w_ic I_c)`.

The report gives each ticker's contribution by term and country, the countries' scores and missing inputs, and
`ranking_stability`, the share of +/-20% weight changes that keep the ticker ranking.
