# Proposal

## Why

El corpus Gold actual no contiene noticias: la sección `presencia` tiene 0 documentos y el sitio no publica `/noticias` ni sala de prensa. La información corporativa reciente vive en la tabla “Información Relevante” de relación con inversionistas y en prensa externa, sin un registro fechado y trazable que el RAG pueda citar. Sin esta capacidad, el agente no puede responder por hechos de 2025-2026 con fuente y sin mezclar opinión con comunicación oficial.

## What Changes

- Añadir ingesta de **hechos relevantes oficiales** desde la tabla “Información Relevante” de la página de inversionistas, limitada a **30-40 hitos importantes de 2025 a hoy**; se excluyen los avisos mensuales rutinarios de pago de dividendos.
- Añadir un registro curado de **prensa externa** con **15-20 fichas**; cada ficha contiene solo título, fecha, medio, enlace y resumen propio. No se guarda el artículo completo, imágenes ni PDFs de prensa.
- No duplicar PDFs ni anexos: si el anexo oficial ya existe en `data/gold/documents.jsonl`, la ficha se enlaza con `documento_id` y `documento_archivo`; si no existe, conserva `anexo` como URL y no se descarga.
- Exigir verificación manual antes de marcar una ficha externa como `verificado`: abrir el enlace original y confirmar que se trata del Banco de Occidente de Colombia y que la fecha es correcta.
- Guardar las fichas en Gold como `data/gold/pages/noticia-*.md` y `data/gold/pages/hecho-*.md`, con frontmatter YAML y cuerpo Markdown; consolidarlas en `data/gold/corpus.jsonl` y generar `data/gold/_NOTICIAS.md`.
- Mantener la curaduría externa en `data/noticias/prensa.yaml`, versionada y fuera de Gold para que `make clean` no la destruya.
- Añadir el comando `uv run corpus noticias` y el target `make noticias` como vía de regeneración. **No** se modifican `make all`, `make gold` ni `make deliver`.
- Parsear únicamente la tabla cuyo encabezado sea `Fecha/Tema/Resumen/Anexo Descargable`. La tabla de accionistas con nombres, cédulas y NIT se ignora siempre.
- Si el sitio responde `403` o bloquea la petición, el programa se detiene y avisa; no cambia User-Agent, no rota proxies ni evade el bloqueo.
- Añadir pruebas, validación de contrato Gold para fichas y documentación en `CONSTITUTION.md`, `docs/ESTANDAR.md`, `docs/FUENTES.md`, `README.md` y `AGENTS.md`.

## Capabilities

### New Capabilities

- `corpus-noticias`: ingestión, verificación, almacenamiento y publicación de hechos relevantes oficiales y fichas de prensa externa en Gold, con fechas, trazabilidad, privacidad y detención segura ante bloqueo.

### Modified Capabilities

- Ninguna. El proyecto no tiene specs previas registradas.

## Impact

- Código nuevo: `src/banco_occidente_corpus/news.py`.
- Código tocado: `cli.py` (subcomando `noticias`), `config.py` (rutas y configuración), `makefile` (solo target `noticias`).
- Sin cambios en `documents.py`, `videos.py` ni `knowledge.py`: los PDFs y videos ya extraídos se consultan como índice y el chunker ya cubre `pages/`, `documents/` y `videos/`.
- Datos nuevos: `data/noticias/prensa.yaml`, `data/gold/pages/noticia-*.md`, `data/gold/pages/hecho-*.md`, `data/gold/_NOTICIAS.md`.
- Datos actualizados: `data/gold/corpus.jsonl`, con `documento_id`, `documento_archivo` y `documento_titulo` cuando el anexo ya existe en Gold.
- Datos de solo lectura: `data/gold/documents/`, `data/gold/documents.jsonl`, `data/gold/videos/` y `data/gold/videos.jsonl`; no se descargan ni duplican PDFs.
- Pruebas: `test/test_news.py`, fixture HTML de la tabla y fixture del índice de documentos; extensión de `healthcheck.py`.
- Documentación: `CONSTITUTION.md`, `docs/ESTANDAR.md`, `docs/FUENTES.md`, `README.md`, `AGENTS.md`.
- Sin dependencias nuevas: se reutilizan `httpx`, `beautifulsoup4`, `lxml`, `pyyaml` y `jsonschema`.
- Sin cambios en `make all`, `make gold`, `make deliver`, `make docs`, `make docs-finanzas`, `make videos` ni `make media`.
- Riesgos controlados: derechos de autor de prensa externa (solo ficha y resumen propio), datos personales (tabla de accionistas excluida), enlaces a documentos desactualizados (se validan contra el índice) y bloqueo del WAF (detención sin evasión).
