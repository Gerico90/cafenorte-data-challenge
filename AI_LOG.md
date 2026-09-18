# AI_LOG

## Propósito

Este documento registra cómo se usaron herramientas de IA durante el desarrollo del reto técnico de Data Solutions Engineer para CaféNorte: qué se pidió, qué respondió la IA, qué decisión tomé con cada respuesta y por qué. La responsabilidad final sobre el pipeline, las definiciones de negocio y los resultados publicados en README.md es mía.

---

## 1. Herramientas utilizadas

- **Claude Code**, corriendo el modelo **Claude Sonnet 5**, en una sesión principal de orquestación que delegó tareas concretas a subagentes especializados. Los subagentes usados fueron:
  - **Workflow Architect** — ayudó a estructurar y revisar la metodología y la documentación del proyecto.
  - **Data Engineer** — validó las fuentes de datos crudas, la reconciliación de productos y aspectos de la implementación del pipeline.
  - **Supply Chain Strategist** — revisó si la interpretación de negocio de "rotación de inventario" usada en la pregunta 1 tenía sentido.
  - **Analytics Reporter** — fue el agente usado con más frecuencia para cuestionar de forma independiente conclusiones analíticas ya propuestas, antes de aceptarlas como definitivas.
  - **Software Architect** — preparó y redactó la propuesta de arquitectura de producción en AWS (`docs/aws_proposal.md`).
  - **Senior Project Manager** — revisó la cobertura final del reto y qué tan lista estaba la entrega del repositorio.
- **ChatGPT**, modelo **GPT-5.6 Sol**, usado como apoyo de razonamiento y planeación general del reto (organización de entregables y secuencia de trabajo).

---

## 2. Flujo de trabajo / orquestación

Actué en todo momento como responsable de las decisiones: ninguna conclusión de negocio se aceptó solo porque el código corriera o los tests pasaran. Para las decisiones ambiguas seguí un patrón simple: primero identificar el hecho observado directamente en los datos, separarlo de cualquier interpretación de negocio, tomar una decisión metodológica explícita sobre esa interpretación, implementarla, y finalmente validarla con pruebas y con una reconstrucción limpia del pipeline desde los archivos crudos.

Para las decisiones donde el significado de negocio no era obvio a partir de los datos (por ejemplo, qué hacer con los ceros en el inventario de la pregunta 1, si el e-commerce debía participar en esa misma pregunta, o qué significan los códigos de `tipo_comprobante`), no me quedé con la primera respuesta que recibí: pedí a un agente de perfil distinto que revisara la misma pregunta con instrucciones explícitas de cuestionar la conclusión en lugar de confirmarla. La decisión sobre el e-commerce en la pregunta 1 es el ejemplo más claro de esto: pasó por dos revisiones independientes con conclusiones opuestas, y la que finalmente se adoptó fue la segunda, después de que una distinción más precisa (identidad de producto vs. atribución de inventario) la sustentara mejor que la primera; ese es un caso de iteración metodológica, no de error de IA (ver sección 3, Prompt 5, y sección 4). El único caso donde un agente sí se equivocó de forma llana es un reporte de cobertura de reconciliación incorrecto relacionado con la pregunta 4; ese error lo detecté y lo rechacé yo, contrastando la recomendación con la evidencia y con lo que pedía la pregunta (ver sección 4).

En términos generales, cada agente cumplió un papel distinto dentro de ese flujo: Workflow Architect ayudó a ordenar la metodología y la documentación del proyecto; Data Engineer validó las fuentes de datos, la reconciliación de productos y partes de la implementación; Supply Chain Strategist revisó si la definición de rotación de inventario tenía sentido desde una perspectiva de negocio; Analytics Reporter fue quien más veces cuestionó conclusiones ya propuestas; Software Architect preparó la propuesta de arquitectura AWS; y Senior Project Manager hizo la revisión final de qué faltaba antes de considerar el reto listo para entregar.

No se documenta aquí cada revisión interna que se hizo durante el desarrollo; se incluyen a continuación los prompts y las decisiones más representativos.

