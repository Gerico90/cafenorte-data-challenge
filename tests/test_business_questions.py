import duckdb
import pandas as pd
import pytest

from src.business_questions import (
    get_q1_inventory_turnover,
    get_q2_stockouts,
    get_q3_channel_mom,
    get_q4_negative_margin,
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
        -- ERP-A, T001: matched (T001 has an inventory series below).
        ('S1', '2025-10-01', 'ERP-A', 'physical',  'T001', 10, 100, 'MXN', 'I'),
        -- ERP-A, ecommerce: no store_id, participates unconditionally.
        ('S2', '2025-10-02', 'ERP-A', 'ecommerce', NULL,    5,  50, 'MXN', NULL),
        -- ERP-B, T001: matched.
        ('S3', '2025-10-03', 'ERP-B', 'physical',  'T001',  8,  80, 'MXN', 'E'),
        -- ERP-A, T003: physical sale with NO inventory series at all for
        -- this store-product pair -- must be excluded from Q1 turnover
        -- (matched-population rule) while still landing in
        -- fact_sales (not deleted from the analytical model).
        ('S4', '2025-10-04', 'ERP-A', 'physical',  'T003', 100, 1000, 'MXN', 'I'),
        -- Outside the Question 1 reporting period (2025-10-01..2026-03-31) --
        -- must not be counted.
        ('S5', '2026-04-01', 'ERP-A', 'physical',  'T001', 999, 9999, 'MXN', 'I')
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

        ('2025-10-01', 'T001', 'ERP-A', 10),
        ('2025-10-02', 'T001', 'ERP-A',  0),
        ('2025-10-03', 'T001', 'ERP-A', NULL),

        ('2025-10-01', 'T002', 'ERP-A', 5),
        ('2025-10-02', 'T002', 'ERP-A', 5),
        ('2025-10-03', 'T002', 'ERP-A', 5),

        ('2025-10-01', 'T001', 'ERP-B', 10),
        ('2025-10-02', 'T001', 'ERP-B', 10),
        ('2025-10-03', 'T001', 'ERP-B', 10)

        -- Note: T003/ERP-A has NO rows at all -> no observable series.
    """)

    connection.close()

    result = get_q1_inventory_turnover(
        database_path=database_path,
        limit=10,
    )

    product_a = result[
        result["sku_erp"] == "ERP-A"
    ].iloc[0]

    product_b = result[
        result["sku_erp"] == "ERP-B"
    ].iloc[0]

    # Product A:
    # physical units sold = 10 (T001, matched) -- the 100 units sold at
    # T003 (no inventory series) and the 999 units sold outside the Q1
    # window are both excluded. The 5 ecommerce units (S2) never
    # participate in Q1 at all -- ecommerce is excluded from this
    # metric entirely, regardless of SKU.
    #
    # T001 average stock = (10 + 0) / 2 = 5 (NULL excluded from AVG,
    # not interpolated, not zero-filled)
    # T002 average stock = (5 + 5 + 5) / 3 = 5
    # average_inventory_units = 5 + 5 = 10
    #
    # turnover = 10 / 10 = 1.0

    assert product_a["physical_units_sold"] == 10

    assert product_a["average_inventory_units"] == pytest.approx(10.0)
    assert product_a["inventory_turnover"] == pytest.approx(1.0)

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
    assert result.iloc[0]["sku_erp"] == "ERP-A"

    # Ecommerce no longer participates in Q1 at all: there is no
    # ecommerce/total-units column left to accidentally leak channel
    # mixing back into the numerator.
    assert "ecommerce_units" not in result.columns
    assert "total_units_sold" not in result.columns


def test_q1_ecommerce_sale_never_changes_turnover_for_same_sku(tmp_path):
    """
    An ecommerce sale for a SKU must not change that SKU's Q1 turnover
    at all -- not by adding to the numerator, not by any other path.
    Proven by building two otherwise-identical databases that differ
    only in the presence of a (large) ecommerce order, and asserting
    the resulting turnover is identical.
    """

    def _build(tmp_path, db_name, include_ecommerce):
        database_path = tmp_path / db_name
        connection = duckdb.connect(str(database_path))

        connection.execute("""
            CREATE TABLE dim_product (
                product_id VARCHAR,
                product_name VARCHAR,
                category VARCHAR
            )
        """)
        connection.execute("""
            INSERT INTO dim_product VALUES ('ERP-E', 'Product E', 'test')
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
            ('S1', '2025-10-01', 'ERP-E', 'physical', 'T001', 10, 100, 'MXN', 'I')
        """)

        if include_ecommerce:
            # A large ecommerce order for the SAME SKU -- if ecommerce
            # ever leaked into the numerator this would move turnover
            # a lot (from 10 to 1010 units).
            connection.execute("""
                INSERT INTO fact_sales VALUES
                ('S2', '2025-10-02', 'ERP-E', 'ecommerce', NULL, 1000, 10000, 'MXN', NULL)
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
            ('2025-10-01', 'T001', 'ERP-E', 10),
            ('2025-10-02', 'T001', 'ERP-E', 10)
        """)

        connection.close()
        return database_path

    without_ecommerce = _build(
        tmp_path, "q1_no_ecom.duckdb", include_ecommerce=False
    )
    with_ecommerce = _build(
        tmp_path, "q1_with_ecom.duckdb", include_ecommerce=True
    )

    result_without = get_q1_inventory_turnover(
        database_path=without_ecommerce, limit=10
    )
    result_with = get_q1_inventory_turnover(
        database_path=with_ecommerce, limit=10
    )

    row_without = result_without[
        result_without["sku_erp"] == "ERP-E"
    ].iloc[0]
    row_with = result_with[
        result_with["sku_erp"] == "ERP-E"
    ].iloc[0]

    # physical_units_sold, average_inventory_units, and inventory_turnover
    # must be identical whether or not the ecommerce order exists.
    assert row_without["physical_units_sold"] == 10
    assert row_with["physical_units_sold"] == 10

    assert row_with["inventory_turnover"] == pytest.approx(
        row_without["inventory_turnover"]
    )
    assert row_with["inventory_turnover"] == pytest.approx(1.0)


def test_q1_excludes_sales_outside_matched_inventory_population(tmp_path):
    """
    A store-SKU pair with physical sales but no observable inventory
    series anywhere must not contribute to Q1 turnover, even though its
    SKU otherwise has an eligible average_inventory_units from other
    stores (matched-population rule).
    """

    database_path = tmp_path / "test_unmatched.duckdb"

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
        ('ERP-C', 'Product C', 'test')
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
        -- T010 has an inventory series -> eligible.
        ('S1', '2025-11-01', 'ERP-C', 'physical', 'T010', 4, 40, 'MXN', 'I'),
        -- T020 has NO inventory series -> excluded from Q1, but kept in
        -- fact_sales.
        ('S2', '2025-11-02', 'ERP-C', 'physical', 'T020', 50, 500, 'MXN', 'I')
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
        ('2025-11-01', 'T010', 'ERP-C', 8),
        ('2025-11-02', 'T010', 'ERP-C', 8)
    """)

    connection.close()

    result = get_q1_inventory_turnover(
        database_path=database_path,
        limit=10,
    )

    product_c = result[
        result["sku_erp"] == "ERP-C"
    ].iloc[0]

    # Only the T010 sale (matched to an observable inventory series)
    # counts; the T020 sale (50 units, no inventory series) must be
    # excluded even though it is far larger.
    assert product_c["physical_units_sold"] == 4
    assert product_c["average_inventory_units"] == pytest.approx(8.0)
    assert product_c["inventory_turnover"] == pytest.approx(0.5)


