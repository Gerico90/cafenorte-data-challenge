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
    Return the top SKUs by inventory turnover for the Question 1
    reporting period (2025-10-01 through 2026-03-31 inclusive).

    This is a PHYSICAL-STORE-ONLY metric:
    "Inventory turnover over physical store-product combinations for
    which both sales and inventory are observable." It is not total
    company-wide turnover, not omnichannel turnover, and not complete
    CaféNorte turnover.

    Turnover =
        physical_units_sold / average_inventory_units

    Grain: SKU/product level (sku_erp).

    Inventory denominator (average physical-store inventory):
    - For each store-SKU combination with an observable inventory
      series (at least one inventory snapshot row in the period),
      compute its average inventory over the period.
    - Numeric 0 is included in that average.
    - N/A / NULL inventory readings are excluded from the average
      (never interpolated, never replaced with zero) via SQL AVG's
      native NULL-skipping behavior.
    - The per-store averages are summed to obtain average_inventory_units
      at SKU level.

    Physical sales numerator (matched-population rule):
    - Physical sales are included only for store-SKU combinations that
      have an observable inventory series in the period.
    - No inventory is imputed for physical store-SKU combinations with
      sales but no inventory series; those sales stay in fact_sales but
      are excluded from this Q1 calculation only.

    tipo_comprobante (document_type):
    - I, E, P, N, T are all included exactly as recorded.
    - cantidad (quantity) is used positive as recorded.
    - No filtering, no sign adjustment.

    Ecommerce is EXCLUDED from Q1 entirely (methodological scope
    decision):
    - Q1 is an inventory-turnover metric. The population-consistency
      principle already applied to physical sales (only store-SKU pairs
      with an observable inventory series participate) must also apply
      to ecommerce. The ecommerce source tells us which SKU was sold and
      how many units, but never which store, warehouse, fulfillment
      location, or inventory pool supplied the order. The only supplied
      inventory snapshots are store-level physical inventory, so
      ecommerce sales cannot be defensibly paired with that denominator.
    - This does NOT invalidate ecommerce sales: they remain in
      fact_sales, available to Q3 and any other sales analysis. They are
      excluded ONLY from this Q1 turnover calculation.
    """

    connection = duckdb.connect(
        str(database_path),
        read_only=True,
    )

    try:
        query = """
        WITH q1_window AS (
            SELECT
                DATE '2025-10-01' AS start_date,
                DATE '2026-03-31' AS end_date
        ),

        inventory_observed AS (
            -- Store-SKU combinations with an observable inventory
            -- series (any snapshot row) in the Q1 period.
            SELECT DISTINCT
                i.store_id,
                i.product_id
            FROM fact_inventory AS i
            CROSS JOIN q1_window AS w

            WHERE CAST(i.date AS DATE)
                BETWEEN w.start_date AND w.end_date
        ),

        inventory_by_store_product AS (
            SELECT
                i.store_id,
                i.product_id,

                AVG(i.stock_quantity) AS avg_stock,

                COUNT(i.stock_quantity) AS observed_days,
                COUNT(*) AS expected_days

            FROM fact_inventory AS i
            CROSS JOIN q1_window AS w

            WHERE CAST(i.date AS DATE)
                BETWEEN w.start_date AND w.end_date

            GROUP BY
                i.store_id,
                i.product_id
        ),

        inventory_by_product AS (
            SELECT
                product_id,

                SUM(avg_stock) AS average_inventory_units,

                COUNT(DISTINCT store_id) AS store_count,

                SUM(observed_days) AS observed_inventory_days,
                SUM(expected_days) AS expected_inventory_days

            FROM inventory_by_store_product

            GROUP BY
                product_id
        ),

        physical_sales_eligible AS (
            -- Physical sales counted only for store-SKU pairs with an
            -- observable inventory series (matched-population rule).
            -- Ecommerce never participates in Q1: it cannot be paired
            -- with a store-level inventory denominator (see docstring).
            SELECT
                s.product_id,

                SUM(s.quantity) AS physical_units_sold

            FROM fact_sales AS s
            CROSS JOIN q1_window AS w

            INNER JOIN inventory_observed AS io
                ON s.store_id = io.store_id
                AND s.product_id = io.product_id

            WHERE s.channel = 'physical'
                AND CAST(s.sold_at AS DATE)
                    BETWEEN w.start_date AND w.end_date

            GROUP BY
                s.product_id
        )

        SELECT
            p.product_id AS sku_erp,
            p.product_name,
            p.category,

            COALESCE(ph.physical_units_sold, 0) AS physical_units_sold,

            inv.average_inventory_units,
            inv.store_count,

            ROUND(
                100.0
                * inv.observed_inventory_days
                / inv.expected_inventory_days,
                2
            ) AS inventory_coverage_pct,

            CASE
                WHEN inv.average_inventory_units > 0
                THEN
                    COALESCE(ph.physical_units_sold, 0)
                    / inv.average_inventory_units
                ELSE NULL
            END AS inventory_turnover

        FROM dim_product AS p

        LEFT JOIN physical_sales_eligible AS ph
            ON p.product_id = ph.product_id

        LEFT JOIN inventory_by_product AS inv
            ON p.product_id = inv.product_id

        WHERE inv.average_inventory_units IS NOT NULL

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
    3 consecutive calendar days during the Question 2 reporting period
    (last complete quarter: 2026-01-01 through 2026-03-31 inclusive).

    A day is a confirmed zero-stock day only when stock_quantity
    is numeric 0. NULL (source "N/A") is unknown -- never zero --
    and therefore breaks/interrupts a zero-stock streak rather than
    extending it.
    """

    connection = duckdb.connect(
        str(database_path),
        read_only=True,
    )

    try:
        query = """
        WITH quarter_window AS (
            SELECT
                DATE '2026-01-01' AS start_date,
                DATE '2026-03-31' AS end_date
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


def get_q3_channel_mom(
    database_path: Path = DATABASE_PATH,
) -> pd.DataFrame:
    """
    Return month-over-month (MoM) sales growth by channel (physical vs.
    e-commerce) for the Question 3 reporting window
    (2025-04-01 through 2026-03-31 inclusive -- exactly 12 calendar
    months).

    "Ventas" = revenue in MXN.

    Currency normalization (accepted Q3 methodology):
    - Physical (sales.csv, field `monto`): already MXN, used as-is. No
      conversion, no filtering, no sign adjustment. tipo_comprobante
      I/E/P/N/T are all included exactly as recorded.
    - E-commerce (ecommerce_orders.parquet, field `amount`):
        - MXN rows: amount unchanged.
        - USD/EUR rows: amount_mxn = amount * rate_to_mxn, where
          rate_to_mxn comes from fact_exchange_rate matched by the
          transaction's calendar date and currency.
    - E-commerce is never assigned to a physical store and no
      fulfillment location is inferred.

    Monthly aggregation happens strictly AFTER per-transaction currency
    normalization: monthly_sales_mxn = SUM(amount_mxn) per channel per
    calendar month.

    MoM_pct = (current_month_sales_mxn - previous_month_sales_mxn)
              / previous_month_sales_mxn * 100

    First displayed month (April 2025):
    - Physical: MoM uses March 2025 physical revenue as the t-1
      baseline. March 2025 is used only for that calculation and is
      NOT part of the displayed 12-month table (filtered out below).
    - E-commerce: MoM is NULL because the supplied e-commerce source
      has no observation before April 2025. This is a property of the
      supplied dataset, not evidence the e-commerce channel began in
      April -- no such inference is made here.

    Grain: one row per (month, channel) -- 12 months x 2 channels = 24
    rows.

    Data integrity:
    - Every non-MXN transaction in the calculation range (including the
      March 2025 baseline month) must resolve to exactly one exchange
      rate for its calendar date + currency. If a rate is missing or
      duplicated, this function raises ValueError rather than letting
      the affected revenue silently drop out of SUM().
    """

    connection = duckdb.connect(
        str(database_path),
        read_only=True,
    )

    try:
        missing_rates = connection.execute("""
            SELECT DISTINCT
                s.currency,
                CAST(s.sold_at AS DATE) AS transaction_date
            FROM fact_sales AS s
            LEFT JOIN fact_exchange_rate AS fx
                ON fx.currency = s.currency
                AND fx.rate_date = CAST(s.sold_at AS DATE)
            WHERE s.currency <> 'MXN'
                AND CAST(s.sold_at AS DATE) >= DATE '2025-03-01'
                AND CAST(s.sold_at AS DATE) <= DATE '2026-03-31'
                AND fx.rate_to_mxn IS NULL
            ORDER BY transaction_date, s.currency
        """).fetchall()

        if missing_rates:
            preview = ", ".join(
                f"{currency} on {transaction_date}"
                for currency, transaction_date in missing_rates[:10]
            )

            raise ValueError(
                "Q3 data-integrity failure: "
                f"{len(missing_rates)} currency/date combination(s) "
                "with non-MXN sales have no exchange rate "
                f"(first {min(len(missing_rates), 10)}: {preview}). "
                "Refusing to drop that revenue silently."
            )

        duplicate_rates = connection.execute("""
            SELECT currency, rate_date, COUNT(*) AS rate_count
            FROM fact_exchange_rate
            GROUP BY currency, rate_date
            HAVING COUNT(*) > 1
            ORDER BY rate_date, currency
        """).fetchall()

        if duplicate_rates:
            preview = ", ".join(
                f"{currency} on {rate_date}"
                for currency, rate_date, _ in duplicate_rates[:10]
            )

            raise ValueError(
                "Q3 data-integrity failure: multiple exchange rates "
                "exist for the same date and currency "
                f"(first {min(len(duplicate_rates), 10)}: {preview}). "
                "Refusing to pick one silently."
            )

        query = """
        WITH normalized_sales AS (
            -- Per-transaction revenue normalized to MXN. Physical rows
            -- are MXN already. E-commerce MXN rows pass through
            -- unchanged; USD/EUR rows are converted using the rate
            -- matched by transaction calendar date + currency.
            SELECT
                s.channel,
                CAST(s.sold_at AS DATE) AS transaction_date,
                CASE
                    WHEN s.currency = 'MXN' THEN s.amount_native
                    WHEN fx.rate_to_mxn IS NOT NULL
                        THEN s.amount_native * fx.rate_to_mxn
                    ELSE NULL
                END AS amount_mxn
            FROM fact_sales AS s
            LEFT JOIN fact_exchange_rate AS fx
                ON fx.currency = s.currency
                AND fx.rate_date = CAST(s.sold_at AS DATE)
            WHERE s.channel IN ('physical', 'ecommerce')
        ),

        monthly_sales AS (
            -- Aggregation occurs strictly AFTER currency normalization.
            -- March 2025 is included here only to serve as the
            -- physical t-1 baseline for April 2025; it is filtered
            -- out of the final displayed output below.
            SELECT
                channel,
                DATE_TRUNC('month', transaction_date) AS month_start,
                SUM(amount_mxn) AS monthly_sales_mxn
            FROM normalized_sales
            WHERE transaction_date >= DATE '2025-03-01'
                AND transaction_date <= DATE '2026-03-31'
            GROUP BY
                channel,
                DATE_TRUNC('month', transaction_date)
        ),

        calendar_months AS (
            SELECT CAST(generate_series AS DATE) AS month_start
            FROM generate_series(
                DATE '2025-03-01',
                DATE '2026-03-01',
                INTERVAL 1 MONTH
            )
        ),

        channels AS (
            SELECT UNNEST(['physical', 'ecommerce']) AS channel
        ),

        full_series AS (
            -- Every (channel, month) combination is represented, even
            -- when a channel has no observed transactions in a given
            -- month, so LAG() sees a true absence (NULL) rather than
            -- silently skipping a month.
            SELECT
                ch.channel,
                cal.month_start,
                ms.monthly_sales_mxn
            FROM channels AS ch
            CROSS JOIN calendar_months AS cal
            LEFT JOIN monthly_sales AS ms
                ON ms.channel = ch.channel
                AND ms.month_start = cal.month_start
        ),

        with_mom AS (
            SELECT
                channel,
                month_start,
                monthly_sales_mxn,
                LAG(monthly_sales_mxn) OVER (
                    PARTITION BY channel
                    ORDER BY month_start
                ) AS previous_month_sales_mxn
            FROM full_series
        )

        SELECT
            month_start AS month,
            channel,
            monthly_sales_mxn AS sales_mxn,
            CASE
                WHEN previous_month_sales_mxn IS NULL THEN NULL
                ELSE ROUND(
                    (monthly_sales_mxn - previous_month_sales_mxn)
                    / previous_month_sales_mxn * 100,
                    2
                )
            END AS mom_pct
        FROM with_mom
        WHERE month_start >= DATE '2025-04-01'
            AND month_start <= DATE '2026-03-01'
        ORDER BY
            month_start,
            channel
        """

        return connection.execute(query).fetchdf()

    finally:
        connection.close()


def get_q4_negative_margin(
    database_path: Path = DATABASE_PATH,
) -> pd.DataFrame:
    """
    Return store + SKU (sku_erp) combinations with negative aggregate
    margin over the full available physical sales history
    (2024-10-01 through 2026-03-31 inclusive) -- accepted Q4 methodology.

    Population (accepted Q4 methodology):
    - Physical sales only (fact_sales.channel = 'physical'). Ecommerce
      is never included in this store-level answer, is never assigned
      to a physical store, and no fulfillment location is inferred --
      its schema cannot answer the requested "en que tiendas" (which
      stores) dimension.
    - tipo_comprobante (document_type) I, E, P, N, T are all included
      exactly as recorded. No filtering, no sign adjustment.
    - Product reconciliation to sku_erp uses the existing accepted
      canonical bridge (src/reconcile.py), applied upstream when
      fact_sales was built. It is not re-evaluated here.

    Cost (accepted Q4 methodology):
    - Source: fact_product_cost (fecha_vigencia -> effective_date,
      costo_mxn -> cost_mxn), the full, non-collapsed cost history.
    - costo_mxn is treated as a per-unit product cost.
    - The applicable cost for a sale is the latest cost_history row for
      that sale's sku_erp where effective_date <= the sale's calendar
      date. No future cost may ever be used.
    - transaction_cost_mxn = cantidad * applicable_costo_mxn
    - transaction_margin_mxn = monto - transaction_cost_mxn

    Grain: store_id + sku_erp. Over the full period:
        revenue_mxn = SUM(monto)
        cost_mxn    = SUM(cantidad * applicable_costo_mxn)
        margin_mxn  = revenue_mxn - cost_mxn
        margin_pct  = margin_mxn / revenue_mxn * 100

    Qualification rule: margin_mxn < 0. margin_mxn (not margin_pct) is
    the authoritative qualification rule, since revenue is positive and
    margin_pct should carry the same sign.

    Data integrity:
    - If any physical sale in the period has no applicable cost row
      (no cost_history entry with effective_date <= sale date for its
      sku_erp), this function raises ValueError rather than silently
      defaulting that sale's cost to zero or dropping the sale.
    """

    connection = duckdb.connect(
        str(database_path),
        read_only=True,
    )

    try:
        # ------------------------------------------------------------
        # Data-integrity gate: every physical sale in the period must
        # resolve to an applicable cost. A sale with no cost_history
        # row at or before its sale date is a data-integrity failure,
        # not a zero-cost default.
        # ------------------------------------------------------------
        integrity_query = """
        WITH q4_window AS (
            SELECT
                DATE '2024-10-01' AS start_date,
                DATE '2026-03-31' AS end_date
        ),

        physical_sales AS (
            SELECT
                s.transaction_id,
                s.product_id,
                CAST(s.sold_at AS DATE) AS sale_date
            FROM fact_sales AS s
            CROSS JOIN q4_window AS w

            WHERE s.channel = 'physical'
                AND CAST(s.sold_at AS DATE)
                    BETWEEN w.start_date AND w.end_date
        ),

        cost_matches AS (
            SELECT
                ps.transaction_id,
                ps.product_id,
                c.cost_mxn AS applicable_cost_mxn,
                ROW_NUMBER() OVER (
                    PARTITION BY ps.transaction_id
                    ORDER BY c.effective_date DESC
                ) AS rn
            FROM physical_sales AS ps
            LEFT JOIN fact_product_cost AS c
                ON c.product_id = ps.product_id
                AND c.effective_date <= ps.sale_date
        )

        SELECT DISTINCT product_id
        FROM cost_matches
        WHERE rn = 1
            AND applicable_cost_mxn IS NULL
        ORDER BY product_id
        """

        unresolved = connection.execute(
            integrity_query
        ).fetchdf()

        if not unresolved.empty:
            raise ValueError(
                "Q4 data-integrity failure: no applicable "
                "cost_history entry (fecha_vigencia <= sale date) "
                "exists for one or more physical sales of the "
                "following sku_erp product(s). Refusing to default "
                "to zero cost or silently drop the affected sales: "
                f"{sorted(unresolved['product_id'].tolist())}"
            )

        # ------------------------------------------------------------
        # Main aggregation: store + sku_erp margin over the full
        # period, using the same latest-applicable-cost resolution
        # validated above.
        # ------------------------------------------------------------
        query = """
        WITH q4_window AS (
            SELECT
                DATE '2024-10-01' AS start_date,
                DATE '2026-03-31' AS end_date
        ),

        physical_sales AS (
            SELECT
                s.transaction_id,
                s.store_id,
                s.product_id,
                CAST(s.sold_at AS DATE) AS sale_date,
                s.quantity,
                s.amount_native AS monto
            FROM fact_sales AS s
            CROSS JOIN q4_window AS w

            WHERE s.channel = 'physical'
                AND CAST(s.sold_at AS DATE)
                    BETWEEN w.start_date AND w.end_date
        ),

        cost_matches AS (
            SELECT
                ps.transaction_id,
                c.cost_mxn AS applicable_cost_mxn,
                ROW_NUMBER() OVER (
                    PARTITION BY ps.transaction_id
                    ORDER BY c.effective_date DESC
                ) AS rn
            FROM physical_sales AS ps
            LEFT JOIN fact_product_cost AS c
                ON c.product_id = ps.product_id
                AND c.effective_date <= ps.sale_date
        ),

        best_cost AS (
            SELECT
                transaction_id,
                applicable_cost_mxn
            FROM cost_matches
            WHERE rn = 1
        ),

        transaction_costed AS (
            SELECT
                ps.store_id,
                ps.product_id,
                ps.monto,
                ps.quantity * bc.applicable_cost_mxn
                    AS transaction_cost_mxn
            FROM physical_sales AS ps

            INNER JOIN best_cost AS bc
                ON bc.transaction_id = ps.transaction_id
        ),

        agg AS (
            SELECT
                store_id,
                product_id AS sku_erp,

                SUM(monto) AS revenue_mxn,
                SUM(transaction_cost_mxn) AS cost_mxn,
                SUM(monto) - SUM(transaction_cost_mxn) AS margin_mxn

            FROM transaction_costed

            GROUP BY
                store_id,
                product_id
        )

        SELECT
            a.store_id,
            a.sku_erp,
            p.product_name,
            a.revenue_mxn,
            a.cost_mxn,
            a.margin_mxn,
            ROUND(
                a.margin_mxn / a.revenue_mxn * 100,
                2
            ) AS margin_pct

        FROM agg AS a

        LEFT JOIN dim_product AS p
            ON p.product_id = a.sku_erp

        WHERE a.margin_mxn < 0

        ORDER BY
            a.margin_mxn ASC
        """

        return connection.execute(query).fetchdf()

    finally:
        connection.close()