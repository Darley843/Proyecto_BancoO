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

## HITL con el asesor

El humano en el bucle es el asesor del banco, y el bot no se queda esperando a
que escriba: **suspende el turno** y lo reanuda la propia persona con un botón.
La entrevista es una máquina de estados (`canal/entrevista.py`); el HITL es un
grafo mínimo de dos nodos en `canal/hitl.py`, porque `interrupt()` y
`Command(resume=...)` solo existen dentro de un grafo con checkpointer.

- **Cuándo se suspende:** cuando el semáforo es `rojo`. El nodo `ofrecer` llama
  a `interrupt({"tipo": "asesor", "caso": {...}})` y el turno termina sin la
  tarjeta final.
- **Qué ve la persona:** el resumen del diagnóstico y dos botones,
  `Contactar` (`diagnostico.contactar`) y `Descartar` (`diagnostico.descartar`).
  Mientras el hilo está suspendido, cualquier otro mensaje repite esos botones.
- **Cómo se reanuda:** con `Command(resume={"accion": "contactar"|"descartar"})`
  sobre el mismo checkpoint. El despachador entrega el mensaje a la entrevista
  antes que al grafo de preguntas, así que el botón encuentra su hilo por
  `usuario_id` y no toca el de otra persona.
- **Contactar:** abre un `CasoAsesor` con `usuario_id`, motivo
  (`semaforo_rojo` o `asesor_solicitado`), semáforo, fecha y estado `pendiente`;
  responde que un asesor revisará el caso y envía la tarjeta.
- **Descartar:** no crea caso, cierra el turno y agradece.
- **Una segunda pulsación:** responde el aviso de «no hay caso pendiente» y no
  duplica la fila.
- **«Olvida mis datos»:** revoca el consentimiento y borra también el hilo
  suspendido, así no queda un caso a medias en la base.
- **Solicitud directa:** «quiero un asesor» a mitad de la entrevista abre el
  caso con semáforo `pendiente` y deja la entrevista.

El checkpoint solo guarda motivo, semáforo y la acción: el resultado del
diagnóstico sigue en `resultados_diagnostico`, que vence a las 24 horas, y el
hilo se borra al reanudar. La tabla `casos` no guarda nombre, número ni texto de
la conversación; el asesor lo ve en la vista Operación con motivo, semáforo,
estado y fecha. Las pruebas están en `test/test_canal_hitl.py` y
`test/test_canal_casos.py`.

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

El **valor de cálculo** de cada rango es representativo y no un límite del
producto. Los escenarios «¿Y si…?» y el MCP aceptan montos de **$500.000 a
$2.000 millones** (`[limites]` de `config/diagnostico.toml`), y el plazo sigue
los rangos de cada objetivo.

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

Umbrales configurables en `config/diagnostico.toml`: `verde_hasta` 0,30,
`amarillo_hasta` 0,40 y `vivienda_primera_cuota` 0,40.

Reglas adicionales:

- **Vivienda:** además, la primera cuota no debe superar el **40 % de los
  ingresos familiares**; si lo supera, el resultado es rojo con la alerta
  `vivienda_primera_cuota`. Es el límite del Decreto 583 de 2025, que modificó
  el Decreto 1077 de 2015 (antes era del 30 % para No VIS). La entrevista usa el
  ingreso declarado como referencia de los ingresos familiares.
- **Libranza:** la Ley 1527 de 2012, modificada por la Ley 1902 de 2018, cubre
  a empleados, pensionados y contratistas por prestación de servicios; lo que se
  exige es una **entidad pagadora con convenio**. La entrevista todavía no
  pregunta por esa entidad, así que el motor solo simula libranza para
  `empleado` o `pensionado`. Si es `independiente`, explica la regla y ofrece
  simular libre inversión.
- **Compra de cartera:** la capacidad comparable descuenta las cuotas que se
  trasladan y el margen se calcula con la cuota nueva. Además se informa el
  ahorro mensual estimado `cuota_trasladar − cuota_nueva`; si es negativo, se
  dice que el traslado no reduce la cuota con ese plazo.
