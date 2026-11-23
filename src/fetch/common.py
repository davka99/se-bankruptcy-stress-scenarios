"""Shared helpers for the fetch modules: HTTP with retry/backoff, snapshots and manifests."""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import requests

from src import config


def http_session() -> requests.Session:
    session = requests.Session()
    session.headers["User-Agent"] = config.USER_AGENT
    return session


def request_with_retry(
    session: requests.Session,
    method: str,
    url: str,
    *,
    retries: int = config.HTTP_RETRIES,
    backoff: float = config.HTTP_BACKOFF,
    timeout: float = config.HTTP_TIMEOUT,
    **kwargs: Any,
) -> requests.Response:
    """Send a request, retrying on connection errors, 429 and 5xx with exponential backoff."""
    last_error: Exception | None = None
    for attempt in range(retries + 1):
        try:
            response = session.request(method, url, timeout=timeout, **kwargs)
            if response.status_code == 429 or response.status_code >= 500:
                raise requests.HTTPError(f"HTTP {response.status_code}", response=response)
            response.raise_for_status()
            return response
        except (requests.ConnectionError, requests.Timeout, requests.HTTPError) as err:
            status = getattr(getattr(err, "response", None), "status_code", None)
            if status is not None and 400 <= status < 500 and status != 429:
                raise  # client errors are not retried
            last_error = err
            if attempt < retries:
                time.sleep(backoff * 2**attempt)
    assert last_error is not None
    raise last_error


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def count_jsonstat_values(content: bytes) -> int | None:
    """Number of non-null cells in a json-stat2 payload, or None if not json-stat2."""
    try:
        payload = json.loads(content)
    except (ValueError, UnicodeDecodeError):
        return None
    if isinstance(payload, dict) and "value" in payload:
        values = payload["value"]
        if isinstance(values, dict):
            return sum(v is not None for v in values.values())
        return sum(v is not None for v in values)
    if isinstance(payload, list):
        return len(payload)
    return None


@dataclass
class Snapshot:
    """A dated folder of raw files for one source, with a manifest."""

    source: str
    snapshot_date: str = field(default_factory=lambda: date.today().isoformat())
    root: Path = config.RAW
    entries: list[dict[str, Any]] = field(default_factory=list)

    @property
    def folder(self) -> Path:
        return self.root / self.source / self.snapshot_date

    def save(
        self,
        filename: str,
        content: bytes,
        *,
        url: str,
        method: str = "GET",
        query: Any = None,
        note: str | None = None,
    ) -> Path:
        self.folder.mkdir(parents=True, exist_ok=True)
        path = self.folder / filename
        path.write_bytes(content)
        self.entries.append(
            {
                "file": filename,
                "url": url,
                "method": method,
                "query": query,
                "retrieved_at": datetime.now(UTC).isoformat(timespec="seconds"),
                "rows": count_jsonstat_values(content),
                "bytes": len(content),
                "sha256": sha256_bytes(content),
                "note": note,
            }
        )
        return path

    def write_manifest(self, extra: dict[str, Any] | None = None) -> Path:
        self.folder.mkdir(parents=True, exist_ok=True)
        manifest = {
            "source": self.source,
            "snapshot_date": self.snapshot_date,
            "files": self.entries,
        }
        if extra:
            manifest.update(extra)
        path = self.folder / "manifest.json"
        path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
        return path


def latest_snapshot(source: str, root: Path = config.RAW) -> Path:
    """Most recent dated snapshot folder for a source."""
    folders = sorted(p for p in (root / source).glob("????-??-??") if p.is_dir())
    if not folders:
        raise FileNotFoundError(f"No snapshot for source '{source}' under {root}")
    return folders[-1]


def pxweb_v1_query(selection: dict[str, list[str] | None]) -> dict[str, Any]:
    """Build a PxWeb v1 JSON query. A value of None or ['*'] selects all values."""
    query = []
    for code, values in selection.items():
        if values is None or values == ["*"]:
            query.append({"code": code, "selection": {"filter": "all", "values": ["*"]}})
        else:
            query.append({"code": code, "selection": {"filter": "item", "values": values}})
    return {"query": query, "response": {"format": "json-stat2"}}
