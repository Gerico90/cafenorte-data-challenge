import pandas as pd

from src.transform import (
    build_fact_sales,
    build_fact_inventory,
    build_fact_product_cost,
)


def test_fact_sales_combines_physical_and_ecommerce():
    physical = pd.DataFrame({
        "venta_id": ["V0001"],
        "fecha_hora": ["2026-01-10 10:30:00"],
        "tienda_id": ["T001"],
        "sku": ["CN-00030"],
        "cantidad": [2],
        "monto": [200.0],
        "moneda": ["MXN"],
        "tipo_comprobante": ["I"],
        "sku_erp": ["ERP-PROV-MX-030-C"],
    })

    ecommerce = pd.DataFrame({
        "order_id": ["SHOP-0001"],
        "fecha": ["2026-01-10 12:00:00"],
        "product_handle": ["molinillo-mercancia-030"],
        "cantidad": [1],
        "amount": [15.0],
        "currency": ["USD"],
        "sku_erp": ["ERP-PROV-MX-030-C"],
    })

    result = build_fact_sales(
        physical,
        ecommerce,
    )

    assert len(result) == 2

    physical_row = result[
        result["channel"] == "physical"
    ].iloc[0]

    ecommerce_row = result[
        result["channel"] == "ecommerce"
    ].iloc[0]

    assert physical_row["transaction_id"] == "V0001"
    assert physical_row["store_id"] == "T001"
    assert physical_row["quantity"] == 2
    assert physical_row["amount_native"] == 200.0
    assert physical_row["currency"] == "MXN"

    assert ecommerce_row["transaction_id"] == "SHOP-0001"
    assert pd.isna(ecommerce_row["store_id"])
    assert ecommerce_row["quantity"] == 1
    assert ecommerce_row["amount_native"] == 15.0
    assert ecommerce_row["currency"] == "USD"


def test_inventory_preserves_zero_and_na_as_different_values():
    inventory = {
        "snapshots": [
            {
                "fecha": "2026-01-01",
                "tienda_id": "T001",
                "sku_erp": "ERP-PROV-MX-030-C",
                "cantidad_en_stock": 0,
            },
            {
                "fecha": "2026-01-02",
                "tienda_id": "T001",
                "sku_erp": "ERP-PROV-MX-030-C",
                "cantidad_en_stock": "N/A",
            },
            {
                "fecha": "2026-01-03",
                "tienda_id": "T001",
                "sku_erp": "ERP-PROV-MX-030-C",
                "cantidad_en_stock": 5,
            },
        ]
    }

    result = build_fact_inventory(inventory)

    assert len(result) == 3

    assert result.loc[0, "stock_quantity"] == 0
    assert pd.isna(result.loc[1, "stock_quantity"])
    assert result.loc[2, "stock_quantity"] == 5


def test_product_cost_preserves_full_history():
    inventory = {
        "catalogo": {
            "productos": [
                {
                    "sku_erp": "ERP-PROV-MX-030-C",
                    "nombre": "Molinillo Mercancia",
                    "categoria": "mercancia",
                    "cost_history": [
                        {
                            "fecha_vigencia": "2025-01-01",
                            "costo_mxn": 100.0,
                            "proveedor": "Proveedor A",
                        },
                        {
                            "fecha_vigencia": "2026-01-01",
                            "costo_mxn": 120.0,
                            "proveedor": "Proveedor B",
                        },
                    ],
                }
            ]
        }
    }

    result = build_fact_product_cost(inventory)

    assert len(result) == 2

    assert result.iloc[0]["cost_mxn"] == 100.0
    assert result.iloc[1]["cost_mxn"] == 120.0

    assert result.iloc[0]["supplier"] == "Proveedor A"
    assert result.iloc[1]["supplier"] == "Proveedor B"

    assert result.iloc[0]["effective_date"] == pd.Timestamp(
        "2025-01-01"
    )

    assert result.iloc[1]["effective_date"] == pd.Timestamp(
        "2026-01-01"
    )