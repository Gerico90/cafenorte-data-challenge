import pandas as pd
import pytest

from src.reconcile import (
    extract_pos_number,
    extract_erp_number,
    extract_handle_number,
    build_product_bridge,
)


def test_identifier_number_extraction():
    assert extract_pos_number("CN-00030") == 30
    assert extract_erp_number("ERP-PROV-MX-030-C") == 30
    assert extract_handle_number("molinillo-mercancia-030") == 30


def test_explicit_mapping_does_not_require_numeric_pattern():
    sales = pd.DataFrame({
        "sku": ["SPECIAL-POS-CODE"]
    })

    ecommerce = pd.DataFrame({
        "product_handle": []
    })

    inventory = {
        "catalogo": {
            "productos": [
                {
                    "sku_erp": "ERP-PROV-MX-030-C",
                    "nombre": "Molinillo Mercancia",
                    "categoria": "mercancia",
                }
            ]
        },
        "sku_mappings": [
            {
                "sku_pos": "SPECIAL-POS-CODE",
                "sku_erp": "ERP-PROV-MX-030-C",
                "handle": None,
            }
        ],
    }

    bridge = build_product_bridge(
        sales,
        ecommerce,
        inventory,
    )

    row = bridge.iloc[0]

    assert row["sku_erp"] == "ERP-PROV-MX-030-C"
    assert row["sku_pos"] == "SPECIAL-POS-CODE"
    assert row["pos_mapping_method"] == "explicit"


def test_numeric_fallback_when_explicit_mapping_is_missing():
    sales = pd.DataFrame({
        "sku": ["CN-00030"]
    })

    ecommerce = pd.DataFrame({
        "product_handle": ["molinillo-mercancia-030"]
    })

    inventory = {
        "catalogo": {
            "productos": [
                {
                    "sku_erp": "ERP-PROV-MX-030-C",
                    "nombre": "Molinillo Mercancia",
                    "categoria": "mercancia",
                }
            ]
        },
        "sku_mappings": [
            {
                "sku_pos": None,
                "sku_erp": None,
                "handle": None,
            }
        ],
    }

    bridge = build_product_bridge(
        sales,
        ecommerce,
        inventory,
    )

    row = bridge.iloc[0]

    assert row["sku_erp"] == "ERP-PROV-MX-030-C"

    assert (
        row["pos_mapping_method"]
        == "inferred_numeric_pattern"
    )

    assert (
        row["shopify_mapping_method"]
        == "inferred_numeric_pattern"
    )


def test_conflicting_explicit_mapping_fails():
    sales = pd.DataFrame({
        "sku": ["CN-00030"]
    })

    ecommerce = pd.DataFrame({
        "product_handle": []
    })

    inventory = {
        "catalogo": {
            "productos": [
                {
                    "sku_erp": "ERP-PROV-MX-030-C",
                    "nombre": "Molinillo",
                    "categoria": "mercancia",
                },
                {
                    "sku_erp": "ERP-PROV-MX-031-A",
                    "nombre": "Termo",
                    "categoria": "mercancia",
                },
            ]
        },
        "sku_mappings": [
            {
                "sku_pos": "CN-00030",
                "sku_erp": "ERP-PROV-MX-030-C",
                "handle": None,
            },
            {
                "sku_pos": "CN-00030",
                "sku_erp": "ERP-PROV-MX-031-A",
                "handle": None,
            },
        ],
    }

    with pytest.raises(ValueError):
        build_product_bridge(
            sales,
            ecommerce,
            inventory,
        )