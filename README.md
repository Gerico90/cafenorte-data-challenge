# CaféNorte — Data Solutions Engineer Technical Challenge

Data pipeline that consolidates CaféNorte's physical (POS) and e-commerce (Shopify) sales, ERP inventory/catalog/cost data, and official FX rates into a single analytical model, and answers four business questions on top of it.

## 1. Project Overview

The pipeline integrates four sources:

| Source | File | Description |
|---|---|---|
| Physical POS sales | `sales.csv` | Point-of-sale transactions across 40 stores |
| ERP inventory / catalog / cost | `inventory.json` | Legacy ERP: product catalog, `sku_mappings`, daily inventory snapshots, product cost history |
| E-commerce orders | `ecommerce_orders.parquet` | Shopify orders |
| Exchange rates | `exchange_rates.csv` | Daily FX rates, used to normalize non-MXN e-commerce revenue to MXN |

`exchange_rates.csv` is not one of the three sources named in the original challenge narrative, but it was confirmed by the challenge owner as official challenge material. This solution uses it to normalize non-MXN e-commerce revenue in Q3. It is treated here as a first-class source, not as an incidental or unofficial file.

**Technology stack**

- Python 3.11
- pandas 3.0.2
- DuckDB 1.5.5
- pyarrow 25.0.1
- pytest 9.1.1

This is a local, single-machine stack: the supplied datasets are small/medium in size (largest table is ~230K rows), the target output is a set of four analytical queries rather than a streaming or low-latency service, and DuckDB provides a SQL-friendly analytical engine over the same process without requiring a distributed runtime. Distributed processing (Spark, cloud warehouses, etc.) would add operational overhead disproportionate to this data volume and this challenge's scope.

## Repository Structure

```text
cafenorte-data-challenge/
├── data/
│   ├── raw/            # challenge source files (gitignored)
│   └── processed/      # cafenorte.duckdb (generated, gitignored)
├── docs/
│   └── aws_proposal.md          # AWS architecture proposal (not part of Q1-Q4)
├── scripts/
│   ├── run_pipeline.py             # CLI entry point
│   └── validate_data_assumptions.py
├── src/
│   ├── load.py                     # raw source loading only
│   ├── reconcile.py                # product identifier reconciliation
│   ├── transform.py                # analytical model construction
│   ├── business_questions.py       # Q1-Q4 DuckDB queries
│   └── pipeline.py                 # orchestration + persistence
├── tests/
│   ├── test_reconciliation.py
│   ├── test_transformations.py
│   └── test_business_questions.py
├── AI_LOG.md
├── README.md
└── requirements.txt
```

## 2. How to Run

From the repository root, with the four raw files placed in `data/raw/`:

```bash
pip install -r requirements.txt
python scripts/run_pipeline.py
python -m pytest -q
```

`scripts/run_pipeline.py` rebuilds `data/processed/cafenorte.duckdb` from the raw sources end to end (load → reconcile → transform → persist). This has been validated with a clean rebuild from raw sources, and the current full test suite result is **41 passed**.

`data/processed/` may also contain timestamped `*.bak_*` backup copies of the DuckDB file created incidentally during local iteration. These backups are not part of the required workflow and are not produced or consumed by `run_pipeline.py`, `business_questions.py`, or the test suite.

## 3. Pipeline Flow

```text
load_sources()                              (src/load.py)
        ↓
build_product_bridge() + reconcile_*()      (src/reconcile.py)
        ↓
build_analytical_model()                    (src/transform.py)
        ↓
persist_analytical_model()  → cafenorte.duckdb   (src/pipeline.py)
        ↓
get_q1..q4_*()                              (src/business_questions.py)
```

`build_analytical_model` produces six tables, persisted as-is into DuckDB:

| Table | Grain | Rows |
|---|---|---|
| `dim_product` | canonical product (`product_id` = `sku_erp`) | 70 |
| `dim_store` | physical store | 40 |
| `fact_sales` | one transaction, physical or e-commerce | 96,437 (86,490 physical + 9,947 e-commerce) |
| `fact_inventory` | store × product × day | 230,776 |
| `fact_product_cost` | product × cost effective date (full history, not collapsed) | 282 |
| `fact_exchange_rate` | rate date × currency (USD/EUR) | 730 |

`fact_sales` keeps `amount_native` + `currency` per transaction; MXN normalization for non-MXN e-commerce rows is applied at query time in Q3 via `fact_exchange_rate`, not during model construction.

## 4. Product Reconciliation

`product_id` (`sku_erp`) is the canonical identifier for every product in the analytical model.