Los prompts se citan textualmente, sin reescribirlos. Por eso algunos hacen referencia a decisiones previas del proyecto ("Accepted Q1 context") y a archivos de trabajo temporales bajo `docs/audits/`. Esos archivos fueron material interno de trabajo y no forman parte de la entrega; las conclusiones relevantes están resumidas en `README.md`. Los Prompts 2 y 3 ocurrieron antes de la decisión final de Q1, por lo que su contexto sobre e-commerce ("Ecommerce participates at SKU level") refleja esa etapa anterior; la versión final excluye el e-commerce de Q1 (ver Prompt 5).

---

## 3. Prompts clave

### Prompt 1 — Descubrimiento de las fuentes de datos (Data Engineer)

**Prompt:**
```
Use the Data Engineer agent for source-data discovery only.

Context:
This is a technical challenge for a Data Solutions Engineer role.
Do not implement the pipeline yet.
Do not transform or modify any source data.
Do not create project files yet.
Do not answer the business questions yet.
Do not choose a technology stack.
Do not design the production AWS architecture.

Analyze ONLY these three local source files:

- data/raw/sales.csv
- data/raw/inventory.json
- data/raw/ecommerce_orders.parquet

Do NOT analyze data/raw/exchange_rates.csv. Its role is currently being clarified with the recruiter.

For each source, report observed facts about:

1. Physical format
2. File size if available
3. Row or record count
4. Columns / schema and detected data types
5. Date fields and actual date coverage
6. Candidate primary identifiers
7. Candidate store identifiers
8. Candidate product / SKU identifiers
9. Null counts and null percentages
10. Duplicate records or duplicate candidate identifiers
11. Cardinality of important identifiers
12. Currency-related fields
13. Price, revenue, quantity and cost-related fields
14. Nested structures, if any
15. Fields that could potentially be used to reconcile this source with the other sources
16. Any observed data-quality issues

Then provide a cross-source section containing ONLY:

- identifiers that appear compatible across sources;
- identifiers that use different representations;
- reconciliation obstacles directly supported by the observed data;
- information that appears to be missing for reconciliation.

Important rules:

- Separate OBSERVED FACTS from INTERPRETATIONS.
- Do not infer undocumented business rules.
- Do not assume two fields correspond only because their names look similar.
- Do not propose Spark, Delta Lake, dbt, Medallion Architecture, Kafka, CDC, Great Expectations, AWS services, databases, or any other technology.
- Do not recommend fixes yet.
- Do not modify any files.
- If something cannot be determined from the data, explicitly say "Cannot be determined from the available source."
```

**Respuesta de la IA:** El agente entregó un reporte de descubrimiento puramente observacional de las tres fuentes (formato, tamaño, conteo de filas, esquema, cobertura de fechas, identificadores candidatos, nulos, duplicados, cardinalidad, campos monetarios y de moneda, estructuras anidadas) y una sección final de reconciliación cruzada, separando explícitamente hechos observados de interpretaciones y excluyendo `exchange_rates.csv` del alcance, tal como se pidió.

**Mi decisión:** Aceptado, sin cambios. Este reporte se convirtió en la base factual sobre la que se apoyaron todas las decisiones posteriores de reconciliación y de negocio.

---

### Prompt 2 — Tratamiento de ceros en inventario para Q1 (Analytics Reporter)

