# CaféNorte — Data Solutions Engineer Technical Challenge

Technical challenge focused on building a data pipeline that integrates and reconciles CaféNorte's POS, inventory, and e-commerce data.

## Status

Work in progress.

## Challenge deliverables

- Functional data pipeline
- Analytical model
- Answers to the four business questions
- Minimum reliability tests
- Technical AWS proposal
- AI usage log

## Repository structure

```text
data/raw/   Original source files used locally
src/        Pipeline source code
tests/      Automated tests
docs/       Technical proposal and supporting documentation

## Data Reconciliation Decisions

### Product identifiers

The three source systems use different identifiers for the same products:

- POS: `sku` values such as `CN-00030`
- ERP: `sku_erp` values such as `ERP-PROV-MX-030-C`
- Shopify: `product_handle` values such as `molinillo-mercancia-030`

The ERP SKU (`sku_erp`) is used as the canonical product identifier in the analytical model.

The ERP source includes an explicit `sku_mappings` structure that links these identifiers, but the mapping is incomplete. Before inferring any missing relationships, the identifier pattern was validated against the provided datasets.

Validation results:

- 60/60 known POS → ERP mappings share the same numeric product component.
- 27/27 known POS → Shopify mappings share the same numeric product component.
- 23/23 mappings containing POS, ERP, and Shopify identifiers are consistent across all three systems.
- The ERP catalog contains 70 products with 70 unique numeric product components.
- No numeric identifier collisions were found in POS, ERP, or Shopify.
- No explicit mapping contradicts the numeric pattern.

Based on these validations, reconciliation follows this rule:

1. Use the explicit mapping from `inventory.json` whenever it exists.
2. If the explicit mapping is missing, extract the numeric product component from the source identifier.
3. Match it to the ERP catalog only when exactly one ERP product has that numeric component.
4. Do not use fuzzy name matching to infer product identity.
5. Preserve how each relationship was obtained (`explicit` or `inferred_numeric_pattern`) so inferred relationships remain distinguishable from source-provided mappings.

This inference rule is considered valid only for the datasets provided with this challenge; it is not assumed to be a permanent source-system contract.