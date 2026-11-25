"""Build the monthly and quarterly sector panels from the committed raw snapshots.

Outputs (data/processed/):
    panel_monthly    sector x month: bankruptcies
    panel_quarterly  sector x quarter: bankruptcies, firms (FDB, November of previous year),
                     annualised rate, denominator variants, macro drivers, pandemic dummy
    macro_quarterly  quarter: unemployment, GDP, policy rate and their y/y changes
Each table is written as CSV (readable diffs) and as Parquet when pyarrow is available.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pandas as pd

from src import config, jsonstat
from src.fetch.common import latest_snapshot

log = logging.getLogger(__name__)

PRELIMINARY_MONTHS = 3  # latest months flagged as subject to revision (no flag in the source)


# --------------------------------------------------------------------------------------
# Sector mapping
# --------------------------------------------------------------------------------------
def division_to_sector(code: str) -> str | None:
    """SNI 2007 two-digit division -> sector code (None for division 84 and non-divisions)."""
    if not (len(code) == 2 and code.isdigit()):
        return None
    div = int(code)
    if div == 0:
        return "UNS"
    for lo, hi, sector in config.DIVISION_RANGES:
        if lo <= div <= hi:
            return sector
    return None


def sector_map_table(meta_path: Path | None = None) -> pd.DataFrame:
    """Reference table: source group code and label -> sector (from the source's own codes)."""
    labels: dict[str, str] = {}
    if meta_path is not None and meta_path.exists():
        meta = json.loads(meta_path.read_bytes())
        for var in meta["variables"]:
            if var["code"] == "Bransch":
                labels = dict(zip(var["values"], var["valueTexts"], strict=True))
    rows = [
        {
            "source": "tillvaxtanalys",
            "source_code": code,
            "source_label": labels.get(code, ""),
            "sector": sector,
            "sector_label": config.SECTORS[sector],
        }
        for code, sector in config.TVA_CODE_TO_SECTOR.items()
    ]
    for lo, hi, sector in config.DIVISION_RANGES:
        rows.append(
            {
                "source": "scb_fdb",
                "source_code": f"{lo:02d}-{hi:02d}",
                "source_label": "SNI 2007 divisions",
                "sector": sector,
                "sector_label": config.SECTORS[sector],
            }
        )
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------------------
# Readers (one per raw source)
# --------------------------------------------------------------------------------------
def month_period(codes: pd.Series) -> pd.PeriodIndex:
    return pd.PeriodIndex(codes.str.replace("M", "-"), freq="M")


def read_bankruptcies(folder: Path) -> pd.DataFrame:
    df = jsonstat.read(folder / "monthly_by_sector.json")
    df = df[df["variabel"] == "0"]
    unknown = set(df["Bransch"]) - set(config.TVA_CODE_TO_SECTOR)
    if unknown:
        raise ValueError(f"Unknown industry codes in bankruptcy table: {sorted(unknown)}")
    out = pd.DataFrame(
        {
            "month": month_period(df["Tid"]).astype(str),
            "source_code": df["Bransch"].to_numpy(),
            "sector": df["Bransch"].map(config.TVA_CODE_TO_SECTOR).to_numpy(),
            "count": df["value"].to_numpy(),
        }
    )
    return out


def read_county_total(folder: Path) -> pd.Series:
    df = jsonstat.read(folder / "monthly_by_county.json")
    df = df[df["variabel"] == "0"]
    total = df.groupby("Tid")["value"].sum(min_count=1)
    total.index = month_period(pd.Series(total.index)).astype(str)
    return total.rename("county_total")


def _sni_column(df: pd.DataFrame) -> str:
    return next(c for c in df.columns if "SNI" in c.upper())


def _total_code(dim_codes: list[str], labels: dict[str, str]) -> str | None:
    for code in dim_codes:
        text = f"{code} {labels.get(code, '')}".lower()
        if "tot" in text or "samtliga" in text or "alla" in text:
            return code
    return None


def read_firms(path: Path) -> pd.DataFrame:
    """Enterprises by sector and year from an SCB FDB/FEK json-stat2 file."""
    ds = jsonstat.load(path)
    df = jsonstat.to_frame(ds)
    sni = _sni_column(df)
    # Keep one value per SNI x year: use the total of any other dimension if it exists.
    for dim in ds["id"]:
        if dim in (sni, "Tid"):
            continue
        codes = jsonstat.category_codes(ds["dimension"][dim])
        labels = ds["dimension"][dim]["category"].get("label", {})
        if dim == "ContentsCode":
            chosen = next(
                (c for c in codes if "antal företag" in labels.get(c, "").lower()), codes[0]
            )
            df = df[df[dim] == chosen]
            continue
        total = _total_code(codes, labels)
        if total is not None:
            df = df[df[dim] == total]
        else:
            df = df.groupby([c for c in df.columns if c not in (dim, "value")], as_index=False)[
                "value"
            ].sum(min_count=1)
    df = df.assign(sector=df[sni].map(division_to_sector)).dropna(subset=["sector"])
    out = df.groupby(["sector", "Tid"], as_index=False)["value"].sum(min_count=1)
    out = out.rename(columns={"Tid": "year", "value": "firms"})
    out["year"] = out["year"].astype(int)
    return out


def read_unemployment(folder: Path) -> pd.Series:
    df = jsonstat.read(folder / "aku_monthly.json")
    s = df.set_index(month_period(df["Tid"]))["value"].sort_index()
    return s.rename("unemp")


def read_gdp(folder: Path) -> pd.Series:
    df = jsonstat.read(folder / "gdp_sa.json")
    idx = pd.PeriodIndex(df["Tid"].str.replace("K", "Q"), freq="Q")
    return pd.Series(df["value"].to_numpy(), index=idx, name="gdp_level").sort_index()


def read_policy_rate(folder: Path) -> pd.Series:
    obs = json.loads((folder / "policy_rate.json").read_bytes())
    s = pd.Series(
        [o["value"] for o in obs], index=pd.to_datetime([o["date"] for o in obs]), dtype=float
    )
    return s.rename("policy_rate").sort_index()


def read_eba(path: Path) -> pd.DataFrame:
    """Sweden's baseline and adverse paths from the official EBA/ESRB workbook.

    Returns one row per scenario x year with gdp_growth (%), unemp (%) and rate_3m (%,
    SEK 3M swap rate).
    """
    import openpyxl

    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)

    def country_row(sheet: str) -> tuple[list, list]:
        rows = list(wb[sheet].iter_rows(values_only=True))
        years = list(rows[4])
        se = next(r for r in rows if len(r) > 2 and r[2] == "SE")
        return years, list(se)

    def sek_row(tenor: str) -> tuple[list, list]:
        rows = list(wb["SWAP rates"].iter_rows(values_only=True))
        years = list(rows[4])
        row = next(r for r in rows if r[1] == "SEK" and r[2] == tenor)
        return years, list(row)

    records = []
    for variable, (years, row) in {
        "gdp_growth": country_row("GDP"),
        "unemp": country_row("Unemployment"),
    }.items():
        # columns: 3 = 2024 history, 4-6 = baseline 2025-27, 7-9 = adverse 2025-27
        for scenario, cols in (("baseline", range(4, 7)), ("adverse", range(7, 10))):
            for c in cols:
                records.append(
                    {
                        "scenario": scenario,
                        "year": int(years[c]),
                        "variable": variable,
                        "value": float(row[c]),
                    }
                )
        records.append(
            {
                "scenario": "history",
                "year": int(years[3]),
                "variable": variable,
                "value": float(row[3]),
            }
        )
    years, row = sek_row("3M")
    # columns: 3 start avg 2024, 4 start latest, 5-7 baseline 2025-27, 8-10 adverse 2025-27
    for scenario, cols in (("baseline", range(5, 8)), ("adverse", range(8, 11))):
        for c in cols:
            records.append(
                {
                    "scenario": scenario,
                    "year": int(years[c]),
                    "variable": "rate_3m",
                    "value": float(row[c]),
                }
            )
    return pd.DataFrame(records)


