import re

import pandas as pd


POS_PATTERN = re.compile(r"CN-(\d{5})$")
ERP_PATTERN = re.compile(r"ERP-PROV-MX-(\d{3})-[A-Z]$")
HANDLE_PATTERN = re.compile(r"-(\d{3})$")


def extract_pos_number(value):
    """Extract the numeric product component from a POS SKU."""
    if pd.isna(value):
        return None

    match = POS_PATTERN.fullmatch(str(value))
    return int(match.group(1)) if match else None


def extract_erp_number(value):
    """Extract the numeric product component from an ERP SKU."""
    if pd.isna(value):
        return None

    match = ERP_PATTERN.fullmatch(str(value))
    return int(match.group(1)) if match else None


def extract_handle_number(value):
    """Extract the numeric product component from a Shopify handle."""
    if pd.isna(value):
        return None

    match = HANDLE_PATTERN.search(str(value))
    return int(match.group(1)) if match else None


def _validate_explicit_mapping(
    mapping: pd.DataFrame,
    source_column: str,
    label: str,
) -> None:
    """
    Ensure one source identifier does not explicitly map
    to multiple ERP products.
    """

    conflicts = (
        mapping
        .groupby(source_column)["sku_erp"]
        .nunique()
    )

    conflicts = conflicts[conflicts > 1]

    if not conflicts.empty:
        raise ValueError(
            f"Conflicting explicit {label} mappings found for: "
            f"{conflicts.index.tolist()}"
        )


