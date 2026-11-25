# Decision memo: SME credit exposure to a Swedish downturn

*To: Credit Committee (fictional). From: Credit Risk Analytics. Data as of {{ last_month }}.*

**Situation.** Company bankruptcies are high: {{ bankruptcies_last_12m }} in the last 12
months, and the rate across the nine modelled industries is {{ total_rate_latest_4q }} per
100 firms per year, against {{ total_rate_2019 }} in 2019. Hotels and restaurants
({{ HOR_rate_now }}), construction ({{ CON_rate_now }}) and trade ({{ TRD_rate_now }}) have
the highest rates.

**Scenarios.** Baseline: Konjunkturinstitutet's latest forecast (vintage {{ ki_vintage_id }}),
in which unemployment falls to {{ baseline_unemp_end }} %. Adverse: the EBA 2025 stress-test
shock for Sweden applied to that baseline; unemployment rises to {{ adverse_unemp_peak }} %
and GDP growth falls to {{ adverse_gdp_min }} % y/y.

**Results.** In the adverse scenario the 12-month bankruptcy rate peaks at
{{ total_adverse_peak }} per 100 firms in {{ total_adverse_peak_q }} (80 % interval
{{ total_adverse_peak_lo }}–{{ total_adverse_peak_hi }}); in the baseline it eases to
{{ total_baseline_min }}. A 1 pp rise in unemployment over a year is associated with a
{{ irr_d_unemp }} % change in expected bankruptcies (95 % CI {{ irr_d_unemp_ci }} %). Relative to their
historical means, adverse first-year rates are {{ overlay_adv_min }}–{{ overlay_adv_max }} %
higher in every industry.

**Recommendation.**
1. Put {{ r2_watchlist_names }} on the watchlist: under stress their bankruptcy rate rises
   by at least 1.25 × the average additional rate of {{ r2_avg_add_pp }} pp (hotels and
   restaurants +{{ r2_add_pp_HOR }}, construction +{{ r2_add_pp_CON }}, trade +{{ r2_add_pp_TRD }},
   transport +{{ r2_add_pp_TRN }} pp per year, adverse minus baseline).
2. Apply probability-weighted PD overlays of {{ HOR_overlay_weighted }} % (hotels and
   restaurants), {{ CON_overlay_weighted }} % (construction) and {{ TRD_overlay_weighted }} % (trade)
   for the next 12 months. On a synthetic test portfolio this raises 12-month ECL by
   {{ synthetic_ecl_weighted_vs_ttc }} % versus through-the-cycle PDs.
3. Re-assess pricing and limits if unemployment is 1 pp or more above its level a year
   earlier, or if monitoring turns red for an industry two quarters in a row.

**Risks and next steps.** The first model did not beat a seasonal-naive forecast in the
2023–2026 test period (MAE {{ test_mae_sat }} vs {{ test_mae_snaive }} pp; 80 % intervals covered
{{ test_cov_sat }} %). A pre-registered second round (unemployment only, plus industry
persistence) cut the error to {{ r2_test_mae_U0_IC085 }} pp and is used for these scenarios, but
it still does not beat the naive forecast and was designed after the test period was seen.
Treat the paths as directional and the bands as too narrow. Bankruptcy is a late, narrow
proxy for default. Next: map the overlay to the bank's own default data and re-test the
model on 2026–2027 outcomes as they arrive (the monitoring log does this quarterly).
