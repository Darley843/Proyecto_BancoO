# Pipeline del corpus — referencia técnica

Documento de apoyo de la skill `corpus-extraction`. La fuente de verdad sigue
siendo `CONSTITUTION.md` (raíz del repositorio).

## Capas

| Capa | Ruta | Qué guarda | ¿Se versiona? |
|---|---|---|---|
| 🥉 Bronze | `data/raw/html/<hash>.html` | HTML crudo, tal como lo devolvió la web | No |
| 🥉 Bronze | `data/raw/capture.jsonl` | url, status, fecha, bytes, sha256, archivo | No |
| 🥉 Bronze | `data/raw/urls.jsonl` | plan de captura (sitemap) | No |
| 🥈 Silver | `data/processed/markdown/*.md` | solo el texto útil | No |
| 🥈 Silver | `data/processed/silver.jsonl` | metadatos + texto limpio | No |
| 🥇 Gold | `data/gold/pages/*.md` | Markdown + frontmatter YAML | **Sí** |
| 🥇 Gold | `data/gold/corpus.jsonl` | metadatos consolidados | **Sí** |
| 🥇 Gold | `data/gold/_INDICE.md` | reporte y checklist | **Sí** |

## Módulos

| Archivo | Responsabilidad |
|---|---|
| `config.py` | Carga `config/site.toml` y resuelve rutas |
| `net.py` | HTTP/2, UA, header `From`, delay, reintentos y backoff |
| `discover.py` | `robots.txt` + sitemap index recursivo + normalización `/w/` |
| `fetch.py` | Bronze incremental (append por URL) |
| `extract.py` | Silver con `trafilatura`, fallback BeautifulSoup |
| `dedupe.py` | Boilerplate por frecuencia (≥35 % de documentos) |
| `section.py` | Clasificación por reglas + keywords |
| `gold.py` | Frontmatter, slug, `corpus.jsonl`, duplicados por hash |
| `checklist.py` | 24 casillas con evidencia citada |
| `stats.py` | `_INDICE.md` |
| `documents.py` | PDFs: inventario, descarga priorizada y texto con `pypdf` |
| `videos.py` | YouTube: canal, subtítulos `.vtt` y transcripción |
| `utils.py` | Hash, JSONL, tokens, slugs |

## Contrato de Gold

```yaml
---
fuente: https://www.bancodeoccidente.com.co/quienes-somos
titulo: Quiénes Somos | Banco de Occidente
seccion: identidad
empresa: Banco de Occidente
fecha_captura: 2026-10-23
idioma: es
tokens: 601
hash: a689f3ac
palabras: 334
metodo: trafilatura
keywords: [historia, servicios, clientes]
---
```

Reglas:

1. Un `.md` por URL única (el slug incluye un hash corto).
2. `##` es frontera de *chunk* para el RAG.
3. `fecha_captura` es la fecha local del autor, derivada del timestamp UTC de
   Bronze.
4. `hash` es el SHA-256 del cuerpo: detecta duplicados y cambios.
5. `corpus.jsonl` repite los metadatos y añade `id` y `archivo`.

## Límites y parámetros (`config/site.toml`)

| Parámetro | Valor | Motivo |
|---|---:|---|
| `delay_seconds` | 1.5 | Cortesía estándar del curso |
| `max_urls` | 3500 | Tope de seguridad (el sitemap ronda 2.500 entradas) |
| `max_sitemaps` | 400 | Índice de índices de Liferay |
| `max_retries` | 3 | Backoff exponencial |
| `boilerplate_ratio` | 0.35 | Línea repetida en ≥35 % de páginas |
| `respect_robots` | true | Regla dura |

## Decisiones que no se deben revertir sin motivo

- **UA de navegador + `From`**: el WAF bloquea UA de bot (403).
- **Normalizar `/w/`**: el sitemap publica rutas que el sitio no sirve.
- **Bronze incremental**: un corte a mitad de captura no pierde lo descargado.
- **Duplicados por hash**: las redirecciones producen el mismo cuerpo.
- **Gold versionado**: es el insumo del RAG del Módulo 2.

## Fase 3 (pendiente)

- PDFs: el sitemap no los publica; hay que extraer enlaces desde el HTML de
  Bronze y procesarlos con `pdfplumber`.
- YouTube: `yt-dlp` / `youtube-transcript-api`, solo si hay subtítulos.
- Al añadir fuentes, actualizar `CONSTITUTION.md` §2 y `docs/FUENTES.md`.
