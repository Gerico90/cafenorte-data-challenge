from pathlib import Path
import json

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RAW_DATA_DIR = PROJECT_ROOT / "data" / "raw"


def _require_file(path: Path) -> None:
    """Raise a clear error when an expected source file is missing."""
    if not path.is_file():
        raise FileNotFoundError(f"Source file not found: {path}")


def load_sales(path: Path | None = None) -> pd.DataFrame:
    """Load the raw POS sales CSV without applying transformations."""
    source_path = path or RAW_DATA_DIR / "sales.csv"
    _require_file(source_path)

    return pd.read_csv(source_path)


def load_ecommerce(path: Path | None = None) -> pd.DataFrame:
    """Load the raw Shopify orders Parquet without applying transformations."""
    source_path = path or RAW_DATA_DIR / "ecommerce_orders.parquet"
    _require_file(source_path)

    return pd.read_parquet(source_path)


def load_inventory(path: Path | None = None) -> dict:
    """Load the raw ERP inventory JSON without applying transformations."""
    source_path = path or RAW_DATA_DIR / "inventory.json"
    _require_file(source_path)

    with source_path.open("r", encoding="utf-8") as file:
        return json.load(file)


def load_sources() -> dict:
    """Load all three challenge sources."""
    return {
        "sales": load_sales(),
        "ecommerce": load_ecommerce(),
        "inventory": load_inventory(),
    }