def build_product_bridge(
    sales: pd.DataFrame,
    ecommerce: pd.DataFrame,
    inventory: dict,
) -> pd.DataFrame:
    """
    Build the canonical product bridge.

    Resolution order:
    1. Use explicit source mappings from inventory.json.
    2. Only when an explicit ERP relationship is missing,
       use the validated numeric product component as fallback.
    """

    catalog = pd.DataFrame(
        inventory["catalogo"]["productos"]
    )[["sku_erp", "nombre", "categoria"]].copy()

    mappings = pd.DataFrame(
        inventory["sku_mappings"]
    ).copy()

    # ------------------------------------------------------------------
    # Validate expected mapping structure
    # ------------------------------------------------------------------

    required_mapping_columns = {
        "sku_pos",
        "sku_erp",
        "handle",
    }

    missing_columns = (
        required_mapping_columns
        - set(mappings.columns)
    )

    if missing_columns:
        raise ValueError(
            "sku_mappings is missing required columns: "
            f"{sorted(missing_columns)}"
        )

    # ------------------------------------------------------------------
    # ERP catalog
    # ------------------------------------------------------------------

    if catalog["sku_erp"].duplicated().any():
        raise ValueError(
            "ERP catalog contains duplicate sku_erp values."
        )

    catalog["product_number"] = (
        catalog["sku_erp"]
        .apply(extract_erp_number)
    )

    # Numeric identifiers are used only for fallback inference.
    numeric_catalog = catalog[
        catalog["product_number"].notna()
    ].copy()

    if numeric_catalog["product_number"].duplicated().any():
        raise ValueError(
            "ERP numeric product identifiers are not unique. "
            "Numeric fallback is unsafe."
        )

    erp_by_number = dict(
        zip(
            numeric_catalog["product_number"],
            numeric_catalog["sku_erp"],
        )
    )

    catalog_skus = set(catalog["sku_erp"])

    # ------------------------------------------------------------------
    # Explicit POS -> ERP mappings
    # ------------------------------------------------------------------

    explicit_pos = (
        mappings
        .dropna(subset=["sku_pos", "sku_erp"])
        [["sku_pos", "sku_erp"]]
        .drop_duplicates()
        .copy()
    )

    _validate_explicit_mapping(
        explicit_pos,
        "sku_pos",
        "POS-to-ERP",
    )

    unknown_pos_targets = (
        set(explicit_pos["sku_erp"])
        - catalog_skus
    )

    if unknown_pos_targets:
        raise ValueError(
            "Explicit POS mappings reference ERP products "
            "not present in the catalog: "
            f"{sorted(unknown_pos_targets)}"
        )

    # If both identifiers follow the known numeric convention,
    # they must not contradict each other.
    explicit_pos["pos_number"] = (
        explicit_pos["sku_pos"]
        .apply(extract_pos_number)
    )

    explicit_pos["erp_number"] = (
        explicit_pos["sku_erp"]
        .apply(extract_erp_number)
    )

    pos_pattern_conflicts = explicit_pos[
        explicit_pos["pos_number"].notna()
        & explicit_pos["erp_number"].notna()
        & (
            explicit_pos["pos_number"]
            != explicit_pos["erp_number"]
        )
    ]

    if not pos_pattern_conflicts.empty:
        raise ValueError(
            "An explicit POS-to-ERP mapping contradicts "
            "the validated numeric fallback rule."
        )

    explicit_pos = explicit_pos[
        ["sku_pos", "sku_erp"]
    ]

    # ------------------------------------------------------------------
    # Explicit Shopify -> ERP mappings
    # ------------------------------------------------------------------

    explicit_shopify = (
        mappings
        .dropna(subset=["handle", "sku_erp"])
        [["handle", "sku_erp"]]
        .drop_duplicates()
        .copy()
    )

    _validate_explicit_mapping(
        explicit_shopify,
        "handle",
        "Shopify-to-ERP",
    )

    unknown_shopify_targets = (
        set(explicit_shopify["sku_erp"])
        - catalog_skus
    )

    if unknown_shopify_targets:
        raise ValueError(
            "Explicit Shopify mappings reference ERP products "
            "not present in the catalog: "
            f"{sorted(unknown_shopify_targets)}"
        )

    explicit_shopify["handle_number"] = (
        explicit_shopify["handle"]
        .apply(extract_handle_number)
    )

    explicit_shopify["erp_number"] = (
        explicit_shopify["sku_erp"]
        .apply(extract_erp_number)
    )

    shopify_pattern_conflicts = explicit_shopify[
        explicit_shopify["handle_number"].notna()
        & explicit_shopify["erp_number"].notna()
        & (
            explicit_shopify["handle_number"]
            != explicit_shopify["erp_number"]
        )
    ]

    if not shopify_pattern_conflicts.empty:
        raise ValueError(
            "An explicit Shopify-to-ERP mapping contradicts "
            "the validated numeric fallback rule."
        )

    explicit_shopify = explicit_shopify[
        ["handle", "sku_erp"]
    ]

    # ------------------------------------------------------------------
    # Resolve observed POS products
    # ------------------------------------------------------------------

    pos_products = pd.DataFrame({
    "sku_pos": pd.Series(
        sorted(
            sales["sku"]
            .dropna()
            .unique()
        ),
        dtype="object",
    )
    })

    # Explicit mapping is applied first.
    pos_products = pos_products.merge(
        explicit_pos,
        on="sku_pos",
        how="left",
        validate="one_to_one",
    )

    pos_products["mapping_method"] = (
        pos_products["sku_erp"]
        .notna()
        .map({
            True: "explicit",
            False: "inferred_numeric_pattern",
        })
    )

    pos_products["product_number"] = (
        pos_products["sku_pos"]
        .apply(extract_pos_number)
    )

    # Only rows without an explicit mapping use numeric fallback.
    pos_needs_fallback = (
        pos_products["sku_erp"].isna()
    )

    pos_fallback = pos_products.loc[
        pos_needs_fallback,
        ["sku_pos", "product_number"],
    ].copy()

    pos_fallback["fallback_sku_erp"] = (
        pos_fallback["product_number"]
        .map(erp_by_number)
    )

    invalid_pos_fallback = pos_fallback[
        pos_fallback["product_number"].isna()
        | pos_fallback["fallback_sku_erp"].isna()
    ]

    if not invalid_pos_fallback.empty:
        raise ValueError(
            "POS SKUs without an explicit mapping could not "
            "be resolved safely by numeric fallback: "
            f"{sorted(invalid_pos_fallback['sku_pos'].tolist())}"
        )

    pos_products.loc[
        pos_fallback.index,
        "sku_erp",
    ] = pos_fallback["fallback_sku_erp"]

    # Current analytical model expects at most one observed
    # POS identifier per canonical ERP product.
    if pos_products["sku_erp"].duplicated().any():
        duplicates = sorted(
            pos_products.loc[
                pos_products["sku_erp"].duplicated(
                    keep=False
                ),
                "sku_erp",
            ].unique()
        )

        raise ValueError(
            "Multiple observed POS SKUs resolve to the same "
            f"ERP product: {duplicates}"
        )

    # ------------------------------------------------------------------
    # Resolve observed Shopify products
    # ------------------------------------------------------------------

    shopify_products = pd.DataFrame({
    "product_handle": pd.Series(
        sorted(
            ecommerce["product_handle"]
            .dropna()
            .unique()
        ),
        dtype="object",
    )
    })

    # Explicit mapping is applied first.
    shopify_products = shopify_products.merge(
        explicit_shopify.rename(
            columns={
                "handle": "product_handle"
            }
        ),
        on="product_handle",
        how="left",
        validate="one_to_one",
    )

    shopify_products["mapping_method"] = (
        shopify_products["sku_erp"]
        .notna()
        .map({
            True: "explicit",
            False: "inferred_numeric_pattern",
        })
    )

    shopify_products["product_number"] = (
        shopify_products["product_handle"]
        .apply(extract_handle_number)
    )

    # Only rows without an explicit mapping use numeric fallback.
    shopify_needs_fallback = (
        shopify_products["sku_erp"].isna()
    )

    shopify_fallback = shopify_products.loc[
        shopify_needs_fallback,
        ["product_handle", "product_number"],
    ].copy()

    shopify_fallback["fallback_sku_erp"] = (
        shopify_fallback["product_number"]
        .map(erp_by_number)
    )

    invalid_shopify_fallback = shopify_fallback[
        shopify_fallback["product_number"].isna()
        | shopify_fallback["fallback_sku_erp"].isna()
    ]

    if not invalid_shopify_fallback.empty:
        raise ValueError(
            "Shopify handles without an explicit mapping "
            "could not be resolved safely by numeric fallback: "
            f"{sorted(invalid_shopify_fallback['product_handle'].tolist())}"
        )

    shopify_products.loc[
        shopify_fallback.index,
        "sku_erp",
    ] = shopify_fallback["fallback_sku_erp"]

    if shopify_products["sku_erp"].duplicated().any():
        duplicates = sorted(
            shopify_products.loc[
                shopify_products["sku_erp"].duplicated(
                    keep=False
                ),
                "sku_erp",
            ].unique()
        )

        raise ValueError(
            "Multiple observed Shopify handles resolve to "
            f"the same ERP product: {duplicates}"
        )

    # ------------------------------------------------------------------
    # Build canonical bridge around ERP catalog
    # ------------------------------------------------------------------

    pos_for_bridge = pos_products[
        [
            "sku_erp",
            "sku_pos",
            "mapping_method",
        ]
    ].rename(
        columns={
            "mapping_method": "pos_mapping_method"
        }
    )

    shopify_for_bridge = shopify_products[
        [
            "sku_erp",
            "product_handle",
            "mapping_method",
        ]
    ].rename(
        columns={
            "mapping_method": "shopify_mapping_method"
        }
    )

    bridge = (
        catalog
        .merge(
            pos_for_bridge,
            on="sku_erp",
            how="left",
            validate="one_to_one",
        )
        .merge(
            shopify_for_bridge,
            on="sku_erp",
            how="left",
            validate="one_to_one",
        )
    )

    bridge["pos_mapping_method"] = (
        bridge["pos_mapping_method"]
        .fillna("not_observed")
    )

    bridge["shopify_mapping_method"] = (
        bridge["shopify_mapping_method"]
        .fillna("not_observed")
    )

    return bridge[
        [
            "sku_erp",
            "nombre",
            "categoria",
            "sku_pos",
            "product_handle",
            "product_number",
            "pos_mapping_method",
            "shopify_mapping_method",
        ]
    ]