def test_q1_all_null_store_sku_excluded_from_denominator_not_zeroed(
    tmp_path,
):
    """
    A store-SKU whose inventory series exists but is entirely NULL/N-A
    must contribute NOTHING to the SKU-level average_inventory_units --
    it must never be coalesced into a 0 that dilutes the denominator.

    Meanwhile, a sibling store-SKU with valid numeric readings --
    including a genuine numeric 0 -- must still have that 0 counted as
    a real observation in its own AVG.
    """

    database_path = tmp_path / "test_all_null_store.duckdb"

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
        ('ERP-Z', 'Product Z', 'test')
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
        -- TA has an observable series (all-NULL) -> still eligible for
        -- the numerator under the matched-population rule, but its
        -- inventory average must be UNKNOWN, not zero.
        ('S1', '2025-10-01', 'ERP-Z', 'physical', 'TA', 10, 100, 'MXN', 'I'),
        -- TB has a valid numeric series including a genuine zero.
        ('S2', '2025-10-01', 'ERP-Z', 'physical', 'TB',  3,  30, 'MXN', 'I')
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
        -- TA: series exists but every observation is NULL/N-A.
        ('2025-10-01', 'TA', 'ERP-Z', NULL),
        ('2025-10-02', 'TA', 'ERP-Z', NULL),

        -- TB: valid numeric series; 0 is a real observation, not a gap.
        ('2025-10-01', 'TB', 'ERP-Z', 0),
        ('2025-10-02', 'TB', 'ERP-Z', 4)
    """)

    connection.close()

    result = get_q1_inventory_turnover(
        database_path=database_path,
        limit=10,
    )

    product_z = result[
        result["sku_erp"] == "ERP-Z"
    ].iloc[0]

    # TA's all-NULL average must be excluded entirely from the SKU
    # denominator (never coalesced to 0): average_inventory_units must
    # equal TB's average alone -- (0 + 4) / 2 = 2 -- not 0, and not
    # diluted/halved by a phantom 0 contribution from TA.
    assert product_z["average_inventory_units"] == pytest.approx(2.0)

    # Numeric 0 is a valid observation, so TB's average is (0 + 4) / 2
    # = 2, not 4 (which is what you'd get if 0 were wrongly dropped
    # like a NULL).
    assert product_z["average_inventory_units"] != pytest.approx(4.0)

    # Physical sales: TA is still matched (it has an observable series,
    # even though every reading is NULL) so both stores' units count.
    assert product_z["physical_units_sold"] == 13

    # turnover = 13 / 2 = 6.5
    assert product_z["inventory_turnover"] == pytest.approx(6.5)


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


def test_q2_stockout_boundary_and_scattered_zero_scenarios(
    tmp_path,
):
    """
    Verify the Question 2 rule (more than 3 consecutive zero days) at its edges:
      - exactly 3 consecutive numeric-zero days does NOT qualify
      - exactly 4 consecutive numeric-zero days DOES qualify
      - "N/A" (NULL) inside a zero run interrupts the confirmed
        streak -- it never bridges two zero segments into one
      - numeric 0 is itself a valid, countable stock observation
      - scattered (non-consecutive) zero days never combine into
        a single qualifying run
    """

    database_path = tmp_path / "test_q2_boundaries.duckdb"

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
        ('ERP-3DAY', 'Exactly Three', 'test'),
        ('ERP-4DAY', 'Exactly Four', 'test'),
        ('ERP-NASPLIT', 'NA Split', 'test'),
        ('ERP-SCATTER', 'Scattered Zeros', 'test')
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

        -- ERP-3DAY: exactly 3 consecutive numeric-zero days.
        -- Must NOT qualify (minimum qualifying run is 4 days).
        ('2026-01-10', 'T001', 'ERP-3DAY', 0),
        ('2026-01-11', 'T001', 'ERP-3DAY', 0),
        ('2026-01-12', 'T001', 'ERP-3DAY', 0),
        ('2026-01-13', 'T001', 'ERP-3DAY', 5),

        -- ERP-4DAY: exactly 4 consecutive numeric-zero days.
        -- Must qualify.
        ('2026-01-10', 'T001', 'ERP-4DAY', 0),
        ('2026-01-11', 'T001', 'ERP-4DAY', 0),
        ('2026-01-12', 'T001', 'ERP-4DAY', 0),
        ('2026-01-13', 'T001', 'ERP-4DAY', 0),
        ('2026-01-14', 'T001', 'ERP-4DAY', 5),

        -- ERP-NASPLIT: two 2-day zero segments separated by a
        -- single N/A (NULL) day. NULL is unknown, not zero, and
        -- must interrupt the run rather than bridging it into a
        -- combined 5-day streak. Neither 2-day segment qualifies.
        ('2026-01-10', 'T001', 'ERP-NASPLIT', 0),
        ('2026-01-11', 'T001', 'ERP-NASPLIT', 0),
        ('2026-01-12', 'T001', 'ERP-NASPLIT', NULL),
        ('2026-01-13', 'T001', 'ERP-NASPLIT', 0),
        ('2026-01-14', 'T001', 'ERP-NASPLIT', 0),

        -- ERP-SCATTER: isolated zero days, each surrounded by
        -- non-zero, non-consecutive days. Must never combine into
        -- a single qualifying run.
        ('2026-01-10', 'T001', 'ERP-SCATTER', 0),
        ('2026-01-11', 'T001', 'ERP-SCATTER', 5),
        ('2026-01-12', 'T001', 'ERP-SCATTER', 0),
        ('2026-01-13', 'T001', 'ERP-SCATTER', 5),
        ('2026-01-14', 'T001', 'ERP-SCATTER', 0),
        ('2026-01-15', 'T001', 'ERP-SCATTER', 5)
    """)

    connection.close()

    result = get_q2_stockouts(
        database_path=database_path,
    )

    qualifying_products = set(result["product_id"])

    # Exactly 3 consecutive zero days does NOT qualify.
    assert "ERP-3DAY" not in qualifying_products

    # Exactly 4 consecutive zero days DOES qualify.
    assert "ERP-4DAY" in qualifying_products

    four_day_event = result[
        result["product_id"] == "ERP-4DAY"
    ].iloc[0]

    assert four_day_event["stockout_days"] == 4
    assert four_day_event["stockout_start"] == pd.Timestamp(
        "2026-01-10"
    )
    assert four_day_event["stockout_end"] == pd.Timestamp(
        "2026-01-13"
    )

    # N/A inside a zero sequence interrupts the confirmed run --
    # neither 2-day segment reaches the 4-day minimum, and numeric
    # zero (not the NULL) is what is being counted on each side.
    assert "ERP-NASPLIT" not in qualifying_products

    # Scattered, non-consecutive zero days never combine into one
    # stockout run.
    assert "ERP-SCATTER" not in qualifying_products

    # Numeric zero is a valid, countable stock observation: the
    # qualifying ERP-4DAY run's day count reflects all 4 zero rows,
    # confirming zeros are not silently dropped like NULLs.
    assert four_day_event["stockout_days"] == 4


