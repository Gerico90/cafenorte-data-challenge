# CaféNorte — Data Solutions Engineer Technical Challenge

Technical challenge focused on building a data pipeline that integrates and reconciles CaféNorte's POS, ERP inventory, and Shopify e-commerce data.

## Current Status

The project currently includes:

- Source ingestion for POS, ERP inventory, and Shopify data.
- Product reconciliation across the three source systems.
- Normalization into analytical tables.
- Persistence of the analytical model in DuckDB.
- Local validation of the main reconciliation and inventory assumptions.
- Reproducible dependency definitions through `requirements.txt`.

The business questions, automated tests, and production architecture proposal have not been implemented yet.

## Repository Structure

```text
cafenorte-data-challenge/
├── data/
│   ├── raw/
│   └── processed/
├── docs/
├── scripts/
│   ├── run_pipeline.py
│   └── validate_data_assumptions.py
├── src/
│   ├── load.py
│   ├── reconcile.py
│   ├── transform.py
│   ├── business_questions.py
│   └── pipeline.py
├── tests/
│   ├── test_reconciliation.py
│   ├── test_transformations.py
│   └── test_business_questions.py
├── .gitignore
├── AI_LOG.md
├── README.md
└── requirements.txt
```

Some files are currently placeholders for later implementation.

## Current Local Stack

The current pipeline uses:

- Python 3.11
- pandas 3.0.2
- pyarrow 25.0.1
- DuckDB 1.5.5

The supplied datasets are small enough to process locally without distributed-computing tooling.

## Source Data

The current pipeline reads these three challenge sources from:

```text
data/raw/
```

Expected filenames:

```text
sales.csv
inventory.json
ecommerce_orders.parquet
```

Raw challenge data is excluded from Git through `.gitignore`.

## Pipeline Flow

The current implemented flow is:

```text
Raw source files
        ↓
     load.py
        ↓
  reconcile.py
        ↓
  transform.py
        ↓
   pipeline.py
        ↓
data/processed/cafenorte.duckdb
```

### `src/load.py`

Responsible only for loading the original source files.

It currently provides:

```text
load_sales()
load_ecommerce()
load_inventory()
load_sources()
```

No data cleaning, reconciliation, or business logic is performed during ingestion.

### `src/reconcile.py`

Responsible for reconciling product identifiers across POS, ERP, and Shopify.

The three systems represent products differently:

```text
POS       → CN-00030
ERP       → ERP-PROV-MX-030-C
Shopify   → molinillo-mercancia-030
```

The ERP `sku_erp` is used as the canonical product identifier in the analytical model.

### `src/transform.py`

Responsible for transforming the reconciled source data into analytical tables.

The current model contains:

```text
dim_product
dim_store
fact_sales
fact_inventory
fact_product_cost
```

### `src/pipeline.py`

Runs the complete current local flow:

```text
load
→ reconcile
→ transform
→ persist
```

The analytical model is persisted in:

```text
data/processed/cafenorte.duckdb
```

## Product Reconciliation

The ERP source contains a `sku_mappings` structure relating POS, ERP, and Shopify identifiers, but that mapping is incomplete.

Before implementing fallback reconciliation, the identifier relationships were validated against the provided datasets.

Observed validation results:

```text
Known POS → ERP mappings:
60 checked
60 numeric-component matches
0 mismatches

Known POS → Shopify mappings:
27 checked
27 numeric-component matches
0 mismatches

Rows containing POS + ERP + Shopify identifiers:
23 checked
23 consistent
0 mismatches
```

The ERP catalog contains:

```text
70 products
70 parsed numeric product components
70 unique numeric product components
0 collisions
```

Additional collision checks found:

```text
POS numeric collisions:      0
ERP numeric collisions:      0
Shopify numeric collisions:  0
Explicit mapping conflicts:  0
```

### Reconciliation Rule

Product reconciliation currently follows this order:

1. Use the explicit relationship from `sku_mappings` when an ERP relationship is available.
2. Only when an explicit ERP relationship is missing, extract the numeric product component from the source identifier.
3. Use the numeric component as a fallback only when it resolves to exactly one ERP product.
4. Reject ambiguous or contradictory relationships.
5. Do not use fuzzy product-name matching.

