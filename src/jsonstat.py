"""Minimal json-stat2 reader: turns a dataset into a long pandas DataFrame."""

from __future__ import annotations

import json
from itertools import product
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


def load(path: Path) -> dict[str, Any]:
    return json.loads(Path(path).read_bytes())


def category_codes(dimension: dict[str, Any]) -> list[str]:
    index = dimension["category"].get("index")
    if index is None:  # single-category dimension may omit index
        return list(dimension["category"]["label"])
    if isinstance(index, dict):
        return sorted(index, key=index.get)
    return list(index)


def to_frame(dataset: dict[str, Any], labels: bool = False) -> pd.DataFrame:
    """Long format: one column per dimension (codes, or labels) plus `value` (float)."""
    dims = dataset["id"]
    sizes = dataset["size"]
    codes = [category_codes(dataset["dimension"][d]) for d in dims]
    if any(len(c) != s for c, s in zip(codes, sizes, strict=True)):
        raise ValueError("json-stat2 size does not match category index")
    n = int(np.prod(sizes))
    raw = dataset["value"]
    if isinstance(raw, dict):  # sparse representation
        values = [None] * n
        for k, v in raw.items():
            values[int(k)] = v
    else:
        values = list(raw)
    if len(values) != n:
        raise ValueError(f"json-stat2 value length {len(values)} != product of sizes {n}")
    rows = list(product(*codes))  # row-major order, last dimension fastest
    frame = pd.DataFrame(rows, columns=dims)
    frame["value"] = pd.to_numeric(pd.Series(values, dtype="object"), errors="coerce")
    if labels:
        for d in dims:
            lab = dataset["dimension"][d]["category"].get("label", {})
            frame[f"{d}_label"] = frame[d].map(lab).fillna(frame[d])
    status = dataset.get("status")
    if status:
        flags = [None] * n
        if isinstance(status, dict):
            for k, v in status.items():
                flags[int(k)] = v
        elif isinstance(status, list):
            flags = list(status) + [None] * (n - len(status))
        frame["status"] = flags
    return frame


def read(path: Path, labels: bool = False) -> pd.DataFrame:
    return to_frame(load(path), labels=labels)
