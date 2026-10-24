# Estándar aplicado (Clase 2 → este proyecto)

Este documento traza cada regla de la clase a su implementación concreta, para
que el entregable sea verificable.

## 1. Arquitectura Medallion

| Capa | Regla de la clase | Implementación |
|---|---|---|
| 🥉 **Bronze** | «Lo que devolvió la web, tal cual. Nunca se edita a mano.» | `data/raw/html/<hash>.html` + `capture.jsonl` (url, fecha, status, sha256, bytes). Generado por `fetch.py`. |
| 🥈 **Silver** | «Solo el texto útil, sin menús, cookies ni duplicados.» | `data/processed/markdown/*.md` + `silver.jsonl`. `extract.py` usa trafilatura y `dedupe.py`. |
| 🥇 **Gold** | «Markdown con metadatos. Es el insumo directo del Módulo 2.» | `data/gold/pages/*.md` + `corpus.jsonl` + `_INDICE.md`. `gold.py` y `stats.py`. |

**Reprocesable:** `make clean && make extract && make gold` regenera Silver y
Gold desde Bronze sin volver a la web.

## 2. Cortesía y legalidad

| Regla | Implementación |
|---|---|
| 1-2 s entre peticiones | `crawl.delay_seconds = 1.5`, más pausa de 10 s cada 50 peticiones |
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
- `data/gold/corpus.jsonl` con todos los metadatos
- `data/gold/_INDICE.md` con el resumen y la cobertura
- `data/knowledge/` con entidades, hechos y relaciones validados
- Pipeline reproducible: `make all`
- Paquete para entregar: `make deliver` → `dist/corpus-gold-YYYY-MM-DD.zip`

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
