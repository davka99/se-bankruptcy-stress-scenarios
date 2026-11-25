# Design decisions

Each decision states the choice, the reason and the rejected alternatives. Sections 1–9 were
committed **before any model was estimated** and the commit is tagged `prereg`. Later
changes are added at the bottom under *Amendments*, each with a date and a reason, so the
git history shows what was decided before and after seeing results.

## 1. Industry groups

**Choice:** nine modelled groups plus "unspecified", built from Tillväxtanalys' own group
codes (`data/reference/sector_map.csv`): AGR 01–03, MAN 05–39, CON 41–43, TRD 45–47,
TRN 49–53, HOR 55–56, ICT 58–63, FRB 64–82, EHO 85–99, UNS unspecified. The source splits
trade (45/46/47) and hospitality (55/56); these are summed.

**Why:** the same grouping is used in Tillväxtanalys' annual report, which is our validation
anchor, and it keeps counts large enough per quarter. "Unspecified" is not modelled but its
share over time is reported.

**Rejected:** modelling the 12 source codes separately (hotels SNI 55 has very few
bankruptcies per quarter, which makes rates noisy).

## 2. SNI 2025

FDB stocks up to 2025 are SNI 2007, so denominators are unaffected until 2027 quarters.
For the 2026 bankruptcy months the coding standard is not stated in the metadata. Rule:
run the level-jump test at 2026M01 per sector. If a sector flags and the jump is not
explained by macro developments, use SCB's SNI 2007–SNI 2025 key to quantify the break; if
it cannot be bridged, end the model sample at 2025Q4 and say so under Limitations.

## 3. Grain

Descriptive analysis per sector × month. **Models per sector × quarter** (GDP and the
scenarios are quarterly or annual, and quarters are less noisy).

## 4. KPI: bankruptcy rate

- Numerator: company bankruptcies in sector *s* in quarter *q* (sum of months).
- Denominator: FDB enterprises in sector *s* in November of the previous year.
- Annualised rate: `rate_{s,q} = 4 × count_{s,q} / firms_{s,year(q)-1}`. A rolling
  four-quarter sum over the stock is also reported.
- Population: companies, all legal forms counted by the source (sole traders included).
- Denominator variants: (a) FDB all, (b) FEK enterprises, (c) limited companies only, if
  a denominator by legal form is available.
- **Rule for the primary denominator (fixed now):** the variant whose 2023 annual rates by
  sector (count 2023 / stock November 2022) have the lowest mean absolute deviation in
  percentage points from Tillväxtanalys' published 2023 shares (9 sectors, UNS excluded)
  becomes primary. Ties go to FDB.

## 5. Splice SCB → Tillväxtanalys

Not needed: Tillväxtanalys' table 12 contains the whole series from 2009M01. The columns
`source` and `is_preliminary` are still kept; the latest published month is flagged as
preliminary.

## 6. Pandemic

`covid_support = 1` for **2020Q2–2021Q4**. Reason: tax deferrals were introduced in March
2020 and reorientation support (omställningsstöd) covered turnover losses from spring 2020
to September 2021, with a further period December 2021–February 2022 (Skatteverket,
"Reorientation support"). Sensitivity: (i) without the dummy, (ii) dummy to 2022Q1,
(iii) pandemic quarters excluded from estimation. The dummy is 0 in all forecasts.

## 7. Bankruptcy ≠ default

Bank default is 90 days past due or unlikely-to-pay; bankruptcy is a later and narrower
event. The PD overlay in phase 4 is therefore a **relative** scaling, not a level.

## 8. Pre-registration of the model

**Model form (count GLM, NB2 with offset):**

`count_{s,q} ~ NB2(μ_{s,q}, α)`,
`log μ_{s,q} = log(firms_{s,y-1}) + η_s + δ_{quarter(q)} + τ·t + β'·macro_{q−k} + γ·covid_q`

**Candidate variables and expected signs:**

