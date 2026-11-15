# Risk formula v2 — mechanical and explainable

**Rule: no number written by a language model enters the score.** LLMs only extract facts (verbatim quotes, lists of countries involved). Code verifies them and computes every number in `tools/risk_math.py`.

## Formula

Revenue exposure (SEC 10-K / 20-F revenue tables, parsed by code):

$$X_c = \sum_i w_i\, w_{ic}$$

Country hazard: the percentile of the Caldara–Iacoviello GPR index among the country's own past months (point in time). Countries the index does not cover use the global GPR, labelled as such.

$$g_c = \frac{\#\{\text{past months with } \mathrm{GPR}_c \le \mathrm{GPR}_c(t)\}}{\#\{\text{past months}\}} \in [0,1]$$

Market stress, one amplifier for the whole portfolio (OFR FSI, STLFSI4 and VIX, each z-scored against its own 3-year window):

$$m = \tfrac{1}{3}\sum_k z_k, \qquad A = 1 + 0.15\cdot\mathrm{clip}(m, 0, 3)$$

Filing flags: the share of the 8 risk channels for which the filing has a quote found word for word by code. The agent's own severity grades are not used.

$$f_i = \frac{\#\{\text{channels with a verified quote}\}}{8}$$

Holding and portfolio scores, with $a_i = 0.8$ when the filing was read and $1$ otherwise:

$$G_i = 100\left[a_i\, A \sum_c w_{ic}\, g_c + (1-a_i)\, f_i\right], \qquad \boxed{P = \sum_i w_i\, G_i}$$

**Reading it.** 50 means a typical month for the countries the portfolio earns in, with calm markets. $P$ is a sum, so every point traces back to a country or a filing. A country contributes $100\, A \sum_i w_i a_i w_{ic}\, g_c$ points, and the points shown in the holdings and countries tables add up exactly to the score.

## Scenarios: a what-if table, not part of the score

For each scenario, the revenue at stake is the share of portfolio revenue in countries directly involved. A country counts as involved when its intensity is at least 0.5:

$$E_s = \sum_c X_c\cdot\mathbb{1}[\text{country } c \text{ directly involved in } s]$$

The agent's likelihood and impact are shown as context and never enter the score.

## Verdict, from the profile

The profile's risk level (1 to 5) sets the tolerance $T$ = 50, 55, 60, 65 or 70. Three tests are shown to the user:

1. $P \le T$
2. $A \le 1.15$ (markets not under acute stress)
3. no broken profile limit

- **Clear** (all three pass): "No immediate danger". No trade is suggested.
- **Watch** (only the market test fails): hold, no trade.
- **Act**: recommendations are made.

## Recommendations (`web/recommend.py`, all chosen by code)

1. **Profile limits first.** Sell only what is needed to respect each stated limit:
   - holdings above the single-holding cap are cut back to the cap;
   - crypto above its cap is cut back to the cap;
   - excluded holdings are sold in full;
   - holdings above the profile's volatility limit are halved.
2. **Then risk, only if $P > T$.** Move part of the largest contributor into the best-fitting fund, sized in quarters to bring $P$ back to $T$, at most 3 swaps.
3. **Fund choice follows the profile.**
   - Horizon ≤ 5 years, a capital-preservation objective or risk level ≤ 2: bond funds, then gold, then equity funds.
   - Growth objective or risk level ≥ 4: equity funds only.
   - High ESG importance: ESG equity funds only.
   - Exclusions and countries to avoid are respected.
   - Among allowed funds, the lowest score wins, with a 10-point penalty for each step down the profile's preference list.
4. Each swap is re-scored with the full formula and shows "why sell" and "why this fund".

## What each agent extracts

| Agent | Information | Term | Status |
|---|---|---|---|
| Market data & filings | Country revenue split $w_{ic}$ (SEC tables) | $X_c$ | in formula |
| Market data & filings | 1y return, volatility, drawdown | profile volatility check | in formula |
| Market data & filings | Beta of returns to GPR | holding sensitivity | candidate |
| Filings agent | Channels with a verified quote | $f_i$ | in formula |
| Filings agent | Severity 0–5, confidence | — | shown, not scored |
| Filings agent | Hassan et al. PRisk word counts on filing text | replaces $f_i$ | candidate |
| Market stress | OFR FSI, STLFSI4, VIX z-scores | $m \to A$ | in formula |
| Market stress | Country FX / 10y-yield move | — | shown, not scored |
| Market stress | EPU by country | second hazard index | candidate |
| Scenarios | Countries directly involved (verified quotes) | $E_s$ (what-if) | in formula |
| Scenarios | Likelihood, impact, intensity | — | shown, not scored |
| Scenarios | Prediction-market price (Polymarket / Kalshi) | probability for $E_s$ | candidate |
| Country risk | GPR percentile vs. own history | $g_c$ | in formula |
| Country risk | Driver line (LLM) | — | shown, not scored |
| Profile | Risk level, horizon, objective, ESG, exclusions | verdict, fund choice | in formula |

## Known limits

- GPR measures news coverage now. It does not forecast; the scenarios table carries the forward view.
- Each country is compared with its own history. A country that is always risky but calm right now scores low. Fix if needed: take the percentile across all countries' months combined.
- Estimated exposures (no usable filing) are equal splits across the company's home and operating countries, and are labelled as estimates in the report.
