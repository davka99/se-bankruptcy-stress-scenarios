"""Unit tests for mapping, aggregation and rate computation on small hand-written frames."""

import pandas as pd
import pytest

from src import build_panel, jsonstat


def test_division_to_sector():
    assert build_panel.division_to_sector("01") == "AGR"
    assert build_panel.division_to_sector("39") == "MAN"
    assert build_panel.division_to_sector("43") == "CON"
    assert build_panel.division_to_sector("56") == "HOR"
    assert build_panel.division_to_sector("82") == "FRB"
    assert build_panel.division_to_sector("99") == "EHO"
    assert build_panel.division_to_sector("84") is None  # public administration
    assert build_panel.division_to_sector("00") == "UNS"
    assert build_panel.division_to_sector("A-U") is None
    assert build_panel.division_to_sector("011") is None


def _monthly(rows):
    df = pd.DataFrame(rows, columns=["sector", "month", "count"])
    df["is_preliminary"] = False
    return df


def test_quarterly_aggregation_sums_months_and_drops_incomplete_quarters():
    monthly = _monthly(
        [
            ("CON", "2023-01", 10),
            ("CON", "2023-02", 20),
            ("CON", "2023-03", 30),
            ("CON", "2023-04", 5),  # 2023Q2 incomplete
        ]
    )
    q = build_panel.aggregate_quarterly(monthly)
    assert q.to_dict("records") == [
        {"sector": "CON", "quarter": "2023Q1", "count": 60, "is_preliminary": False}
    ]


def test_rate_uses_previous_year_stock_and_is_annualised():
    q = pd.DataFrame({"sector": ["CON"], "quarter": ["2023Q1"], "count": [60]})
    fdb = pd.DataFrame({"sector": ["CON", "CON"], "year": [2022, 2023], "firms": [1000, 2000]})
    fek = pd.DataFrame({"sector": ["CON"], "year": [2022], "firms": [500]})
    out = build_panel.attach_denominators(q, fdb, fek)
    assert out.loc[0, "firms"] == 1000  # November 2022 stock for 2023 quarters
    assert out.loc[0, "rate"] == pytest.approx(4 * 60 / 1000)
    assert out.loc[0, "rate_fek"] == pytest.approx(4 * 60 / 500)


def test_denominator_join_does_not_fan_out():
    q = pd.DataFrame(
        {
            "sector": ["CON"] * 4,
            "quarter": ["2023Q1", "2023Q2", "2023Q3", "2023Q4"],
            "count": [1, 2, 3, 4],
        }
    )
    fdb = pd.DataFrame({"sector": ["CON"], "year": [2022], "firms": [100]})
    fek = pd.DataFrame(columns=["sector", "year", "firms"])
    out = build_panel.attach_denominators(q, fdb, fek)
    assert len(out) == len(q)
    # A duplicated stock row would multiply rows; the guard must catch it.
    dup = pd.concat([fdb, fdb])
    with pytest.raises(RuntimeError, match="fan-out"):
        build_panel.attach_denominators(q, dup, fek)


def test_rolling_four_quarter_rate():
    q = pd.DataFrame(
        {
            "sector": ["CON"] * 4,
            "quarter": ["2023Q1", "2023Q2", "2023Q3", "2023Q4"],
            "count": [10, 20, 30, 40],
        }
    )
    fdb = pd.DataFrame({"sector": ["CON"], "year": [2022], "firms": [1000]})
    out = build_panel.attach_denominators(q, fdb, pd.DataFrame(columns=["sector", "year", "firms"]))
    assert pd.isna(out.loc[2, "rate_r4"])
    assert out.loc[3, "rate_r4"] == pytest.approx(100 / 1000)


def test_jsonstat_row_major_order():
    ds = {
        "id": ["a", "b"],
        "size": [2, 3],
        "dimension": {
            "a": {"category": {"index": {"x": 0, "y": 1}}},
            "b": {"category": {"index": ["p", "q", "r"]}},
        },
        "value": [1, 2, 3, 4, 5, None],
    }
    df = jsonstat.to_frame(ds)
    assert df.loc[(df.a == "y") & (df.b == "p"), "value"].item() == 4
    assert pd.isna(df.loc[(df.a == "y") & (df.b == "r"), "value"].item())


def test_macro_quarterly_changes():
    months = pd.period_range("2007-01", "2009-12", freq="M")
    unemp = pd.Series(range(len(months)), index=months, dtype=float)
    gdp = pd.Series(100.0, index=pd.period_range("2007Q1", "2009Q4", freq="Q"))
    gdp.iloc[-1] = 110.0
    days = pd.date_range("2007-01-01", "2009-12-31", freq="D")
    policy = pd.Series(1.0, index=days)
    m = build_panel.macro_quarterly(unemp, gdp, policy)
    assert m.loc["2008Q1", "d_unemp"] == pytest.approx(12.0)  # monthly +1 => +12 pp per year
    assert m.loc["2009Q4", "gdp_yoy"] == pytest.approx(10.0)
    assert m.loc["2009Q4", "d_policy"] == pytest.approx(0.0)
