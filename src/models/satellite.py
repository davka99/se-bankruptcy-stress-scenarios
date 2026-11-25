"""Satellite model: NB2 count model of bankruptcies by sector and quarter with a firm offset.

    log mu_{s,q} = log(firms_{s,y-1}) + eta_s + delta_quarter(q) + tau * t
                   + beta' macro_{q-k} + gamma * covid_support_q

Variants (pre-registered, see docs/decisions.md):
    A        common slopes, common lag k
    B        sector-specific slope on d_unemp, other slopes common
    C        B with sector slopes shrunk towards their precision-weighted mean (empirical Bayes)
    NOMACRO  baseline 3: same model without macro terms

Round 2 (decisions A10) adds an optional intercept correction: at the end of the training
data, c_s = log(sum count / sum mu) over each industry's last four quarters, and forecasts
h quarters ahead are multiplied by exp(c_s * rho**h) (`Spec.ic_rho`).
"""

from __future__ import annotations

from dataclasses import dataclass, replace

import numpy as np
import pandas as pd

from src import config
from src.models.nb2 import NB2Result, fit_nb2, simulate_counts

SHRINK_VAR = "d_unemp"
IC_WINDOW = 4  # quarters used for the intercept correction (A10)
POLICY_LAG_SUFFIX = "d_policy_l"  # derived regressor: d_policy k quarters earlier


@dataclass(frozen=True)
class Spec:
    name: str
    lag: int = 1
    variant: str = "A"  # "A", "B", "C" or "NOMACRO"
    trend: bool = True
    covid: tuple[str, str] | None = config.COVID_SUPPORT
    macro: tuple[str, ...] = tuple(config.MACRO_VARS)
    exclude_covid_quarters: bool = False
    ic_rho: float | None = None  # A10 intercept correction; None = off

    @property
    def uses_macro(self) -> bool:
        return self.variant != "NOMACRO" and len(self.macro) > 0


def spec_grid(best_lag: int | None = None) -> list[Spec]:
    """The pre-registered grid: 5 lags for A; with the best lag also B, C and A without trend."""
    grid = [Spec(f"A_k{k}", lag=k) for k in config.LAG_GRID]
    if best_lag is not None:
        grid += [
            Spec(f"B_k{best_lag}", lag=best_lag, variant="B"),
            Spec(f"C_k{best_lag}", lag=best_lag, variant="C"),
            Spec(f"A_k{best_lag}_notrend", lag=best_lag, trend=False),
        ]
    return grid


def quarter_index(quarters: pd.Series) -> np.ndarray:
    """Years since 2009Q1 as a float (used for the trend)."""
    p = pd.PeriodIndex(quarters.astype(str), freq="Q")
    return ((p.year - 2009) * 4 + (p.quarter - 1)).to_numpy() / 4.0


def covid_flag(quarters: pd.Series, window: tuple[str, str] | None) -> np.ndarray:
    if window is None:
        return np.zeros(len(quarters))
    p = pd.PeriodIndex(quarters.astype(str), freq="Q")
    lo, hi = pd.Period(window[0], "Q"), pd.Period(window[1], "Q")
    return ((p >= lo) & (p <= hi)).astype(float)


def add_derived(macro: pd.DataFrame, variables: tuple[str, ...]) -> pd.DataFrame:
    """Add derived regressors named `d_policy_l<k>` (d_policy k quarters earlier)."""
    m = macro
    for v in variables:
        if v.startswith(POLICY_LAG_SUFFIX) and v not in m.columns:
            k = int(v[len(POLICY_LAG_SUFFIX) :])
            m = m.copy()
            idx = pd.PeriodIndex(m.index.astype(str), freq="Q")
            lagged = pd.Series(m["d_policy"].to_numpy(), index=idx + k)
            m[v] = lagged.reindex(idx).to_numpy()
    return m


