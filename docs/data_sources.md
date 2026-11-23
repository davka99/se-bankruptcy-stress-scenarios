# Data sources

Verified on **2026-11-23** against the live APIs and publication pages. Retrieval dates for
the committed snapshots are recorded per file in `data/raw/<source>/<date>/manifest.json`.

## Verification table

| # | Data | Source and exact ID | Variables used | Period / frequency | Format | Industry standard | Status vs plan |
|---|---|---|---|---|---|---|---|
| D1 | Company bankruptcies by industry and month | Tillväxtanalys statistics portal, PxWeb **API v1** (POST), table `12_konkurser_manad_tot_bransch.px` ("Konkurser per månad 2009M01–2026M10, efter bransch", updated 2026-11-05) | `Bransch` (13 codes incl. `bransch_ospecificerad`), `variabel=0` (number of bankruptcies) | 2009M01–2026M10, monthly | json-stat2 | Group codes are SNI 2007 ranges (`01-03` … `85-99`); see SNI note below | **Better than planned:** the whole series from 2009 is in one table, so no SCB → Tillväxtanalys splice is needed. The portal runs PxWeb API v1, not v2. |
| D1 (total) | Company bankruptcies by county and month | Tillväxtanalys table `11_konkurser_manad_lan.px` | `Län` (21 counties) | 1996M01–2026M10 | json-stat2 | – | Used as an independent national total for the sum check (the industry table has no total row). |
| D1 (detail) | Bankruptcies by industry, region, legal form, size class | Tillväxtanalys table `14_konkurser_manad_kom_bransch_juridisk_form_storleksklass_popAH.px` | `Juridisk_form` (`a` limited companies, `e` sole traders, `h` partnerships) | 2009M01–2026M10 | json-stat2 | as D1 | Legal-form and size-class splits exist per industry and month, but region cannot be eliminated and the API refuses the ~2.4 million-cell query (HTTP 403). The annual table `02_konkurser_ar_tot_bransch_jurform.px` is fetched instead. |
| D1 (reserve) | SCB NV1401 | SCB | – | stops May 2024 | – | – | Not needed (see D1). SCB stopped publishing with May 2024. |
| D2 | Latest months | Same tables as D1 | – | Latest: October 2026, published 12 Nov 2026 | – | – | D1 does not lag, so D2 is the same table. Preliminary/revised flags are **not** exposed in the table metadata; the latest month is treated as preliminary (`is_preliminary`). |
| D3 | Number of enterprises by industry (denominator) | SCB FDB (NV0101), PxWebApi v2 table **`TAB5166`** ("Företag (FDB) efter näringsgren SNI2007 och storleksklass. År 2008–2025", updated 2025-12-02) | SNI 2007 divisions (2-digit codes), all size classes | 2008–2025, annual (reference: November) | json-stat2 | SNI 2007 | The planned ID `FDBR07N` was the v1 name; the v2 ID is `TAB5166`. Population: all legal and natural persons registered for VAT, F-tax or as employers (includes dormant units). The 2026 stock (expected Dec 2026) may be coded in SNI 2025; it is first needed for 2027 quarters. |
| D3b | Active enterprises (alternative denominator) | SCB FEK (NV0109) `TAB600` (2000–2021) and `TAB6017` (2022–2024) | number of enterprises by SNI 2007 | annual | json-stat2 | SNI 2007 | Two table vintages with a break in 2022; used for the denominator sensitivity only. |
| D4 | Unemployment rate 15–74, seasonally adjusted | SCB AKU, `TAB6387` | `Arbetskraftstillh=ALÖSP`, `TypData=SR_DATA`, `Kon=1+2`, `Alder=tot15-74` | 2001M01–2026M10, monthly | json-stat2 | – | 2001–2020 are linked series (macro-linked 2001–04, micro-linked 2005–20) because of the 2021 AKU redesign; seasonally adjusted values are revised at every release. |
| D5 | GDP, fixed prices, quarterly | SCB NR, `TAB4553` | `BNPM`, `NR0103CE` (seasonally adjusted, fixed prices ref. year 2025, SEK m) | 1981K1–2026K2 | json-stat2 | – | SCB's seasonally adjusted series is also calendar adjusted; y/y growth is computed from levels. |
| D6 | Policy rate | Riksbank SWEA `SECBREPOEFF` | daily | 1994-06-01 onwards | JSON | – | STIBOR 3M (`SEDP3MSTIBORDELAYC`) is **closed in SWEA, last observation 2020-07-03** (confirmed in the series list). Policy rate is the only rate variable. |
| D7 | Business tendency indicator | KI statistics database | – | – | – | – | Optional; not used in the model (not in both scenarios). |
| D8 | Baseline scenario | KI forecast database, `SenastePrognosen`, tables `F2108` (unemployment, quarterly, to 2027Q4), `F2107` (annual), `F0905` (GDP, quarterly SA levels), `F0604` (policy rate, monthly) | see `src/config.py` | updated 2026-09-28 | json-stat2 | – | The latest forecast in the database was updated 2026-09-28 (the September 2026 Konjunkturläget). The vintage is frozen at fetch time and documented in the manifest. KI's next forecast (December 2026) will only be adopted in a separate PR. |
| D8 (vintages) | Historical forecasts | KI `TidigarePrognoser` | same tables | 45 vintages from Dec 2015 to Jun 2026 | json-stat2 | – | **Vintages exist**, so the real-time backtest uses KI; the Riksbank forecast API (from 2020) is not needed. |
| D9 | Stress scenario | EBA/ESRB 2025 EU-wide stress test, macro-financial scenario, **corrigendum xlsx (updated 26 Feb 2025)** | Sweden: real GDP growth, unemployment rate, 3M rate; baseline and adverse 2025–2027 | annual | xlsx | – | The 2027 exercise's methodology was published 9 Nov 2026 but its **scenarios are released in January 2027**, so the 2025 scenario is used. Baseline = national central bank projections of December 2024. Values are parsed from the official file by `src/fetch/eba.py`, not typed by hand. |

