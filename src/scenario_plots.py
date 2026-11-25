"""Scenario figures: hero image, sector fan charts and macro paths."""

from __future__ import annotations

from pathlib import Path

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from src import config, plots

HERO_SECTORS = ["HOR", "CON", "TRD"]
HERO_STYLES = ["-", "-", (0, (5, 2))]  # trade dashed: it runs on top of construction


def _dates(quarters) -> pd.DatetimeIndex:
    return pd.PeriodIndex(pd.Series(quarters).astype(str), freq="Q").to_timestamp(how="end")


def short(sector: str) -> str:
    return config.SECTORS[sector].split(" (")[0]


def fig_hero(panel: pd.DataFrame, agg: pd.DataFrame, start: pd.Period, folder: Path) -> Path:
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13, 4.6), gridspec_kw={"width_ratios": [1.4, 1]})
    labels = []
    for color, ls, s in zip(plots.HIGHLIGHT, HERO_STYLES, HERO_SECTORS, strict=True):
        g = panel[panel["sector"] == s].dropna(subset=["rate_r4"])
        d = _dates(g["quarter"])
        ax1.plot(d, 100 * g["rate_r4"], color=color, lw=2, ls=ls)
        labels.append((d[-1], 100 * g["rate_r4"].iloc[-1], short(s)))
    plots.shade_episodes(ax1)
    ax1.legend(
        handles=plots.episode_handles(),
        loc="lower center",
        fontsize=8,
        frameon=False,
        handlelength=1.6,
        borderaxespad=0.2,
    )
    ax1.set_ylim(bottom=0)
    place_labels(ax1, labels, min_gap=0.12)
    ax1.set_xlim(right=labels[0][0] + pd.Timedelta(days=4 * 365))
    ax1.set_ylabel("Bankruptcies per 100 firms, rolling 4 quarters")
    ax1.set_title("History: the three highest-rate sectors", fontsize=10)
    ax1.xaxis.set_major_locator(mdates.YearLocator(3))
    ax1.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))

    hist = agg[agg["scenario"] == "history"]
    ax2.plot(_dates(hist["quarter"]), 100 * hist["p50"], color=plots.INK_2, lw=2)
    labels = []
    for name, color in (("baseline", plots.BASELINE), ("adverse", plots.ADVERSE)):
        g = agg[agg["scenario"] == name]
        d = _dates(g["quarter"])
        ax2.fill_between(d, 100 * g["p10"], 100 * g["p90"], color=color, alpha=0.18, lw=0)
        ax2.plot(d, 100 * g["p50"], color=color, lw=2)
        labels.append((d[-1], 100 * g["p50"].iloc[-1], name.capitalize()))
    place_labels(ax2, labels, min_gap=0.05)
    ax2.axvline(_dates([str(start)])[0], color=plots.INK_2, lw=0.8, ls="--")
    ax2.set_ylim(bottom=0)
    ax2.set_title("All modelled sectors, rolling 4 quarters (median, 80 % band)", fontsize=10)
    ax2.set_ylabel("Bankruptcies per 100 firms")
    ax2.xaxis.set_major_locator(mdates.YearLocator(4))
    ax2.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    ax2.set_xlim(right=_dates([str(start + config.SCENARIO_HORIZON)])[0] + pd.Timedelta(days=500))
    adv = agg[agg["scenario"] == "adverse"]
    base = agg[agg["scenario"] == "baseline"]
    peak_row = adv.loc[adv["p50"].idxmax()]
    # Compare with the baseline in the same quarter, not with the baseline's own maximum.
    base_same_q = base.loc[base["quarter"] == peak_row["quarter"], "p50"].iloc[0]
    fig.suptitle(
        f"Adverse scenario: the 12-month bankruptcy rate peaks at {100 * peak_row['p50']:.2f} "
        f"per 100 firms in {peak_row['quarter']}, vs {100 * base_same_q:.2f} in the baseline",
        x=0.01,
        ha="left",
        fontweight="bold",
    )
    fig.tight_layout(rect=(0, 0, 1, 0.93))
    plots.source_note(
        fig, plots.SOURCE_SCEN + " Intervals understate uncertainty (see Validation)."
    )
    return plots.save(fig, "hero", folder)


def fig_fans(panel: pd.DataFrame, scen: pd.DataFrame, start: pd.Period, folder: Path) -> Path:
    fig, axes = plt.subplots(3, 3, figsize=(12, 8.5), sharex=True)
    for ax, s in zip(axes.flat, config.MODEL_SECTORS, strict=True):
        h = panel[(panel["sector"] == s) & (panel["quarter"] >= str(start - 16))]
        ax.plot(_dates(h["quarter"]), 100 * h["rate"], color=plots.INK_2, lw=1.4)
        for name, color in (("baseline", plots.BASELINE), ("adverse", plots.ADVERSE)):
            g = scen[(scen["sector"] == s) & (scen["scenario"] == name)]
            d = _dates(g["quarter"])
            ax.fill_between(d, 100 * g["p10"], 100 * g["p90"], color=color, alpha=0.18, lw=0)
            ax.plot(d, 100 * g["p50"], color=color, lw=2, label=name.capitalize())
        ax.set_title(short(s), fontsize=10)
        ax.set_ylim(bottom=0)
        ax.xaxis.set_major_locator(mdates.YearLocator(2))
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    axes[0, 0].legend(fontsize=8, loc="lower left")
    fig.suptitle(
        "Annualised bankruptcy rate per 100 firms: history (grey), baseline and adverse",
        x=0.01,
        ha="left",
        fontweight="bold",
    )
    fig.text(
        0.01,
        0.945,
        "Median and 80 % band from 5,000 simulated paths (parameter and "
        "count uncertainty only; scenario uncertainty not included).",
        fontsize=9,
        color=plots.INK_2,
    )
    fig.tight_layout(rect=(0, 0, 1, 0.93))
    plots.source_note(fig, plots.SOURCE_SCEN)
    return plots.save(fig, "scenario_fans_by_sector", folder)


