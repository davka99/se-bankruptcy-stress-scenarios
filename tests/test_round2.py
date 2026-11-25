"""Round-2 tests (decisions A10). All data in this file are synthetic."""

import numpy as np
import pandas as pd
import pytest

from src import config, round2
from src.models import satellite
from src.synthetic import synthetic_panel


@pytest.fixture(scope="module")
def synthetic():
    return synthetic_panel(lag=0)


def test_add_derived_shifts_policy_by_k_quarters():
    q = pd.period_range("2020Q1", "2021Q4", freq="Q").astype(str)
    m = pd.DataFrame({"d_policy": np.arange(8.0)}, index=q)
    out = satellite.add_derived(m, ("d_unemp", "d_policy_l4"))
    assert np.isnan(out.loc["2020Q4", "d_policy_l4"])
    assert out.loc["2021Q1", "d_policy_l4"] == m.loc["2020Q1", "d_policy"]
    assert out.loc["2021Q4", "d_policy_l4"] == m.loc["2020Q4", "d_policy"]
    assert "d_policy_l4" not in m.columns  # input is not modified


def test_intercept_correction_recovers_a_level_shift(synthetic):
    """synthetic: one sector's last four quarters are doubled; its c_s is about log 2."""
    panel, macro = synthetic
    p = panel.copy()
    last4 = sorted(p["quarter"].unique())[-4:]
    hit = (p["sector"] == "CON") & p["quarter"].isin(last4)
    p.loc[hit, "count"] = p.loc[hit, "count"] * 2
    spec = satellite.Spec("U0+IC1", lag=0, macro=("d_unemp",), ic_rho=1.0)
    fitted = satellite.fit(p, macro, spec)
    assert fitted.ic_origin == pd.Period(last4[-1], "Q")
    assert fitted.ic["CON"] == pytest.approx(np.log(2), abs=0.2)
    others = fitted.ic.drop("CON")
    assert others.abs().max() < 0.25


def test_ic_offset_fades_with_rho():
    spec = satellite.Spec("x", lag=0, macro=("d_unemp",), ic_rho=0.5)
    f = satellite.FittedSatellite(
        spec, result=None, ic=pd.Series({"CON": 1.0}), ic_origin=pd.Period("2026Q3", "Q")
    )
    rows = pd.DataFrame(
        {"sector": ["CON", "CON", "AGR"], "quarter": ["2026Q4", "2027Q2", "2026Q4"]}
    )
    assert f.ic_offset(rows) == pytest.approx([0.5, 0.125, 0.0])
    plain = satellite.FittedSatellite(satellite.Spec("y"), result=None)
    assert plain.ic_offset(rows) == pytest.approx([0.0, 0.0, 0.0])


def test_backtest_with_ic_never_uses_target_data(synthetic):
    """The correction is computed from training data only: changing the targets after the
    origin must not change the forecasts."""
    from src import backtest

    panel, macro = synthetic
    spec = satellite.Spec("U0+IC1", lag=0, macro=("d_unemp",), ic_rho=1.0)
    origin = pd.Period("2016Q4", "Q")
    a = backtest.run(panel, macro, [spec], origin_list=[origin], include_baselines=False, n_sim=50)
    p2 = panel.copy()
    future = pd.PeriodIndex(p2["quarter"], freq="Q") > origin
    p2.loc[future, "count"] = p2.loc[future, "count"] * 3
    b = backtest.run(p2, macro, [spec], origin_list=[origin], include_baselines=False, n_sim=50)
    assert np.allclose(a["forecast"], b["forecast"])


def test_conformal_bands_and_coverage():
    rng = np.random.default_rng(0)
    n = 4000
    f = np.full(n, 0.01)
    rate = f * np.exp(rng.normal(0, 0.2, n))
    d = pd.DataFrame(
        {"model": "m", "h": np.repeat([1, 4], n // 2), "rate": rate, "forecast": f, "covered": 0.0}
    )
    bands = round2.conformal_bands(d, "m")
    assert bands.loc[4, "log_q10"] == pytest.approx(-0.2 * 1.2816, abs=0.03)
    cov = round2.conformal_coverage(d, "m", bands)
    assert cov["coverage_conformal"].to_numpy() == pytest.approx([0.8, 0.8], abs=0.01)


def test_watchlist_additional_flags_by_additional_rate():
    sectors = config.MODEL_SECTORS
    quarters = pd.period_range("2026Q4", "2028Q3", freq="Q").astype(str)
    rows = pd.DataFrame(
        [{"sector": s, "quarter": q, "firms": 1000.0} for s in sectors for q in quarters]
    )
    n = 200
    base = np.full((n, len(rows)), 0.01)
    adv = base.copy()
    con = (rows["sector"] == "CON").to_numpy()
    adv[:, con] += 0.02  # only construction rises
    adv[:, ~con] += 0.001
    w = round2.watchlist_additional(rows, {"baseline": base, "adverse": adv})
    flagged = w.loc[w["watchlist"], "sector"].tolist()
    assert flagged == ["CON"]
    assert w["share_of_extra"].sum() == pytest.approx(1.0)


def test_total_rate_is_four_quarter_sum_over_firms():
    quarters = pd.period_range("2026Q4", "2027Q4", freq="Q").astype(str)
    rows = pd.DataFrame(
        [{"sector": s, "quarter": q, "firms": 100.0} for s in ("A", "B") for q in quarters]
    )
    rates = np.full((10, len(rows)), 0.04)  # annualised 4 % -> 1 per quarter per 100 firms
    t = round2.total_rate(rows, rates)
    assert list(t["quarter"]) == ["2027Q3", "2027Q4"]
    assert t["p50"].to_numpy() == pytest.approx([0.04, 0.04])
