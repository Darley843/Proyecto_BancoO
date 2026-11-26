# Pana anfitrión: preguntas probables y respuestas fijas

Ficha del presentador para la tarea 6.13 del cambio `demo-gota-a-gota` y fuente
única de las respuestas fijas: la usan el endpoint `POST /api/escena/pregunta` y la
ficha corta de la pantalla, y de aquí salen las entradas de
`config/escena.toml [preguntas]` (tarea 6.14). Son las preguntas que más
probablemente hará el profesor o un invitado en la sustentación del **sábado 28**.

Cada pregunta tiene dos textos:

- **Voz:** la respuesta fija que dice Pana. Si la pregunta del público coincide
  con una de estas, Pana la dice tal cual (`origen: "guion_fijo"`), con la línea
  `Fuente:` que apunta al ancla de esta ficha (`docs/PRESENTADOR.md#p1` a `#p22`).
  Máximo tres frases y 40 palabras contando esa línea, como exige la 6.14.
- **Detalle:** la versión larga, para el panel de la pantalla y para quien
  presenta. No se dice en voz alta.

Si la pregunta no coincide, la responde el recuperador del proyecto con el modelo
(`origen: "llm"`); el rechazo y el respaldo usan `origen: "reglas"`.

Reglas de redacción, iguales a las del documento de Pana anfitrión:

- Español, tuteo y, en la voz, como mucho tres frases y 40 palabras.
- Sin códigos internos ni nombres de archivo. Las cifras se escriben como se
  dicen.
- Cada respuesta tiene su fuente en el repositorio, para revisarla antes de
  congelar.
- Nada de promesas: Pana no aprueba créditos y lo dice.

Las marcas **⚠️ Confirmar** señalan lo que el equipo tiene que validar antes de
usar la respuesta en vivo.

---

## A. El proyecto

<a id="p1"></a>

### P1. ¿Qué es este proyecto? / ¿Qué es la Sucursal 1965?

**Variantes:** de qué se trata, qué hicieron, qué es Pana, qué es la Sucursal.

**Voz** (lo que dice Pana):

> Somos un asistente que responde por WhatsApp con la información pública del Banco de Occidente, siempre citando la fuente. Orienta a jóvenes antes de su primer crédito. Se llama Sucursal 1965 porque el banco nació en 1965.

**Detalle (para el panel, no para la voz):**
Somos un asistente del Banco de Occidente construido solo con su información
pública: el sitio web, sus documentos y sus videos, siempre citando la fuente.
Responde preguntas por la web y por WhatsApp, y orienta a jóvenes que van a pedir
su primer crédito con un diagnóstico de semáforo. Se llama Sucursal 1965 porque el
banco nació en Cali en 1965.

**Fuente:** `README.md` («Problema y solución»); el año sale del fragmento de
*Nuestro Banco* en la Bóveda.

<a id="p2"></a>

### P2. ¿Quiénes son y qué hizo cada uno?

**Variantes:** quién hizo qué, el equipo, los integrantes.

**Voz** (lo que dice Pana):

> Somos cuatro. Nayla hizo las tasas, el motor del diagnóstico, el comité y el agente en OpenClaw; Darley, WhatsApp y el servidor MCP; Anny, la búsqueda, su evaluación y la seguridad; y Yoldy, la documentación y la pantalla.

**Detalle (para el panel, no para la voz):**

| Quién | Sucursal 1965 y agente | Escena «Pana vs. el gota a gota» |
|---|---|---|
| Nayla | Tasas 2026, motor del diagnóstico, comité y entrevista por WhatsApp; agente en OpenClaw (gateway, workspace, seguridad y conexión del MCP) | Don Gota, comparación con el motor y negociación |
| Darley | Canal de WhatsApp con Meta, HITL, modo evento y servidor MCP con las 20 herramientas | Entrada por voz, voluntario (tecla V) y API de la escena |
| Anny | Bóveda: evaluación (Arqueo y t-SNE), seguridad, Roba la Bóveda y cuatro herramientas del agente | Auditor y plan B |
| Yoldy | Frontend, Tablero, mapa y operación/latencia; documentación y diagramas | Pantalla, voces, retratos y Pana anfitrión |

