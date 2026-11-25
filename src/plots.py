"""Shared figure style: one colour-blind-safe palette, conclusion titles, source notes."""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from src import config  # noqa: E402

# Validated with the dataviz palette checker (CVD and normal-vision separation).
BASELINE = "#2a78d6"  # neutral blue
ADVERSE = "#eb6834"  # orange
HIGHLIGHT = ["#1baf7a", "#6250d6", "#008300"]  # aqua, violet, green (direct-labelled)
INK = "#0b0b0b"
INK_2 = "#52514e"
GRID = "#e4e3df"
SURFACE = "#fcfcfb"
SEQUENTIAL_CMAP = "Blues"

EPISODES = [
    ("2009-01-01", "2009-12-31", "Financial crisis"),
    ("2020-04-01", "2021-12-31", "Pandemic support"),
    ("2022-01-01", "2024-12-31", "Inflation and rate hikes"),
]


def shade_episodes(ax) -> None:
    """Grey fill for the crisis and pandemic episodes, hatching for 2022-2024."""
    import pandas as pd

    for start, end, name in EPISODES:
        if name.startswith("Inflation"):
            ax.axvspan(
                pd.Timestamp(start),
                pd.Timestamp(end),
                facecolor="none",
                edgecolor=GRID,
                hatch="////",
                lw=0,
            )
        else:
            ax.axvspan(pd.Timestamp(start), pd.Timestamp(end), color=GRID, alpha=0.8, lw=0)


def episode_handles() -> list:
    """Legend entries for the shaded episodes drawn by shade_episodes."""
    from matplotlib.patches import Patch

    return [
        Patch(
            facecolor=GRID,
            alpha=0.8,
            lw=0,
            label="Financial crisis 2009, pandemic support 2020–21",
        ),
        Patch(
            facecolor="none",
            edgecolor=GRID,
            hatch="////",
            lw=0,
            label="Inflation and rate hikes 2022–24",
        ),
    ]


def apply_style() -> None:
    plt.rcParams.update(
        {
            "figure.facecolor": SURFACE,
            "axes.facecolor": SURFACE,
            "axes.edgecolor": INK_2,
            "axes.labelcolor": INK_2,
            "axes.titlesize": 12,
            "axes.titleweight": "bold",
            "axes.titlelocation": "left",
            "axes.spines.top": False,
            "axes.spines.right": False,
            "axes.grid": True,
            "axes.grid.axis": "y",
            "grid.color": GRID,
            "grid.linewidth": 0.8,
            "xtick.color": INK_2,
            "ytick.color": INK_2,
            "lines.linewidth": 2.0,
            "font.size": 10,
            "legend.frameon": False,
            "savefig.dpi": 150,
            "savefig.bbox": "tight",
        }
    )


def source_note(fig, text: str) -> None:
    fig.text(0.01, -0.02, f"Source: {text}", ha="left", va="top", fontsize=8, color=INK_2)


def save(fig, name: str, folder: Path = config.FIGURES) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{name}.png"
    fig.savefig(path)
    plt.close(fig)
    return path


SOURCE_TVA = "Tillväxtanalys (bankruptcies), SCB FDB (enterprises); own calculations."
SOURCE_MACRO = "Tillväxtanalys, SCB (AKU, national accounts), Riksbank; own calculations."
SOURCE_SCEN = (
    "Tillväxtanalys, SCB, Riksbank, Konjunkturinstitutet (baseline), EBA/ESRB 2025 "
    "stress test (adverse); own calculations."
)


def round2_mae(summary, winner: str, path: Path) -> Path:
    """Round 2: firm-weighted MAE at h = 4 per candidate, selection vs test (seen) period."""
    import numpy as np

    apply_style()
    s = summary[summary["h"] == config.SELECTION_HORIZON]
    models = s[s["period"] == "selection"].sort_values("mae_rate_pct")["model"].tolist()
    fig, ax = plt.subplots(figsize=(8.5, 4.2))
    y = np.arange(len(models))
    hgt = 0.38
    for j, (period, colour, label) in enumerate(
        (
            ("selection", BASELINE, "Selection period (targets ≤ 2022Q4)"),
            ("test", ADVERSE, "Test period 2023–2026 (already seen in A7)"),
        )
    ):
        vals = s[s["period"] == period].set_index("model").reindex(models)["mae_rate_pct"]
        ax.barh(y + (hgt / 2 if j == 0 else -hgt / 2), vals, height=hgt, color=colour, label=label)
        for yi, v in zip(y, vals, strict=True):
            if np.isfinite(v):
                ax.text(
                    v + 0.002,
                    yi + (hgt / 2 if j == 0 else -hgt / 2),
                    f"{v:.3f}",
                    va="center",
                    fontsize=8,
                    color=INK,
                )
    labels = [f"{m}  (selected)" if m == winner else m for m in models]
    ax.set_yticks(y, labels)
    ax.invert_yaxis()
    ax.grid(axis="y", visible=False)
    ax.grid(axis="x", color=GRID)
    ax.set_xlabel("Firm-weighted MAE of the annual bankruptcy rate, h = 4 (pp)")
    ax.set_title("Round 2: which model forecasts a year ahead best?")
    ax.legend(loc="lower right", fontsize=8.5)
    source_note(fig, SOURCE_TVA)
    fig.savefig(path)
    plt.close(fig)
    return path