| Variable | Definition | Expected sign |
|---|---|---|
| `d_unemp` | change in the unemployment rate 15–74 (SA, quarterly mean) vs same quarter a year earlier, percentage points | + |
| `gdp_yoy` | GDP growth, SA fixed prices, vs same quarter a year earlier, percent | − |
| `d_policy` | change in the policy rate (quarterly mean of daily values) vs a year earlier, percentage points | + |

All three are in both the KI baseline and the EBA scenario, which is required for the
scenario model. The business tendency indicator and EBA's sector GVA are used only in EDA
and as a plausibility check.

**Specification grid (8 specifications, no others):**

1–5. Variant A: common slopes, common lag k ∈ {0, 1, 2, 3, 4} for all three variables.
6. Variant B: best k from A, sector-specific slope on `d_unemp` (others common).
7. Variant C: as B, but sector slopes shrunk towards the common slope with precision
   weights (empirical Bayes).
8. Variant A at best k without the trend term.

**Selection rule:** lowest firm-weighted MAE of the annualised rate at horizon h = 4 over
origins whose target quarter is ≤ 2022Q4. Ties (within 1 %) go to the simpler model
(A before C before B; with trend before without, since trend is part of the baseline).

**Evaluation:** rolling origin, expanding window, first origin 2014Q4 (moved later if fewer
than 16 usable training quarters), horizons 1, 4, 8. Metrics: firm-weighted MAE of the rate,
MASE vs seasonal naive, coverage of 80 % intervals, CRPS (sample-based). MAPE is not a
headline metric. The **untouched test period** (targets from 2023Q1) is evaluated once,
after the selection is committed.

**Conditional backtest:** actual macro outcomes are used over the forecast horizon. A
real-time variant uses KI forecast vintages available at each origin.

## 9. Watchlist criteria

A sector is put on the watchlist if, under the adverse scenario, **the median rate in any
rolling four-quarter window within the 12-quarter horizon is at least 1.25 × the sector's
historical mean rate** (2009–latest, pandemic quarters excluded) **and the 10th percentile
of that window is above the historical mean**.

Why 1.25: a 25 % relative rise in expected bankruptcies is a material change for pricing
and limits on an SME book, and it is fixed here before any scenario has been run. The p10
condition requires that the rise is not only a central estimate. The watchlist is also
reported at 1.10 and 1.50 as a sensitivity, but the decision uses 1.25.

## 10. Implementation choices (phase 0)

- **NB2 estimation engine.** The NB2 likelihood is implemented directly in
  `src/models/nb2.py` (numpy/scipy, analytic gradient, cluster-robust sandwich covariance).
  A test compares it with `statsmodels.discrete.discrete_model.NegativeBinomial` (NB2, ML
  estimate of α) to 1e-4 whenever statsmodels is installed, which it is in CI. Reason: the
  development environment could not install statsmodels, and a small transparent
  implementation is easier to audit; the statsmodels test guards against errors.
- **Raw data are committed** as dated snapshots with manifests (URL, query, timestamp,
  rows, SHA-256), because official tables are revised and SCB's v1 API is being retired.
- **Versions are pinned** in `requirements.txt` so that CI and local runs agree.

## Amendments

### A1 (2026-11-23, phase 1, before any model estimation): primary denominator = FDB

Applying the rule in section 4 to the first data snapshot: mean absolute deviation from
Tillväxtanalys' published 2023 shares is **0.030 pp for FDB** (max 0.048) and 0.192 pp for
FEK (max 0.328). FDB with the November 2022 stock reproduces all nine published shares
after rounding to one decimal, so it is almost certainly the denominator the report uses.
FDB is primary; FEK is kept as a sensitivity column (`rate_fek`). Note that FEK excludes
financial corporations and divisions 97-99, which explains part of its larger deviation.

### A2 (2026-11-23, phase 1): denominator variant (c) dropped

Bankruptcies by industry x legal form exist monthly only in a table where region cannot be
eliminated (about 2.4 million cells), which the API refuses (HTTP 403). The annual table
by industry and legal form is fetched for description. FDB by legal form is not available
in the same table either, so the limited-company denominator variant is not built.

