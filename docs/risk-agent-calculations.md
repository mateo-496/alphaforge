# How the risk score is calculated — step by step

This document explains every calculation behind the portfolio risk numbers AlphaForge shows: the **objective
risk** (0-100), the **personalised concern** (0-100, the headline), the **confidence** (0-1), the verdict and
the level label. It follows the code line by line, with every constant and two worked examples computed from
real app runs.

> **Status (2026-11-15).** This describes the code in the working tree, which includes changes made while
> calibrating the scores on the risk ladder (`examples/risk_ladder.json`). The changes are not committed yet:
> the new country hazard (§4.2), the company sleeve (§5.3), the quadratic block mean (§6.4) and the final
> calibration (§6.7). The final calibration is still **neutral** (`r_mid = 0.5`, `r_k = 1`, so the identity) until its
> constants are fitted; §11 lists what changed versus the previous version.

---

## 0. Who computes what

| Part | What it does | Where |
|---|---|---|
| Agents (LLMs) | Extract **facts**: verbatim quotes from filings, country lists, one-line drivers, prose. | `agents/*.py` |
| Code | Checks the quotes, then computes **every number** of the score. | `tools/`, `web/scoring.py` |
| Risk agent | Writes the 4 explanation sentences shown under the score. Computes nothing. | `agents/risk_agent.py` |

**Rule: no number written by a language model enters the score.** The risk agent receives the computed facts and
writes four sentences (countries, holdings, profile, watch). Code then extracts every number in each sentence
(regex `[-+]?\d+(\.\d+)?%?`) and **drops any sentence containing a number that is not in the facts** (the facts'
numbers are accepted as written, ×100, rounded to 0 or 1 decimal, with or without `%`). If the agent fails, the
report keeps the factual lines written by code.

The calculation runs in `web/pipeline.py`, step 6 "Portfolio risk", after the agents have gathered the inputs:

```
weights w_i ─┐
             ├─ exposure X_c ─┬─ A1 (macro fragility M_c)      ─┐
splits w_ic ─┘                └─ A2 (country hazard g_c)        ├─ two-stage formula ─ objective R ─ concern C
filings  ─────────────────────── A3 (filing flags f_i)         ─┘          ▲
profile risk level ──────────────────────────── tolerance t ───────────────┘ (concern only)
```

---

## 1. Notation