**Prompt:**
```
Use the Analytics Reporter subagent only.

Scope: resolve ONLY how numeric 0 values in
inventory.json.cantidad_en_stock should be treated for Q1.

Do NOT:
- choose a final N/A treatment
- calculate the final Q1 Top 10
- decide Shopify inclusion
- decide tipo_comprobante handling
- decide absent store-SKU meaning
- modify code
- modify README.md
- modify AI_LOG.md
- review Q2-Q4

Accepted Q1 context:
- Period: 2025-10-01 through 2026-03-31
- Formula: total_units_sold / average_inventory_units
- N/A means unknown and is excluded from averages
- Ecommerce participates at SKU level
- Physical sales without observable inventory remain excluded
- All tipo_comprobante codes are counted as recorded

Question:

When cantidad_en_stock is the NUMERIC value 0 in inventory.json,
should that observation participate in the Q1 inventory average as zero?

Important:
Do NOT decide whether zero means "stockout", "out of assortment",
"closed store", "data error", or any other business state unless the
supplied data proves it.

We only need to decide whether numeric 0 should be treated as an observed
inventory quantity of zero for the Q1 denominator.

Check directly:

1. Whether 0 is stored as a numeric value distinct from "N/A".
2. Whether the field itself is explicitly named/described as inventory quantity.
3. Whether zero values appear inside otherwise normal store-SKU time series.
4. Whether there is any evidence in the supplied source that numeric 0 is a
   missing-value sentinel or should be discarded.
5. What happens conceptually to the average if zeros are excluded.

Return ONLY:

Observed facts
Interpretation
Recommended Q1 treatment
Assumption introduced
Risk if wrong
Verdict: INCLUDE ZERO / EXCLUDE ZERO / UNRESOLVED

Maximum 40 lines.

Do not create an audit file.
Do not modify code or documentation.
```

**Respuesta de la IA:** El agente confirmó que 0 se almacena como un entero JSON, del mismo tipo que cualquier otro conteo de inventario, y que solo la cadena "N/A" actúa como valor centinela en la fuente; no encontró evidencia de que 0 deba tratarse como dato faltante. Concluyó INCLUDE ZERO, señalando como único supuesto que el sistema ERP registra 0 solo cuando efectivamente se realizó un conteo.

**Mi decisión:** Aceptado. Se implementó exactamente así en el cálculo de inventario promedio de Q1 y se validó después con una prueba unitaria dedicada.

---

### Prompt 3 — Validación de `tipo_comprobante` (Analytics Reporter)

**Prompt:**
```
Use the Analytics Reporter subagent only.

Scope: investigate ONLY the meaning and analytical treatment of
sales.csv.tipo_comprobante for CaféNorte Q1.

Do NOT:
- reopen the accepted Q1 period
- reopen the turnover formula
- reopen N/A treatment
- reopen inventory aggregation
- reopen the matched physical-sales decision
- reopen ecommerce inclusion
- calculate the final Top 10
- modify code
- modify README.md
- modify AI_LOG.md
- review Q2-Q4

Accepted Q1 context:
- Period: 2025-10-01 through 2026-03-31
- Turnover formula: total_units_sold / average_inventory_units
- Ecommerce participates at SKU level
- Physical sales without observable inventory remain excluded from Q1
- Inventory N/A means unknown and is excluded from averages

Question to resolve:

sales.csv contains tipo_comprobante with observed codes:
I, E, P, N, T

All rows currently have positive cantidad and positive monto.

We need to determine whether all document types should contribute equally to
the Q1 units-sold numerator, or whether any type may represent returns,
credits, cancellations, transfers, adjustments, or some other transaction
that should be treated differently.

IMPORTANT RULE:
Do NOT assign business meaning to a code based only on standard Mexican
accounting/fiscal conventions, naming intuition, or external knowledge.

Observed fact != interpretation != decision.

Use only the supplied challenge data as evidence unless clearly marked as
external domain context.

Authoritative source:
- data/raw/sales.csv
- data/raw/inventory.json only if needed for cross-checking product/store patterns

Investigate:

## 1. Source facts

Verify directly:
- distinct tipo_comprobante values
- row count by code
- total cantidad by code
- total monto by code
- number of stores by code
- number of SKUs by code
- date coverage by code

## 2. Behavioral patterns

For each code, compare:
- quantity distribution
- amount distribution
- amount per unit
- store distribution
- SKU distribution
- time-of-day / date pattern
- whether rows cluster around specific stores, products, dates, or unusually
  large/small quantities

Describe patterns only.
Do not infer semantics yet.

## 3. Transaction relationships

Look for evidence that certain rows could be reversals or adjustments.

Check whether rows of different tipo_comprobante appear to mirror each other by:
- same store
- same SKU
- close timestamps
- same or similar quantity
- same or similar amount

Do not require exact transaction IDs if none exist.

Quantify any pattern found.

## 4. Sign behavior

Confirm whether:
- cantidad is ever negative
- monto is ever negative
- zero values exist
- any code behaves differently from the others on sign

If every code is positive, state that this prevents direct identification of
returns/credits through sign alone.

## 5. Can semantics be established from the data?

For each code I / E / P / N / T classify exactly one:

SUPPORTED MEANING
PARTIAL EVIDENCE ONLY
UNKNOWN

A code can only be SUPPORTED MEANING if the supplied data itself provides
clear evidence of its role.

Do NOT use external fiscal conventions as proof.

## 6. Q1 treatment candidates

Evaluate:

A. Count all codes equally in units sold.

B. Exclude one or more codes.

C. Treat some codes with a sign adjustment.

D. Leave semantics unresolved and choose the least-assumptive treatment.

For each, state:
- what evidence supports it
- what unsupported assumption it would introduce
- risk if wrong

## 7. Quantitative materiality

For each code, report its percentage of:
- physical sales rows
- physical units
- physical monto

Also calculate the effect on Q1 physical units if each non-I code were:
- excluded
- sign-reversed

Do NOT calculate the final Top 10.
Only show aggregate sensitivity.

## 8. Independent verdict

Choose exactly one:

COUNT ALL CODES AS OBSERVED
FILTER SPECIFIC CODES
SIGN-ADJUST SPECIFIC CODES
UNRESOLVED

The verdict must be based on supplied-data evidence.

If the data does not establish semantics, do not invent them.

## 9. Decision record

Include:
Decision
Evidence
Interpretation
Assumptions
Risk if wrong
Status

Save to:

docs/audits/18_q1_tipo_comprobante_review.txt

Do not modify any other file.
```

