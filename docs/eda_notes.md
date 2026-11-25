# EDA notes

Figures: `reports/figures/eda_*.png`. Tables: `reports/tables/eda_*.csv`, `annual_rates.csv`.
These observations do **not** change the pre-registered choices in `docs/decisions.md`.

1. **Hotels and restaurants has the highest rate in every year.** Annual rates were
   1.4–1.9 per 100 firms in 2009–2019 and 2.8 in both 2024 and 2025. Construction and
   trade follow at roughly 1.0–1.7.
2. **The recent rise is broad.** Seven of nine sectors had their highest annual rate since
   2009 in 2023 or later. Manufacturing and agriculture are the exceptions: their 2009
   rates are still the highest in the series.
3. **The pandemic broke the macro link.** GDP fell sharply in 2020, but rates in most
   sectors were flat or lower in 2021–2022 than in 2019, which is consistent with the
   support programmes. This supports the pre-registered `covid_support` dummy.
4. **Policy-rate changes co-move most with rate changes.** Using y/y changes on both sides
   (to avoid trend-driven correlation), the median correlation across sectors is 0.39 for
   the policy-rate change at lag 1 and still 0.24 at lag 4.
5. **Unemployment changes are positively correlated only at short lags.** The median
   correlation is 0.22 at lag 0 and 0.13 at lag 1, then turns negative (-0.24 at lag 4).
   A plausible reading is that bankruptcies lead unemployment (job losses follow
   bankruptcies), so a long-lag unemployment coefficient may not have the expected sign.
   The pre-registered lag grid is unchanged; the backtest decides.
6. **GDP growth is negatively correlated at lags 0–3** (median about -0.2), as expected.
7. **Strong seasonality.** July and August hold about 6.8 % and 5.8 % of a year's
   bankruptcies, against 8.3 % for an even spread. Quarterly seasonal terms are needed.
8. **The unspecified-industry share fell from about 16 % (2009–2010) to about 7 %
   (2020–2026).** Sector counts in the early years are therefore understated relative to
   later years, which biases sector trends upwards. Agriculture's rate is tiny
   (about 0.03–0.06 per 100) because FDB counts many small farm units; its counts are
   noisy. Both points belong under Limitations.
