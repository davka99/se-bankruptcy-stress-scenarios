"""Negative binomial (NB2) regression with an offset, estimated by maximum likelihood.

    y_i ~ NB2(mu_i, alpha),  Var(y_i) = mu_i + alpha * mu_i**2,
    log mu_i = x_i' beta + offset_i

Both beta and alpha are estimated by ML (alpha through log alpha, so it stays positive).
This is the same model as `statsmodels.discrete.discrete_model.NegativeBinomial` with
`loglike_method="nb2"`; `tests/test_models.py` checks the two agree.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from scipy import optimize, special


def _loglik_terms(y: np.ndarray, mu: np.ndarray, alpha: float) -> np.ndarray:
    inv = 1.0 / alpha
    return (
        special.gammaln(y + inv)
        - special.gammaln(inv)
        - special.gammaln(y + 1.0)
        + inv * np.log(inv / (inv + mu))
        + y * np.log(mu / (inv + mu))
    )


def _scores(X: np.ndarray, y: np.ndarray, mu: np.ndarray, alpha: float) -> np.ndarray:
    """Per-observation score w.r.t. (beta, log alpha)."""
    inv = 1.0 / alpha
    s_beta = X * ((y - mu) / (1.0 + alpha * mu))[:, None]
    d_alpha = inv**2 * (np.log1p(alpha * mu) - special.digamma(y + inv) + special.digamma(inv)) + (
        y - mu
    ) / (alpha * (1.0 + alpha * mu))
    return np.column_stack([s_beta, d_alpha * alpha])


def _poisson_start(X: np.ndarray, y: np.ndarray, offset: np.ndarray, iters: int = 50) -> np.ndarray:
    """Poisson IRLS for starting values."""
    beta = np.zeros(X.shape[1])
    beta_lstsq = np.linalg.lstsq(X, np.log(y + 0.5) - offset, rcond=None)[0]
    beta[:] = beta_lstsq
    for _ in range(iters):
        eta = np.clip(X @ beta + offset, -30, 30)
        mu = np.exp(eta)
        z = eta - offset + (y - mu) / mu
        W = mu
        XtW = X.T * W
        new = np.linalg.solve(XtW @ X + 1e-10 * np.eye(X.shape[1]), XtW @ z)
        if np.max(np.abs(new - beta)) < 1e-10:
            beta = new
            break
        beta = new
    return beta


@dataclass
class NB2Result:
    params: pd.Series  # beta (named) followed by "alpha"
    cov: pd.DataFrame  # covariance of (beta, log alpha), robust if clusters were given
    cov_model: pd.DataFrame  # model-based (inverse Hessian) covariance of (beta, log alpha)
    loglik: float
    nobs: int
    converged: bool
    exog_names: list[str] = field(default_factory=list)
    pearson_chi2_df: float = float("nan")

    @property
    def beta(self) -> np.ndarray:
        return self.params[self.exog_names].to_numpy()

    @property
    def alpha(self) -> float:
        return float(self.params["alpha"])

    def predict_mu(self, X: pd.DataFrame | np.ndarray, offset: np.ndarray) -> np.ndarray:
        Xa = X[self.exog_names].to_numpy() if isinstance(X, pd.DataFrame) else X
        return np.exp(Xa @ self.beta + offset)

    def bse(self) -> pd.Series:
        return pd.Series(np.sqrt(np.diag(self.cov)), index=self.cov.index)

    def irr_table(self, names: list[str]) -> pd.DataFrame:
        """Incidence rate ratios with 95 % CI (robust SE) for selected coefficients."""
        se = self.bse()
        b = self.params[names]
        z = 1.959963984540054
        return pd.DataFrame(
            {
                "coef": b,
                "se": se[names],
                "irr": np.exp(b),
                "irr_lo": np.exp(b - z * se[names]),
                "irr_hi": np.exp(b + z * se[names]),
            }
        )

    def draw_params(self, n: int, rng: np.random.Generator) -> tuple[np.ndarray, np.ndarray]:
        """Draws of (beta, alpha) from the asymptotic normal of (beta, log alpha)."""
        mean = np.append(self.beta, np.log(self.alpha))
        draws = rng.multivariate_normal(mean, self.cov.to_numpy(), size=n, method="eigh")
        return draws[:, :-1], np.exp(draws[:, -1])


def fit_nb2(
    X: pd.DataFrame,
    y: np.ndarray | pd.Series,
    offset: np.ndarray | pd.Series | None = None,
    clusters: np.ndarray | pd.Series | None = None,
    maxiter: int = 2000,
) -> NB2Result:
    names = list(X.columns)
    Xa = X.to_numpy(dtype=float)
    ya = np.asarray(y, dtype=float)
    off = np.zeros(len(ya)) if offset is None else np.asarray(offset, dtype=float)
    if np.any(ya < 0) or np.any(~np.isfinite(Xa)):
        raise ValueError("counts must be non-negative and X finite")

    beta0 = _poisson_start(Xa, ya, off)
    mu0 = np.exp(Xa @ beta0 + off)
    alpha0 = max(np.mean(((ya - mu0) ** 2 - ya) / mu0**2), 1e-3)
    theta0 = np.append(beta0, np.log(alpha0))

    def negll(theta: np.ndarray) -> float:
        mu = np.exp(np.clip(Xa @ theta[:-1] + off, -30, 30))
        return -float(np.sum(_loglik_terms(ya, mu, float(np.exp(theta[-1])))))

    def neggrad(theta: np.ndarray) -> np.ndarray:
        mu = np.exp(np.clip(Xa @ theta[:-1] + off, -30, 30))
        return -_scores(Xa, ya, mu, float(np.exp(theta[-1]))).sum(axis=0)

    res = optimize.minimize(
        negll, theta0, jac=neggrad, method="BFGS", options={"maxiter": maxiter, "gtol": 1e-8}
    )
    theta = res.x
    k = len(theta)

    def hessian(th: np.ndarray) -> np.ndarray:
        """Numerical Hessian from the analytic gradient (central differences)."""
        H = np.zeros((k, k))
        for j in range(k):
            h = 1e-5 * max(1.0, abs(th[j]))
            e = np.zeros(k)
            e[j] = h
            H[:, j] = (neggrad(th + e) - neggrad(th - e)) / (2 * h)
        return 0.5 * (H + H.T)

    # Polish the BFGS solution with Newton steps (with step halving).
    for _ in range(25):
        g = neggrad(theta)
        if np.max(np.abs(g)) < 1e-7 * max(1.0, abs(negll(theta))):
            break
        step = np.linalg.lstsq(hessian(theta), g, rcond=None)[0]
        t, f0 = 1.0, negll(theta)
        while t > 1e-4 and negll(theta - t * step) > f0:
            t /= 2
        theta = theta - t * step
    H = hessian(theta)
    H_inv = np.linalg.pinv(H)

    mu = np.exp(Xa @ theta[:-1] + off)
    alpha = float(np.exp(theta[-1]))
    if clusters is not None:
        S = _scores(Xa, ya, mu, alpha)
        groups = pd.Series(np.asarray(clusters)).astype(str).to_numpy()
        uniq = np.unique(groups)
        meat = np.zeros((k, k))
        for g in uniq:
            sg = S[groups == g].sum(axis=0)
            meat += np.outer(sg, sg)
        G = len(uniq)
        n = len(ya)
        factor = G / (G - 1) * (n - 1) / (n - k) if G > 1 else 1.0
        cov = factor * H_inv @ meat @ H_inv
    else:
        cov = H_inv

    labels = [*names, "log_alpha"]
    pearson = float(np.sum((ya - mu) ** 2 / (mu + alpha * mu**2)) / (len(ya) - k))
    return NB2Result(
        params=pd.Series(np.append(theta[:-1], alpha), index=[*names, "alpha"]),
        cov=pd.DataFrame(cov, index=labels, columns=labels),
        cov_model=pd.DataFrame(H_inv, index=labels, columns=labels),
        loglik=-float(res.fun),
        nobs=len(ya),
        converged=float(np.max(np.abs(neggrad(theta)))) < 1e-4 * max(1.0, abs(negll(theta))),
        exog_names=names,
        pearson_chi2_df=pearson,
    )


def fit_poisson(X: pd.DataFrame, y, offset=None) -> tuple[pd.Series, float]:
    """Poisson ML coefficients and Pearson chi2/df (to show overdispersion)."""
    Xa = X.to_numpy(dtype=float)
    ya = np.asarray(y, dtype=float)
    off = np.zeros(len(ya)) if offset is None else np.asarray(offset, dtype=float)
    beta = _poisson_start(Xa, ya, off, iters=200)
    mu = np.exp(Xa @ beta + off)
    chi2_df = float(np.sum((ya - mu) ** 2 / mu) / (len(ya) - Xa.shape[1]))
    return pd.Series(beta, index=X.columns), chi2_df


def simulate_counts(
    mu: np.ndarray, alpha: np.ndarray | float, rng: np.random.Generator
) -> np.ndarray:
    """NB2 draws via the gamma-Poisson mixture. `mu` and `alpha` broadcast together."""
    alpha = np.asarray(alpha, dtype=float)
    shape = 1.0 / alpha
    lam = rng.gamma(shape=np.broadcast_to(shape, np.shape(mu)), scale=np.asarray(mu) * alpha)
    return rng.poisson(lam)
