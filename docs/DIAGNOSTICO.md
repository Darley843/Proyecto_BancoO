# Diagnóstico financiero guiado

Guion de la entrevista, ids canónicos y reglas de cálculo del diagnóstico del
Corresponsal WhatsApp de la Sucursal 1965 (cambio OpenSpec
`corresponsal-whatsapp`, sección 3). Responsable: Nayla.

Este documento es el contrato con el canal (botones y listas) y con el
simulador de personas sintéticas: los ids de aquí son los únicos válidos.

## Principios

- **Orientativo, no es aprobación.** El resultado nunca dice "aprobado" ni
  "negado"; el texto de aviso va en toda respuesta final.
- **Rangos, no cifras exactas.** No se piden ingresos ni deudas exactas, ni
  cédula, ni número de cuenta.
- **Cálculo determinístico en Python.** El LLM no calcula: solo redacta a
  partir de `ResultadoDiagnostico`.
- **Tasas del Tablero vigente** (`data/gold/tasas/`), solo filas con
  `tipo_tasa = "fija"`, citando vigencia y fuente.
- **Prudencia:** el semáforo se calcula con la **tasa máxima** del rango
  publicado; la cuota se muestra como rango (tasa mínima a tasa máxima).

## Flujo de la entrevista

| Paso | Pregunta al cliente | Tipo | Ids posibles |
|---|---|---|---|
| 1 | ¿Qué te gustaría revisar? | Lista | `objetivo.*` |
| 2 | ¿Cómo recibes tus ingresos? | Botones | `vinculacion.*` |
| 3 | ¿En qué rango están tus ingresos mensuales? | Lista | `ingresos.*` |
| 4 | ¿Cuánto gastas al mes en gastos fijos (arriendo, servicios, mercado, transporte)? | Lista | `gastos.*` |
| 5 | ¿Cuánto pagas hoy en cuotas de créditos o tarjetas? | Lista | `cuotas.*` |
| 6 | ¿Cuánto dinero necesitas? | Lista según objetivo | `monto.*` |
| 7 | ¿En cuánto tiempo quieres pagarlo? | Lista según objetivo | `plazo.*` |
| 6b | Solo compra de cartera: ¿cuánto pagas hoy de cuota por las deudas que quieres trasladar? | Lista | `cuota_trasladar.*` |

Para `objetivo.ahorro` se omiten los pasos 6, 7 y 6b.

## Ids canónicos

### objetivo

| Id | Texto | Producto en la tabla de tasas |
|---|---|---|
| `objetivo.libre_inversion` | Préstamo de libre inversión | `libre_inversion` |
| `objetivo.compra_cartera` | Pasar mis deudas a una mejor tasa | `compra_cartera` |
| `objetivo.vehiculo_nuevo` | Comprar vehículo nuevo | `vehiculo_nuevo` |
| `objetivo.vehiculo_usado` | Comprar vehículo usado | `vehiculo_usado` |
| `objetivo.vivienda` | Comprar vivienda | `vivienda` (segmento crédito hipotecario) |
| `objetivo.libranza` | Crédito por libranza | `libranza` (segmento libre inversión) |
| `objetivo.ahorro` | Solo quiero ahorrar | `ahorro` y `cdt` |

La tarjeta de crédito queda fuera del diagnóstico: es un cupo rotativo sin
cuota fija que simular.

### vinculacion

`vinculacion.empleado`, `vinculacion.independiente`, `vinculacion.pensionado`.

### ingresos (mensuales)

| Id | Rango | Valor de cálculo |
|---|---|---|
| `ingresos.MENOS_2M` | Menos de $2 millones | $1.500.000 |
| `ingresos.DE_2M_A_3M` | $2 a $3 millones | $2.500.000 |
| `ingresos.DE_3M_A_5M` | $3 a $5 millones | $4.000.000 |
| `ingresos.DE_5M_A_8M` | $5 a $8 millones | $6.500.000 |
| `ingresos.DE_8M_A_12M` | $8 a $12 millones | $10.000.000 |
| `ingresos.MAS_12M` | Más de $12 millones | $14.000.000 |

