from pathlib import Path
import json

import pandas as pd


BASE = Path(__file__).resolve().parents[1]
RAW = BASE / "data" / "raw"

SALES_PATH = RAW / "sales.csv"
INVENTORY_PATH = RAW / "inventory.json"
ECOMMERCE_PATH = RAW / "ecommerce_orders.parquet"


def section(title: str) -> None:
    print("\n" + "=" * 80)
    print(title)
    print("=" * 80)


# ---------------------------------------------------------------------
# Load sources
# ---------------------------------------------------------------------

sales = pd.read_csv(SALES_PATH)
ecommerce = pd.read_parquet(ECOMMERCE_PATH)

with open(INVENTORY_PATH, "r", encoding="utf-8") as f:
    inventory = json.load(f)


# ---------------------------------------------------------------------
# 1. Basic counts
# ---------------------------------------------------------------------

section("1. BASIC COUNTS")

print(f"sales.csv rows: {len(sales):,}")
print(f"ecommerce_orders.parquet rows: {len(ecommerce):,}")

print(f"inventory tiendas_info: {len(inventory['tiendas_info']):,}")
print(f"inventory sku_mappings: {len(inventory['sku_mappings']):,}")
print(f"inventory catalogo.productos: {len(inventory['catalogo']['productos']):,}")
print(f"inventory snapshots: {len(inventory['snapshots']):,}")


# ---------------------------------------------------------------------
# 2. Date ranges
# ---------------------------------------------------------------------

section("2. DATE RANGES")

sales_dates = pd.to_datetime(sales["fecha_hora"])
ecommerce_dates = pd.to_datetime(ecommerce["fecha"])

snapshots = pd.DataFrame(inventory["snapshots"])
snapshot_dates = pd.to_datetime(snapshots["fecha"])

print(
    "sales:",
    sales_dates.min(),
    "->",
    sales_dates.max(),
)

print(
    "ecommerce:",
    ecommerce_dates.min(),
    "->",
    ecommerce_dates.max(),
)

print(
    "inventory snapshots:",
    snapshot_dates.min(),
    "->",
    snapshot_dates.max(),
)

three_way_start = max(
    sales_dates.min().date(),
    ecommerce_dates.min().date(),
    snapshot_dates.min().date(),
)

three_way_end = min(
    sales_dates.max().date(),
    ecommerce_dates.max().date(),
    snapshot_dates.max().date(),
)

print(
    "three-way overlap:",
    three_way_start,
    "->",
    three_way_end,
)


# ---------------------------------------------------------------------
# 3. Core identifiers
# ---------------------------------------------------------------------

section("3. IDENTIFIERS")

print(f"sales unique venta_id: {sales['venta_id'].nunique():,}")
print(f"sales duplicate venta_id: {sales['venta_id'].duplicated().sum():,}")

print(f"sales unique tienda_id: {sales['tienda_id'].nunique():,}")
print(f"sales unique sku: {sales['sku'].nunique():,}")

print(f"ecommerce unique order_id: {ecommerce['order_id'].nunique():,}")
print(f"ecommerce duplicate order_id: {ecommerce['order_id'].duplicated().sum():,}")
print(f"ecommerce unique product_handle: {ecommerce['product_handle'].nunique():,}")

print(
    "ecommerce has tienda_id:",
    "tienda_id" in ecommerce.columns,
)


# ---------------------------------------------------------------------
# 4. Inventory snapshot quality
# ---------------------------------------------------------------------

section("4. INVENTORY SNAPSHOT QUALITY")

stock_as_text = snapshots["cantidad_en_stock"].astype(str)

na_stock = (stock_as_text == "N/A").sum()

print(f"snapshot rows: {len(snapshots):,}")
print(f"'N/A' cantidad_en_stock: {na_stock:,}")
print(f"'N/A' percentage: {na_stock / len(snapshots) * 100:.4f}%")

snapshot_duplicate_keys = snapshots.duplicated(
    subset=["fecha", "tienda_id", "sku_erp"]
).sum()

print(
    "duplicate (fecha, tienda_id, sku_erp):",
    f"{snapshot_duplicate_keys:,}",
)


# ---------------------------------------------------------------------
# 5. SKU reconciliation
# ---------------------------------------------------------------------

section("5. SKU RECONCILIATION")

mappings = pd.DataFrame(inventory["sku_mappings"])

sales_skus = set(sales["sku"].dropna().unique())
mapped_pos = set(mappings["sku_pos"].dropna().unique())

print(f"sales distinct SKUs: {len(sales_skus)}")
print(f"mapping distinct sku_pos: {len(mapped_pos)}")
print(f"overlap: {len(sales_skus & mapped_pos)}")

missing_sales_skus = sorted(sales_skus - mapped_pos)

print(
    "sales SKUs missing from sku_mappings:",
    missing_sales_skus,
)

print(
    "null sku_erp in mappings:",
    int(mappings["sku_erp"].isna().sum()),
)

print(
    "null handle in mappings:",
    int(mappings["handle"].isna().sum()),
)


# ---------------------------------------------------------------------
# 6. Ecommerce handle reconciliation
# ---------------------------------------------------------------------

section("6. ECOMMERCE HANDLE RECONCILIATION")

order_handles = set(ecommerce["product_handle"].dropna().unique())
mapped_handles = set(mappings["handle"].dropna().unique())

print(f"ecommerce distinct handles: {len(order_handles)}")
print(f"mapped non-null handles: {len(mapped_handles)}")
print(f"overlap: {len(order_handles & mapped_handles)}")

missing_handles = sorted(order_handles - mapped_handles)

print(
    "ecommerce handles missing from sku_mappings:",
    missing_handles,
)


# ---------------------------------------------------------------------
# 7. Currency
# ---------------------------------------------------------------------

section("7. CURRENCIES")

print("sales currencies:")
print(sales["moneda"].value_counts(dropna=False).sort_index())

print("\necommerce currencies:")
print(ecommerce["currency"].value_counts(dropna=False).sort_index())


# ---------------------------------------------------------------------
# 8. Store reconciliation
# ---------------------------------------------------------------------

section("8. STORE RECONCILIATION")

stores = pd.DataFrame(inventory["tiendas_info"])

sales_stores = set(sales["tienda_id"].dropna().unique())
inventory_stores = set(stores["tienda_id"].dropna().unique())

print(f"sales stores: {len(sales_stores)}")
print(f"inventory stores: {len(inventory_stores)}")
print(f"store overlap: {len(sales_stores & inventory_stores)}")

print(
    "identical store sets:",
    sales_stores == inventory_stores,
)


# ---------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------

section("VALIDATION COMPLETE")

print(
    "This script only verifies critical Source Discovery facts. "
    "It does not transform data or define business rules."
)