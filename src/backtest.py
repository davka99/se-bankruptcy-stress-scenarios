"""Rolling-origin backtest (expanding window) with a selection period and an untouched test period.

The backtest is *conditional*: it uses the actual macro outcomes over the forecast horizon,
so it measures how well the model maps macro to bankruptcies, not how well anyone could
forecast the macro. A real-time variant replaces the actual macro with KI forecast vintages.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path

import numpy as np
import pandas as pd

from src import config
from src.models import baselines, satellite

log = logging.getLogger(__name__)

N_SIM_BACKTEST = 1000  # fewer draws than the scenarios (5,000) to keep runtime reasonable


def crps_sample(samples: np.ndarray, obs: float) -> float:
    """Sample CRPS: E|X - y| - 0.5 E|X - X'| (computed with sorted samples)."""
    x = np.sort(samples)
    n = len(x)
    term1 = np.mean(np.abs(x - obs))
    i = np.arange(1, n + 1)
    term2 = np.sum((2 * i - n - 1) * x) / (n * n)
    return float(term1 - term2)


def origins(panel: pd.DataFrame, first: str = config.FIRST_ORIGIN) -> list[pd.Period]:
    quarters = pd.PeriodIndex(sorted(panel["quarter"].astype(str).unique()), freq="Q")
    first_p = pd.Period(first, "Q")
    # require at least MIN_TRAIN_QUARTERS of training data
    earliest = quarters[0] + config.MIN_TRAIN_QUARTERS - 1
    start = max(first_p, earliest)
    return [q for q in quarters if start <= q < quarters[-1]]


def _nb_forecasts(
    fitted: satellite.FittedSatellite,
    target_rows: pd.DataFrame,
    macro: pd.DataFrame,
    rng: np.random.Generator,
    n_sim: int,
) -> pd.DataFrame:
    X = satellite.design(target_rows, macro, fitted.spec)
    complete = X.notna().all(axis=1).to_numpy()  # e.g. GDP not yet published for the target
    X, target_rows = X[complete], target_rows[complete]
    offset = np.log(target_rows["firms"].to_numpy(dtype=float)) + fitted.ic_offset(target_rows)
    mu = fitted.mu(X, offset)
    sims = fitted.simulate(X, offset, n_sim, rng)
    scale = 4.0 / target_rows["firms"].to_numpy(dtype=float)
    rates = sims * scale[None, :]
    out = target_rows[["sector", "quarter", "rate", "firms", "count"]].copy()
    out["forecast"] = mu * scale
    out["p10"] = np.quantile(rates, config.INTERVAL[0], axis=0)
    out["p50"] = np.quantile(rates, 0.5, axis=0)
    out["p90"] = np.quantile(rates, config.INTERVAL[1], axis=0)
    out["crps"] = [crps_sample(rates[:, j], r) for j, r in enumerate(out["rate"])]
    return out


def run(
    panel: pd.DataFrame,
    macro: pd.DataFrame,
    specs: list[satellite.Spec],
    horizons: list[int] = config.HORIZONS,
    include_baselines: bool = True,
    macro_for_origin: Callable[[pd.Period], pd.DataFrame] | None = None,
    origin_list: list[pd.Period] | None = None,
    n_sim: int = N_SIM_BACKTEST,
    seed: int = config.SEED,
) -> pd.DataFrame:
    """Long table: origin, h, target, sector, model, forecast, p10/p50/p90, actual, firms.

    `macro_for_origin(origin)` returns the macro frame to use for targets (real-time
    variant); by default the actual macro outcomes are used (conditional backtest).
    """
    rng = np.random.default_rng(seed)
    panel = panel[panel["sector"].isin(config.MODEL_SECTORS)].copy()
    panel["qp"] = pd.PeriodIndex(panel["quarter"].astype(str), freq="Q")
    rate_hist = panel.set_index(["sector", "qp"])["rate"]
    rows = []
    for origin in origin_list or origins(panel):
        train = panel[panel["qp"] <= origin]
        # The training panel never sees anything after the origin (tested in test_models).
        train_macro = macro[pd.PeriodIndex(macro.index.astype(str), freq="Q") <= origin]
        targets = {h: origin + h for h in horizons if origin + h <= panel["qp"].max()}
        if not targets:
            continue
        target_rows = panel[panel["qp"].isin(list(targets.values()))]
        target_macro = macro if macro_for_origin is None else macro_for_origin(origin)
        for spec in specs:
            fitted = satellite.fit(train.drop(columns="qp"), train_macro, spec)
            fc = _nb_forecasts(fitted, target_rows.drop(columns="qp"), target_macro, rng, n_sim)
            fc["model"] = spec.name
            fc["origin"] = str(origin)
            rows.append(fc)
        if include_baselines:
            for sector, grp in train.groupby("sector"):
                hist = grp.set_index("qp")["rate"]
                log_rate = np.log(np.maximum(hist.to_numpy(), 1e-6))
                ets = baselines.ets_forecast(log_rate, list(targets))
                for h, target in targets.items():
                    actual = target_rows[
                        (target_rows["sector"] == sector) & (target_rows["qp"] == target)
                    ]
                    if actual.empty:
                        continue
                    base = {
                        "sector": sector,
                        "quarter": str(target),
                        "rate": float(actual["rate"].iloc[0]),
                        "firms": float(actual["firms"].iloc[0]),
                        "count": float(actual["count"].iloc[0]),
                        "origin": str(origin),
                    }
                    snaive = baselines.seasonal_naive(rate_hist.loc[sector], origin, target)
                    rows.append(
                        pd.DataFrame([{**base, "model": "seasonal_naive", "forecast": snaive}])
                    )
                    rows.append(
                        pd.DataFrame([{**base, "model": "ets", "forecast": np.exp(ets[h])}])
                    )
        log.info("Backtest origin %s done", origin)
    out = pd.concat(rows, ignore_index=True)
    out["h"] = (
        pd.PeriodIndex(out["quarter"], freq="Q") - pd.PeriodIndex(out["origin"], freq="Q")
    ).map(lambda d: d.n)
    out["abs_err"] = (out["forecast"] - out["rate"]).abs()
    inside = (out["rate"] >= out["p10"]) & (out["rate"] <= out["p90"])
    out["covered"] = np.where(out["p10"].isna(), np.nan, inside.astype(float))
    return out