**Fuente:** cada quien su fila; `openspec/changes/agente-openclaw/tasks.md` y
`openspec/changes/demo-gota-a-gota/tasks.md`.
**⚠️ Confirmar:** Darley, su fila. La escena mantiene el voluntario por voz
(tecla V, opción B), como anuncia la presentación de Pana (#205).

<a id="p3"></a>

### P3. ¿Usaron inteligencia artificial para programarlo?

**Variantes:** lo hizo una IA, usaron ChatGPT, usaron agentes, quién escribió el
código.

**Voz** (lo que dice Pana):

> Sí, como asistente, y lo decimos abiertamente. Cada cambio parte de una especificación, pasa pruebas automáticas y una revisión automática, y otra persona del equipo lo revisa antes de entrar. La IA acelera; las decisiones son nuestras.

**Detalle (para el panel, no para la voz):**
Sí, como asistente, y lo decimos abiertamente. Cada cambio empieza en una
especificación de OpenSpec, pasa por pruebas automáticas y por la revisión de GGA,
y otra persona del equipo lo aprueba antes de entrar a main. La IA acelera; las
decisiones y la revisión son nuestras.

**Fuente:** propuesta del equipo (22 nov); `AGENTS.md`, `.pre-commit-config.yaml`
(revisión GGA) y `CONSTITUTION.md` §14 (protección de `main`: un PR con una
aprobación de alguien distinto a quien subió el cambio).

---

## B. Decisiones técnicas

<a id="p4"></a>

### P4. ¿Por qué eligieron Qdrant?

**Variantes:** base vectorial, por qué no Chroma, dónde guardan los vectores.

**Voz** (lo que dice Pana):

> El curso pedía una base vectorial con colección, metadatos y filtros, y Qdrant lo cumple dentro del mismo programa, sin un servidor aparte. Los textos del banco no salen del computador. Empezamos con Chroma y quedó como alternativa.

**Detalle (para el panel, no para la voz):**
El módulo 2 pedía una base vectorial con colección, metadatos y filtros, y Qdrant
lo cumple corriendo dentro del mismo programa, sin un servidor aparte. Todo queda
en el computador: los textos del banco no salen a ningún servicio. Empezamos con
Chroma y lo dejamos como opción de compatibilidad.

**Fuente:** `CONSTITUTION.md` §11, decisión del 13 de noviembre de 2026.

<a id="p5"></a>

### P5. ¿Por qué DeepSeek?

**Variantes:** qué modelo usan, por qué no OpenAI, cuánto cuesta.

**Voz** (lo que dice Pana):

> Por costo: una deliberación del comité cuesta menos de una décima de centavo de dólar y un mensaje del agente, una o dos décimas. Solo redacta: las cifras salen del motor y de las tasas.

**Detalle (para el panel, no para la voz):**
Por costo: una deliberación del comité cuesta menos de una décima de centavo de
dólar (las tres rondas de la demo, con 18 posturas, costaron USD 0,0033) y la app
tiene un tope de veinte centavos al día. Con OpenClaw cada mensaje usa el modelo:
Nayla midió entre una y dos décimas de centavo por mensaje, y el tope global del
modo evento, 300 mensajes, deja la jornada en menos de un dólar. Además se integra
directo con LangChain y es el mismo modelo que usamos en OpenCode. Y solo redacta:
las cifras salen del motor y de las tasas del banco, no del modelo.

**Fuente:** medición de Nayla en la revisión de este PR (USD 0,0005 por
deliberación) y en el #204 (0,1 a 0,2 centavos por mensaje con OpenClaw);
`CONSTITUTION.md` §3 y §11 (embeddings locales: «solo DeepSeek se paga»);
`docs/DESPLIEGUE_WHATSAPP.md` §8.2 (tope global del modo evento).

<a id="p6"></a>

### P6. ¿Cómo saben que la búsqueda funciona bien?

**Variantes:** cómo lo evaluaron, qué tan preciso es, métricas, el Arqueo.

**Voz** (lo que dice Pana):

> La medimos con 36 preguntas de fuente conocida: la búsqueda híbrida la encuentra entre los cinco primeros resultados en 27, y solo con palabras clave en 19. Por ser pocas, damos su intervalo de confianza.

**Detalle (para el panel, no para la voz):**
Lo medimos con 36 preguntas cuya respuesta correcta conocemos: la búsqueda híbrida
encuentra la fuente correcta entre los cinco primeros resultados en 27 de las 36,
y solo con palabras clave en 19. Con 36 preguntas el margen de error es amplio, y
por eso lo reportamos con su intervalo de confianza y no como una cifra exacta.

**Fuente:** `docs/ARQUEO.md` y `data/evaluacion/arqueo.json` (hit@5 0,75 = 27/36
con 0,6/0,4 y con 1/0; 0,53 = 19/36 con 0/1; intervalo de Wilson).

<a id="p7"></a>

### P7. ¿Cómo evitan que responda cualquier cosa?

**Variantes:** preguntas fuera de tema, alucinaciones, el filtro, el Digiturno.

**Voz** (lo que dice Pana):

> Cada pregunta pasa primero por reglas fijas que deciden si es del banco, de tarifas, de diagnóstico o de otro tema; el modelo solo resuelve las dudas. De cincuenta preguntas fuera de tema, ninguna se coló.

**Detalle (para el panel, no para la voz):**
Cada pregunta pasa primero por reglas fijas que deciden si es del banco, de
tarifas, de diagnóstico o de otro tema, y el modelo solo decide los casos dudosos.
En una prueba con cincuenta preguntas fuera de tema, ninguna se coló. Además,
cada respuesta debe citar su fuente, y si no la encuentra, lo dice.

**Fuente:** `CONSTITUTION.md` §11 (Digiturno: reglas antes que modelo, decisión del
17 de noviembre de 2026); `docs/ARQUEO.md` («Filtro de dominio»: fuga 0 de 50 en
las tres corridas con el modelo).

<a id="p8"></a>

### P8. ¿Por qué las voces de Piper y de Edge?

**Variantes:** de dónde salen las voces, por qué esa voz, es una voz real.

**Voz** (lo que dice Pana):

> Piper genera las voces en el computador, sin internet y sin enviar el texto. Pana usa una voz colombiana de Edge, más natural, y sin red vuelve sola a Piper. Sin sonido, quedan los subtítulos.

**Detalle (para el panel, no para la voz):**
Piper genera las voces en el computador, sin internet y sin enviar el texto a
nadie, así que siempre funciona. Para Pana usamos una voz colombiana de Microsoft
Edge, más natural, que sí necesita internet; si se cae la red, vuelve sola a su
voz de Piper. Y si no hay sonido, la escena sigue con subtítulos.

**Fuente:** `docs/VOZ.md`; arreglos de los PR #171 y #177.

---

## C. Crédito, datos y seguridad

<a id="p9"></a>

### P9. ¿El sistema aprueba créditos?

**Variantes:** me van a prestar, es una aprobación, sirve para pedir un crédito.

**Voz** (lo que dice Pana):

> No. El diagnóstico es orientativo: dice si la cuota te cabe en el bolsillo con los datos que diste, sin consultar tu historial. La decisión siempre es del banco, con su propio estudio.

**Detalle (para el panel, no para la voz):**
No. El diagnóstico es orientativo: dice si la cuota te cabe en el bolsillo con los
datos que diste, pero no consulta tu historial ni decide por el banco. La decisión
real siempre es del banco, con su propio estudio.

**Fuente:** `docs/COMITE.md` («Por qué es orientativo»; el historial crediticio
no se usa) y `docs/DIAGNOSTICO.md`.

<a id="p10"></a>

### P10. ¿Cómo se calcula el semáforo?

**Variantes:** verde, amarillo y rojo, qué significa cada color, los umbrales.

**Voz** (lo que dice Pana):

> Comparamos cuotas e ingresos: hasta el 30 % es verde, hasta el 40 % amarillo, y más arriba, o si los gastos superan los ingresos, rojo. Son límites del proyecto, como permite la norma.

**Detalle (para el panel, no para la voz):**
Comparamos tus cuotas con tus ingresos. Si se llevan hasta el 30 % es verde, entre
30 y 40 % es amarillo, y por encima del 40 %, o si los gastos ya superan los
ingresos, es rojo. Esos límites son política del proyecto, porque la norma de la
Superfinanciera deja que cada entidad fije los suyos.

**Fuente:** `docs/DIAGNOSTICO.md` (umbrales `verde_hasta` 0,30 y
`amarillo_hasta` 0,40) y `docs/COMITE.md` («Marco normativo», CBF 1.1.2.20).

<a id="p11"></a>

### P11. ¿Qué hace el comité de crédito?

**Variantes:** los tres agentes, riesgo y comercial, por qué varios agentes.

**Voz** (lo que dice Pana):

> En amarillo o rojo deliberan tres agentes: Riesgo, Comercial y un Auditor que revisa a los otros dos. El semáforo nunca cambia y gana la recomendación más prudente. Nadie inventa cifras: usan las del motor.

**Detalle (para el panel, no para la voz):**
Cuando el resultado es amarillo o rojo, tres agentes deliberan: Riesgo, Comercial
y un Auditor que revisa a los otros dos. El semáforo nunca cambia, y se queda la
recomendación más prudente. Ninguno puede inventar cifras: solo usan los
escenarios que el motor ya calculó.

**Fuente:** `docs/COMITE.md` («Los tres agentes» y «Síntesis»).

<a id="p12"></a>

### P12. ¿Qué hace el auditor?

**Variantes:** para qué sirve el auditor, quién revisa las cifras.

**Voz** (lo que dice Pana):

> Revisa cada intervención: que toda cifra tenga fuente, que nadie prometa un crédito, que nadie recomiende el gota a gota y que no haya datos personales. Su veredicto es conforme, con observaciones u objeta, sin colores.

**Detalle (para el panel, no para la voz):**
El auditor revisa cada intervención: que toda cifra exista y tenga fuente, que
nadie prometa una aprobación, que nadie recomiende el gota a gota y que no
aparezcan datos personales. Su veredicto es conforme, con observaciones u objeta,
sin colores, para no confundirlo con el semáforo del crédito. Si objeta, la escena
no termina en verde.

**Fuente:** `src/banco_occidente_corpus/escena/auditor.py` (#182, seis reglas
altas y cinco medias), `openspec/changes/demo-gota-a-gota/tasks.md` (4.2 y 4.3) y
`docs/COMITE.md` («Auditor»).

<a id="p13"></a>

### P13. ¿Cómo protegen los datos personales?

**Variantes:** Ley 1581, privacidad, guardan mi número, habeas data.

**Voz** (lo que dice Pana):

> Primero pedimos tu autorización según la Ley 1581, y no guardamos tu número: lo convertimos en un código irreversible. Los datos personales se bloquean antes del modelo, y «olvida mis datos» borra todo.

**Detalle (para el panel, no para la voz):**
Antes de empezar pedimos autorización con el aviso de la Ley 1581, y no guardamos
el número: lo convertimos en un código que no se puede revertir. Los datos
personales se bloquean antes de llegar al modelo, y basta escribir «olvida mis
datos» para borrar todo. Todo lo que hoy se usa en la escena es inventado.

**Fuente:** `docs/SEGURIDAD.md`, `docs/OPERACION_WHATSAPP.md` y
`CONSTITUTION.md` §13; la revocación la comprueba `make simular` (9.3).

<a id="p14"></a>

### P14. ¿Qué pasa si el resultado es rojo?

**Variantes:** el asesor, me llama alguien, el caso, el HITL.

**Voz** (lo que dice Pana):

> Pana te ofrece un asesor y tú decides si lo contactas. Si aceptas, se abre un caso que el asesor ve en la vista de Operación. Como es un proyecto académico, el banco real no recibe estos casos.

**Detalle (para el panel, no para la voz):**
Pana te ofrece hablar con un asesor y tú decides si pulsas Contactar o Descartar.
Si contactas, se abre un caso que el asesor ve en la vista de Operación. Como es un
proyecto académico, el banco real no recibe estos casos.

**Fuente:** `docs/LISTA_DEMO.md` (sección 5, pasos 11 y 15) y `docs/COMITE.md`
(«Síntesis», punto 4).

---

## D. La actividad

<a id="p15"></a>

### P15. ¿Qué es el gota a gota y por qué lo muestran?

**Variantes:** Don Gota, préstamo informal, usura, por qué es peligroso.

**Voz** (lo que dice Pana):

> Es un préstamo informal al 20 % mensual: renovando un millón por tres años pagas 8,2 millones, casi seis veces lo del banco. Su tasa, cerca de 800 % anual, es unas 28 veces la usura: es delito.

**Detalle (para el panel, no para la voz):**
Es un préstamo informal que cobra el 20 % cada mes: por un millón pagas cuarenta
mil diarios, y si renuevas durante tres años terminas pagando 8,2 millones, casi
seis veces lo que pagarías con el banco. Su tasa, de casi 800 % efectivo anual, es
unas 28 veces la de usura, y cobrar por encima de la usura es delito en Colombia.
Lo mostramos para que se vea, con cifras, lo que cuesta lo fácil.

**Fuente:** `openspec/changes/demo-gota-a-gota/tasks.md` (2.1: interés de
$200.000 por ciclo, cuota diaria de $40.000, total de $8.200.000 en 36 meses y
791,61 % E.A.; 2.3 y 2.4: artículo 305 del Código Penal); PR #174 (8,2 millones
frente a 1,4 con el banco y 27,9 veces la usura).
La tasa del gota se configura en `config/escena.toml` (20 % mensual).