# ---------------------------------------------------------------------
# Q3: channel MoM
# ---------------------------------------------------------------------

def _build_q3_database(tmp_path, db_name, fact_sales_rows, fact_exchange_rate_rows):
    """
    Build a minimal DuckDB database containing only the tables
    get_q3_channel_mom() reads: fact_sales and fact_exchange_rate.

    fact_sales_rows: list of tuples
        (transaction_id, sold_at, channel, amount_native, currency)
    fact_exchange_rate_rows: list of tuples
        (rate_date, currency, rate_to_mxn)
    """

    database_path = tmp_path / db_name

    connection = duckdb.connect(str(database_path))

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

    for transaction_id, sold_at, channel, amount_native, currency in fact_sales_rows:
        store_id = "T001" if channel == "physical" else None
        document_type = "I" if channel == "physical" else None

        connection.execute(
            """
            INSERT INTO fact_sales VALUES
            (?, ?, 'ERP-A', ?, ?, 1, ?, ?, ?)
            """,
            [
                transaction_id,
                sold_at,
                channel,
                store_id,
                amount_native,
                currency,
                document_type,
            ],
        )

    connection.execute("""
        CREATE TABLE fact_exchange_rate (
            rate_date DATE,
            currency VARCHAR,
            rate_to_mxn DOUBLE
        )
    """)

    for rate_date, currency, rate_to_mxn in fact_exchange_rate_rows:
        connection.execute(
            "INSERT INTO fact_exchange_rate VALUES (?, ?, ?)",
            [rate_date, currency, rate_to_mxn],
        )

    connection.close()

    return database_path


def _sales_mxn(result, month, channel):
    row = result[
        (result["month"] == pd.Timestamp(month))
        & (result["channel"] == channel)
    ].iloc[0]
    return row["sales_mxn"]


def _mom_pct(result, month, channel):
    row = result[
        (result["month"] == pd.Timestamp(month))
        & (result["channel"] == channel)
    ].iloc[0]
    return row["mom_pct"]


