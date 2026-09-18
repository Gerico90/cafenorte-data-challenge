# CaféNorte — Reto Técnico de Data Solutions Engineer

Pipeline de datos que consolida las ventas físicas (POS) y de e-commerce (Shopify) de CaféNorte, los datos de inventario/catálogo/costo del ERP y los tipos de cambio oficiales en un único modelo analítico, y responde cuatro preguntas de negocio sobre él.

## 1. Resumen del proyecto

El pipeline integra cuatro fuentes:

| Fuente | Archivo | Descripción |
|---|---|---|
| Ventas físicas POS | `sales.csv` | Transacciones de punto de venta en 40 tiendas |
| Inventario / catálogo / costo del ERP | `inventory.json` | ERP legado: catálogo de productos, `sku_mappings`, snapshots diarios de inventario, historial de costos de producto |
| Órdenes de e-commerce | `ecommerce_orders.parquet` | Órdenes de Shopify |
| Tipos de cambio | `exchange_rates.csv` | Tipos de cambio diarios, usados para normalizar a MXN los ingresos de e-commerce en otras monedas |

`exchange_rates.csv` no es una de las tres fuentes mencionadas en la narrativa original del reto, pero fue confirmado por el responsable del reto como material oficial del mismo. Esta solución lo usa para normalizar a MXN los ingresos de e-commerce en monedas distintas de MXN en Q3. Se trata aquí como una fuente de primer nivel, no como un archivo incidental o no oficial.

**Stack tecnológico**

- Python 3.11
- pandas 3.0.2
- DuckDB 1.5.5
- pyarrow 25.0.1
- pytest 9.1.1

Este es un stack local, de una sola máquina: los conjuntos de datos suministrados son de tamaño pequeño/mediano (la tabla más grande tiene ~230K filas), el resultado objetivo es un conjunto de cuatro consultas analíticas y no un servicio de streaming o de baja latencia, y DuckDB ofrece un motor analítico compatible con SQL dentro del mismo proceso sin requerir un entorno de ejecución distribuido. El procesamiento distribuido (Spark, data warehouses en la nube, etc.) añadiría una carga operativa desproporcionada para este volumen de datos y el alcance de este reto.

## Estructura del repositorio

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

## 2. Cómo ejecutar

Desde la raíz del repositorio, con los cuatro archivos raw colocados en `data/raw/`:

```bash
pip install -r requirements.txt
python scripts/run_pipeline.py
python -m pytest -q
```

`scripts/run_pipeline.py` reconstruye `data/processed/cafenorte.duckdb` de principio a fin a partir de las fuentes raw (load → reconcile → transform → persist). Esto se ha validado con una reconstrucción limpia desde las fuentes raw, y el resultado actual de la suite de pruebas completa es **41 passed**.

`data/processed/` también puede contener copias de respaldo `*.bak_*` con marca de tiempo del archivo DuckDB, creadas de forma incidental durante la iteración local. Estos respaldos no forman parte del flujo de trabajo requerido y no son producidos ni consumidos por `run_pipeline.py`, `business_questions.py` ni la suite de pruebas.

## 3. Flujo del pipeline

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

`build_analytical_model` produce seis tablas, persistidas tal cual en DuckDB:

| Tabla | Granularidad | Filas |
|---|---|---|
| `dim_product` | producto canónico (`product_id` = `sku_erp`) | 70 |
| `dim_store` | tienda física | 40 |
| `fact_sales` | una transacción, física o de e-commerce | 96,437 (86,490 physical + 9,947 e-commerce) |
| `fact_inventory` | tienda × producto × día | 230,776 |
| `fact_product_cost` | producto × fecha de vigencia del costo (historial completo, sin colapsar) | 282 |
| `fact_exchange_rate` | fecha del tipo de cambio × moneda (USD/EUR) | 730 |

`fact_sales` conserva `amount_native` + `currency` por transacción; la normalización a MXN de las filas de e-commerce en moneda distinta de MXN se aplica al momento de la consulta en Q3 mediante `fact_exchange_rate`, no durante la construcción del modelo.

## 4. Reconciliación de productos

`product_id` (`sku_erp`) es el identificador canónico de cada producto en el modelo analítico.

Prioridad de reconciliación, aplicada en `src/reconcile.py`:

