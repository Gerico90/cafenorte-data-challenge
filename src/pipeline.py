from pathlib import Path

import duckdb

from src.load import load_sources
from src.reconcile import (
    build_product_bridge,
    reconcile_sales_products,
    reconcile_ecommerce_products,
)
from src.transform import build_analytical_model


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PROCESSED_DATA_DIR = PROJECT_ROOT / "data" / "processed"
DATABASE_PATH = PROCESSED_DATA_DIR / "cafenorte.duckdb"


def persist_analytical_model(
    model: dict,
    database_path: Path = DATABASE_PATH,
) -> None:
    """Persist analytical tables into DuckDB."""

    database_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    connection = duckdb.connect(str(database_path))

    try:
        for table_name, dataframe in model.items():
            connection.register(
                f"{table_name}_df",
                dataframe,
            )

            connection.execute(
                f"""
                CREATE OR REPLACE TABLE {table_name} AS
                SELECT *
                FROM {table_name}_df
                """
            )

            connection.unregister(
                f"{table_name}_df"
            )

    finally:
        connection.close()


def run_pipeline(
    database_path: Path = DATABASE_PATH,
) -> None:
    """Run the complete local analytical pipeline."""

    sources = load_sources()

    product_bridge = build_product_bridge(
        sources["sales"],
        sources["ecommerce"],
        sources["inventory"],
    )

    reconciled_sales = reconcile_sales_products(
        sources["sales"],
        product_bridge,
    )

    reconciled_ecommerce = reconcile_ecommerce_products(
        sources["ecommerce"],
        product_bridge,
    )

    model = build_analytical_model(
        reconciled_sales,
        reconciled_ecommerce,
        sources["inventory"],
        product_bridge,
    )

    persist_analytical_model(
        model,
        database_path,
    )


if __name__ == "__main__":
    run_pipeline()

    print(
        f"Analytical model persisted to: "
        f"{DATABASE_PATH}"
    )