def test_q3_returns_24_rows_covering_all_12_months_both_channels(tmp_path):
    """
    Sanity check on shape: 12 displayed months x 2 channels = 24 rows,
    and every displayed month/channel combination is present even when
    a channel has no transactions in a given month (e.g. e-commerce
    before its data begins).
    """

    database_path = _build_q3_database(
        tmp_path,
        "q3_shape.duckdb",
        fact_sales_rows=[
            ("V1", "2025-03-15 10:00:00", "physical", 100.0, "MXN"),
            ("V2", "2025-04-15 10:00:00", "physical", 100.0, "MXN"),
            ("S1", "2025-04-15 10:00:00", "ecommerce", 100.0, "MXN"),
        ],
        fact_exchange_rate_rows=[],
    )

    result = get_q3_channel_mom(database_path=database_path)

    assert len(result) == 24
    assert set(result["channel"].unique()) == {"physical", "ecommerce"}
    assert result["month"].nunique() == 12

    # March 2025 (used only as the physical baseline) must not
    # appear in the displayed output.
    assert not (result["month"] == pd.Timestamp("2025-03-01")).any()

    for expected_month in pd.date_range(
        "2025-04-01", "2026-03-01", freq="MS"
    ):
        for channel in ("physical", "ecommerce"):
            assert (
                (result["month"] == expected_month)
                & (result["channel"] == channel)
            ).any(), f"missing {channel} row for {expected_month}"


def test_q3_physical_mxn_requires_no_conversion(tmp_path):
    database_path = _build_q3_database(
        tmp_path,
        "q3_physical_mxn.duckdb",
        fact_sales_rows=[
            ("V1", "2025-04-10 10:00:00", "physical", 1000.0, "MXN"),
            ("V2", "2025-04-20 10:00:00", "physical", 500.0, "MXN"),
        ],
        fact_exchange_rate_rows=[],
    )

    result = get_q3_channel_mom(database_path=database_path)

    assert _sales_mxn(result, "2025-04-01", "physical") == pytest.approx(1500.0)


def test_q3_ecommerce_mxn_requires_no_conversion(tmp_path):
    database_path = _build_q3_database(
        tmp_path,
        "q3_ecom_mxn.duckdb",
        fact_sales_rows=[
            ("S1", "2025-04-10 10:00:00", "ecommerce", 300.0, "MXN"),
            ("S2", "2025-04-20 10:00:00", "ecommerce", 200.0, "MXN"),
        ],
        fact_exchange_rate_rows=[],
    )

    result = get_q3_channel_mom(database_path=database_path)

    assert _sales_mxn(result, "2025-04-01", "ecommerce") == pytest.approx(500.0)


def test_q3_ecommerce_usd_eur_uses_amount_times_rate_to_mxn(tmp_path):
    database_path = _build_q3_database(
        tmp_path,
        "q3_ecom_fx.duckdb",
        fact_sales_rows=[
            ("S1", "2025-04-05 10:00:00", "ecommerce", 100.0, "USD"),
            ("S2", "2025-04-05 10:00:00", "ecommerce", 50.0, "EUR"),
        ],
        fact_exchange_rate_rows=[
            ("2025-04-05", "USD", 17.0),
            ("2025-04-05", "EUR", 20.0),
        ],
    )

    result = get_q3_channel_mom(database_path=database_path)

    # 100 * 17.0 + 50 * 20.0 = 1700 + 1000 = 2700
    assert _sales_mxn(result, "2025-04-01", "ecommerce") == pytest.approx(2700.0)


def test_q3_exchange_rate_matched_by_transaction_date_and_currency(tmp_path):
    """
    The rate applied must be the one for the transaction's own calendar
    date and currency -- not any other date's rate for that currency,
    even within the same month.
    """

    database_path = _build_q3_database(
        tmp_path,
        "q3_fx_match.duckdb",
        fact_sales_rows=[
            # Same currency, same month, different days -> must
            # each pick up their own day's rate.
            ("S1", "2025-04-05 09:00:00", "ecommerce", 100.0, "USD"),
            ("S2", "2025-04-20 09:00:00", "ecommerce", 100.0, "USD"),
        ],
        fact_exchange_rate_rows=[
            ("2025-04-05", "USD", 17.0),
            ("2025-04-20", "USD", 20.0),
            # A decoy EUR rate on the same dates must never be
            # applied to USD rows.
            ("2025-04-05", "EUR", 999.0),
            ("2025-04-20", "EUR", 999.0),
        ],
    )

    result = get_q3_channel_mom(database_path=database_path)

    # Per-transaction conversion by its own date's rate:
    # 100 * 17.0 + 100 * 20.0 = 1700 + 2000 = 3700.
    # A wrong (e.g. single/last-day) rate match would give 4000.
    assert _sales_mxn(result, "2025-04-01", "ecommerce") == pytest.approx(3700.0)


def test_q3_monthly_aggregation_happens_after_currency_normalization(tmp_path):
    """
    Revenue must be converted per transaction using that transaction's
    own day's rate BEFORE summing to the month -- never by summing
    native amounts first and applying a single rate to the total.
    """

    database_path = _build_q3_database(
        tmp_path,
        "q3_agg_order.duckdb",
        fact_sales_rows=[
            ("S1", "2025-05-02 09:00:00", "ecommerce", 100.0, "USD"),
            ("S2", "2025-05-28 09:00:00", "ecommerce", 100.0, "USD"),
        ],
        fact_exchange_rate_rows=[
            ("2025-05-02", "USD", 17.0),
            ("2025-05-28", "USD", 19.0),
        ],
    )

    result = get_q3_channel_mom(database_path=database_path)

    correct = 100.0 * 17.0 + 100.0 * 19.0  # 3600.0
    wrong_if_summed_first = (100.0 + 100.0) * 19.0  # 3800.0 (last rate)

    actual = _sales_mxn(result, "2025-05-01", "ecommerce")

    assert actual == pytest.approx(correct)
    assert actual != pytest.approx(wrong_if_summed_first)


def test_q3_standard_mom_calculation(tmp_path):
    database_path = _build_q3_database(
        tmp_path,
        "q3_standard_mom.duckdb",
        fact_sales_rows=[
            ("V1", "2025-04-15 10:00:00", "physical", 1000.0, "MXN"),
            ("V2", "2025-05-15 10:00:00", "physical", 1500.0, "MXN"),
        ],
        fact_exchange_rate_rows=[],
    )

    result = get_q3_channel_mom(database_path=database_path)

    # (1500 - 1000) / 1000 * 100 = 50.0
    assert _mom_pct(result, "2025-05-01", "physical") == pytest.approx(50.0)