### gastos (fijos mensuales)

| Id | Rango | Valor de cálculo |
|---|---|---|
| `gastos.MENOS_1M` | Menos de $1 millón | $750.000 |
| `gastos.DE_1M_A_2M` | $1 a $2 millones | $1.500.000 |
| `gastos.DE_2M_A_3M` | $2 a $3 millones | $2.500.000 |
| `gastos.DE_3M_A_5M` | $3 a $5 millones | $4.000.000 |
| `gastos.MAS_5M` | Más de $5 millones | $6.000.000 |

### cuotas (créditos y tarjetas actuales)

| Id | Rango | Valor de cálculo |
|---|---|---|
| `cuotas.NINGUNA` | No tengo cuotas | $0 |
| `cuotas.MENOS_500K` | Menos de $500 mil | $300.000 |
| `cuotas.DE_500K_A_1M` | $500 mil a $1 millón | $750.000 |
| `cuotas.DE_1M_A_2M` | $1 a $2 millones | $1.500.000 |
| `cuotas.DE_2M_A_3M` | $2 a $3 millones | $2.500.000 |
| `cuotas.MAS_3M` | Más de $3 millones | $3.500.000 |

`cuota_trasladar.*` usa los mismos rangos que `cuotas.*` (sin `NINGUNA`) y no
puede ser mayor que la respuesta del paso 5.

### monto (según objetivo)

| Objetivo | Ids | Valor de cálculo |
|---|---|---|
| Libre inversión, compra de cartera, libranza | `monto.HASTA_5M`, `monto.DE_5M_A_10M`, `monto.DE_10M_A_20M`, `monto.DE_20M_A_50M`, `monto.MAS_50M` | 4M, 7,5M, 15M, 35M, 60M |
| Vehículo | `monto.DE_30M_A_60M`, `monto.DE_60M_A_100M`, `monto.MAS_100M` | 45M, 80M, 120M |
| Vivienda | `monto.DE_100M_A_200M`, `monto.DE_200M_A_350M`, `monto.MAS_350M` | 150M, 275M, 400M |

### plazo (meses)

| Objetivo | Ids |
|---|---|
| Libre inversión, compra de cartera, libranza, vehículo | `plazo.12`, `plazo.24`, `plazo.36`, `plazo.48`, `plazo.60`, `plazo.72` |
| Vivienda | `plazo.120`, `plazo.180`, `plazo.240` |

## Cálculo

Con los valores de cálculo de cada rango, con precisión decimal de 28 dígitos:

- Tasa mensual: `i = (1 + EA) ^ (1/12) − 1`, sin redondear.
- Cuota (amortización francesa): `cuota = monto × i / (1 − (1 + i) ^ (−n))`;
  con `i = 0`, `cuota = monto / n`. Solo la cuota final se redondea al peso.
- **Capacidad de pago**: `capacidad = ingresos − gastos − cuotas actuales`,
  antes de la cuota nueva. En compra de cartera las cuotas trasladadas
  desaparecen: `capacidad = ingresos − gastos − (cuotas − cuota_trasladar)`.
- **Margen después de la cuota**: `margen = capacidad − cuota_nueva`.
- Razón de endeudamiento: `RE = (cuotas + cuota_nueva) / ingresos`
  (en compra de cartera: `(cuotas − cuota_trasladar + cuota_nueva) / ingresos`)
- Cuota mostrada: rango entre la cuota con la tasa mínima y con la tasa máxima.
- Semáforo y RE: siempre con la **tasa máxima**.

## Semáforo

| Color | Regla |
|---|---|
| Rojo | `margen < 0`, o `RE > 40 %` |
| Amarillo | `margen ≥ 0` y `30 % < RE ≤ 40 %` |
| Verde | `margen ≥ 0` y `RE ≤ 30 %` |

