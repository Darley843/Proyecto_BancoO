# Pana anfitrión: preguntas probables y respuestas fijas

Ficha del presentador para la tarea 6.13 del cambio `demo-gota-a-gota` y fuente
única de las respuestas fijas: la usan el endpoint `POST /api/escena/pregunta` y la
ficha corta de la pantalla. Son las preguntas que más probablemente hará el
profesor en la sustentación del viernes 27, con una respuesta fija y revisada para
cada una. Si la pregunta del público coincide con
una de estas, Pana responde con el texto fijo (`origen: "reglas"`). Si no
coincide, la responde el recuperador del proyecto con el modelo (`origen: "llm"`).

Reglas de redacción, iguales a las del documento de Pana anfitrión:

- Español, tuteo y como mucho tres frases: la respuesta se dice en voz alta.
- Sin códigos internos ni nombres de archivo. Las cifras se escriben como se
  dicen.
- Cada respuesta tiene su fuente en el repositorio, para revisarla antes de
  congelar.
- Nada de promesas: Pana no aprueba créditos y lo dice.

Las marcas **⚠️ Confirmar** señalan lo que el equipo tiene que validar antes de
usar la respuesta en vivo.

---

## A. El proyecto

### P1. ¿Qué es este proyecto? / ¿Qué es la Sucursal 1965?

**Variantes:** de qué se trata, qué hicieron, qué es Pana, qué es la Sucursal.

**Respuesta:**
Somos un asistente del Banco de Occidente construido solo con su información
pública: el sitio web, sus documentos y sus videos, siempre citando la fuente.
Responde preguntas por la web y por WhatsApp, y orienta a jóvenes que van a pedir
su primer crédito con un diagnóstico de semáforo. Se llama Sucursal 1965 porque el
banco nació en Cali en 1965.

**Fuente:** `README.md` («Problema y solución»); el año sale del fragmento de
*Nuestro Banco* en la Bóveda.

### P2. ¿Quiénes son y qué hizo cada uno?

**Variantes:** quién hizo qué, el equipo, los integrantes.

**Respuesta:**
Somos cuatro. Nayla hizo la Ventanilla y la Bóveda, y en la escena a Don Gota, la
comparación y la negociación; Darley, el canal de WhatsApp, el asesor y la entrada
por voz; Anny, la evaluación, la seguridad, Roba la Bóveda y el auditor; y Yoldy, la
pantalla, las voces, el Tablero y la operación. Todo cambio lo revisa otra persona
del equipo antes de entrar.

**Detalle (para el panel, no para la voz):**

| Quién | Sucursal 1965 | Escena «Pana vs. el gota a gota» |
|---|---|---|
| Nayla | Ventanilla y Bóveda | Don Gota, comparación con el motor y negociación |
| Darley | Canal de WhatsApp y HITL | Entrada por voz, voluntario y API de la escena |
| Anny | Evaluación, seguridad y Roba la Bóveda | Auditor, perfiles seguros y plan B |
| Yoldy | Frontend, Tablero, mapa y operación/latencia | Pantalla, voces, retratos y Pana anfitrión |

**Fuente:** propuesta del equipo (22 nov); `openspec/changes/demo-gota-a-gota/tasks.md`.
**⚠️ Confirmar:** que cada quien corrija su parte.

### P3. ¿Usaron inteligencia artificial para programarlo?

**Variantes:** lo hizo una IA, usaron ChatGPT, usaron agentes, quién escribió el
código.

**Respuesta:**
Sí, como asistente, y lo decimos abiertamente. Cada cambio empieza en una
especificación de OpenSpec, pasa por pruebas automáticas y por la revisión de GGA,
y otra persona del equipo lo aprueba antes de entrar a main. La IA acelera; las
decisiones y la revisión son nuestras.

**Fuente:** propuesta del equipo (22 nov); `AGENTS.md`, `.pre-commit-config.yaml`
(revisión GGA) y `CONSTITUTION.md` §14 (protección de `main`: un PR con una
aprobación de alguien distinto a quien subió el cambio).

---

## B. Decisiones técnicas

### P4. ¿Por qué eligieron Qdrant?

**Variantes:** base vectorial, por qué no Chroma, dónde guardan los vectores.

**Respuesta:**
El módulo 2 pedía una base vectorial con colección, metadatos y filtros, y Qdrant
lo cumple corriendo dentro del mismo programa, sin un servidor aparte. Todo queda
en el computador: los textos del banco no salen a ningún servicio. Empezamos con
Chroma y lo dejamos como opción de compatibilidad.

**Fuente:** `CONSTITUTION.md` §11, decisión del 13 de noviembre de 2026.

### P5. ¿Por qué DeepSeek?

**Variantes:** qué modelo usan, por qué no OpenAI, cuánto cuesta.

