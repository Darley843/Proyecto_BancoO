# CONSTITUTION — Corpus Banco de Occidente

> **Verdad central del proyecto.** Define el propósito, el alcance, el stack, la
> estructura, las convenciones y el flujo de trabajo del corpus. Si algo aquí
> contradice al código, el código manda **y este archivo se actualiza en el mismo
> commit**.

> ⚠️ **Directiva de mantenimiento:** todo cambio significativo (nueva etapa del
> pipeline, cambio de alcance, nueva dependencia, nuevo comando) actualiza este
> archivo en el mismo commit.

Este proyecto hereda el estándar del curso **TAAML** (Maestría en IA y Ciencias
de Datos, Universidad Autónoma de Occidente) definido en la CONSTITUTION del
repositorio `Darley843/Proyecto_BancoO`. Las reglas duras del curso se aplican
íntegras; las decisiones locales se documentan abajo con su motivo.

---

## 0. Identidad del proyecto

| Campo | Valor |
|-------|-------|
| **Nombre** | Corpus Banco de Occidente |
| **Paquete Python** | `banco_occidente_corpus` |
| **Curso** | Técnicas Avanzadas de IA aplicadas en Modelos de Lenguaje (TAAML) |
| **Institución** | Universidad Autónoma de Occidente (UAO) |
| **Programa** | Maestría en Inteligencia Artificial y Ciencias de Datos |
| **Entregable** | Taller 1 — Fase 1: corpus propio de la empresa asignada |
| **Empresa** | Banco de Occidente (Grupo Aval, Cali — Valle del Cauca) |
| **Sitio fuente** | https://www.bancodeoccidente.com.co |
| **Repositorio** | https://github.com/Darley843/Proyecto_BancoO (privado) |
| **Autor** | Darley Idárraga — `Darley843` · `darley.idarraga@uao.edu.co` |
| **Licencia** | MIT |
| **Rama principal** | `main` |
| **Estado** | En construcción 🚧 |

## 1. Propósito y no-propósito

### Propósito

Extraer, limpiar y enriquecer la información **pública** del sitio web del Banco
de Occidente para construir un corpus reproducible en Markdown, con metadatos,
listo para alimentar el RAG (Módulo 2) y el agente (Módulo 3) del proyecto
integrador.

El corpus debe cubrir las 24 casillas del checklist del Taller 1: identidad,
oferta, presencia digital y datos duros.

### No-propósito

- **No** es un producto de software ni una librería publicable en PyPI.
- **No** captura zonas privadas, transaccionales o tras login
  (`/portaltransaccional/`, `/icbs-web/`, `/AjaxTx`, `/wps/`).
- **No** almacena datos personales de clientes ni de empleados (Ley 1581 de
  2012 — Habeas Data).
- **No** sustituye la revisión humana: la clasificación por secciones y el
  checklist son heurísticas verificables, no verdad legal.
- **No** versiona Bronze ni Silver (son reproducibles y pesados); Gold **sí** se
  versiona porque es el entregable.

## 2. Alcance y fases

| Fase | Descripción | Estado |
|------|-------------|:------:|
| **Fase 1** | Captura del sitio (Bronze), limpieza (Silver) y corpus Gold con metadatos | ✅ |
| **Fase 2** | Cobertura del checklist y reporte `_INDICE.md` | ✅ |
| **Fase 3** | Documentos (PDF), YouTube (subtítulos) y noticias (hechos oficiales + prensa curada) como fuentes complementarias | 🚧 |
| **Fase 4** | Chunking + embeddings y consumo desde el RAG del Módulo 2 | ⏳ |

**Dentro del alcance:** páginas HTML públicas del dominio, `robots.txt`,
`sitemap.xml` (índice de índices de Liferay), noticias, blog, información
corporativa, tarifas, documentos enlazados (registrados, no descargados aún),
hechos relevantes oficiales de la página de inversionistas y prensa externa
curada (solo ficha mínima y resumen propio).