def test_q3_physical_april_uses_march_baseline_but_march_not_displayed(tmp_path):
    database_path = _build_q3_database(
        tmp_path,
        "q3_march_baseline.duckdb",
        fact_sales_rows=[
            ("V0", "2025-03-10 10:00:00", "physical", 1000.0, "MXN"),
            ("V1", "2025-04-10 10:00:00", "physical", 1500.0, "MXN"),
        ],
        fact_exchange_rate_rows=[],
    )

    result = get_q3_channel_mom(database_path=database_path)

    # March 2025 must not be a row in the displayed output.
    assert not (
        (result["month"] == pd.Timestamp("2025-03-01"))
        & (result["channel"] == "physical")
    ).any()

    # But April's MoM must still be calculated against it:
    # (1500 - 1000) / 1000 * 100 = 50.0
    assert _mom_pct(result, "2025-04-01", "physical") == pytest.approx(50.0)


def test_q3_ecommerce_april_mom_is_null_no_prior_observation(tmp_path):
    database_path = _build_q3_database(
        tmp_path,
        "q3_ecom_april_null.duckdb",
        fact_sales_rows=[
            ("S1", "2025-04-10 10:00:00", "ecommerce", 500.0, "MXN"),
        ],
        fact_exchange_rate_rows=[],
    )

    result = get_q3_channel_mom(database_path=database_path)

    value = _mom_pct(result, "2025-04-01", "ecommerce")
    assert pd.isna(value)


def test_q3_ecommerce_subsequent_months_use_previous_displayed_month(tmp_path):
    database_path = _build_q3_database(
        tmp_path,
        "q3_ecom_subsequent.duckdb",
        fact_sales_rows=[
            ("S1", "2025-04-10 10:00:00", "ecommerce", 1000.0, "MXN"),
            ("S2", "2025-05-10 10:00:00", "ecommerce", 1500.0, "MXN"),
            ("S3", "2025-06-10 10:00:00", "ecommerce", 750.0, "MXN"),
        ],
        fact_exchange_rate_rows=[],
    )

    result = get_q3_channel_mom(database_path=database_path)

    # April: NULL (no March e-commerce observation at all).
    assert pd.isna(_mom_pct(result, "2025-04-01", "ecommerce"))

    # May uses April (the previous *displayed* month) as baseline:
    # (1500 - 1000) / 1000 * 100 = 50.0
    assert _mom_pct(result, "2025-05-01", "ecommerce") == pytest.approx(50.0)

    # June uses May normally:
    # (750 - 1500) / 1500 * 100 = -50.0
    assert _mom_pct(result, "2025-06-01", "ecommerce") == pytest.approx(-50.0)


def test_q3_missing_exchange_rate_raises_instead_of_dropping_revenue(tmp_path):
    """
    A non-MXN sale whose transaction date + currency has no exchange
    rate must fail loudly. Without the gate its revenue would become
    NULL and be silently ignored by SUM().
    """

    database_path = _build_q3_database(
        tmp_path,
        "q3_missing_fx.duckdb",
        fact_sales_rows=[
            ("S1", "2025-04-10 10:00:00", "ecommerce", 10.0, "USD"),
            ("S2", "2025-04-11 10:00:00", "ecommerce", 10.0, "USD"),
        ],
        # Rate exists for 2025-04-10 only; 2025-04-11 is missing.
        fact_exchange_rate_rows=[("2025-04-10", "USD", 20.0)],
    )

    with pytest.raises(ValueError, match="no exchange rate") as error:
        get_q3_channel_mom(database_path=database_path)

    assert "USD on 2025-04-11" in str(error.value)


def test_q3_missing_exchange_rate_for_march_baseline_also_raises(tmp_path):
    """The March 2025 baseline month is part of the calculation range."""

    database_path = _build_q3_database(
        tmp_path,
        "q3_missing_fx_baseline.duckdb",
        fact_sales_rows=[
            ("S1", "2025-03-20 10:00:00", "ecommerce", 10.0, "EUR"),
        ],
        fact_exchange_rate_rows=[],
    )

    with pytest.raises(ValueError, match="no exchange rate"):
        get_q3_channel_mom(database_path=database_path)


def test_q3_duplicate_exchange_rate_for_date_and_currency_raises(tmp_path):
    database_path = _build_q3_database(
        tmp_path,
        "q3_duplicate_fx.duckdb",
        fact_sales_rows=[
            ("S1", "2025-04-10 10:00:00", "ecommerce", 10.0, "USD"),
        ],
        fact_exchange_rate_rows=[
            ("2025-04-10", "USD", 20.0),
            ("2025-04-10", "USD", 21.0),
        ],
    )

    with pytest.raises(ValueError, match="multiple exchange rates"):
        get_q3_channel_mom(database_path=database_path)


def test_q3_complete_exchange_rate_coverage_keeps_conversion_result(tmp_path):
    """
    With a rate for every non-MXN transaction date + currency the gate
    stays silent and the accepted conversion is unchanged:
    amount_mxn = amount * rate_to_mxn.
    """

    database_path = _build_q3_database(
        tmp_path,
        "q3_complete_fx.duckdb",
        fact_sales_rows=[
            ("S1", "2025-04-10 10:00:00", "ecommerce", 10.0, "USD"),
            ("S2", "2025-04-11 10:00:00", "ecommerce", 10.0, "EUR"),
            ("S3", "2025-04-12 10:00:00", "ecommerce", 100.0, "MXN"),
        ],
        fact_exchange_rate_rows=[
            ("2025-04-10", "USD", 20.0),
            ("2025-04-11", "EUR", 22.0),
            # Unused rates must not matter.
            ("2025-04-10", "EUR", 21.0),
        ],
    )

    result = get_q3_channel_mom(database_path=database_path)

    assert len(result) == 24
    # 10 * 20 + 10 * 22 + 100 = 520
    assert _sales_mxn(result, "2025-04-01", "ecommerce") == pytest.approx(520.0)