1. **Mapeo explícito** desde `inventory.json → sku_mappings` (SKU de POS o handle de Shopify → `sku_erp`).
2. **Respaldo numérico**, aplicado únicamente cuando no existe un mapeo explícito para ese identificador *y* el componente numérico extraído de él se resuelve en exactamente un producto del ERP.
3. No se realiza ninguna coincidencia difusa por nombre (fuzzy name matching) en ninguna parte de la reconciliación.

El método de mapeo usado para cada producto observado se conserva en `dim_product` como `pos_mapping_method` / `shopify_mapping_method`, con los valores `explicit`, `inferred_numeric_pattern` o `not_observed`.

**Cobertura final**

- 70 / 70 SKUs físicos de POS reconciliados a un `sku_erp` canónico.
- 0 filas de ventas físicas sin reconciliar.
- Los 33 productos de Shopify observados en el mismo período se reconcilian a un SKU canónico. Esta cobertura de reconciliación es un hecho general del pipeline usado en Q3; no significa por sí misma que el e-commerce participe en el cálculo de rotación de Q1 — véase la sección 5.

## 5. Pregunta de negocio 1 — Rotación de inventario (Top 10 SKUs)

*Top 10 SKUs por rotación de inventario en los últimos 6 meses.*

- **Período:** del 2025-10-01 al 2026-03-31 (inclusive).
- **Alcance:** solo ventas físicas (POS). Q1 mide la rotación de inventario únicamente para combinaciones tienda-producto físicas donde tanto las ventas como el inventario son observables. Esta exclusión aplica solo a Q1; el e-commerce no se excluye del modelo analítico, permanece completamente reconciliado a nivel de SKU en `fact_sales`, se usa en Q3 y está disponible para cualquier otro análisis de ventas donde sea apropiado.
- **Fórmula:** `inventory_turnover = physical_units_sold_from_inventory_observable_store_product_pairs / average_inventory_units`
- **Inventario (denominador):** para cada par tienda-SKU con al menos un snapshot de inventario observable en el período, se promedian sus lecturas numéricas (el `0` numérico cuenta como observación; `N/A`/`NULL` se excluye, nunca se interpola ni se reemplaza por `0`). Los promedios tienda-SKU se suman a nivel de SKU.
- **Ventas físicas (numerador):** se incluyen únicamente para los pares tienda-SKU que tienen una serie de inventario observable en el período. No se imputa inventario a los pares con ventas pero sin serie de inventario; esas ventas siguen siendo válidas en otras partes de `fact_sales`, solo que quedan fuera de este cálculo específico.
- **E-commerce:** excluido del numerador y del denominador de Q1. Esta es una decisión de consistencia de población entre numerador y denominador, no un problema de calidad de datos: la fuente de e-commerce indica qué producto se vendió y cuántas unidades, pero no identifica la tienda, el almacén, la ubicación de cumplimiento ni el pool de inventario que surtió la orden, y los snapshots de inventario suministrados corresponden a inventario de tiendas físicas. Emparejar la demanda de e-commerce con el denominador de inventario de tiendas físicas no está respaldado por los datos suministrados. Esto **no** significa que falte el inventario de e-commerce; significa que los datos suministrados no identifican el pool de inventario que surtió las órdenes de e-commerce. Véase la divulgación más abajo para el volumen exacto excluido.
- **`tipo_comprobante`:** los cinco códigos observados (I, E, P, N, T) se cuentan exactamente como fueron registrados, sin filtrado y sin inversión de signo.

`sales.csv` incluye una columna `tipo_comprobante` con cinco códigos de letra: I, E, P, N, T. Solo como contexto externo, estas letras coinciden con el catálogo CFDI oficial del SAT de México (`c_TipoDeComprobante`: I = Ingreso, E = Egreso, T = Traslado, N = Nómina, P = Pago). Ese catálogo se menciona aquí únicamente como referencia: la fuente de CaféNorte nunca afirma que `tipo_comprobante` sea una exportación de CFDI, y carece de los campos fiscales (UUID, complemento de pago y similares) que serían necesarios para confirmar realmente un comportamiento CFDI. Asumir que aplica la semántica del SAT solo porque las letras coinciden no estaría respaldado por los datos.

En cambio, el campo se revisó directamente: se compararon entre los cinco códigos la cantidad, el monto, el monto por unidad, los patrones de hora del día/día de la semana/mes y la concentración por tienda/SKU, y se buscaron en los datos pares de filas que pudieran representar una reversión o un ajuste. Ningún código mostró un patrón que lo distinguiera de una venta ordinaria, las cantidades y montos son positivos en los cinco códigos y no se encontraron pares de reversión. Dado que los datos suministrados no ofrecen evidencia para tratar algún código de forma distinta, los cinco se cuentan tal como fueron registrados.

