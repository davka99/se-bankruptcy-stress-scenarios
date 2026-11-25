"""Full-sample estimation of the selected satellite model: coefficients, overdispersion,
sign check, elasticities, sensitivity analyses, diagnostics and backtest figure."""

from __future__ import annotations

import json
import logging
from dataclasses import replace
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from src import backtest, config, plots
from src.models import satellite
from src.models.nb2 import fit_poisson

log = logging.getLogger(__name__)

LABELS = {
    "d_unemp": "Unemployment change (+1 pp y/y)",
    "gdp_yoy": "GDP growth (+1 % y/y)",
    "d_policy": "Policy-rate change (+1 pp y/y)",
    "covid_support": "Pandemic support (2020Q2-2021Q4)",
    "trend": "Trend (per year)",
}


def round1_spec(tables: Path = config.TABLES) -> satellite.Spec:
    """The model selected in round 1 (A6)."""
    name = json.loads((tables / "model_selection.json").read_text())["selected"]
    return next(s for s in backtest.all_specs() if s.name == name)


def selected_spec(tables: Path = config.TABLES) -> satellite.Spec:
    """The scenario model: the round-2 winner if A10's adoption rule was met, else round 1."""
    from src import round2

    return round2.scenario_spec(tables) or round1_spec(tables)


def coefficient_table(fitted: satellite.FittedSatellite) -> pd.DataFrame:
    names = [n for n in LABELS if n in fitted.result.exog_names]
    t = fitted.result.irr_table(names).reset_index(names="term")
    t["label"] = t["term"].map(LABELS)
    t["expected_sign"] = t["term"].map(config.EXPECTED_SIGNS)
    t["sign_as_expected"] = np.where(
        t["expected_sign"].isna(), np.nan, np.sign(t["coef"]) == t["expected_sign"]
    )
    z = t["coef"] / t["se"]
    t["significant_95"] = z.abs() > 1.96
    return t


def elasticity_table(fitted: satellite.FittedSatellite, panel: pd.DataFrame) -> pd.DataFrame:
    """+1 pp unemployment change: % change (common) and pp change per sector at latest level."""
    b = fitted.result.params["d_unemp"]
    se = fitted.result.bse()["d_unemp"]
    latest_q = panel["quarter"].max()
    latest = panel[panel["quarter"] == latest_q].set_index("sector")["rate_r4"]
    rows = []
    for s in config.MODEL_SECTORS:
        pct = np.exp(b) - 1
        lo, hi = np.exp(b - 1.96 * se) - 1, np.exp(b + 1.96 * se) - 1
        rows.append(
            {
                "sector": s,
                "sector_label": config.SECTORS[s],
                "rate_latest_4q_pct": 100 * latest[s],
                "effect_pct": 100 * pct,
                "effect_pct_lo95": 100 * lo,
                "effect_pct_hi95": 100 * hi,
                "effect_pp": 100 * latest[s] * pct,
                "effect_pp_lo95": 100 * latest[s] * lo,
                "effect_pp_hi95": 100 * latest[s] * hi,
            }
        )
    return pd.DataFrame(rows)


def sensitivity(panel: pd.DataFrame, macro: pd.DataFrame, spec: satellite.Spec) -> pd.DataFrame:
    """Macro coefficients under the pre-registered pandemic and denominator sensitivities."""
    variants = {
        "main": spec,
        "no pandemic dummy": replace(spec, covid=None),
        "dummy to 2022Q1": replace(spec, covid=config.COVID_SUPPORT_SENSITIVITY),
        "pandemic quarters excluded": replace(spec, exclude_covid_quarters=True),
    }
    rows = []
    for name, sp in variants.items():
        f = satellite.fit(panel, macro, sp)
        for v in spec.macro:
            rows.append(
                {
                    "variant": name,
                    "term": v,
                    "coef": f.result.params[v],
                    "se": f.result.bse()[v],
                    "alpha": f.result.alpha,
                }
            )
    fek = panel.dropna(subset=["firms_fek"]).assign(firms=lambda d: d["firms_fek"])
    f = satellite.fit(fek, macro, spec)
    for v in spec.macro:
        rows.append(
            {
                "variant": "FEK denominator",
                "term": v,
                "coef": f.result.params[v],
                "se": f.result.bse()[v],
                "alpha": f.result.alpha,
            }
        )
    out = pd.DataFrame(rows)
    out["irr"] = np.exp(out["coef"])
    return out


def residual_diagnostics(
    fitted: satellite.FittedSatellite, panel: pd.DataFrame, macro: pd.DataFrame
) -> pd.DataFrame:
    X = satellite.design(panel, macro, fitted.spec)
    ok = X.notna().all(axis=1).to_numpy()
    p = panel[ok].copy()
    mu = fitted.mu(X[ok], np.log(p["firms"].to_numpy(dtype=float)))
    a = fitted.result.alpha
    p["pearson_resid"] = (p["count"] - mu) / np.sqrt(mu + a * mu**2)
    return p[["sector", "quarter", "count", "pearson_resid"]]


def acf(x: np.ndarray, lags: int = 8) -> list[float]:
    x = x - x.mean()
    denom = np.sum(x * x)
    return [float(np.sum(x[k:] * x[: len(x) - k]) / denom) for k in range(1, lags + 1)]


