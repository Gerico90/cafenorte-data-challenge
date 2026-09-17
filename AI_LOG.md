
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

None documented yet.

---

## Final Self-Critique

To be completed at the end of the challenge.