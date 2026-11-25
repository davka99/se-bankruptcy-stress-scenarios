"""Data-quality tests on the committed raw snapshots and the processed panels.

The most important test is `test_sectors_sum_to_independent_total`: the industry table and
the county table are separate tables from the source, so if they agree month by month the
industry mapping, the parsing and the aggregation are all very unlikely to be wrong.
"""

import json

import numpy as np
import pandas as pd
import pytest

from src import build_panel, config, jsonstat
from src.fetch.common import latest_snapshot

pytestmark = pytest.mark.skipif(
    not (config.PROCESSED / "panel_quarterly.csv").exists(),
    reason="processed panels not built",
)

ANCHOR_TOLERANCE_PP = 0.15  # published shares are rounded to 0.1 pp; 0.1 pp for definitions
LEVEL_JUMP_QUANTILE = 0.99


@pytest.fixture(scope="module")
def monthly():
    return build_panel.load("panel_monthly")


@pytest.fixture(scope="module")
def quarterly():
    return build_panel.load("panel_quarterly")


@pytest.fixture(scope="module")
def macro():
    return build_panel.load("macro_quarterly").set_index("quarter")


def test_no_missing_months(monthly):
    months = pd.period_range(monthly["month"].min(), monthly["month"].max(), freq="M").astype(str)
    for sector, grp in monthly.groupby("sector"):
        assert list(grp["month"]) == list(months), sector


def test_no_duplicate_sector_months(monthly, quarterly):
    assert not monthly.duplicated(["sector", "month"]).any()
    assert not quarterly.duplicated(["sector", "quarter"]).any()


def test_sectors_sum_to_independent_total(monthly):
    totals = build_panel.load("county_total").set_index("month")["county_total"]
    sector_sum = monthly.groupby("month")["count"].sum()
    diff = sector_sum - totals.reindex(sector_sum.index)
    assert diff.abs().max() == 0, diff[diff != 0]


def test_rates_and_firms_in_range(quarterly):
    q = quarterly[quarterly["sector"].isin(config.MODEL_SECTORS)]
    assert (q["firms"] > 0).all()
    assert ((q["rate"] >= 0) & (q["rate"] < 0.1)).all()
    assert (q["count"] >= 0).all()


def test_macro_complete_over_model_period(macro, quarterly):
    first, last = quarterly["quarter"].min(), quarterly["quarter"].max()
    lag_start = str(pd.Period(first, "Q") - max(config.LAG_GRID))
    window = macro.loc[lag_start:last, ["d_unemp", "gdp_yoy", "d_policy"]]
    expected = pd.period_range(lag_start, last, freq="Q").astype(str)
    assert list(window.index) == list(expected)  # quarterly frequency, no gaps
    # GDP is published about two months after the quarter; it may lag the bankruptcies by
    # at most one quarter (that quarter then uses lagged GDP or the KI nowcast).
    assert not window.iloc[:-1].isna().any().any()
    assert not window.iloc[-1][["d_unemp", "d_policy"]].isna().any()


def level_jumps(monthly: pd.DataFrame, break_month: str) -> pd.DataFrame:
    """Flag sectors whose y/y change in the 3 months from a break month is extreme.

    Threshold: the 99th percentile of absolute y/y log changes of rolling 3-month sums
    in the same sector, pandemic months excluded.
    """
    rows = []
    for sector, grp in monthly.groupby("sector"):
        s = grp.set_index("month")["count"].astype(float).rolling(3).sum()
        yoy = np.log(s / s.shift(12)).dropna()
        idx = pd.PeriodIndex(yoy.index, freq="M")
        hist = yoy[(idx < pd.Period(break_month, "M")) & ~((idx >= "2020-03") & (idx <= "2022-03"))]
        end = str(pd.Period(break_month, "M") + 2)
        if end not in yoy.index:
            continue
        threshold = hist.abs().quantile(LEVEL_JUMP_QUANTILE)
        rows.append(
            {
                "sector": sector,
                "break_month": break_month,
                "yoy_log_change": yoy[end],
                "threshold": threshold,
                "flag": abs(yoy[end]) > threshold,
            }
        )
    return pd.DataFrame(rows)


def test_level_jump_at_sni2025_switch_is_documented(monthly):
    """A flagged jump at 2026M01 must be listed in data/reference/documented_breaks.csv."""
    jumps = level_jumps(monthly, "2026-01")
    flagged = set(jumps.loc[jumps["flag"], "sector"])
    documented_path = config.REFERENCE / "documented_breaks.csv"
    documented = set()
    if documented_path.exists():
        documented = set(pd.read_csv(documented_path)["sector"])
    assert flagged <= documented, f"Undocumented level jumps at 2026M01: {flagged - documented}"


def test_validation_anchor_2023(quarterly):
    """Our 2023 annual rate (count 2023 / FDB Nov 2022) vs Tillväxtanalys' published shares."""
    anchor = pd.read_csv(config.REFERENCE / "validation_anchor_2023.csv").set_index("sector")
    q = quarterly[quarterly["quarter"].str.startswith("2023")]
    ours = 100 * q.groupby("sector")["count"].sum() / q.groupby("sector")["firms"].first()
    # bankruptcy counts must match the report exactly
    counts = q.groupby("sector")["count"].sum()
    for s in config.MODEL_SECTORS:
        assert counts[s] == anchor.loc[s, "bankruptcies_2023"], s
    deviation = (
        ours[config.MODEL_SECTORS] - anchor.loc[config.MODEL_SECTORS, "share_of_existing_firms_pct"]
    ).abs()
    assert (deviation <= ANCHOR_TOLERANCE_PP).all(), deviation.round(3).to_dict()


def test_raw_bankruptcy_schema():
    folder = latest_snapshot("tillvaxtanalys")
    ds = jsonstat.load(folder / "monthly_by_sector.json")
    assert ds["id"] == ["Tid", "Bransch", "variabel"]
    codes = set(jsonstat.category_codes(ds["dimension"]["Bransch"]))
    assert codes == set(config.TVA_CODE_TO_SECTOR)
    df = jsonstat.to_frame(ds)
    assert df["Tid"].str.fullmatch(r"\d{4}M\d{2}").all()
    assert (df["value"].dropna() >= 0).all() and df["value"].notna().all()


def test_raw_manifests_have_checksums():
    for source in ("tillvaxtanalys", "scb", "riksbank", "ki", "eba"):
        folder = latest_snapshot(source)
        manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
        for entry in manifest["files"]:
            path = folder / entry["file"]
            assert path.exists(), path
            assert len(entry["sha256"]) == 64


def test_raw_macro_schema():
    scb = latest_snapshot("scb")
    for name, dims in {
        "aku_monthly.json": {"Tid"},
        "gdp_sa.json": {"Tid"},
        "fdb_firms.json": {"Tid"},
    }.items():
        ds = jsonstat.load(scb / name)
        assert dims <= set(ds["id"]), name
    obs = json.loads((latest_snapshot("riksbank") / "policy_rate.json").read_bytes())
    assert {"date", "value"} <= set(obs[0])
