# Modelado: Módulo 1 y propuesta para el Módulo 2

Este documento alimenta la sección **Modelado** del informe. Separa lo que ya
está implementado (Módulo 1) de lo que el grupo propone para el Módulo 2, donde
el asistente pasa de "todo el contexto en el prompt" a recuperación (RAG).

> Estado: la parte del Módulo 2 es una **propuesta para que el grupo la
> confirme**. No hay código de embeddings ni base vectorial en el repositorio.

## 1. Módulo 1 (implementado)

| Pieza | Elección | Dónde |
|---|---|---|
| Fuente | Sitio oficial, capturado respetando `robots.txt`, 1,5 s entre peticiones y header `From` | `docs/FUENTES.md` |
| Limpieza | Bronze → Silver (texto útil, sin boilerplate) → Gold (Markdown + frontmatter) | `CONSTITUTION.md` §7 |
| Conocimiento consolidado | `data/contexto/contexto_banco.md`: 191 páginas, ~167 000 tokens estimados | `make contexto` |
| LLM | DeepSeek Flash (`deepseek-flash`) por API, orquestado con LangChain (`ChatDeepSeek`) | `asistente/modelo.py` |
| Estrategia | Contexto completo en el mensaje de sistema, temperatura 0, prompt versionado | `config/prompts/qa_v1.md` |
| Control de alucinaciones | Frase fija si no hay dato, cita obligatoria de fuente, validación de cifras, URL y PII | `asistente/validacion.py` |
| Evaluación | 20 preguntas del alcance con `make evaluar` | `docs/RESULTADOS_20_PREGUNTAS.md` |

El costo de esta estrategia es que cada pregunta envía unos 187 000 tokens de
entrada. La caché del proveedor cubre más del 99 % desde la segunda llamada
(`docs/EXPERIMENTOS_PROMPTS.md`), pero el contexto no puede crecer: ya está
cerca del tope de 175 000 tokens del manifest y deja fuera los PDF y los videos.

## 2. Segmentación (chunking)

`make chunks` corta cada documento de Gold por sus encabezados Markdown
(`##` es frontera de chunk, contrato de Gold) y descarta trozos de menos de 40
caracteres. Cada chunk conserva `url`, `section`, `heading` y un `chunk_id`
estable derivado del contenido.

| Archivo | Contenido | Tamaño | Versionado |
|---|---|---:|---|
| `data/knowledge/chunks_web.jsonl` | 1 388 chunks de las 181 páginas web (~162 000 tokens) | 1,2 MB | Sí |
| `data/knowledge/chunks.jsonl` | 14 490 chunks: páginas, PDF y videos (~9 millones de tokens) | 43 MB | No (se regenera) |

Limitación observada: algunos chunks arrancan con restos del menú del sitio
(por ejemplo "Canales digitales / Segmentos / Mesa de dinero"). Antes de
indexar conviene filtrar esas líneas con el mismo detector de líneas comunes que
usa la capa Contexto, para que no dominen la similitud.

## 3. Propuesta para el Módulo 2

### Modelo de embeddings

**Propuesta: `intfloat/multilingual-e5-base`**, local, con `sentence-transformers`.

- Está entrenado para recuperación en varios idiomas, incluido el español, y
  es pequeño (~280 M de parámetros): corre en CPU para ~15 000 chunks.
- Es local y gratuito: no envía el corpus a otro proveedor y no depende de que
  el proveedor del LLM ofrezca embeddings.
- Requiere los prefijos `query:` y `passage:` al codificar preguntas y chunks.

Alternativas a comparar con las mismas 20 preguntas:

| Modelo | A favor | En contra |
|---|---|---|
| `BAAI/bge-m3` | Muy bueno en multilingüe, admite textos largos (8 192 tokens) | Más pesado (~570 M); más lento en CPU |
| `paraphrase-multilingual-MiniLM-L12-v2` | Muy liviano y rápido | Menor calidad en recuperación |
| Embeddings por API (por ejemplo OpenAI `text-embedding-3-small`) | Sin cómputo local | Costo por token y el corpus sale a un tercero |

### Base de datos vectorial

**Propuesta: Chroma** (`langchain-chroma`), persistida en `data/vectorial/`.

- Corre embebida en el mismo proceso, sin servidor, y persiste en disco.
- Guarda los metadatos de cada chunk (`url`, `section`, `heading`), así que el
  asistente puede seguir citando la fuente y filtrar por sección.
- Se integra con LangChain, que el proyecto ya usa.

Alternativa: **FAISS**, más rápido en búsquedas puras, pero sin metadatos ni
persistencia propios; habría que guardarlos aparte.

La base vectorial es un derivado, como `chunks.jsonl`: no se versiona y se
regenera desde `chunks_web.jsonl` (o `chunks.jsonl` si se incluyen los PDF).

### LLM del Módulo 2

**Se mantiene DeepSeek Flash**, con el mismo prompt `qa_v1` y la misma
validación. Lo que cambia es el contexto: en lugar del corpus completo se
envían los *k* chunks más parecidos a la pregunta (propuesta inicial: *k* = 6,
unos 3 000 a 5 000 tokens), cada uno con su URL para que la cita siga siendo
verificable. Eso baja el costo por pregunta en más de 30 veces y permite sumar
los PDF y los videos al conocimiento.

Pendiente de confirmar con el profesor que DeepSeek por API es válido (la guía
da como ejemplos Ollama o modelos privados como GPT o Gemini).

### Cómo se compara

1. Correr `make evaluar` con la estrategia actual (contexto completo).
2. Implementar la recuperación y correr `make evaluar` con las mismas 20
   preguntas.
3. Comparar aciertos, falsos negativos, tokens de entrada y latencia.

## 4. Diseño del prompt (resumen)

Ver `config/prompts/qa_v1.md` y `docs/EXPERIMENTOS_PROMPTS.md`. Las decisiones
clave son: contexto entre `<contexto>` al inicio (aprovecha la caché), reglas
después del contexto y repetidas en `<reglas_clave>` junto a la pregunta, frase
fija cuando no hay dato, cita obligatoria de la fuente y validación posterior
que reemplaza cualquier respuesta sin cita, con cifras que no están en el
contexto o con datos personales.
