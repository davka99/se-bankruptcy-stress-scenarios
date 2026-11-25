# Data dictionary

All processed tables are in `data/processed/` (CSV committed; Parquet written when pyarrow
is installed). Rates are annualised and expressed as fractions (0.014 = 1.4 % per year).

## panel_monthly

| Column | Type | Unit | Source / definition |
|---|---|---|---|
| sector | str | code | Sector group (see `data/reference/sector_map.csv`) |
| month | str | YYYY-MM | Month the bankruptcy was opened |
| count | int | companies | Company bankruptcies, Tillväxtanalys table 12 (sole traders included) |
| source | str | – | Always `tillvaxtanalys` (no splice with SCB is needed) |
| is_preliminary | bool | – | True for the latest three published months (no flag in the source) |

## panel_monthly_source

As `panel_monthly`, but at the source's 13 group codes (`source_code`) before trade (45/46/47)
and hospitality (55/56) are summed.

## county_total

| Column | Type | Unit | Source |
|---|---|---|---|
| month | str | YYYY-MM | |
| county_total | int | companies | Sum over the 21 counties in Tillväxtanalys table 11 (independent total) |

## panel_quarterly

| Column | Type | Unit | Source / definition |
|---|---|---|---|
| sector, quarter | str | code, YYYYQn | Complete quarters only |
| count | int | companies | Sum of the three months |
| is_preliminary | bool | – | Any month in the quarter is preliminary |
| firms_year | int | year | Year of the stock used (previous year; latest stock held if not yet published) |
| firms | float | enterprises | SCB FDB `TAB5166`, November stock, SNI 2007 divisions summed to sectors |
| firms_fek | float | enterprises | SCB FEK `TAB600`/`TAB6017` (sensitivity denominator) |
| rate | float | per year | `4 × count / firms` |
| rate_fek | float | per year | `4 × count / firms_fek` |
| rate_r4 | float | per year | Rolling four-quarter count / firms |
| covid_support | int | 0/1 | 1 in 2020Q2–2021Q4 (pre-registered) |
| unemp, d_unemp | float | %, pp | AKU 15–74 SA, quarterly mean; change vs same quarter a year earlier |
| gdp_level, gdp_yoy | float | SEK m, % | GDP SA fixed prices (ref. 2025); growth vs a year earlier |
| policy_rate, d_policy | float | %, pp | Riksbank policy rate, quarterly mean of daily values; y/y change |
| source | str | – | `tillvaxtanalys` |

## macro_quarterly

One row per quarter from 2001Q1 with `unemp`, `gdp_level`, `policy_rate`, `d_unemp`,
`gdp_yoy`, `d_policy` as above. The latest quarter can be partial for the policy rate and
missing for GDP (publication lag, see `docs/decisions.md` A4).

## firms_fdb, firms_fek

`sector`, `year`, `firms`: annual stocks by sector (FDB reference month November).

## Reference tables (`data/reference/`)

| File | Content |
|---|---|
| sector_map.csv | Source codes -> sector, built from the source's own codes and labels |
| validation_anchor_2023.csv | Tillväxtanalys Statistik 2024:02, Table 1 (counts and shares, 2023) |
| eba_2025_sweden.csv | Sweden's rows from the EBA 2025 scenario workbook (parsed, not typed) |
