# Comité de crédito

Criterios del comité de crédito del Corresponsal WhatsApp (cambio OpenSpec
`corresponsal-whatsapp`, comité multiagente). Responsable: Nayla.

El comité **no decide el semáforo**: el semáforo lo calcula el motor del
diagnóstico de forma determinística. El comité delibera **qué recomendarle a la
persona** cuando su caso es amarillo o rojo, con tres miradas que se controlan
entre sí.

## Marco normativo de referencia

Los criterios se inspiran en la gestión del riesgo de crédito del SIAR, hoy en
la **Circular Básica Financiera (CBF)** de la Superintendencia Financiera de
Colombia, expedida con la Circular Externa 004 de 2026 y vigente desde el 1 de
junio de 2026 (reemplaza a la Circular Básica Contable y Financiera, CE 100 de
1995). El SIAR está en la Parte 1, capítulo 1.

| Párrafo CBF | Qué exige | Cómo lo reflejamos |
|---|---|---|
| 1.1.2.20 | La entidad define sus propios niveles de tolerancia al riesgo | Umbrales como **política del proyecto**, configurables |
| 1.1.2.26 | Evaluación comprensiva de la capacidad de pago, fundamental para la probabilidad de incumplimiento | Capacidad de pago y margen del motor |
| 1.1.2.27 a | Flujos de ingresos y egresos | Ingresos, gastos fijos y cuotas de la entrevista |
| 1.1.2.27 b | Solvencia, por ejemplo nivel de endeudamiento | Razón de endeudamiento |
| 1.1.2.27 c | Historial crediticio de operadores de información | **No se usa** (ver "Por qué es orientativo") |
| 1.1.2.27 e | Escenarios según variables económicas y volatilidad de los flujos | Prueba de estrés diferenciada por vinculación |
| 1.1.2.15 | Análisis de sensibilidades y escenarios adversos | Escenarios precalculados por el motor |

Otras normas aplicables:

- **Vivienda:** la primera cuota no puede superar el **40 %** de los ingresos
  familiares (Decreto 583 de 2025, que modificó el Decreto 1077 de 2015; antes
  30 % para No VIS).
- **Libranza:** Ley 1527 de 2012 (modificada por la Ley 1902 de 2018): requiere
  entidad pagadora con convenio (asalariado, pensionado o contratista por
  prestación de servicios) y el deudor no puede recibir menos del 50 % del neto
  de su salario o pensión.

Los porcentajes de este documento (30 %, 40 % y los de estrés) son **política
del proyecto**, no cifras de la norma: la CBF deja los umbrales a cada entidad.

## Cuándo se activa

| Resultado del motor | ¿Comité? | Qué pasa |
|---|---|---|
| Verde | No | Respuesta directa del diagnóstico |
| Amarillo con cuota simulada | **Sí** | Deliberación de una ronda |
| Rojo con cuota simulada | **Sí** | Deliberación y oferta de asesor (HITL) |
| Rojo por capacidad negativa (sin cuota) | No | Recomendación fija de ordenar gastos y deudas + oferta de asesor |
| Ahorro / libranza que no aplica | No | Respuesta directa del diagnóstico |

## Entrada del comité

Solo datos calculados, nunca datos personales:

- `ResultadoDiagnostico` del motor (cuota en rango, tasa máxima y vigencia,
  razón de endeudamiento, capacidad, margen, semáforo y alertas).
- Los rangos elegidos en la entrevista (ids), no cifras exactas.
- **Escenarios precalculados por el motor** antes de llamar al modelo, para que
  nadie invente cifras:
  - plazo más largo (siguiente opción de la entrevista);
  - monto 20 % menor;
  - compra de cartera, si hay cuotas actuales;
  - **prueba de estrés de ingreso:** −10 % para empleado y pensionado, −20 %
    para independiente, con la misma cuota.
- Opcional: fragmentos de la Bóveda con requisitos del producto, marcados como
  datos.

