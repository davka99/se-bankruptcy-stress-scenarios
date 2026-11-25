"""Model monitoring: compare each new complete quarter with the model's previous forecast.

Status per sector (a simple traffic light, as in a bank's model-monitoring routine):
    green   outcome inside the 80 % interval
    yellow  outside once
    red     outside two quarters in a row -> trigger re-estimation / model review

The log starts with a backfill from the conditional backtest (one-quarter-ahead forecasts in
the test period, labelled `backfill`). From then on every pipeline run registers the
baseline forecast for the next quarter, and the monthly refresh evaluates it once the
quarter is complete (labelled `live`). Monthly updates within a quarter are not assessed.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pandas as pd

from src import config

log = logging.getLogger(__name__)

LOG_COLUMNS = [
    "quarter",
    "sector",
    "actual",
    "p10",
    "p50",
    "p90",
    "outside",
    "status",
    "issued",
    "source",
]


def status_sequence(outside: list[bool]) -> list[str]:
    out, prev = [], False
    for o in outside:
        out.append("red" if (o and prev) else "yellow" if o else "green")
        prev = o
    return out


def assign_status(log_df: pd.DataFrame) -> pd.DataFrame:
    log_df = log_df.sort_values(["sector", "quarter"]).copy()
    log_df["status"] = log_df.groupby("sector")["outside"].transform(
        lambda s: pd.Series(status_sequence(list(s.astype(bool))), index=s.index)
    )
    return log_df


def backfill(tables: Path) -> pd.DataFrame:
    selected = json.loads((tables / "model_selection.json").read_text())["selected"]
    bt = pd.read_csv(tables / "backtest_test_detail.csv", dtype={"quarter": str, "origin": str})
    bt = bt[(bt["model"] == selected) & (bt["h"] == 1)]
    out = pd.DataFrame(
        {
            "quarter": bt["quarter"],
            "sector": bt["sector"],
            "actual": bt["rate"],
            "p10": bt["p10"],
            "p50": bt["p50"],
            "p90": bt["p90"],
            "issued": bt["origin"],
            "source": "backfill (conditional backtest, h=1)",
        }
    )
    out["outside"] = (out["actual"] < out["p10"]) | (out["actual"] > out["p90"])
    return out


def main(out: Path = config.TABLES) -> pd.DataFrame:
    from src import build_panel

    panel = build_panel.load("panel_quarterly")
    latest_q = panel["quarter"].max()
    log_path = out / "monitoring_log.csv"
    reg_path = out / "forecast_register.csv"

    log_df = (
        pd.read_csv(log_path, dtype={"quarter": str, "issued": str})
        if log_path.exists()
        else backfill(out)
    )
    register = (
        pd.read_csv(reg_path, dtype={"quarter": str, "issued": str})
        if reg_path.exists()
        else pd.DataFrame(columns=["issued", "quarter", "sector", "p10", "p50", "p90"])
    )

    # Evaluate registered forecasts whose target quarter is now complete.
    actual = panel.set_index(["sector", "quarter"])["rate"]
    done = set(zip(log_df["sector"], log_df["quarter"], strict=True))
    new_rows = []
    for _, r in register.iterrows():
        key = (r["sector"], r["quarter"])
        if r["quarter"] <= latest_q and key not in done and key in actual.index:
            a = float(actual[key])
            new_rows.append(
                {
                    **r.to_dict(),
                    "actual": a,
                    "source": "live",
                    "outside": bool(a < r["p10"] or a > r["p90"]),
                }
            )
    if new_rows:
        log_df = pd.concat([log_df, pd.DataFrame(new_rows)], ignore_index=True)

    # Register the baseline forecast for the next quarter (once per issue quarter).
    paths = pd.read_csv(out / "scenario_paths.csv", dtype={"quarter": str})
    nxt = str(pd.Period(latest_q, "Q") + 1)
    if not ((register["issued"] == latest_q) & (register["quarter"] == nxt)).any():
        add = paths[(paths["scenario"] == "baseline") & (paths["quarter"] == nxt)]
        add = add[["quarter", "sector", "p10", "p50", "p90"]].assign(issued=latest_q)
        register = pd.concat([register, add], ignore_index=True)
    register.to_csv(reg_path, index=False)

    log_df = assign_status(log_df)[LOG_COLUMNS]
    log_df.to_csv(log_path, index=False)
    last = log_df[log_df["quarter"] == log_df["quarter"].max()]
    log.info("Monitoring %s: %s", log_df["quarter"].max(), last["status"].value_counts().to_dict())
    return log_df


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print(main().tail(18).to_string())
