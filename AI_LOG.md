
Ese último punto es importante: **no fingimos que ya elegimos tecnología**.

---

## 5. Crear `AI_LOG.md`

Aquí sí debemos empezar desde hoy.

Pon:

```markdown
# AI_LOG

## Purpose

This document records how AI tools were used during the development of the CaféNorte Data Solutions Engineer technical challenge, including prompts, outputs, decisions, corrections, and validation performed by me.

---

## Tools Used

### ChatGPT
- Model: GPT-5.6 Sol
- Usage: planning, requirements analysis, technical discussion and review.

Additional tools will be documented when they are actually used.

---

## Workflow

The project started with a requirements review before inspecting or transforming the source datasets.

The initial decision was to separate:

- project planning and technical review;
- local implementation and execution;
- AI-assisted development;
- human validation of outputs.

No data transformation or technology stack was selected before inspecting the available sources.

---

## Key Prompts

### Prompt 1 — Project planning

**Prompt**

I asked ChatGPT to read only the technical challenge document, without analyzing the datasets, and create a plan strictly based on the requirements in the document.

**AI response summary**

ChatGPT separated the challenge into:
- functional pipeline;
- technical AWS proposal;
- AI usage log;
- interview/demo preparation.

It also proposed using the local Git repository as the development environment and keeping AI usage documented throughout the project.

**Decision**

Modified / accepted.

**Reason**

The proposed workflow matches the required deliverables, while implementation decisions were intentionally postponed until the source datasets are inspected.

### Prompt 2 — Source discovery

**Prompt**

I asked the Claude Code Data Engineer agent to profile only the three challenge sources (`sales.csv`, `inventory.json`, and `ecommerce_orders.parquet`) without modifying data, selecting a technology stack, designing the pipeline, or proposing cloud infrastructure.

The agent was explicitly instructed to separate observed facts from interpretations and report schemas, counts, date coverage, identifiers, nulls, duplicates, currencies, potential reconciliation fields, and observed data-quality issues.

**AI response summary**

The agent identified:

- 86,490 physical sales rows.
- 9,947 e-commerce order rows.
- 230,776 inventory snapshots.
- 40 stores shared between POS and ERP.
- Different product identifiers across systems (`sku`, `sku_erp`, and `product_handle`).
- An incomplete SKU mapping bridge.
- 4,417 inventory records with `"N/A"` instead of numeric stock.
- Multiple currencies in e-commerce.
- No physical store identifier in e-commerce.
- Partial date coverage across sources.

**Decision**

Accepted after independent validation of the critical findings.

**Validation**

I created and executed a local Python validation script against the original source files. It independently confirmed the critical row counts, date ranges, identifier cardinalities, mapping coverage, missing mappings, inventory `"N/A"` count, currencies, duplicate-key checks, store overlap, and cross-source date overlap.

No discrepancy was found in the critical facts used for subsequent design decisions.

### Prompt 3 — Independent cold review

**Prompt**

I asked a Claude Code Code Reviewer agent to perform a cold audit of the repository using only the challenge materials, source data, and repository contents.

The reviewer was asked to identify reasoning gaps, hidden assumptions, reproducibility problems, incorrect data-model decisions, and implementation risks without modifying the project.

**AI response summary**

The review identified a discrepancy in the product reconciliation logic.

The documented strategy was:

1. Use explicit mappings from `sku_mappings` first.
2. Use the validated numeric pattern only as a fallback.

However, the implementation was deriving product relationships from the numeric pattern first and using `sku_mappings` only to label whether the resulting relationship was explicit or inferred.

The reviewer also identified reproducibility issues such as uncommitted pipeline files and missing dependency documentation.

**Decision**

Accepted and corrected the reconciliation finding.

`src/reconcile.py` was changed so that explicit mappings are now actually used first. Numeric-pattern inference is only used when an explicit ERP relationship is unavailable.

The pipeline was executed again after the correction.

**Validation**

The corrected implementation produced the same results on the supplied dataset:

- 70 canonical products
- 60 explicit POS mappings
- 10 inferred POS mappings
- 23 explicit Shopify mappings
- 10 inferred Shopify mappings
- 0 unreconciled POS sales rows
- 0 unreconciled Shopify rows

This confirmed that the previous implementation happened to produce the correct result for the supplied data, but did not correctly implement the intended reconciliation hierarchy.

**Why this mattered**

The independent review detected a reasoning and implementation gap that was not visible from the final row counts alone. The correction made the code consistent with the documented reconciliation decision rather than relying on an accidental property of the current dataset.

---

## Validation and Decision Notes

### Product identifier reconciliation

During review of the source-discovery results, ChatGPT suggested investigating whether the numeric component embedded in the POS, ERP, and Shopify product identifiers could be used to reconcile records missing from the explicit `sku_mappings` table.

I did not accept this relationship based only on the identifiers looking similar.

Two additional local validation steps were performed against the original datasets:

1. **Known-mapping validation**
   - 60/60 known POS → ERP mappings had matching numeric components.
   - 27/27 known POS → Shopify mappings had matching numeric components.
   - 23/23 rows containing all three identifiers were consistent.
   - All currently unmapped POS SKUs and Shopify handles resolved to exactly one ERP product candidate.

2. **Collision/conflict validation**
   - All POS, ERP, and Shopify product identifiers were parseable using the observed identifier formats.
   - No numeric identifier collisions were found within any of the three systems.
   - No explicit mapping in the source data contradicted the numeric relationship.

**Decision**

Use the explicit source mapping first. Where it is missing, allow a numeric-component fallback only when it resolves to exactly one ERP product and does not conflict with an explicit mapping.

The ERP SKU is used as the canonical product identifier.

Fuzzy matching based on product names was deliberately rejected because the deterministic identifier relationship was supported by the provided data and is easier to validate and audit.

**Human validation**

The rule was accepted only after running the validation locally against the original source files. The inference is scoped to the datasets provided for the challenge and is not assumed to be a permanent upstream business rule.


---

## AI Errors / Suboptimal Suggestions

### AI error — Shopify reconciliation merge

ChatGPT initially suggested merging Shopify orders against the complete product bridge using `validate="many_to_one"`.

The implementation failed because the canonical bridge contains all 70 ERP products, while only 33 are observed in Shopify. Products without a Shopify identifier therefore produced multiple `NaN` values in the merge key, which pandas correctly rejected as non-unique.

**Detection**

The error was detected by executing the reconciliation code locally. Pandas raised a `MergeError` indicating that the right-side merge key was not unique.

**Correction**

The Shopify reconciliation step was changed to filter the product bridge to rows with a non-null `product_handle` before performing the `many_to_one` merge.

The validation constraint was kept rather than removed, because it provides protection against genuinely ambiguous Shopify mappings.

**Result**

After the correction:

- 70 canonical ERP products were preserved in the bridge.
- 33 Shopify product handles were reconciled.
- 0 Shopify order rows remained unreconciled.
- 0 POS sales rows remained unreconciled.

---

## Final Self-Critique

To be completed at the end of the challenge.