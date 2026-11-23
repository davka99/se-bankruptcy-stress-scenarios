"""Central configuration: seed, paths, sources, sector map and pre-registered settings.

Every table ID and URL used by the project lives here so that a reviewer can audit
the data lineage in one place.
"""

from __future__ import annotations

from pathlib import Path

SEED = 42

# --------------------------------------------------------------------------------------
# Paths
# --------------------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
RAW = DATA / "raw"
REFERENCE = DATA / "reference"
PROCESSED = DATA / "processed"
FIXTURES = DATA / "fixtures"
REPORTS = ROOT / "reports"
FIGURES = REPORTS / "figures"
TABLES = REPORTS / "tables"
DOCS = ROOT / "docs"

# --------------------------------------------------------------------------------------
# HTTP
# --------------------------------------------------------------------------------------
HTTP_TIMEOUT = 60  # seconds
HTTP_RETRIES = 4
HTTP_BACKOFF = 2.0  # seconds, doubled per retry
USER_AGENT = "se-bankruptcy-stress-scenarios (github.com/davka99)"
RIKSBANK_KEY_ENV = "RIKSBANK_API_KEY"  # optional, read from the environment only

# --------------------------------------------------------------------------------------
# Sources (verified 2026-11-23, see docs/data_sources.md)
# --------------------------------------------------------------------------------------
# D1: Tillväxtanalys statistics portal, PxWeb API v1 (POST with a JSON query).
TVA_API = (
    "https://statistik.tillvaxtanalys.se/PxWeb/api/v1/sv/"
    "Tillväxtanalys statistikdatabas/Konkurser och offentliga ackord/"
)
TVA_TABLES = {
    # monthly bankruptcies by industry, 2009M01 onwards, one table (no SCB splice needed)
    "monthly_by_sector": "12_konkurser_manad_tot_bransch.px",
    # monthly bankruptcies by county (independent total for the sum check)
    "monthly_by_county": "11_konkurser_manad_lan.px",
    # monthly by industry x region x legal form x size class (legal-form split)
    "monthly_detail": "14_konkurser_manad_kom_bransch_juridisk_form_storleksklass_popAH.px",
}
# Validation anchor: Tillväxtanalys, Statistik 2024:02, Table 1, p. 10
TVA_ANCHOR_REPORT_URL = (
    "https://tillvaxtanalys.se/download/18.3469032218e5fb1783c189dc/1715931573755/"
    "Statistik_2024_02%20Konkurser%20och%20offentliga%20ackord%202023.pdf"
)

# D3-D5: SCB PxWebApi v2 (GET). v1 is switched off at the turn of 2026/2027.
SCB_API = "https://statistikdatabasen.scb.se/api/v2"
SCB_TABLES = {
    # D3 FDB: enterprises by SNI 2007 and size class, annual, reference month November
    "fdb_firms": "TAB5166",
    # D3b FEK: enterprises (active) by SNI 2007, two vintages with a break in 2022
    "fek_firms_2000_2021": "TAB600",
    "fek_firms_2022_": "TAB6017",
    # D4 AKU: monthly labour-force status, 15-74, incl. seasonally adjusted series
    "aku_monthly": "TAB6387",
    # D5 GDP, expenditure side, seasonally and calendar adjusted, fixed prices
    "gdp_sa": "TAB4553",
}
SCB_SELECTIONS = {
    "aku_monthly": {
        "Arbetskraftstillh": ["ALÖSP"],  # unemployment rate, percent
        "TypData": ["SR_DATA"],  # seasonally adjusted
        "Kon": ["1+2"],
        "Alder": ["tot15-74"],
        "ContentsCode": ["*"],
        "Tid": ["*"],
    },
    "gdp_sa": {
        "Anvandningstyp": ["BNPM"],  # GDP at market prices
        "ContentsCode": ["NR0103CE"],  # SA, fixed prices reference year 2025, SEK m
        "Tid": ["*"],
    },
}

# D6: Riksbank SWEA API
RIKSBANK_API = "https://api.riksbank.se/swea/v1"
RIKSBANK_SERIES = {
    "policy_rate": "SECBREPOEFF",
    # STIBOR 3M in SWEA is closed (last observation 2020-07-03); kept for documentation only
    "stibor_3m_closed": "SEDP3MSTIBORDELAYC",
}

