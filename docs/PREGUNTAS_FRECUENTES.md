# Preguntas frecuentes sobre Sucursal 1965

Respuestas cortas a lo que suele preguntar un jurado o un invitado. Pana las usa
para responder sobre el proyecto: cada título es la pregunta como se haría en
voz alta y cada respuesta dice de dónde sale la cifra. Si una cifra cambia, se
actualiza aquí y en el documento que se cita.

## El proyecto

### ¿Qué problema resuelve el proyecto?

Muchos jóvenes piden su primer préstamo al gota a gota porque el banco les
parece lejano. Pana les muestra, con las tasas reales del Banco de Occidente,
cuánto pagarían en cada opción y si la cuota les cabe. Fuente: `README.md`.

### ¿Para quién es Pana? ¿Cuál es el público objetivo?

Para jóvenes que van a pedir su primer crédito y no saben si la cuota les cabe.
Pana les habla por WhatsApp, en lenguaje sencillo y sin juzgar. Fuente:
`README.md` («Entrega final»).

### ¿Qué es Pana?

Pana es el agente de la Sucursal 1965: un asistente que conversa por WhatsApp,
consulta las tasas publicadas, calcula un diagnóstico orientativo y compara el
banco con el gota a gota. Es orientación, nunca una aprobación de crédito.

### ¿Qué es Don Gota?

Don Gota es el prestamista gota a gota de la escena. No es un modelo de
lenguaje: sus cifras salen de una fórmula fija. Cobra el 20 % mensual, que
equivale a 791,61 % E.A. Fuente: `docs/DEMO_GOTA_A_GOTA.md`.

### ¿Cuánto más caro es el gota a gota que el banco?

Con $1.000.000 a 36 meses, Don Gota cobra 791,61 % E.A., 27,9 veces la usura
de 28,34 % E.A. Se pagarían $8.200.000 frente a $1.432.836 con el banco: casi 6
veces más. Fuente: `docs/DEMO_GOTA_A_GOTA.md`.

### ¿Por qué Pana no aprueba créditos?

Porque es un proyecto académico, no un canal del banco. Pana da una simulación
orientativa con rangos; la decisión final siempre es del banco, por sus canales
oficiales. El auditor bloquea cualquier frase que suene a aprobación.

### ¿Qué limitaciones tiene el proyecto?

Es una demo académica: no aprueba créditos, el número de WhatsApp es de prueba,
no recibe audios ni pagos y las tasas valen solo para su vigencia (noviembre de
2026). Fuente: `docs/OPERACION_WHATSAPP.md` («Limitaciones conocidas»).

### ¿Qué harían con más tiempo?

Pasar el token del gateway a un almacén de secretos, medir la latencia con
invitados reales, sumar notas de voz y un número verificado de producción.
Fuente: `docs/DESPLIEGUE.md` (secciones marcadas con ⏳).

## Arquitectura

### ¿Cuál es la arquitectura del sistema?

WhatsApp entrega el mensaje, por Meta, al canal en FastAPI, que pide
consentimiento y cambia el número por una huella. El agente Pana, en OpenClaw,
responde con las 20 herramientas del servidor MCP. Fuente: `README.md`.

### ¿Cómo llega un mensaje de WhatsApp hasta el agente?

Meta envía el mensaje firmado al webhook por el túnel de cloudflared. El canal
verifica la firma, revisa el consentimiento y pasa al agente solo el texto y la
huella, nunca el número. Fuente: `docs/DIAGRAMAS.md` (diagrama 1).

### ¿Qué es OpenClaw y por qué lo usaron?

OpenClaw es el gateway donde vive el agente Pana: guarda su identidad, sus
reglas y su memoria, y le da una API local con token. No es un segundo canal:
es el cerebro detrás del canal. Fuente: `docs/DESPLIEGUE.md` (sección 5).

### ¿Qué pasa si OpenClaw se cae?

El canal responde con el grafo de LangGraph que ya funcionaba: digiturno,
Bóveda, entrevista y tarjeta. El invitado siempre recibe respuesta. Fuente:
`docs/DIAGRAMAS.md` (diagrama 2).

### ¿Qué herramientas tiene el agente? ¿Cuántas herramientas tiene el MCP?

Veinte herramientas con esquema Pydantic: tasas, cuota, usura, diagnóstico,
«¿Y si…?», comité, Don Gota, negociación, ficha, consentimiento, asesor,
documentos, tarifas, clasificar y auditar. Fuente: `README.md` («Las 20
herramientas»).

### ¿Cómo funciona la memoria del agente?

Cada invitado tiene su propio hilo, identificado por la huella de su número.
OpenClaw guarda el contexto de la conversación; la memoria local nunca guarda
nombres, números ni montos de invitados. Fuente: `openclaw/README.md`.

### ¿Qué modelo de lenguaje usan? ¿Por qué eligieron DeepSeek?

DeepSeek V4.1 Flash (`deepseek-flash`), con DeepSeek V4 Pro como respaldo. Es
rápido y barato: 44 preguntas de evaluación costaron 0,0157 USD. Las cifras no
las inventa el modelo: salen de código. Fuente: `docs/RESULTADOS_FASE2.md`.

