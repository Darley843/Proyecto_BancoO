# Demo «Pana vs. el gota a gota»

Escena en vivo del Taller 1 para el **sábado 28 de noviembre de 2026**. Don
Gota es un personaje ficticio: la escena no aprueba créditos, no acusa a
personas reales y no recomienda el gota a gota. Todas las cifras salen de
código determinista o del motor del diagnóstico; ningún turno de Don Gota lo
genera un modelo.

Este documento cubre las tareas 1.5, 2.5 y 3.5 del cambio
`demo-gota-a-gota`. Los ejemplos usan la tabla Gold de tasas de noviembre de
2026 (tasa máxima de libre inversión `28,17 % E.A.` y usura `28,34 % E.A.`) y
la fecha de consulta del 16 de noviembre de 2026. Si cambia la tabla, las
cifras se recalculan con el motor y no se escriben a mano.

## 1. Flujo de la escena

| # | Momento | Quién habla | Qué ocurre | Origen |
|---|---|---|---|---|
| 1 | Selección | Pana | Fila y silla al azar con `secrets.SystemRandom`; el voluntario inventa un personaje ficticio. No se pide nombre ni se guarda la selección. | `entrada_voz` |
| 2 | Cuatro preguntas | Pana y el voluntario | Monto, ingresos, gastos y deudas con letras A–F; Pana confirma las cuatro respuestas. Si el monto declarado cae dentro del rango de la letra se usa ese monto; si no, se usa el valor del rango y Pana lo dice. | `reglas` |
| 3 | Diagnóstico | Motor | `ResultadoDiagnostico`: cuota, tasa E.A., totales, semáforo, razón de endeudamiento, margen y aviso. | `motor` |
| 4 | Oferta | Don Gota | Cuatro turnos fijos con el interés mensual, el total del ciclo y la cuota diaria. | `guion_fijo` |
| 5 | Comparación | Pana | Golpe con el supuesto de 36 renovaciones, tasa E.A. frente a la usura y artículo 305. | `motor` |
| 6 | Negociación | Agente del joven y agente del banco | Hasta cuatro turnos sobre la mesa precalculada; el cierre remite a un asesor. | `llm` o `reglas` |
| 7 | Veredicto | Auditor | `conforme`, `con_observaciones` u `objeta`; si objeta, Pana ofrece alternativas formales. | `reglas` |

La escena dura menos de seis minutos. Los turnos de Don Gota ocupan los
órdenes 1–4 por defecto; Pana empieza en el 8 y la negociación en el 11, de
modo que los órdenes 5–7 quedan para la fase de perfil y diagnóstico de
`escena/servicio.py` (tarea 5.5 de Darley).

| Turno | Orden | Personaje |
|---|---|---|
| `gota.oferta.v1` | 1 | `don_gota` |
| `gota.presion.v1` | 2 | `don_gota` |
| `gota.renovacion.v1` | 3 | `don_gota` |
| `gota.cierre.v1` | 4 | `don_gota` |
| `pana.golpe.v1` | 8 | `pana` |
| `pana.tasa.v1` | 9 | `pana` |
| `pana.ley.v1` | 10 | `pana` |
| `negociacion.agente_joven.1.v1` | 11 | `agente_joven` |
| `negociacion.agente_banco.2.v1` | 12 | `agente_banco` |
| `negociacion.agente_joven.3.v1` | 13 | `agente_joven` |
| `negociacion.agente_banco.4.v1` | 14 | `agente_banco` |

## 2. Contrato `TurnoEscena`

La pantalla, la voz, los subtítulos, la entrada por voz y el auditor consumen
el mismo objeto. La pantalla no calcula cifras ni decide rutas: pinta lo que
recibe. Los modelos rechazan campos extra (`extra="forbid"`), así que cualquier
dato nuevo obliga a actualizar `design.md`, `app/web/escena/contrato.js` y
`escena/contratos.py` en el mismo cambio.

| Campo | Tipo | Regla |
|---|---|---|
| `id` | `str` | Identificador estable del turno. |
| `orden` | `int` | Posición en la escena; mayor o igual que cero. |
| `personaje` | `pana`, `don_gota`, `joven`, `agente_joven`, `agente_banco`, `auditor` | Coincide con las claves de `config/voz.toml`. |
| `texto` | `str` | Lo que se habla y se subtitula. |
| `subtitulo` | `str \| None` | Texto alterno para el modo solo subtítulos. |
| `cifras` | `tuple[CifraEscena, ...]` | Cada cifra con su fuente; vacío si el turno no cita cifras. |
| `escenario` | `EscenarioEscena \| None` | Escenario del motor que sostiene el turno, si aplica. |
| `origen` | `guion_fijo`, `motor`, `llm`, `reglas`, `entrada_voz` | Quién produjo el turno. Don Gota siempre usa `guion_fijo`. |
| `hallazgos` | `tuple[HallazgoEscena, ...]` | Observaciones del auditor sobre ese turno. |

