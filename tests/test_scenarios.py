"""Scenario construction tests (synthetic inputs)."""

import numpy as np
import pandas as pd

from src import scenarios


def _levels():
    q = pd.period_range("2022Q1", "2029Q3", freq="Q")
    rng = np.random.default_rng(42)
    return pd.DataFrame(
        {
            "unemp": 8 + rng.normal(0, 0.2, len(q)),
            "gdp_level": 100 * np.cumprod(1 + rng.normal(0.005, 0.002, len(q))),
            "policy_rate": 2 + rng.normal(0, 0.1, len(q)),
        },
        index=q,
    )


def _eba(adverse_equals_baseline: bool) -> pd.DataFrame:
    rows = []
    for year, g, u, r in [(2025, 2.0, 8.4, 2.1), (2026, 2.3, 8.0, 2.0), (2027, 1.8, 7.6, 2.0)]:
        rows += [
            {"scenario": "baseline", "year": year, "variable": "gdp_growth", "value": g},
            {"scenario": "baseline", "year": year, "variable": "unemp", "value": u},
            {"scenario": "baseline", "year": year, "variable": "rate_3m", "value": r},
        ]
        shock = 0 if adverse_equals_baseline else 1
        rows += [
            {"scenario": "adverse", "year": year, "variable": "gdp_growth", "value": g - 5 * shock},
            {"scenario": "adverse", "year": year, "variable": "unemp", "value": u + 4 * shock},
            {"scenario": "adverse", "year": year, "variable": "rate_3m", "value": r + shock},
        ]
    return pd.DataFrame(rows)


def test_zero_deviation_gives_identical_paths():
    base = _levels()
    start = pd.Period("2026Q3", "Q")
    dev = scenarios.eba_deviations(_eba(adverse_equals_baseline=True))
    adv = scenarios.adverse_path(base, dev, start)
    pd.testing.assert_frame_equal(adv, base)


def test_deviation_applies_only_after_start_and_reaches_annual_values():
    base = _levels()
    start = pd.Period("2026Q3", "Q")
    dev = scenarios.eba_deviations(_eba(adverse_equals_baseline=False))
    adv = scenarios.adverse_path(base, dev, start)
    before = adv.index <= start
    pd.testing.assert_frame_equal(adv[before], base[before])
    diff = (adv["unemp"] - base["unemp"])[~before].to_numpy()
    assert np.all(diff >= 0)
    assert diff.max() <= 4 + 1e-9  # never above the largest annual deviation
    np.testing.assert_allclose(
        scenarios.quarterly_deviation(np.array([1.0, 2.0, 3.0]), 12)[[1, 9]], [0.8, 2.875]
    )


def test_interpolate_annual_hits_mid_year_values():
    annual = pd.Series([7.0, 6.0], index=[2028, 2029])
    quarters = pd.period_range("2028Q1", "2029Q4", freq="Q")
    out = scenarios.interpolate_annual(annual, quarters, (pd.Period("2027Q4", "Q"), 8.0))
    assert out.mean() < 8 and out.iloc[-1] == 6.0