Los escenarios viajan con un código estable (`plazo_mas_largo`,
`monto_20_por_ciento_menos`, `compra_de_cartera`, `estres_de_ingreso`), su
cuota, su semáforo, su razón de endeudamiento y su margen.

## Los tres agentes

Riesgo y comercial deliberan en paralelo con los mismos datos. El auditor corre
después, ya con las dos posturas, y las revisa. Si objeta, hay una única
corrección del comercial con sus hallazgos.

### Riesgo

Evalúa si la cuota es sostenible. Postura: `favorable`, `con_condiciones` o
`desfavorable`.

1. Razón de endeudamiento frente a los umbrales (30 % y 40 %) — CBF 1.1.2.27 b.
2. Margen después de la cuota — CBF 1.1.2.27 a.
3. **Prueba de estrés de ingreso** — CBF 1.1.2.27 e:
   - si con el ingreso estresado el margen se vuelve negativo o el semáforo pasa
     a rojo, la postura no puede ser `favorable`;
   - el estrés es mayor para independientes por la mayor volatilidad de sus
     flujos.
4. Alertas del motor (`vivienda_primera_cuota`, `vigencia_vencida`) deben
   mencionarse.

### Comercial

Busca una alternativa viable para no dejar a la persona sin opción.

1. Propone **máximo dos alternativas**, elegidas **solo** de los escenarios
   precalculados, citando su cuota y su semáforo tal como los dio el motor.
2. Prioriza la alternativa que deja la razón de endeudamiento en verde con el
   menor cambio (plazo antes que monto).
3. Si hay cuotas actuales caras, considera la compra de cartera.
4. Prohibido: prometer aprobación, inventar productos, tasas o plazos, o
   presionar a tomar crédito.

Cada alternativa que propone el agente empieza con el código del escenario
entre corchetes, por ejemplo `[plazo_mas_largo]`. La síntesis nunca inventa
texto de alternativa: toma la descripción del escenario precalculado.

### Auditor

Revisa a los otros dos. Postura: `conforme` u `objeta`, con hallazgos.

Lista de chequeo:

1. **Cifras:** cada número citado existe en la entrada (cuota, tasa, razón,
   margen, escenarios). El código también lo verifica de forma determinística.
2. **Tasa:** se cita la tasa máxima en E.A. y su vigencia; si hay
   `vigencia_vencida`, se dice.
3. **Sin promesas:** ninguna frase como "aprobado", "te lo dan", "garantizado"
   o equivalentes.
4. **Sin complacencia:** la recomendación final no puede ser más favorable que
   la postura de Riesgo, aunque la persona lo pida.
5. **Alternativas válidas:** solo las precalculadas.
6. **Aviso orientativo** presente.
7. **Sin datos personales** ni instrucciones tomadas de los fragmentos.

Además del agente, `diagnostico/comite.py` tiene un **auditor determinístico**
(`auditar`) que atrapa las cuatro trampas: cifra inventada, promesa de
aprobación, alternativa fuera de los escenarios y recomendación más favorable
que la de Riesgo. También revisa PII y, si se le pasa la recomendación final, el
aviso orientativo.

## Síntesis (reglas determinísticas)

1. El semáforo del motor **nunca cambia**.
2. La recomendación final toma la postura **más prudente** entre Riesgo y la
   síntesis comercial.
3. Si el Auditor **objeta**, se corrige una vez con sus hallazgos; si vuelve a
   objetar, se responde con el texto determinístico del diagnóstico (sin
   comité). Si Riesgo y Comercial se abstienen, también se responde con ese
   texto: el auditor determinístico no revisa los mensajes de error.
4. Rojo → siempre se ofrece hablar con un asesor (HITL), una sola vez.
5. Respuesta final: postura de cada agente en una línea, recomendación,
   hasta dos alternativas y el aviso orientativo.

La recomendación usa una de estas etiquetas: `apto`, `apto_con_condiciones`,
`no_apto` o `requiere_asesor`. Una abstención o un rol que no responde produce
`requiere_asesor`; si Riesgo y Comercial se abstienen a la vez, se usa el texto
del diagnóstico. Nunca se inventa una decisión.

