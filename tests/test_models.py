"""Model tests on synthetic data (all data in this file are synthetic)."""

import numpy as np
import pandas as pd
import pytest

from src import backtest
from src.models import baselines, satellite
from src.models.nb2 import fit_nb2, simulate_counts
from src.synthetic import TRUE_ALPHA, TRUE_BETA, synthetic_panel


@pytest.fixture(scope="module")
def synthetic():
    return synthetic_panel(lag=1)


def test_nb2_recovers_known_parameters():
    """synthetic: beta and alpha recovered within 4 robust standard errors.

    The tolerance comes from the estimator's own sampling distribution: under correct
    specification |beta_hat - beta| / se exceeds 4 with probability < 1e-4.
    """
    rng = np.random.default_rng(42)
    n = 2000
    X = pd.DataFrame({"const": 1.0, "x1": rng.normal(size=n), "x2": rng.normal(size=n)})
    offset = np.log(rng.uniform(1_000, 50_000, n))
    beta = np.array([-5.0, 0.3, -0.2])
    alpha = 0.05
    y = simulate_counts(np.exp(X.to_numpy() @ beta + offset), alpha, rng)
    res = fit_nb2(X, y, offset, clusters=np.arange(n) % 100)
    se = res.bse()
    assert res.converged
    for name, true in zip(X.columns, beta, strict=True):
        assert abs(res.params[name] - true) < 4 * se[name]
    assert abs(np.log(res.alpha) - np.log(alpha)) < 4 * se["log_alpha"]


def test_satellite_recovers_macro_slopes(synthetic):
    panel, macro = synthetic
    fitted = satellite.fit(panel, macro, satellite.Spec("A_k1", lag=1))
    se = fitted.result.bse()
    for v, true in TRUE_BETA.items():
        assert abs(fitted.result.params[v] - true) < 4 * se[v], v
    assert abs(np.log(fitted.result.alpha) - np.log(TRUE_ALPHA)) < 4 * se["log_alpha"]


def test_nb2_matches_statsmodels():
    sm = pytest.importorskip("statsmodels.discrete.discrete_model")
    rng = np.random.default_rng(7)
    n = 800
    X = pd.DataFrame({"const": 1.0, "x1": rng.normal(size=n), "x2": rng.uniform(size=n)})
    offset = np.log(rng.uniform(100, 5_000, n))
    y = simulate_counts(np.exp(X.to_numpy() @ np.array([-4.0, 0.2, 0.5]) + offset), 0.1, rng)
    ours = fit_nb2(X, y, offset)
    theirs = sm.NegativeBinomial(y, X, offset=offset, loglike_method="nb2").fit(
        disp=0, maxiter=500, method="bfgs"
    )
    np.testing.assert_allclose(ours.params[list(X.columns)], theirs.params[:3], atol=1e-4)
    np.testing.assert_allclose(ours.alpha, theirs.params.iloc[-1], rtol=1e-3)
    np.testing.assert_allclose(ours.loglik, theirs.llf, rtol=1e-8)


def test_forecasts_non_negative_and_intervals_ordered(synthetic):
    panel, macro = synthetic
    bt = backtest.run(
        panel,
        macro,
        [satellite.Spec("A_k1", lag=1), satellite.Spec("C_k1", lag=1, variant="C")],
        origin_list=[pd.Period("2018Q4", "Q")],
        include_baselines=False,
        n_sim=300,
    )
    assert (bt["forecast"] >= 0).all()
    assert (bt["p10"] >= 0).all()
    assert (bt["p10"] <= bt["p50"]).all() and (bt["p50"] <= bt["p90"]).all()


def test_backtest_never_uses_data_after_origin(synthetic):
    panel, macro = synthetic
    origin = pd.Period("2017Q4", "Q")
    poisoned = panel.copy()
    future = pd.PeriodIndex(poisoned["quarter"], freq="Q") > origin
    # Extreme future counts would change any estimate that leaked them in.
    poisoned.loc[future, "count"] = poisoned.loc[future, "count"] * 50
    specs = [satellite.Spec("A_k1", lag=1)]
    kwargs = {"origin_list": [origin], "include_baselines": True, "n_sim": 200}
    a = backtest.run(panel, macro, specs, **kwargs)
    b = backtest.run(poisoned, macro, specs, **kwargs)
    np.testing.assert_allclose(a["forecast"].to_numpy(), b["forecast"].to_numpy())


def test_seasonal_naive_uses_same_quarter_last_observed_year():
    hist = pd.Series(
        [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0],
        index=pd.period_range("2020Q1", periods=8, freq="Q"),
    )
    origin = pd.Period("2021Q4", "Q")
    assert baselines.seasonal_naive(hist, origin, origin + 1) == 5.0
    assert baselines.seasonal_naive(hist, origin, origin + 4) == 8.0
    assert baselines.seasonal_naive(hist, origin, origin + 8) == 8.0


def test_empirical_bayes_shrinks_towards_mean():
    b = np.array([0.0, 0.1, 0.5])
    v = np.array([0.01, 0.01, 0.2])
    shrunk, weight, _ = satellite.empirical_bayes_shrink(b, v)
    mean = np.sum(b / v) / np.sum(1 / v)
    assert np.all(np.abs(shrunk - mean) <= np.abs(b - mean) + 1e-12)
    assert weight[2] <= weight[0]  # the noisiest estimate is shrunk the most


def test_crps_of_point_mass_is_absolute_error():
    assert backtest.crps_sample(np.full(100, 2.0), 3.0) == pytest.approx(1.0)