## Validation anchor

Tillväxtanalys, *Konkurser och offentliga ackord 2023* (Statistik 2024:02), Table 1 (page 9 of 24):
"Andel av befintliga företag 2023, procent" by industry. The report says the denominator is
"all existing companies" in the industry but does not name the register or reference date.
The published counts and shares are stored in `data/reference/validation_anchor_2023.csv`
(checked against the PDF, which is also kept in the raw snapshot). Our 2023 bankruptcy
counts by sector match the report exactly, and our FDB-based rates reproduce all nine
published shares after rounding (see `docs/decisions.md`, amendment A1).

## SNI 2007 → SNI 2025

SNI 2025 replaced SNI 2007 on 8 December 2025. Tillväxtanalys' monthly tables still label
industry groups with SNI 2007 ranges, and the metadata does not say which standard the 2026
months are coded in. Commercial sources (UC) note that SNI 2025 may affect comparability in
2026. The pipeline therefore runs a level-jump test at 2026M01 per sector (see
`tests/test_data_quality.py`) and the result is recorded in `docs/decisions.md`.

## Licences

| Source | Licence / terms |
|---|---|
| Tillväxtanalys | Official statistics published as open data through the statistics portal; cite Tillväxtanalys as source. No explicit licence text was found on the portal, so re-use relies on the general principle that official statistics are free to use with attribution. |
| SCB | Open data, CC BY 4.0; cite SCB as source. |
| Riksbank SWEA | Free to use and re-use; optional API key via `RIKSBANK_API_KEY` (never committed). |
| Konjunkturinstitutet | Open data; KI must always be cited as source. |
| EBA/ESRB | Public documents; reproduced for non-commercial analysis with source citation. |

Raw snapshots are committed under `data/raw/` so that the project can be rebuilt even if a
source changes or an API version is retired.