def lagged_macro(macro: pd.DataFrame, lag: int, variables: tuple[str, ...]) -> pd.DataFrame:
    """Macro values at q - lag, indexed by target quarter q (string 'YYYYQn')."""
    m = add_derived(macro, variables).copy()
    m.index = pd.PeriodIndex(m.index.astype(str), freq="Q")
    shifted = m[list(variables)].copy()
    shifted.index = shifted.index + lag
    shifted.index = shifted.index.astype(str)
    return shifted


def design(panel: pd.DataFrame, macro: pd.DataFrame, spec: Spec) -> pd.DataFrame:
    """Design matrix (one row per panel row). Panel needs sector, quarter."""
    sectors = config.MODEL_SECTORS
    q = panel["quarter"].astype(str)
    X = pd.DataFrame(index=panel.index)
    for s in sectors:
        X[f"eta_{s}"] = (panel["sector"] == s).astype(float)
    qn = pd.PeriodIndex(q, freq="Q").quarter
    for k in (2, 3, 4):
        X[f"q{k}"] = (qn == k).astype(float)
    if spec.trend:
        X["trend"] = quarter_index(q)
    if spec.covid is not None and not spec.exclude_covid_quarters:
        X["covid_support"] = covid_flag(q, spec.covid)
    if spec.uses_macro:
        lagged = lagged_macro(macro, spec.lag, spec.macro).reindex(q.to_numpy())
        for v in spec.macro:
            values = lagged[v].to_numpy()
            if spec.variant in ("B", "C") and v == SHRINK_VAR:
                for s in sectors:
                    X[f"{v}_x_{s}"] = values * (panel["sector"] == s).to_numpy()
            else:
                X[v] = values
    return X


@dataclass
class FittedSatellite:
    spec: Spec
    result: NB2Result
    shrunk: pd.Series | None = None  # variant C: shrunk sector slopes on SHRINK_VAR
    shrink_weights: pd.Series | None = None
    shrink_post_sd: pd.Series | None = None
    ic: pd.Series | None = None  # A10 intercept correction per sector
    ic_origin: pd.Period | None = None  # last training quarter

    def ic_offset(self, rows: pd.DataFrame) -> np.ndarray:
        """c_s * rho**h for each row (sector, quarter); zeros without a correction."""
        if self.ic is None or self.spec.ic_rho is None:
            return np.zeros(len(rows))
        h = (pd.PeriodIndex(rows["quarter"].astype(str), freq="Q") - self.ic_origin).map(
            lambda d: d.n
        )
        c = rows["sector"].map(self.ic).fillna(0.0).to_numpy()
        return c * self.spec.ic_rho ** np.asarray(h, dtype=float)

    def _offset_extra(self, X: pd.DataFrame) -> np.ndarray:
        if self.shrunk is None:
            return np.zeros(len(X))
        cols = [f"{SHRINK_VAR}_x_{s}" for s in self.shrunk.index]
        return X[cols].to_numpy() @ self.shrunk.to_numpy()

    def mu(self, X: pd.DataFrame, offset: np.ndarray) -> np.ndarray:
        return self.result.predict_mu(X, offset + self._offset_extra(X))

    def simulate(
        self, X: pd.DataFrame, offset: np.ndarray, n: int, rng: np.random.Generator
    ) -> np.ndarray:
        """(n, rows) simulated counts with parameter uncertainty and NB noise."""
        betas, alphas = self.result.draw_params(n, rng)
        Xa = X[self.result.exog_names].to_numpy()
        eta = betas @ Xa.T + offset[None, :]
        if self.shrunk is not None:
            cols = [f"{SHRINK_VAR}_x_{s}" for s in self.shrunk.index]
            slope_draws = rng.normal(
                self.shrunk.to_numpy(), self.shrink_post_sd.to_numpy(), size=(n, len(cols))
            )
            eta = eta + slope_draws @ X[cols].to_numpy().T
        mu = np.exp(np.clip(eta, -30, 30))
        return simulate_counts(mu, alphas[:, None], rng)


def fit(panel: pd.DataFrame, macro: pd.DataFrame, spec: Spec) -> FittedSatellite:
    fitted = _fit(panel, macro, spec)
    if spec.ic_rho is not None:
        fitted.ic, fitted.ic_origin = intercept_correction(fitted, panel, macro)
    return fitted