- **Ahorro:** no hay semáforo de crédito. Se informa la capacidad de ahorro
  mensual (`capacidad`) y las tasas vigentes de ahorro y CDT del Tablero. La
  tasa de ahorro se presenta con el **tramo de saldo más bajo** (por ejemplo,
  «De 0 a $5.000.000») como referencia para quien empieza, y la envolvente del
  producto queda en `rango_completo` como dato adicional. El CDT no se resume en
  un solo porcentaje: `tasa_ea` es el rango por plazo del **monto mínimo** (por
  ejemplo, «De $500 mil a $99 millones»), `tramos` detalla cada plazo y
  `rango_completo` conserva la envolvente. El motivo explica que la tasa depende
  del plazo y del monto.
- **Capacidad negativa** (gastos + cuotas actuales > ingresos): rojo sin
  simular crédito, con recomendación de ordenar gastos y deudas primero. Con
  capacidad **cero** la recomendación del ahorro es revisar los gastos fijos, no
  automatizar un ahorro que no cabe en el presupuesto.
- **Vigencia:** si la vigencia de la tasa consultada no incluye la fecha de hoy
  (por ejemplo, la de ahorro del 4 al 9 de noviembre de 2026), el resultado
  agrega la alerta `vigencia_vencida` y un motivo que cita la vigencia publicada
  y la fecha de la consulta. La tasa se informa igual, con la advertencia. Si
  ninguna tabla cubre hoy, la consulta usa la más reciente en lugar de detener
  el diagnóstico: la app sigue respondiendo después del 30 de noviembre y el
  aviso viaja en el Tablero (`TasaVigente.vigencia_vencida`), en el motor y en
  el MCP. `TasaNoDisponible` queda solo para un producto sin ninguna tasa
  publicada.

## Representación en `ResultadoDiagnostico`

Los campos de crédito son opcionales porque no todos los productos simulan una
cuota. El motor lo representa así:

| Caso | `semaforo` | `cuota_mensual` y tasa | Alerta |
|---|---|---|---|
| Crédito simulado | `verde`, `amarillo` o `rojo` | Con valor, en rango | Ninguna |
| Ahorro (`objetivo.ahorro`) | `None` | `None`; `capacidad_pago` es la capacidad de ahorro y `tasas_captacion` lista ahorro y CDT | Ninguna |
| Libranza de independiente | `None` | `None` | `libranza_no_aplica` |
| Capacidad negativa | `rojo` (regla del guion) | `None`: no se simula | `capacidad_negativa` |
| Vivienda sobre el 40 % de los ingresos familiares (Decreto 583 de 2025) | `rojo` | Con valor | `vivienda_primera_cuota` |
| Tasa cuya vigencia no cubre hoy | El del producto | Con el valor publicado | `vigencia_vencida` |

`TasaCaptacion` guarda `producto`, `tasa_ea` (la referencia), `referencia` (el
tramo de saldo o la banda de monto), `rango_completo`, `tramos` (plazos del CDT
con su tasa), la vigencia y la fuente.

`monto_credito` y `plazo_meses` son obligatorios en los productos de crédito y
el contrato los prohíbe en ahorro: el validador rechaza un ahorro con monto o
plazo. `vinculacion` es obligatoria. `cuota_trasladar` es opcional y el motor
solo la exige en compra de cartera. `ahorro_mensual_estimado` se llena solo en
compra de cartera (`cuota_trasladar − cuota_nueva`) y `rango_usado` conserva el
id canónico de cada bloque de la entrevista.

Los ids de la entrevista se convierten en la entrada con
`diagnostico.motor.entrada_desde_respuestas`, que toma los valores de cálculo
de `config/diagnostico.toml`; el canal nunca conoce las cifras. El cálculo se
ejecuta con `diagnostico.motor.calcular`.

## Recomendaciones por color

- **Verde:** la cuota cabe con margen. Sugerir comparar plazos (el más corto
  paga menos intereses) y revisar requisitos del producto en la Bóveda.
- **Amarillo:** la cuota cabe pero con poco margen. Sugerir un plazo más largo
  o un monto menor, y simular de nuevo ("¿y si…?").
