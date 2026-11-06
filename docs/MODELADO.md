# Modelado: Módulo 1 y propuesta para el Módulo 2

Este documento alimenta la sección **Modelado** del informe. Separa lo que ya
está implementado (Módulo 1) de lo que el grupo propone para el Módulo 2, donde
el asistente pasa de "todo el contexto en el prompt" a recuperación (RAG).

> Estado: la Bóveda del Módulo 2 ya está implementada (fragmentos, embeddings
> locales, índice Chroma y mapa); el recuperador híbrido y el grafo llegan en los
> PR siguientes del cambio `sucursal-1965`.

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
(por ejemplo "Canales digitales / Segmentos / Mesa de dinero"). La Bóveda los
descarta al construir fragmentos con `dedupe.is_noise` y con la detección de
líneas repetidas entre páginas web (`boveda/fragmentos.py`), de modo que ese
ruido no compite por similitud en el índice.

## 3. Módulo 2 (implementado en la Bóveda)

| Pieza | Elección | Dónde |
|---|---|---|
| Fragmentos | 957 fragmentos (878 de páginas, 81 de PDF y 6 hechos); fusión hasta 80 tokens, límite de 400 y tablas largas partidas por filas | `boveda/fragmentos.py`, `make fragmentos` |
| Embeddings | `nomic-embed-text-v2-moe` en Ollama local, 768 dimensiones, sin clave ni costo | `boveda/embeddings.py` |
| Prefijos | `search_document: ` al indexar y `search_query: ` al consultar; se desactivan con `prefijos = false` | `config/sucursal.toml` |
| Índice | Chroma persistente en `data/boveda/chroma`, colección `boveda`, distancia coseno | `boveda/almacen.py` |
| Metadatos | `data/boveda/indice.json` con modelo, prefijos, alcance, fragmentos y dimensión | `make indice` |
| Alcance base | Páginas web, PDF con `categoria_documento: producto` y hechos verificados | `make indice` |
| Alcance completo | Añade el resto de PDF y los videos transcritos | `make indice-completo` |
| Recuperación | Híbrida: vectorial + BM25 con pesos configurables y `puntaje` = 1 − coseno | `boveda/recuperador.py` |

### Modelo de embeddings

Ollama sirve `nomic-embed-text-v2-moe` en `127.0.0.1:11434`; la URL se declara
como `base_url` en `[embeddings]` de `config/sucursal.toml`, no con
`OLLAMA_HOST`. Ese último es la dirección de *bind* del daemon y puede ser
`0.0.0.0`, que no sirve como destino; el módulo lo traduce a `127.0.0.1` solo
cuando llega como respaldo del entorno. Con embeddings locales, el plano de
vectores no consume la cuota de DeepSeek: solo el chat se factura.

Alternativas descartadas: `sentence-transformers` con `multilingual-e5-base`
(descarga pesos en la primera ejecución y complica la CI) y embeddings por API
(el corpus saldría a un tercero y tendría costo por token).

### Base de datos vectorial

**Chroma** (`langchain-chroma`) persistida en `data/boveda/chroma`, con la
métrica coseno fijada al crear la colección. Guarda los metadatos de cada
fragmento (`url`, `titulo`, `seccion`, `encabezado`, `tipo`, `tokens`), así que
la respuesta puede seguir citando la fuente.

La colección se reconstruye entera en cada `make indice`: no hay *upsert*
incremental, para no dejar fragmentos huérfanos cuando cambia el chunking. El
índice es un derivado, no se versiona (`data/boveda/` está en `.gitignore`) y se
regenera desde Gold y Knowledge.

Alternativa: **FAISS**, más rápido en búsquedas puras, pero sin metadatos ni
persistencia propios; habría que mantener un archivo aparte.

### Recuperación y prompt del Módulo 2

La recuperación es **híbrida**: `EnsembleRetriever` combina el almacén vectorial
de Chroma con `BM25Retriever` en memoria sobre los fragmentos del alcance. Los
pesos viven en `[recuperacion]` de `config/sucursal.toml` (`k`,
`peso_vectorial`, `peso_bm25`) y se normalizan a suma 1 antes de pasarlos. El
orden final lo decide el híbrido; después, cada candidato se vuelve a puntuar
contra la consulta con el mismo embedding, de modo que `puntaje` significa
siempre `1 − distancia coseno`, también para los fragmentos que solo devolvió
BM25.

