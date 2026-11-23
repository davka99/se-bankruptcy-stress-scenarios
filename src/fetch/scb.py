"""Fetch SCB tables through PxWebApi v2 (GET requests, json-stat2 output).

PxWebApi v2 is queried with GET: `/tables/{id}/metadata` describes the dimensions and
`/tables/{id}/data?valueCodes[DIM]=a,b` returns the selected cells. Dimensions that are
left out are eliminated by the server when the table allows it.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any
from urllib.parse import quote

from src import config
from src.fetch.common import Snapshot, http_session, request_with_retry

log = logging.getLogger(__name__)

TWO_DIGIT = re.compile(r"^\d{2}$")


def dimensions(meta: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Return {dim_id: {"codes": [...], "labels": {...}, "extension": {...}}} from metadata."""
    out = {}
    for dim_id in meta.get("id", []):
        dim = meta["dimension"][dim_id]
        index = dim["category"]["index"]
        codes = sorted(index, key=index.get) if isinstance(index, dict) else list(index)
        out[dim_id] = {
            "codes": codes,
            "labels": dim["category"].get("label", {}),
            "extension": dim.get("extension", {}) or {},
            "label": dim.get("label", dim_id),
        }
    return out


def is_eliminable(dim: dict[str, Any]) -> bool:
    ext = dim["extension"]
    return bool(ext.get("elimination", False))


def industry_selection(meta: dict[str, Any]) -> dict[str, list[str]]:
    """Selection for FDB/FEK-type tables: SNI divisions (2-digit), all other dims kept.

    The total and unknown-industry codes are also kept so that the panel can check that
    divisions add up to the total.
    """
    selection: dict[str, list[str]] = {}
    for dim_id, dim in dimensions(meta).items():
        if dim_id == "Tid":
            selection[dim_id] = ["*"]
        elif "SNI" in dim_id.upper() or "SNI" in str(dim["label"]).upper():
            keep = [
                c
                for c in dim["codes"]
                if TWO_DIGIT.match(c) or c in {"0", "00", "A-U", "TOT", "Totalt"}
            ]
            selection[dim_id] = keep
        elif dim_id == "ContentsCode":
            selection[dim_id] = ["*"]
        elif is_eliminable(dim):
            continue  # let the server aggregate
        else:
            selection[dim_id] = ["*"]
    return selection


def find_base(session, table: str) -> str:
    """First v2 host that serves table metadata; every attempt is logged for diagnosis."""
    for base in [config.SCB_API, *config.SCB_API_ALTERNATIVES]:
        for suffix in ("?lang=sv", "?lang=en", ""):
            url = f"{base}/tables/{table}/metadata{suffix}"
            response = session.get(url, timeout=config.HTTP_TIMEOUT)
            log.info("SCB probe %s -> %s %s", url, response.status_code, response.text[:200])
            if response.ok:
                return base
    raise RuntimeError("No SCB PxWebApi v2 host answered; see probe lines above")


def data_url(table: str, selection: dict[str, list[str]], base: str = config.SCB_API) -> str:
    params = "&".join(
        f"valueCodes[{quote(dim)}]={quote(','.join(codes), safe='*,()')}"
        for dim, codes in selection.items()
    )
    return f"{base}/tables/{table}/data?lang=sv&outputFormat=json-stat2&{params}"


def fetch(snapshot_date: str | None = None) -> Snapshot:
    snap = Snapshot("scb", **({"snapshot_date": snapshot_date} if snapshot_date else {}))
    session = http_session()
    session.headers["Accept"] = "application/json"
    base = find_base(session, next(iter(config.SCB_TABLES.values())))
    for key, table in config.SCB_TABLES.items():
        meta_url = f"{base}/tables/{table}/metadata?lang=sv"
        meta_resp = request_with_retry(session, "GET", meta_url)
        snap.save(f"{key}_metadata.json", meta_resp.content, url=meta_url)
        meta = json.loads(meta_resp.content)
        selection = config.SCB_SELECTIONS.get(key) or industry_selection(meta)
        url = data_url(table, selection, base)
        try:
            data = request_with_retry(session, "GET", url)
        except Exception as err:
            if key.startswith("fek"):  # sensitivity denominator only
                log.warning("Optional table %s failed: %s", table, err)
                continue
            raise
        snap.save(f"{key}.json", data.content, url=url, query=selection)
        log.info("SCB %s (%s): %d bytes", key, table, len(data.content))
    snap.write_manifest({"api": "PxWebApi v2"})
    return snap


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    fetch()
