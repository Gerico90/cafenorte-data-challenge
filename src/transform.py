import pandas as pd


def _require_columns(
    dataframe: pd.DataFrame,
    required_columns: set[str],
    dataframe_name: str,
) -> None:
    """Fail clearly if an expected source column is missing."""

    missing = required_columns - set(dataframe.columns)

    if missing:
        raise ValueError(
            f"{dataframe_name} is missing required columns: "
            f"{sorted(missing)}"
        )


# ---------------------------------------------------------------------
# DIM PRODUCT
# ---------------------------------------------------------------------

def build_dim_product(
    product_bridge: pd.DataFrame,
) -> pd.DataFrame:
    """Build the canonical product dimension."""

    required = {
        "sku_erp",
        "nombre",
        "categoria",
        "sku_pos",
        "product_handle",
        "product_number",
        "pos_mapping_method",
        "shopify_mapping_method",
    }

    _require_columns(
        product_bridge,
        required,
        "product_bridge",
    )

    dim_product = product_bridge[
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
    ].copy()

    dim_product = dim_product.rename(
        columns={
            "sku_erp": "product_id",
            "nombre": "product_name",
            "categoria": "category",
        }
    )

    if dim_product["product_id"].duplicated().any():
        raise ValueError(
            "dim_product contains duplicate product_id values."
        )

    return dim_product.reset_index(drop=True)


# ---------------------------------------------------------------------
# DIM STORE
# ---------------------------------------------------------------------

def build_dim_store(
    inventory: dict,
) -> pd.DataFrame:
    """Build the physical-store dimension from ERP store metadata."""

    stores = pd.DataFrame(
        inventory["tiendas_info"]
    ).copy()

    required = {
        "tienda_id",
        "ciudad",
        "region",
        "timezone",
    }

    _require_columns(
        stores,
        required,
        "tiendas_info",
    )

    dim_store = stores.rename(
        columns={
            "tienda_id": "store_id",
            "ciudad": "city",
        }
    )

    if dim_store["store_id"].duplicated().any():
        raise ValueError(
            "dim_store contains duplicate store_id values."
        )

    return dim_store[
        [
            "store_id",
            "city",
            "region",
            "timezone",
        ]
    ].reset_index(drop=True)


# ---------------------------------------------------------------------
# FACT SALES
# ---------------------------------------------------------------------

def build_fact_sales(
    reconciled_sales: pd.DataFrame,
    reconciled_ecommerce: pd.DataFrame,
) -> pd.DataFrame:
    """
    Build one sales fact table for both physical and e-commerce channels.

    Monetary values remain in their source currency at this stage.
    """

    sales_required = {
        "venta_id",
        "fecha_hora",
        "tienda_id",
        "sku",
        "cantidad",
        "monto",
        "moneda",
        "tipo_comprobante",
        "sku_erp",
    }

    ecommerce_required = {
        "order_id",
        "fecha",
        "product_handle",
        "cantidad",
        "amount",
        "currency",
        "sku_erp",
    }

    _require_columns(
        reconciled_sales,
        sales_required,
        "reconciled_sales",
    )

    _require_columns(
        reconciled_ecommerce,
        ecommerce_required,
        "reconciled_ecommerce",
    )

    # Physical POS sales
    physical = pd.DataFrame({
        "transaction_id": reconciled_sales["venta_id"],
        "sold_at": pd.to_datetime(
            reconciled_sales["fecha_hora"],
            errors="raise",
        ),
        "product_id": reconciled_sales["sku_erp"],
        "channel": "physical",
        "store_id": reconciled_sales["tienda_id"],
        "quantity": reconciled_sales["cantidad"],
        "amount_native": reconciled_sales["monto"],
        "currency": reconciled_sales["moneda"],
        "document_type": reconciled_sales["tipo_comprobante"],
    })

    # Shopify sales
    ecommerce = pd.DataFrame({
        "transaction_id": reconciled_ecommerce["order_id"],
        "sold_at": pd.to_datetime(
            reconciled_ecommerce["fecha"],
            errors="raise",
        ),
        "product_id": reconciled_ecommerce["sku_erp"],
        "channel": "ecommerce",
        "store_id": pd.NA,
        "quantity": reconciled_ecommerce["cantidad"],
        "amount_native": reconciled_ecommerce["amount"],
        "currency": reconciled_ecommerce["currency"],
        "document_type": pd.NA,
    })

    fact_sales = pd.concat(
        [physical, ecommerce],
        ignore_index=True,
    )

    fact_sales["quantity"] = pd.to_numeric(
        fact_sales["quantity"],
        errors="raise",
    ).astype("Int64")

    fact_sales["amount_native"] = pd.to_numeric(
        fact_sales["amount_native"],
        errors="raise",
    )

    return fact_sales


