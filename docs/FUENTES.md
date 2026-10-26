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
| `/ayuda/agendar-cita-asesor` | ❌ | Formulario de agendamiento: `AGENTS.md` prohíbe capturar formularios. Se excluye en `config/site.toml` y se filtra también al construir Gold |

> El pipeline aplica además una lista de `exclude_patterns` en
> `config/site.toml` (login, carrito, admin, documentos, imágenes y el
> formulario de agendamiento). El filtro se usa en el descubrimiento y otra vez
> en Gold, para que una página ya capturada en Bronze no vuelva al entregable.

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

### Tabla de hechos relevantes (información oficial)

La actualidad corporativa oficial se captura de la tabla **“Información
Relevante”** de la página de inversionistas, no de una sala de prensa.

| Campo | Valor |
|-------|-------|
| Página | `https://www.bancodeoccidente.com.co/quienes-somos/informacion-inversionistas` |
| Tabla | encabezados `Fecha`, `Tema`, `Resumen`, `Anexo Descargable` |
| Enlace | la celda del anexo contiene el texto `Ver Anexo`; se guarda como URL absoluta |
| Parser | `news.py` → `parse_hechos_relevantes()` |
| Fixture | `test/fixtures/inversionistas.html` |
| Pruebas | `test/test_news.py` |

Reglas de selección y privacidad:

- Solo se procesan las tablas cuyos cuatro encabezados coinciden exactamente
  con `Fecha`, `Tema`, `Resumen` y `Anexo Descargable`. Cualquier otra tabla se
  ignora.
- La **tabla de accionistas** (nombre, cédula, NIT y participación) se excluye
  siempre y nunca llega al render ni a Gold.
- Se incluyen únicamente hechos entre `2025-01-01` y la fecha de ejecución; se
  conservan como máximo **40**, del más reciente al más antiguo.
- Los avisos mensuales rutinarios de pago de dividendos se excluyen. Las
  decisiones de asamblea sobre distribución de utilidades sí son hitos.
- Una celda con `No aplica` deja el campo `anexo` vacío.
- Antes de publicar se validan cédula, NIT, correo y teléfono en título y
  resumen; si aparece cualquiera de esos datos, la fila se descarta.
- El enlace `Ver Anexo` se compara con `data/gold/documents.jsonl` por URL
  canónica (sin query ni fragmento y con los hosts `www` y `portalpublico`
  equivalentes). Si el PDF ya está en Gold, la ficha lo enlaza; nunca se
  descarga ni se reextrae.

## 2. Fuente secundaria — documentos (PDF, DOCX, XLSX)

| Campo | Valor |
|-------|-------|
| Detección | `documents.discover_documents()` sobre el HTML Bronze |
| Inventario | **622 PDFs** únicos (balances, informes, gobierno, productos) |
| Prioridad | 1: financiero/gobierno ≥2024 · 2: ≥2022 o categoría · 3: histórico |
| Descarga | `make docs`; tope `--max-mb` (400 por defecto) y 80 MB por archivo |
| Extracción | `pypdf` → `data/gold/documents/*.md` (texto por página) |
| Índice | `data/gold/documents.jsonl` |
| Escaneados | se omiten si el texto extraído es < 500 caracteres |
| Origen | `www.` y `portalpublico.bancodeoccidente.com.co` (mismo banco) |

El host `www.` devuelve `403` en algunos adjuntos; el pipeline reintenta en
`portalpublico.` antes de marcar el fallo.

## 3. Fuente terciaria — YouTube

| Campo | Valor |
|-------|-------|
| Herramienta | `yt-dlp` (metadatos + subtítulos automáticos/manuales) |
| Inventario | videos enlazados en el sitio + canal `@BancodeOccidenteCol` |
| Descarga | `make videos` (solo subtítulos, no el video) |
| Extracción | VTT → párrafos → `data/gold/videos/*.md` |
| Regla | sin subtítulo no entra al corpus (no se transcribe a mano) |
| Índice | `data/gold/videos.jsonl` |

## 4. Fuera de alcance

- Zonas transaccionales y contenido tras login.
- Datos personales de clientes o empleados (Ley 1581 de 2012 — Habeas Data).
- Redes sociales (requieren autenticación y tienen términos propios).
- Contenido protegido por paywall o licencias restrictivas.

## 5. Cortesía y trazabilidad

| Regla | Implementación |
|-------|----------------|
| 1,5 s entre peticiones (decisión del proyecto: `robots.txt` no declara `Crawl-delay`) | `crawl.delay_seconds` |
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
| Documentos Gold (únicos) | 183 (10 duplicados descartados) |
| Tokens de páginas | 151.972 |
| Documentos PDF | 190 (138 financieros) |
| Tokens de PDFs | 10.954.933 |
| Videos transcritos | 32 |
| Tokens de videos | 119.845 |
| Tokens del corpus completo | 11.226.750 |
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