Reconciliation priority, applied in `src/reconcile.py`:

1. **Explicit mapping** from `inventory.json → sku_mappings` (POS SKU or Shopify handle → `sku_erp`).
2. **Numeric fallback**, applied only when no explicit mapping exists for that identifier *and* the numeric component extracted from it resolves to exactly one ERP product.
3. No fuzzy name matching is performed anywhere in reconciliation.

The mapping method used for each observed product is retained in `dim_product` as `pos_mapping_method` / `shopify_mapping_method`, with values `explicit`, `inferred_numeric_pattern`, or `not_observed`.

**Final coverage**

- 70 / 70 physical POS SKUs reconciled to a canonical `sku_erp`.
- 0 physical sales rows unreconciled.
- All 33 Shopify products observed in the same period reconcile to a canonical SKU. This reconciliation coverage is a general pipeline fact used in Q3; it does not by itself mean e-commerce participates in the Q1 turnover calculation — see section 5.

## 5. Business Question 1 — Inventory Turnover (Top 10 SKUs)

*Top 10 SKUs por rotación de inventario en los últimos 6 meses.*

- **Period:** 2025-10-01 through 2026-03-31 (inclusive).
- **Scope:** physical (POS) sales only. Q1 measures inventory turnover only for physical store-product combinations where both sales and inventory are observable. This exclusion applies only to Q1; e-commerce is not excluded from the analytical model, remains fully reconciled at SKU level in `fact_sales`, is used in Q3, and is available for any other sales analysis where it is appropriate.
- **Formula:** `inventory_turnover = physical_units_sold_from_inventory_observable_store_product_pairs / average_inventory_units`
- **Inventory (denominator):** for each store-SKU pair with at least one observable inventory snapshot in the period, average its numeric readings (numeric `0` counts as an observation; `N/A`/`NULL` is excluded, never interpolated or replaced with `0`). Store-SKU averages are summed to the SKU level.
- **Physical sales (numerator):** included only for store-SKU pairs that have an observable inventory series in the period. No inventory is imputed for pairs with sales but no inventory series — those sales remain valid elsewhere in `fact_sales`, just outside this specific calculation.
- **E-commerce:** excluded from the Q1 numerator and denominator. This is a numerator/denominator population-consistency decision, not a data-quality problem: the e-commerce source tells us which product was sold and how many units, but it does not identify the store, warehouse, fulfillment location, or inventory pool that supplied the order, and the supplied inventory snapshots are physical-store inventory. Pairing e-commerce demand with the physical-store inventory denominator is not supported by the supplied data. This does **not** mean e-commerce inventory is missing — it means the supplied data does not identify the inventory pool that fulfilled e-commerce orders. See the disclosure below for the exact volume excluded.
- **`tipo_comprobante`:** all five observed codes (I, E, P, N, T) are counted exactly as recorded, with no filtering and no sign reversal.

`sales.csv` carries a `tipo_comprobante` column with five letter codes: I, E, P, N, T. As external context only, these letters happen to match Mexico's official SAT CFDI catalogue (`c_TipoDeComprobante`: I = Ingreso, E = Egreso, T = Traslado, N = Nómina, P = Pago). That catalogue is mentioned here purely for reference — the CaféNorte source itself never states that `tipo_comprobante` is a CFDI export, and it is missing the fiscal fields (UUID, complemento de pago, and similar) that would be needed to actually confirm CFDI behavior. Assuming SAT semantics apply, just because the letters match, would not be supported by the data.

Instead, the field was checked directly: quantity, amount, amount-per-unit, time-of-day/day-of-week/monthly patterns, and store/SKU concentration were compared across the five codes, and the data was searched for pairs of rows that could represent a reversal or adjustment. No code showed a pattern distinguishing it from an ordinary sale, quantities and amounts are positive across all five codes, and no reversal pairs were found. Because the supplied data gives no evidence for treating any code differently, all five are counted as recorded.

**Coverage disclosure (physical units):** of 44,336 total physical units sold in the Q1 period, 20,318 belong to store-SKU combinations with an observable inventory series and are included in this calculation; the remaining 24,018 (54.17%) belong to store-SKU combinations that have no observable inventory series and therefore cannot participate in this calculation. This is not evidence of missing inventory, an assortment gap, a stockout, or an extraction error — the business meaning of that absence is unknown from the supplied data. Those 24,018 units remain valid sales data elsewhere in `fact_sales`.

**Coverage disclosure (e-commerce):** 6,627 e-commerce units were sold during the same period. They are not included in this calculation because the supplied data does not identify the inventory pool that fulfilled those orders — not because the sales are invalid. Those units also remain valid sales data, fully reconciled at SKU level in `fact_sales`, and are used in Q3 and any other appropriate sales analysis.

