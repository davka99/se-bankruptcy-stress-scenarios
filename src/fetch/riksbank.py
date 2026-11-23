"""Fetch the policy rate from the Riksbank SWEA API.

An API key is optional. If the environment variable RIKSBANK_API_KEY is set, it is sent in
the `Ocp-Apim-Subscription-Key` header. The key is never written to disk.
"""

from __future__ import annotations

import logging
import os
from datetime import date

from src import config
from src.fetch.common import Snapshot, http_session, request_with_retry

log = logging.getLogger(__name__)

START = "2007-01-01"


def fetch(snapshot_date: str | None = None) -> Snapshot:
    snap = Snapshot("riksbank", **({"snapshot_date": snapshot_date} if snapshot_date else {}))
    session = http_session()
    key = os.environ.get(config.RIKSBANK_KEY_ENV)
    if key:
        session.headers["Ocp-Apim-Subscription-Key"] = key
    end = date.today().isoformat()
    for name, series in config.RIKSBANK_SERIES.items():
        url = f"{config.RIKSBANK_API}/Observations/{series}/{START}/{end}"
        response = request_with_retry(session, "GET", url)
        snap.save(f"{name}.json", response.content, url=url)
        log.info("Riksbank %s: %d bytes", series, len(response.content))
    series_url = f"{config.RIKSBANK_API}/Series"
    response = request_with_retry(session, "GET", series_url)
    snap.save("series_list.json", response.content, url=series_url)
    snap.write_manifest({"api": "SWEA v1", "api_key_used": bool(key)})
    return snap


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    fetch()