*Nota: el archivo `docs/audits/18_q1_tipo_comprobante_review.txt` mencionado al final del prompt fue material de trabajo temporal; no forma parte de la entrega. Su conclusión está resumida en `README.md`, sección 5.*

**Respuesta de la IA:** El agente encontró que los cinco códigos (I, E, P, N, T) tienen montos y cantidades siempre positivos, distribuciones de monto, cantidad, tienda y SKU estadísticamente indistinguibles entre sí, y ningún patrón de pares que sugiriera reversas o ajustes. Concluyó que no hay evidencia en los datos suministrados para asignar un significado de negocio distinto a ningún código, y recomendó contarlos todos tal como fueron registrados (COUNT ALL CODES AS OBSERVED), dejando el significado real de los códigos como una ambigüedad abierta y explícita.

**Mi decisión:** Aceptado. Se mantiene el conteo de todos los códigos sin filtrar ni invertir signo, tanto en Q1 como posteriormente en Q3, donde se verificó que no había evidencia nueva que contradijera esta conclusión.

---

### Prompt 4 — Propuesta de arquitectura AWS (Software Architect)

**Prompt:**
```
Use the Software Architect subagent only.

Edit ONLY:
docs/aws_proposal.md

The architecture and all technical decisions are CLOSED.
Do not redesign or add services.

Problem:
The challenge requires the proposal to fit in approximately 2 pages.
The current proposal is too long.

Compress it aggressively while preserving:

1. Mermaid architecture diagram
2. Selected AWS services and why they are used
3. Monthly cost estimate and USD 200 limit
4. NAT Gateway conditional-cost note
5. Three implementation phases
6. Main risks + mitigation
7. Essential open questions

Reduce:
- repetitive explanations
- long trade-off prose
- redundant local-to-AWS descriptions
- open questions to the 5 most important
- risk table to the 5 most important risks

The final proposal should target approximately 900–1,100 words maximum.

Do NOT:
- change architecture
- change cost assumptions
- modify any other file
- add new analysis

Return:
Approximate word count before
Approximate word count after
Sections shortened
```

**Respuesta de la IA:** El agente redujo la propuesta de aproximadamente 1,985 palabras a una versión bastante más corta, conservando el diagrama Mermaid, los servicios de AWS con su justificación, la tabla de costos y el límite de USD 200, la nota sobre el costo condicional de NAT Gateway, las tres fases de implementación, y recortando la tabla de riesgos y la lista de preguntas abiertas a los cinco puntos más importantes de cada una.