**Se mantiene DeepSeek Flash** para redactar, con el prompt `qa_v2` y la
validación de citas. Lo que cambia es el contexto: en lugar del corpus completo
se envían los *k* fragmentos recuperados, cada uno con su URL para que la cita
siga siendo verificable. Eso baja el costo por pregunta y permite sumar los PDF
y los videos al conocimiento.

### Digiturno (router)

`boveda` y `tablero` no se eligen por azar: el **digiturno** asigna un turno a
cada pregunta antes de llamar a nada. El orden es fijo y se detiene en la
primera coincidencia:

1. **PII** (`validacion.detectar_pii`) → `X`. Los teléfonos públicos del canal
   se aceptan como permitidos; si falta `data/contexto/`, la lista queda vacía.
2. **Fuera de alcance** (patrones de `[digiturno]` en `config/sucursal.toml`):
   saldo o deudas propias, otro banco, clima, consejo de inversión, intento de
   revelar instrucciones → `X`.
3. **Tarifas y coberturas** (`cuota`, `tarifa`, `cobertura`, `carencia`,
   `descuento`, `promoción`, `asistencia`, `seguro`…) → `T`.
4. **Duda**: si se inyecta un clasificador, se pregunta a DeepSeek a temperatura
   0 con salida JSON `{letra, motivo}` y hasta 512 tokens: el modelo gasta medio
   centenar solo en razonar y con topes bajos la duda caía siempre al respaldo.
   Cualquier salida inválida cae a `B` con motivo `defecto:modelo_sin_respuesta`.
5. Por defecto, **`B`** (Bóveda), con motivo `defecto` cuando no hay clasificador.

`numero` es un consecutivo por proceso (empieza en 1) y **no se persiste**; la
pregunta tampoco se guarda. `T` es provisional: el grafo confirmará la ruta solo
si el Tablero devuelve de una a tres filas; con cero o más de tres, la pregunta
pasa a `B`.

### Tablero de tasas (datos estructurados)

`make tablero` convierte el tarifario PDF y las tablas Markdown de Gold en
`data/estructurados/tablero.csv`, un archivo pequeño, determinista y versionado
que responde con cifras exactas sin pasar por el modelo.

| Origen | De dónde sale | Cómo se extrae |
|---|---|---|
| `tarifario` | `ver-tarifas-2025-*.md` | Máquina de estados sobre las líneas «concepto, valor y fecha» (`Cuota de Manejo Tarjeta Débito $16.700 20-nov-25`) |
| `tabla_web` | Páginas de asistencias, Cuota Protegida, promociones, asistencia vehicular y proyectos de vivienda | Lector de tablas Markdown con adaptadores por página |

Columnas exactas, en este orden:

```text
concepto, categoria, valor, moneda, recargos, periodicidad,
vigente_desde, origen, pagina, fuente
```

Reglas:

1. `valor` conserva el formato original (`16.700`, `2.000`, `407,027,630`) y la
   `moneda` es `COP`, `USD`, `EUR` o `%` según la fuente.
2. `recargos` conserva `+ IVA` o `+ Seguro` y nunca se suma al valor.
3. `vigente_desde` se normaliza a ISO (`20-nov-25` → `2025-11-20`); si la fuente
   no trae fecha, queda vacío: no se inventa una vigencia.
4. `pagina` es la ruta relativa del Gold y `fuente` la URL pública exacta.
5. El CSV se ordena de forma determinista y dos ejecuciones producen el mismo
   archivo; `data/boveda/` sigue fuera de Git, pero este CSV sí se versiona.
6. `make tablero` cruza las 8 preguntas de tipo `tabla` del set de fase 2 y
   termina con error si alguna no encuentra fila o valor, con el detalle de cuál.