<a id="p16"></a>

### P16. ¿Por qué Don Gota no es una inteligencia artificial?

**Variantes:** el villano, por qué está guionado.

**Voz** (lo que dice Pana):

> A propósito: no queremos que un modelo de lenguaje escriba un discurso a favor del gota a gota, ni por error. Don Gota dice frases fijas y sus cifras salen de una fórmula. Los demás sí son agentes.

**Detalle (para el panel, no para la voz):**
A propósito: no queremos que un modelo de lenguaje escriba jamás un discurso a
favor del gota a gota, ni por error. Don Gota dice frases fijas y sus cifras salen
de una fórmula, así que siempre dice lo mismo y siempre cuadra. Los demás
personajes sí son agentes.

**Fuente:** `openspec/changes/demo-gota-a-gota/tasks.md` (2.2: ningún turno de Don
Gota tiene `origen="llm"`).

<a id="p17"></a>

### P17. ¿Qué pasa si algo falla en vivo?

**Variantes:** se cae internet, falla DeepSeek, plan B.

**Voz** (lo que dice Pana):

> Cada pieza tiene respaldo: si OpenClaw no responde, el canal contesta con nuestro flujo anterior; sin DeepSeek, la negociación sigue con reglas fijas; y si fallan la pantalla o las voces, todo continúa por WhatsApp. Lo ensayamos antes.

