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
# 9. PRODUCT ID PATTERN VALIDATION
# ---------------------------------------------------------------------

import re

section("9. PRODUCT ID PATTERN VALIDATION")


def extract_pos_number(value):
    if pd.isna(value):
        return None

    match = re.fullmatch(r"CN-(\d{5})", str(value))
    return int(match.group(1)) if match else None


def extract_erp_number(value):
    if pd.isna(value):
        return None

    match = re.fullmatch(r"ERP-PROV-MX-(\d{3})-[A-Z]", str(value))
    return int(match.group(1)) if match else None


def extract_handle_number(value):
    if pd.isna(value):
        return None

    match = re.search(r"-(\d{3})$", str(value))
    return int(match.group(1)) if match else None


# Add extracted numeric components
mapping_check = mappings.copy()

mapping_check["pos_number"] = mapping_check["sku_pos"].apply(extract_pos_number)
mapping_check["erp_number"] = mapping_check["sku_erp"].apply(extract_erp_number)
mapping_check["handle_number"] = mapping_check["handle"].apply(extract_handle_number)


# ---------------------------------------------------------------------
# POS <-> ERP known mappings
# ---------------------------------------------------------------------

pos_erp_known = mapping_check.dropna(subset=["sku_pos", "sku_erp"]).copy()

pos_erp_known["number_match"] = (
    pos_erp_known["pos_number"] == pos_erp_known["erp_number"]
)

print("\nPOS -> ERP known mappings")
print(f"known mappings: {len(pos_erp_known)}")
print(f"numeric matches: {int(pos_erp_known['number_match'].sum())}")
print(f"numeric mismatches: {int((~pos_erp_known['number_match']).sum())}")

if not pos_erp_known["number_match"].all():
    print("\nMismatches:")
    print(
        pos_erp_known.loc[
            ~pos_erp_known["number_match"],
            ["sku_pos", "sku_erp", "pos_number", "erp_number"]
        ].to_string(index=False)
    )


# ---------------------------------------------------------------------
# POS <-> HANDLE known mappings
# ---------------------------------------------------------------------

pos_handle_known = mapping_check.dropna(subset=["sku_pos", "handle"]).copy()

pos_handle_known["number_match"] = (
    pos_handle_known["pos_number"] == pos_handle_known["handle_number"]
)

print("\nPOS -> HANDLE known mappings")
print(f"known mappings: {len(pos_handle_known)}")
print(f"numeric matches: {int(pos_handle_known['number_match'].sum())}")
print(f"numeric mismatches: {int((~pos_handle_known['number_match']).sum())}")

if not pos_handle_known["number_match"].all():
    print("\nMismatches:")
    print(
        pos_handle_known.loc[
            ~pos_handle_known["number_match"],
            ["sku_pos", "handle", "pos_number", "handle_number"]
        ].to_string(index=False)
    )


# ---------------------------------------------------------------------
# ERP catalog numeric-key uniqueness
# ---------------------------------------------------------------------

catalog = pd.DataFrame(inventory["catalogo"]["productos"]).copy()

catalog["erp_number"] = catalog["sku_erp"].apply(extract_erp_number)

print("\nERP catalog numeric-key uniqueness")
print(f"catalog products: {len(catalog)}")
print(f"parsed ERP numbers: {catalog['erp_number'].notna().sum()}")
print(f"unique ERP numbers: {catalog['erp_number'].nunique()}")

duplicate_erp_numbers = catalog[
    catalog["erp_number"].duplicated(keep=False)
].sort_values("erp_number")

print(f"duplicate numeric ERP identifiers: {len(duplicate_erp_numbers)}")

if not duplicate_erp_numbers.empty:
    print(duplicate_erp_numbers[["sku_erp", "erp_number", "nombre"]].to_string(index=False))


# ---------------------------------------------------------------------
# Candidate inference for currently unmapped POS SKUs
# ---------------------------------------------------------------------

print("\nCandidate ERP mappings for unmapped POS SKUs")

unmapped_pos = sorted(sales_skus - mapped_pos)

for sku in unmapped_pos:
    number = extract_pos_number(sku)

    candidates = catalog[catalog["erp_number"] == number]

    print(f"\n{sku} -> numeric component {number:03d}")
    print(f"candidate count: {len(candidates)}")

    if len(candidates) > 0:
        print(
            candidates[
                ["sku_erp", "nombre", "categoria"]
            ].to_string(index=False)
        )


