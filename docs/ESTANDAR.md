# Estándar aplicado (Clase 2 → este proyecto)

Este documento traza cada regla de la clase a su implementación concreta, para
que el entregable sea verificable.

## 1. Arquitectura Medallion

| Capa | Regla de la clase | Implementación |
|---|---|---|
| 🥉 **Bronze** | «Lo que devolvió la web, tal cual. Nunca se edita a mano.» | `data/raw/html/<hash>.html` + `capture.jsonl` (url, fecha, status, sha256, bytes). Generado por `fetch.py`. |
| 🥈 **Silver** | «Solo el texto útil, sin menús, cookies ni duplicados.» | `data/processed/markdown/*.md` + `silver.jsonl`. `extract.py` usa trafilatura y `dedupe.py`. |
| 🥇 **Gold** | «Markdown con metadatos. Es el insumo directo del Módulo 2.» | `data/gold/pages/*.md` + `corpus.jsonl` + `_INDICE.md`. `gold.py` y `stats.py`. |

**Reprocesabilidad real del checkout actual:** Bronze conserva **1 HTML**,
Silver está **vacío** y Gold tiene **181 páginas web** del sitio (más 40 fichas
`hecho-*` y 20 `noticia-*`, para 241 archivos en `pages/`). Por tanto, hoy
`make clean && make extract && make gold` **no** puede regenerar las 181 páginas
del sitio: el Gold versionado es la única fuente disponible para medirlas. Para
volver a generar Silver y Gold hay que re-capturar Bronze con `make all`; ese
trabajo sigue pendiente y se registra en `CONSTITUTION.md` §14.

## 2. Cortesía y legalidad

| Regla | Implementación |
|---|---|
| 1-2 s entre peticiones (aquí 1,5 s; `robots.txt` no declara `Crawl-delay`, es decisión del proyecto) | `crawl.delay_seconds = 1.5`, más pausa de 10 s cada 50 peticiones |
| User-Agent identificable | UA de navegador + header `From` con el contacto académico (el WAF responde 403 a UA que se declaren bot; ver `CONSTITUTION.md` §10) |
| Respetar `robots.txt` | `discover.parse_robots()` + `can_fetch()`; los `Disallow` se registran como descartados |
| Leer el sitemap primero | `discover.py` expande el **índice de índices** de Liferay hasta 2 niveles |
| Nada de datos personales | filtros de alcance + revisión en la etapa Gold |
| Guardar el crudo además del limpio | Bronze separado de Silver/Gold |

## 3. Extracción y limpieza

| Regla | Implementación |
|---|---|
| `requests`/HTTP para HTML estático | `net.py` (httpx con HTTP/2, reintentos y backoff) |
| `BeautifulSoup` para parsear | `extract._fallback()` con selectores `main`/`article` |
| `trafilatura` para extracción semántica | `extract._trafilatura()` → Markdown |
| Quitar boilerplate repetido | `dedupe.find_boilerplate()`: líneas presentes en ≥35 % de los documentos |
| «>90 % menos contexto» | se mide en `make stats` (tokens Gold vs. HTML crudo) |

### Deduplicación de Gold: solo medición

La deduplicación de **Silver** sigue siendo una limpieza: `find_boilerplate()`
elimina líneas repetidas antes de escribir el Markdown procesado. La
deduplicación de **Gold** es distinta: **solo se mide**. `make repetidos` analiza
`data/gold/pages/*.md` en modo lectura, detecta líneas y bloques de 2-3 líneas
repetidos y escribe un único reporte, `data/gold/_REPETIDOS.md`; no elimina
líneas, no reescribe páginas ni `corpus.jsonl` y no cambia el entregable.

Sobre el Gold actual (181 páginas web, 8 094 líneas de contenido), el texto que
pertenece a algún bloque presente en al menos 5, 10 y 20 páginas es el **22.3 %**,
**16.7 %** y **9.1 %** respectivamente. Estas cifras son un diagnóstico, no una
orden de borrado: cualquier política de deduplicación de Gold se decide aparte y
debería regenerar el corpus desde Bronze, algo que hoy no es posible (ver §1).

## 4. Capa Gold

Frontmatter exacto del estándar:

```yaml
---
fuente: <url>
titulo: <título>
seccion: identidad | oferta | presencia | datos | atencion | legal | otros
empresa: Banco de Occidente
fecha_captura: YYYY-MM-DD
idioma: es
tokens: <int>
hash: <sha256[:8]>
palabras: <int>          # extra
metodo: trafilatura      # extra
keywords: [...]          # extra
---
```

Encabezados `#`/`##` como fronteras de chunk. Tablas y listas se conservan.

### Fichas de noticias y hechos relevantes

Las fichas se escriben como `data/gold/pages/noticia-*.md` (prensa externa
verificada) y `hecho-*.md` (hechos oficiales). Su frontmatter extiende el
contrato anterior con los campos de noticias:

```yaml
---
id: hecho-2026-10-19-emision-de-valores
tipo: hecho
origen: oficial
seccion: presencia
empresa: Banco de Occidente
titulo: Emisión de valores
fecha_publicacion: 2026-10-19
fecha_captura: 2026-10-24
idioma: es
fuente: https://www.bancodeoccidente.com.co/inversionistas
medio: Banco de Occidente
resumen: Colocación de bonos ordinarios por $500.000 millones.
temas: [financiacion]
relevancia: alta
estado: verificado
tokens: 42
hash: 3f9c1a7d
palabras: 10
metodo: noticias
evento: 2026-10-19-emision
anexo: https://www.bancodeoccidente.com.co/documents/d/guest/ir-final-oct-2026
documento_id: ir-final-oct-2026
documento_archivo: ir-final-oct-2026.md
documento_titulo: Informe Final Octubre 2026
---
```