**Detalle (para el panel, no para la voz):**
Cada pieza tiene un respaldo. Si OpenClaw no responde, el canal contesta con el
grafo que ya funcionaba; sin DeepSeek, la app pasa a modo demo y la negociación
sigue con reglas fijas; si fallan la pantalla o las voces, todo continúa por
WhatsApp y la escena sigue con subtítulos; y si se cae Meta o el túnel, se
reinicia el túnel y, como último recurso, se muestra el simulador. Lo ensayamos el
viernes en el computador de la demo.

**Fuente:** `docs/LISTA_DEMO.md` (sección 6, plan B del canal y de la escena) y
`openspec/changes/demo-gota-a-gota/tasks.md` (7.5: completa → núcleo → solo
subtítulos → perfil seguro → escena proyectada).

---

## E. El repositorio, el código y las pruebas

<a id="p18"></a>

### P18. ¿Dónde está el repositorio y puedo ver los pull requests?

**Variantes:** repositorio público, ver el código, los PR, dónde suben el proyecto.

**Voz** (lo que dice Pana):

> El repositorio es público y está en GitHub. Cada cambio entra por una rama y un pull request con la plantilla del proyecto, y lo aprueba alguien distinto de quien lo escribió. La tecla G muestra el QR del repositorio.

**Detalle (para el panel, no para la voz):**
El repositorio está en GitHub, en la cuenta del equipo
(`Darley843/Proyecto_BancoO`), y es público: se abre sin cuenta. Cada cambio va
en una rama propia y entra por un pull request que usa la plantilla
`.github/PULL_REQUEST_TEMPLATE.md`; lo aprueba alguien distinto de quien subió el
último commit. En la pantalla, la tecla **G** abre el panel de recursos con el QR
y el enlace del repositorio, y con los seis diagramas de Archify.