| Symbol | Meaning | Range |
|---|---|---|
| $i$ | a holding (ticker) | |
| $c$ | a country (ISO alpha-3), or `Other` (revenue no source attributes to a country) | |
| $w_i$ | portfolio weight of holding $i$ (the form's weights rescaled to sum to 1) | 0-1 |
| $w_{ic}$ | share of holding $i$'s revenue earned in country $c$ ($\sum_c w_{ic} = 1$) | 0-1 |
| $X_c$ | portfolio revenue exposure to country $c$ | 0-1 |
| $M_c$ | macro fragility of country $c$ | 0-1 |
| $g_c$ | geopolitical hazard of country $c$ | 0-1 |
| $f_i$ | filing flags of company $i$ | 0-1 |
| $A_1, A_2, A_3$ | the three risk inputs of the formula | 0-1 |
| $c_1, c_2, c_3$ | their confidences (share of the portfolio each input actually covers) | 0-1 |
| $s$ | share of the portfolio held in single companies | 0-1 |
| $t$ | investor risk tolerance | 0-1 |

`clip(x)` means $\min(1, \max(0, x))$.

---

## 2. Portfolio weights

The form accepts weights, quantities or market values (`web/app.py`, `build_request`):

- **Quantities** × last close on or before the analysis date, in the base currency → market values.
- Amounts are added up per ticker (a ticker entered twice is summed), then rescaled:
  $w_i = \text{amount}_i / \sum_j \text{amount}_j$, rounded to 6 decimals.
- Negative amounts (short positions) are rejected. Tickers outside the asset universe are ignored, with a note.

---

## 3. Country exposure $X_c$

### 3.1 Each holding's split $w_{ic}$ (exposure agent)

Each holding gets a country revenue split from the best source available, tagged with its tier (full rules in
`docs/risk-formula.md` §1 and `agents/exposure_agent.py`):

| Tier | Source | Weight $\lambda$ of the reported split |
|---|---|---|
| 1 | XBRL geographic table of the latest 10-K / 20-F / 40-F filed on or before the analysis date | 1.0 |
| 2 | Filing text, each share inside a verified verbatim quote | 0.8 |
| 3 | Previous filing (stale) | 0.6 |
| 4 | Sector peers' average split | 0 |
| 5 | Home-bias prior | 0 |
| 6 | Weekly returns on country ETFs (equity ETFs) | 0 |

A reported split is blended with the prior: $w_{ic} = \lambda\, w^{\text{reported}}_{ic} + (1-\lambda)\, w^{\text{prior}}_{ic}$.
Bond ETFs use their recorded countries, weighted by GDP. **Gold and crypto have no country**: their split is
`{"Other": 1}`.

### 3.2 Portfolio exposure

$$X_c = \sum_i w_i\, w_{ic}$$

(`web/scoring.py`, `exposure`). `Other` is kept in $X$ but **counts as not covered** in every input below.

---

## 4. The two country inputs

### 4.1 Macro fragility $M_c$ (country risk agent → `tools/risk_calculator.py`)

The latest World Bank value of each indicator **published by the analysis date** (a value for year $Y$ is only
used from $Y+1$) is mapped linearly to a 0-100 risk score:

$$\text{risk}(x) = 100 \cdot \text{clip}\Big(\frac{x - \text{low}}{\text{high} - \text{low}}\Big) \quad (\text{reversed: } 100 - \text{that})$$

| Component | World Bank code | low → high (0 → 100 risk) | Weight |
|---|---|---|---|
| Inflation, % | FP.CPI.TOTL.ZG | 2 → 20 | 0.15 |
| Unemployment, % | SL.UEM.TOTL.ZS | 3 → 25 | 0.10 |
| Central government debt, % of GDP | GC.DOD.TOTL.GD.ZS | 30 → 150 | 0.15 |
| Low GDP growth, % (reversed) | NY.GDP.MKTP.KD.ZG | +5 → −5 | 0.10 |
| Bank non-performing loans, % | FB.AST.NPER.ZS | 1 → 15 | 0.20 |
| Weak bank capital, capital/assets % (reversed) | FB.BNK.CAPA.ZS | 20 → 8 | 0.15 |
| Weak liquidity (reversed) | — (no World Bank field is fetched) | 160 → 80 | 0.15 |

The score is the weighted mean over the **available** components only (missing ones drop out and the weights are
renormalised):

$$\text{macro}_c = \frac{\sum_{k \in \text{avail}} \omega_k\, \text{risk}_k}{\sum_{k \in \text{avail}} \omega_k}, \qquad M_c = \text{macro}_c / 100$$

In practice the liquidity component is never available, so 6 components at most. A country with no World Bank
data (Taiwan; Hong Kong and Macao are reported with China) has no $M_c$.

*Example:* the USA's 2024 central government debt of 115.79% of GDP gives $100 \times (115.79-30)/120 = 71.5$ on
that component.

### 4.2 Geopolitical hazard $g_c$ (geopolitical agent → `tools/risk_math.hazard`)

Three measured parts, combined by code:

**a) Internal instability $S_c$** — World Bank Worldwide Governance Indicator *Political Stability and Absence of
Violence/Terrorism* (`GOV_WGI_PV.EST`, source 3, latest year $\le$ analysis year − 1), an estimate on about
−2.5 (unstable) to +2.5 (stable):

$$S_c = \text{clip}\Big(\frac{1.5 - PV_c}{1.5 - (-2.0)}\Big)$$

$PV = +1.5$ or better → 0; $PV = -2.0$ or worse → 1. Taiwan is not in the World Bank data: no $S_c$.

**b) External tension $E_c$** — the Caldara–Iacoviello country GPR index (share of articles in ten US, UK and
Canadian newspapers that mention the country together with geopolitical tensions). Take the mean of its last 12
monthly values before the analysis month, $\overline{GPR}^{12m}_c$, on a log scale:

$$E_c = \text{clip}\Big(\frac{\ln \overline{GPR}^{12m}_c - lo}{hi - lo}\Big)$$

- $lo$ = 10th percentile and $hi$ = maximum of $\ln \overline{GPR}^{12m}$ over all covered countries on that date
  (`tools/gpr.tension_anchors`; needs at least 3 countries).
- **Not computed for the USA, the UK and Canada**: the index is built from their newspapers, so home coverage
  inflates their level (the USA's 4.5 is twice Israel's 2.0).
- No $E_c$ for countries the index does not cover (about 44 countries are covered).

