# Decision memo: SME credit exposure to a Swedish downturn

*To: Credit Committee (fictional). From: Credit Risk Analytics. Data as of 2026-10.*

**Situation.** Company bankruptcies are high: 10,439 in the last 12
months, and the rate across the nine modelled industries is 0.72 per
100 firms per year, against 0.56 in 2019. Hotels and restaurants
(2.50), construction (1.56) and trade (1.53) have
the highest rates.

**Scenarios.** Baseline: Konjunkturinstitutet's latest forecast (vintage 20260930),
in which unemployment falls to 7.1 %. Adverse: the EBA 2025 stress-test
shock for Sweden applied to that baseline; unemployment rises to 14.5 %
and GDP growth falls to -6.2 % y/y.

**Results.** In the adverse scenario the 12-month bankruptcy rate peaks at
0.95 per 100 firms in 2027Q4 (80 % interval
0.85–1.06); in the baseline it eases to
0.60. A 1 pp rise in unemployment over a year is associated with a
+11.6 % change in expected bankruptcies (95 % CI +6.5 to +16.9 %). Relative to their
historical means, adverse first-year rates are 44–50 %
higher in every industry.

**Recommendation.**
1. Put **Hotels and restaurants**, **Construction** and **Wholesale and retail trade** on the watchlist (the
   largest increases in percentage points under adverse: +1.15,
   +0.76 and +0.75 pp vs historical means).
2. Apply probability-weighted PD overlays of +19 % (hotels and
   restaurants), +17 % (construction) and +16 % (trade)
   for the next 12 months. On a synthetic test portfolio this raises 12-month ECL by
   +17 % versus through-the-cycle PDs.
3. Re-assess pricing and limits if unemployment is 1 pp or more above its level a year
   earlier, or if monitoring turns red for an industry two quarters in a row.

**Risks and next steps.** The model did not beat a seasonal-naive forecast in the 2023–2026
test period (MAE 0.171 vs 0.100 pp) and its 80 % intervals covered
only 38 % of outcomes, so treat the paths as directional and the bands as
too narrow. Bankruptcy is a late, narrow proxy for default. Next: map the overlay to the
bank's own default data, pre-register variable-specific lags (the policy rate appears to
act with a delay), and add a persistence term.
