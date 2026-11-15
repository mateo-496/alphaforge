# Risk formula — Cedric's two-stage score on measured inputs

**Rule: no number written by a language model enters the score.** LLMs extract facts (verbatim quotes, shares stated
in a filing) that code verifies; every number of the score is computed by code.

Code: `tools/portfolio_score.py` (Cedric's formula, unchanged) fed by `web/scoring.py`.

## 1. Country revenue split $w_{ic}$ (exposure agent, `agents/exposure_agent.py`)

Filings are the best source, not the only one. Each holding's split comes from the best tier available and is
tagged with that tier in the report.

| Tier | Source | $\lambda$ |
|---|---|---|
| 1 xbrl | XBRL geographic table of the latest 10-K / 20-F / 40-F filed on or before `as_of` | 1.0 |
| 2 text | Filing text (geographic note, MD&A): LLM pass; each share must sit in a verbatim quote that states that number | 0.8 |
| 3 stale | The company's previous filing when the latest has no split, or a fiscal year ending > ~18 months before `as_of` | 0.6 |
| 4 sector prior | Peers in the same industry (else GICS sector) that report a split, filed by `as_of` (at least 3) | 0 |
| 5 home-bias prior | $w_{ic} = h_s\,\mathbb{1}[c=\text{home}_i] + (1-h_s)\,\pi_{sc}$, $\pi_{sc}$ = world GDP weights without peers | 0 |
| 6 returns-based | Weekly returns on country ETFs, world market regressed out, $w \ge 0$, $\sum w = 1$, prices up to `as_of` | 0 |

A reported tier is blended with the prior:

$$w_{ic} = \lambda_i\, w^{\text{reported}}_{ic} + (1-\lambda_i)\, w^{\text{prior}}_{ic}$$

- Reported regions ("Asia Pacific") are split within the region by the prior's mix $\pi_{sc}$, not evenly; "outside the
  U.S." lines by the prior's foreign mix; the share a filing leaves unattributed follows the prior outside every place it names.
- $h_s$ is the peers' average domestic share; with fewer than 3 reporting peers, $h = 0.6$ (an assumption, shown as such).
- Funds: returns-based for equity ETFs, the fund's recorded countries weighted by GDP for bond ETFs. Gold and crypto: no country.
- EDGAR refusals (HTTP 403 / 429) are reported as "blocked", never as "no filing".
- Every split read from a filing joins the peer library (`exposure-library/` in storage) with its filing date.

### Cheap checks before reading any text

Stop at the first that applies; the step is logged per holding (`cache`, `xbrl`, `prior:small`, `prior:domestic`,
`carry`, `regex`, `llm`, `prior:nomatch`, `prior:timeout`):

1. XBRL geographic table → tier 1.
2. Accession already read (`exposure-splits/{accession}.json`) → cached split, no download.
3. Weight $w_i < 0.02$ → prior (its error barely moves $P$).
4. Domestic sector (banks, utilities, telecoms, REITs, regional insurers) → $w_{i,home}=0.9$, the remaining $0.1$ spread by the prior.
5. Same fiscal year already read from another filing → carried forward.
6. Main document only: ~1,500-character snippets around geographic wording; none → prior, no LLM call.
7. Regex `N% of (our) (total) (net) revenue/sales` next to a place, or "substantially all of our revenue … <country>"; accepted when $0.9 \le \sum_c w_{ic} \le 1.05$.
8. LLM on the snippets only, within `EXPOSURE_TEXT_WAIT_S` (60 s).

## 2. Inputs, for any exposure vector (a holding's $w_{ic}$, or the portfolio's $X_c = \sum_i w_i w_{ic}$)

$$A_1 = \frac{\sum_c X_c M_c}{\sum_{c \in \text{covered}} X_c}, \quad
A_2 = \frac{\sum_c X_c\, g_c}{\sum_{c \in \text{covered}} X_c}, \quad
A_3 = \frac{\sum_i w_i f_i}{\sum_{i \in \text{read}} w_i}$$

- $M_c$: macro fragility, World Bank indicators (point in time) → `tools/risk_calculator.py`, divided by 100.
- $g_c$: share of the country's past months with a lower Caldara–Iacoviello GPR index.
- $f_i$: share of the 8 risk channels with a verified quote in the filing (filings agent).
- $t$: profile risk level 1→5 mapped to low, low-moderate, moderate, moderate-high, high (0.20 … 0.85).
- Confidence $c_k$ = share of revenue (or weight) the input covers; unattributed revenue counts as not covered.

## 3. Cedric's two-stage formula (`portfolio_scores`)

Shrinkage and convex transform:

$$\tilde A_k = c_k A_k + (1-c_k)\mu, \qquad f(x) = \frac{e^{\lambda x}-1}{e^{\lambda}-1}$$

Blocks, interaction and red flag:

$$F_S = \alpha f(\tilde A_1) + (1-\alpha) f(\tilde A_3), \quad F_G = f(\tilde A_2), \quad B = w_S F_S + w_G F_G$$

$$R_0 = B + \eta F_S F_G (1-B), \qquad h = \left(\frac{\max(0, \max_k \tilde A_k - \tau)}{1-\tau}\right)^2, \qquad R = R_0 + \kappa h (1-R_0)$$

Personalised concern, with comfort level $\rho(t) = a + b\,t$:

$$C = 100\,\frac{\sigma(k(R-\rho)) - \sigma(-k\rho)}{\sigma(k(1-\rho)) - \sigma(-k\rho)}$$

Parameters ($\lambda, w_S, w_G, \alpha, \eta, \tau, \kappa, k, a, b, \mu$) are `Params()` in `tools/portfolio_score.py`.

The headline is $C$; the objective risk $100R$ is shown next to it. The same function scores each holding (its own
$w_{ic}$ and $f_i$) and each country (its own $M_c$ and $g_c$, no company term), so the holdings and countries tables
use the same scale as the headline.

## 4. Verdict and recommendations

- **Clear** when $100R \le 100\,\rho(t)$ and no stated profile limit is broken: no trade suggested.
- **Act** otherwise: `web/recommend.py` fixes broken limits first, then moves the riskiest holdings into the best
  profile-approved fund in quarters until $100R$ is back under the comfort level; every swap is re-scored with the
  full formula. The remediation agent may add alternatives, kept only if code re-scoring shows they lower $R$.

## 5. Context, never scored

Scenario likelihood and impact, the filing-risk agent's risks, severity grades, GPR claims, driver and macro notes,
official sources. The what-if per scenario is $E_s = \sum_c X_c\,\mathbb{1}[\text{country directly involved in } s]$.

## Known limits

- GPR measures news coverage now; it does not forecast. The scenarios carry the forward view.
- Unknown inputs are shrunk to the neutral prior $\mu = 0.5$, so a holding with no country (gold, crypto) sits mid-scale.
- The returns-based tier is noisy; the peer library starts small and improves with every analysis
  (`python -m agents.exposure_agent --warm --as-of <date>` fills it from the starter universe).