# ---------------------------------------------------------------------
# FACT INVENTORY
# ---------------------------------------------------------------------

def build_fact_inventory(
    inventory: dict,
) -> pd.DataFrame:
    """Build the daily store-product inventory fact table."""

    snapshots = pd.DataFrame(
        inventory["snapshots"]
    ).copy()

    required = {
        "fecha",
        "tienda_id",
        "sku_erp",
        "cantidad_en_stock",
    }

    _require_columns(
        snapshots,
        required,
        "inventory snapshots",
    )

    fact_inventory = pd.DataFrame({
        "date": pd.to_datetime(
            snapshots["fecha"],
            errors="raise",
        ),
        "store_id": snapshots["tienda_id"],
        "product_id": snapshots["sku_erp"],
        "stock_quantity": pd.to_numeric(
            snapshots["cantidad_en_stock"],
            errors="coerce",
        ),
    })

    # Nullable integer preserves source N/A as missing instead of zero.
    fact_inventory["stock_quantity"] = (
        fact_inventory["stock_quantity"]
        .astype("Int64")
    )

    return fact_inventory


# ---------------------------------------------------------------------
# FACT PRODUCT COST
# ---------------------------------------------------------------------

def build_fact_product_cost(
    inventory: dict,
) -> pd.DataFrame:
    """Flatten ERP product cost history into an analytical table."""

    products = inventory["catalogo"]["productos"]

    rows = []

    for product in products:
        product_id = product["sku_erp"]

        for cost_entry in product["cost_history"]:
            rows.append({
                "product_id": product_id,
                "effective_date": cost_entry["fecha_vigencia"],
                "cost_mxn": cost_entry["costo_mxn"],
                "supplier": cost_entry["proveedor"],
            })

    fact_product_cost = pd.DataFrame(rows)

    fact_product_cost["effective_date"] = pd.to_datetime(
        fact_product_cost["effective_date"],
        errors="raise",
    )

    fact_product_cost["cost_mxn"] = pd.to_numeric(
        fact_product_cost["cost_mxn"],
        errors="raise",
    )

    if fact_product_cost.duplicated(
        subset=["product_id", "effective_date"]
    ).any():
        raise ValueError(
            "Multiple cost records exist for the same "
            "product and effective date."
        )

    return (
        fact_product_cost
        .sort_values(
            ["product_id", "effective_date"]
        )
        .reset_index(drop=True)
    )


# ---------------------------------------------------------------------
# FACT EXCHANGE RATE
# ---------------------------------------------------------------------

def build_fact_exchange_rate(
    exchange_rates: pd.DataFrame,
) -> pd.DataFrame:
    """
    Build the daily currency exchange rate fact table.

    Grain: one row per (rate_date, currency). Rates are used to convert
    non-MXN transaction amounts to MXN by matching on the transaction's
    calendar date and currency -- never averaged, interpolated, or
    otherwise altered.
    """

    required = {
        "fecha",
        "currency",
        "rate_to_mxn",
    }

    _require_columns(
        exchange_rates,
        required,
        "exchange_rates",
    )

    fact_exchange_rate = pd.DataFrame({
        "rate_date": pd.to_datetime(
            exchange_rates["fecha"],
            errors="raise",
        ).dt.date,
        "currency": exchange_rates["currency"],
        "rate_to_mxn": pd.to_numeric(
            exchange_rates["rate_to_mxn"],
            errors="raise",
        ),
    })

    if fact_exchange_rate.duplicated(
        subset=["rate_date", "currency"]
    ).any():
        raise ValueError(
            "exchange_rates contains multiple rates for the same "
            "date and currency. Refusing to silently pick one -- "
            "this is a data-integrity issue that must be resolved "
            "upstream."
        )

    return (
        fact_exchange_rate
        .sort_values(["rate_date", "currency"])
        .reset_index(drop=True)
    )


# ---------------------------------------------------------------------
# COMPLETE ANALYTICAL MODEL
# ---------------------------------------------------------------------

def build_analytical_model(
    reconciled_sales: pd.DataFrame,
    reconciled_ecommerce: pd.DataFrame,
    inventory: dict,
    product_bridge: pd.DataFrame,
    exchange_rates: pd.DataFrame,
) -> dict[str, pd.DataFrame]:
    """Build all normalized analytical tables."""

    return {
        "dim_product": build_dim_product(
            product_bridge
        ),
        "dim_store": build_dim_store(
            inventory
        ),
        "fact_sales": build_fact_sales(
            reconciled_sales,
            reconciled_ecommerce,
        ),
        "fact_inventory": build_fact_inventory(
            inventory
        ),
        "fact_product_cost": build_fact_product_cost(
            inventory
        ),
        "fact_exchange_rate": build_fact_exchange_rate(
            exchange_rates
        ),
    }