**Mi decisión:** Aceptado como punto de partida, sin alterar la arquitectura ni los supuestos de costo. La propuesta se acortó de nuevo en la pasada final de limpieza (aprox. 1,000–1,100 palabras) para acercarse al máximo de 2 páginas del reto.

---

### Prompt 5 — ¿Debe el e-commerce participar en la rotación de Q1? (Analytics Reporter) — recomendación inicialmente rechazada, aceptada después de evidencia adicional

**Prompt:**
```
Use the Analytics Reporter subagent only.

Scope: resolve ONLY CaféNorte Q1 decision #5:

Should Shopify/e-commerce units participate in the inventory-turnover numerator?

Do NOT:
- calculate the final Top 10
- reopen the accepted period
- reopen the turnover formula
- reopen the N/A decision
- reopen inventory aggregation
- reopen the physical-sales matched-population decision
- decide tipo_comprobante
- modify code
- modify README.md
- modify AI_LOG.md
- review Q2-Q4

Accepted Q1 decisions:

1. Period:
   2025-10-01 through 2026-03-31.

2. Formula:
   inventory_turnover = total_units_sold / average_inventory_units

3. Inventory denominator:
   for each product, calculate the average inventory for each store-product
   combination with an observable inventory series, then sum those store-level
   averages.

4. Physical sales scope:
   include physical sales ONLY for store-product combinations that also have an
   observable inventory series.

5. N/A:
   unknown inventory; exclude from average, do not zero-fill or interpolate.

Current question:

ecommerce_orders.parquet contains product quantities that can be reconciled to
CaféNorte products.

However, ecommerce orders do NOT have a physical store_id or another confirmed
field identifying which inventory pool fulfilled the order.

The physical inventory source is inventory.json, whose snapshots are identified
by tienda_id + sku_erp.

We therefore need to determine whether Shopify quantities can defensibly be added
to the Q1 turnover numerator.

Authoritative sources:
- data/raw/ecommerce_orders.parquet
- data/raw/inventory.json
- data/raw/sales.csv
- docs/audits/16_q1_sales_inventory_scope_final_decision.txt

Review the following.

## 1. Exact evidence in ecommerce source

Verify directly:
- row count and accepted-period row count
- available product identifier(s)
- quantity field
- whether store_id exists
- whether fulfillment location / warehouse / inventory-location fields exist
- whether shipping_city or shipping_address exists
- whether those fields identify customer destination rather than fulfillment origin
- any other field that could legitimately connect an online order to an inventory pool

Do not infer fulfillment from shipping destination.

## 2. Product reconciliation

Verify whether observed Shopify products can be reconciled to sku_erp.

Separate:

"we know WHICH PRODUCT was sold"

from:

"we know WHICH INVENTORY supplied that sale"

These are not the same question.

## 3. Inventory compatibility

Assess whether there is an observable denominator corresponding to ecommerce sales.

Check specifically whether the supplied data contains:
- a dedicated ecommerce warehouse/inventory pool
- Shopify inventory snapshots
- warehouse identifiers
- fulfillment-location identifiers
- or a documented rule allocating ecommerce sales to physical stores

If none exists, say so.

## 4. Candidate interpretations

Evaluate at least:

A. Include Shopify units in numerator together with matched physical sales.

B. Exclude Shopify units from Q1 because there is no observable inventory pool
   that can be tied to those sales.

If there is a genuinely data-supported third alternative, describe it.

Do NOT propose assigning Shopify orders to stores by shipping city/address unless
the source proves that customer destination equals fulfillment origin.

Do NOT invent an ecommerce inventory pool.

## 5. Quantitative materiality

For the accepted Q1 period, quantify:

- physical units included under accepted matched-population rule
- ecommerce units
- ecommerce units as a percentage of:
    a) matched physical units
    b) total physical units
    c) matched physical + ecommerce units

Also quantify:
- number of Shopify products sold in the period
- how many reconcile to sku_erp
- whether Shopify participation is concentrated in a small number of products or
  distributed broadly

This is descriptive only.

Do NOT calculate the final Top 10.

## 6. Metric consistency

For each candidate, explain in plain language:

If Shopify is INCLUDED:
what inventory is the ecommerce numerator being divided by?

If Shopify is EXCLUDED:
what business activity is omitted from the Q1 turnover metric?

Separate:
- completeness
from
- numerator/denominator consistency.

## 7. Independent verdict

Choose exactly one:

INCLUDE SHOPIFY
EXCLUDE SHOPIFY
UNRESOLVED

Base the verdict only on what the supplied data supports.

The verdict is about Q1 inventory turnover only.
It does NOT imply ecommerce sales should be removed from the analytical model or
from sales-related questions.

If EXCLUDE:
make clear that Shopify sales remain valid and should still be used in Q3 and any
other appropriate sales analysis.

If INCLUDE:
identify exactly which observable inventory denominator supports those units.

If UNRESOLVED:
state exactly what missing evidence prevents a choice.

Use exactly these sections:

## 1. Question
## 2. Ecommerce source evidence
## 3. Product reconciliation vs inventory attribution
## 4. Available inventory pools
## 5. Quantitative materiality
## 6. Candidate interpretations
## 7. Metric consistency
## 8. Independent verdict
## 9. Decision record

Save to:

docs/audits/17_q1_shopify_inclusion_review.txt

Do not modify any other file.
```