# ---------------------------------------------------------------------
# Q4: negative margin by store + SKU
# ---------------------------------------------------------------------

def _build_q4_database(
    tmp_path,
    db_name,
    fact_sales_rows,
    fact_product_cost_rows,
    dim_product_rows=None,
):
    """
    Build a minimal DuckDB database containing only the tables
    get_q4_negative_margin() reads: fact_sales, fact_product_cost,
    and dim_product.

    fact_sales_rows: list of tuples
        (transaction_id, sold_at, store_id, product_id, quantity,
         monto, document_type)
    fact_product_cost_rows: list of tuples
        (product_id, effective_date, cost_mxn, supplier)
    dim_product_rows: optional list of tuples
        (product_id, product_name, category)
    """

    database_path = tmp_path / db_name

    connection = duckdb.connect(str(database_path))

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

    for (
        transaction_id,
        sold_at,
        store_id,
        product_id,
        quantity,
        monto,
        document_type,
    ) in fact_sales_rows:
        connection.execute(
            """
            INSERT INTO fact_sales VALUES
            (?, ?, ?, 'physical', ?, ?, ?, 'MXN', ?)
            """,
            [
                transaction_id,
                sold_at,
                product_id,
                store_id,
                quantity,
                monto,
                document_type,
            ],
        )

    connection.execute("""
        CREATE TABLE fact_product_cost (
            product_id VARCHAR,
            effective_date DATE,
            cost_mxn DOUBLE,
            supplier VARCHAR
        )
    """)

    for (
        product_id,
        effective_date,
        cost_mxn,
        supplier,
    ) in fact_product_cost_rows:
        connection.execute(
            "INSERT INTO fact_product_cost VALUES (?, ?, ?, ?)",
            [product_id, effective_date, cost_mxn, supplier],
        )

    connection.execute("""
        CREATE TABLE dim_product (
            product_id VARCHAR,
            product_name VARCHAR,
            category VARCHAR
        )
    """)

    if dim_product_rows is None:
        # Default: one dim_product row per distinct sku referenced by
        # either sales or cost history, so joins resolve cleanly
        # unless a test deliberately wants otherwise.
        skus = sorted(
            {row[3] for row in fact_sales_rows}
            | {row[0] for row in fact_product_cost_rows}
        )
        dim_product_rows = [
            (sku, f"Product {sku}", "test") for sku in skus
        ]

    for product_id, product_name, category in dim_product_rows:
        connection.execute(
            "INSERT INTO dim_product VALUES (?, ?, ?)",
            [product_id, product_name, category],
        )

    connection.close()

    return database_path


def test_q4_explicit_reconciled_product_gets_correct_margin(tmp_path):
    """
    A sku_erp that reached fact_sales via an EXPLICIT product
    reconciliation (src/reconcile.py, step 1) is just a normal
    product_id by the time it lands in fact_sales/fact_product_cost --
    Q4 must compute its cost and margin correctly using that key.
    """

    database_path = _build_q4_database(
        tmp_path,
        "q4_explicit.duckdb",
        fact_sales_rows=[
            (
                "V1",
                "2025-01-10 10:00:00",
                "T001",
                "ERP-PROV-MX-001-A",
                10,
                50.0,
                "I",
            ),
        ],
        fact_product_cost_rows=[
            ("ERP-PROV-MX-001-A", "2024-01-01", 10.0, "Prov A"),
        ],
    )

    result = get_q4_negative_margin(database_path=database_path)

    row = result[result["sku_erp"] == "ERP-PROV-MX-001-A"].iloc[0]

    # revenue = 50, cost = 10 units * 10.0 = 100, margin = -50
    assert row["revenue_mxn"] == pytest.approx(50.0)
    assert row["cost_mxn"] == pytest.approx(100.0)
    assert row["margin_mxn"] == pytest.approx(-50.0)


def test_q4_fallback_reconciled_product_can_receive_its_cost(tmp_path):
    """
    A sku_erp that reached fact_sales via the validated unique numeric
    fallback (src/reconcile.py, step 2, applied only when explicit
    mapping was absent) is indistinguishable from any other sku_erp by
    the time it reaches fact_sales/fact_product_cost. Q4's cost join
    keys purely on product_id/sku_erp, so a fallback-reconciled
    product must resolve its applicable cost exactly like an
    explicitly mapped one.
    """

    database_path = _build_q4_database(
        tmp_path,
        "q4_fallback.duckdb",
        fact_sales_rows=[
            (
                "V1",
                "2025-01-10 10:00:00",
                "T001",
                "ERP-PROV-MX-002-B",
                4,
                20.0,
                "I",
            ),
        ],
        fact_product_cost_rows=[
            ("ERP-PROV-MX-002-B", "2024-01-01", 15.0, "Prov B"),
        ],
    )

    result = get_q4_negative_margin(database_path=database_path)

    row = result[result["sku_erp"] == "ERP-PROV-MX-002-B"].iloc[0]

    # revenue = 20, cost = 4 * 15.0 = 60, margin = -40
    assert row["revenue_mxn"] == pytest.approx(20.0)
    assert row["cost_mxn"] == pytest.approx(60.0)
    assert row["margin_mxn"] == pytest.approx(-40.0)