The reconciliation method is retained in the product dimension as:

```text
explicit
inferred_numeric_pattern
not_observed
```

The numeric fallback is considered valid for the supplied challenge datasets only. It is not assumed to be a permanent upstream-system contract.

## Reconciliation Coverage

The implemented reconciliation currently resolves all observed sales records to a canonical ERP product.

For the six-month period validated during source analysis:

```text
POS
rows:              28,622
mapped rows:       28,622
unmapped rows:          0
total units:       44,336
mapped units:      44,336
unmapped units:         0
```

```text
Shopify
rows:               4,985
mapped rows:        4,985
unmapped rows:          0
total units:        6,627
mapped units:       6,627
unmapped units:         0
```

The full reconciled pipeline currently also reports:

```text
POS explicit mappings:          60
POS inferred mappings:          10

Shopify explicit mappings:      23
Shopify inferred mappings:      10

Unreconciled POS sales rows:      0
Unreconciled Shopify rows:        0
```

## Inventory Structure Validation

The inventory snapshots cover:

```text
2025-10-01 through 2026-03-31
182 distinct calendar days
```

There are:

```text
1,268 unique store-SKU pairs
230,776 total inventory snapshots
```

Every observed store-SKU pair contains all 182 daily snapshots:

```text
minimum days per pair:       182
maximum days per pair:       182
median days per pair:        182
pairs with full coverage:  1,268
pairs with partial coverage:  0
```

Every calendar day also contains exactly:

```text
1,268 inventory rows
```

### Missing Inventory Values

The source contains:

```text
4,417 values recorded as "N/A"
```

These values are preserved as missing values in the analytical model.

They are not converted to zero.

Missingness by store-SKU pair is limited:

```text
minimum N/A days:          0
maximum N/A days:         10
median N/A days:           3
mean N/A days:          3.48
maximum missing rate:   5.49%
```

Therefore the model distinguishes between:

```text
stock_quantity = 0
```

which represents an observed zero-stock value,

and:

```text
stock_quantity = NULL
```

which represents an unknown stock quantity from a source `"N/A"` value.

A store-SKU combination that does not exist in the source is not automatically interpreted as zero inventory.

## Analytical Model

### `dim_product`

Current columns:

```text
product_id
product_name
category
sku_pos
product_handle
product_number
pos_mapping_method
shopify_mapping_method
```

Current row count:

```text
70
```

### `dim_store`

Current columns:

```text
store_id
city
region
timezone
```

Current row count:

```text
40
```

### `fact_sales`

Physical POS and Shopify transactions are stored in the same fact table.

Current columns:

```text
transaction_id
sold_at
product_id
channel
store_id
quantity
amount_native
currency
document_type
```

Physical transactions use:

```text
channel = physical
```

Shopify transactions use:

```text
channel = ecommerce
```

Shopify records do not contain a physical `store_id`, so no physical store association is inferred.

Current row count:

```text
96,437
```

Composed of:

```text
86,490 POS rows
 9,947 Shopify rows
-------
96,437 total rows
```

Monetary values are currently preserved in their original source currency through:

```text
amount_native
currency
```

No currency normalization has been implemented yet.

### `fact_inventory`

Current columns:

```text
date
store_id
product_id
stock_quantity
```

Current row count:

```text
230,776
```

### `fact_product_cost`

The ERP product `cost_history` structure is flattened while preserving the complete history.

Current columns:

```text
product_id
effective_date
cost_mxn
supplier
```

Current row count:

```text
282
```

## Running the Current Pipeline

Install the current dependencies:

```bash
pip install -r requirements.txt
```

Place the three source files in:

```text
data/raw/
```

Run the pipeline from the repository root:

```bash
python -m src.pipeline
```

A successful execution generates:

```text
data/processed/cafenorte.duckdb
```

containing:

```text
dim_product
dim_store
fact_sales
fact_inventory
fact_product_cost
```

Current validated row counts:

```text
dim_product             70
dim_store               40
fact_sales          96,437
fact_inventory     230,776
fact_product_cost      282
```