**Fuente:** `README.md` («Cómo contribuir»), `CONSTITUTION.md` §14 y
`.github/PULL_REQUEST_TEMPLATE.md`.

<a id="p19"></a>

### P19. ¿Qué es un token en git? ¿Usan tokens?

**Variantes:** tokens de GitHub, claves, secretos, tokens en el repositorio.

**Voz** (lo que dice Pana):

> Un token es una credencial, no un archivo del repositorio. Las claves van por variables de entorno y nunca se versionan; el único token es el del gateway local de OpenClaw. El repositorio no guarda secretos.

**Detalle (para el panel, no para la voz):**
Un token es una credencial de acceso, no un archivo que se guarde en el
repositorio. Las claves viajan por variables de entorno de la sesión, el proyecto
no lee `.env` y `make check` no las necesita. El único token del proyecto es el
del gateway local de OpenClaw, en `127.0.0.1`. El repositorio no contiene tokens
ni claves, y `.env.example` solo lista los nombres.

**Fuente:** `docs/SEGURIDAD.md` §4 (secretos), `AGENTS.md` (solo `uv` y sin
`.env`) y `.env.example`.

<a id="p20"></a>

### P20. ¿Cómo está organizado el código?

**Variantes:** explicar el código, qué hay en src, cómo se lee el proyecto.