def fig_diagnostics(resid: pd.DataFrame, folder: Path) -> Path:
    fig, axes = plt.subplots(1, 2, figsize=(12, 3.8))
    r = resid.copy()
    r["date"] = pd.PeriodIndex(r["quarter"], freq="Q").to_timestamp(how="end")
    for _, g in r.groupby("sector"):
        axes[0].plot(g["date"], g["pearson_resid"], color=plots.GRID, lw=1)
    med = r.groupby("date")["pearson_resid"].median()
    axes[0].plot(med.index, med.to_numpy(), color=plots.BASELINE, lw=2)
    axes[0].axhline(0, color=plots.INK_2, lw=0.8)
    axes[0].set_title("Pearson residuals by sector (grey) and median (blue)", fontsize=10)
    acfs = np.array([acf(g["pearson_resid"].to_numpy()) for _, g in r.groupby("sector")])
    lags = np.arange(1, acfs.shape[1] + 1)
    axes[1].bar(lags, np.median(acfs, axis=0), color=plots.BASELINE, width=0.6)
    n = r.groupby("sector").size().median()
    axes[1].axhline(1.96 / np.sqrt(n), color=plots.INK_2, ls="--", lw=0.8)
    axes[1].axhline(-1.96 / np.sqrt(n), color=plots.INK_2, ls="--", lw=0.8)
    axes[1].set_title("Median residual autocorrelation across sectors", fontsize=10)
    axes[1].set_xlabel("Lag (quarters)")
    lag1 = float(np.median(acfs[:, 0]))
    fig.suptitle(
        f"Residuals are autocorrelated (median lag-1 ACF {lag1:.2f}): sector deviations persist",
        x=0.01,
        ha="left",
        fontweight="bold",
    )
    fig.tight_layout(rect=(0, 0, 1, 0.92))
    plots.source_note(fig, plots.SOURCE_MACRO)
    return plots.save(fig, "model_residual_diagnostics", folder)


def fig_backtest(summary: pd.DataFrame, folder: Path) -> Path:
    fig, axes = plt.subplots(1, 2, figsize=(12, 3.8), sharey=True)
    order = ["seasonal_naive", "ets", "NOMACRO"]
    sat = [m for m in summary["model"].unique() if m.startswith("satellite")]
    models = order + sat
    names = {"seasonal_naive": "Seasonal naive", "ets": "ETS", "NOMACRO": "NB without macro"}
    colors = {
        "seasonal_naive": plots.INK_2,
        "ets": plots.HIGHLIGHT[1],
        "NOMACRO": plots.HIGHLIGHT[0],
    }
    width = 0.2
    for ax, period in zip(axes, ["selection", "test"], strict=True):
        s = summary[summary["period"] == period]
        for i, m in enumerate(models):
            g = s[s["model"] == m].sort_values("h")
            x = np.arange(len(g)) + (i - 1.5) * width
            ax.bar(
                x,
                g["mae_rate_pct"],
                width=width * 0.9,
                color=colors.get(m, plots.BASELINE),
                label=names.get(m, m),
            )
        ax.set_xticks(range(3), [f"h = {h}" for h in config.HORIZONS])
        title = (
            "Selection period (targets to 2022Q4)"
            if period == "selection"
            else ("Untouched test period (targets from 2023Q1)")
        )
        ax.set_title(title, fontsize=10)
    axes[0].set_ylabel("Firm-weighted MAE, pp of annual rate")
    axes[0].legend(fontsize=8, loc="upper left")
    t = summary[(summary["period"] == "test") & (summary["h"] == 4)].set_index("model")
    sat_name = sat[0]
    beats = t.loc[sat_name, "mae_rate_pct"] < t.loc["seasonal_naive", "mae_rate_pct"]
    fig.suptitle(
        "The satellite model beats seasonal naive at h = 4 in the test period"
        if beats
        else "Seasonal naive beats the satellite model at h = 4 in the test period",
        x=0.01,
        ha="left",
        fontweight="bold",
    )
    fig.tight_layout(rect=(0, 0, 1, 0.92))
    plots.source_note(fig, plots.SOURCE_MACRO + " Conditional backtest (actual macro).")
    return plots.save(fig, "backtest_mae", folder)


def main(out: Path = config.TABLES, figures: Path = config.FIGURES) -> dict:
    plots.apply_style()
    panel, macro = backtest.load_inputs()
    spec = selected_spec(out)
    fitted = satellite.fit(panel, macro, spec)

    coef = coefficient_table(fitted)
    coef.to_csv(out / "coefficients.csv", index=False)
    r1 = round1_spec(out)
    coefficient_table(satellite.fit(panel, macro, r1)).to_csv(
        out / "coefficients_round1.csv", index=False
    )
    X = satellite.design(panel, macro, spec)
    ok = X.notna().all(axis=1).to_numpy()
    _, poisson_disp = fit_poisson(X[ok], panel["count"][ok], np.log(panel["firms"][ok]))
    fit_stats = {
        "spec": spec.name,
        "nobs": fitted.result.nobs,
        "alpha": fitted.result.alpha,
        "nb_pearson_chi2_df": fitted.result.pearson_chi2_df,
        "poisson_pearson_chi2_df": poisson_disp,
        "loglik": fitted.result.loglik,
        "converged": fitted.result.converged,
        "sample": [panel.loc[ok, "quarter"].min(), panel.loc[ok, "quarter"].max()],
    }
    (out / "model_fit.json").write_text(json.dumps(fit_stats, indent=2, default=float))
    elasticity_table(fitted, panel).to_csv(out / "elasticity.csv", index=False)
    sensitivity(panel, macro, spec).to_csv(
        out / "sensitivity_pandemic_denominator.csv", index=False
    )
    resid = residual_diagnostics(fitted, panel, macro)
    fig_diagnostics(resid, figures)
    fig_backtest(pd.read_csv(out / "backtest.csv"), figures)
    log.info("Model report written (%s)", spec.name)
    return fit_stats


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print(main())
