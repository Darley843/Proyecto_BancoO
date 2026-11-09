# Proposal

## Why

La fase 1 dejó un corpus Gold versionado y un asistente que funciona enviando todo el
contexto en el prompt de sistema: unos 187 000 tokens de entrada por pregunta, sin
recuperación, sin memoria entre turnos y sin acceso a las cifras que viven en tablas.
La app actual es un Streamlit de demostración que no se parece a la experiencia que
pide la fase 2. En dos semanas el proyecto debe demostrar RAG con embeddings, memoria
conversacional, datos estructurados y un router que decida qué hacer con cada pregunta,
detrás de una app web propia con el concepto de una sucursal bancaria. DeepSeek Flash
sigue siendo el único modelo que se paga; los embeddings corren locales con Ollama.

## What Changes

- Añadir la capa **Bóveda** (`boveda/`): fragmentos a partir de `data/knowledge/chunks_web.jsonl`
  y `chunks.jsonl`, embeddings locales con Ollama (`nomic-embed-text-v2-moe`), índice
  persistente en Chroma y recuperación híbrida (vectorial + BM25) con pesos configurables.
  Targets `make indice` (web, documentos de producto y hechos) y `make indice-completo`.
- Añadir el **Tablero** (`tablero/`): extracción del tarifario PDF “Ver tarifas 2025” y de
  las tablas Markdown de Gold a `data/estructurados/tablero.csv` con esquema único,
  búsqueda y comparación deterministas. Target `make tablero`.
- Añadir la **Sucursal** (`sucursal/`): digiturno de reglas, grafo LangGraph con memoria
  SQLite por `thread_id`, respuesta directa del Tablero cuando hay de una a tres filas,
  tope de gasto diario, caché de respuestas y modo demo. API FastAPI en `127.0.0.1:8000`.
- Añadir el prompt `config/prompts/qa_v2.md` y `asistente/rag.py` (fragmentos numerados,
  citas `[n]`, lista final de fuentes y validación de citas).
- Reemplazar Streamlit por una app web sin frameworks en `app/web/` (HTML, CSS, JavaScript)
  con una vista por archivo: vestíbulo, ventanilla, bóveda, tablero, cámara y arqueo.
  `app.py` levanta uvicorn y `make app` hace lo mismo.
- Añadir el **Arqueo** (`arqueo/`): experimentos de recuperación (hit@5, MRR, pesos del
  híbrido, prefijos), comparación v1/v2 con McNemar sobre las 20 preguntas de alcance y
  targets `make arqueo` y `make evaluar VERSION=v2`.
- **BREAKING**: se retira Streamlit (`app/streamlit_app.py`, `app/scraping_ui.py` y la
  dependencia `streamlit`) al final del cambio; `make app` deja de abrir Streamlit.
- Adoptar el trabajo ya abierto por el grupo: la nueva plantilla de PR (#43), las 40
  preguntas de `config/evaluacion/preguntas_fase2.toml` (#44) y las métricas de
  `arqueo/metricas.py` (#45). El diseño no las reimplementa: las integra.

## Capabilities

### New Capabilities

- `boveda-rag`: preparación de fragmentos, embeddings locales con prefijos, índice vectorial
  persistente, recuperación híbrida y proyección 2D para explorar el corpus.
- `tablero-tarifas`: conversión del tarifario PDF y de las tablas Markdown de Gold en filas
  comparables con concepto, valor, moneda, recargos, periodicidad y vigencia.
- `sucursal-agente`: digiturno, grafo con memoria, política de costo y caché, y contrato
  JSON de la API que consume el frontend.
- `sucursal-frontend`: app web propia sin frameworks, con una vista por archivo y datos de
  ejemplo con la misma forma que la API.
- `arqueo-evaluacion`: experimentos de recuperación, evaluación v1/v2 con McNemar y
  reportes reproducibles en `data/evaluacion/arqueo.json` y `docs/ARQUEO.md`.

### Modified Capabilities

- Ninguna. `corpus-noticias` y `corpus-dedupe` no cambian sus requisitos; el pipeline de
  captura y el contrato de Gold se mantienen intactos.

## Impact

- Código nuevo: `src/banco_occidente_corpus/{boveda,tablero,sucursal,arqueo}/`,
  `src/banco_occidente_corpus/asistente/rag.py`, `app/web/`, `app.py`,
  `config/prompts/qa_v2.md`, `config/sucursal.toml`, `config/vestibulo.toml` y la skill
  `.opencode/skills/boveda-rag/`.
- Código tocado: `makefile` (targets `indice`, `indice-completo`, `tablero`, `arqueo`,
  `app`), `asistente/cli.py` (modo v2 por el grafo), `arqueo/experimentos.py`,
  `CONSTITUTION.md`, `AGENTS.md`, `docs/MODELADO.md`, `docs/ESTANDAR.md` y `README.md`.
- Código retirado al final: `app/streamlit_app.py`, `app/scraping_ui.py` y la dependencia
  `streamlit` de `pyproject.toml`.
- Dependencias nuevas (solo PR 0, responsable Darley, con `uv add`): LangGraph, Chroma,
  `langchain-classic` (EnsembleRetriever/BM25), `langchain-ollama`, `fastapi`, `uvicorn`,
  `scikit-learn` y `sqlalchemy` si LangGraph lo exige. `uv.lock` no se edita a mano.
- Datos nuevos no versionados: `data/boveda/` (Chroma) y `data/asistente/*.sqlite`
  (memoria, gasto y caché). Datos nuevos versionados: `data/estructurados/tablero.csv`
  (derivado pequeño y determinista, evidencia de las preguntas de tabla),
  `data/evaluacion/arqueo.json` y `docs/ARQUEO.md`.
- Pruebas nuevas sin red: `FakeListChatModel` y `DeterministicFakeEmbedding` de
  `langchain_core`; ninguna prueba llama a Ollama, a DeepSeek ni al sitio del banco.
- Riesgos controlados: índice y bases locales fuera de Git; servidor escuchando solo en
  `127.0.0.1`; fragmentos tratados como datos y nunca como instrucciones; tope diario y
  modo demo para no gastar en desarrollo.