**Respuesta:**
Por costo: un comité de crédito cuesta alrededor de un centavo de dólar y la app
tiene un tope de veinte centavos al día. Además se integra directo con LangChain y
es el mismo modelo que usamos en OpenCode, así que ya lo conocíamos. Y solo
redacta: las cifras salen del motor y de las tasas del banco, no del modelo.

**Fuente:** propuesta del equipo (22 nov); `CONSTITUTION.md` §3 y §11 (embeddings
locales: «solo DeepSeek se paga»); `docs/LISTA_DEMO.md` («DeepSeek»: un comité
cuesta alrededor de un centavo y el tope diario es de US$ 0,20).

### P6. ¿Cómo saben que la búsqueda funciona bien?

**Variantes:** cómo lo evaluaron, qué tan preciso es, métricas, el Arqueo.

**Respuesta:**
Lo medimos con 36 preguntas cuya respuesta correcta conocemos: la búsqueda híbrida
encuentra la fuente correcta entre los cinco primeros resultados en 27 de las 36,
y solo con palabras clave en 19. Con 36 preguntas el margen de error es amplio, y
por eso lo reportamos con su intervalo de confianza y no como una cifra exacta.

**Fuente:** `docs/ARQUEO.md` y `data/evaluacion/arqueo.json` (hit@5 0,75 = 27/36
con 0,6/0,4 y con 1/0; 0,53 = 19/36 con 0/1; intervalo de Wilson).

### P7. ¿Cómo evitan que responda cualquier cosa?

**Variantes:** preguntas fuera de tema, alucinaciones, el filtro, el Digiturno.

**Respuesta:**
Cada pregunta pasa primero por reglas fijas que deciden si es del banco, de
tarifas, de diagnóstico o de otro tema, y el modelo solo decide los casos dudosos.
En una prueba con cincuenta preguntas fuera de tema, ninguna se coló. Además,
cada respuesta debe citar su fuente, y si no la encuentra, lo dice.

**Fuente:** `CONSTITUTION.md` §11 (Digiturno: reglas antes que modelo, decisión del
17 de noviembre de 2026); `docs/ARQUEO.md` («Filtro de dominio»: fuga 0 de 50 en
las tres corridas con el modelo).

### P8. ¿Por qué las voces de Piper y de Edge?

**Variantes:** de dónde salen las voces, por qué esa voz, es una voz real.

**Respuesta:**
Piper genera las voces en el computador, sin internet y sin enviar el texto a
nadie, así que siempre funciona. Para Pana usamos una voz colombiana de Microsoft
Edge, más natural, que sí necesita internet; si se cae la red, vuelve sola a su
voz de Piper. Y si no hay sonido, la escena sigue con subtítulos.

**Fuente:** `docs/VOZ.md`; arreglos de los PR #171 y #177.

---

## C. Crédito, datos y seguridad

### P9. ¿El sistema aprueba créditos?

**Variantes:** me van a prestar, es una aprobación, sirve para pedir un crédito.

**Respuesta:**
No. El diagnóstico es orientativo: dice si la cuota te cabe en el bolsillo con los
datos que diste, pero no consulta tu historial ni decide por el banco. La decisión
real siempre es del banco, con su propio estudio.

**Fuente:** `docs/COMITE.md` («Por qué es orientativo»; el historial crediticio
no se usa) y `docs/DIAGNOSTICO.md`.

### P10. ¿Cómo se calcula el semáforo?

**Variantes:** verde, amarillo y rojo, qué significa cada color, los umbrales.

**Respuesta:**
Comparamos tus cuotas con tus ingresos. Si se llevan hasta el 30 % es verde, entre
30 y 40 % es amarillo, y por encima del 40 %, o si los gastos ya superan los
ingresos, es rojo. Esos límites son política del proyecto, porque la norma de la
Superfinanciera deja que cada entidad fije los suyos.

**Fuente:** `docs/DIAGNOSTICO.md` (umbrales `verde_hasta` 0,30 y
`amarillo_hasta` 0,40) y `docs/COMITE.md` («Marco normativo», CBF 1.1.2.20).

### P11. ¿Qué hace el comité de crédito?

**Variantes:** los tres agentes, riesgo y comercial, por qué varios agentes.

**Respuesta:**
Cuando el resultado es amarillo o rojo, tres agentes deliberan: Riesgo, Comercial
y un Auditor que revisa a los otros dos. El semáforo nunca cambia, y se queda la
recomendación más prudente. Ninguno puede inventar cifras: solo usan los
escenarios que el motor ya calculó.

**Fuente:** `docs/COMITE.md` («Los tres agentes» y «Síntesis»).

### P12. ¿Qué hace el auditor?

**Variantes:** para qué sirve el auditor, quién revisa las cifras.

