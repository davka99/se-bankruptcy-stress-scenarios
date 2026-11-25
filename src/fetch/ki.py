"""Fetch forecasts from Konjunkturinstitutet's (NIER) forecast database (PxWeb API v1).

The latest forecast (`SenastePrognosen`) is the baseline scenario. Earlier forecast
vintages (`TidigarePrognoser/<yyyymmdd>`) are used for the real-time backtest.
Source must always be cited as Konjunkturinstitutet.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any
from urllib.parse import quote

from src import config
from src.fetch.common import Snapshot, http_session, pxweb_v1_query, request_with_retry

log = logging.getLogger(__name__)

PAUSE = 0.25  # seconds between calls, to stay well below the portal's rate limit
VINTAGE_TABLES = ["unemployment_q", "gdp_q", "policy_rate_m"]
FALLBACKS = {"unemployment_q": "unemployment_q_old"}


def _url(*parts: str) -> str:
    return quote("/".join([config.KI_API, *parts]), safe=":/")


def _get_json(session, url: str) -> Any:
    time.sleep(PAUSE)
    return json.loads(request_with_retry(session, "GET", url).content)


def _find_tables(session, base_parts: list[str], depth: int = 0) -> dict[str, list[str]]:
    """Walk a database folder and return {table_file_stem: path_parts}."""
    found: dict[str, list[str]] = {}
    for item in _get_json(session, _url(*base_parts)):
        if item.get("type") == "t":
            found[item["id"].split(".")[0]] = [*base_parts, item["id"]]
        elif item.get("type") == "l" and depth < 3:
            found.update(_find_tables(session, [*base_parts, item["id"]], depth + 1))
    return found


def _selection(meta: dict, variable: str | None) -> dict[str, list[str] | None]:
    """All values of every variable in the table, except `variabel` when one is given."""
    selection: dict[str, list[str] | None] = {}
    for var in meta["variables"]:
        code = var["code"]
        keep = variable is not None and code == "variabel" and variable in var["values"]
        selection[code] = [variable] if keep else None
    return selection


def _fetch_table(session, snap: Snapshot, parts: list[str], variable: str | None, name: str):
    url = _url(*parts)
    time.sleep(PAUSE)
    meta = request_with_retry(session, "GET", url)
    snap.save(f"{name}_metadata.json", meta.content, url=url)
    query = pxweb_v1_query(_selection(json.loads(meta.content), variable))
    time.sleep(PAUSE)
    data = request_with_retry(session, "POST", url, json=query)
    snap.save(f"{name}.json", data.content, url=url, method="POST", query=query)


def fetch(snapshot_date: str | None = None, vintages: bool = True) -> Snapshot:
    snap = Snapshot("ki", **({"snapshot_date": snapshot_date} if snapshot_date else {}))
    session = http_session()

    latest_listing = _get_json(session, _url(config.KI_LATEST_DB))
    for name, (folder, table, variable) in config.KI_TABLES.items():
        parts = [config.KI_LATEST_DB, folder, table]
        _fetch_table(session, snap, parts, variable, f"latest_{name}")
    folder_listing = {
        folder: _get_json(session, _url(config.KI_LATEST_DB, folder))
        for folder, _, _ in config.KI_TABLES.values()
    }

    vintage_ids: list[str] = []
    missing: list[str] = []
    if vintages:
        for item in _get_json(session, _url(config.KI_VINTAGE_DB)):
            vintage_id = item["id"]
            if not item.get("text", "").startswith("Konjunk"):
                continue  # skip e.g. the wage formation report
            tables = _find_tables(session, [config.KI_VINTAGE_DB, vintage_id])
            vintage_ids.append(vintage_id)
            for name in VINTAGE_TABLES:
                _, table, variable = config.KI_TABLES[name]
                stem = table.split(".")[0]
                if stem not in tables and name in FALLBACKS:
                    name = FALLBACKS[name]
                    _, table, variable = config.KI_TABLES[name]
                    stem = table.split(".")[0]
                if stem not in tables:
                    missing.append(f"{vintage_id}:{stem}")
                    continue
                try:
                    _fetch_table(
                        session, snap, tables[stem], variable, f"vintage_{vintage_id}_{name}"
                    )
                except Exception as err:
                    log.warning("KI vintage %s %s failed: %s", vintage_id, stem, err)
                    missing.append(f"{vintage_id}:{stem}")
    snap.write_manifest(
        {
            "api": "PxWeb v1",
            "latest_listing": latest_listing,
            "latest_folder_listing": folder_listing,
            "vintages": vintage_ids,
            "missing_vintage_tables": missing,
        }
    )
    return snap


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    fetch()
