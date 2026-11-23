"""Fetch bankruptcy statistics from Tillväxtanalys' statistics portal (PxWeb API v1)."""

from __future__ import annotations

import json
import logging
from urllib.parse import quote

from src import config
from src.fetch.common import Snapshot, http_session, pxweb_v1_query, request_with_retry

log = logging.getLogger(__name__)


def selection_from_metadata(meta: dict) -> dict[str, list[str] | None]:
    """All values of every variable, except `variabel` = '0' (number of bankruptcies)."""
    selection: dict[str, list[str] | None] = {}
    for var in meta["variables"]:
        selection[var["code"]] = ["0"] if var["code"] == "variabel" else None
    return selection


def table_url(table: str) -> str:
    return quote(config.TVA_API + table, safe=":/")


def fetch(snapshot_date: str | None = None) -> Snapshot:
    snap = Snapshot("tillvaxtanalys", **({"snapshot_date": snapshot_date} if snapshot_date else {}))
    session = http_session()

    listing_url = quote(config.TVA_API, safe=":/")
    listing = request_with_retry(session, "GET", listing_url)
    snap.save("table_listing.json", listing.content, url=listing_url)

    for key, table in config.TVA_TABLES.items():
        url = table_url(table)
        meta = request_with_retry(session, "GET", url)
        snap.save(f"{key}_metadata.json", meta.content, url=url)
        query = pxweb_v1_query(selection_from_metadata(json.loads(meta.content)))
        try:
            data = request_with_retry(session, "POST", url, json=query)
        except Exception as err:  # optional tables must not stop the pipeline
            if key == "annual_by_sector_legal_form":
                log.warning("Optional table %s failed: %s", table, err)
                continue
            raise
        snap.save(f"{key}.json", data.content, url=url, method="POST", query=query)
        log.info("Tillväxtanalys %s: %d bytes", table, len(data.content))

    report = request_with_retry(session, "GET", config.TVA_ANCHOR_REPORT_URL)
    snap.save(
        "validation_anchor_report_2023.pdf",
        report.content,
        url=config.TVA_ANCHOR_REPORT_URL,
        note="Statistik 2024:02, Table 1 p. 10 holds the validation anchor",
    )
    snap.write_manifest({"api": "PxWeb v1", "listing": json.loads(listing.content)})
    return snap


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    fetch()