# --------------------------------------------------------------------------------------
# Assembly
# --------------------------------------------------------------------------------------
def macro_quarterly(unemp_m: pd.Series, gdp_q: pd.Series, policy_d: pd.Series) -> pd.DataFrame:
    unemp_q = unemp_m.groupby(unemp_m.index.asfreq("Q")).agg(["mean", "count"])
    unemp_q = unemp_q.loc[unemp_q["count"] == 3, "mean"].rename("unemp")
    pol = policy_d.groupby(policy_d.index.to_period("Q")).mean().rename("policy_rate")
    macro = pd.concat([unemp_q, gdp_q.rename("gdp_level"), pol], axis=1).sort_index()
    macro = macro[macro.index >= pd.Period("2001Q1", "Q")]
    macro["d_unemp"] = macro["unemp"] - macro["unemp"].shift(4)
    macro["gdp_yoy"] = 100 * (macro["gdp_level"] / macro["gdp_level"].shift(4) - 1)
    macro["d_policy"] = macro["policy_rate"] - macro["policy_rate"].shift(4)
    macro.index = macro.index.astype(str)
    macro.index.name = "quarter"
    return macro


def aggregate_quarterly(monthly: pd.DataFrame) -> pd.DataFrame:
    """Sum months to quarters; keep only complete quarters (three published months)."""
    m = monthly.copy()
    m["quarter"] = pd.PeriodIndex(m["month"], freq="M").asfreq("Q").astype(str)
    q = m.groupby(["sector", "quarter"]).agg(
        count=("count", "sum"),
        months=("count", "size"),
        is_preliminary=("is_preliminary", "any"),
    )
    return q[q["months"] == 3].drop(columns="months").reset_index()