**On the missing inventory series:** store-product combinations with no inventory series at all are treated as unknown, and no stock value is fabricated for them. This submission does not adopt an imputation rule because the supplied data does not provide a sufficiently defensible basis for one; the gap above is therefore left as missing rather than estimated.

This result is a physical-store inventory-turnover ranking. It is not a company-wide or omnichannel turnover figure.

**Final result:**

| Rank | product_id | physical_units_sold | avg_inventory_units | inventory_turnover |
|---|---|---:|---:|---:|
| 1 | ERP-PROV-MX-068-C | 369 | 710.32 | 0.519482 |
| 2 | ERP-PROV-MX-015-D | 340 | 684.12 | 0.496989 |
| 3 | ERP-PROV-MX-049-A | 365 | 742.47 | 0.491602 |
| 4 | ERP-PROV-MX-047-B | 343 | 713.32 | 0.480849 |
| 5 | ERP-PROV-MX-067-C | 336 | 720.83 | 0.466130 |
| 6 | ERP-PROV-MX-036-A | 315 | 684.53 | 0.460167 |
| 7 | ERP-PROV-MX-012-B | 241 | 525.94 | 0.458228 |
| 8 | ERP-PROV-MX-059-B | 326 | 726.95 | 0.448451 |
| 9 | ERP-PROV-MX-069-C | 317 | 719.08 | 0.440838 |
| 10 | ERP-PROV-MX-053-A | 291 | 665.03 | 0.437576 |

## 6. Business Question 2 — Stockouts Over 3 Days (Last Quarter)

*Tiendas con quiebres de stock de más de 3 días en el último trimestre.*

- **Period:** last complete calendar quarter, 2026-01-01 through 2026-03-31.
- **Stockout observation:** numeric inventory `== 0`.
- **Qualifying event:** more than 3 consecutive calendar days of confirmed zero stock.
- **`N/A` handling:** unknown, and interrupts a zero-stock streak rather than extending it.
- Events are detected at store-SKU grain, then reported at store level.

**Final result:**

| Store | SKU | Start | End | Days |
|---|---|---|---|---:|
| T015 | ERP-PROV-MX-014-D | 2026-02-09 | 2026-02-12 | 4 |
| T023 | ERP-PROV-MX-046-A | 2026-01-25 | 2026-01-28 | 4 |
| T038 | ERP-PROV-MX-040-A | 2026-03-18 | 2026-03-21 | 4 |

## 7. Business Question 3 — Month-over-Month Revenue Growth by Channel

*Crecimiento mes a mes (MoM) de ventas por canal (físico vs. e-commerce) en el último año.*

- **"Ventas"** is interpreted as revenue.
- **Reporting period:** 2025-04 through 2026-03 (12 months).
- **Currency:** physical `monto` is already MXN; e-commerce MXN rows are unchanged; e-commerce USD/EUR rows are converted with `amount_mxn = amount * rate_to_mxn`, where the rate is matched by transaction date + currency. 0 USD/EUR rows were left unmatched. `get_q3_channel_mom()` enforces this: if any non-MXN transaction in the calculation range lacks an exchange rate for its date + currency, or an FX date + currency is duplicated, it raises a `ValueError` instead of silently dropping that revenue.
- **MoM:** `(current_month − previous_month) / previous_month * 100`.
- **First month (April 2025):** physical MoM uses March 2025 physical revenue as baseline (March itself is not displayed). E-commerce April 2025 is `N/A` because the supplied e-commerce dataset has no observation before April 2025 — this reflects the supplied dataset only, not a claim that Shopify sales began in April 2025.

**Final result:**

