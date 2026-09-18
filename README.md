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

`exchange_rates.csv` is not one of the three sources named in the original challenge narrative, but it was confirmed by the challenge owner as official material required for currency normalization in Q3. It is treated here as a first-class source, not as an incidental or unofficial file.

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

`scripts/run_pipeline.py` rebuilds `data/processed/cafenorte.duckdb` from the raw sources end to end (load → reconcile → transform → persist). This has been validated with a clean rebuild from raw sources, and the current full test suite result is **36 passed**.

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
- All 33 Shopify products observed in the Q1 window reconcile to a canonical SKU.

## 5. Business Question 1 — Inventory Turnover (Top 10 SKUs)

*Top 10 SKUs por rotación de inventario en los últimos 6 meses.*

- **Period:** 2025-10-01 through 2026-03-31 (inclusive).
- **Formula:** `inventory_turnover = total_units_sold / average_inventory_units`
- **Inventory (denominator):** for each store-SKU pair with at least one observable inventory snapshot in the period, average its numeric readings (numeric `0` counts as an observation; `N/A`/`NULL` is excluded, never interpolated or replaced with `0`). Store-SKU averages are summed to the SKU level.
- **Physical sales (numerator):** included only for store-SKU pairs that have an observable inventory series in the period. No inventory is imputed for pairs with sales but no inventory series — those sales remain valid elsewhere in `fact_sales`, just outside this specific calculation.
- **E-commerce:** participates at the SKU level only. It is never assigned to a physical store and no fulfillment store is inferred.
- **`tipo_comprobante`:** values I/E/P/N/T are all counted as recorded; their semantics are not defined by the supplied data, so no filtering or sign reversal was introduced without evidence.

**Limitation:** 24,018 of 44,336 physical units (54.17%) belong to store-SKU combinations that have no inventory series and therefore cannot participate in this calculation. This is not evidence of missing inventory, an assortment gap, a stockout, or an extraction error — the business meaning of that absence is unknown from the supplied data. Those units remain valid sales data elsewhere.

**Final result:**

| # | SKU | Physical | E-commerce | Total | Avg inventory | Turnover |
|---|---|---:|---:|---:|---:|---:|
| 1 | ERP-PROV-MX-057-C | 199 | 225 | 424 | 478.735987 | 0.885666 |
| 2 | ERP-PROV-MX-037-C | 260 | 211 | 471 | 599.049042 | 0.786246 |
| 3 | ERP-PROV-MX-047-B | 343 | 198 | 541 | 713.322050 | 0.758423 |
| 4 | ERP-PROV-MX-041-D | 182 | 209 | 391 | 523.717058 | 0.746586 |
| 5 | ERP-PROV-MX-003-D | 269 | 200 | 469 | 638.307808 | 0.734755 |
| 6 | ERP-PROV-MX-030-C | 213 | 196 | 409 | 561.644324 | 0.728219 |
| 7 | ERP-PROV-MX-004-B | 265 | 196 | 461 | 635.040262 | 0.725938 |
| 8 | ERP-PROV-MX-024-A | 265 | 242 | 507 | 698.625776 | 0.725710 |
| 9 | ERP-PROV-MX-052-C | 322 | 215 | 537 | 743.987721 | 0.721786 |
| 10 | ERP-PROV-MX-054-B | 309 | 242 | 551 | 764.175743 | 0.721038 |

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
- **Currency:** physical `monto` is already MXN; e-commerce MXN rows are unchanged; e-commerce USD/EUR rows are converted with `amount_mxn = amount * rate_to_mxn`, where the rate is matched by transaction date + currency. 0 USD/EUR rows were left unmatched.
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
| A1 | `tipo_comprobante` (I/E/P/N/T) semantics are not defined in the supplied data; all values are counted as recorded in every question, with no filtering or sign reversal. | Methodological interpretation |
| A2 | `costo_mxn` is treated as a per-unit product cost (used in Q4). | Methodological interpretation |
| A3 | Q1 inventory turnover is conditional on observable physical inventory coverage; 54.17% of physical units fall outside an inventory series and cannot participate in that calculation. | Limitation |
| A4 | A store-SKU combination absent from `fact_inventory`, or a `N/A` snapshot value, means "unknown," not zero. No interpolation or zero-substitution is applied anywhere. | Observed fact |
| A5 | The e-commerce source carries no physical-store dimension; no store or fulfillment location is inferred for e-commerce transactions (affects Q1 and Q4). | Observed fact |
| A6 | The supplied e-commerce dataset has no observation before 2025-04-01; this is a property of the dataset, not evidence of when the Shopify channel actually began operating. | Observed fact / Limitation |
| A7 | Where source data limits analytical coverage (Q1, Q4 scope), that absence is not assigned an unsupported business meaning (e.g., not described as a stockout, assortment gap, or extraction error). | Limitation |

## 10. Testing / Reproducibility

```bash
python scripts/run_pipeline.py
python -m pytest -q
```

A clean rebuild from raw sources was validated end to end:

- Q1, Q2, Q3, and Q4 results reproduced exactly as documented above.
- Full test suite: **36 passed**.