**Voz** (lo que dice Pana):

> Está en capas: corpus Medallion, asistente, Bóveda, sucursal, canal, diagnóstico y escena. Cada módulo vive en su carpeta de src y tiene su prueba en test; el mapa completo está en el repositorio.

**Detalle (para el panel, no para la voz):**
`src/banco_occidente_corpus/` está en capas: `discover`/`fetch`/`extract`/`gold`
para el corpus Medallion; `asistente` para el RAG; `boveda` para fragmentos,
embeddings y Qdrant; `sucursal` para el grafo y la API; `canal` para WhatsApp;
`diagnostico` para el motor y el comité; `escena` para Pana y la pantalla; y
`tablero`, `pana`, `herramientas` y `mcp_servidor` como piezas de apoyo. Cada
módulo tiene su archivo en `test/`, y el mapa completo está en `AGENTS.md` y en
`docs/CODIGO.md`.

**Fuente:** `AGENTS.md` («Mapa del código») y `docs/CODIGO.md`.

<a id="p21"></a>

### P21. ¿Tienen un diagrama de arquitectura?

**Variantes:** ver los diagramas, cómo se conectan las piezas, cómo se ve la arquitectura.

**Voz** (lo que dice Pana):

> Sí. Arquitectura, flujo de datos, canal y diagnóstico son diagramas interactivos hechos con Archify, y la tecla G abre el panel con seis. El HTML sale de un JSON versionado; nadie lo edita a mano.

**Detalle (para el panel, no para la voz):**
Hay seis diagramas interactivos generados con Archify: `docs/arquitectura.html`
(arquitectura), `docs/datos.html` (flujo de datos), `docs/canal.html` (secuencia
del canal), `docs/diagnostico.html` (flujo del diagnóstico),
`docs/agente-openclaw.html` y `docs/despliegue-openclaw.html`. Cada uno tiene su
fuente `.json` versionada y su HTML se genera con `archify finalize`; nunca se
edita a mano. La app los sirve en `/diagramas/<nombre>.html` y el panel de
recursos (tecla **G**) enlaza los seis.

**Fuente:** `README.md` («Diagramas interactivos de la fase 2»),
`docs/DIAGRAMAS.md` y los `docs/*.json` versionados.

<a id="p22"></a>

### P22. ¿Cómo prueban el proyecto?

**Variantes:** pruebas automáticas, make check, integración continua, cómo evitan romper el código.

**Voz** (lo que dice Pana):

> Con pruebas automáticas que corren sin red: lint, tipos y pytest. make check corre las tres y debe quedar en verde antes de cada cambio; el pipeline de GitHub las repite en cada pull request.

**Detalle (para el panel, no para la voz):**
`make check` corre `ruff` (lint y formato), `ty` (tipos) y `pytest`. Las pruebas
no usan red: `test/conftest.py` bloquea cualquier conexión fuera de loopback y
los clientes de DeepSeek y Ollama se reemplazan por dobles. El pipeline de
GitHub (`.github/workflows/ci.yml`) repite `make check` en cada pull request, y
los hooks de `.pre-commit-config.yaml` lo revisan antes del commit.

**Fuente:** `AGENTS.md` («Verificación antes de dar algo por terminado»),
`pyproject.toml`, `test/conftest.py` y `.github/workflows/ci.yml`.

---

## Respuestas especiales (ya definidas en el documento de Pana anfitrión)

- **Karol G o Shakira:** respuesta fija con el guiño al profesor Jan.
- **Fuera de tema:** «No tengo información sobre eso. Puedo contarles sobre el
  proyecto, la tecnología que usamos, las decisiones del equipo, la actividad de
  hoy o los productos del banco.»
- **Datos personales en la pregunta:** «Prefiero no recibir datos personales aquí.»

## Pendiente antes de congelar (jueves 26)

1. Darley confirma su fila en P2.
2. Las voces de esta ficha pasan a `config/escena.toml [preguntas]` (tarea 6.14),
   con una prueba que revisa las 40 palabras, las tres frases, la fuente y las
   cifras declaradas.
3. Leer en voz alta cada voz con la voz de Pana (Gonzalo); todas duran menos de
   unos 15 segundos.
