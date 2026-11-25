"""Round 2 (pre-registered in docs/decisions.md A10): variable-specific lags, an industry
intercept correction for persistence, empirical intervals and a watchlist rule based on the
additional rate under stress.

Selection uses the selection period only. The test period was already seen in A7, so it is
re-evaluated for every candidate but labelled "seen before" and never used to choose.

Two pipeline steps:
    main     selection, test-period re-evaluation, conformal bands; writes
             round2_selection.json, which decides the scenario model (A10 adoption rule)
    compare  after the scenarios: round-1 vs adopted model and the A10 watchlist
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, replace
from pathlib import Path

import numpy as np
import pandas as pd

from src import backtest, build_panel, config, scenarios
from src.models import satellite

log = logging.getLogger(__name__)

POLICY_LAG = 4
IC_RHOS = {"IC085": 0.85, "IC1": 1.0}
ADOPT_IMPROVEMENT = 0.05  # winner must beat A_k0 by >= 5 % (selection period, h = 4)
WATCH_MULTIPLE = 1.25

MACRO_FORMS = {
    "U0": satellite.Spec("U0", lag=0, macro=("d_unemp",)),
    "A_k0": satellite.Spec("A_k0", lag=0),
    "U0_P4": satellite.Spec(
        "U0_P4", lag=0, macro=("d_unemp", f"{satellite.POLICY_LAG_SUFFIX}{POLICY_LAG}")
    ),
}
STEP1_ORDER = ["U0", "A_k0", "U0_P4"]  # simplest first; ties within 1 % go to the earlier


def with_ic(form: str, key: str) -> satellite.Spec:
    return replace(MACRO_FORMS[form], name=f"{form}+{key}", ic_rho=IC_RHOS[key])


def spec_from_json(d: dict) -> satellite.Spec:
    d = dict(d)
    d["macro"] = tuple(d["macro"])
    d["covid"] = tuple(d["covid"]) if d.get("covid") else None
    return satellite.Spec(**d)


def scenario_spec(tables: Path = config.TABLES) -> satellite.Spec | None:
    """The round-2 spec if A10's adoption rule was met, else None."""
    path = tables / "round2_selection.json"
    if not path.exists():
        return None
    info = json.loads(path.read_text())
    return spec_from_json(info["scenario_spec"]) if info["adopted_for_scenarios"] else None


def conformal_bands(sel_detail: pd.DataFrame, model: str) -> pd.DataFrame:
    """Per horizon: 10th/90th percentile of log(actual / forecast) in the selection period."""
    d = sel_detail[sel_detail["model"] == model]
    e = np.log(np.maximum(d["rate"].to_numpy(), 1e-6) / d["forecast"].to_numpy())
    q = pd.DataFrame({"h": d["h"].to_numpy(), "e": e}).groupby("h")["e"]
    return pd.DataFrame(
        {"log_q10": q.quantile(config.INTERVAL[0]), "log_q90": q.quantile(config.INTERVAL[1])}
    )


def conformal_coverage(detail: pd.DataFrame, model: str, bands: pd.DataFrame) -> pd.DataFrame:
    d = detail[detail["model"] == model].join(bands, on="h")
    lo = d["forecast"] * np.exp(d["log_q10"])
    hi = d["forecast"] * np.exp(d["log_q90"])
    d = d.assign(covered_conformal=((d["rate"] >= lo) & (d["rate"] <= hi)).astype(float))
    return (
        d.groupby("h")
        .agg(
            coverage_model=("covered", "mean"),
            coverage_conformal=("covered_conformal", "mean"),
            n=("rate", "size"),
        )
        .reset_index()
    )


def main(out: Path = config.TABLES, figures: Path = config.FIGURES) -> dict:
    from src import plots

    panel, macro = backtest.load_inputs()
    sel_org = backtest.selection_origins(panel)
    test_org = backtest.test_origins(panel)

    # Step 1: macro form, selection period only.
    step1 = [MACRO_FORMS[n] for n in STEP1_ORDER]
    bt1 = backtest.only_period(backtest.run(panel, macro, step1, origin_list=sel_org), "selection")
    form = backtest.pick(backtest.summarise(bt1), STEP1_ORDER)
    # Step 2: intercept correction on that form.
    step2 = [with_ic(form, k) for k in IC_RHOS]
    bt2 = backtest.only_period(
        backtest.run(panel, macro, step2, origin_list=sel_org, include_baselines=False),
        "selection",
    )
    sel = pd.concat([bt1, bt2], ignore_index=True)
    sel_summary = backtest.summarise(sel)
    winner = backtest.pick(sel_summary, [form, f"{form}+IC085", f"{form}+IC1"])
    s4 = sel_summary[sel_summary["h"] == config.SELECTION_HORIZON].set_index("model")
    improvement = 1 - s4.loc[winner, "mae_rate_pct"] / s4.loc["A_k0", "mae_rate_pct"]
    adopted = bool(winner != "A_k0" and improvement >= ADOPT_IMPROVEMENT)
    winner_spec = next(s for s in step1 + step2 if s.name == winner)

    # Test period (seen before in A7): every candidate, same origins as A7.
    bt_test = backtest.only_period(
        backtest.run(panel, macro, step1 + step2, origin_list=test_org), "test"
    )
    summary = backtest.summarise(pd.concat([sel, bt_test], ignore_index=True))
    bands = conformal_bands(sel, winner)
    cov = conformal_coverage(bt_test, winner, bands)

    out.mkdir(parents=True, exist_ok=True)
    summary.to_csv(out / "round2_backtest.csv", index=False)
    bands.reset_index().to_csv(out / "round2_conformal_bands.csv", index=False)
    cov.to_csv(out / "round2_test_coverage.csv", index=False)

    fitted = satellite.fit(panel, macro, winner_spec)
    coefs = fitted.result.irr_table(list(winner_spec.macro))
    info = {
        "macro_form": form,
        "winner": winner,
        "adopted_for_scenarios": adopted,
        "improvement_vs_A_k0_selection_h4": round(float(improvement), 4),
        "scenario_spec": asdict(winner_spec if adopted else MACRO_FORMS["A_k0"]),
        "intercept_correction_at_start": (
            fitted.ic.round(4).to_dict() if fitted.ic is not None else None
        ),
        "coefficients_winner": coefs.reset_index(names="term").to_dict(orient="records"),
    }
    (out / "round2_selection.json").write_text(json.dumps(info, indent=2, default=float))
    plots.round2_mae(summary, winner, figures / "round2_backtest_mae.png")
    log.info("Round 2: winner %s, adopted %s (%.1f %%)", winner, adopted, 100 * improvement)
    return info