def period_of(target: pd.Series) -> pd.Series:
    p = pd.PeriodIndex(target.astype(str), freq="Q")
    sel_end = pd.Period(config.SELECTION_END, "Q")
    return pd.Series(np.where(p <= sel_end, "selection", "test"), index=target.index)


def summarise(bt: pd.DataFrame) -> pd.DataFrame:
    """Firm-weighted MAE, MASE vs seasonal naive, coverage and CRPS per model x horizon x period."""
    bt = bt.copy()
    bt["period"] = period_of(bt["quarter"])
    # Compare models on the same forecasts only (some targets lack published drivers).
    keys = ["origin", "quarter", "sector"]
    bt["_key"] = bt[keys].astype(str).agg("|".join, axis=1)
    common = set.intersection(*(set(g["_key"]) for _, g in bt.groupby("model")))
    bt = bt[bt["_key"].isin(common)].drop(columns="_key")
    snaive = bt[bt["model"] == "seasonal_naive"].set_index(["origin", "quarter", "sector"])[
        "abs_err"
    ]
    rows = []
    for (model, h, period), g in bt.groupby(["model", "h", "period"]):
        w = g["firms"]
        mae = float(np.sum(w * g["abs_err"]) / np.sum(w))
        key = g.set_index(["origin", "quarter", "sector"]).index
        sn = snaive.reindex(key).to_numpy()
        ok = ~np.isnan(sn)
        mase = (
            float(np.sum(w[ok] * g["abs_err"][ok]) / np.sum(w[ok] * sn[ok])) if ok.any() else np.nan
        )
        cov = g["covered"].dropna()
        rows.append(
            {
                "model": model,
                "h": int(h),
                "period": period,
                "n": len(g),
                "mae_rate_pct": 100 * mae,
                "mase": mase,
                "coverage80": float(cov.mean()) if len(cov) else np.nan,
                "crps_pct": 100 * float(g["crps"].mean()) if g["crps"].notna().any() else np.nan,
            }
        )
    return pd.DataFrame(rows).sort_values(["period", "h", "mae_rate_pct"]).reset_index(drop=True)


# --------------------------------------------------------------------------------------
# Pre-registered selection and one-off test evaluation
# --------------------------------------------------------------------------------------
def selection_origins(panel: pd.DataFrame) -> list[pd.Period]:
    sel_end = pd.Period(config.SELECTION_END, "Q")
    return [o for o in origins(panel) if o + min(config.HORIZONS) <= sel_end]


def test_origins(panel: pd.DataFrame) -> list[pd.Period]:
    test_start = pd.Period(config.TEST_START, "Q")
    return [o for o in origins(panel) if o + max(config.HORIZONS) >= test_start]


def only_period(bt: pd.DataFrame, period: str) -> pd.DataFrame:
    return bt[period_of(bt["quarter"]) == period].reset_index(drop=True)