`CifraEscena` guarda `etiqueta`, `valor` (decimal de máquina), `valor_legible`
(el texto que se muestra y que aparece en el turno), `unidad` (`pesos`,
`porcentaje_ea`, `porcentaje`, `meses`, `dias` o `veces`) y `fuente`. Las tasas
se guardan como fracción: `0.2834` es `28,34 % E.A.`.

`FuenteCifra` declara el origen verificable de cada cifra:

| `tipo` | Referencia típica | Verificación |
|---|---|---|
| `config` | `config/escena.toml#gota.tasa_mensual` | Leer el TOML y comparar el valor. |
| `gold` | `data/gold/tasas/tasas-personas-2026-11.jsonl#libre_inversion` | Leer la fila, comparar tasa, vigencia y `sha256`. |
| `motor` | `diagnostico.motor#cuota_mensual.hasta` | Comparar con el `ResultadoDiagnostico`. |
| `calculo_gota` | `escena.gota#total_pagado_horizonte` | Comparar con el `PrestamoGota`. |
| `usura` | `config/tasas.toml#usura.tasa_ea` | Comparar con la usura vigente. |
| `guion` | `config/escena.toml#gota.frases.oferta` | Comparar con la plantilla fija. |
| `documento` | `docs/ARQUEO.md#ancla` | Abrir el archivo versionado, ir al ancla y comparar el valor. |

El tipo `documento` se usa cuando la cifra viene de un archivo versionado que
no es configuración, Gold, motor, cálculo de Don Gota, usura ni plantilla fija;
la referencia debe incluir el ancla del documento. Toda `CifraEscena` debe
declarar una `FuenteCifra` con `referencia` no vacía.

El **semáforo del crédito** (`verde`, `amarillo`, `rojo`) es el resultado
financiero del motor y vive en `EscenarioEscena.semaforo`. El **veredicto del
auditor** (`conforme`, `con_observaciones`, `objeta`) vive en
`VeredictoAuditor.veredicto` y no usa colores. Son dos etiquetas separadas: un
crédito en rojo puede tener un auditor `conforme`, y un cierre no se habilita
si el veredicto es `objeta`.

## 3. Roles en vivo

| Rol | Persona | Responsabilidad |
|---|---|---|
| Operación | Nayla | Lleva el turno, elige al voluntario, controla los tiempos y decide el plan B. |
| Pantalla y voces | Yoldy | Abre `escena.html`, revisa avatares, subtítulos y audio; activa solo subtítulos si falla la voz. |
| Voluntario y micrófono | Darley | Acompaña al voluntario, prueba el micrófono y pasa a tarjetas A–F o perfil seguro si falla. |
| Auditor y plan B | Anny | Vigila el veredicto, el panel de trazabilidad y ejecuta el salto a núcleo o al JSON proyectado. |

El público no ve el panel de trazabilidad por defecto. El voluntario no entrega
datos personales: si dice un nombre, teléfono, correo o documento, Pana lo
redirige y no se guarda nada.

## 4. Don Gota: fórmulas y supuesto de las 36 renovaciones

`config/escena.toml [gota]` fija `tasa_mensual = 0.20`, `dias_ciclo = 30` y
`meses_horizonte = 36`. Las fórmulas se aplican en `Decimal` con
`ROUND_HALF_UP`:

```text
interes_mensual        = monto * tasa_mensual
total_ciclo            = monto + interes_mensual
cuota_diaria           = total_ciclo / dias_ciclo
intereses_horizonte    = interes_mensual * meses_horizonte
total_pagado_horizonte = monto + intereses_horizonte
tasa_ea                = (1 + tasa_mensual) ** 12 - 1
```

Con `$1.000.000` el resultado real de `calcular_prestamo_gota` es:

| Cifra | Valor |
|---|---|
| Interés mensual | `$200.000` |
| Total del ciclo | `$1.200.000` |
| Cuota diaria | `$40.000` |
| Intereses de 36 meses | `$7.200.000` |
| Total pagado en el horizonte | `$8.200.000` |
| Tasa E.A. equivalente | `791,61 % E.A.` |

