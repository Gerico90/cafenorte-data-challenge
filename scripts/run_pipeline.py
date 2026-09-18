"""
Minimal CLI entry point for the CaféNorte pipeline.

Runs the existing orchestration in src/pipeline.py end-to-end:
    load raw sources -> reconcile products -> build analytical model
    -> persist to data/processed/cafenorte.duckdb

This script intentionally contains no pipeline logic of its own; it
only wires up the already-implemented orchestration so it can be
invoked as `python scripts/run_pipeline.py` from the repository root.
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.pipeline import run_pipeline, DATABASE_PATH


def main() -> None:
    run_pipeline()
    print(f"Analytical model persisted to: {DATABASE_PATH}")


if __name__ == "__main__":
    main()
