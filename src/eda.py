"""Exploratory analysis: figures in reports/figures/, tables in reports/tables/.

EDA does not change the pre-registered model choices (docs/decisions.md).
"""

from __future__ import annotations

import logging
from pathlib import Path

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from src import build_panel, config, plots

log = logging.getLogger(__name__)
MAX_LAG = 6


def annual_rates(q: pd.DataFrame) -> pd.DataFrame:
    """Annual rate per sector x year: bankruptcies in the year / FDB stock previous November."""
    q = q.assign(year=q["quarter"].str[:4].astype(int))
    full = q.groupby(["sector", "year"]).filter(lambda g: len(g) == 4)
    out = full.groupby(["sector", "year"]).agg(count=("count", "sum"), firms=("firms", "first"))
    out["rate"] = out["count"] / out["firms"]
    return out.reset_index()


def fig_heatmap(q: pd.DataFrame, folder: Path) -> Path:
    a = annual_rates(q[q["sector"].isin(config.MODEL_SECTORS)])
    wide = a.pivot(index="sector", columns="year", values="rate") * 100
    order = wide.mean(axis=1).sort_values(ascending=False).index
    wide = wide.loc[order]
    fig, ax = plt.subplots(figsize=(11, 4.6))
    im = ax.imshow(wide.to_numpy(), aspect="auto", cmap=plots.SEQUENTIAL_CMAP)
    ax.set_xticks(range(wide.shape[1]), wide.columns, rotation=0, fontsize=8)
    ax.set_yticks(range(wide.shape[0]), [config.SECTORS[s].split(" (")[0] for s in wide.index])
    ax.grid(False)
    for i in range(wide.shape[0]):
        for j in range(wide.shape[1]):
            v = wide.iat[i, j]
            ax.text(
                j,
                i,
                f"{v:.1f}",
                ha="center",
                va="center",
                fontsize=7,
                color="white" if v > np.nanpercentile(wide, 70) else plots.INK,
            )
    top = wide.mean(axis=1).idxmax()
    ax.set_title(
        f"{config.SECTORS[top].split(' (')[0]} has the highest bankruptcy rate in every year"
        if (wide.idxmax(axis=0) == top).all()
        else "Bankruptcy rates differ more between sectors than over time"
    )
    fig.colorbar(im, ax=ax, label="Bankruptcies per 100 firms per year", shrink=0.8)
    plots.source_note(fig, plots.SOURCE_TVA)
    return plots.save(fig, "eda_heatmap_rate_sector_year", folder)


def fig_sector_lines(q: pd.DataFrame, folder: Path) -> Path:
    q = q[q["sector"].isin(config.MODEL_SECTORS)].copy()
    q["date"] = pd.PeriodIndex(q["quarter"], freq="Q").to_timestamp(how="end")
    fig, axes = plt.subplots(3, 3, figsize=(12, 8), sharex=True)
    for ax, sector in zip(axes.flat, config.MODEL_SECTORS, strict=True):
        g = q[q["sector"] == sector]
        plots.shade_episodes(ax)
        ax.plot(g["date"], 100 * g["rate"], color=plots.BASELINE, lw=1.2, alpha=0.5)
        ax.plot(g["date"], 100 * g["rate_r4"], color=plots.BASELINE, lw=2)
        ax.set_title(config.SECTORS[sector].split(" (")[0], fontsize=10)
        ax.set_ylim(bottom=0)
        ax.xaxis.set_major_locator(mdates.YearLocator(5))
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    a = annual_rates(q)
    peak_year = a.loc[a.groupby("sector")["rate"].idxmax()].set_index("sector")["year"]
    recent = [
        config.SECTORS[s].split(" (")[0].split(",")[0]
        for s in peak_year.index
        if peak_year[s] >= 2023
    ]
    fig.suptitle(
        f"{len(recent)} of 9 sectors had their highest annual rate since 2009 in 2023 or later",
        x=0.01,
        ha="left",
        fontweight="bold",
    )
    fig.text(
        0.01,
        0.94,
        "Bankruptcies per 100 firms, annualised. Thin line: quarter; thick: rolling 4 quarters. "
        "Grey: 2009 crisis and pandemic support (2020Q2-2021Q4); hatched: inflation and rate "
        "hikes (2022-2024).",
        fontsize=9,
        color=plots.INK_2,
    )
    fig.tight_layout(rect=(0, 0, 1, 0.93))
    plots.source_note(fig, plots.SOURCE_TVA)
    return plots.save(fig, "eda_sector_rates_over_time", folder)


def yoy_log_rate(q: pd.DataFrame) -> pd.DataFrame:
    q = q.sort_values(["sector", "quarter"]).copy()
    q["dlog_rate"] = q.groupby("sector")["rate"].transform(lambda s: np.log(s) - np.log(s.shift(4)))
    return q