| Month | Channel | Revenue (MXN) | MoM % |
|---|---|---:|---:|
| 2025-04 | ecommerce | 383,213.10 | N/A |
| 2025-04 | physical | 1,673,072.00 | -2.38 |
| 2025-05 | ecommerce | 365,088.20 | -4.73 |
| 2025-05 | physical | 1,796,953.00 | 7.40 |
| 2025-06 | ecommerce | 339,352.30 | -7.05 |
| 2025-06 | physical | 1,712,535.00 | -4.70 |
| 2025-07 | ecommerce | 350,578.50 | 3.31 |
| 2025-07 | physical | 1,790,212.00 | 4.54 |
| 2025-08 | ecommerce | 343,799.80 | -1.93 |
| 2025-08 | physical | 1,778,834.00 | -0.64 |
| 2025-09 | ecommerce | 345,453.80 | 0.48 |
| 2025-09 | physical | 1,684,031.00 | -5.33 |
| 2025-10 | ecommerce | 376,497.20 | 8.99 |
| 2025-10 | physical | 1,817,582.00 | 7.93 |
| 2025-11 | ecommerce | 359,337.60 | -4.56 |
| 2025-11 | physical | 1,680,699.00 | -7.53 |
| 2025-12 | ecommerce | 346,649.20 | -3.53 |
| 2025-12 | physical | 1,778,998.00 | 5.85 |
| 2026-01 | ecommerce | 344,899.10 | -0.50 |
| 2026-01 | physical | 1,713,210.00 | -3.70 |
| 2026-02 | ecommerce | 323,250.60 | -6.28 |
| 2026-02 | physical | 1,576,722.00 | -7.97 |
| 2026-03 | ecommerce | 350,763.40 | 8.51 |
| 2026-03 | physical | 1,718,189.00 | 8.97 |

## 8. Business Question 4 — Products with Negative Margin, by Store

*Productos con margen negativo y en qué tiendas ocurren.*

- **Period:** full physical sales history, 2024-10-01 through 2026-03-31.
- **Methodological assumption:** `costo_mxn` is treated as a per-unit product cost. The source does not state this unit semantic explicitly.
- **Applicable cost:** the latest `cost_history` row for the SKU where `fecha_vigencia <= sale date`.
- **Per transaction:** `cost = cantidad * applicable costo_mxn`; `margin = monto - cost`.
- **Aggregation:** store + SKU. Qualifying rows have `margin_mxn < 0`.
- **Coverage:** 70/70 POS SKUs reconciled; 86,490/86,490 physical sales resolved to an applicable cost; no duplicate cost effective dates; no unresolved cost rows.
- **Scope note:** e-commerce is not included in this output because the requested result requires a store dimension that the e-commerce source does not carry; no store or fulfillment location is inferred for it.

**Final result summary:** 120 negative store-SKU combinations, across 40 stores, involving 3 SKUs — each of the 3 negative in all 40 stores. `get_q4_negative_margin()` returns the full 120-row detail (store, SKU, revenue, cost, margin, margin %); the table below is the concise product-level view.

| SKU | Product | Stores with negative margin |
|---|---|---:|
| ERP-PROV-MX-001-A | Sándwich Comida Caliente | 40 / 40 |
| ERP-PROV-MX-002-B | Sándwich Comida Caliente | 40 / 40 |
| ERP-PROV-MX-015-D | Especial Cafe Molido | 40 / 40 |

## 9. Assumptions / Limitations

| # | Statement | Type |
|---|---|---|
| A1 | `tipo_comprobante` (I/E/P/N/T) letters match SAT's CFDI catalogue, but the supplied data does not prove this field is a CFDI export and shows no behavioral difference between codes; all values are counted as recorded in every question, with no filtering or sign reversal. | Methodological interpretation |
| A2 | `costo_mxn` is treated as a per-unit product cost (used in Q4). | Methodological interpretation |
| A3 | Q1 inventory turnover is conditional on observable physical inventory coverage; 54.17% of physical units (24,018 of 44,336) fall outside an inventory series and cannot participate in that calculation. | Limitation |
| A4 | A store-SKU combination absent from `fact_inventory`, or a `N/A` snapshot value, means "unknown," not zero. No interpolation or zero-substitution is applied anywhere. | Observed fact |
| A5 | The e-commerce source carries no physical-store dimension; no store or fulfillment location is inferred for e-commerce transactions (affects Q1 and Q4). Because of this, e-commerce is excluded from Q1 (6,627 units in the period): it cannot be defensibly paired with the physical-store inventory denominator. This exclusion applies only to Q1 — e-commerce remains in `fact_sales`, fully reconciled at SKU level, and is used in Q3 and any other appropriate sales analysis. | Observed fact / Methodological interpretation |
| A6 | The supplied e-commerce dataset has no observation before 2025-04-01; this is a property of the dataset, not evidence of when the Shopify channel actually began operating. | Observed fact / Limitation |
| A7 | Where source data limits analytical coverage (Q1, Q4 scope), that absence is not assigned an unsupported business meaning (e.g., not described as a stockout, assortment gap, or extraction error). | Limitation |

## 10. Testing / Reproducibility

```bash
python scripts/run_pipeline.py
python -m pytest -q
```

A clean rebuild from raw sources was validated end to end:

- Q1, Q2, Q3, and Q4 results reproduced exactly as documented above.
- Full test suite: **41 passed**.
