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
0.98 per 100 firms in 2027Q4 (80 % interval
0.88–1.09); in the baseline it eases to
0.63. A 1 pp rise in unemployment over a year is associated with a
+9.9 % change in expected bankruptcies (95 % CI +5.9 to +14.0 %). Relative to their
historical means, adverse first-year rates are 33–71 %
higher in every industry.

**Recommendation.**
1. Put hotels and restaurants, construction, wholesale and retail trade, transport and storage on the watchlist: under stress their bankruptcy rate rises
   by at least 1.25 × the average additional rate of 0.32 pp (hotels and
   restaurants +1.07, construction +0.70, trade +0.69,
   transport +0.67 pp per year, adverse minus baseline).
2. Apply probability-weighted PD overlays of +32 % (hotels and
   restaurants), +24 % (construction) and +22 % (trade)
   for the next 12 months. On a synthetic test portfolio this raises 12-month ECL by
   +24 % versus through-the-cycle PDs.
3. Re-assess pricing and limits if unemployment is 1 pp or more above its level a year
   earlier, or if monitoring turns red for an industry two quarters in a row.

**Risks and next steps.** The first model did not beat a seasonal-naive forecast in the
2023–2026 test period (MAE 0.171 vs 0.100 pp; 80 % intervals covered
38 %). A pre-registered second round (unemployment only, plus industry
persistence) cut the error to 0.125 pp and is used for these scenarios, but
it still does not beat the naive forecast and was designed after the test period was seen.
Treat the paths as directional and the bands as too narrow. Bankruptcy is a late, narrow
proxy for default. Next: map the overlay to the bank's own default data and re-test the
model on 2026–2027 outcomes as they arrive (the monitoring log does this quarterly).