# ---------------------------------------------------------------------
# Candidate inference for currently unmapped ecommerce handles
# ---------------------------------------------------------------------

print("\nCandidate ERP mappings for unmapped ecommerce handles")

for handle in missing_handles:
    number = extract_handle_number(handle)

    candidates = catalog[catalog["erp_number"] == number]

    print(f"\n{handle} -> numeric component {number:03d}")
    print(f"candidate count: {len(candidates)}")

    if len(candidates) > 0:
        print(
            candidates[
                ["sku_erp", "nombre", "categoria"]
            ].to_string(index=False)
        )


# ---------------------------------------------------------------------
# Full three-way consistency where all three identifiers are present
# ---------------------------------------------------------------------

three_way = mapping_check.dropna(
    subset=["sku_pos", "sku_erp", "handle"]
).copy()

three_way["all_match"] = (
    (three_way["pos_number"] == three_way["erp_number"])
    & (three_way["erp_number"] == three_way["handle_number"])
)

print("\nThree-way known mappings")
print(f"rows with POS + ERP + handle: {len(three_way)}")
print(f"all numeric components match: {int(three_way['all_match'].sum())}")
print(f"mismatches: {int((~three_way['all_match']).sum())}")

# ---------------------------------------------------------------------
# 10. PRODUCT ID COLLISION / CONFLICT CHECK
# ---------------------------------------------------------------------

section("10. PRODUCT ID COLLISION / CONFLICT CHECK")


# All POS identifiers actually observed
all_pos = pd.DataFrame({
    "sku_pos": sorted(sales["sku"].dropna().unique())
})
all_pos["number"] = all_pos["sku_pos"].apply(extract_pos_number)


# All ERP identifiers in the catalog
all_erp = catalog[["sku_erp"]].copy()
all_erp["number"] = all_erp["sku_erp"].apply(extract_erp_number)


# All Shopify identifiers actually observed
all_handles = pd.DataFrame({
    "handle": sorted(ecommerce["product_handle"].dropna().unique())
})
all_handles["number"] = all_handles["handle"].apply(extract_handle_number)


print("\nUnparseable identifiers")
print("POS:", int(all_pos["number"].isna().sum()))
print("ERP:", int(all_erp["number"].isna().sum()))
print("Shopify:", int(all_handles["number"].isna().sum()))


def report_collisions(df, number_col, id_col, label):
    collisions = (
        df.groupby(number_col)[id_col]
        .nunique()
        .loc[lambda x: x > 1]
    )

    print(f"\n{label} numeric collisions: {len(collisions)}")

    if not collisions.empty:
        for number in collisions.index:
            values = df.loc[
                df[number_col] == number,
                id_col
            ].unique()

            print(number, "->", list(values))


report_collisions(all_pos, "number", "sku_pos", "POS")
report_collisions(all_erp, "number", "sku_erp", "ERP")
report_collisions(all_handles, "number", "handle", "Shopify")


# Check explicit mapping rows against the numeric rule
explicit_conflicts = []

for _, row in mappings.iterrows():

    pos_num = extract_pos_number(row["sku_pos"])
    erp_num = extract_erp_number(row["sku_erp"])
    handle_num = extract_handle_number(row["handle"])

    known_numbers = [
        x for x in [pos_num, erp_num, handle_num]
        if x is not None
    ]

    if len(set(known_numbers)) > 1:
        explicit_conflicts.append({
            "sku_pos": row["sku_pos"],
            "sku_erp": row["sku_erp"],
            "handle": row["handle"],
            "numbers": known_numbers,
        })


print("\nExplicit mapping conflicts:", len(explicit_conflicts))

if explicit_conflicts:
    print(pd.DataFrame(explicit_conflicts).to_string(index=False))

# ---------------------------------------------------------------------
# 11. INVENTORY SNAPSHOT STRUCTURE
# ---------------------------------------------------------------------

section("11. INVENTORY SNAPSHOT STRUCTURE")

snapshot_check = snapshots.copy()

snapshot_check["fecha_dt"] = pd.to_datetime(snapshot_check["fecha"])
snapshot_check["stock_numeric"] = pd.to_numeric(
    snapshot_check["cantidad_en_stock"],
    errors="coerce"
)


# ---------------------------------------------------------------------
# Date coverage
# ---------------------------------------------------------------------