- **Rojo:** con estos datos la cuota compromete demasiado el ingreso. Sugerir
  monto menor o plazo mayor, compra de cartera si hay deudas caras, y suspender
  el turno con el HITL para ofrecer hablar con un asesor.
- **Ahorro sin capacidad (cero o negativa):** sugerir revisar los gastos fijos
  y renegociar las cuotas que más pesan; no proponer automatizar el ahorro
  hasta que haya margen.

## Texto de aviso (obligatorio)

> Este resultado es orientativo y se basa en rangos aproximados y en las tasas
> publicadas por el Banco de Occidente, vigentes [vigencia]. No incluye tu
> historial crediticio, que un banco evalúa obligatoriamente (Circular Básica
> Financiera, Circular Externa 004 de 2026 de la Superfinanciera, párrafo
> 1.1.2.27 c). No es una aprobación ni una oferta de crédito; la tasa final
> depende del monto, el plazo y tu perfil. Proyecto académico de la UAO, no es
> un canal oficial del banco.

## Referencias normativas

- **Decreto 583 de 2025**, que modificó el Decreto 1077 de 2015: la primera
  cuota de un crédito de vivienda no puede superar el **40 % de los ingresos
  familiares**. Antes el límite era del 30 % para vivienda No VIS.
- **Ley 1527 de 2012**, modificada por la **Ley 1902 de 2018**: la libranza
  cubre a empleados, pensionados y contratistas por prestación de servicios
  siempre que exista una **entidad pagadora con convenio**.
- **Circular Básica Financiera (CBF)**, Circular Externa 004 de 2026 de la
  Superintendencia Financiera de Colombia, párrafos **1.1.2.20**, **1.1.2.26**
  y **1.1.2.27**: evaluación de la capacidad de pago y del historial
  crediticio. Esta referencia reemplaza a la anterior «Circular Básica Contable
  y Financiera». El diagnóstico no consulta el historial: por eso el aviso lo
  declara fuera del alcance y el resultado nunca sustituye la evaluación del
  banco.

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

## Implementación y pruebas

| Pieza | Archivo | Qué hace |
|---|---|---|
| Configuración | `config/diagnostico.toml` | umbrales, límites de monto y plazo y mapeo producto → objetivo |
| Entrada | `diagnostico/motor.py::entrada_desde_respuestas` | ids de la entrevista → `EntradaDiagnostico` |
| Motor | `diagnostico/motor.py::calcular` | `ResultadoDiagnostico` con semáforo, cuota, tasas y avisos |
| Cálculo | `diagnostico/calculo.py` | `tasa_mensual`, `cuota_francesa`, capacidad y razón de endeudamiento |
| Tasas | `tablero/tasas.py` → `calculo.tasa_de_tablero` | solo la tabla Gold 2026; un spread no es una tasa |
| Escenarios | `diagnostico/escenarios.py` | `bifurcar_escenario`, `comparar_resultado` e `interpretar_pedido` |
| Comité | `diagnostico/comite.py` | `deliberar` con riesgo, comercial y auditor determinístico |
| Canal | `canal/entrevista.py` | pasos, botones y listas; el resultado vive 24 h por huella |
| Tarjeta | `pana/desde_diagnostico.py` | `tarjeta_y_texto` y `escenario_y_texto` |
| MCP | `mcp_servidor/servidor.py` | `simular_cuota` con las mismas primitivas, para que la cuota coincida |

Las pruebas que fijan este contrato, todas sin red:

```bash
uv run pytest test/test_diagnostico_calculo.py test/test_diagnostico_motor.py \
  test/test_diagnostico_escenarios.py test/test_diagnostico_comite.py \
  test/test_canal_entrevista.py test/test_pana_desde_diagnostico.py -q
```

`test/test_diagnostico_motor.py` recorre las cinco personas sintéticas de
`data/evaluacion/personas_sinteticas.json`; `test/test_canal_entrevista.py`
comprueba la tarjeta, el «¿Y si…?» y el vencimiento a las 24 horas; y
`test_simular_cuota_coincide_con_el_diagnostico` fija que el MCP y el motor dan
la misma cuota.