def test_q4_selects_latest_effective_cost_not_earliest(tmp_path):
    """
    When multiple cost_history rows are effective on/before the sale
    date, the LATEST one (closest to, but not after, the sale date)
    must be selected -- never the earliest.
    """

    database_path = _build_q4_database(
        tmp_path,
        "q4_latest_cost.duckdb",
        fact_sales_rows=[
            (
                "V1",
                "2025-06-15 10:00:00",
                "T001",
                "ERP-A",
                1,
                5.0,
                "I",
            ),
        ],
        fact_product_cost_rows=[
            ("ERP-A", "2024-01-01", 100.0, "Prov A"),  # too early, but valid
            ("ERP-A", "2025-01-01", 50.0, "Prov A"),   # latest valid <= sale date
        ],
    )

    result = get_q4_negative_margin(database_path=database_path)

    row = result[result["sku_erp"] == "ERP-A"].iloc[0]

    # Must use 50.0 (the latest applicable), not 100.0.
    # cost = 1 * 50.0 = 50, revenue = 5, margin = -45
    assert row["cost_mxn"] == pytest.approx(50.0)
    assert row["margin_mxn"] == pytest.approx(-45.0)


def test_q4_never_selects_a_future_cost(tmp_path):
    """
    A cost_history row with fecha_vigencia AFTER the sale date must
    never be used, even when it is the "latest" cost row overall for
    that product.
    """

    database_path = _build_q4_database(
        tmp_path,
        "q4_future_cost.duckdb",
        fact_sales_rows=[
            (
                "V1",
                "2025-01-10 10:00:00",
                "T001",
                "ERP-A",
                1,
                5.0,
                "I",
            ),
        ],
        fact_product_cost_rows=[
            ("ERP-A", "2024-01-01", 20.0, "Prov A"),   # valid, on/before sale
            ("ERP-A", "2026-01-01", 999.0, "Prov A"),  # future -- must be ignored
        ],
    )

    result = get_q4_negative_margin(database_path=database_path)

    row = result[result["sku_erp"] == "ERP-A"].iloc[0]

    # Must use 20.0 (the only cost effective on/before the sale date).
    # cost = 1 * 20.0 = 20, revenue = 5, margin = -15
    assert row["cost_mxn"] == pytest.approx(20.0)
    assert row["margin_mxn"] == pytest.approx(-15.0)


def test_q4_cantidad_multiplies_unit_cost(tmp_path):
    """transaction_cost_mxn = cantidad * applicable_costo_mxn."""

    database_path = _build_q4_database(
        tmp_path,
        "q4_quantity.duckdb",
        fact_sales_rows=[
            (
                "V1",
                "2025-01-10 10:00:00",
                "T001",
                "ERP-A",
                7,
                10.0,
                "I",
            ),
        ],
        fact_product_cost_rows=[
            ("ERP-A", "2024-01-01", 3.0, "Prov A"),
        ],
    )

    result = get_q4_negative_margin(database_path=database_path)

    row = result[result["sku_erp"] == "ERP-A"].iloc[0]

    # cost = 7 * 3.0 = 21, revenue = 10, margin = -11
    assert row["cost_mxn"] == pytest.approx(21.0)
    assert row["margin_mxn"] == pytest.approx(-11.0)


def test_q4_positive_margin_store_sku_does_not_qualify(tmp_path):
    """A store-SKU with margin_mxn >= 0 must not appear in the output."""

    database_path = _build_q4_database(
        tmp_path,
        "q4_positive.duckdb",
        fact_sales_rows=[
            (
                "V1",
                "2025-01-10 10:00:00",
                "T001",
                "ERP-POS",
                1,
                100.0,
                "I",
            ),
        ],
        fact_product_cost_rows=[
            ("ERP-POS", "2024-01-01", 10.0, "Prov A"),
        ],
    )

    result = get_q4_negative_margin(database_path=database_path)

    # revenue 100, cost 10, margin +90 -- must be excluded.
    assert "ERP-POS" not in set(result["sku_erp"])


def test_q4_negative_aggregate_margin_qualifies_even_if_no_single_loss(
    tmp_path,
):
    """
    Aggregation happens across the FULL period before qualification --
    a store-SKU whose individual transactions are not all losses, but
    whose SUMMED margin_mxn is negative, must still qualify.
    """

    database_path = _build_q4_database(
        tmp_path,
        "q4_aggregate_negative.duckdb",
        fact_sales_rows=[
            # Transaction 1: small profit.
            (
                "V1",
                "2025-01-10 10:00:00",
                "T001",
                "ERP-AGG",
                1,
                12.0,
                "I",
            ),
            # Transaction 2: bigger loss -- net aggregate is negative.
            (
                "V2",
                "2025-02-10 10:00:00",
                "T001",
                "ERP-AGG",
                5,
                10.0,
                "I",
            ),
        ],
        fact_product_cost_rows=[
            ("ERP-AGG", "2024-01-01", 10.0, "Prov A"),
        ],
    )

    result = get_q4_negative_margin(database_path=database_path)

    # revenue = 12 + 10 = 22
    # cost = 1*10 + 5*10 = 10 + 50 = 60
    # margin = 22 - 60 = -38
    row = result[result["sku_erp"] == "ERP-AGG"].iloc[0]
    assert row["revenue_mxn"] == pytest.approx(22.0)
    assert row["cost_mxn"] == pytest.approx(60.0)
    assert row["margin_mxn"] == pytest.approx(-38.0)