- El cuerpo solo lleva título, medio, fecha, enlace al origen y resumen propio;
  no se copia el artículo, ni imágenes, ni PDFs de prensa.
- Si el anexo ya está en `documents.jsonl`, se agrega el enlace relativo
  `../documents/<archivo>.md`; si no, se conserva `anexo` sin descargar.
- `_NOTICIAS.md` resume la ventana, los conteos y la tabla de fichas. Las filas
  `noticia-*` y `hecho-*` también se consolidan en `corpus.jsonl`.
- `healthcheck.py` exige `fecha_publicacion`, `tipo`, `origen`, `medio` y
  `resumen`, detecta ids duplicados y valida el documento enlazado.

## 5. Entorno con uv

| Regla de la clase | Implementación |
|---|---|
| `pyproject.toml` (PEP 621) | `pyproject.toml` |
| `uv.lock` versionado | `uv.lock` |
| `.python-version` versionado | `.python-version` (3.13) |
| `.venv/` **no** se versiona | `.gitignore` |
| `uv add` para dependencias | `make add PKG=...` |
| `uvx` para herramientas | `make lint` / `make fmt` vía `uv run ruff` |
| Scripts PEP 723 para pruebas | `scripts/scrape_empresa.py` |
| Nada de `pip` ni `requirements.txt` | no hay ninguno en el repo |

## 6. Checklist del Taller 1

24 casillas en 4 categorías (`identidad`, `oferta`, `presencia`, `datos`).
`checklist.py` busca evidencia en el corpus y `make stats` escribe el estado en
`data/gold/_INDICE.md`.

## 7. Entregable

- Un `.md` por página en `data/gold/pages/`
- Fichas `data/gold/pages/noticia-*.md` y `hecho-*.md` con el frontmatter de
  noticias y su enlace a `../documents/<archivo>.md` cuando el anexo ya existe
- `data/gold/corpus.jsonl` con todos los metadatos, incluidas las fichas
- `data/gold/_INDICE.md` con el resumen y la cobertura
- `data/gold/_NOTICIAS.md` con la ventana, los conteos y la tabla de fichas
- `data/gold/_REPETIDOS.md` con el diagnóstico de bloques repetidos de las
  páginas web (solo medición, no modifica el resto de Gold)
- `data/knowledge/` con entidades, hechos y relaciones validados
- Pipeline reproducible: `make all`
- Noticias reproducibles por separado: `make noticias`
- Diagnóstico de repeticiones por separado: `make repetidos` (offline; no forma
  parte de `make all`, `make gold` ni `make deliver`, y no elimina contenido)
- Paquete para entregar: `make deliver` → `dist/corpus-gold-YYYY-MM-DD.zip`

`make repetidos` ejecuta `uv run corpus repetidos`, analiza únicamente
`data/gold/pages/*.md` (sin `hecho-*` ni `noticia-*`) y reescribe solo
`data/gold/_REPETIDOS.md` con las 181 páginas analizadas, la tabla de umbrales
5/10/20 (22.3 %, 16.7 % y 9.1 %), el top 20 de bloques y las métricas de
`unique_ratio`. No hace peticiones HTTP y es determinista: dos ejecuciones con
el mismo Gold producen el mismo archivo.

## 8. Estándar de ingeniería (heredado de la CONSTITUTION del curso)

| Regla | Dónde se cumple |
|---|---|
| `uv` único gestor; prohibido `pip`/`requirements.txt` | `pyproject.toml`, `uv.lock`, hook `no-pip-requirements` |
| Estilo Ruff (línea 100, comillas dobles) | `[tool.ruff]` + `make lint` / `make fmt` |
| Tipado estático | `make typecheck` (`ty`) |
| Pruebas AAA sin red | `test/test_pipeline.py` + `make test` |
| Conventional Commits | `CONSTITUTION.md` §8 |
| Hooks antes del commit | `.pre-commit-config.yaml` |
| CI en verde | `.github/workflows/ci.yml` (lint + formato + pytest + demo) |
| Documentación viva | `CONSTITUTION.md` y este archivo se actualizan en el mismo commit |

## 9. Trazabilidad de la captura

`data/raw/capture.jsonl` guarda por URL: `status`, `fecha_captura`, `bytes`,
`sha256`, `archivo` y `error`. Con `sha256` se detecta si el contenido cambió y
con `_INDICE.md` se ve la cobertura. `make status` resume las cuatro etapas.

## 10. Extracción semántica (capa Knowledge)

| Regla | Implementación |
|---|---|
| Un chunk = una frontera de encabezado | `knowledge.split_page()`; `chk:<hash>` determinista |
| Todo hecho tiene cita textual | `evidence.quote` + `validate_knowledge()` |
| La cita debe estar en el chunk | normalización sin markdown + comparación |
| Esquema explícito | `config/knowledge.schema.json` (JSON Schema 2020-12) |
| Sin datos personales | `PII_PATTERNS` (email, celular, documento) |
| Sin duplicados | firma `(entidad, predicado, valor)` y `(sujeto, predicado, objeto)` |
| Revisión humana | `review: pending → approved` |
| Extracción incremental | borradores por sección + `--file` / `--merge` |
| Skill del agente | `.opencode/skills/semantic-extraction/` |

Comandos:

```bash
make chunks
uv run corpus knowledge --file data/knowledge/draft-identidad.jsonl
uv run corpus knowledge --merge data/knowledge/draft-identidad.jsonl
make knowledge
```

El detalle del contrato está en la skill (`references/schema.md` y
`references/taxonomy.md`).