min_date = snapshot_check["fecha_dt"].min()
max_date = snapshot_check["fecha_dt"].max()

distinct_dates = snapshot_check["fecha_dt"].nunique()

expected_dates = pd.date_range(
    min_date,
    max_date,
    freq="D"
)

observed_dates = pd.DatetimeIndex(
    snapshot_check["fecha_dt"].unique()
)

missing_dates = expected_dates.difference(observed_dates)

print("\nDate coverage")
print(f"first date: {min_date.date()}")
print(f"last date: {max_date.date()}")
print(f"distinct dates: {distinct_dates}")
print(f"expected calendar days: {len(expected_dates)}")
print(f"missing calendar days: {len(missing_dates)}")

if len(missing_dates) > 0:
    print("missing dates:", list(missing_dates))


# ---------------------------------------------------------------------
# Store-SKU pairs
# ---------------------------------------------------------------------

pair_day_counts = (
    snapshot_check
    .groupby(["tienda_id", "sku_erp"])["fecha_dt"]
    .nunique()
)

print("\nStore-SKU pair coverage")
print(f"unique store-SKU pairs: {len(pair_day_counts)}")
print(f"minimum days per pair: {pair_day_counts.min()}")
print(f"maximum days per pair: {pair_day_counts.max()}")
print(f"median days per pair: {pair_day_counts.median()}")

full_coverage_pairs = (pair_day_counts == distinct_dates).sum()
partial_coverage_pairs = (pair_day_counts != distinct_dates).sum()

print(f"pairs with all {distinct_dates} days: {full_coverage_pairs}")
print(f"pairs with partial coverage: {partial_coverage_pairs}")


# Show distribution if there are different coverage lengths
print("\nDays-per-pair distribution:")
print(
    pair_day_counts
    .value_counts()
    .sort_index()
    .to_string()
)


# ---------------------------------------------------------------------
# Rows per day
# ---------------------------------------------------------------------

rows_per_day = (
    snapshot_check
    .groupby("fecha_dt")
    .size()
)

print("\nRows per day")
print(f"minimum rows/day: {rows_per_day.min()}")
print(f"maximum rows/day: {rows_per_day.max()}")
print(f"unique row-count values: {rows_per_day.nunique()}")

print("\nRows/day distribution:")
print(
    rows_per_day
    .value_counts()
    .sort_index()
    .to_string()
)


# ---------------------------------------------------------------------
# Missing numeric stock ('N/A')
# ---------------------------------------------------------------------

na_mask = snapshot_check["stock_numeric"].isna()

print("\nN/A stock distribution")
print(f"N/A rows: {na_mask.sum()}")
print(
    "store-SKU pairs affected by N/A:",
    snapshot_check.loc[
        na_mask,
        ["tienda_id", "sku_erp"]
    ].drop_duplicates().shape[0]
)
print(
    "stores affected by N/A:",
    snapshot_check.loc[na_mask, "tienda_id"].nunique()
)
print(
    "SKUs affected by N/A:",
    snapshot_check.loc[na_mask, "sku_erp"].nunique()
)
print(
    "dates affected by N/A:",
    snapshot_check.loc[na_mask, "fecha_dt"].nunique()
)


# ---------------------------------------------------------------------
# Actual zero stock
# ---------------------------------------------------------------------

zero_mask = snapshot_check["stock_numeric"] == 0

print("\nZero-stock observations")
print(f"zero-stock rows: {zero_mask.sum()}")
print(
    "store-SKU pairs with at least one zero:",
    snapshot_check.loc[
        zero_mask,
        ["tienda_id", "sku_erp"]
    ].drop_duplicates().shape[0]
)
print(
    "stores with at least one zero:",
    snapshot_check.loc[zero_mask, "tienda_id"].nunique()
)
print(
    "SKUs with at least one zero:",
    snapshot_check.loc[zero_mask, "sku_erp"].nunique()
)

# ---------------------------------------------------------------------
# 12. INVENTORY MISSINGNESS BY STORE-SKU
# ---------------------------------------------------------------------

section("12. INVENTORY MISSINGNESS BY STORE-SKU")

missing_by_pair = (
    snapshot_check
    .assign(is_na=snapshot_check["stock_numeric"].isna())
    .groupby(["tienda_id", "sku_erp"])["is_na"]
    .agg(["sum", "count"])
)