def cross_correlations(q: pd.DataFrame, macro: pd.DataFrame) -> pd.DataFrame:
    """Correlation between y/y log change in the rate and macro drivers lagged 0..6 quarters.

    Using y/y changes on both sides avoids spurious correlation between trending levels.
    Pandemic-support quarters are excluded.
    """
    q = yoy_log_rate(q[q["sector"].isin(config.MODEL_SECTORS)])
    covid = (q["quarter"] >= config.COVID_SUPPORT[0]) & (q["quarter"] <= config.COVID_SUPPORT[1])
    q = q[~covid]
    m = macro.copy()
    m.index = pd.PeriodIndex(m.index, freq="Q")
    rows = []
    for var in config.MACRO_VARS:
        for lag in range(MAX_LAG + 1):
            shifted = m[var].copy()
            shifted.index = (shifted.index + lag).astype(str)
            for sector, g in q.groupby("sector"):
                x = shifted.reindex(g["quarter"]).to_numpy()
                y = g["dlog_rate"].to_numpy()
                ok = ~np.isnan(x) & ~np.isnan(y)
                rows.append(
                    {
                        "variable": var,
                        "lag": lag,
                        "sector": sector,
                        "n": int(ok.sum()),
                        "corr": float(np.corrcoef(x[ok], y[ok])[0, 1]),
                    }
                )
    return pd.DataFrame(rows)


def fig_crosscorr(cc: pd.DataFrame, folder: Path) -> Path:
    fig, axes = plt.subplots(1, 3, figsize=(12, 3.8), sharey=True)
    labels = {
        "d_unemp": "Unemployment change (pp, y/y)",
        "gdp_yoy": "GDP growth (%, y/y)",
        "d_policy": "Policy-rate change (pp, y/y)",
    }
    for ax, var in zip(axes, config.MACRO_VARS, strict=True):
        g = cc[cc["variable"] == var]
        for _, s in g.groupby("sector"):
            ax.plot(s["lag"], s["corr"], color=plots.GRID, lw=1.2)
        med = g.groupby("lag")["corr"].median()
        ax.plot(med.index, med.to_numpy(), color=plots.BASELINE, lw=2.2, marker="o", ms=4)
        ax.axhline(0, color=plots.INK_2, lw=0.8)
        ax.set_title(labels[var], fontsize=10)
        ax.set_xlabel("Lag (quarters)")
    axes[0].set_ylabel("Correlation with y/y change in log rate")
    best = cc.groupby(["variable", "lag"])["corr"].median()
    v, k = best.abs().idxmax()
    fig.suptitle(
        f"The strongest median co-movement is with {labels[v].split(' (')[0].lower()} "
        f"at lag {k} (median r = {best[(v, k)]:.2f})",
        x=0.01,
        ha="left",
        fontweight="bold",
    )
    fig.text(
        0.01,
        0.90,
        "Grey: individual sectors; blue: median. Pandemic quarters excluded.",
        fontsize=9,
        color=plots.INK_2,
    )
    fig.tight_layout(rect=(0, 0, 1, 0.88))
    plots.source_note(fig, plots.SOURCE_MACRO)
    return plots.save(fig, "eda_cross_correlations", folder)


def fig_scatter(q: pd.DataFrame, macro: pd.DataFrame, folder: Path, lag: int = 0) -> Path:
    q = yoy_log_rate(q[q["sector"].isin(config.MODEL_SECTORS)])
    m = macro["d_unemp"].copy()
    m.index = (pd.PeriodIndex(m.index, freq="Q") + lag).astype(str)
    q["x"] = m.reindex(q["quarter"]).to_numpy()
    covid = (q["quarter"] >= config.COVID_SUPPORT[0]) & (q["quarter"] <= config.COVID_SUPPORT[1])
    fig, axes = plt.subplots(3, 3, figsize=(11, 9), sharex=True, sharey=True)
    for ax, sector in zip(axes.flat, config.MODEL_SECTORS, strict=True):
        g = q[(q["sector"] == sector)].dropna(subset=["x", "dlog_rate"])
        c = covid[g.index]
        ax.scatter(
            g.loc[~c, "x"],
            100 * g.loc[~c, "dlog_rate"],
            s=14,
            color=plots.BASELINE,
            alpha=0.7,
            edgecolor=plots.SURFACE,
            linewidth=0.5,
        )
        ax.scatter(
            g.loc[c, "x"],
            100 * g.loc[c, "dlog_rate"],
            s=14,
            facecolor="none",
            edgecolor=plots.INK_2,
            linewidth=0.8,
            label="Pandemic support",
        )
        ax.axhline(0, color=plots.INK_2, lw=0.6)
        ax.axvline(0, color=plots.INK_2, lw=0.6)
        ax.set_title(config.SECTORS[sector].split(" (")[0], fontsize=10)
    axes[0, 0].legend(loc="upper left", fontsize=8)
    for ax in axes[-1]:
        ax.set_xlabel(f"Unemployment change, pp y/y (lag {lag})")
    for ax in axes[:, 0]:
        ax.set_ylabel("Rate change, % y/y (log)")
    ok = q.dropna(subset=["x", "dlog_rate"])
    ok = ok[~covid[ok.index]]
    r = ok.groupby("sector").apply(lambda g: np.corrcoef(g["x"], g["dlog_rate"])[0, 1]).median()
    fig.suptitle(
        f"Same-quarter unemployment changes and rate changes co-move weakly (median r = {r:.2f})",
        x=0.01,
        ha="left",
        fontweight="bold",
    )
    fig.tight_layout(rect=(0, 0, 1, 0.96))
    plots.source_note(fig, plots.SOURCE_MACRO)
    return plots.save(fig, "eda_scatter_rate_vs_unemployment", folder)