**Fuera del alcance (por ahora):** redes sociales, contenido tras login,
descarga masiva de PDF, transcripción de vídeo.

## 3. Stack técnico

| Categoría | Tecnología |
|-----------|------------|
| **Lenguaje** | Python 3.13 (`.python-version`) |
| **Gestor de entorno y dependencias** | [`uv`](https://docs.astral.sh/uv/) — **único permitido** |
| **Build backend** | `uv_build` (src-layout) |
| **HTTP** | `httpx` (HTTP/2, reintentos, backoff) |
| **Parseo HTML** | `lxml` + `beautifulsoup4` |
| **Extracción semántica** | `trafilatura` (HTML → Markdown) |
| **Frontmatter** | `PyYAML` |
| **Tokens** | `stable_tokens` (chars/4) para el presupuesto del contexto, sin red; `tiktoken` (extra `tokens`) solo para el campo informativo de Gold |
| **Herramienta del agente** | `scrapling` (grupo `mcp`) — navegación ad hoc vía MCP, **fuera del pipeline** |
| **Testing** | `pytest` (patrón AAA) |
| **Lint / formato** | `ruff` (línea 100, comillas dobles) |
| **Tipado** | `ty` (target `make typecheck`) |
| **CI** | GitHub Actions (`.github/workflows/ci.yml`) |
| **Orquestación local** | `make` (GNU Make) |

> ⚠️ **Regla dura heredada:** prohibido `pip` y `requirements.txt`. Toda
> dependencia entra con `uv add` (o `uv add --dev`) y se fija en `uv.lock`.
> Las pruebas de una tarde van con `uv run --with` o PEP 723, no al proyecto.

### Herramientas del agente (MCP)

`opencode.json` declara los servidores MCP del agente: `docs-langchain`,
`reference-langchain` (remotos, solo consulta) y `scrapling` (local). Scrapling
vive en el grupo `mcp` de `pyproject.toml` y se lanza con
`uv run --group mcp scrapling mcp`; **no** forma parte de las dependencias del
pipeline ni de la CI.

Reglas:

1. Un MCP es herramienta del agente, no una etapa del corpus: no escribe en
   Bronze, Silver ni Gold.
2. Si se usa contra el sitio del banco, siguen mandando `robots.txt`, el
   ritmo de 1,5 s entre peticiones y el header `From` de `net.py`.
3. Los fetchers de navegador requieren `uv run --group mcp scrapling install`
   una sola vez; el modo HTTP funciona sin ese paso.
4. Toda herramienta nueva entra con su grupo propio y se documenta aquí en el
   mismo commit.

## 4. Estructura del repositorio

```text
ProyectoAvance1/
├── src/banco_occidente_corpus/
│   ├── cli.py            # discover | fetch | extract | gold | all | stats | doctor
│   ├── config.py         # site.toml tipado + rutas de las capas
│   ├── discover.py       # robots.txt + sitemap index recursivo + filtros
│   ├── net.py            # cliente HTTP: UA, From, delay, reintentos
│   ├── fetch.py          # BRONZE: HTML crudo + capture.jsonl
│   ├── extract.py        # SILVER: trafilatura + fallback BeautifulSoup
│   ├── dedupe.py         # boilerplate repetido por frecuencia
│   ├── section.py        # clasificación en secciones + keywords
│   ├── gold.py           # GOLD: Markdown + frontmatter + corpus.jsonl
│   ├── contexto.py       # CONTEXTO: prompt del asistente derivado de Gold
│   ├── checklist.py      # 24 casillas del Taller 1
│   ├── stats.py          # _INDICE.md
│   └── utils.py          # hashing, JSONL, tokens, slugs
├── test/                 # pytest + fixtures (sin red)
├── config/site.toml      # alcance, cortesía, filtros y secciones
├── config/contexto.toml  # secciones, prioridad y presupuesto del contexto
├── data/
│   ├── raw/              # Bronze (ignorado por Git)
│   ├── processed/        # Silver (ignorado por Git)
│   ├── gold/             # Gold (VERSIONADO) → páginas, documentos y videos
│   ├── contexto/         # Contexto (VERSIONADO) → prompt del asistente + manifest
│   └── knowledge/        # Knowledge (VERSIONADO) → entidades, hechos, relaciones
├── scripts/
│   ├── tasks.py          # tareas del Makefile portables (Windows/Unix)
│   ├── demo_offline.py   # pipeline completo con un fixture, sin red
│   └── scrape_empresa.py # scraper autocontenido PEP 723
├── docs/ESTANDAR.md      # trazabilidad regla de la clase → implementación
├── .opencode/skills/corpus-extraction/    # skill operativa del pipeline
├── .opencode/skills/semantic-extraction/  # skill de conocimiento semántico
├── .github/workflows/ci.yml
├── .pre-commit-config.yaml
├── CONSTITUTION.md       # este archivo
├── AGENTS.md             # contexto para agentes LLM
├── README.md             # puerta de entrada
├── makefile              # automatización
├── pyproject.toml / uv.lock / .python-version
└── LICENSE
```

## 5. Convenciones de código

- **Estilo:** PEP 8 / PEP 257, impuesto por Ruff (`line-length = 100`, comillas
  dobles).
- **Tipado:** anotaciones en funciones y firmas públicas; `from __future__ import
  annotations` al inicio de cada módulo.
- **Nomenclatura:** `snake_case` (funciones/variables), `PascalCase` (clases),
  `UPPER_CASE` (constantes).
- **Docstrings:** en módulos, clases y funciones públicas.
- **Idioma:** UI, documentación y commits en español; identificadores de código
  en inglés. Los textos del corpus conservan el español original.
- **Pruebas:** `pytest`, patrón **AAA** (Arrange · Act · Assert), sin red.
- **Notebooks:** no se versionan; la lógica vive en `src/` o en scripts `.py`.

## 6. Calidad y automatización

| Herramienta | Rol | Comando |
|-------------|-----|---------|
| `uv` | Entorno y dependencias | `make init` |
| Ruff | Lint + formato | `make lint` / `make fmt` |
| `ty` | Verificación de tipos | `make typecheck` |
| `pytest` | Pruebas | `make test` |
| pre-commit | Hooks antes del commit | `make pre-commit` |
| GitHub Actions | CI (lint + tipos + pruebas) | `.github/workflows/ci.yml` |

- Ningún commit se salta los hooks (`--no-verify` prohibido salvo causa
  justificada y documentada).
- La CI debe estar en verde antes de fusionar un Pull Request.
- `make check` = lint + typecheck + pruebas. `make ci` = `check` + demo offline.

## 7. Arquitectura de datos (Medallion)

```text
data/raw/html/<hash>.html     BRONZE  lo que devolvió la web, tal cual
data/raw/capture.jsonl                url, status, fecha, bytes, sha256
data/raw/urls.jsonl                   plan de captura (sitemap)
data/processed/markdown/*.md  SILVER  solo el texto útil
data/gold/pages/*.md          GOLD    Markdown + frontmatter YAML
data/gold/pages/noticia-*.md  GOLD    fichas de prensa externa verificada
data/gold/pages/hecho-*.md    GOLD    hechos relevantes oficiales
data/gold/corpus.jsonl                metadatos consolidados
data/gold/_NOTICIAS.md                índice de noticias y hechos
data/gold/_REPETIDOS.md               diagnóstico de bloques repetidos (solo medición)
data/noticias/prensa.yaml     FUENTE  curaduría externa (fuera de Gold)
```

### Contrato de la capa Gold

```yaml
---
fuente: https://www.bancodeoccidente.com.co/quienes-somos
titulo: Quiénes somos
seccion: identidad        # identidad | oferta | presencia | datos | atencion | legal | otros
empresa: Banco de Occidente
fecha_captura: 2026-10-23
idioma: es
tokens: 812
hash: 3f9c1a7d
palabras: 190
metodo: trafilatura
keywords: [historia, misión, visión]
---
```

**Reglas del contrato:**

1. Un archivo `.md` por URL, con nombre = slug estable.
2. `##` es frontera de *chunk*: cada trozo debe quedar autocontenido.
3. `corpus.jsonl` es la fuente para el índice y para el RAG.
4. El hash del cuerpo detecta duplicados y permite re-scrapear solo lo cambiado.
5. Gold **nunca** se edita a mano: se regenera con `make gold`.
6. La deduplicación de Gold es **solo de medición**. `make repetidos` analiza
   `data/gold/pages/*.md` en modo lectura y escribe únicamente
   `data/gold/_REPETIDOS.md`; no elimina líneas ni reescribe páginas,
   `corpus.jsonl`, `documents.jsonl` o `videos.jsonl`. Esto es distinto de la
   limpieza de Silver (`find_boilerplate`), que sí elimina boilerplate antes de
   escribir el Markdown procesado.
7. El reporte registra las 183 páginas web analizadas, el texto repetido en al
   menos 5/10/20 páginas (22.3 %, 16.8 % y 9.1 %) y el top 20 de bloques. Es
   un diagnóstico reproducible y offline, no una autorización para borrar
   contenido del corpus.

### Fichas de noticias y hechos relevantes

Las fichas de noticias viven en `data/gold/pages/noticia-*.md` (prensa externa
verificada) y `data/gold/pages/hecho-*.md` (hechos oficiales). Su frontmatter
sigue el contrato:

```yaml
---
id: hecho-2026-10-19-emision-de-valores
tipo: hecho              # hecho | noticia
origen: oficial          # oficial | prensa
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

Reglas de las fichas:

1. `noticia-*` es prensa externa con `estado: verificado`; `hecho-*` es
   comunicación oficial. Una ficha `pendiente` no se publica.
2. El cuerpo solo contiene título, medio, fecha, enlace al origen y resumen
   propio. Nunca se copia el cuerpo del artículo, imágenes, audio ni PDFs.
3. Si el anexo oficial ya existe en `documents.jsonl`, se añaden
   `documento_id`, `documento_archivo` y `documento_titulo` y el enlace relativo
   `../documents/<archivo>.md`; si no existe, se conserva `anexo` sin descargar.
4. `_NOTICIAS.md` resume la ventana, los conteos por tipo/origen/año/medio y la
   tabla de fichas publicadas. `corpus.jsonl` recibe las filas `noticia-*` y
   `hecho-*` junto con las filas del sitio.
5. La curaduría externa vive en `data/noticias/prensa.yaml`, fuera de Gold, para
   que `make clean` no la destruya.
6. La tabla de accionistas se ignora y el título/resumen pasan validación de PII
   antes de escribir.
7. La regeneración es `make noticias`, independiente de `make all`, `make gold`,
   `make deliver`, `make docs`, `make docs-finanzas`, `make videos` y `make media`.

### Reprocesabilidad

`make clean && make extract && make gold` reconstruye Silver y Gold desde Bronze
sin volver a la web. Bronze nunca se edita a mano.

**Límite actual:** el checkout versiona Bronze con **1 HTML**, Silver con **0
archivos** y Gold con **183 páginas web** del sitio (243 archivos en `pages/`,
contando 40 `hecho-*` y 20 `noticia-*`). Por eso hoy ese comando no puede
regenerar las 183 páginas del sitio; el Gold versionado es la única fuente
disponible para medir. Recuperar esa capacidad exige re-capturar Bronze con
`make all` (ver §14).

### Capa Knowledge (conocimiento semántico)

Sobre Gold se deriva una capa de conocimiento **verificable**:

```text
data/knowledge/entities.jsonl    entidades canónicas (ent:...)
data/knowledge/facts.jsonl       hechos atómicos (fact:...)
data/knowledge/relations.jsonl   relaciones (rel:...)
data/knowledge/chunks.jsonl      segmentos por encabezado (derivado, no se versiona)
data/knowledge/_INDICE.md        conteos y revisión
config/knowledge.schema.json     contrato JSON Schema 2020-12
```

**Reglas:**

1. Todo hecho o relación lleva `evidence` con `url`, `page_id`, `chunk_id`,
   `section` y `quote`.
2. La cita debe aparecer **dentro del chunk**; el validador lo comprueba.
3. Sin cita no hay registro; no se infiere conocimiento entre páginas.
4. Sin datos personales (correos, celulares, documentos).
5. Todo entra con `review: "pending"`; solo una persona lo pasa a `approved`.
6. Knowledge se regenera desde Gold + extractor; Gold sigue siendo la verdad.

Comandos: `make chunks` (segmenta) y `make knowledge` (valida + índice).
Borradores: `uv run corpus knowledge --file <jsonl>` y `--merge <jsonl>`.
La skill responsable es `.opencode/skills/semantic-extraction/`.

### Documentos PDF y videos

| Capa | Ruta | Contenido |
|---|---|---|
| Bronze | `data/raw/documents/*.pdf` | PDF tal como se descargó |
| Bronze | `data/raw/documents_capture.jsonl` | url, sha256, bytes, título, categoría, año |
| Gold | `data/gold/documents/*.md` | texto por página + frontmatter (`tipo: pdf`) |
| Gold | `data/gold/documents.jsonl` | índice de documentos |
| Bronze | `data/raw/videos/` | metadatos y subtítulos `.vtt` |
| Gold | `data/gold/videos/*.md` | transcripción + frontmatter (`tipo: video`) |
| Gold | `data/gold/videos.jsonl` | índice de videos |

Reglas:

1. Solo se descargan documentos **públicos** enlazados desde el sitio; `robots.txt`
   se respeta host por host.
2. Selección por prioridad: estados financieros, informes de gestión y gobierno
   corporativo recientes primero; tope configurable (`--max-mb`, por defecto 400).
3. PDFs escaneados sin texto se omiten y se registran (no se inventa contenido).
4. Videos: solo se transcriben si existe subtítulo (manual o automático). Sin
   subtítulo, el video no entra al corpus.
5. El texto de un PDF se parte por página (`## Pagina N`) para conservar la
   trazabilidad.

Comandos: `make docs`, `make videos`, `make media`.

### Capa Contexto (prompt del asistente)

Sobre Gold se deriva el **prompt de sistema** del asistente Q&A:

```text
data/contexto/contexto_banco.md   CONTEXTO  páginas Gold unidas en un solo Markdown
data/contexto/manifest.json       CONTEXTO  qué entró, qué quedó fuera y por qué
config/contexto.toml              FUENTE    secciones, prioridad y presupuesto
```

**Contrato del archivo:**

```markdown
# Contexto del Banco de Occidente

Documento generado a partir de data/gold. No editar a mano: make contexto.

## Información común del sitio
Fuente: data/gold/pages/*.md
Sección: varias

<líneas repetidas>
...

## Quiénes Somos | Banco de Occidente
Fuente: https://www.bancodeoccidente.com.co/quienes-somos
Sección: identidad

<cuerpo Gold sin frontmatter, con los encabezados degradados un nivel>
```

**Reglas:**

1. Solo lee `data/gold/corpus.jsonl` y `data/gold/pages/*.md`. Nunca Bronze,
   Silver ni la web; `documents/` y `videos/` quedan fuera por contrato
   (motivo `fuente_no_pagina`).
2. Se quita el frontmatter YAML y los encabezados del cuerpo bajan **un nivel**
   (`##` → `###`, `###` → `####`) fuera de bloques de código. Solo en memoria:
   Gold no se modifica. Así `##` marca únicamente bloques y **cada línea que
   empieza con `## ` va seguida de su `Fuente:`** (57 páginas de Gold traen `##`
   propios en el cuerpo).
3. Orden determinista: prioridad de sección y luego título. La misma entrada
   produce el mismo archivo, sin fechas ni rutas absolutas.
4. Primero se descartan los cuerpos clonados (hash del cuerpo) y **después** se
   calculan las líneas repetidas de menú/pie, para que los clones no inflen el
   conteo. Esas líneas **no se pierden**: se conservan una vez en
   `## Información común del sitio` (teléfonos de atención, avisos).
5. Fichas `noticia-*`/`hecho-*`: solo las `max_noticias` más recientes por
   `fecha_publicacion`; una ficha `pendiente` no se publica.
6. El presupuesto se mide con `utils.stable_tokens` (chars/4, sin red). El tope
   por defecto es `max_tokens = 175000` (`config/contexto.toml`); si el texto
   excede ese tope, se descartan primero las secciones de menor
   prioridad y se informa en consola y en el manifest. Si aun sin páginas el
   preámbulo y el bloque común no caben, el comando termina con error y **no
   escribe** el archivo.
7. `manifest.json` lista incluidas, excluidas con motivo
   (`fuente_no_pagina`, `archivo_ausente`, `ficha_excluida`, `ficha_pendiente`,
   `ficha_fuera_de_ventana`, `url_excluida`, `seccion_no_incluida`,
   `cuerpo_vacio`, `duplicado`, `presupuesto`) y tokens por sección.
8. El módulo no hace peticiones de red: solo lee Gold y mide con
   `stable_tokens`.

Comando: `make contexto` (`uv run python -m banco_occidente_corpus.contexto`).
Es independiente de `make all`, `make gold`, `make deliver`, `make docs`,
`make videos` y `make media`. `make clean` no toca `data/contexto/`: es un
artefacto versionado y reproducible que se reconstruye con `make contexto`.

## 8. Repositorio y Git

- **El corpus vive en este mismo repositorio.** No hay un repo aparte: Gold se
  versiona en `data/gold/` y se publica junto con el código.
- **Remoto:** `https://github.com/Darley843/Proyecto_BancoO.git` (privado).
- **Rama principal:** `main`.
- **Ramas:** `feat/...`, `fix/...`, `docs/...`, `refactor/...`, `test/...`,
  `chore/...`; integración por Pull Request.
- **Commits:** [Conventional Commits](https://www.conventionalcommits.org/) —
  `feat:`, `fix:`, `docs:`, `refactor:`, `style:`, `test:`, `chore:`.
- **Identidad git (capturada):**

  ```ini
  [user]
      name = Darley843
      email = darley.idarraga@uao.edu.co
  ```

  Se fija en el repositorio con `make identity`; el detalle de la cuenta se
  verifica con `make whoami`.

## 9. Flujo diario

```bash
# 1. Ver cambios
git status

# 2. Verificación completa
make check

# 3. Captura (si hace falta) y regeneración
make doctor          # red + robots.txt + estado
make all             # discover -> fetch -> extract -> gold -> stats
make noticias        # hechos oficiales y prensa curada
make contexto        # prompt del asistente desde Gold (data/contexto/)

# 4. Commit (los hooks corren solos)
git add -A
git commit -m "tipo: mensaje descriptivo"

# 5. Subir
git push
```

## 10. Identificación y cortesía (decisión local)

El sitio está detrás de un WAF (CloudFront) que **responde 403 a cualquier
User-Agent que se declare bot**, aunque `robots.txt` permita el contenido. Se
verificó empíricamente: `TAAML-bot/1.0` → 403; UA de navegador → 200.

Decisión:

- `User-Agent`: cadena de un navegador real (Chrome estable), definida en
  `config/site.toml`.
- Identificación académica: header HTTP **`From`** (RFC 9110 §10.1.2) con el
  correo del autor, enviado en **cada** petición.
- Ritmo de cortesía **del proyecto**: 1,5 s entre peticiones + pausa de 10 s
  cada 50. `robots.txt` del banco **no declara `Crawl-delay`**: el valor es una
  decisión propia, no una directiva del sitio.
- `robots.txt` se parsea y sus `Disallow` se excluyen por código.
- El HTML crudo se conserva para no repetir peticiones.
- **No hay fallback con navegador.** Ante un `403` persistente el pipeline se
  detiene con código 2: usar Chromium para saltar el WAF sería evasión y la
  regla del curso lo prohíbe. Se documentó la limitación y se eliminó el extra
  `browser` (Playwright).

Esto no es evasión: es la única forma de acceder a contenido público que el
propio `robots.txt` permite, manteniendo identificación y cortesía.

## 11. Historial de decisiones técnicas

| Fecha | Decisión | Motivo |
|-------|----------|--------|
| 2026-10-23 | `uv` como gestor único (sin `pip` ni `requirements.txt`) | Reproducibilidad y regla dura del curso |
| 2026-10-23 | Arquitectura Medallion con Gold versionado | Separar captura de interpretación; el RAG consume solo Gold |
| 2026-10-23 | `httpx` en vez de `requests` | HTTP/2, timeouts y reintentos con una sola dependencia |
| 2026-10-23 | `trafilatura` como extractor principal, BeautifulSoup como fallback | Extracción semántica con respaldo cuando no hay artículo |
| 2026-10-23 | Clasificación por reglas sobre URL + título | Explicable y auditable; sin costo ni caja negra |
| 2026-10-23 | UA de navegador + header `From` | El WAF bloquea UA declarados bot; ver §10 |
| 2026-10-23 | Tareas del Makefile en `scripts/tasks.py` | El mismo comando funciona en Windows y Unix (sin grep/awk/rm) |
| 2026-10-23 | Bronze y Silver ignorados por Git; Gold versionado | Tamaño y reproducibilidad frente al entregable |
| 2026-10-23 | `demo` offline con fixture | Validar el pipeline completo sin red ni riesgo para el sitio |
| 2026-10-23 | Capa **Knowledge** con entidades, hechos y relaciones, cada uno con cita textual | El agente debe responder con fuente verificable, no con paráfrasis |
| 2026-10-23 | Validación con JSON Schema + comprobación de la cita contra el chunk | Un esquema solo no detecta citas inventadas; la evidencia se valida en el texto |
| 2026-10-23 | Chunks deterministas por encabezado (`chk:<hash>`) | Evidencia atómica y estable para el RAG y para el validador |
| 2026-10-24 | Documentos PDF en Gold con `pypdf` y una sección por página | Los balances e informes no están en HTML; el PDF conserva tablas y cifras |
| 2026-10-24 | Videos solo si hay subtítulos (`yt-dlp`) | Transcribir a mano no es reproducible; sin subtítulo no hay fuente |
| 2026-10-24 | Descarga de documentos priorizada y con tope de MB | Hay 622 PDFs históricos; se captura lo reciente y relevante sin saturar el sitio |
| 2026-10-24 | Noticias en Gold: hechos oficiales y prensa externa curada, con enlace de solo lectura a documentos | El sitio no tiene sala de prensa; la actualidad vive en la tabla de inversionistas y en medios externos |
| 2026-10-24 | Fichas de prensa con resumen propio y verificación humana antes de publicar | Respeta derechos de autor y evita publicar enlaces o fechas sin confirmar |
| 2026-10-24 | Descarga con `httpx` (`HttpClient` de `net.py`) en vez del `Fetcher` de Scrapling que propone la guía del curso; Scrapling queda solo como servidor MCP del agente (grupo `mcp`) | El pipeline ya descarga con `HttpClient`, que aplica User-Agent, header `From`, `Crawl-delay`, reintentos y caché en Bronze; el motivo por el que no se adoptó Scrapling en el pipeline está pendiente de confirmar |
| 2026-10-25 | Limitación conocida: `urllib.robotparser` no interpreta comodines (`/*!ut/p*`) del `robots.txt` del banco | `RobotFileParser` solo compara prefijos literales; se verificó que ninguna URL de `corpus.jsonl`, `documents.jsonl` ni `videos.jsonl` coincide con las rutas prohibidas |
| 2026-10-25 | `/ayuda/agendar-cita-asesor` fuera de Gold: es un formulario | `AGENTS.md` prohíbe capturar formularios; el filtro de `exclude_patterns` se aplica también al construir Gold para que una página ya capturada no vuelva al entregable |
| 2026-10-25 | Los 1,5 s entre peticiones son decisión del proyecto, no un `Crawl-delay` del sitio | `robots.txt` del banco no declara `Crawl-delay`; la documentación lo aclara para no atribuirle al sitio una directiva que no existe |
| 2026-10-25 | Se elimina el fallback con Playwright (`--browser`) y el mínimo de 1,5 s se impone en `net.py` | Un navegador headless eludiría el WAF (evasión prohibida); el ritmo no puede bajarse desde el CLI ni desde una config relajada |
| 2026-10-25 | Capa **Contexto** derivada de Gold y versionada (`data/contexto/`) | Es el artefacto que evalúa la rúbrica y el prompt del asistente; al clonar debe funcionar sin regenerar. `make clean` no la borra: se reconstruye con `make contexto` |
| 2026-10-25 | El contexto no pasa por `cli.py`: se ejecuta con `uv run python -m banco_occidente_corpus.contexto` | Mantiene el cambio autocontenido: el CLI del pipeline no se modifica, y la configuración y las rutas del contexto viven en `contexto.py` |
| 2026-10-25 | El contexto usa `stable_tokens` (chars/4) y no importa `tiktoken` | El tokenizador de OpenAI descarga datos la primera vez y no es el del modelo servido; el estimador es determinista, sin red e igual en la CI |
| 2026-10-25 | Boilerplate del contexto a `0.10` (Gold usa `0.35`) y bloque `Información común del sitio` | Con `0.35` no se detectaba ninguna línea; con `0.10` se retiran 26 CTAs. Las líneas retiradas se conservan una vez para no perder datos repetidos (teléfonos de atención) |
| 2026-10-25 | Los encabezados del cuerpo se degradan un nivel al renderizar el contexto (`##`→`###`) | 57 páginas de Gold traen `##` propios; degradarlos deja `##` como frontera exclusiva de bloque, sin editar Gold |

## 12. Configuración local (no trackear)

- `.env`, tokens y credenciales **nunca** se versionan (`.gitignore`).
- El repositorio vive en Windows (`D:\Documentos_Loni\...`); los comandos del
  Makefile se probaron en PowerShell con GNU Make.
- Para GitHub CLI: `gh auth login` o exportar `GITHUB_TOKEN`; el Makefile no
  guarda el token.

## 13. Ética y legalidad

- Solo información **pública**; se respeta `robots.txt` y los términos de uso.
- Nada de datos personales (Ley 1581 de 2012).
- Sin martilleo: 1.5 s entre peticiones y pausas periódicas.
- El corpus se usa con fines académicos y se cita la fuente en cada documento
  (`fuente` en el frontmatter).

## 14. Pendientes

- [x] Pipeline Bronze → Silver → Gold con `uv`.
- [x] Checklist de 24 casillas y reporte `_INDICE.md`.
- [x] Makefile portable y diagnóstico de red.
- [x] Skill `semantic-extraction`, esquema JSON y validador de evidencia.
- [x] Documentos PDF (balances e informes) y videos con subtítulos.
- [ ] Poblar Knowledge para todas las secciones (semilla actual: identidad).
- [ ] Re-capturar Bronze para poder regenerar desde cero las 183 páginas web del
  sitio (hoy Bronze conserva 1 HTML y Silver está vacío).
- [ ] Procesar los 622 PDFs históricos restantes (hoy se captura 2022–2026).
- [ ] Transcripciones de YouTube de todo el canal (hoy, las más recientes).
- [ ] Chunking + embeddings para el Módulo 2 (Fase 4).
- [ ] Configurar protección de `main` (PR + CI verde). **Bloqueado**: GitHub
  exige plan Pro (o repo público) para proteger ramas en repos privados; la API
  devuelve 403. Se retoma cuando el grupo decida publicar el repo o subir de plan.