`buscar_filas` y `comparar_filas` son funciones puras: filtran por concepto y
categoría sin tildes ni mayúsculas, y comparan dos grupos (por ejemplo Visa y
Mastercard) devolviendo las filas que solo existen en un lado y las que difieren
en valor. `buscar_filas` parte la consulta en palabras significativas (descarta
artículos y muletillas como «cuánto», «cuesta» o «de»), compara raíces para
aceptar plurales y flexiones, y devuelve las filas con más coincidencias en vez
de exigir todos los términos; si la consulta no trae palabras significativas no
devuelve filas.

Estado actual: 622 filas únicas en el CSV y 8 de 8 preguntas de tabla cubiertas.

### Grafo con memoria

`sucursal/grafo.py` compila un `StateGraph` con seis nodos y `SqliteSaver` en
`data/asistente/memoria.sqlite`:

```text
reformular → digiturno ─┬─ X → rechazo
                        ├─ T → tablero ─┬─ 1–3 filas → plantilla → redactar
                        │               └─ 0 o 4+ → boveda
                        └─ B → boveda ──┬─ hay fragmentos → redactar
                                        └─ sin fragmentos → rechazo
```

- `reformular` solo actúa si hay historial y la pregunta es un seguimiento
  («¿Y…», «y…», «cuánto», «cuál», «cómo» o menos de seis palabras); el historial
  se recorta con `trim_messages` y `count_tokens_approximately`.
- `redactar` usa la plantilla si el Tablero ya respondió (costo cero) o
  `ContextoRag` con `qa_v2`; si el modelo falla, cae en la frase fija sin romper
  el hilo.
- La pregunta con PII se rechaza **antes** de invocar el grafo, así que no entra
  al checkpointer; cada conversación se aísla por `thread_id`.
- El estado guarda datos serializables (diccionarios) y las respuestas de
  `RespuestaCitas` se propagan en `fuentes`, `uso` y `avisos`.

### API local, costo y caché

`app.py` monta la API antes de los estáticos y escucha **solo** en
`127.0.0.1:8000`. Endpoints de lectura:

| Endpoint | Contenido |
|---|---|
| `GET /api/estado` | modo demo, gasto del día, tope, índice y modelo de embeddings |
| `GET /api/tablero?q=` | filas del CSV filtradas por concepto o categoría |
| `GET /api/boveda/mapa?pregunta=` | puntos PCA, pregunta proyectada y top de fragmentos; `disponible: false` si falta `mapa.json` |
| `GET /api/pipeline` | etapas de `panel.pipeline_summary` + estado de indexación |
| `GET /api/arqueo` | contenido de `data/evaluacion/arqueo.json` o `disponible: false` |
| `GET /api/vestibulo` | hitos de `config/vestibulo.toml` |

Costo y caché (`sucursal/costo.py`):

- Las tarifas se importan de `arqueo/metricas.py` (única fuente) y se elige pico
  de lunes a viernes entre 01:00–04:00 y 06:00–10:00 UTC; el resto es valle.
- `GastoDiario` suma costo, llamadas y tokens del día en
  `data/asistente/gasto.sqlite`; el tope sale de `[sucursal]` y
  `SUCURSAL_TOPE_USD` lo sobrescribe.
- `CacheRespuestas` guarda la respuesta completa con clave
  `sha256(pregunta normalizada|ruta|versión)` y TTL de `[sucursal]`.
- Con `SUCURSAL_DEMO=1` no se crea cliente de DeepSeek, el costo es cero y no se
  escribe gasto.

### Cómo se compara

1. Correr `make evaluar` con la estrategia actual (contexto completo).
2. Correr `make evaluar VERSION=v2` con la recuperación y las mismas preguntas.
3. Comparar aciertos, falsos negativos, tokens de entrada, latencia y costo con
   `docs/ARQUEO.md` y McNemar.

## 4. Diseño del prompt (resumen)

Ver `config/prompts/qa_v1.md` y `docs/EXPERIMENTOS_PROMPTS.md`. Las decisiones
clave son: contexto entre `<contexto>` al inicio (aprovecha la caché), reglas
después del contexto y repetidas en `<reglas_clave>` junto a la pregunta, frase
fija cuando no hay dato, cita obligatoria de la fuente y validación posterior
que reemplaza cualquier respuesta sin cita, con cifras que no están en el
contexto o con datos personales.