def seasonality(monthly: pd.DataFrame) -> pd.DataFrame:
    """Average share of the year's bankruptcies by calendar month (full years, all sectors)."""
    m = monthly.groupby("month")["count"].sum().reset_index()
    m["year"] = m["month"].str[:4].astype(int)
    m["mon"] = m["month"].str[5:].astype(int)
    full = m.groupby("year").filter(lambda g: len(g) == 12)
    full = full.assign(share=full["count"] / full.groupby("year")["count"].transform("sum"))
    return full.groupby("mon")["share"].agg(["mean", "std"]).reset_index()


def fig_seasonality(season: pd.DataFrame, folder: Path) -> Path:
    fig, ax = plt.subplots(figsize=(8, 3.6))
    ax.bar(season["mon"], 100 * season["mean"], color=plots.BASELINE, width=0.7)
    ax.axhline(100 / 12, color=plots.INK_2, lw=0.8, ls="--")
    ax.text(12.45, 100 / 12, "even\nspread", fontsize=8, color=plots.INK_2, va="center")
    ax.set_xticks(
        range(1, 13),
        ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"],
    )
    ax.set_ylabel("% of the year's bankruptcies")
    low = season.loc[season["mean"].idxmin(), "mon"]
    ax.set_title(
        f"Bankruptcies dip in {pd.Timestamp(2000, int(low), 1):%B}: "
        "quarterly seasonal terms are needed"
    )
    plots.source_note(fig, plots.SOURCE_TVA)
    return plots.save(fig, "eda_seasonality", folder)


def fig_unspecified(monthly: pd.DataFrame, folder: Path) -> Path:
    m = monthly.assign(year=monthly["month"].str[:4])
    share = (
        m[m["sector"] == "UNS"].groupby("year")["count"].sum() / m.groupby("year")["count"].sum()
    )
    fig, ax = plt.subplots(figsize=(8, 3.4))
    ax.plot(share.index.astype(int), 100 * share.to_numpy(), color=plots.BASELINE, marker="o", ms=4)
    ax.set_ylim(bottom=0)
    ax.set_ylabel("% of all bankruptcies")
    ax.set_title(
        f"Unspecified industry: {100 * share.min():.0f}-{100 * share.max():.0f} % "
        "of bankruptcies per year (not modelled)"
    )
    plots.source_note(fig, plots.SOURCE_TVA)
    return plots.save(fig, "eda_unspecified_share", folder)


def main(out: Path | None = None) -> None:
    plots.apply_style()
    figures = (out / "figures") if out else config.FIGURES
    tables = (out / "tables") if out else config.TABLES
    tables.mkdir(parents=True, exist_ok=True)
    folder = out if out else config.PROCESSED
    q = build_panel.load("panel_quarterly", folder)
    monthly = build_panel.load("panel_monthly", folder)
    macro = build_panel.load("macro_quarterly", folder).set_index("quarter")

    fig_heatmap(q, figures)
    fig_sector_lines(q, figures)
    cc = cross_correlations(q, macro)
    cc.to_csv(tables / "eda_cross_correlations.csv", index=False)
    fig_crosscorr(cc, figures)
    fig_scatter(q, macro, figures)
    season = seasonality(monthly)
    season.to_csv(tables / "eda_seasonality.csv", index=False)
    fig_seasonality(season, figures)
    fig_unspecified(monthly, figures)
    annual_rates(q).to_csv(tables / "annual_rates.csv", index=False)
    log.info("EDA figures written to %s", figures)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