### A3 (2026-11-23, phase 1): SNI 2025 level-jump check passed

The level-jump test (y/y log change of 3-month sums starting at 2026M01 vs the 99th
percentile of each sector's own history, pandemic months excluded) flags no sector. The
largest absolute changes were AGR (+0.27, threshold 0.75) and HOR (-0.25, threshold 0.55).
The full sample to the latest quarter is kept. `data/reference/documented_breaks.csv` is
therefore not needed.

### A4 (2026-11-23, phase 1): publication lags

SCB publishes GDP about two months after the quarter, so GDP can lag the bankruptcy data by
one quarter. Rows without all drivers for a specification are dropped from that fit; in
scenarios each macro series is spliced to KI's forecast at its own last published quarter.

### A5 (2026-11-23, phase 1): Parquet copies are not committed

The pipeline writes Parquet when pyarrow is installed (it is in `requirements.txt`). Only
the CSV copies are committed, because they give readable diffs and every number can be
rebuilt from `data/raw/` with `python -m src.pipeline`.

### A6 (2026-11-23, phase 3): model selection, committed before the test period is evaluated

Selection used only forecasts whose target quarter is ≤ 2022Q4 (32 origins, 2014Q4–2022Q3).
Firm-weighted MAE of the annualised rate at h = 4, in percentage points
(`reports/tables/backtest_selection_summary.csv`):

| Specification | MAE h=4 | MASE h=4 |
|---|---|---|
| A, k=0 | 0.082 | 1.12 |
| C, k=0 | 0.083 | 1.14 |
| B, k=0 | 0.084 | 1.14 |
| A, k=1 | 0.090 | 1.23 |
| A, k=2 | 0.092 | 1.26 |
| A, k=3 | 0.099 | 1.35 |
| A, k=4 | 0.104 | 1.42 |
| A, k=0, no trend | 0.105 | 1.42 |

**Selected: variant A with lag 0** (common slopes, same-quarter macro drivers, with trend).
Sector-specific slopes (B, C) did not improve the backtest, so per section 8 they are not
used, and headline statements are made in percent (common) and percentage points (sector).

Two results are recorded here, before the test period is opened, because they matter for
how the model is presented:

- In the selection period **no satellite specification beats seasonal naive at h = 4**
  (MASE > 1); A_k0 beats it at h = 1 (MASE 0.91) and h = 8 (0.88). The no-macro baseline
  has the same h = 4 MAE as A_k0 (0.082). The macro terms therefore add little to point
  accuracy at one year in this period; their role is to translate scenarios into rates.
- **The 80 % intervals cover only 57–69 %** of outcomes. Parameter uncertainty and NB noise
  do not capture persistent sector-level deviations, so the intervals are too narrow. This
  is reported as a limitation, and scenario intervals are described as lower bounds.

### A7 (2026-11-23, phase 3): untouched test period, evaluated once after A6

Targets 2023Q1–2026Q2 (126 forecasts per horizon on the common set; 2026Q3 lacks published
GDP). Firm-weighted MAE in pp, h = 4: seasonal naive 0.100, ETS 0.108, **satellite A_k0
0.171**, NB without macro 0.182. MASE of the satellite model at h = 4 is 1.70 and coverage
of its 80 % intervals is 38 %.

The satellite model therefore **does not beat seasonal naive** in the test period, but it
does beat the no-macro baseline (so the macro terms add information). The 2023–2024 rise
was larger than the model's macro drivers imply, and seasonal naive benefits from the high
persistence of rates. This is reported as is in the README. The model is still used for
scenarios, because a scenario model must map macro paths to rates, which the naive and ETS
baselines cannot do, but its intervals are presented as too narrow and its level path as
uncertain.

Not changed after seeing the test period: the specification, lag, trend and variables.
Candidates for a future pre-registered round are listed under Limitations (variable-specific
lags, especially for the policy rate; a sector-level persistence term).

### A8 (2026-11-23, phase 4): scenario construction and watchlist outcome

- **Start and horizon:** start 2026Q3 (last complete bankruptcy quarter), 12 quarters.
  Exposure held at the November 2025 FDB stock. Pandemic dummy 0.
- **Baseline:** KI `SenastePrognosen` (archive vintage 20260930). Unemployment uses KI's
  quarterly table to 2027Q4 and then the annual table, interpolated with annual values at
  mid-year. GDP levels are spliced to SCB's last published quarter by KI's growth rates.
  Policy rate: KI's monthly averages.
- **Adverse:** annual EBA deviations (adverse − baseline) for scenario years 1–3, reached
  at the middle of each scenario year and interpolated linearly from 0 at the start, flat
  after year 3: +3.8, +7.1, +7.0 pp unemployment; −5.5 %, −13.2 %, −14.5 % GDP level
  (log); +1.2, +1.0, +0.8 pp short rate. EBA has a 3M SEK swap rate, not the policy rate;
  its deviation is used for the policy rate.
- **Plausibility check against EBA sector GVA:** the macro-financial scenario workbook
  (corrigendum, Feb 2025) contains no sector GVA sheet, so this check is **not done**.
- **Watchlist outcome:** the pre-registered rule flags **all nine** industries under the
  adverse scenario (and also at 1.10 and 1.50). This follows from the selected model's
  common slope: every industry's rate rises by about the same percentage. The rule does
  not discriminate with variant A. To produce a usable shortlist, industries are
  **prioritised by the increase in percentage points** (worst window median minus
  historical mean). This prioritisation was chosen after seeing the scenario results and
  is labelled as such; the pre-registered rule itself is reported unchanged.

### A9 (2026-11-23, phase 5): presentation and monitoring

- **Numbers in documents are generated.** `src/report_numbers.py` writes
  `reports/tables/key_numbers.json`; README, decision memo and Quarto report are rendered
  from templates in `docs/` by `python -m src.render_readme`, and `tests/test_readme.py`
  fails if a committed document differs from a fresh rendering.
- **Monitoring backfill:** the log starts with one-quarter-ahead forecasts from the
  conditional backtest in the test period (labelled `backfill`). Every pipeline run then
  registers the baseline forecast for the next quarter (`forecast_register.csv`); the
  monthly refresh evaluates it once the quarter is complete (labelled `live`).
- **ETS baseline:** implemented in-house as additive Holt-Winters with damped trend on
  log rates (`src/models/baselines.py`), because statsmodels could not be installed in
  the development environment. It is a baseline only; the NB2 estimator is the one
  cross-checked against statsmodels.
- **Pages:** `pages.yml` only runs when the repository is public (Pages on a free account).
- **Cross-environment reproducibility:** a full pipeline run on GitHub's Ubuntu runner
  (pinned versions) gave the same `key_numbers.json`, README and memo as the development
  run. Detail tables differ only at floating-point level (MAE < 1e-6 pp); simulated
  interval coverage can differ by up to about 1 percentage point because the random draws
  depend on the linear-algebra backend. Re-running in the same environment is exact.

### A10 (2026-11-25, round 2): pre-registration of a second model round, written before any round-2 estimate

**Why a second round.** A7 showed that the selected model A_k0 does not beat seasonal naive
in the test period (h = 4 MAE 0.171 vs 0.100 pp), that its 80 % intervals cover 38 %, and
that GDP growth has the wrong sign; A8 showed that the pre-registered watchlist ratio
cannot separate industries when the slope is common. A7 named two candidates: lags that
differ by variable and a sector-level persistence term.

**What is already known (so the round is not blind).** The test period 2023Q1–2026Q2 has
been seen (A7), and so have the round-1 coefficients (GDP +0.5 % per pp, policy rate
+0.9 %, both not significant). Selection below therefore uses the **selection period
only**; the test period is re-evaluated for every candidate and reported, but labelled
"seen before" and not used to choose.

**Candidates (6, no others).** All NB2 with firm offset, industry effects, quarter
dummies, trend and pandemic dummy as in section 8.

| Name | Macro terms | Intercept correction |
|---|---|---|
| `A_k0` | d_unemp, gdp_yoy, d_policy, lag 0 (round 1, reference) | – |
| `U0` | d_unemp lag 0 | – |
| `U0_P4` | d_unemp lag 0, d_policy lag 4 | – |
| `M+IC1` | best of the three rows above | ρ = 1 |
| `M+IC085` | best of the three rows above | ρ = 0.85 |

*Intercept correction (persistence):* at each forecast origin, c_s = log(Σ count / Σ μ̂)
over the industry's last four quarters up to the origin (in-sample fit of the model
estimated at that origin). Forecasts for h quarters ahead are multiplied by
exp(c_s · ρ^h). This carries a persistent industry deviation forward, which is the
information seasonal naive uses, while keeping the macro mapping needed for scenarios.