def attach_denominators(
    q: pd.DataFrame, firms_fdb: pd.DataFrame, fek: pd.DataFrame
) -> pd.DataFrame:
    """Join the annual stock of the previous year (November) and compute rates.

    Guarded against join fan-out: the number of rows must not change.
    """
    q = q.copy()
    q["firms_year"] = pd.PeriodIndex(q["quarter"], freq="Q").year - 1
    # Hold the latest available stock for quarters whose previous-year stock is not published.
    q["firms_year"] = q["firms_year"].clip(upper=int(firms_fdb["year"].max()))
    n = len(q)
    q = q.merge(
        firms_fdb.rename(columns={"year": "firms_year"}), on=["sector", "firms_year"], how="left"
    )
    fek_m = fek.rename(columns={"year": "firms_year", "firms": "firms_fek"})
    q = q.merge(fek_m, on=["sector", "firms_year"], how="left")
    if len(q) != n:
        raise RuntimeError("Denominator join changed the number of rows (fan-out)")
    q["rate"] = 4 * q["count"] / q["firms"]
    q["rate_fek"] = 4 * q["count"] / q["firms_fek"]
    q = q.sort_values(["sector", "quarter"]).reset_index(drop=True)
    roll = q.groupby("sector")["count"].transform(lambda s: s.rolling(4).sum())
    q["rate_r4"] = roll / q["firms"]
    return q


def build(raw_root: Path = config.RAW) -> dict[str, pd.DataFrame]:
    tva = latest_snapshot("tillvaxtanalys", raw_root)
    scb = latest_snapshot("scb", raw_root)
    rb = latest_snapshot("riksbank", raw_root)

    monthly_src = read_bankruptcies(tva)
    monthly = monthly_src.groupby(["sector", "month"], as_index=False)["count"].sum()
    months = sorted(monthly["month"].unique())
    monthly["source"] = "tillvaxtanalys"
    monthly["is_preliminary"] = monthly["month"].isin(months[-PRELIMINARY_MONTHS:])
    county_total = read_county_total(tva)

    firms_fdb = read_firms(scb / "fdb_firms.json")
    firms_fek = []
    for name in ("fek_firms_2000_2021", "fek_firms_2022_"):
        if (scb / f"{name}.json").exists():
            firms_fek.append(read_firms(scb / f"{name}.json"))
    fek = pd.concat(firms_fek) if firms_fek else pd.DataFrame(columns=["sector", "year", "firms"])
    fek = fek.drop_duplicates(["sector", "year"], keep="last")

    macro = macro_quarterly(read_unemployment(scb), read_gdp(scb), read_policy_rate(rb))

    q = aggregate_quarterly(monthly)
    q = attach_denominators(q, firms_fdb, fek)
    q["covid_support"] = (
        (q["quarter"] >= config.COVID_SUPPORT[0]) & (q["quarter"] <= config.COVID_SUPPORT[1])
    ).astype(int)
    q = q.merge(macro, left_on="quarter", right_index=True, how="left")
    q["source"] = "tillvaxtanalys"
    q = q.reset_index(drop=True)

    return {
        "panel_monthly": monthly.sort_values(["sector", "month"]).reset_index(drop=True),
        "panel_monthly_source": monthly_src,
        "county_total": county_total.rename_axis("month").reset_index(),
        "panel_quarterly": q,
        "macro_quarterly": macro.reset_index(),
        "firms_fdb": firms_fdb,
        "firms_fek": fek,
    }


def write(tables: dict[str, pd.DataFrame], out: Path = config.PROCESSED) -> None:
    out.mkdir(parents=True, exist_ok=True)
    for name, df in tables.items():
        df.to_csv(out / f"{name}.csv", index=False)
        try:
            df.to_parquet(out / f"{name}.parquet", index=False)
        except ImportError:
            log.warning("pyarrow not installed: wrote %s.csv only", name)


def load(name: str, folder: Path = config.PROCESSED) -> pd.DataFrame:
    """Read a processed table (CSV is the canonical, diffable copy)."""
    dtype = {"quarter": str, "month": str, "sector": str}
    return pd.read_csv(folder / f"{name}.csv", dtype=dtype)


def main() -> None:
    tables = build()
    write(tables)
    tva = latest_snapshot("tillvaxtanalys")
    sector_map_table(tva / "monthly_by_sector_metadata.json").to_csv(
        config.REFERENCE / "sector_map.csv", index=False
    )
    eba = read_eba(latest_snapshot("eba") / "macro_financial_scenario_2025_corrigendum.xlsx")
    eba.to_csv(config.REFERENCE / "eba_2025_sweden.csv", index=False)
    log.info("Panels written: %s", {k: len(v) for k, v in tables.items()})


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