**c) Heat** — how tense this month is for the country *compared with its own past*: the share of its past months
(from the start of the series, at least 36 months, all strictly before the analysis month) whose GPR is at or below
the latest value. If the country is not covered, the global GPR's percentile is used (labelled "global").

**Combination:**

$$L_c = \text{mean of the available parts among } (S_c, E_c), \qquad g_c = L_c \cdot \Big(\frac12 + \frac12\,\text{heat}_c\Big)$$

- The level $L_c$ says how dangerous the country is compared with other countries. Heat moves it between ×0.5
  (calmest month in its history) and ×1 (tensest). Unknown heat counts as 0.5 (×0.75).
- If neither $S_c$ nor $E_c$ exists, $g_c$ is **unknown** (`None`): the country is left out of $A_2$'s coverage (§5.2).

*Why the level matters:* heat alone was the previous $g_c$. When world tension rises, almost every country is near
the top of its own history (in November 2026: USA 0.92, Canada 0.92, Norway 0.98), so a Canadian bond fund and an
Israeli company looked alike.

---

## 5. The three risk inputs $A_1, A_2, A_3$ and their confidences

All in `web/scoring.py`, function `score`, applied to the portfolio's exposure $X$.

### 5.1 $A_1$ — national (macro) risk

$$A_1 = \frac{\sum_{c \ne \text{Other},\ M_c \text{ known}} X_c\, M_c}{\sum_{c \ne \text{Other},\ M_c \text{ known}} X_c},
\qquad c_1 = \frac{\sum_{c \ne \text{Other},\ M_c \text{ known}} X_c}{\sum_c X_c}$$

### 5.2 $A_2$ — geopolitical risk

$$A_2 = \frac{\sum_{c \ne \text{Other},\ g_c \text{ known}} X_c\, g_c}{\sum_{c \ne \text{Other},\ g_c \text{ known}} X_c},
\qquad c_2 = \frac{\sum_{c \ne \text{Other},\ g_c \text{ known}} X_c}{\sum_c X_c}$$

### 5.3 $A_3$ — company disclosures, over the company sleeve only

Only **single companies** (`asset_class == "equity"`) have a filing. Funds, bonds, gold and crypto have none: for
them the company term is *not applicable*, which is different from *not read yet*.

