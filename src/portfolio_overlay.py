"""Bank perspective on a **synthetic** SME portfolio: scenario PDs, ECL and a PD overlay.

Everything about the portfolio (loans, exposures, through-the-cycle PDs, LGD) is synthetic
and labelled as such. The PD overlay itself depends only on real data: it is the ratio of
the scenario bankruptcy rate to the sector's historical mean rate.

Simplifications versus a real IFRS 9 model: no stage transfers, no significant-increase-in-
credit-risk (SICR) test, no lifetime PD, a single 12-month horizon, and bankruptcy used as a
relative proxy for default.
"""

from __future__ import annotations

import logging
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from src import config, plots

log = logging.getLogger(__name__)

BASE_TTC_PD = 0.02  # synthetic: portfolio-average through-the-cycle PD


def synthetic_portfolio(
    hist_mean: pd.Series, firm_share: pd.Series, n: int = config.N_LOANS, seed: int = config.SEED
) -> pd.DataFrame:
    """synthetic loans: sector mix proportional to the real firm counts, lognormal EAD,
    TTC-PD = 2 % scaled by each sector's historical bankruptcy rate relative to the mean."""
    rng = np.random.default_rng(seed)
    sectors = list(firm_share.index)
    mix = firm_share / firm_share.sum()
    sector = rng.choice(sectors, size=n, p=mix.to_numpy())
    ead = np.round(rng.lognormal(mean=np.log(750_000), sigma=0.9, size=n), -3)
    rel = hist_mean / np.average(hist_mean, weights=mix.reindex(hist_mean.index))
    ttc = np.clip(BASE_TTC_PD * rel, 0.002, 0.2)
    return pd.DataFrame(
        {
            "loan_id": np.arange(1, n + 1),
            "sector": sector,
            "ead_sek": ead,
            "ttc_pd": ttc.reindex(sector).to_numpy(),
            "synthetic": True,
        }
    )


def ecl_by_sector(
    portfolio: pd.DataFrame,
    overlay: pd.DataFrame,
    lgd: float = config.LGD,
    weights: dict[str, float] = config.SCENARIO_WEIGHTS,
) -> pd.DataFrame:
    """12-month ECL = PD x LGD x EAD per scenario, and the probability-weighted ECL."""
    ratio = overlay.pivot(index="sector", columns="scenario", values="rate_first_year_p50")
    hist = overlay.groupby("sector")["hist_mean_rate"].first()
    rows = []
    for sector, g in portfolio.groupby("sector"):
        ead = g["ead_sek"].sum()
        ttc = float(g["ttc_pd"].iloc[0])
        row = {
            "sector": sector,
            "n_loans": len(g),
            "ead_sek": ead,
            "ttc_pd": ttc,
            "ecl_ttc_sek": ttc * lgd * ead,
        }
        for scenario in weights:
            pd_s = min(ttc * ratio.loc[sector, scenario] / hist[sector], 1.0)
            row[f"pd_{scenario}"] = pd_s
            row[f"ecl_{scenario}_sek"] = pd_s * lgd * ead
        row["ecl_weighted_sek"] = sum(w * row[f"ecl_{s}_sek"] for s, w in weights.items())
        rows.append(row)
    out = pd.DataFrame(rows)
    out["synthetic"] = True
    return out


def weight_sensitivity(ecl: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for w_adv in (0.1, 0.2, 0.3, 0.4, 0.5):
        total = ((1 - w_adv) * ecl["ecl_baseline_sek"] + w_adv * ecl["ecl_adverse_sek"]).sum()
        rows.append({"weight_adverse": w_adv, "ecl_weighted_sek": total, "synthetic": True})
    return pd.DataFrame(rows)


def fig_overlay(overlay: pd.DataFrame, folder: Path) -> Path:
    adv = overlay[overlay["scenario"] == "adverse"].set_index("sector")
    base = overlay[overlay["scenario"] == "baseline"].set_index("sector")
    order = adv["rate_worst_window_p50"].sub(adv["hist_mean_rate"]).sort_values().index
    fig, ax = plt.subplots(figsize=(9, 4.4))
    y = np.arange(len(order))
    ax.barh(
        y + 0.2,
        100 * base.loc[order, "overlay_first_year"],
        height=0.38,
        color=plots.BASELINE,
        label="Baseline, first year",
    )
    ax.barh(
        y - 0.2,
        100 * adv.loc[order, "overlay_first_year"],
        height=0.38,
        color=plots.ADVERSE,
        label="Adverse, first year",
    )
    ax.set_yticks(y, [config.SECTORS[s].split(" (")[0] for s in order])
    ax.axvline(0, color=plots.INK_2, lw=0.8)
    ax.set_xlabel("PD overlay: scenario rate vs historical mean rate, %")
    ax.grid(axis="x", color=plots.GRID)
    ax.grid(axis="y", visible=False)
    ax.legend(fontsize=8, loc="lower right")
    lo, hi = 100 * adv["overlay_first_year"].min(), 100 * adv["overlay_first_year"].max()
    ax.set_title(
        f"Adverse first-year overlay is +{lo:.0f} to +{hi:.0f} % in every sector; "
        "sectors sorted by pp increase"
    )
    plots.source_note(fig, plots.SOURCE_SCEN + " Overlay uses real data only.")
    return plots.save(fig, "pd_overlay_by_sector", folder)


def main(out: Path = config.TABLES, figures: Path = config.FIGURES) -> dict:
    from src import build_panel

    plots.apply_style()
    overlay = pd.read_csv(out / "scenario_rates_overlay.csv")
    hist = overlay.groupby("sector")["hist_mean_rate"].first()
    q = build_panel.load("panel_quarterly")
    latest = q[q["quarter"] == q["quarter"].max()].set_index("sector")["firms"]
    portfolio = synthetic_portfolio(hist, latest.reindex(config.MODEL_SECTORS))
    portfolio.to_csv(out / "synthetic_portfolio.csv", index=False)
    ecl = ecl_by_sector(portfolio, overlay)
    ecl.to_csv(out / "synthetic_ecl_by_sector.csv", index=False)
    weight_sensitivity(ecl).to_csv(out / "synthetic_ecl_weight_sensitivity.csv", index=False)
    fig_overlay(overlay, figures)
    totals = {c: float(ecl[c].sum()) for c in ecl.columns if c.startswith("ecl_")}
    log.info("synthetic ECL totals: %s", totals)
    return totals


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print(main())
