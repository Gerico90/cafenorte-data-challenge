import duckdb
import pandas as pd
import pytest

from src.business_questions import (
    get_q1_inventory_turnover,
    get_q2_stockouts,
)

def test_q1_inventory_turnover_calculation(tmp_path):
    database_path = tmp_path / "test.duckdb"

    connection = duckdb.connect(str(database_path))

    connection.execute("""
        CREATE TABLE dim_product (
            product_id VARCHAR,
            product_name VARCHAR,
            category VARCHAR
        )
    """)

    connection.execute("""
        INSERT INTO dim_product VALUES
        ('ERP-A', 'Product A', 'test'),
        ('ERP-B', 'Product B', 'test')
    """)

    connection.execute("""
        CREATE TABLE fact_sales (
            transaction_id VARCHAR,
            sold_at TIMESTAMP,
            product_id VARCHAR,
            channel VARCHAR,
            store_id VARCHAR,
            quantity INTEGER,
            amount_native DOUBLE,
            currency VARCHAR,
            document_type VARCHAR
        )
    """)

    connection.execute("""
        INSERT INTO fact_sales VALUES
        ('S1', '2026-03-01', 'ERP-A', 'physical',  'T001', 10, 100, 'MXN', NULL),
        ('S2', '2026-03-02', 'ERP-A', 'ecommerce', NULL,    5,  50, 'MXN', NULL),
        ('S3', '2026-03-03', 'ERP-B', 'physical',  'T001',  8,  80, 'MXN', NULL)
    """)

    connection.execute("""
        CREATE TABLE fact_inventory (
            date DATE,
            store_id VARCHAR,
            product_id VARCHAR,
            stock_quantity INTEGER
        )
    """)

    connection.execute("""
        INSERT INTO fact_inventory VALUES

        ('2026-03-01', 'T001', 'ERP-A', 10),
        ('2026-03-02', 'T001', 'ERP-A',  0),
        ('2026-03-03', 'T001', 'ERP-A', NULL),

        ('2026-03-01', 'T002', 'ERP-A', 5),
        ('2026-03-02', 'T002', 'ERP-A', 5),
        ('2026-03-03', 'T002', 'ERP-A', 5),

        ('2026-03-01', 'T001', 'ERP-B', 10),
        ('2026-03-02', 'T001', 'ERP-B', 10),
        ('2026-03-03', 'T001', 'ERP-B', 10)
    """)

    connection.close()

    result = get_q1_inventory_turnover(
        database_path=database_path,
        limit=10,
    )

    product_a = result[
        result["product_id"] == "ERP-A"
    ].iloc[0]

    product_b = result[
        result["product_id"] == "ERP-B"
    ].iloc[0]

    # Product A:
    # units sold = 10 physical + 5 ecommerce = 15
    #
    # T001 average stock = (10 + 0) / 2 = 5
    # NULL is excluded from AVG
    #
    # T002 average stock = (5 + 5 + 5) / 3 = 5
    #
    # total average inventory = 10
    # turnover = 15 / 10 = 1.5

    assert product_a["physical_units"] == 10
    assert product_a["ecommerce_units"] == 5
    assert product_a["total_units_sold"] == 15

    assert product_a["avg_inventory"] == pytest.approx(10.0)
    assert product_a["inventory_turnover"] == pytest.approx(1.5)

    assert product_a["inventory_coverage_pct"] == pytest.approx(
        83.33,
        abs=0.01,
    )

    # Product B:
    # units sold = 8
    # average inventory = 10
    # turnover = 0.8

    assert product_b["inventory_turnover"] == pytest.approx(0.8)

    # Product A should rank above Product B.
    assert result.iloc[0]["product_id"] == "ERP-A"

def test_q2_stockout_requires_more_than_three_consecutive_zero_days(
    tmp_path,
):
    database_path = tmp_path / "test_q2.duckdb"

    connection = duckdb.connect(str(database_path))

    connection.execute("""
        CREATE TABLE dim_product (
            product_id VARCHAR,
            product_name VARCHAR,
            category VARCHAR
        )
    """)

    connection.execute("""
        INSERT INTO dim_product VALUES
        ('ERP-A', 'Product A', 'test')
    """)

    connection.execute("""
        CREATE TABLE dim_store (
            store_id VARCHAR,
            city VARCHAR,
            region VARCHAR,
            timezone VARCHAR
        )
    """)

    connection.execute("""
        INSERT INTO dim_store VALUES
        ('T001', 'Test City', 'test', 'America/Mexico_City')
    """)

    connection.execute("""
        CREATE TABLE fact_inventory (
            date DATE,
            store_id VARCHAR,
            product_id VARCHAR,
            stock_quantity INTEGER
        )
    """)

    connection.execute("""
        INSERT INTO fact_inventory VALUES

        -- Valid 4-day stockout
        ('2026-01-01', 'T001', 'ERP-A', 0),
        ('2026-01-02', 'T001', 'ERP-A', 0),
        ('2026-01-03', 'T001', 'ERP-A', 0),
        ('2026-01-04', 'T001', 'ERP-A', 0),

        -- Break the streak
        ('2026-01-05', 'T001', 'ERP-A', 5),

        -- NULL must break this sequence
        ('2026-02-01', 'T001', 'ERP-A', 0),
        ('2026-02-02', 'T001', 'ERP-A', 0),
        ('2026-02-03', 'T001', 'ERP-A', NULL),
        ('2026-02-04', 'T001', 'ERP-A', 0),
        ('2026-02-05', 'T001', 'ERP-A', 0),

        -- Establish end of latest quarter
        ('2026-03-31', 'T001', 'ERP-A', 5)
    """)

    connection.close()

    result = get_q2_stockouts(
        database_path=database_path,
    )

    assert len(result) == 1

    event = result.iloc[0]

    assert event["store_id"] == "T001"
    assert event["product_id"] == "ERP-A"
    assert event["stockout_days"] == 4

    assert event["stockout_start"] == pd.Timestamp(
        "2026-01-01"
    )

    assert event["stockout_end"] == pd.Timestamp(
        "2026-01-04"
    )