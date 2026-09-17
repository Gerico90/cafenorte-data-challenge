from pathlib import Path

import duckdb
import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATABASE_PATH = PROJECT_ROOT / "data" / "processed" / "cafenorte.duckdb"


def get_q1_inventory_turnover(
    database_path: Path = DATABASE_PATH,
    limit: int = 10,
) -> pd.DataFrame:
    """
    Return the top SKUs by inventory turnover for the latest
    six calendar months available in the inventory data.

    Turnover =
        total units sold across physical + ecommerce channels
        / average ERP inventory

    Source inventory N/A values remain NULL and are therefore
    excluded from AVG calculations rather than treated as zero.
    """

    connection = duckdb.connect(
        str(database_path),
        read_only=True,
    )

    try:
        query = """
        WITH analysis_window AS (
            SELECT
                MAX(date) AS end_date,
                DATE_TRUNC('month', MAX(date))
                    - INTERVAL '5 months' AS start_date
            FROM fact_inventory
        ),

        sales_6m AS (
            SELECT
                s.product_id,

                SUM(
                    CASE
                        WHEN s.channel = 'physical'
                        THEN s.quantity
                        ELSE 0
                    END
                ) AS physical_units,

                SUM(
                    CASE
                        WHEN s.channel = 'ecommerce'
                        THEN s.quantity
                        ELSE 0
                    END
                ) AS ecommerce_units,

                SUM(s.quantity) AS total_units_sold

            FROM fact_sales AS s
            CROSS JOIN analysis_window AS w

            WHERE CAST(s.sold_at AS DATE)
                BETWEEN w.start_date AND w.end_date

            GROUP BY
                s.product_id
        ),

        inventory_by_store_product AS (
            SELECT
                i.store_id,
                i.product_id,

                AVG(i.stock_quantity) AS avg_stock,

                COUNT(i.stock_quantity) AS observed_days,
                COUNT(*) AS expected_days

            FROM fact_inventory AS i
            CROSS JOIN analysis_window AS w

            WHERE i.date
                BETWEEN w.start_date AND w.end_date

            GROUP BY
                i.store_id,
                i.product_id
        ),

        inventory_by_product AS (
            SELECT
                product_id,

                SUM(avg_stock) AS avg_inventory,

                COUNT(DISTINCT store_id) AS store_count,

                SUM(observed_days) AS observed_inventory_days,
                SUM(expected_days) AS expected_inventory_days

            FROM inventory_by_store_product

            GROUP BY
                product_id
        )

        SELECT
            p.product_id,
            p.product_name,
            p.category,

            COALESCE(s.physical_units, 0) AS physical_units,
            COALESCE(s.ecommerce_units, 0) AS ecommerce_units,
            COALESCE(s.total_units_sold, 0) AS total_units_sold,

            i.avg_inventory,
            i.store_count,

            ROUND(
                100.0
                * i.observed_inventory_days
                / i.expected_inventory_days,
                2
            ) AS inventory_coverage_pct,

            CASE
                WHEN i.avg_inventory > 0
                THEN
                    COALESCE(s.total_units_sold, 0)
                    / i.avg_inventory
                ELSE NULL
            END AS inventory_turnover

        FROM dim_product AS p

        LEFT JOIN sales_6m AS s
            ON p.product_id = s.product_id

        LEFT JOIN inventory_by_product AS i
            ON p.product_id = i.product_id

        WHERE i.avg_inventory IS NOT NULL

        ORDER BY
            inventory_turnover DESC NULLS LAST

        LIMIT ?
        """

        return connection.execute(
            query,
            [limit],
        ).fetchdf()

    finally:
        connection.close()

def get_q2_stockouts(
    database_path: Path = DATABASE_PATH,
) -> pd.DataFrame:
    """
    Return store-product stockout events lasting more than
    3 consecutive days during the latest calendar quarter
    available in inventory data.

    NULL inventory values break a zero-stock streak.
    """

    connection = duckdb.connect(
        str(database_path),
        read_only=True,
    )

    try:
        query = """
        WITH quarter_window AS (
            SELECT
                CAST(
                    DATE_TRUNC('quarter', MAX(date))
                    AS DATE
                ) AS start_date,

                CAST(MAX(date) AS DATE) AS end_date

            FROM fact_inventory
        ),

        zero_days AS (
            SELECT
                i.store_id,
                i.product_id,

                CAST(i.date AS DATE) AS date,

                CAST(i.date AS DATE)
                - CAST(
                    ROW_NUMBER() OVER (
                        PARTITION BY
                            i.store_id,
                            i.product_id
                        ORDER BY i.date
                    )
                    AS INTEGER
                ) AS streak_group

            FROM fact_inventory AS i
            CROSS JOIN quarter_window AS w

            WHERE CAST(i.date AS DATE)
                BETWEEN w.start_date AND w.end_date

              AND i.stock_quantity = 0
        ),

        stockout_events AS (
            SELECT
                store_id,
                product_id,
                MIN(date) AS stockout_start,
                MAX(date) AS stockout_end,
                COUNT(*) AS stockout_days

            FROM zero_days

            GROUP BY
                store_id,
                product_id,
                streak_group

            HAVING COUNT(*) > 3
        )

        SELECT
            e.store_id,
            s.city,
            s.region,
            e.product_id,
            p.product_name,
            e.stockout_start,
            e.stockout_end,
            e.stockout_days

        FROM stockout_events AS e

        LEFT JOIN dim_store AS s
            ON e.store_id = s.store_id

        LEFT JOIN dim_product AS p
            ON e.product_id = p.product_id

        ORDER BY
            e.stockout_days DESC,
            e.store_id,
            e.product_id,
            e.stockout_start
        """

        return connection.execute(query).fetchdf()

    finally:
        connection.close()