def reconcile_sales_products(
    sales: pd.DataFrame,
    product_bridge: pd.DataFrame,
) -> pd.DataFrame:
    """Attach the canonical ERP SKU to every POS sales record."""

    pos_bridge = (
        product_bridge
        .loc[
            product_bridge["sku_pos"].notna(),
            ["sku_pos", "sku_erp"],
        ]
        .copy()
    )

    reconciled = sales.merge(
        pos_bridge,
        left_on="sku",
        right_on="sku_pos",
        how="left",
        validate="many_to_one",
    )

    missing = reconciled["sku_erp"].isna()

    if missing.any():
        missing_skus = sorted(
            reconciled.loc[
                missing,
                "sku",
            ].unique()
        )

        raise ValueError(
            f"Unreconciled POS SKUs: {missing_skus}"
        )

    return reconciled.drop(
        columns=["sku_pos"]
    )


def reconcile_ecommerce_products(
    ecommerce: pd.DataFrame,
    product_bridge: pd.DataFrame,
) -> pd.DataFrame:
    """Attach the canonical ERP SKU to every Shopify order record."""

    shopify_bridge = (
        product_bridge
        .loc[
            product_bridge["product_handle"].notna(),
            ["product_handle", "sku_erp"],
        ]
        .copy()
    )

    reconciled = ecommerce.merge(
        shopify_bridge,
        on="product_handle",
        how="left",
        validate="many_to_one",
    )

    missing = reconciled["sku_erp"].isna()

    if missing.any():
        missing_handles = sorted(
            reconciled.loc[
                missing,
                "product_handle",
            ].unique()
        )

        raise ValueError(
            "Unreconciled Shopify handles: "
            f"{missing_handles}"
        )

    return reconciled