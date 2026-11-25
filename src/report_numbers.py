"""Collect every number quoted in the README, the decision memo and the report into
reports/tables/key_numbers.json. Text is never edited by hand with numbers."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import numpy as np
import pandas as pd

from src import build_panel, config

log = logging.getLogger(__name__)


def pct(x: float, nd: int = 2) -> str:
    """Rate as 'per 100 firms' string, e.g. 0.01557 -> '1.56'."""
    return f"{100 * x:.{nd}f}"


def compute(tables: Path = config.TABLES) -> dict:
    k: dict = {}
    q = build_panel.load("panel_quarterly")
    monthly = build_panel.load("panel_monthly")
    model_q = q[q["sector"].isin(config.MODEL_SECTORS)]

    # Data
    k["first_month"] = monthly["month"].min()
    k["last_month"] = monthly["month"].max()
    k["last_quarter"] = q["quarter"].max()
    last12 = sorted(monthly["month"].unique())[-12:]
    k["bankruptcies_last_12m"] = f"{int(monthly[monthly['month'].isin(last12)]['count'].sum()):,}"
    agg = model_q.groupby("quarter").agg(c=("count", "sum"), f=("firms", "sum"))
    agg["r4"] = agg["c"].rolling(4).sum() / agg["f"]
    k["total_rate_latest_4q"] = pct(agg["r4"].iloc[-1])
    k["total_rate_2019"] = pct(agg.loc["2019Q4", "r4"])

    anchor = pd.read_csv(config.REFERENCE / "validation_anchor_2023.csv").set_index("sector")
    q23 = q[q["quarter"].str.startswith("2023")]
    ours = 100 * q23.groupby("sector")["count"].sum() / q23.groupby("sector")["firms"].first()
    dev = (
        ours[config.MODEL_SECTORS] - anchor.loc[config.MODEL_SECTORS, "share_of_existing_firms_pct"]
    ).abs()
    k["anchor_mad_pp"] = f"{dev.mean():.3f}"
    k["anchor_max_pp"] = f"{dev.max():.3f}"

    # Model
    fit = json.loads((tables / "model_fit.json").read_text())
    k["model_spec"] = fit["spec"]
    k["model_sample"] = f"{fit['sample'][0]}–{fit['sample'][1]}"
    k["nb_dispersion"] = f"{fit['nb_pearson_chi2_df']:.2f}"
    k["poisson_dispersion"] = f"{fit['poisson_pearson_chi2_df']:.2f}"
    coef = pd.read_csv(tables / "coefficients.csv").set_index("term")
    for term in ("d_unemp", "gdp_yoy", "d_policy", "covid_support"):
        r = coef.loc[term]
        k[f"irr_{term}"] = f"{100 * (r['irr'] - 1):+.1f}"
        k[f"irr_{term}_ci"] = f"{100 * (r['irr_lo'] - 1):+.1f} to {100 * (r['irr_hi'] - 1):+.1f}"
    el = pd.read_csv(tables / "elasticity.csv").set_index("sector")
    for s in ("CON", "HOR", "TRD"):
        k[f"effect_pp_{s}"] = f"{el.loc[s, 'effect_pp']:.2f}"

    # Backtest
    bt = pd.read_csv(tables / "backtest.csv")
    t4 = bt[(bt["period"] == "test") & (bt["h"] == 4)].set_index("model")
    s4 = bt[(bt["period"] == "selection") & (bt["h"] == 4)].set_index("model")
    sat = next(m for m in t4.index if m.startswith("satellite"))
    for name, frame in (("test", t4), ("sel", s4)):
        k[f"{name}_mae_sat"] = f"{frame.loc[sat, 'mae_rate_pct']:.3f}"
        k[f"{name}_mae_snaive"] = f"{frame.loc['seasonal_naive', 'mae_rate_pct']:.3f}"
        k[f"{name}_mae_ets"] = f"{frame.loc['ets', 'mae_rate_pct']:.3f}"
        k[f"{name}_mae_nomacro"] = f"{frame.loc['NOMACRO', 'mae_rate_pct']:.3f}"
        k[f"{name}_mase_sat"] = f"{frame.loc[sat, 'mase']:.2f}"
        k[f"{name}_cov_sat"] = f"{100 * frame.loc[sat, 'coverage80']:.0f}"
    k["beats_snaive_test_h4"] = bool(
        t4.loc[sat, "mae_rate_pct"] < t4.loc["seasonal_naive", "mae_rate_pct"]
    )
    k["beats_nomacro_test_h4"] = bool(
        t4.loc[sat, "mae_rate_pct"] < t4.loc["NOMACRO", "mae_rate_pct"]
    )
    rt = pd.read_csv(tables / "backtest_realtime.csv")
    rt4 = rt[(rt["period"] == "test") & (rt["h"] == 4)].set_index("model")
    k["test_mae_sat_realtime"] = (
        f"{rt4.loc[[m for m in rt4.index if 'real-time' in m][0], 'mae_rate_pct']:.3f}"
    )

    # Scenarios
    info = json.loads((tables / "scenario_info.json").read_text())
    k["scenario_start"] = info["start_quarter"]
    k["ki_vintage_id"] = info["ki_vintage"]["latest_vintage_id_in_archive"]
    k["ki_retrieved"] = info["ki_vintage"]["retrieved"][:10]
    k["eba_vintage"] = info["eba_vintage"]
    mp = pd.read_csv(tables / "scenario_macro_paths.csv")
    adv = mp[(mp["scenario"] == "adverse") & (mp["quarter"] > info["start_quarter"])]
    base = mp[(mp["scenario"] == "baseline") & (mp["quarter"] > info["start_quarter"])]
    k["adverse_unemp_peak"] = f"{adv['unemp'].max():.1f}"
    k["baseline_unemp_end"] = f"{base['unemp'].iloc[-1]:.1f}"
    k["adverse_gdp_min"] = f"{adv['gdp_yoy'].min():.1f}"
    tot = pd.read_csv(tables / "scenario_paths_total.csv")
    ta, tb = tot[tot["scenario"] == "adverse"], tot[tot["scenario"] == "baseline"]
    i = ta["p50"].idxmax()
    k["total_adverse_peak"] = pct(ta.loc[i, "p50"])
    k["total_adverse_peak_lo"] = pct(ta.loc[i, "p10"])
    k["total_adverse_peak_hi"] = pct(ta.loc[i, "p90"])
    k["total_adverse_peak_q"] = ta.loc[i, "quarter"]
    k["total_baseline_peak"] = pct(tb["p50"].max())
    k["total_baseline_min"] = pct(tb["p50"].min())

    ov = pd.read_csv(tables / "scenario_rates_overlay.csv")
    oa = ov[ov["scenario"] == "adverse"].set_index("sector")
    ob = ov[ov["scenario"] == "baseline"].set_index("sector")
    win = pd.read_csv(tables / "scenario_windows.csv")
    latest = model_q[model_q["quarter"] == k["last_quarter"]].set_index("sector")["rate_r4"]
    for s in config.MODEL_SECTORS:
        w = win[(win["scenario"] == "adverse") & (win["sector"] == s)]
        wi = w["w_p50"].idxmax()
        k[f"{s}_rate_now"] = pct(latest[s])
        k[f"{s}_adv_peak"] = pct(w.loc[wi, "w_p50"])
        k[f"{s}_adv_peak_lo"] = pct(w.loc[wi, "w_p10"])
        k[f"{s}_adv_peak_hi"] = pct(w.loc[wi, "w_p90"])
        k[f"{s}_adv_peak_window"] = f"{w.loc[wi, 'window_start']}–{w.loc[wi, 'window_end']}"
        k[f"{s}_hist_mean"] = pct(oa.loc[s, "hist_mean_rate"])
        k[f"{s}_overlay_adv"] = f"{100 * oa.loc[s, 'overlay_first_year']:+.0f}"
        k[f"{s}_overlay_adv_worst"] = f"{100 * oa.loc[s, 'overlay_worst_window']:+.0f}"
        k[f"{s}_overlay_base"] = f"{100 * ob.loc[s, 'overlay_first_year']:+.0f}"
    w_b, w_a = config.SCENARIO_WEIGHTS["baseline"], config.SCENARIO_WEIGHTS["adverse"]
    weighted = w_b * ob["overlay_first_year"] + w_a * oa["overlay_first_year"]
    for s in config.MODEL_SECTORS:
        k[f"{s}_overlay_weighted"] = f"{100 * weighted[s]:+.0f}"
    k["overlay_adv_min"] = f"{100 * oa['overlay_first_year'].min():.0f}"
    k["overlay_adv_max"] = f"{100 * oa['overlay_first_year'].max():.0f}"
    k["overlay_worst_min"] = f"{100 * oa['overlay_worst_window'].min():.0f}"
    k["overlay_worst_max"] = f"{100 * oa['overlay_worst_window'].max():.0f}"
    k["overlay_base_min"] = f"{100 * ob['overlay_first_year'].min():.0f}"
    k["overlay_base_max"] = f"{100 * ob['overlay_first_year'].max():.0f}"

    wl = pd.read_csv(tables / "watchlist.csv")
    main_wl = wl[np.isclose(wl["multiplier"], config.WATCHLIST_MULTIPLIER)]
    k["watchlist_n"] = int(main_wl["watchlist"].sum())
    # Priority within the watchlist: largest increase in percentage points (worst window).
    inc = (oa["rate_worst_window_p50"] - oa["hist_mean_rate"]).sort_values(ascending=False)
    flagged = [s for s in inc.index if s in set(main_wl.loc[main_wl["watchlist"], "sector"])]
    for j, s in enumerate(flagged[:3], start=1):
        k[f"priority{j}"] = config.SECTORS[s].split(" (")[0]
        k[f"priority{j}_code"] = s
        k[f"priority{j}_inc_pp"] = f"{100 * inc[s]:.2f}"

    grid = pd.read_csv(tables / "sensitivity_grid.csv").set_index("sector")
    k["double_unemp_pp"] = f"{grid.loc['CON', 'unemp_rise_to_double_pp']:.1f}"
    k["double_unemp_lo"] = f"{grid.loc['CON', 'unemp_rise_to_double_p10']:.1f}"
    k["double_unemp_hi"] = f"{grid.loc['CON', 'unemp_rise_to_double_p90']:.1f}"
    for x in (1, 2, 3):
        k[f"CON_plus{x}pp"] = pct(grid.loc["CON", f"rate_plus{x}pp"])

    ecl = pd.read_csv(tables / "synthetic_ecl_by_sector.csv")
    ttc, w = ecl["ecl_ttc_sek"].sum(), ecl["ecl_weighted_sek"].sum()
    k["synthetic_ecl_weighted_vs_ttc"] = f"{100 * (w / ttc - 1):+.0f}"
    k["synthetic_ecl_adverse_vs_base"] = (
        f"{100 * (ecl['ecl_adverse_sek'].sum() / ecl['ecl_baseline_sek'].sum() - 1):+.0f}"
    )

    mon = pd.read_csv(tables / "monitoring_log.csv", dtype={"quarter": str})
    last = mon[mon["quarter"] == mon["quarter"].max()]
    k["monitoring_quarter"] = mon["quarter"].max()
    for status in ("green", "yellow", "red"):
        k[f"monitoring_{status}"] = int((last["status"] == status).sum())
    reds = last.loc[last["status"] == "red", "sector"].tolist()
    k["monitoring_red_sectors"] = (
        ", ".join(config.SECTORS[s].split(" (")[0] for s in reds) or "none"
    )
    return k


def main(out: Path = config.TABLES) -> dict:
    k = compute(out)
    (out / "key_numbers.json").write_text(json.dumps(k, indent=2, ensure_ascii=False))
    log.info("key_numbers.json written (%d numbers)", len(k))
    return k


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print(json.dumps(main(), indent=1, ensure_ascii=False))