def pick(summary: pd.DataFrame, candidates: list[str], h: int = config.SELECTION_HORIZON) -> str:
    """Lowest firm-weighted MAE at horizon h; ties within 1 % go to the earlier candidate."""
    s = summary[(summary["h"] == h) & summary["model"].isin(candidates)].set_index("model")
    best = s["mae_rate_pct"].min()
    for name in candidates:  # candidates are listed from simplest to most complex
        if name in s.index and s.loc[name, "mae_rate_pct"] <= best * 1.01:
            return name
    raise ValueError("no candidate evaluated")


def run_selection(panel: pd.DataFrame, macro: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Step 1: variant A over the lag grid. Step 2: B, C and no-trend at the best lag."""
    org = selection_origins(panel)
    step1 = satellite.spec_grid()
    bt1 = only_period(run(panel, macro, step1, origin_list=org), "selection")
    best_a = pick(summarise(bt1), [s.name for s in step1])
    best_lag = next(s.lag for s in step1 if s.name == best_a)
    step2 = satellite.spec_grid(best_lag)[len(step1) :]
    nomacro = [satellite.Spec("NOMACRO", variant="NOMACRO")]  # baseline 3, not a candidate
    bt2 = only_period(
        run(panel, macro, step2 + nomacro, origin_list=org, include_baselines=False), "selection"
    )
    bt = pd.concat([bt1, bt2], ignore_index=True)
    summary = summarise(bt)
    order = [best_a, f"A_k{best_lag}_notrend", f"C_k{best_lag}", f"B_k{best_lag}"]
    chosen = pick(summary, order)
    return bt, {"best_lag": best_lag, "best_A": best_a, "selected": chosen}


def run_test(panel: pd.DataFrame, macro: pd.DataFrame, selected: str) -> pd.DataFrame:
    """One-off evaluation on the untouched test period (targets from TEST_START)."""
    spec = next(s for s in all_specs() if s.name == selected)
    specs = [spec, satellite.Spec("NOMACRO", variant="NOMACRO")]
    bt = run(panel, macro, specs, origin_list=test_origins(panel))
    return only_period(bt, "test")


def all_specs() -> list[satellite.Spec]:
    specs = satellite.spec_grid()
    for k in config.LAG_GRID:
        specs += satellite.spec_grid(k)[len(config.LAG_GRID) :]
    return specs


def load_inputs() -> tuple[pd.DataFrame, pd.DataFrame]:
    from src import build_panel

    q = build_panel.load("panel_quarterly")
    q = q[q["sector"].isin(config.MODEL_SECTORS)].reset_index(drop=True)
    macro = build_panel.load("macro_quarterly").set_index("quarter")
    return q, macro


def main_selection(out: Path = config.TABLES) -> dict:
    import json

    panel, macro = load_inputs()
    bt, selection = run_selection(panel, macro)
    out.mkdir(parents=True, exist_ok=True)
    summary = summarise(bt)
    summary.to_csv(out / "backtest_selection_summary.csv", index=False)
    bt.to_csv(out / "backtest_selection_detail.csv", index=False)
    (out / "model_selection.json").write_text(json.dumps(selection, indent=2))
    log.info("Selected model: %s", selection)
    return selection


def main_test(out: Path = config.TABLES) -> pd.DataFrame:
    import json

    panel, macro = load_inputs()
    selected = json.loads((out / "model_selection.json").read_text())["selected"]
    test = run_test(panel, macro, selected)
    test.to_csv(out / "backtest_test_detail.csv", index=False)
    sel = pd.read_csv(out / "backtest_selection_detail.csv", dtype={"origin": str, "quarter": str})
    keep = ["seasonal_naive", "ets", "NOMACRO", selected]
    combined = pd.concat([sel[sel["model"].isin(keep)], test], ignore_index=True)
    summary = summarise(combined)
    summary["model"] = summary["model"].replace({selected: f"satellite ({selected})"})
    summary.to_csv(out / "backtest.csv", index=False)
    return summary


def smoke(tmp: Path) -> None:
    """CI smoke test on the small synthetic fixture (data/fixtures, `synthetic`)."""
    panel = pd.read_csv(config.FIXTURES / "synthetic_panel.csv", dtype={"quarter": str})
    macro = pd.read_csv(config.FIXTURES / "synthetic_macro.csv", dtype={"quarter": str})
    macro = macro.set_index("quarter")
    bt = run(
        panel,
        macro,
        [satellite.Spec("A_k1", lag=1)],
        origin_list=[pd.Period("2015Q4", "Q")],
        n_sim=100,
    )
    summary = summarise(bt)
    summary.to_csv(tmp / "smoke_backtest_synthetic.csv", index=False)
    log.info("Smoke backtest on synthetic fixture: %d rows", len(bt))