El supuesto es **«si renuevas cada mes durante tres años»**: el interés del
horizonte es simple porque el capital no baja, no se capitaliza. La tasa E.A.
es la equivalente compuesta de la tasa mensual (`1,20^12 - 1`), no el total del
horizonte. Capitalizar el 20 % mes a mes daría `1,20^36` y la comparación
dejaría de ser creíble; por eso la escena declara la renovación sin capitalizar
en voz y en el panel de trazabilidad. Don Gota no dice la E.A. ni los totales de
36 meses: vende el costo mensual y la cuota diaria.

Los cuatro turnos reales de Don Gota para `$1.000.000` con el perfil `seguro`
son:

> «¿Necesitas $1.000.000? Te los presto hoy. Solo el 20 % al mes: me devuelves
> $1.200.000 en 30 días, sin papeles.»

> «Son solo $40.000 al día: divides $1.200.000 entre 30 días y listo. Si no
> pagas, la cuota sube.»

> «Renuevas cuando quieras: solo el 20 % al mes y $40.000 diarios. Sin papeles,
> sin fila y sin consulta.»

> «Firma hoy y te doy $1.000.000. Solo necesito tu compromiso y $40.000 al
> día.»

La frase de cada grupo se elige por índice determinista (SHA-256 del perfil),
no por un modelo: dos corridas del mismo perfil eligen la misma frase.

## 5. Comparación con el motor y la usura

`comparar_gota_banco` usa el mismo monto y el mismo horizonte de 36 meses, el
producto `libre_inversion` y la vinculación `empleado`. Del rango del motor
toma el extremo **máximo** de la tasa E.A., la cuota y los totales, igual que
el semáforo (`base_semaforo="tasa_maxima"`): la frase no usa el extremo
favorable. La usura sale de `config/tasas.toml [usura]`.

Con `$1.000.000` y la tabla de noviembre de 2026:

| Cifra | Don Gota | Banco (extremo máximo) |
|---|---|---|
| Tasa E.A. | `791,61 % E.A.` | `28,17 % E.A.` |
| Total en 36 meses | `$8.200.000` | `$1.432.836` |
| Diferencia | `$6.767.164` a favor del banco | — |
| Veces el total del banco | `5,72` → «casi 6 veces» | — |
| Veces la usura | `27,93` → «27,9 veces» | — |

La usura vigente es `28,34 % E.A.` del 1 al 30 de noviembre de 2026. Los tres
turnos reales de Pana son:

> «Si renuevas cada mes durante tres años, con Don Gota pagarías $8.200.000 por
> $1.000.000; con el banco, a 36 meses, $1.432.836. Es casi 6 veces lo que
> pagarías con el banco.»

> «Don Gota cobra 791,61 % E.A.: 27,9 veces la usura. El banco, a su tasa
> máxima, cobra 28,17 % E.A.»

> «Si te cobran por encima de la usura, es delito (Código Penal, artículo 305).
> Usura vigente: 28,34 % E.A., del 1 al 30 de noviembre de 2026.»

La frase del artículo 305 es informativa y no acusa a una persona real. Si la
usura no está certificada, la comparación deja vacíos `usura_ea`,
`usura_vigencia`, `veces_usura` y `fuente_usura`, muestra
`usura_sin_certificar` y el auditor no puede dar `conforme`. Si el Tablero no
publica la tasa del producto, el motor sube `tasa_no_disponible`; la escena no
inventa una tasa y usa el núcleo.

## 6. Mesa de escenarios

`construir_mesa` precalcula con `diagnostico.motor.calcular` los escenarios que
los agentes pueden discutir. Los códigos son exactamente `CODIGOS_MESA`:

| Código | Monto | Plazo | Producto | ¿Ofertable? |
|---|---|---|---|---|
| `base` | El del perfil | 36 | Libre inversión | Sí |
| `plazo_mas_largo_48` | Igual | 48 | Libre inversión | Sí |
| `plazo_mas_largo_60` | Igual | 60 | Libre inversión | Sí |
| `monto_20_por_ciento_menos` | 80 % | 36 | Libre inversión | Sí |
| `monto_40_por_ciento_menos` | 60 % | 36 | Libre inversión | Sí |
| `compra_de_cartera` | Igual | 36 | Compra de cartera | Sí, solo si el perfil tiene deudas |
| `estres_de_ingreso` | Igual | 36 | Libre inversión | No: es una prueba, no una oferta |