- **Filing flags** (filings agent → `web/firms.py` → `tools/risk_math.firm_flags`): the agent reads the latest
  annual filing and emits at most about 6 claims, each tagged with one of 8 channels (trade tariffs, export controls,
  sanctions, conflict exposure, supply chain, regulatory, FX/capital controls, financial stress) and a verbatim
  quote. Code checks each quote against the filing text. Then

  $$f_i = \frac{\#\{\text{distinct channels with at least one verified quote}\}}{8}$$

  The claim's severity and confidence written by the model are **not used**. With about 6 claims at most, $f_i$
  rarely exceeds 0.75. A filing that is not read within `FILINGS_WAIT_S` (45 s) carries on in the background:
  $f_i$ is **unknown** for this run (`None`), and the result is cached for the next analysis.
- **Company sleeve** $C = \{i : i \text{ is an equity}\}$, $s = \sum_{i \in C} w_i \,/\, \sum_i w_i$.

$$A_3 = \frac{\sum_{i \in C,\ f_i \text{ known}} w_i\, f_i}{\sum_{i \in C,\ f_i \text{ known}} w_i},
\qquad c_3 = \frac{\sum_{i \in C,\ f_i \text{ known}} w_i}{\sum_{i \in C} w_i}$$

If no input value is known, $A$ is `None`; with confidence 0 it is replaced by the prior in §6.1.

---

## 6. Stage 1 — objective risk $R$ (`tools/portfolio_score.portfolio_scores`)

Parameters (`Params`, frozen, so identical inputs always give identical outputs):

| Name | Value | Role |
|---|---|---|
| $\mu$ | 0.50 | neutral prior for unknown inputs |
| $\lambda$ | 0.0 | convexity of $f$ (0 = identity) |
| $\alpha$ | 0.50 | share of $A_1$ vs $A_3$ inside the structural block (when $s = 1$) |
| $w_S, w_G$ | 0.60, 0.40 | weights of the structural and geopolitical blocks |
| $q$ | 2.0 | power of the block mean (> 1: the worse block weighs more) |
| $\eta$ | 0.25 | interaction strength |
| $\tau, \kappa$ | 0.70, 0.35 | red-flag threshold and strength |
| $r_{mid}, r_k$ | 0.5, 1.0 | final calibration (currently the identity) |
| $k, a, b$ | 8.0, 0.15, 0.70 | personalised concern (stage 2) |

### 6.1 Shrink each input toward the prior by its confidence

$$\tilde A_k = c_k\, A_k + (1 - c_k)\, \mu \qquad (A_k = \text{None} \Rightarrow A_k := 0.5)$$

An input covering 60% of the portfolio keeps 60% of its value and takes 40% from the neutral 0.5.

### 6.2 Transform

$$f(x) = \frac{e^{\lambda x} - 1}{e^{\lambda} - 1}, \qquad \lambda = 0 \Rightarrow f(x) = x$$

With the current $\lambda = 0$ this step does nothing.

### 6.3 Blocks

$$w_3 = (1-\alpha)\, s, \qquad F_S = (1 - w_3)\, f(\tilde A_1) + w_3\, f(\tilde A_3), \qquad F_G = f(\tilde A_2)$$

- All companies ($s = 1$): $F_S = \tfrac12 \tilde A_1 + \tfrac12 \tilde A_3$ (the original formula).
- No companies ($s = 0$): $F_S = \tilde A_1$; neither $A_3$ nor its prior counts.

### 6.4 Base risk: weighted power mean of the blocks

$$B = \Big(\frac{w_S\, F_S^{\,q} + w_G\, F_G^{\,q}}{w_S + w_G}\Big)^{1/q}$$

With $q = 2$ this is a weighted quadratic mean: it equals $F$ when both blocks are equal and leans toward the
worse block when they differ.

### 6.5 Interaction

$$R_0 = B + \eta\, F_S\, F_G\, (1 - B)$$

Structural and geopolitical risk together are worse than either alone. The $(1-B)$ factor keeps $R_0 \le 1$.

### 6.6 Red flag (weakest link)

$$\text{peak} = \max(\tilde A_1, \tilde A_2, \tilde A_3) \ \ (\tilde A_3 \text{ only if } s > 0), \qquad
h = \Big(\frac{\max(0,\ \text{peak} - \tau)}{1 - \tau}\Big)^2, \qquad R_1 = R_0 + \kappa\, h\, (1 - R_0)$$

Zero until one input passes 0.70, then a smooth (squared) ramp: a single input at 1.0 adds 35% of the remaining gap
to 1.

### 6.7 Final calibration

$$R = g(R_1,\ r_{mid},\ r_k), \qquad g(x, m, k) = \frac{r^k}{1 + r^k}, \quad r = \frac{x/(1-x)}{m/(1-m)}$$

$g(0)=0$, $g(m)=0.5$, $g(1)=1$, increasing. $r_{mid}$ is meant to be the raw $R_1$ of the **world-economy
portfolio** ($X_c$ = World Bank GDP weights, no companies), so that a portfolio as risky as the world economy scores
50, and $r_k$ spreads the scores over 0-100. Until those are fitted, $(0.5, 1)$ makes $R = R_1$.

**Objective risk** $= 100\,R$, rounded to 2 decimals. It does **not** depend on the investor.

---

## 7. Stage 2 — personalised concern $C$ (the headline)

### 7.1 Tolerance

Profile risk level 1-5 → label → tolerance $t$ (`web/scoring.tolerance`, `TOLERANCE_MAP`):

| Risk level | 1 | 2 | 3 | 4 | 5 |
|---|---|---|---|---|---|
| Label | low | low-moderate | moderate | moderate-high | high |
| $t$ | 0.20 | 0.40 | 0.60 | 0.75 | 0.85 |
| Comfort level $\rho = 0.15 + 0.70\,t$ | 0.29 | 0.43 | 0.57 | 0.675 | 0.745 |

$\rho$ is the objective risk (0-1) at which concern starts to rise for that investor.

### 7.2 Normalised logistic gap

$$\sigma(z) = \frac{1}{1+e^{-z}}, \qquad
C = 100 \cdot \frac{\sigma\big(k(R-\rho)\big) - \sigma(-k\rho)}{\sigma\big(k(1-\rho)\big) - \sigma(-k\rho)}, \quad k = 8$$

$C = 0$ when $R = 0$ and $C = 100$ when $R = 1$ for every investor. Concern is about halfway when $R$ reaches the
comfort level. Higher tolerance → lower concern for the same portfolio.

### 7.3 Confidence

$$\text{conf} = \frac{w_S (1-w_3)\, c_1 + w_S\, w_3\, c_3 + w_G\, c_2}{w_S + w_G}$$

The block weights applied to the input confidences: the share of the score resting on measured data, not the
prior. Rounded to 2 decimals.

---

## 8. Labels, verdict, tables and recommendations

- **Level** (from the concern $C$): low < 25 ≤ moderate < 50 ≤ elevated < 75 ≤ high.
- **Verdict** (`web/scoring.verdict`): **clear** when objective $\le 100\rho$ **and** no stated profile limit is broken
  (single-holding cap, crypto cap, excluded sectors/themes/tickers, volatility limit); otherwise **act**.
- **Holdings table**: the same function on one holding's own split, $\text{score}(w_{ic}, M, g, [(1, f_i)])$, with $s = 1$
  for a company and $s = 0$ for a fund.
- **Countries table**: the same function on one country alone, $\text{score}(\{c: 1\}, M, g, [\,])$, with $s = 0$.
- **Recommendations** (`web/recommend.py`): fix broken limits first, then move the riskiest holdings into the best
  profile-approved fund in quarters until the objective score is back under $100\rho$. Every swap is re-scored with
  the full formula above.

### What is never in the score

Scenario likelihoods and impacts, filing-risk severities, GPR claims, country drivers and macro notes are shown
as context only. They are written or judged by a language model, so they never enter a number.

---

## 9. Worked example 1 — Canadian cash (`L01-cad-cash`, real app run, analysis date 2026-11-12)

Holdings: ZST.TO 70%, XBB.TO 30% (Canadian bond ETFs, recorded country Canada).

| Step | Calculation | Value |
|---|---|---|
| Exposure | $X_{CAN} = 0.7 \cdot 1 + 0.3 \cdot 1$ | 1.0 |
| $M_{CAN}$ | World Bank macro score 28.66 / 100 | 0.2866 |
| $S_{CAN}$ | $PV = 0.81$: $(1.5 - 0.81)/3.5$ | 0.1971 |
| $E_{CAN}$ | press country | — |
| heat | Canada's GPR above 91.8% of its past months | 0.918 |
| $g_{CAN}$ | $0.1971 \cdot (0.5 + 0.5 \cdot 0.918)$ | 0.1891 |
| $A_1, c_1$ | only Canada | 0.2866, 1.0 |
| $A_2, c_2$ | only Canada | 0.1891, 1.0 |
| $s$, $A_3$ | no companies | 0, not applicable |
| $F_S$, $F_G$ | $w_3 = 0$: $F_S = 0.2866$; $F_G = 0.1891$ | |
| $B$ | $\sqrt{0.6 \cdot 0.2866^2 + 0.4 \cdot 0.1891^2}$ | 0.2522 |
| $R_0$ | $0.2522 + 0.25 \cdot 0.2866 \cdot 0.1891 \cdot (1 - 0.2522)$ | 0.2623 |
| Red flag | peak 0.2866 < 0.70 | $h = 0$ |
| **Objective** | $100 \cdot 0.2623$ | **26.23** |
| **Concern** (moderate, $\rho = 0.57$) | §7.2 | **7.12** |
| Confidence | $(0.6 \cdot 1 + 0.4 \cdot 1)/1$ | 1.00 |

The same run scored **74.46** under the previous version: Canada's heat (0.918) was used as its hazard, the
missing company term was filled with the prior 0.5, and the red flag fired on the 0.918.

## 10. Worked example 2 — US mega-cap tech (`L05-us-megacap-tech`, real app run)

Holdings: QQQ 30%, AAPL 20%, AMZN 20%, MSFT 15%, GOOGL 15%. Main exposures: USA 60.0%, China 10.1%,
Taiwan 5.9%, Germany 2.3%, UK 2.0%.

| Country | $PV$ → $S$ | $\overline{GPR}^{12m}$ → $E$ | heat | $g_c$ | $M_c$ |
|---|---|---|---|---|---|
| USA | −0.302 → 0.5149 | press country → — | 0.918 | 0.5149 × 0.959 = 0.4937 | 0.3346 |
| China | 0.022 → 0.4223 | 1.1854 → 0.8580 | 0.857 | mean 0.6401 × 0.9285 = 0.5944 | 0.2356 |
| Taiwan | not in World Bank → — | 0.2225 → 0.4183 | 0.775 | 0.4183 × 0.8875 = 0.3713 | — |

| Step | Calculation | Value |
|---|---|---|
| $A_1$, $c_1$ | exposure-weighted $M_c$; Taiwan (no $M$) not covered | 0.3169, 0.941 |
| $A_2$, $c_2$ | exposure-weighted $g_c$ | 0.4700, 1.0 |
| $s$ | AAPL + AMZN + MSFT + GOOGL (QQQ is a fund) | 0.70 |
| $A_3$, $c_3$ | only AMZN's filing read in time: 5 of 8 channels verified, $f = 0.625$; covered $0.2 / 0.7$ | 0.625, 0.286 |
| Shrink | $\tilde A_1 = 0.941 \cdot 0.3169 + 0.059 \cdot 0.5$; $\tilde A_3 = 0.286 \cdot 0.625 + 0.714 \cdot 0.5$ | 0.3277, 0.4700, 0.5357 |
| Blocks | $w_3 = 0.5 \cdot 0.7 = 0.35$; $F_S = 0.65 \cdot 0.3277 + 0.35 \cdot 0.5357$; $F_G = 0.4700$ | 0.4005, 0.4700 |
| $B$ | $\sqrt{0.6 \cdot 0.4005^2 + 0.4 \cdot 0.4700^2}$ | 0.4296 |
| $R_0$ | $0.4296 + 0.25 \cdot 0.4005 \cdot 0.4700 \cdot (1 - 0.4296)$ | 0.4565 |
| Red flag | peak 0.5357 < 0.70 | $h = 0$ |
| **Objective** | | **45.64** |
| **Concern** (moderate) | | **28.89** |
| Confidence | $(0.6 \cdot 0.65 \cdot 0.941 + 0.6 \cdot 0.35 \cdot 0.286 + 0.4 \cdot 1)/1$ | 0.83 |

The previous version scored this run **71.20**. Once the other three filings are read (cached for the next
analysis), $c_3$ rises and $A_3$ moves from the prior toward their measured flags.

Both examples were recomputed by hand from the run's stored inputs and match the code's output (the 0.01
differences come from confidences rounded for display).

---

## 11. Changes versus the previous version (not committed yet)

| | Previous | Now | Why |
|---|---|---|---|
| $g_c$ | heat only (own-history GPR percentile) | level (WGI + GPR level) × heat | heat is high for almost every country when world tension rises: no cross-country signal |
| $A_3$ for funds, bonds, gold, crypto | unknown → prior 0.5 | not applicable ($s$) | a bond fund has no filing; the prior added a mid-scale company risk to every fund portfolio |
| Block mean | weighted mean, $\lambda = 2$ convexity (earlier) | quadratic mean, $\lambda = 0$ | the convexity squeezed scores into a narrow band |
| Final calibration | none | $g(R_1, r_{mid}, r_k)$, neutral for now | to use the full 0-100 range against a measured anchor |

**Effect on the risk ladder** (ten real app runs, same moderate profile; objective score):

| Portfolio | Intended | Previous | Now (before calibration) |
|---|---|---|---|
| L01 Canadian cash | ~5 | 74.46 | 26.23 |
| L02 Canadian income | ~15 | 74.23 | 30.21 |
| L03 North American 60/40 | ~25 | 74.09 | 34.66 |
| L04 Developed world | ~35 | 70.64 | 37.54 |
| L05 US mega-cap tech | ~45 | 71.20 | 45.64 |
| L06 Semiconductors | ~55 | 62.40 | 43.03 |
| L07 Emerging markets | ~65 | 66.49 | 40.51 |
| L08 Frontier Africa/LatAm | ~75 | 58.15 | 41.56 |
| L09 China/Taiwan | ~85 | 68.16 | 46.26 (no filing read yet) |
| L10 Conflict zones | ~95 | still running | |

### Known limits

- **Macro fragility leans on public debt**: India (0.22), Indonesia (0.12) and China (0.24) score as less fragile
  than Canada (0.29) or the USA (0.33), which pulls emerging-market portfolios down through $A_1$.
- **Taiwan is not in the World Bank data**: its level comes from the GPR level alone (0.42), likely too low.
- **Germany and France** get a high external tension from heavy war coverage.
- **The exposure agent's returns-based tier is noisy**: in L08 the Africa ETF was mapped to South Africa, Canada,
  the UK and Korea, so Nigeria, Egypt and Kenya never reached the score.
- **Filings still being read count as unknown**: the score of the same portfolio can move on the next analysis
  once its filings are cached.
- **Gold and crypto have no country**: they sit at the neutral prior in $A_1$ and $A_2$.