**Divulgación de cobertura (unidades físicas):** de 44,336 unidades físicas vendidas en total en el período de Q1, 20,318 pertenecen a combinaciones tienda-SKU con una serie de inventario observable y están incluidas en este cálculo; las 24,018 restantes (54.17%) pertenecen a combinaciones tienda-SKU que no tienen una serie de inventario observable y, por lo tanto, no pueden participar en este cálculo. Esto no es evidencia de inventario faltante, de una brecha de surtido, de un desabasto ni de un error de extracción; el significado de negocio de esa ausencia se desconoce a partir de los datos suministrados. Esas 24,018 unidades siguen siendo datos de ventas válidos en otras partes de `fact_sales`.

**Divulgación de cobertura (e-commerce):** se vendieron 6,627 unidades de e-commerce durante el mismo período. No se incluyen en este cálculo porque los datos suministrados no identifican el pool de inventario que surtió esas órdenes, no porque las ventas sean inválidas. Esas unidades también siguen siendo datos de ventas válidos, completamente reconciliados a nivel de SKU en `fact_sales`, y se usan en Q3 y en cualquier otro análisis de ventas apropiado.

**Sobre combinaciones sin serie de inventario observable:** las combinaciones tienda-producto sin ninguna serie de inventario se tratan como desconocidas, y no se fabrica ningún valor de stock para ellas. Esta entrega no adopta una regla de imputación porque los datos suministrados no ofrecen una base lo suficientemente defendible para una; por lo tanto, la ausencia descrita arriba se mantiene como desconocida en lugar de estimarse.

Este resultado es un ranking de rotación de inventario de tiendas físicas. No es una cifra de rotación a nivel de toda la compañía ni omnicanal.

**Resultado final:**

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

## 6. Pregunta de negocio 2 — Desabastos de más de 3 días (último trimestre)

*Tiendas con quiebres de stock de más de 3 días en el último trimestre.*

- **Período:** último trimestre calendario completo, del 2026-01-01 al 2026-03-31.
- **Observación de desabasto:** inventario numérico `== 0`.
- **Evento calificable:** más de 3 días calendario consecutivos de stock cero confirmado.
- **Manejo de `N/A`:** desconocido, e interrumpe una racha de stock cero en lugar de extenderla.
- Los eventos se detectan a nivel tienda-SKU y luego se reportan a nivel tienda.

**Resultado final:**

| Store | SKU | Start | End | Days |
|---|---|---|---|---:|
| T015 | ERP-PROV-MX-014-D | 2026-02-09 | 2026-02-12 | 4 |
| T023 | ERP-PROV-MX-046-A | 2026-01-25 | 2026-01-28 | 4 |
| T038 | ERP-PROV-MX-040-A | 2026-03-18 | 2026-03-21 | 4 |

## 7. Pregunta de negocio 3 — Crecimiento mensual (MoM) de ingresos por canal

*Crecimiento mes a mes (MoM) de ventas por canal (físico vs. e-commerce) en el último año.*

- **"Ventas"** se interpreta como ingresos.
- **Período de reporte:** 2025-04 a 2026-03 (12 meses).
- **Moneda:** el `monto` físico ya está en MXN; las filas de e-commerce en MXN no se modifican; las filas de e-commerce en USD/EUR se convierten con `amount_mxn = amount * rate_to_mxn`, donde el tipo de cambio se asocia por fecha de transacción + moneda. 0 filas USD/EUR quedaron sin asociar. `get_q3_channel_mom()` lo hace cumplir: si alguna transacción en moneda distinta de MXN dentro del rango del cálculo carece de un tipo de cambio para su fecha + moneda, o si una fecha + moneda de tipo de cambio está duplicada, lanza un `ValueError` en lugar de descartar silenciosamente ese ingreso.
- **MoM:** `(current_month − previous_month) / previous_month * 100`.
- **Primer mes (abril de 2025):** el MoM físico usa el ingreso físico de marzo de 2025 como base (marzo en sí no se muestra). El MoM de e-commerce de abril de 2025 es `N/A` porque el conjunto de datos de e-commerce suministrado no tiene ninguna observación anterior a abril de 2025; esto refleja únicamente el conjunto de datos suministrado, no una afirmación de que las ventas de Shopify hayan comenzado en abril de 2025.

**Resultado final:**

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

## 8. Pregunta de negocio 4 — Productos con margen negativo, por tienda