Los escenarios con monto por debajo de la frontera de
`config/diagnostico.toml` no se construyen. La prueba de estrés baja el ingreso
un 10 % y mantiene la cuota; ningún agente puede venderla. Un escenario es
`aceptable` solo si es ofertable, tiene cuota simulada, su semáforo es verde o
amarillo y deja margen mayor o igual que cero. Los umbrales del semáforo no se
mueven: salen de `config/diagnostico.toml`.

## 7. Negociación acotada

### 7.1 Turnos y lenguaje

La secuencia determinista es:

1. `agente_joven` propone el crédito pedido.
2. `agente_banco` recomienda si es sostenible, contrapropone la alternativa
   verde con el menor cambio si está ajustado, o dice que no cabe.
3. `agente_joven` acepta la contrapropuesta o prueba la siguiente alternativa.
4. `agente_banco` cierra con el escenario aceptado o con `sin_acuerdo`.

El banco **nunca acepta ni aprueba**: recomienda, contrapropone o rechaza. El
cierre siempre incluye «La decisión final es de un asesor.». El texto prohíbe
`acepto`, `aceptamos`, `cerramos`, `aprobado`, `aprobación`, `aprobamos` y
«me quedo con el crédito». El modelo solo aporta un argumento corto, sin
dígitos, sin nombres de color, sin promesas y sin recomendar el gota a gota;
las cifras las pone la plantilla desde el `EscenarioEscena`. Un argumento que
incumpla esas reglas se descarta y se usa la política determinista.

Los ejemplos reales de los tres perfiles usan ingresos, gastos y deudas
ficticios: verde `$5.000.000 / $2.000.000 / $0`, amarillo
`$3.000.000 / $1.200.000 / $0` y rojo `$2.000.000 / $1.500.000 / $0`.

| Perfil | Monto pedido | Cuota base | Total base | Semáforo base | Margen base | Resultado |
|---|---|---|---|---|---|---|
| Verde | `$10.000.000` | `$398.006` | `$14.328.216` | Verde | `$2.601.994` | Acuerdo en `base` en 2 turnos. |
| Amarillo | `$25.000.000` | `$995.016` | `$35.820.576` | Amarillo | `$804.984` | Acuerdo en `plazo_mas_largo_48` en 4 turnos. |
| Rojo | `$30.000.000` | `$1.194.019` | `$42.984.684` | Rojo | `-$694.019` | Sin acuerdo: el banco no acepta un rojo. |

### 7.2 Verde

> «Quisiera $10.000.000 a 36 meses; la cuota sería $398.006.»

> «Esta opción es sostenible: la cuota de $398.006 para $10.000.000 a 36 meses
> cabe con holgura y el total es $14.328.216. La decisión final es de un
> asesor.»

### 7.3 Amarillo

El escenario base es aceptable por código (amarillo y margen positivo), pero la
política determinista busca una alternativa verde con el menor cambio: primero
el plazo y después el monto. Así no cierra en un escenario ajustado si existe
uno holgado.

> «Quisiera $25.000.000 a 36 meses; la cuota sería $995.016.»

> «Cabe, pero ajustado: con 48 meses la cuota baja de $995.016 a $830.005, pero
> el total sube de $35.820.576 a $39.840.240: $4.019.664 más.»

> «Entre pagar menos al mes y pagar menos en total, prefiero la cuota más baja.
> Quisiera $25.000.000 a 48 meses; la cuota sería $830.005.»

> «Esta opción es sostenible: la cuota de $830.005 para $25.000.000 a 48 meses
> cabe con holgura y el total es $39.840.240. La decisión final es de un
> asesor.»

La contrapropuesta siempre compara las dos cifras: la cuota que baja y el total
que sube, con la diferencia de total. No se presenta la cuota más baja como una
ventaja sin decir cuánto cuesta en total.

### 7.4 Rojo

> «Quisiera $30.000.000 a 36 meses; la cuota sería $1.194.019.»

> «No cabe en tu capacidad: con $30.000.000 a 36 meses la cuota de $1.194.019
> supera el margen de tu presupuesto.»

> «Quisiera $30.000.000 a 60 meses; la cuota sería $881.897.»

> «Con $30.000.000 a 60 meses la cuota de $881.897 sigue por encima de tu
> capacidad. Con el monto menor la cuota sería $716.412 y tampoco alcanza: no
> hay acuerdo hoy. La decisión final es de un asesor.»

En el rojo el joven prueba primero el plazo de 60 meses y después el monto
menor. El escenario de 60 meses deja margen `-$381.897`; el monto 40 % menor
(`$18.000.000`) deja `-$216.412`: ninguno es aceptable. La escena cierra sin
acuerdo y Pana ofrece alternativas formales (microcrédito, cooperativas y
entidades vigiladas por la Superfinanciera), sin prometer aprobación.