def test_q4_aggregation_grain_is_store_plus_sku(tmp_path):
    """
    The same SKU sold at two different stores must be aggregated
    separately -- one store's negative margin must not be diluted or
    masked by another store's positive margin for the same SKU.
    """

    database_path = _build_q4_database(
        tmp_path,
        "q4_grain.duckdb",
        fact_sales_rows=[
            # Store T001: loss.
            (
                "V1",
                "2025-01-10 10:00:00",
                "T001",
                "ERP-GRAIN",
                10,
                5.0,
                "I",
            ),
            # Store T002: profit, same SKU.
            (
                "V2",
                "2025-01-10 10:00:00",
                "T002",
                "ERP-GRAIN",
                1,
                100.0,
                "I",
            ),
        ],
        fact_product_cost_rows=[
            ("ERP-GRAIN", "2024-01-01", 10.0, "Prov A"),
        ],
    )

    result = get_q4_negative_margin(database_path=database_path)

    negative_rows = result[result["sku_erp"] == "ERP-GRAIN"]

    # T001: revenue 5, cost 100, margin -95 -- qualifies.
    assert (negative_rows["store_id"] == "T001").any()
    t001_row = negative_rows[negative_rows["store_id"] == "T001"].iloc[0]
    assert t001_row["margin_mxn"] == pytest.approx(-95.0)

    # T002: revenue 100, cost 10, margin +90 -- must not appear.
    assert not (negative_rows["store_id"] == "T002").any()


def test_q4_all_tipo_comprobante_values_remain_eligible(tmp_path):
    """
    tipo_comprobante I, E, P, N, T are all included exactly as
    recorded -- no filtering, no sign adjustment.
    """

    database_path = _build_q4_database(
        tmp_path,
        "q4_document_types.duckdb",
        fact_sales_rows=[
            ("V1", "2025-01-01 10:00:00", "T001", "ERP-DOC", 1, 1.0, "I"),
            ("V2", "2025-01-02 10:00:00", "T001", "ERP-DOC", 1, 1.0, "E"),
            ("V3", "2025-01-03 10:00:00", "T001", "ERP-DOC", 1, 1.0, "P"),
            ("V4", "2025-01-04 10:00:00", "T001", "ERP-DOC", 1, 1.0, "N"),
            ("V5", "2025-01-05 10:00:00", "T001", "ERP-DOC", 1, 1.0, "T"),
        ],
        fact_product_cost_rows=[
            ("ERP-DOC", "2024-01-01", 10.0, "Prov A"),
        ],
    )

    result = get_q4_negative_margin(database_path=database_path)

    row = result[result["sku_erp"] == "ERP-DOC"].iloc[0]

    # All 5 rows, regardless of document_type, contribute to revenue.
    # revenue = 5 * 1.0 = 5, cost = 5 * 10.0 = 50, margin = -45.
    assert row["revenue_mxn"] == pytest.approx(5.0)
    assert row["cost_mxn"] == pytest.approx(50.0)
    assert row["margin_mxn"] == pytest.approx(-45.0)


def test_q4_missing_applicable_cost_raises_instead_of_defaulting(tmp_path):
    """
    A physical sale whose sku_erp has NO cost_history row effective
    on/before its sale date must cause an explicit failure -- never a
    silent zero-cost default and never a silently dropped sale.
    """

    database_path = _build_q4_database(
        tmp_path,
        "q4_missing_cost.duckdb",
        fact_sales_rows=[
            (
                "V1",
                "2025-01-10 10:00:00",
                "T001",
                "ERP-NOCOST",
                1,
                100.0,
                "I",
            ),
        ],
        # No cost_history entry at all for ERP-NOCOST.
        fact_product_cost_rows=[],
    )

    with pytest.raises(ValueError):
        get_q4_negative_margin(database_path=database_path)


def test_q4_missing_applicable_cost_raises_when_only_future_cost_exists(
    tmp_path,
):
    """
    A sale dated before the EARLIEST cost_history row for its sku_erp
    has no applicable (non-future) cost at all, and must raise rather
    than falling back to that future cost or to zero.
    """

    database_path = _build_q4_database(
        tmp_path,
        "q4_only_future_cost.duckdb",
        fact_sales_rows=[
            (
                "V1",
                "2024-11-01 10:00:00",
                "T001",
                "ERP-ONLYFUTURE",
                1,
                100.0,
                "I",
            ),
        ],
        fact_product_cost_rows=[
            # Only cost on record is AFTER the sale date.
            ("ERP-ONLYFUTURE", "2025-01-01", 10.0, "Prov A"),
        ],
    )

    with pytest.raises(ValueError):
        get_q4_negative_margin(database_path=database_path)


def test_q4_excludes_sales_outside_the_period_window(tmp_path):
    """
    Sales outside 2024-10-01..2026-03-31 must not contribute to the
    Q4 margin calculation.
    """

    database_path = _build_q4_database(
        tmp_path,
        "q4_period_window.duckdb",
        fact_sales_rows=[
            # In-window loss.
            (
                "V1",
                "2025-06-01 10:00:00",
                "T001",
                "ERP-PERIOD",
                1,
                5.0,
                "I",
            ),
            # Before the window -- must be excluded.
            (
                "V2",
                "2024-09-30 10:00:00",
                "T001",
                "ERP-PERIOD",
                1,
                5.0,
                "I",
            ),
            # After the window -- must be excluded.
            (
                "V3",
                "2026-04-01 10:00:00",
                "T001",
                "ERP-PERIOD",
                1,
                5.0,
                "I",
            ),
        ],
        fact_product_cost_rows=[
            ("ERP-PERIOD", "2024-01-01", 10.0, "Prov A"),
        ],
    )

    result = get_q4_negative_margin(database_path=database_path)

    row = result[result["sku_erp"] == "ERP-PERIOD"].iloc[0]

    # Only the in-window sale counts: revenue = 5, cost = 10,
    # margin = -5. If the out-of-window sales were wrongly included,
    # revenue would be 15 and cost 30.
    assert row["revenue_mxn"] == pytest.approx(5.0)
    assert row["cost_mxn"] == pytest.approx(10.0)
    assert row["margin_mxn"] == pytest.approx(-5.0)