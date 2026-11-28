# Pana anfitrión: preguntas probables y respuestas fijas

Ficha del presentador para la tarea 6.13 del cambio `demo-gota-a-gota` y fuente
única de las respuestas fijas: la usan el endpoint `POST /api/escena/pregunta` y la
ficha corta de la pantalla, y de aquí salen las entradas de
`config/escena.toml [preguntas]` (tarea 6.14). Son las preguntas que más
probablemente hará el profesor o un invitado en la sustentación del **sábado 28**.

Cada pregunta tiene dos textos:

- **Voz:** la respuesta fija que dice Pana. Si la pregunta del público coincide
  con una de estas, Pana la dice tal cual (`origen: "guion_fijo"`), con la línea
  `Fuente:` que apunta al ancla de esta ficha (`docs/PRESENTADOR.md#p1` a `#p32`).
  Entre dos y cuatro frases y máximo 100 palabras contando esa línea, como exige
  la 6.14.
- **Detalle:** la versión larga, para el panel de la pantalla y para quien
  presenta. No se dice en voz alta.

Si la pregunta no coincide, la responde el recuperador del proyecto con el modelo
(`origen: "llm"`); el rechazo y el respaldo usan `origen: "reglas"`.

Reglas de redacción, iguales a las del documento de Pana anfitrión:

- Español, tuteo y, en la voz, entre dos y cuatro frases y máximo 100 palabras.
- Sin códigos internos ni nombres de archivo. Las cifras se escriben como se
  dicen.
- Cada respuesta tiene su fuente en el repositorio, para revisarla antes de
  congelar.
- Nada de promesas: Pana no aprueba créditos y lo dice.

Las marcas **⚠️ Confirmar** señalan lo que el equipo tiene que validar antes de
usar la respuesta en vivo.

---

## Cómo abrir la actividad

Al terminar la presentación, la pantalla deja el QR y la convocatoria. Quien
presenta dice:

> **«Primero escanea nuestro voluntario; los demás, en un momento.»**

El primero que escanee y escriba **Acepto** (o cualquier mensaje, si ya aceptó
la Ley 1581) queda como voluntario sin código y sale en la pantalla. Los demás
siguen conversando con Pana por WhatsApp como invitados: sus mensajes no se
publican y reciben una sola vez el aviso de que el voluntario ya está en el
escenario.