**Selection.** Lowest firm-weighted MAE of the annual rate at h = 4, selection period
(targets ≤ 2022Q4), same origins as A6. Step 1 picks the macro form among `U0`, `A_k0`,
`U0_P4` (ties within 1 % to the earlier name in that order, i.e. the simplest). Step 2
compares that form with and without the intercept correction (order: none, IC085, IC1).

**Adoption.** The round-2 winner replaces A_k0 as the scenario model **only if** its
selection-period h = 4 MAE is at least 5 % lower than A_k0's. Otherwise A_k0 stays and
round 2 is reported as a negative result.

**Intervals.** Empirical (split-conformal) bands: for each horizon, the 10th and 90th
percentiles of log(actual / forecast) of the winner in the selection period are applied
as multiplicative bands. Coverage is reported for the test period.

**Watchlist, round 2.** With a common slope, any ratio to an industry's own history moves
the same way for every industry, so A8's rule flags all or none. The round-2 rule ranks
by what a lender loses money on: the *additional* annual rate under stress, adverse minus
baseline, in the worst rolling four-quarter window. An industry is flagged if the median
additional rate is ≥ 1.25 × the firm-weighted average additional rate across the nine
industries **and** the 10th percentile of the additional rate is above 0. This rule is
written after A8's percentage-point ranking was seen, so it is not blind to the result;
it is reported next to the pre-registered rule, which is not changed.