**Respuesta:**
El auditor revisa cada intervención: que toda cifra exista y tenga fuente, que
nadie prometa una aprobación, que nadie recomiende el gota a gota y que no
aparezcan datos personales. Su veredicto es conforme, con observaciones u objeta,
sin colores, para no confundirlo con el semáforo del crédito. Si objeta, la escena
no termina en verde.

**Fuente:** `openspec/changes/demo-gota-a-gota/tasks.md` (4.2, 4.3 y 7.4) y
`docs/COMITE.md` («Auditor»).
**⚠️ Confirmar:** cuando la sección 4 de la escena esté implementada.

### P13. ¿Cómo protegen los datos personales?

**Variantes:** Ley 1581, privacidad, guardan mi número, habeas data.

**Respuesta:**
Antes de empezar pedimos autorización con el aviso de la Ley 1581, y no guardamos
el número: lo convertimos en un código que no se puede revertir. Los datos
personales se bloquean antes de llegar al modelo, y basta escribir «olvida mis
datos» para borrar todo. Todo lo que hoy se usa en la escena es inventado.

**Fuente:** `docs/SEGURIDAD.md`, `docs/OPERACION_WHATSAPP.md` y
`CONSTITUTION.md` §13; la revocación la comprueba `make simular` (9.3).

### P14. ¿Qué pasa si el resultado es rojo?

**Variantes:** el asesor, me llama alguien, el caso, el HITL.

**Respuesta:**
Pana te ofrece hablar con un asesor y tú decides si pulsas Contactar o Descartar.
Si contactas, se abre un caso que el asesor ve en la vista de Operación. Como es un
proyecto académico, el banco real no recibe estos casos.

**Fuente:** `docs/LISTA_DEMO.md` (pasos 9 y 14) y `docs/COMITE.md` («Síntesis»,
punto 4).

---

## D. La actividad

### P15. ¿Qué es el gota a gota y por qué lo muestran?

**Variantes:** Don Gota, préstamo informal, usura, por qué es peligroso.

**Respuesta:**
Es un préstamo informal que cobra el 20 % cada mes: por un millón pagas cuarenta
mil diarios, y si renuevas durante tres años terminas pagando 8,2 millones, casi
seis veces lo que pagarías con el banco. Su tasa, de casi 800 % efectivo anual, es
unas 28 veces la de usura, y cobrar por encima de la usura es delito en Colombia.
Lo mostramos para que se vea, con cifras, lo que cuesta lo fácil.

**Fuente:** `openspec/changes/demo-gota-a-gota/tasks.md` (2.1: interés de
$200.000 por ciclo, cuota diaria de $40.000, total de $8.200.000 en 36 meses y
791,61 % E.A.; 2.3 y 2.4: artículo 305 del Código Penal); PR #174 (8,2 millones
frente a 1,4 con el banco y 27,9 veces la usura).
**⚠️ Confirmar:** con `config/escena.toml` cuando esté (la tasa del gota se
configura ahí).

### P16. ¿Por qué Don Gota no es una inteligencia artificial?

**Variantes:** el villano, por qué está guionado.

**Respuesta:**
A propósito: no queremos que un modelo de lenguaje escriba jamás un discurso a
favor del gota a gota, ni por error. Don Gota dice frases fijas y sus cifras salen
de una fórmula, así que siempre dice lo mismo y siempre cuadra. Los demás
personajes sí son agentes.

**Fuente:** `openspec/changes/demo-gota-a-gota/tasks.md` (2.2: ningún turno de Don
Gota tiene `origen="llm"`).

### P17. ¿Qué pasa si algo falla en vivo?

**Variantes:** se cae internet, falla DeepSeek, plan B.

**Respuesta:**
Cada pieza tiene un respaldo: sin DeepSeek la app responde en modo demo, sin
internet las voces vuelven a Piper y, sin sonido, la escena sigue con subtítulos.
Si la negociación se cae, pasamos a una versión corta de la escena ya calculada.
Lo ensayamos en el computador de la demo.

**Fuente:** `docs/LISTA_DEMO.md` §4 y `openspec/changes/demo-gota-a-gota/tasks.md`
(7.5: completa → núcleo → solo subtítulos → perfil seguro → JSON proyectado).

---

## Respuestas especiales (ya definidas en el documento de Pana anfitrión)

- **Karol G o Shakira:** respuesta fija con el guiño al profesor Jan.
- **Fuera de tema:** «No tengo información sobre eso. Puedo contarles sobre el
  proyecto, la tecnología que usamos, las decisiones del equipo o la actividad de
  hoy.»
- **Datos personales en la pregunta:** «Prefiero no recibir datos personales aquí.»

## Pendiente antes de congelar (jueves 26)

1. Cada quien corrige su parte en P2.
2. Las cifras de P15 se comparan con la salida de `make escena-proyectada`.
3. Leer en voz alta cada respuesta con la voz de Pana (Gonzalo) y recortar la que
   pase de unos 15 segundos.
