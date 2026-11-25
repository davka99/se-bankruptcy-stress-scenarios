"""Real-time variant of the backtest: macro drivers for the targets come from the KI forecast
vintage that was published when the forecast would have been made, not from outcomes.

The forecast date for origin T is taken as 15 days after the end of quarter T (bankruptcy
statistics for a month are published around the 12th of the following month). The model is
still trained on today's (revised) macro history; only the target-period drivers are real
time. KI vintages with all three tables exist from December 2017.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pandas as pd

from src import backtest, config, jsonstat
from src.fetch.common import latest_snapshot

log = logging.getLogger(__name__)


def _q(index) -> pd.PeriodIndex:
    return pd.PeriodIndex([str(i) for i in index], freq="Q")


def vintage_levels(folder: Path, vintage: str) -> pd.DataFrame | None:
    """Quarterly unemp, gdp_level and policy_rate as published in one KI vintage."""
    f_u = folder / f"vintage_{vintage}_unemployment_q.json"
    f_u_old = folder / f"vintage_{vintage}_unemployment_q_old.json"
    f_g = folder / f"vintage_{vintage}_gdp_q.json"
    f_r = folder / f"vintage_{vintage}_policy_rate_m.json"
    if not (f_g.exists() and f_r.exists() and (f_u.exists() or f_u_old.exists())):
        return None

    def read(path: Path) -> pd.DataFrame:
        # older vintages code the period as 0, 1, 2, ...; the labels hold the dates
        df = jsonstat.read(path, labels=True)
        df["period"] = df["period_label"]
        return df

    if f_u.exists():
        u = read(f_u)
        u = u[u["variabel"].str.contains("Arali")].set_index("period")["value"]
    else:
        u = read(f_u_old)
        # codes changed over time (e.g. F2104Aal1574 -> F2104Aali1574s); use the labels
        u = u[u["enhet"] == "NS"].pivot(index="period", columns="variabel_label", values="value")
        u = 100 * u["Arbetslösa"] / u["Arbetskraften"]
    g = read(f_g)
    g = g[(g["variabel"] == "F0905Nbnpmpfs") & (g["enhet"] == "FL")].set_index("period")["value"]
    r = read(f_r)
    r = r[r["variabel"] == "F0604Repo"].set_index("period")["value"].dropna()
    r.index = pd.PeriodIndex(r.index.str.replace("M", "-"), freq="M")
    r = r.groupby(r.index.asfreq("Q")).mean()
    levels = pd.DataFrame(
        {
            "unemp": pd.Series(u.to_numpy(), index=_q(u.index)),
            "gdp_level": pd.Series(g.to_numpy(), index=_q(g.index)),
            "policy_rate": r,
        }
    ).sort_index()
    return levels


def drivers(levels: pd.DataFrame) -> pd.DataFrame:
    out = levels.copy()
    out["d_unemp"] = out["unemp"] - out["unemp"].shift(4)
    out["gdp_yoy"] = 100 * (out["gdp_level"] / out["gdp_level"].shift(4) - 1)
    out["d_policy"] = out["policy_rate"] - out["policy_rate"].shift(4)
    out.index = out.index.astype(str)
    return out


def vintage_for_origin(origin: pd.Period, vintages: list[str]) -> str | None:
    decision_date = origin.end_time.normalize() + pd.Timedelta(days=15)
    eligible = [v for v in vintages if pd.Timestamp(v) <= decision_date]
    return max(eligible) if eligible else None


def main(out: Path = config.TABLES) -> pd.DataFrame:
    folder = latest_snapshot("ki")
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    vintages = sorted(manifest["vintages"])
    panel, macro = backtest.load_inputs()
    selected = json.loads((out / "model_selection.json").read_text())["selected"]
    spec = next(s for s in backtest.all_specs() if s.name == selected)

    cache: dict[str, pd.DataFrame | None] = {}
    usable = []
    for origin in backtest.origins(panel):
        v = vintage_for_origin(origin, vintages)
        if v is None:
            continue
        if v not in cache:
            levels = vintage_levels(folder, v)
            cache[v] = drivers(levels) if levels is not None else None
        if cache[v] is not None:
            usable.append((origin, v))

    def macro_for_origin(origin: pd.Period) -> pd.DataFrame:
        v = dict(usable)[origin]
        rt = cache[v]
        # actual history up to the origin, the vintage's numbers after it
        hist = macro[_q(macro.index) <= origin]
        fut = rt[_q(rt.index) > origin]
        return pd.concat([hist, fut])[list(config.MACRO_VARS)]

    origin_list = [o for o, _ in usable]
    rt_bt = backtest.run(
        panel,
        macro,
        [spec],
        origin_list=origin_list,
        include_baselines=True,
        macro_for_origin=macro_for_origin,
    )
    rt_bt["vintage"] = rt_bt["origin"].map({str(o): v for o, v in usable})
    rt_bt.to_csv(out / "backtest_realtime_detail.csv", index=False)
    summary = backtest.summarise(rt_bt)
    summary["model"] = summary["model"].replace({selected: f"satellite ({selected}), real-time"})
    summary.to_csv(out / "backtest_realtime.csv", index=False)
    log.info(
        "Real-time backtest: %d origins (%s to %s)",
        len(origin_list),
        origin_list[0] if origin_list else None,
        origin_list[-1] if origin_list else None,
    )
    return summary


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    s = main()
    print(s.round(3).to_string())