### A11 (2026-11-25, round 2): result, evaluated once after A10

Source: `reports/tables/round2_backtest.csv`, `round2_selection.json`.
- **Step 1 (macro form), selection period, h = 4:** `U0` 0.079, `U0_P4` 0.079, `A_k0`
  0.082. `U0` is selected (simplest within 1 %). Dropping GDP and the policy rate does not
  hurt; the policy rate at lag 4 adds nothing.
- **Step 2 (intercept correction):** `U0+IC085` 0.075, `U0+IC1` 0.075, `U0` 0.079.
  `U0+IC085` is selected (tie within 1 %, listed first). Improvement over `A_k0`: 8.8 %,
  so the A10 adoption rule is met and the scenarios use `U0+IC085`.
- **Test period (seen before, not an untouched test), h = 4:** `U0+IC085` 0.125,
  `U0+IC1` 0.108, `A_k0` 0.171, seasonal naive 0.100. Round 2 still does not beat seasonal
  naive at four quarters. At h = 1 it does (0.074 vs 0.100); at h = 8 it is close (0.181 vs
  0.161). `U0+IC1` is better than the selected variant in the test period; it is **not**
  switched to, because that would be choosing on the test.
- **Intervals:** conformal bands from selection-period errors cover 84 / 73 / 62 % of test
  outcomes at h = 1 / 4 / 8 (model bands: 85 / 64 / 41 %).
- **Scenarios:** the adverse 12-month rate peaks at 0.98 per 100 firms in 2027Q4 (80 %
  0.88–1.09) vs 0.95 with `A_k0`. The intercept correction raises most industries'
  current level (it is positive in 8 of 9; manufacturing −0.10), so overlays relative to
  historical means are larger than in round 1 and now differ by industry.
- **Watchlist:** the A9 rule still flags 9 of 9. The A10 rule flags hotels and
  restaurants, construction, trade, and transport and storage.