*Nota: los archivos `docs/audits/16_…` y `docs/audits/17_…` mencionados en el prompt fueron material de trabajo temporal; no forman parte de la entrega.*

**Respuesta de la IA:** El agente verificó que las órdenes de e-commerce no traen `store_id` ni ningún campo de bodega o ubicación de despacho, que `shipping_city` y `shipping_address` describen el destino del cliente y no el origen del despacho, y que los 33 productos de Shopify sí concilian con `sku_erp`. Concluyó **EXCLUDE SHOPIFY** para la rotación de Q1: sumar unidades de e-commerce al numerador lo emparejaría con un denominador (inventario de tiendas físicas) sin relación demostrada.

**Mi decisión (en el momento):** Rechazado. El agente tenía razón en los hechos (no existe atribución de despacho para el e-commerce), pero en ese momento consideré que la conclusión iba más allá de lo que los datos exigían: la pregunta pide un ranking por producto, la identidad del producto de e-commerce sí está completamente conciliada contra `sku_erp`, y me pareció que la sola ausencia de una columna de tienda no bastaba para excluir un canal de un cálculo a nivel de SKU. Con ese razonamiento, mi siguiente prompt estableció como contexto aceptado que "Ecommerce participates at SKU level", y el prompt de implementación al Data Engineer exigió explícitamente no asignarle tienda, no inferir un centro de despacho y no excluirlo por falta de `store_id`. Esta fue la versión implementada inicialmente.

**Revisión posterior y decisión final:** Al cerrar la definición final de Q1, una revisión adicional mostró que mi rechazo inicial confundía dos preguntas distintas: "¿sabemos qué producto se vendió?" (identidad de producto, resuelta por la reconciliación a `sku_erp`) y "¿sabemos qué inventario surtió esa venta?" (atribución de inventario, que la fuente de e-commerce nunca resuelve). Que los 33 productos de Shopify reconcilien contra el catálogo prueba lo primero, pero no dice nada sobre lo segundo. La rotación de inventario es una razón numerador/denominador: su denominador son los inventarios de tienda física observados en `inventory.json`, y sin una atribución demostrada de qué inventario surtió cada orden de e-commerce, sumar esas unidades al numerador arma una razón entre poblaciones que no corresponden entre sí. Con esa distinción ya explícita, revisé mi decisión original: el veredicto `EXCLUDE SHOPIFY` del agente pasó de rechazado a aceptado para la pregunta 1, exclusivamente. Esto es una iteración metodológica sobre una decisión propia, no una corrección de un error de la IA — el agente había señalado el hecho correcto (ausencia de atribución de despacho) desde el principio; lo que cambió fue mi propio criterio sobre si ese hecho bastaba para excluir el canal. La versión final implementada excluye el e-commerce del numerador y del denominador de Q1 (ver README.md, sección 5); el e-commerce se mantiene en `fact_sales`, completamente reconciliado a nivel de SKU, y se sigue usando en la pregunta 3 y en cualquier otro análisis de ventas donde sea pertinente.

