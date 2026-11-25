"""Macro scenarios and simulated bankruptcy-rate paths by sector.

Baseline: Konjunkturinstitutet's latest forecast (frozen vintage in data/raw/ki/<date>/).
Adverse:  the deviation method - baseline + (EBA adverse - EBA baseline) for scenario years
          1-3, counted from the start quarter rather than EBA's calendar years. This moves
          EBA's shock size to today's starting point instead of using EBA's levels, which
          were built on December 2024 projections.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import numpy as np
import pandas as pd

from src import config, jsonstat
from src.models import satellite

log = logging.getLogger(__name__)

# Anchor points (in quarters after the start) at which annual deviations are attained:
# scenario year i is centred at quarter 4*(i-1) + 2.5. Deviation is 0 at the start.
ANCHORS = np.array([0.0, 2.5, 6.5, 10.5])


# --------------------------------------------------------------------------------------
# KI baseline
# --------------------------------------------------------------------------------------
def _ki_series(path: Path, variable: str, unit: str | None = None) -> pd.Series:
    df = jsonstat.read(path)
    df = df[df["variabel"] == variable]
    if unit is not None and "enhet" in df:
        df = df[df["enhet"] == unit]
    return df.set_index("period")["value"].dropna()


def ki_vintage_info(folder: Path) -> dict:
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    vintages = manifest.get("vintages", [])
    meta = json.loads((folder / "latest_unemployment_q_metadata.json").read_bytes())
    return {
        "database": "SenastePrognosen",
        "table_title": meta.get("title"),
        "retrieved": manifest["files"][0]["retrieved_at"],
        "latest_vintage_id_in_archive": vintages[0] if vintages else None,
    }


def interpolate_annual(annual: pd.Series, quarters: pd.PeriodIndex, anchor: tuple) -> pd.Series:
    """Quarterly values from annual averages placed mid-year, joined to a quarterly anchor."""
    x = [anchor[0].ordinal]
    y = [anchor[1]]
    for year, value in annual.items():
        mid = pd.Period(f"{int(year)}Q2", "Q").ordinal + 0.5
        if mid > x[-1]:
            x.append(mid)
            y.append(value)
    return pd.Series(np.interp([q.ordinal for q in quarters], x, y), index=quarters)


def baseline_path(
    macro_hist: pd.DataFrame, ki_folder: Path, start: pd.Period, horizon: int
) -> pd.DataFrame:
    """Quarterly levels (unemp, gdp_level, policy_rate) from 4 years before `start` to the end
    of the horizon: actual values where published (up to `start`), KI's forecast afterwards.

    Each series is spliced at its own last published quarter (GDP is published later than
    unemployment). GDP levels are spliced by growth rates so that revisions between KI's
    vintage and SCB's latest release do not create a jump.
    """
    quarters = pd.period_range(start - 16, start + horizon, freq="Q")
    hist = macro_hist.copy()
    hist.index = pd.PeriodIndex(hist.index.astype(str), freq="Q")
    hist = hist[hist.index <= start][["unemp", "gdp_level", "policy_rate"]]

    def last_actual(col: str) -> pd.Period:
        return hist[col].dropna().index.max()

    # Unemployment: KI quarterly table, then annual table interpolated (mid-year anchors).
    uq = _ki_series(ki_folder / "latest_unemployment_q.json", "F2108Arali1574")
    uq.index = pd.PeriodIndex(uq.index, freq="Q")
    ua = _ki_series(ki_folder / "latest_unemployment_a.json", "F2107Arali1574")
    ua.index = ua.index.astype(int)
    future_u = quarters[quarters > last_actual("unemp")]
    unemp = uq.reindex(future_u)
    if unemp.isna().any():
        last_q = uq.index.max()
        tail = future_u[unemp.isna().to_numpy()]
        unemp[unemp.isna()] = interpolate_annual(
            ua[ua.index > last_q.year], tail, (last_q, uq[last_q])
        ).to_numpy()

    # GDP: KI seasonally adjusted levels, spliced to SCB's level by growth.
    gq = _ki_series(ki_folder / "latest_gdp_q.json", "F0905Nbnpmpfs", "FL")
    gq.index = pd.PeriodIndex(gq.index, freq="Q")
    g0 = last_actual("gdp_level")
    future_g = quarters[quarters > g0]
    gdp = hist.loc[g0, "gdp_level"] * gq.reindex(future_g) / gq[g0]

    # Policy rate: KI monthly averages -> quarterly means after the start quarter.
    rm = _ki_series(ki_folder / "latest_policy_rate_m.json", "F0604Repo")
    rm.index = pd.PeriodIndex(rm.index.str.replace("M", "-"), freq="M")
    future_r = quarters[quarters > start]
    rate = rm.groupby(rm.index.asfreq("Q")).mean().reindex(future_r)

    path = hist.reindex(quarters)
    path.loc[future_u, "unemp"] = unemp.to_numpy()
    path.loc[future_g, "gdp_level"] = gdp.to_numpy()
    path.loc[future_r, "policy_rate"] = rate.to_numpy()
    if path.isna().any().any():
        raise ValueError(f"Baseline path incomplete:\n{path[path.isna().any(axis=1)]}")
    path["source_unemp"] = np.where(path.index > last_actual("unemp"), "KI", "SCB")
    path["source_gdp"] = np.where(path.index > g0, "KI", "SCB")
    path["source_policy_rate"] = np.where(path.index > start, "KI", "Riksbank")
    return path


# --------------------------------------------------------------------------------------
# EBA deviations
# --------------------------------------------------------------------------------------
def eba_deviations(eba: pd.DataFrame) -> pd.DataFrame:
    """Annual adverse-minus-baseline deviations for scenario years 1-3.

    unemp and rate_3m: percentage points. gdp: log-level difference of the cumulated paths.
    """
    wide = eba[eba["scenario"].isin(["baseline", "adverse"])].pivot_table(
        index="year", columns=["variable", "scenario"], values="value"
    )
    years = sorted(wide.index)
    g_base = np.log1p(wide[("gdp_growth", "baseline")] / 100).cumsum()
    g_adv = np.log1p(wide[("gdp_growth", "adverse")] / 100).cumsum()
    dev = pd.DataFrame(
        {
            "scenario_year": range(1, len(years) + 1),
            "eba_year": years,
            "d_unemp_level": (wide[("unemp", "adverse")] - wide[("unemp", "baseline")]).to_numpy(),
            "d_log_gdp": (g_adv - g_base).to_numpy(),
            "d_rate": (wide[("rate_3m", "adverse")] - wide[("rate_3m", "baseline")]).to_numpy(),
        }
    )
    return dev


def quarterly_deviation(annual: np.ndarray, horizon: int) -> np.ndarray:
    """Piecewise-linear quarterly deviation through the annual anchors, flat after year 3."""
    j = np.arange(1, horizon + 1, dtype=float)
    return np.interp(j, ANCHORS, np.concatenate([[0.0], annual]))


def adverse_path(base: pd.DataFrame, dev: pd.DataFrame, start: pd.Period) -> pd.DataFrame:
    adv = base.copy()
    fut = adv.index > start
    h = int(fut.sum())
    adv.loc[fut, "unemp"] += quarterly_deviation(dev["d_unemp_level"].to_numpy(), h)
    adv.loc[fut, "gdp_level"] *= np.exp(quarterly_deviation(dev["d_log_gdp"].to_numpy(), h))
    # EBA gives a 3M market rate, not the policy rate: its deviation proxies the policy-rate one.
    adv.loc[fut, "policy_rate"] += quarterly_deviation(dev["d_rate"].to_numpy(), h)
    return adv


def drivers(levels: pd.DataFrame) -> pd.DataFrame:
    """Model drivers (y/y changes) from quarterly levels."""
    out = levels.copy()
    out["d_unemp"] = out["unemp"] - out["unemp"].shift(4)
    out["gdp_yoy"] = 100 * (out["gdp_level"] / out["gdp_level"].shift(4) - 1)
    out["d_policy"] = out["policy_rate"] - out["policy_rate"].shift(4)
    out.index = out.index.astype(str)
    return out


# --------------------------------------------------------------------------------------
# Simulation
# --------------------------------------------------------------------------------------
def future_rows(panel: pd.DataFrame, start: pd.Period, horizon: int) -> pd.DataFrame:
    """Sector x future-quarter rows with exposure held at the latest observed stock."""
    latest = panel[panel["quarter"] == str(start)].set_index("sector")["firms"]
    quarters = pd.period_range(start + 1, start + horizon, freq="Q").astype(str)
    rows = [
        {"sector": s, "quarter": q, "firms": float(latest[s])}
        for s in config.MODEL_SECTORS
        for q in quarters
    ]
    return pd.DataFrame(rows)


def simulate_paths(
    fitted: satellite.FittedSatellite,
    rows: pd.DataFrame,
    macro: pd.DataFrame,
    n_sim: int,
    rng: np.random.Generator,
) -> np.ndarray:
    """(n_sim, len(rows)) simulated annualised rates; parameter uncertainty + NB noise."""
    X = satellite.design(rows, macro, fitted.spec)
    if "covid_support" in X:
        X["covid_support"] = 0.0  # the dummy is switched off in all forecasts
    if X.isna().any().any():
        raise ValueError("Missing macro drivers over the scenario horizon")
    offset = np.log(rows["firms"].to_numpy(dtype=float)) + fitted.ic_offset(rows)
    counts = fitted.simulate(X, offset, n_sim, rng)
    return counts * (4.0 / rows["firms"].to_numpy(dtype=float))[None, :]


def summarise_paths(rows: pd.DataFrame, rates: np.ndarray, scenario: str) -> pd.DataFrame:
    out = rows[["sector", "quarter"]].copy()
    out["scenario"] = scenario
    out["p10"] = np.quantile(rates, config.INTERVAL[0], axis=0)
    out["p50"] = np.quantile(rates, 0.5, axis=0)
    out["p90"] = np.quantile(rates, config.INTERVAL[1], axis=0)
    out["mean"] = rates.mean(axis=0)
    return out


def rolling_window_stats(rows: pd.DataFrame, rates: np.ndarray) -> pd.DataFrame:
    """Per sector and 4-quarter window: p10/p50/p90 of the window's average rate."""
    records = []
    for sector in rows["sector"].unique():
        idx = np.flatnonzero(rows["sector"].to_numpy() == sector)
        quarters = rows["quarter"].to_numpy()[idx]
        r = rates[:, idx]
        for w in range(len(idx) - 3):
            avg = r[:, w : w + 4].mean(axis=1)
            records.append(
                {
                    "sector": sector,
                    "window_start": quarters[w],
                    "window_end": quarters[w + 3],
                    "w_p10": float(np.quantile(avg, 0.1)),
                    "w_p50": float(np.quantile(avg, 0.5)),
                    "w_p90": float(np.quantile(avg, 0.9)),
                }
            )
    return pd.DataFrame(records)


