# Inventario de fuentes autorizadas

Registro de **qué se puede leer**, **dónde está** y **cómo se captura**. Cierra
la tarea *Inventariar fuentes autorizadas* (issue #4) del proyecto.

## 1. Fuente primaria — sitio web público

| Campo | Valor |
|-------|-------|
| Dominio | `https://www.bancodeoccidente.com.co` |
| Tipo | HTML público (Liferay) |
| Mapa | `https://www.bancodeoccidente.com.co/sitemap.xml` |
| Reglas | `https://www.bancodeoccidente.com.co/robots.txt` |
| Método | `requests`/`httpx` + `trafilatura` (fallback BeautifulSoup) |
| Capa destino | Bronze → Silver → Gold |

### Reglas de `robots.txt` (verificadas)

```text
User-agent: *
Disallow: /portaltransaccional/
Disallow: /icbs-web/
Disallow: /AjaxTx
Disallow: /wps/
Disallow: /*!ut/p*
Allow: /_next/
Allow: /_next/static/
Allow: /_next/image/
Allow: /*.js$
Allow: /*.css$
Allow: /*.woff$
Allow: /*.woff2$
Allow: /*.ttf$
Allow: /*.svg$
Sitemap: https://www.bancodeoccidente.com.co/sitemap.xml
```

| Ruta | ¿Se captura? | Motivo |
|------|:------------:|--------|
| `/quienes-somos`, `/cuentas`, `/tarjetas-credito`, `/creditos`, `/inversion`, `/seguros`, `/noticias`, `/tarifas` | ✅ | Contenido público |
| `/portaltransaccional/` | ❌ | `Disallow` (banca transaccional) |
| `/icbs-web/`, `/AjaxTx`, `/wps/` | ❌ | `Disallow` (backend/servicios) |
| `/*!ut/p*` | ❌ | `Disallow` (parámetros de sesión) |
| `/_next/`, `*.js`, `*.css`, `*.woff*`, `*.svg` | ➖ | Permitido, pero es ruido para el corpus |

> El pipeline aplica además una lista de `exclude_patterns` en
> `config/site.toml` (login, carrito, admin, documentos, imágenes).

### Hallazgo: el sitemap publica rutas `/w/`

El sitemap de Liferay enumera las páginas como `/w/<slug>`, pero el sitio sirve
el contenido en `/<slug>`:

| URL del sitemap | Estado real | URL que sirve |
|-----------------|:-----------:|---------------|
| `/w/cuenta-de-ahorros` | `404` | `/cuenta-de-ahorros` (`200`) |

`discover.normalize_url()` elimina el prefijo `/w/` antes de encolar. Sin esa
normalización la captura sería de 404 en masa.

### Hallazgo: WAF y User-Agent

CloudFront responde `403` a cualquier UA que se declare bot, aunque
`robots.txt` permita la página. Solución adoptada (documentada en
`CONSTITUTION.md` §10): UA de navegador + header `From` con el correo
académico en **cada** petición.

## 2. Fuente secundaria — documentos (PDF, DOCX, XLSX)

| Campo | Valor |
|-------|-------|
| Detección | `discover.py` → `data/raw/documents.jsonl` |
| Extensiones | `.pdf`, `.doc`, `.docx`, `.xls`, `.xlsx`, `.ppt`, `.pptx` |
| Estado | **Registrados, no descargados** (Fase 3) |
| Uso previsto | Informes, memorias anuales, catálogos, tarifarios |

No se descargan todavía para no duplicar esfuerzo ni peso: primero se estabiliza
el corpus HTML y se decide qué documentos aportan al checklist.

## 3. Fuente terciaria — YouTube

| Campo | Valor |
|-------|-------|
| Herramienta | `yt-dlp` / `youtube-transcript-api` |
| Contenido | Entrevistas del presidente, videos institucionales |
| Estado | **Fase 3** |
| Regla | Solo si existe transcripción (no transcribir a mano) |

## 4. Fuera de alcance

- Zonas transaccionales y contenido tras login.
- Datos personales de clientes o empleados (Ley 1581 de 2012 — Habeas Data).
- Redes sociales (requieren autenticación y tienen términos propios).
- Contenido protegido por paywall o licencias restrictivas.

## 5. Cortesía y trazabilidad

| Regla | Implementación |
|-------|----------------|
| 1.5 s entre peticiones | `crawl.delay_seconds` |
| Pausa de 10 s cada 50 peticiones | `crawl.politeness` |
| Timeout de 30 s y 3 reintentos con backoff | `net.HttpClient` |
| Identificación | UA de navegador + header `From` |
| Evidencia por URL | `data/raw/capture.jsonl` (status, fecha, bytes, sha256) |
| Reprocesable | Bronze intacto; Silver y Gold se regeneran sin red |

## 6. Resultado de la primera captura (2026-10-23)

| Métrica | Valor |
|---|---:|
| Sitemaps leídos | 210 (11 con `404`, layouts obsoletos) |
| URLs públicas descubiertas | 196 |
| Páginas capturadas (Bronze) | 193 |
| URLs no capturadas | 3 (`404` reales) |
| Peso del HTML crudo | 102.3 MB |
| Páginas con texto útil (Silver) | 193 |
| Documentos Gold (únicos) | 184 (9 duplicados descartados) |
| Tokens totales | 151.972 |
| Cobertura del checklist | 24/24 (heurística, con evidencia citada) |

> El sitemap no publica PDFs ni vídeos: esos quedan para la Fase 3 con
> `yt-dlp` y `pdfplumber`.

## 7. Cómo verificar el inventario

```bash
make doctor      # red + robots.txt + estado
make discover    # expande el sitemap y escribe data/raw/urls.jsonl
make status      # URLs / Bronze / Silver / Gold
make stats       # cobertura de las 24 casillas del Taller 1
```
