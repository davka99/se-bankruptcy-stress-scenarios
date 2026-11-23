"""Synthetic data generators for tests (everything here is `synthetic`, not real data)."""

from __future__ import annotations

import numpy as np
import pandas as pd

from src import config
from src.models.nb2 import simulate_counts

TRUE_BETA = {"d_unemp": 0.12, "gdp_yoy": -0.03, "d_policy": 0.05}
TRUE_ALPHA = 0.02


def synthetic_macro(start: str = "2005Q1", end: str = "2026Q2", seed: int = config.SEED):
    """synthetic quarterly macro drivers with realistic-looking scale."""
    rng = np.random.default_rng(seed)
    q = pd.period_range(start, end, freq="Q")
    n = len(q)
    unemp = 7 + np.cumsum(rng.normal(0, 0.25, n)) * 0.6
    gdp = 2 + rng.normal(0, 1.5, n)
    rate = np.clip(1.5 + np.cumsum(rng.normal(0, 0.25, n)), -0.5, 5)
    macro = pd.DataFrame({"unemp": unemp, "gdp_yoy": gdp, "policy_rate": rate}, index=q.astype(str))
    macro["d_unemp"] = macro["unemp"] - macro["unemp"].shift(4)
    macro["d_policy"] = macro["policy_rate"] - macro["policy_rate"].shift(4)
    return macro


def synthetic_panel(
    lag: int = 1,
    start: str = "2009Q1",
    end: str = "2026Q2",
    seed: int = config.SEED,
    alpha: float = TRUE_ALPHA,
    beta: dict[str, float] | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """synthetic sector x quarter panel drawn from the NB2 satellite model itself."""
    beta = beta or TRUE_BETA
    rng = np.random.default_rng(seed)
    macro = synthetic_macro(seed=seed)
    quarters = pd.period_range(start, end, freq="Q")
    rows = []
    base_rates = np.linspace(0.004, 0.02, len(config.MODEL_SECTORS))
    firms = rng.integers(20_000, 300_000, len(config.MODEL_SECTORS))
    for s, r0, f in zip(config.MODEL_SECTORS, base_rates, firms, strict=True):
        for q in quarters:
            m = macro.loc[str(q - lag)]
            seas = {1: 0.0, 2: 0.05, 3: -0.15, 4: 0.05}[q.quarter]
            eta = np.log(f) + np.log(r0 / 4) + seas + sum(beta[v] * m[v] for v in beta)
            rows.append({"sector": s, "quarter": str(q), "firms": float(f), "mu": np.exp(eta)})
    panel = pd.DataFrame(rows)
    panel["count"] = simulate_counts(panel["mu"].to_numpy(), alpha, rng).astype(float)
    panel["rate"] = 4 * panel["count"] / panel["firms"]
    panel["synthetic"] = True
    return panel.drop(columns="mu"), macro