def intercept_correction(
    fitted: FittedSatellite, train: pd.DataFrame, macro: pd.DataFrame
) -> tuple[pd.Series, pd.Period]:
    """c_s = log(sum count / sum mu) over each industry's last IC_WINDOW training quarters
    (in-sample fit of the model estimated on `train`)."""
    qp = pd.PeriodIndex(train["quarter"].astype(str), freq="Q")
    last = qp.max()
    recent = train[(qp > last - IC_WINDOW) & (qp <= last)]
    X = design(recent, macro, fitted.spec)
    ok = X.notna().all(axis=1).to_numpy()
    recent, X = recent[ok], X[ok]
    mu = fitted.mu(X, np.log(recent["firms"].to_numpy(dtype=float)))
    g = (
        pd.DataFrame(
            {"sector": recent["sector"].to_numpy(), "y": recent["count"].to_numpy(), "mu": mu}
        )
        .groupby("sector")[["y", "mu"]]
        .sum()
    )
    return np.log(np.maximum(g["y"], 0.5) / g["mu"]), last


def _fit(panel: pd.DataFrame, macro: pd.DataFrame, spec: Spec) -> FittedSatellite:
    data = panel
    if spec.exclude_covid_quarters and spec.covid is not None:
        data = panel[covid_flag(panel["quarter"], spec.covid) == 0]
    X = design(data, macro, spec)
    keep = X.notna().all(axis=1).to_numpy()
    X, data = X[keep], data[keep]
    offset = np.log(data["firms"].to_numpy(dtype=float))
    y = data["count"].to_numpy(dtype=float)
    clusters = data["quarter"].astype(str).to_numpy()
    if spec.variant != "C":
        return FittedSatellite(spec, fit_nb2(X, y, offset, clusters=clusters))

    # Variant C: fit B, shrink sector slopes, then refit with shrunk slopes in the offset.
    res_b = fit_nb2(X, y, offset, clusters=clusters)
    cols = [f"{SHRINK_VAR}_x_{s}" for s in config.MODEL_SECTORS]
    b = res_b.params[cols]
    v = np.diag(res_b.cov.loc[cols, cols].to_numpy())
    shrunk, weights, post_sd = empirical_bayes_shrink(b.to_numpy(), v)
    shrunk_s = pd.Series(shrunk, index=config.MODEL_SECTORS)
    X_rest = X.drop(columns=cols)
    extra = X[cols].to_numpy() @ shrunk
    res_c = fit_nb2(X_rest, y, offset + extra, clusters=clusters)
    return FittedSatellite(
        spec,
        res_c,
        shrunk=shrunk_s,
        shrink_weights=pd.Series(weights, index=config.MODEL_SECTORS),
        shrink_post_sd=pd.Series(post_sd, index=config.MODEL_SECTORS),
    )


def empirical_bayes_shrink(
    b: np.ndarray, v: np.ndarray
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Shrink estimates b (variances v) towards their precision-weighted mean.

    Between-sector variance tau^2 by DerSimonian-Laird. Returns shrunk slopes, the weight on
    each sector's own estimate (tau^2 / (tau^2 + v)) and an approximate posterior sd.
    """
    w = 1.0 / v
    mean = np.sum(w * b) / np.sum(w)
    q_stat = np.sum(w * (b - mean) ** 2)
    k = len(b)
    denom = np.sum(w) - np.sum(w**2) / np.sum(w)
    tau2 = max(0.0, (q_stat - (k - 1)) / denom) if denom > 0 else 0.0
    weight = tau2 / (tau2 + v) if tau2 > 0 else np.zeros(k)
    shrunk = mean + weight * (b - mean)
    post_var = weight * v + (1 - weight) ** 2 / np.sum(w)
    return shrunk, weight, np.sqrt(post_var)


def with_lag(spec: Spec, lag: int) -> Spec:
    return replace(spec, lag=lag)