missing_by_pair["missing_pct"] = (
    missing_by_pair["sum"] / missing_by_pair["count"] * 100
)

print("\nMissing stock per store-SKU pair")
print(f"minimum N/A days: {missing_by_pair['sum'].min()}")
print(f"maximum N/A days: {missing_by_pair['sum'].max()}")
print(f"median N/A days: {missing_by_pair['sum'].median()}")
print(f"mean N/A days: {missing_by_pair['sum'].mean():.2f}")

print(
    f"maximum missing percentage: "
    f"{missing_by_pair['missing_pct'].max():.2f}%"
)

print("\nN/A-days-per-pair distribution:")
print(
    missing_by_pair["sum"]
    .value_counts()
    .sort_index()
    .to_string()
)

print("\nTop 10 pairs by missing percentage:")
print(
    missing_by_pair
    .sort_values("missing_pct", ascending=False)
    .head(10)
    .to_string()
)

# ---------------------------------------------------------------------
# 13. SALES PRODUCT RECONCILIATION COVERAGE
# ---------------------------------------------------------------------

section("13. SALES PRODUCT RECONCILIATION COVERAGE")


def canonical_erp_from_number(number):
    if pd.isna(number):
        return None

    candidates = catalog.loc[
        catalog["erp_number"] == number,
        "sku_erp"
    ]

    if len(candidates) == 1:
        return candidates.iloc[0]

    return None


# ---------------------------------------------------------------------
# Six-month analysis window
# ---------------------------------------------------------------------

start_date = pd.Timestamp("2025-10-01")
end_date = pd.Timestamp("2026-03-31 23:59:59")


# ---------------------------------------------------------------------
# POS
# ---------------------------------------------------------------------

sales_recon = sales.copy()
sales_recon["fecha_dt"] = pd.to_datetime(sales_recon["fecha_hora"])

sales_6m = sales_recon[
    sales_recon["fecha_dt"].between(start_date, end_date)
].copy()

sales_6m["product_number"] = sales_6m["sku"].apply(
    extract_pos_number
)

sales_6m["canonical_sku_erp"] = sales_6m[
    "product_number"
].apply(canonical_erp_from_number)

sales_6m["mapped"] = sales_6m["canonical_sku_erp"].notna()


print("\nPOS reconciliation coverage")
print(f"rows: {len(sales_6m)}")
print(f"mapped rows: {sales_6m['mapped'].sum()}")
print(f"unmapped rows: {(~sales_6m['mapped']).sum()}")

print(f"total units: {sales_6m['cantidad'].sum()}")
print(
    "mapped units:",
    sales_6m.loc[sales_6m["mapped"], "cantidad"].sum()
)
print(
    "unmapped units:",
    sales_6m.loc[~sales_6m["mapped"], "cantidad"].sum()
)


# ---------------------------------------------------------------------
# Shopify
# ---------------------------------------------------------------------

ecommerce_recon = ecommerce.copy()
ecommerce_recon["fecha_dt"] = pd.to_datetime(
    ecommerce_recon["fecha"]
)

ecommerce_6m = ecommerce_recon[
    ecommerce_recon["fecha_dt"].between(start_date, end_date)
].copy()

ecommerce_6m["product_number"] = ecommerce_6m[
    "product_handle"
].apply(extract_handle_number)

ecommerce_6m["canonical_sku_erp"] = ecommerce_6m[
    "product_number"
].apply(canonical_erp_from_number)

ecommerce_6m["mapped"] = ecommerce_6m[
    "canonical_sku_erp"
].notna()


print("\nShopify reconciliation coverage")
print(f"rows: {len(ecommerce_6m)}")
print(f"mapped rows: {ecommerce_6m['mapped'].sum()}")
print(f"unmapped rows: {(~ecommerce_6m['mapped']).sum()}")

print(f"total units: {ecommerce_6m['cantidad'].sum()}")
print(
    "mapped units:",
    ecommerce_6m.loc[
        ecommerce_6m["mapped"],
        "cantidad"
    ].sum()
)
print(
    "unmapped units:",
    ecommerce_6m.loc[
        ~ecommerce_6m["mapped"],
        "cantidad"
    ].sum()
)

# ---------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------

section("VALIDATION COMPLETE")

print(
    "This script only verifies critical Source Discovery facts. "
    "It does not transform data or define business rules."
)