# --------------------------------------------------------------------------------------
# After the scenarios: round 1 vs adopted model, and the A10 watchlist
# --------------------------------------------------------------------------------------
def simulate_both(
    panel: pd.DataFrame, macro: pd.DataFrame, spec: satellite.Spec, tables: Path
) -> tuple[pd.DataFrame, dict[str, np.ndarray]]:
    """Baseline and adverse simulated annualised rates for `spec` (same paths as scenarios)."""
    rng = np.random.default_rng(config.SEED)
    fitted = satellite.fit(panel, macro, spec)
    start = pd.Period(panel["quarter"].max(), "Q")
    rows = scenarios.future_rows(
        build_panel.load("panel_quarterly"), start, config.SCENARIO_HORIZON
    )
    paths = pd.read_csv(tables / "scenario_macro_paths.csv")
    sims = {}
    for name in ("baseline", "adverse"):
        m = paths[paths["scenario"] == name].set_index("quarter")
        sims[name] = scenarios.simulate_paths(fitted, rows, m, config.N_SIM, rng)
    return rows, sims


def total_rate(rows: pd.DataFrame, rates: np.ndarray) -> pd.DataFrame:
    """Rolling four-quarter rate over the nine industries (simulated quarters only)."""
    q = rows["quarter"].to_numpy()
    firms = rows["firms"].to_numpy(dtype=float)
    quarters = sorted(set(q))
    counts = np.stack([(rates[:, q == x] * firms[q == x] / 4).sum(1) for x in quarters], 1)
    denom = rows.groupby("quarter")["firms"].sum()
    recs = []
    for i in range(3, len(quarters)):
        r4 = counts[:, i - 3 : i + 1].sum(1) / denom[quarters[i]]
        recs.append(
            {
                "quarter": quarters[i],
                "p10": float(np.quantile(r4, 0.1)),
                "p50": float(np.median(r4)),
                "p90": float(np.quantile(r4, 0.9)),
            }
        )
    return pd.DataFrame(recs)


def watchlist_additional(rows: pd.DataFrame, sims: dict[str, np.ndarray]) -> pd.DataFrame:
    """A10 rule: rank by the additional rate (adverse - baseline) in the worst window."""
    diff = sims["adverse"] - sims["baseline"]
    recs = []
    for s in config.MODEL_SECTORS:
        idx = np.flatnonzero(rows["sector"].to_numpy() == s)
        best = None
        for w in range(len(idx) - 3):
            avg = diff[:, idx[w : w + 4]].mean(axis=1)
            med = float(np.median(avg))
            if best is None or med > best["add_p50"]:
                best = {
                    "sector": s,
                    "window_start": rows["quarter"].to_numpy()[idx[w]],
                    "window_end": rows["quarter"].to_numpy()[idx[w + 3]],
                    "add_p50": med,
                    "add_p10": float(np.quantile(avg, 0.1)),
                    "add_p90": float(np.quantile(avg, 0.9)),
                    "firms": float(rows["firms"].to_numpy()[idx[0]]),
                }
        recs.append(best)
    w = pd.DataFrame(recs)
    avg = float(np.average(w["add_p50"], weights=w["firms"]))
    w["firm_weighted_avg_add"] = avg
    w["multiple_of_avg"] = w["add_p50"] / avg
    w["extra_bankruptcies_per_year"] = w["add_p50"] * w["firms"]
    w["share_of_extra"] = w["extra_bankruptcies_per_year"] / w["extra_bankruptcies_per_year"].sum()
    w["watchlist"] = (w["multiple_of_avg"] >= WATCH_MULTIPLE) & (w["add_p10"] > 0)
    return w.sort_values("add_p50", ascending=False).reset_index(drop=True)


def compare(out: Path = config.TABLES) -> None:
    panel, macro = backtest.load_inputs()
    info = json.loads((out / "round2_selection.json").read_text())
    used = spec_from_json(info["scenario_spec"])
    specs = {"A_k0": MACRO_FORMS["A_k0"], used.name: used}
    totals = []
    for name, spec in specs.items():
        rows, sims = simulate_both(panel, macro, spec, out)
        for scen, rates in sims.items():
            t = total_rate(rows, rates)
            t["scenario"], t["model"] = scen, name
            totals.append(t)
        if name == used.name:
            watchlist_additional(rows, sims).to_csv(out / "round2_watchlist.csv", index=False)
    pd.concat(totals, ignore_index=True).to_csv(out / "round2_scenario_total.csv", index=False)
    log.info("Round-2 comparison written (scenario model %s)", used.name)
