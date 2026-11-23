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
