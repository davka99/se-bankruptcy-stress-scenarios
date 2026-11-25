"""Run the whole project in order.

python -m src.pipeline              # offline (default): build everything from committed raw data
python -m src.pipeline --refresh    # fetch new raw snapshots first, then build
python -m src.pipeline --fetch-only # only fetch (used by the refresh workflow)
"""

from __future__ import annotations

import argparse
import importlib
import logging
import sys
import tempfile
import traceback
from pathlib import Path

log = logging.getLogger("pipeline")

FETCHERS = ["tillvaxtanalys", "scb", "riksbank", "ki", "eba"]

# (module, function) in run order; later phases add their steps here.
BUILD_STEPS = [
    ("src.build_panel", "main"),
    ("src.eda", "main"),
    ("src.backtest", "main_selection"),
    ("src.backtest", "main_test"),
    ("src.realtime", "main"),
    ("src.model_report", "main"),
    ("src.scenarios", "main"),
    ("src.portfolio_overlay", "main"),
    ("src.monitoring", "main"),
    ("src.report_numbers", "main"),
    ("src.render_readme", "main"),
]


def run_fetch() -> list[str]:
    failed = []
    for name in FETCHERS:
        log.info("Fetching %s", name)
        try:
            importlib.import_module(f"src.fetch.{name}").fetch()
        except Exception:
            log.error("Fetch %s failed:\n%s", name, traceback.format_exc())
            failed.append(name)
    return failed


def run_build() -> None:
    for module, func in BUILD_STEPS:
        log.info("Running %s.%s", module, func)
        getattr(importlib.import_module(module), func)()


def run_smoke() -> None:
    """Parse the committed raw data into a temporary folder and run smoke steps."""
    from src import build_panel

    with tempfile.TemporaryDirectory() as tmp:
        tables = build_panel.build()
        build_panel.write(tables, Path(tmp))
        log.info("Smoke: panels built (%s quarterly rows)", len(tables["panel_quarterly"]))
        for module, func in SMOKE_STEPS:
            getattr(importlib.import_module(module), func)(Path(tmp))


SMOKE_STEPS: list[tuple[str, str]] = [
    ("src.eda", "main"),
    ("src.backtest", "smoke"),
]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--offline", action="store_true", help="build from committed raw data")
    mode.add_argument("--refresh", action="store_true", help="fetch new data, then build")
    mode.add_argument("--fetch-only", action="store_true", help="fetch new data only")
    mode.add_argument("--smoke", action="store_true", help="quick offline smoke test")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

    if args.smoke:
        run_smoke()
        return 0
    failed: list[str] = []
    if args.refresh or args.fetch_only:
        failed = run_fetch()
    if not args.fetch_only:
        run_build()
    if failed:
        log.error("Fetch failed for: %s", ", ".join(failed))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