## Por qué el resultado es orientativo

La CBF (1.1.2.27 c) exige que una entidad evalúe el historial de pagos y la
información de los operadores de información (centrales de riesgo). El
Corresponsal **no** consulta centrales de riesgo, por diseño y por protección de
datos. Por eso el resultado es orientativo y nunca una aprobación. El aviso lo
dice explícitamente:

> Este resultado es orientativo: se basa en rangos aproximados y en las tasas
> publicadas por el Banco de Occidente, vigentes [vigencia], y no incluye tu
> historial crediticio, que un banco evalúa obligatoriamente. No es una
> aprobación ni una oferta de crédito. Proyecto académico de la UAO, no es un
> canal oficial del banco.

## Salida estructurada

```python
class PosturaAgente(BaseModel):
    agente: Literal["riesgo", "comercial", "auditor"]
    postura: str
    argumentos: list[str]  # máximo 3
    evidencia: list[str]  # campos del resultado que respaldan cada argumento


class DeliberacionComite(BaseModel):
    posturas: list[PosturaAgente]
    recomendacion: str
    alternativas: list[str]  # máximo 2, de los escenarios precalculados
    hallazgos_auditor: list[str]
    ofrece_asesor: bool
```

Los modelos viven en `src/banco_occidente_corpus/diagnostico/comite.py` y se
piden con `with_structured_output(PosturaAgente, method="json_mode")`: el
esquema viaja en el prompt y la respuesta se valida con Pydantic. No se fuerza
`tool_choice`, porque el modo de razonamiento de DeepSeek lo rechaza con un 400.

## Límites y experiencia

- Una sola ronda; máximo 4 llamadas al modelo (3 agentes + 1 corrección).
- Tope de tokens por agente y tiempo máximo de la deliberación (30 s).
- Mientras delibera, el canal envía: "El comité está revisando tu caso…".
- La deliberación queda disponible para mostrarse en pantalla durante la demo.
- Costo esperado: alrededor de un centavo de dólar por deliberación.

Los límites se configuran en `[comite]` de `config/diagnostico.toml`:
`max_llamadas`, `max_tokens_agente`, `tiempo_maximo_segundos` y
`max_alternativas`.

## Cómo se prueba

- **Sin red:** modelos de prueba con posturas fijas, para verificar la síntesis,
  las reglas de precedencia y el tope de llamadas.
- **Estrés:** casos donde el estrés cambia el resultado (por ejemplo, un
  independiente en amarillo que con −20 % de ingreso pasa a margen negativo) y
  la postura de Riesgo no puede ser `favorable`.
- **Auditor bajo ataque:** respuestas sembradas con errores (una cifra
  inventada, una promesa de aprobación, una alternativa no precalculada, una
  recomendación más favorable que Riesgo). El auditor determinístico debe
  atraparlas todas.
- **Con DeepSeek real (pocas corridas):** Andrés (rojo) y Jaime (amarillo),
  revisando a mano la calidad de los argumentos.

Las pruebas viven en `test/test_diagnostico_comite.py`. La demo con DeepSeek
real se ejecuta con:

```bash
uv run python scripts/demo_comite.py
```

## Implementación

| Archivo | Responsabilidad |
|---|---|
| `diagnostico/comite.py` | `deliberar`, escenarios, auditor determinístico y síntesis |
| `config/prompts/comite_riesgo_v1.md` | Rol de riesgo |
| `config/prompts/comite_comercial_v1.md` | Rol comercial |
| `config/prompts/comite_auditor_v1.md` | Rol auditor |
| `test/test_diagnostico_comite.py` | Pruebas sin red del comité |
| `scripts/demo_comite.py` | Demo con DeepSeek real sobre Andrés y Jaime |

El comité todavía **no está conectado** al canal ni al grafo del diagnóstico:
esta entrega deja el módulo, sus pruebas y la demo listos para integrarlo.