# D7/D8: Konjunkturinstitutet (NIER) forecast database, PxWeb API v1
KI_API = "https://prognos.konj.se/PxWeb/api/v1/sv"
KI_LATEST_DB = "SenastePrognosen"
KI_VINTAGE_DB = "TidigarePrognoser"
KI_TABLES = {
    "unemployment_q": ("f21_arbetsmarknad", "F2108.px", "F2108Arali1574"),
    "unemployment_a": ("f21_arbetsmarknad", "F2107.px", None),
    "gdp_q": ("f09_bnpkonsumtioninvesteringarochutrikeshandel", "F0905.px", "F0905Nbnpmpfs"),
    "gdp_a": ("f09_bnpkonsumtioninvesteringarochutrikeshandel", "F0901.px", None),
    "policy_rate_m": ("f06_rantorochvaxelkurser", "F0604.px", "F0604Repo"),
}

# D9: EBA 2025 EU-wide stress test, macro-financial scenario (corrigendum, 26 Feb 2025)
EBA_SCENARIO_XLSX = (
    "https://www.eba.europa.eu/sites/default/files/2025-03/"
    "d0668400-aed7-40d7-b668-1f77eb24b934/"
    "2025%20EU-wide%20stress%20test%20-%20Macro%20financial%20scenario%20"
    "%28updated%2026%20February%202025%29-incl%20disclaimer%20for%20EBA%20%285%29.xlsx"
)
EBA_VINTAGE = "EBA 2025 EU-wide stress test, macro-financial scenario, corrigendum 2025-02-26"

# --------------------------------------------------------------------------------------
# Sector groups (built from the source's own group codes; see data/reference/sector_map.csv)
# --------------------------------------------------------------------------------------
SECTORS = {
    "AGR": "Agriculture, forestry and fishing (SNI 01-03)",
    "MAN": "Manufacturing, mining and utilities (SNI 05-39)",
    "CON": "Construction (SNI 41-43)",
    "TRD": "Wholesale and retail trade (SNI 45-47)",
    "TRN": "Transport and storage (SNI 49-53)",
    "HOR": "Hotels and restaurants (SNI 55-56)",
    "ICT": "Information and communication (SNI 58-63)",
    "FRB": "Finance, real estate and business services (SNI 64-82)",
    "EHO": "Education, health and other services (SNI 85-99)",
    "UNS": "Unspecified industry",
}
MODEL_SECTORS = [s for s in SECTORS if s != "UNS"]

# Tillväxtanalys bankruptcy group code -> sector
TVA_CODE_TO_SECTOR = {
    "01-03": "AGR",
    "05-39": "MAN",
    "41-43": "CON",
    "45": "TRD",
    "46": "TRD",
    "47": "TRD",
    "49-53": "TRN",
    "55": "HOR",
    "56": "HOR",
    "58-63": "ICT",
    "64-82": "FRB",
    "85-99": "EHO",
    "bransch_ospecificerad": "UNS",
}

# SNI 2007 division (2 digits) ranges -> sector, for the FDB/FEK denominators.
# Division 84 (public administration) has no bankruptcy group and is excluded.
DIVISION_RANGES = [
    (1, 3, "AGR"),
    (5, 39, "MAN"),
    (41, 43, "CON"),
    (45, 47, "TRD"),
    (49, 53, "TRN"),
    (55, 56, "HOR"),
    (58, 63, "ICT"),
    (64, 82, "FRB"),
    (85, 99, "EHO"),
]

# --------------------------------------------------------------------------------------
# Pre-registered settings (see docs/decisions.md, tag `prereg`)
# --------------------------------------------------------------------------------------
COVID_SUPPORT = ("2020Q2", "2021Q4")
COVID_SUPPORT_SENSITIVITY = ("2020Q2", "2022Q1")
LAG_GRID = [0, 1, 2, 3, 4]
MACRO_VARS = ["d_unemp", "gdp_yoy", "d_policy"]
EXPECTED_SIGNS = {"d_unemp": 1, "gdp_yoy": -1, "d_policy": 1}
FIRST_ORIGIN = "2014Q4"
MIN_TRAIN_QUARTERS = 16
SELECTION_END = "2022Q4"  # model selection uses targets up to and including this quarter
TEST_START = "2023Q1"  # untouched test period
HORIZONS = [1, 4, 8]
SELECTION_HORIZON = 4
SCENARIO_HORIZON = 12
N_SIM = 5000
INTERVAL = (0.10, 0.90)  # 80 % interval
WATCHLIST_MULTIPLIER = 1.25
SCENARIO_WEIGHTS = {"baseline": 0.7, "adverse": 0.3}  # labelled assumption
LGD = 0.45  # labelled assumption
N_LOANS = 5000  # synthetic portfolio size
