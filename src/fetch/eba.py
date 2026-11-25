"""Download the EBA 2025 EU-wide stress test macro-financial scenario (official xlsx)."""

from __future__ import annotations

import logging

from src import config
from src.fetch.common import Snapshot, http_session, request_with_retry

log = logging.getLogger(__name__)


def fetch(snapshot_date: str | None = None) -> Snapshot:
    snap = Snapshot("eba", **({"snapshot_date": snapshot_date} if snapshot_date else {}))
    session = http_session()
    response = request_with_retry(session, "GET", config.EBA_SCENARIO_XLSX)
    snap.save(
        "macro_financial_scenario_2025_corrigendum.xlsx",
        response.content,
        url=config.EBA_SCENARIO_XLSX,
        note=config.EBA_VINTAGE,
    )
    snap.write_manifest({"vintage": config.EBA_VINTAGE})
    return snap


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    fetch()