def historical_mean_rate(panel: pd.DataFrame) -> pd.Series:
    """Mean annualised rate per sector over the full sample, pandemic quarters excluded."""
    covid = satellite.covid_flag(panel["quarter"], config.COVID_SUPPORT) == 1
    return panel[~covid].groupby("sector")["rate"].mean()


def watchlist(windows: pd.DataFrame, hist_mean: pd.Series, multiplier: float) -> pd.DataFrame:
    w = windows.copy()
    w["hist_mean"] = w["sector"].map(hist_mean)
    w["median_ratio"] = w["w_p50"] / w["hist_mean"]
    w["trigger"] = (w["median_ratio"] >= multiplier) & (w["w_p10"] > w["hist_mean"])
    agg = w.groupby("sector").agg(
        hist_mean=("hist_mean", "first"),
        max_median_ratio=("median_ratio", "max"),
        watchlist=("trigger", "any"),
    )
    agg["multiplier"] = multiplier
    return agg.reset_index()


# --------------------------------------------------------------------------------------
# Sensitivity grid and reverse stress test
# --------------------------------------------------------------------------------------
def sensitivity_grid(
    fitted: satellite.FittedSatellite,
    panel: pd.DataFrame,
    shocks: tuple[float, ...] = (1.0, 2.0, 3.0),
    n_draws: int = config.N_SIM,
    rng: np.random.Generator | None = None,
) -> pd.DataFrame:
    """Rate per sector while unemployment is `x` pp higher than a year earlier, other
    drivers unchanged, relative to the latest observed four-quarter rate. Also the
    unemployment rise that doubles the rate (reverse stress test), with an 80 % interval
    from the parameter draws."""
    rng = rng or np.random.default_rng(config.SEED)
    names = fitted.result.exog_names
    betas, _ = fitted.result.draw_params(n_draws, rng)
    latest = panel[panel["quarter"] == panel["quarter"].max()].set_index("sector")["rate_r4"]
    rows = []
    for s in config.MODEL_SECTORS:
        if fitted.spec.variant in ("B", "C"):
            col = f"d_unemp_x_{s}"
            b_hat = fitted.shrunk[s] if fitted.shrunk is not None else fitted.result.params[col]
            b_draw = (
                rng.normal(b_hat, fitted.shrink_post_sd[s], n_draws)
                if fitted.shrunk is not None
                else betas[:, names.index(col)]
            )
        else:
            b_hat = fitted.result.params["d_unemp"]
            b_draw = betas[:, names.index("d_unemp")]
        row = {"sector": s, "rate_latest_4q": float(latest[s]), "beta_d_unemp": float(b_hat)}
        for x in shocks:
            mult = np.exp(b_draw * x)
            row[f"rate_plus{int(x)}pp"] = float(latest[s] * np.exp(b_hat * x))
            row[f"rate_plus{int(x)}pp_p10"] = float(latest[s] * np.quantile(mult, 0.1))
            row[f"rate_plus{int(x)}pp_p90"] = float(latest[s] * np.quantile(mult, 0.9))
        with np.errstate(divide="ignore"):
            needed = np.where(b_draw > 0, np.log(2) / b_draw, np.inf)
        row["unemp_rise_to_double_pp"] = float(np.log(2) / b_hat) if b_hat > 0 else np.inf
        row["unemp_rise_to_double_p10"] = float(np.quantile(needed, 0.1))
        row["unemp_rise_to_double_p90"] = float(np.quantile(needed, 0.9))
        rows.append(row)
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------------------
def main(out: Path = config.TABLES, figures: Path = config.FIGURES) -> dict:
    from src import backtest, build_panel, model_report
    from src.fetch.common import latest_snapshot

    rng = np.random.default_rng(config.SEED)
    panel, macro = backtest.load_inputs()
    spec = model_report.selected_spec(out)
    fitted = satellite.fit(panel, macro, spec)
    start = pd.Period(panel["quarter"].max(), "Q")
    ki = latest_snapshot("ki")
    eba = pd.read_csv(config.REFERENCE / "eba_2025_sweden.csv")

    base_levels = baseline_path(macro, ki, start, config.SCENARIO_HORIZON)
    dev = eba_deviations(eba)
    adv_levels = adverse_path(base_levels, dev, start)
    paths = {"baseline": base_levels, "adverse": adv_levels}
    macro_paths = []
    for name, lv in paths.items():
        d = drivers(lv[["unemp", "gdp_level", "policy_rate"]])
        d["scenario"] = name
        macro_paths.append(d.reset_index(names="quarter"))
    macro_paths = pd.concat(macro_paths, ignore_index=True)
    macro_paths.to_csv(out / "scenario_macro_paths.csv", index=False)
    dev.to_csv(out / "eba_deviations.csv", index=False)

    rows = future_rows(build_panel.load("panel_quarterly"), start, config.SCENARIO_HORIZON)
    summaries, windows, sims = [], [], {}
    for name in paths:
        m = macro_paths[macro_paths["scenario"] == name].set_index("quarter")
        rates = simulate_paths(fitted, rows, m, config.N_SIM, rng)
        sims[name] = rates
        summaries.append(summarise_paths(rows, rates, name))
        w = rolling_window_stats(rows, rates)
        w["scenario"] = name
        windows.append(w)
    scen = pd.concat(summaries, ignore_index=True)
    scen[["sector", "quarter", "scenario", "p10", "p50", "p90", "mean"]].to_csv(
        out / "scenario_paths.csv", index=False
    )
    windows = pd.concat(windows, ignore_index=True)
    windows.to_csv(out / "scenario_windows.csv", index=False)

    hist_mean = historical_mean_rate(panel)
    adv_w = windows[windows["scenario"] == "adverse"]
    wl = pd.concat(
        [watchlist(adv_w, hist_mean, m) for m in (config.WATCHLIST_MULTIPLIER, 1.10, 1.50)],
        ignore_index=True,
    )
    wl.to_csv(out / "watchlist.csv", index=False)
    sensitivity_grid(fitted, panel, rng=rng).to_csv(out / "sensitivity_grid.csv", index=False)

    # Rate in the first scenario year and in the worst rolling 4-quarter window.
    first_year = [str(start + i) for i in range(1, 5)]
    overlay_rows = []
    for name, rates in sims.items():
        for s in config.MODEL_SECTORS:
            idx = np.flatnonzero((rows["sector"] == s).to_numpy())
            first = rates[:, idx[:4]].mean(axis=1)
            sw = windows[(windows["scenario"] == name) & (windows["sector"] == s)]
            worst = sw.loc[sw["w_p50"].idxmax()]
            overlay_rows.append(
                {
                    "sector": s,
                    "scenario": name,
                    "first_year": f"{first_year[0]}-{first_year[-1]}",
                    "rate_first_year_p50": float(np.median(first)),
                    "rate_first_year_p10": float(np.quantile(first, 0.1)),
                    "rate_first_year_p90": float(np.quantile(first, 0.9)),
                    "worst_window": f"{worst['window_start']}-{worst['window_end']}",
                    "rate_worst_window_p50": float(worst["w_p50"]),
                    "hist_mean_rate": float(hist_mean[s]),
                }
            )
    ov = pd.DataFrame(overlay_rows)
    ov["overlay_first_year"] = ov["rate_first_year_p50"] / ov["hist_mean_rate"] - 1
    ov["overlay_worst_window"] = ov["rate_worst_window_p50"] / ov["hist_mean_rate"] - 1
    ov.to_csv(out / "scenario_rates_overlay.csv", index=False)

    from src import scenario_plots

    agg = scenario_plots.aggregate(panel, rows, sims, start)
    agg.to_csv(out / "scenario_paths_total.csv", index=False)
    scenario_plots.main(panel, scen, macro_paths, start, figures, agg=agg)
    info = {
        "start_quarter": str(start),
        "horizon_quarters": config.SCENARIO_HORIZON,
        "n_sim": config.N_SIM,
        "model": spec.name,
        "ki_vintage": ki_vintage_info(ki),
        "eba_vintage": config.EBA_VINTAGE,
    }
    (out / "scenario_info.json").write_text(json.dumps(info, indent=2))
    log.info("Scenarios written from %s", start)
    return info