---

## 4. Casos de error de IA

### Caso considerado y descartado como error de IA — inclusión de e-commerce en la rotación de la pregunta 1

La recomendación del agente **Analytics Reporter** en el Prompt 5 (`EXCLUDE SHOPIFY`) fue, en su momento, rechazada por mí (ver arriba). Esa decisión se revisó más tarde y el veredicto del agente terminó siendo el adoptado en la versión final del proyecto. Por eso este caso **no** se documenta aquí como un error de la IA: el agente tenía razón desde el principio en el hecho relevante (no hay atribución de inventario para el e-commerce); lo que hubo fue una revisión metodológica propia, hecha por mí, al detectar que mi rechazo inicial no distinguía entre identidad de producto y atribución de inventario. La responsabilidad de la decisión final, tanto la inicial como la revisada, fue siempre mía.

### Caso principal — un reporte de cobertura de productos incompleto (pregunta 4)

Más adelante, al revisar la pregunta 4 (márgenes negativos), pedí a un agente que confirmara cuántos de los 70 productos de punto de venta se podían relacionar con el catálogo del ERP. El agente reportó que 10 de los 70 no se podían relacionar. Ese reporte era incorrecto: el agente solo había revisado las relaciones explícitas ya registradas en el ERP y no aplicó la segunda regla de reconciliación, ya validada anteriormente, que usa el número contenido en el código de producto para completar la relación cuando no existe una entrada explícita.

Al aplicar exactamente la misma lógica de reconciliación que usa el pipeline (primero buscar una relación explícita y, si no existe, usar el número del código de producto), los 70 productos sí se relacionan con el catálogo, sin excepción. Esa corrección también sacó a la luz un tercer producto con margen negativo que el reporte incorrecto había dejado fuera, precisamente porque ese producto dependía de la relación numérica que el agente había pasado por alto. El resultado que aparece en el README (sección 8: 70 productos reconciliados, 3 con margen negativo) ya refleja esta corrección.

---

## 5. Autocrítica final

**Lo que considero 100% mío es la decisión metodológica final:** decidir qué supuestos aceptar, qué recomendaciones de la IA aceptar o rechazar, y hacerme responsable del resultado entregado. No afirmo haber escrito todo el código a mano: la IA aportó de forma real y medible en el perfilado de las cuatro fuentes, la generación de interpretaciones alternativas para las decisiones ambiguas, la implementación del pipeline y de las pruebas, y la revisión independiente de resultados, trabajo que a mano habría tomado mucho más tiempo. La responsabilidad metodológica final se quedó siempre conmigo: en la decisión sobre si el e-commerce debía participar en la rotación de la pregunta 1, rechacé inicialmente la recomendación del agente de excluirlo, y más tarde revisé esa decisión propia cuando una evidencia adicional expuso un argumento de consistencia numerador/denominador más sólido, no porque la IA se hubiera equivocado, sino porque mi primer criterio no distinguía entre identidad de producto y atribución de inventario. Validé el trabajo entregado de varias formas, no solo con que corriera sin errores: una reconstrucción completa de la base de datos desde los archivos crudos reproduce exactamente los resultados publicados en el README; la suite de 41 pruebas pasa sobre esa reconstrucción; las decisiones más ambiguas (ceros de inventario, `tipo_comprobante`, e-commerce en la pregunta 1) se sometieron a una segunda revisión independiente antes de aceptarse; y una revisión externa, sin contexto previo del proyecto, recalculó Q1–Q4 y confirmó que coincidían con el README de ese momento, lo que llevó a agregar una validación de integridad de tipos de cambio en Q3 y a precisar limitaciones documentadas. Esa revisión ocurrió antes del cambio final de Q1 a un cálculo solo de tiendas físicas, así que no valida el resultado final de Q1; ese resultado se verificó después con las pruebas actualizadas (41) y comparándolo contra la tabla del README. La IA sí se equivocó en un caso concreto que detecté yo antes de publicar: reportó que 10 de 70 productos no se podían reconciliar con el catálogo porque revisó solo una parte de la regla de reconciliación ya validada.