Umbrales configurables en `config/diagnostico.toml` (por defecto 0,30 y 0,40).

Reglas adicionales:

- **Vivienda:** además, la primera cuota no debe superar el 30 % de los
  ingresos; si lo supera, el resultado es rojo. (Verificar la norma vigente
  antes de la sustentación.)
- **Libranza:** solo para `empleado` o `pensionado`. Si es `independiente`, se
  explica que la libranza requiere convenio con el empleador o pagador y se
  ofrece simular libre inversión.
- **Compra de cartera:** la capacidad comparable descuenta las cuotas que se
  trasladan y el margen se calcula con la cuota nueva. Además se informa el
  ahorro mensual estimado `cuota_trasladar − cuota_nueva`; si es negativo, se
  dice que el traslado no reduce la cuota con ese plazo.
- **Ahorro:** no hay semáforo de crédito. Se informa la capacidad de ahorro
  mensual (`capacidad`) y las tasas vigentes de ahorro y CDT del Tablero.
- **Capacidad negativa** (gastos + cuotas actuales > ingresos): rojo sin
  simular crédito, con recomendación de ordenar gastos y deudas primero.

## Recomendaciones por color

- **Verde:** la cuota cabe con margen. Sugerir comparar plazos (el más corto
  paga menos intereses) y revisar requisitos del producto en la Bóveda.
- **Amarillo:** la cuota cabe pero con poco margen. Sugerir un plazo más largo
  o un monto menor, y simular de nuevo ("¿y si…?").
- **Rojo:** con estos datos la cuota compromete demasiado el ingreso. Sugerir
  monto menor o plazo mayor, compra de cartera si hay deudas caras, y ofrecer
  hablar con un asesor (HITL).

## Texto de aviso (obligatorio)

> Este resultado es orientativo y se basa en rangos aproximados y en las tasas
> publicadas por el Banco de Occidente para [vigencia]. No es una aprobación ni
> una oferta de crédito; la tasa final depende del monto, el plazo y tu perfil.
> Proyecto académico de la UAO, no es un canal oficial del banco.

## Personas sintéticas sugeridas para pruebas

| Persona | Respuestas | Resultado esperado |
|---|---|---|
| Empleada en verde | `objetivo.libre_inversion`, `vinculacion.empleado`, `ingresos.DE_5M_A_8M`, `gastos.DE_2M_A_3M`, `cuotas.NINGUNA`, `monto.DE_10M_A_20M`, `plazo.48` | Verde |
| Independiente en rojo | `objetivo.libre_inversion`, `vinculacion.independiente`, `ingresos.DE_2M_A_3M`, `gastos.DE_1M_A_2M`, `cuotas.DE_500K_A_1M`, `monto.DE_20M_A_50M`, `plazo.36` | Rojo → oferta de asesor |
| Pensionado en amarillo | `objetivo.libranza`, `vinculacion.pensionado`, `ingresos.DE_3M_A_5M`, `gastos.DE_1M_A_2M`, `cuotas.DE_500K_A_1M`, `monto.DE_10M_A_20M`, `plazo.60` | Amarillo |
| Joven que quiere ahorrar | `objetivo.ahorro`, `vinculacion.empleado`, `ingresos.MENOS_2M`, `gastos.DE_1M_A_2M`, `cuotas.NINGUNA` | Capacidad de ahorro + tasas de ahorro y CDT |
| Compra de cartera | `objetivo.compra_cartera`, `vinculacion.empleado`, `ingresos.DE_3M_A_5M`, `gastos.DE_1M_A_2M`, `cuotas.DE_1M_A_2M`, `cuota_trasladar.DE_1M_A_2M`, `monto.DE_20M_A_50M`, `plazo.60` | Semáforo + ahorro mensual estimado |

Los resultados esperados se confirman con el motor implementado; si alguno no
coincide, se ajusta la persona, no la regla.