def fig_macro(macro_paths: pd.DataFrame, start: pd.Period, folder: Path) -> Path:
    fig, axes = plt.subplots(1, 3, figsize=(12, 3.6))
    spec = [
        ("unemp", "Unemployment rate, %"),
        ("gdp_yoy", "GDP growth, % y/y"),
        ("policy_rate", "Policy rate, %"),
    ]
    for ax, (col, title) in zip(axes, spec, strict=True):
        for name, color in (("baseline", plots.BASELINE), ("adverse", plots.ADVERSE)):
            g = macro_paths[macro_paths["scenario"] == name].dropna(subset=[col])
            g = g[g["quarter"] >= str(start - 8)]
            ax.plot(_dates(g["quarter"]), g[col], color=color, lw=2, label=name.capitalize())
        ax.axvline(_dates([str(start)])[0], color=plots.INK_2, lw=0.8, ls="--")
        ax.set_title(title, fontsize=10)
        ax.xaxis.set_major_locator(mdates.YearLocator(2))
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    axes[0].legend(fontsize=8)
    adv = macro_paths[macro_paths["scenario"] == "adverse"]["unemp"].max()
    fig.suptitle(
        f"Adverse scenario: unemployment rises to {adv:.1f} % (EBA shock applied to KI's baseline)",
        x=0.01,
        ha="left",
        fontweight="bold",
    )
    fig.tight_layout(rect=(0, 0, 1, 0.9))
    plots.source_note(
        fig,
        "SCB, Riksbank, Konjunkturinstitutet (baseline), EBA/ESRB 2025 "
        "stress test (shock size); own calculations.",
    )
    return plots.save(fig, "scenario_macro_paths", folder)


def aggregate(
    panel: pd.DataFrame, rows: pd.DataFrame, sims: dict[str, np.ndarray], start: pd.Period
) -> pd.DataFrame:
    """Rolling four-quarter rate over all modelled sectors: history and simulated quantiles.

    Each simulated path is preceded by the last three observed quarters so that the first
    forecast windows mix observed and simulated quarters, like a published 12-month figure.
    """
    hist = panel[panel["sector"].isin(config.MODEL_SECTORS)]
    h = hist.groupby("quarter").agg(count=("count", "sum"), firms=("firms", "sum"))
    h["r4"] = h["count"].rolling(4).sum() / h["firms"]
    out = [
        {"quarter": q, "scenario": "history", "p10": r, "p50": r, "p90": r}
        for q, r in h["r4"].dropna().items()
    ]
    quarters = list(rows["quarter"].unique())
    firms = rows["firms"].to_numpy()
    last3 = h["count"].iloc[-3:].to_numpy()
    for name, rates in sims.items():
        counts = rates * firms[None, :] / 4
        q_counts = np.column_stack(
            [counts[:, (rows["quarter"] == q).to_numpy()].sum(axis=1) for q in quarters]
        )
        full = np.column_stack([np.tile(last3, (q_counts.shape[0], 1)), q_counts])
        total_firms = firms[(rows["quarter"] == quarters[0]).to_numpy()].sum()
        for j, q in enumerate(quarters):
            r4 = full[:, j : j + 4].sum(axis=1) / total_firms
            out.append(
                {
                    "quarter": q,
                    "scenario": name,
                    "p10": np.quantile(r4, 0.1),
                    "p50": np.quantile(r4, 0.5),
                    "p90": np.quantile(r4, 0.9),
                }
            )
    return pd.DataFrame(out)


def place_labels(ax, items: list[tuple[pd.Timestamp, float, str]], min_gap: float) -> None:
    """Direct labels at line ends, nudged apart vertically so they never overlap."""
    items = sorted(items, key=lambda t: t[1])
    ys: list[float] = []
    for _, y, _ in items:
        ys.append(max(y, ys[-1] + min_gap) if ys else y)
    for (x, _, text), y in zip(items, ys, strict=True):
        ax.annotate(
            text,
            (x, y),
            xytext=(6, 0),
            textcoords="offset points",
            va="center",
            fontsize=9,
            color=plots.INK,
        )


def main(panel, scen, macro_paths, start, figures, agg=None) -> None:
    plots.apply_style()
    if agg is not None:
        fig_hero(panel, agg, start, figures)
    fig_fans(panel, scen, start, figures)
    fig_macro(macro_paths, start, figures)
