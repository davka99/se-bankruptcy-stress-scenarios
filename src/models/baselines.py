"""Baseline forecasts the satellite model must beat.

1. Seasonal naive: the rate in the same quarter of the last observed year.
2. ETS: additive Holt-Winters with damped trend on log(rate), per sector (ETS(A,Ad,A)).
3. No-macro NB2: the satellite model without macro terms (see `satellite.Spec(variant="NOMACRO")`).
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import optimize

SEASON = 4


def seasonal_naive(history: pd.Series, origin: pd.Period, target: pd.Period) -> float:
    """history: rate indexed by quarterly Period. Same quarter, last year observed at origin."""
    steps_back = ((target - origin).n - 1) // SEASON + 1
    source = target - SEASON * steps_back
    return float(history.get(source, np.nan))


def _hw_filter(y: np.ndarray, params: np.ndarray) -> tuple[np.ndarray, tuple]:
    alpha, beta, gamma, phi = params
    m = SEASON
    level = y[:m].mean()
    trend = (y[m : 2 * m].mean() - y[:m].mean()) / m if len(y) >= 2 * m else 0.0
    season = list(y[:m] - level)
    errors = np.zeros(len(y))
    for t in range(len(y)):
        s = season[t]
        fitted = level + phi * trend + s
        errors[t] = y[t] - fitted
        new_level = alpha * (y[t] - s) + (1 - alpha) * (level + phi * trend)
        trend = beta * (new_level - level) + (1 - beta) * phi * trend
        season.append(gamma * (y[t] - new_level) + (1 - gamma) * s)
        level = new_level
    return errors, (level, trend, season, len(y))


def fit_ets(y: np.ndarray) -> np.ndarray:
    """Smoothing parameters (alpha, beta, gamma, phi) by least squares on one-step errors."""
    y = np.asarray(y, dtype=float)

    def sse(p: np.ndarray) -> float:
        e, _ = _hw_filter(y, p)
        return float(np.sum(e[SEASON:] ** 2))

    bounds = [(0.01, 0.99), (0.001, 0.5), (0.001, 0.99), (0.8, 0.98)]
    x0 = np.array([0.3, 0.05, 0.1, 0.9])
    res = optimize.minimize(sse, x0, bounds=bounds, method="L-BFGS-B")
    return res.x


def ets_forecast(y: np.ndarray, horizons: list[int]) -> dict[int, float]:
    """Point forecasts of y (here: log rate) at the given horizons."""
    params = fit_ets(y)
    _, (level, trend, season, n) = _hw_filter(np.asarray(y, dtype=float), params)
    phi = params[3]
    out = {}
    for h in horizons:
        damp = sum(phi**i for i in range(1, h + 1))
        s = season[n + (h - 1) % SEASON]  # latest estimate for that season position
        out[h] = level + damp * trend + s
    return out