### 7.5 Límites de tiempo y política determinista

| Límite | Valor |
|---|---|
| Turnos | Máximo 4 |
| Tiempo total | 15 segundos |
| Tiempo por llamada | 4 segundos |
| Palabras por turno | 40 |
| Temperatura | 0 |
| Reintentos | 0 |

`cargar_limites_negociacion` recorta los valores del TOML contra esos máximos:
aunque el archivo traiga más, la negociación no los supera. El reloj se controla
con `ThreadPoolExecutor` y `future.result(timeout=min(4, restante))`; si una
llamada falla o se agota el tiempo, ese turno y los siguientes usan la política
determinista. Si no hay acuerdo, el registro lo declara y es un final válido.

Con `SUCURSAL_DEMO` en `1`, `true`, `si` o `sí`, o sin `DEEPSEEK_API_KEY`, se
usa directamente la política determinista de principio a fin, con los mismos
cuatro turnos y `origen="reglas"`; no se construye el modelo. Las pruebas usan
dobles (`FakeListChatModel` o un runnable equivalente) y nunca abren la red.

Mientras entre la tarea 4.2 de Anny, `negociar` acepta un auditor inyectable y,
si no se pasa, deja un veredicto provisional `con_observaciones` con el hallazgo
`auditor_pendiente`. Ese veredicto nunca es `conforme`: la escena no se cierra
como aprobada sin el auditor real.

## 8. Plan B

| Paso | Cuándo se activa | Qué se hace |
|---|---|---|
| Escena completa | Todo funciona | API, DeepSeek y voces de Piper o del navegador. |
| Núcleo | La negociación falla o supera 15 s | Don Gota → Pana → auditor, `modo="nucleo"`, con el botón **Núcleo**. |
| Solo subtítulos | Falla la voz o el audio | No se llama a `/api/voz`; se avanza con clic, espacio o Enter y el público lee las cifras. |
| Perfil seguro | Falla el micrófono, el reconocimiento de voz o el voluntario no confirma | Se usa un perfil ficticio preparado; el auditor se ejecuta igual. |
| Escena proyectada | Falla la API o el plan B no se recupera | `GET /api/escena/proyectado` lee `data/escena/proyectado.json`; si la app se cayó, se reinicia `make app`. |
| Simulador o escena proyectada | Último recurso, todo en vivo | `make simular` con las personas sintéticas o la escena proyectada (`data/escena/proyectado.json`); sin capturas ni video. |

Los ensayos del viernes 27 miden el tiempo de recuperación de cada salto y
lo anota aquí (tarea 7.5). La regla es que el plan B se active en menos de un
minuto y que la escena no se detenga.

## 9. Comandos

Preflight y ensayo:

```make
make check
make voces-prueba
make app
```

La escena se abre en `http://127.0.0.1:8000/escena.html`. Para el modo demo sin
modelo, en PowerShell:

```powershell
$env:SUCURSAL_DEMO = "1"
make app
```

El objetivo del plan B es **aparte** de `make simular`, que no se modifica:

```make
make escena-proyectada
```

`make escena-proyectada` ejecuta
`uv run python -m banco_occidente_corpus.escena --proyectado` y escribe
`data/escena/proyectado.json` sin DeepSeek, sin red y sin Ollama. **Depende de
la tarea 7.2 de Darley (`escena/__main__.py`), que todavía no existe**: el
objetivo está listo y documentado, pero no se ejecuta hasta que entre esa tarea.
Por eso el preflight no lo corre todavía; cuando exista, genera el JSON que usa
el plan B.

## 10. Verificación

- Los valores de `$1.000.000` están fijados en
  `test/test_escena_gota.py` (interés, ciclo, cuota diaria, intereses de 36
  meses, total y `791,61 % E.A.`).
- La comparación, el extremo máximo, la usura, el artículo 305 y
  `usura_sin_certificar` están en `test/test_escena_comparacion.py`.
- La mesa, los cuatro turnos, los códigos, el lenguaje sin aprobación, los
  límites y la política determinista están en `test/test_escena_negociacion.py`.
- `data/escena/` queda ignorado por Git:
  `git check-ignore -v data/escena/proyectado.json` devuelve la regla de
  `.gitignore`.
- `config/escena.toml` y este documento no contienen secretos, teléfonos,
  correos, documentos ni datos de clientes.
- Antes de dar la escena por cerrada: `make check`,
  `uv run ruff format --check .` y
  `openspec validate demo-gota-a-gota --strict` en verde.