**Riesgo de que alguien se adelante.** Si la persona que escanea primero no es
la que debe salir, quien presenta pulsa **L**: la pantalla libera al voluntario,
vuelve al QR y abre una convocatoria nueva. La persona liberada sigue
conversando por WhatsApp como invitada. No se pide un nombre ni se dicta ningún
código; el respaldo con `ESCENA` y el código de la tarjeta queda solo para el
voluntario si la API de la convocatoria falla.

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
**Fila de Darley confirmada** (26 de noviembre): la entrada por voz (tecla V), el
voluntario y la API de la escena entran en el #232. La escena mantiene al
voluntario por voz (tecla V, opción B), como anuncia la presentación de Pana
(#205).

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

## F. Preguntas técnicas del jurado

<a id="p23"></a>

### P23. ¿Qué modelo usa el agente en producción?

**Variantes:** qué modelo usa el agente en producción, qué modelo usa Pana en producción, cuál es el modelo principal y el alternativo, qué modelo de lenguaje usa el agente.

**Voz** (lo que dice Pana):

> El agente usa DeepSeek Flash como modelo principal y DeepSeek Pro como respaldo, con el razonamiento extendido apagado para bajar la latencia. Lo elegimos por costo: medimos entre 0,1 y 0,2 centavos de dólar por mensaje, y se integra directo con LangChain. Ollama no redacta: solo calcula los embeddings locales de la Bóveda.

**Detalle (para el panel, no para la voz):**
`openclaw/openclaw.json` declara `deepseek/deepseek-flash` como principal y
`deepseek/deepseek-v4-pro` como respaldo, con `thinkingDefault: "off"`. La
medición de costo por mensaje está en `docs/PRESENTADOR.md` (P5) y los
embeddings locales de Ollama, en `README.md`.

**Fuente:** `openclaw/openclaw.json`, `docs/PRESENTADOR.md#p5` y `README.md`.

<a id="p24"></a>

### P24. ¿Cómo es la arquitectura del proyecto?

**Variantes:** cómo es la arquitectura del proyecto, cómo es la arquitectura del sistema, explícame la arquitectura y qué recorrido hace un mensaje de WhatsApp hasta la respuesta.

**Voz** (lo que dice Pana):

> El mensaje entra por WhatsApp a Meta, pasa al canal FastAPI que verifica la firma, el consentimiento, la huella del número, los comandos y los cupos, y de ahí al gateway local de OpenClaw con el agente Pana y su workspace. Pana usa el servidor MCP propio, con sus veinte herramientas tipadas, que llaman a los módulos de diagnóstico, Tablero de tasas, RAG y escena. El auditor revisa la respuesta antes de enviarla y, si el gateway falla, el canal responde con el grafo de los módulos anteriores.

**Detalle (para el panel, no para la voz):**
El recorrido completo está en `docs/AGENTE_OPENCLAW.md` §2 y §4.1: Meta,
webhook con firma, cola, despachador, gateway en loopback, MCP en loopback y
respaldo con el grafo de LangGraph.

**Fuente:** `docs/AGENTE_OPENCLAW.md`.

<a id="p25"></a>

### P25. ¿Qué es OpenClaw y qué es el MCP?

**Variantes:** qué es OpenClaw y qué es el MCP, por qué separaron OpenClaw del MCP, diferencia entre OpenClaw y el servidor MCP.

**Voz** (lo que dice Pana):

> OpenClaw es el gateway y el runtime del agente Pana: recibe el turno, conversa y decide qué herramienta usar. El MCP es el protocolo con el que ese agente llama a nuestro servidor local de veinte herramientas tipadas, que son las que calculan y consultan los datos. Los separamos para que el agente no pueda ejecutar comandos ni tocar archivos: el gateway solo conversa y el MCP solo expone herramientas cerradas, en loopback y con token.

**Detalle (para el panel, no para la voz):**
El gateway y el servidor MCP son procesos distintos, ambos en loopback y con
token. El gateway no ejecuta ni sale del workspace; el MCP solo publica las
veinte herramientas del catálogo. Ver `docs/AGENTE_OPENCLAW.md` §2 y §6.

**Fuente:** `docs/AGENTE_OPENCLAW.md`.

<a id="p26"></a>

### P26. ¿Cuántas herramientas tiene y cómo evitan que alucine?

**Variantes:** cuántas herramientas tiene, cómo decide qué herramienta usar, cómo controlan la alucinación, cómo evitan que invente cifras.

**Voz** (lo que dice Pana):

> Pana tiene veinte herramientas y elige entre ellas por el nombre y la descripción del esquema; no ve ninguna otra. La lista es cerrada por el filtro del gateway y cada entrada es un esquema Pydantic que rechaza campos extra. La entrevista la conduce la herramienta de diagnóstico, que devuelve la pregunta y las opciones, y las cifras salen del código o del Tablero, nunca del modelo. El auditor revisa el texto antes de enviarlo.

**Detalle (para el panel, no para la voz):**
Las veinte herramientas y las seis defensas están en `docs/HERRAMIENTAS.md`
(«Control de la alucinación»). El catálogo cerrado y los esquemas Pydantic, en
`docs/AGENTE_OPENCLAW.md` §3 y §6.

**Fuente:** `docs/HERRAMIENTAS.md`.

<a id="p27"></a>

### P27. ¿De dónde sale la información del RAG y cómo lo evaluaron?

**Variantes:** de dónde sale la información del RAG, cómo funciona el RAG, qué evalúan del RAG, cuánto da recall@10 y nDCG@10, qué muestra la proyección t-SNE, de donde sale la informacion del RAG.

**Voz** (lo que dice Pana):

> La Bóveda sale del sitio público del banco: guardamos el texto en Gold y lo indexamos en Qdrant local, con embeddings que calcula Ollama. Cada búsqueda es híbrida, vectores para el sentido y BM25 para los nombres exactos, y cada respuesta cita el documento del fragmento. Con 36 preguntas de fuente conocida medimos recall@10 de 0,82 y nDCG@10 de 0,64; la proyección t-SNE salió confiable en 0,95 y con pureza de vecindario de 0,66.

**Detalle (para el panel, no para la voz):**
`docs/ARQUEO.md` publica recall@10 0,82 y nDCG@10 0,64 con los pesos por
defecto; `docs/PROYECCION.md` publica confiabilidad 0,95 y pureza de vecindario
0,66 (al azar, 0,22).

**Fuente:** `docs/ARQUEO.md` y `docs/PROYECCION.md`.

<a id="p28"></a>

### P28. ¿Cómo funciona la memoria del agente?

**Variantes:** cómo funciona la memoria del agente, qué guardan en la memoria, qué no guardan de los invitados, dónde está la memoria de largo plazo.

**Voz** (lo que dice Pana):

> Cada persona tiene su hilo de corto plazo en OpenClaw, identificado por la huella HMAC de su número, y ese hilo no guarda el número. El largo plazo vive en MEMORY.md y en la bitácora diaria del workspace, que son locales y no se versionan. No guardamos nombres, teléfonos, montos, deudas ni textos de invitados; al cerrar el evento se borran las sesiones, la memoria y la bitácora.

**Detalle (para el panel, no para la voz):**
El workspace, `MEMORY.md` y la bitácora están en `openclaw/README.md`; el
borrado del evento, en `docs/AGENTE_OPENCLAW.md` §9.

**Fuente:** `openclaw/README.md` y `docs/AGENTE_OPENCLAW.md`.

<a id="p29"></a>

### P29. ¿Cómo protegen el agente?

**Variantes:** cómo protegen el agente, qué herramientas tiene bloqueadas, cómo va la evaluación de inyección, qué publica el túnel, cómo prueban la seguridad, como protegen el agente.

**Voz** (lo que dice Pana):

> Pana tiene bloqueadas la ejecución de comandos, el sistema de archivos, el navegador y el envío de mensajes, y el espacio de trabajo está limitado con workspaceOnly. La auditoría de OpenClaw dio cero hallazgos críticos y dos advertencias justificadas. En la evaluación de inyección, quince ataques se repitieron en nueve corridas: la mejor llegó a quince de quince y las demás quedaron entre once y quince, porque el modelo varía. El túnel solo publica el webhook y la salud, y al cerrar el evento se borran las sesiones y la memoria.

**Detalle (para el panel, no para la voz):**
La lista de herramientas bloqueadas y `workspaceOnly` están en
`docs/HERRAMIENTAS.md`; el resultado de inyección y su variabilidad, en
`docs/INYECCION.md`; la superficie del túnel y el borrado, en
`docs/SEGURIDAD.md` y `docs/AGENTE_OPENCLAW.md` §9.

**Fuente:** `docs/HERRAMIENTAS.md`, `docs/INYECCION.md` y `docs/SEGURIDAD.md`.

<a id="p30"></a>

### P30. ¿Cuánto cuesta un mensaje y cuánto tarda?

**Variantes:** cuánto cuesta un mensaje con OpenClaw, cuánto tarda una respuesta, por qué tarda, cuánto cuesta la jornada del evento.

**Voz** (lo que dice Pana):

> Cada mensaje con OpenClaw cuesta entre 0,1 y 0,2 centavos de dólar, y el tope de 300 mensajes del modo evento deja la jornada en menos de un dólar. Una respuesta con herramientas tarda unos 9 segundos. Tarda porque el modelo decide, llama una o varias herramientas locales, espera la auditoría y solo entonces el canal envía por WhatsApp; el razonamiento extendido está apagado para no sumar más espera.

**Detalle (para el panel, no para la voz):**
El costo por mensaje y el tope de 300 están en `docs/PRESENTADOR.md` (P5) y
`docs/DESPLIEGUE_WHATSAPP.md` §8.2; los «unos 9 s» de una respuesta con
herramientas, en `docs/INYECCION.md`.

**Fuente:** `docs/PRESENTADOR.md`, `docs/DESPLIEGUE_WHATSAPP.md` y `docs/INYECCION.md`.

<a id="p31"></a>

### P31. ¿Cómo se conecta con WhatsApp?

**Variantes:** cómo se conecta con WhatsApp, cómo verifican el número del bot, cómo funciona el modo evento, cómo piden el consentimiento por WhatsApp.

**Voz** (lo que dice Pana):

> El número del bot se registra y se verifica en Meta, y el webhook recibe los mensajes con la firma verificada. En el modo evento, cualquier número dentro de la ventana recibe primero el aviso de la Ley 1581 y no se procesa nada sin un Acepto explícito. La ventana es de 08:00 a 20:00, con 30 mensajes por hora y 40 en total por persona, y un tope global de 300.

**Detalle (para el panel, no para la voz):**
La verificación del número está en `docs/DESPLIEGUE_WHATSAPP.md` §4.2; el
modo evento y sus cuotas, en §8.

**Fuente:** `docs/DESPLIEGUE_WHATSAPP.md`.

<a id="p32"></a>

### P32. ¿Cómo funciona la escena en vivo?

**Variantes:** cómo funciona la escena en vivo, cómo hablan los personajes, de dónde salen las cifras de la escena, quién habla en la escena.

**Voz** (lo que dice Pana):

> En la escena en vivo hablan Pana, Don Gota, el joven, los dos agentes de la negociación y el auditor. Cada uno tiene su voz y su turno, y la pantalla pinta lo que recibe; el invitado escribe por WhatsApp y aparece solo en subtítulos. Las cifras de la escena salen de las herramientas, no del modelo: el motor del diagnóstico, la fórmula del gota a gota y el Tablero.

**Detalle (para el panel, no para la voz):**
Los personajes, los turnos y la publicación desde las herramientas están en
`docs/ESCENA_EN_VIVO.md` §3 y §8.

**Fuente:** `docs/ESCENA_EN_VIVO.md`.

---

## Respuestas especiales (ya definidas en el documento de Pana anfitrión)

- **Karol G o Shakira:** respuesta fija con el guiño al profesor Jan.
- **Fuera de tema:** «No tengo información sobre eso. Puedo contarles sobre el
  proyecto, la tecnología que usamos, las decisiones del equipo, la actividad de
  hoy o los productos del banco.»
- **Datos personales en la pregunta:** «Prefiero no recibir datos personales aquí.»

## Pendiente antes de congelar (jueves 26)

1. Las voces de esta ficha pasan a `config/escena.toml [preguntas]` (tarea 6.14),
   con una prueba que revisa las 100 palabras, las cuatro frases, la fuente y las
   cifras declaradas.
2. Leer en voz alta cada voz con la voz de Pana (Gonzalo); todas duran menos de
   unos 15 segundos.