*Productos con margen negativo y en qué tiendas ocurren.*

- **Período:** historial completo de ventas físicas, del 2024-10-01 al 2026-03-31.
- **Supuesto metodológico:** `costo_mxn` se trata como el costo por unidad del producto. La fuente no establece explícitamente esta semántica de unidad.
- **Costo aplicable:** la fila más reciente de `cost_history` para el SKU donde `fecha_vigencia <= sale date`.
- **Por transacción:** `cost = cantidad * applicable costo_mxn`; `margin = monto - cost`.
- **Agregación:** tienda + SKU. Las filas calificables tienen `margin_mxn < 0`.
- **Cobertura:** 70/70 SKUs de POS reconciliados; 86,490/86,490 ventas físicas resueltas a un costo aplicable; sin fechas de vigencia de costo duplicadas; sin filas de costo sin resolver.
- **Nota de alcance:** el e-commerce no se incluye en este resultado porque el resultado solicitado requiere una dimensión de tienda que la fuente de e-commerce no contiene; no se infiere ninguna tienda ni ubicación de cumplimiento para él.

**Resumen del resultado final:** 120 combinaciones tienda-SKU negativas, en 40 tiendas, que involucran 3 SKUs — cada uno de los 3 con margen negativo en las 40 tiendas. `get_q4_negative_margin()` devuelve el detalle completo de 120 filas (tienda, SKU, ingresos, costo, margen, margen %); la tabla siguiente es la vista concisa a nivel de producto.

| SKU | Product | Stores with negative margin |
|---|---|---:|
| ERP-PROV-MX-001-A | Sándwich Comida Caliente | 40 / 40 |
| ERP-PROV-MX-002-B | Sándwich Comida Caliente | 40 / 40 |
| ERP-PROV-MX-015-D | Especial Cafe Molido | 40 / 40 |

## 9. Supuestos / Limitaciones

| # | Enunciado | Tipo |
|---|---|---|
| A1 | Las letras de `tipo_comprobante` (I/E/P/N/T) coinciden con el catálogo CFDI del SAT, pero los datos suministrados no prueban que este campo sea una exportación de CFDI y no muestran ninguna diferencia de comportamiento entre códigos; todos los valores se cuentan tal como fueron registrados en cada pregunta, sin filtrado ni inversión de signo. | Interpretación metodológica |
| A2 | `costo_mxn` se trata como el costo por unidad del producto (usado en Q4). | Interpretación metodológica |
| A3 | La rotación de inventario de Q1 está condicionada a la cobertura de inventario físico observable; el 54.17% de las unidades físicas (24,018 de 44,336) proviene de combinaciones tienda-SKU sin una serie de inventario observable y no puede participar en ese cálculo. | Limitación |
| A4 | Una combinación tienda-SKU ausente de `fact_inventory`, o un valor de snapshot `N/A`, significa "desconocido", no cero. No se aplica interpolación ni sustitución por cero en ninguna parte. | Hecho observado |
| A5 | La fuente de e-commerce no contiene dimensión de tienda física; no se infiere ninguna tienda ni ubicación de cumplimiento para las transacciones de e-commerce (afecta Q1 y Q4). Por ello, el e-commerce se excluye de Q1 (6,627 unidades en el período): los datos suministrados no respaldan emparejar esas ventas con el denominador de inventario de tiendas físicas. Esta exclusión aplica solo a Q1 — el e-commerce permanece en `fact_sales`, completamente reconciliado a nivel de SKU, y se usa en Q3 y en cualquier otro análisis de ventas apropiado. | Hecho observado / Interpretación metodológica |
| A6 | El conjunto de datos de e-commerce suministrado no tiene ninguna observación anterior al 2025-04-01; esto es una propiedad del conjunto de datos, no evidencia de cuándo el canal de Shopify comenzó realmente a operar. | Hecho observado / Limitación |
| A7 | Cuando los datos fuente limitan la cobertura analítica (alcance de Q1, Q4), esa ausencia no se asocia con un significado de negocio sin respaldo (p. ej., no se describe como un desabasto, una brecha de surtido o un error de extracción). | Limitación |

## 10. Pruebas / Reproducibilidad

```bash
python scripts/run_pipeline.py
python -m pytest -q
```

Se validó una reconstrucción limpia desde las fuentes raw de principio a fin:

- Los resultados de Q1, Q2, Q3 y Q4 se reprodujeron exactamente como se documentan arriba.
- Suite de pruebas completa: **41 passed**.