### ¿Cuánto cuesta cada conversación?

Muy poco: en la evaluación, 44 preguntas costaron 0,0157 USD en total, unos
0,0004 USD por pregunta. Las preguntas de tasas no usan el modelo y cuestan
cero. Fuente: `docs/RESULTADOS_FASE2.md` («Uso y costo»).

### ¿Cómo se despliega el proyecto?

Todo corre en un computador, solo en 127.0.0.1: la app con `make app`, el túnel
de cloudflared, el gateway de OpenClaw y el servidor MCP. La guía paso a paso
está en `docs/DESPLIEGUE.md`.

## Datos y conocimiento

### ¿Cómo funciona el RAG?

La Bóveda guarda 869 fragmentos del sitio del banco en Qdrant local. Cada
búsqueda es híbrida: vectores para el sentido y BM25 para nombres exactos, con
pesos 0,6 y 0,4. Cada respuesta cita su documento. Fuente: `docs/ARQUEO.md`.

### ¿Qué base vectorial usan? ¿Qué embeddings usan?

Qdrant en modo local, sin servidor aparte. Los embeddings son
`nomic-embed-text-v2-moe`, de 768 dimensiones, calculados con Ollama en el
mismo computador. Fuente: `README.md` («Bóveda»).

### ¿Cómo evaluaron la recuperación? ¿Cuál es el hit@5 y el nDCG?

Con 36 preguntas cuya fuente se conoce: hit@5 de 0,75, MRR de 0,58, recall@10
de 0,82 y nDCG@10 de 0,64. El híbrido gana a BM25 solo (0,75 frente a 0,53).
Fuente: `docs/ARQUEO.md`.

### ¿Qué muestra la proyección t-SNE?

Que los embeddings agrupan bien por sección: la confiabilidad es 0,95 y la
pureza de vecindario 0,66 (al azar sería 0,22). Explica por qué fallan las 9
preguntas que no aciertan. Fuente: `docs/PROYECCION.md`.

### ¿De dónde salen las tasas?

Del tarifario y las tasas que publica el Banco de Occidente, vigentes del 1 al
30 de noviembre de 2026, guardadas en `config/tasas.toml` y en el Tablero.
Cada tasa se responde con su fuente y su vigencia.

### ¿Cómo calculan la usura?

No la calculan: usan la tasa certificada por la Superintendencia Financiera,
28,34 % E.A. para consumo en noviembre de 2026 (Resolución 1707 de 2026),
guardada en `config/tasas.toml`.

## Confianza y seguridad

### ¿Cómo evitan que el agente invente cifras?

Toda cifra sale de una herramienta: el motor del diagnóstico, el Tablero o la
fórmula de Don Gota. El auditor revisa que cada número del texto exista en los
cálculos antes de enviarlo. Fuente: `docs/COMITE.md`.

### ¿Qué hace el auditor?

Revisa cada texto antes de salir: cifras sin respaldo, promesas de aprobación,
recomendar el gota a gota, datos personales y falta del aviso orientativo. Es
código, no solo un prompt. Fuente: `docs/DIAGRAMAS.md` (diagrama 5).

### ¿Cómo funciona el comité de crédito?

Solo se reúne en casos amarillos o rojos. Riesgo, comercial y auditor
deliberan una ronda, y gana la postura más prudente. El comité nunca cambia el
semáforo. Fuente: `docs/COMITE.md`.

### ¿Cómo protegen los datos personales? ¿Cómo cumplen la Ley 1581?

Antes de todo, Pana muestra el aviso de la Ley 1581 y espera «Acepto». El
número se cambia por una huella y nunca se guarda en logs. «Olvida mis datos»
borra todo. Fuente: `docs/SEGURIDAD.md`.

### ¿Cómo se protegen de la inyección de prompts?

Los documentos y mensajes son datos, no instrucciones. Un catálogo de ataques
se prueba contra el agente, y el auditor marca cualquier intento sin revelar
las instrucciones. Fuente: `docs/INYECCION.md` y `docs/ROBA_BOVEDA.md`.

## Equipo y calidad

### ¿Qué hizo cada integrante del equipo?

Nayla: OpenClaw, el workspace de Pana y la escena. Darley: el canal de
WhatsApp con Meta, el modo evento y el servidor MCP. Anny: RAG, evaluación y
seguridad. Yoldy: documentación, diagramas y pantalla de la escena.

### ¿Cuántas pruebas tiene el proyecto?

Más de 2.500 pruebas automáticas, que corren con `make check` sin internet,
sin DeepSeek y sin Ollama. Fuente: `CONSTITUTION.md`.

### ¿Qué licencia tiene el proyecto?

MIT, a nombre de los cuatro integrantes: Darley Idárraga, Nayla Ledesma, Anny
Valencia y Yoldy Benavides. El contenido del sitio del banco pertenece a sus
titulares. Fuente: `LICENSE`.
