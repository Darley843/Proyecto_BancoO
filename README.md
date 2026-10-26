# Corpus web — Banco de Occidente

Pipeline de extracción y limpieza del sitio público de **Banco de Occidente**
(`https://www.bancodeoccidente.com.co`) siguiendo el estándar de la Clase 2:
arquitectura **Medallion** (Bronze → Silver → Gold), `trafilatura`,
`corpus.jsonl` y gestión del proyecto con **uv**.

El resultado es el corpus que alimenta el RAG y el agente de los Módulos 2 y 3
del Taller 1.

**Documentación**

| Documento | Contenido |
|---|---|
| [`CONSTITUTION.md`](./CONSTITUTION.md) | Verdad central: alcance, stack, convenciones y decisiones |
| [`docs/ESTANDAR.md`](./docs/ESTANDAR.md) | Trazabilidad regla de la clase → implementación |
| [`docs/FUENTES.md`](./docs/FUENTES.md) | Inventario de fuentes, `robots.txt` y hallazgos del sitio |
| [`docs/IDENTIDAD.md`](./docs/IDENTIDAD.md) | Identidad de Git y GitHub del autor |
| [`AGENTS.md`](./AGENTS.md) | Contexto y reglas para agentes LLM |
| [`.opencode/skills/corpus-extraction/`](./.opencode/skills/corpus-extraction/SKILL.md) | Skill operativa del pipeline (flujo, diagnóstico, healthcheck) |
| [`.opencode/skills/semantic-extraction/`](./.opencode/skills/semantic-extraction/SKILL.md) | Skill de extracción semántica (entidades, hechos y relaciones) |
| [`docs/CONSTITUTION-curso-TAAML.md`](./docs/CONSTITUTION-curso-TAAML.md) | Estándar del curso (documento original) |

## Resultado de la captura (2026-10-23)

| Métrica | Valor |
|---|---:|
| Sitemaps leídos | 210 |
| URLs públicas | 196 |
| Páginas Bronze | 193 (102.3 MB) |
| Páginas Gold | 184 |
| Documentos PDF | 190 (11.0 M tokens) |
| Videos transcritos | 32 (119.8 k tokens) |
| Tokens del corpus completo | 11.2 M |
| Cobertura del checklist | 24/24 (con evidencia) |

El detalle y las decisiones están en [`docs/FUENTES.md`](./docs/FUENTES.md).
El entregable se regenera con `make all` y se empaqueta con `make deliver`.

**El corpus vive en este mismo repositorio.** Gold (`data/gold/`) se versiona
porque es el entregable que consume el RAG; Bronze y Silver son reproducibles y
se regeneran sin volver a la web (`make clean && make extract && make gold`).
No hay un repositorio aparte para el corpus.

## Capa Knowledge (conocimiento verificable)

Sobre Gold se construye una capa semántica: entidades, hechos y relaciones, cada
uno con su cita textual. Es lo que permite que el agente responda **con fuente**
y no con paráfrasis.

```bash
make chunks      # ~14.300 chunks de 406 documentos (páginas + PDFs + videos)
make knowledge   # valida esquema + evidencia y actualiza el índice
```

| Archivo | Contenido |
|---|---|
| `data/knowledge/entities.jsonl` | Entidades canónicas (`ent:...`) |
| `data/knowledge/facts.jsonl` | Hechos atómicos (`fact:...`) |
| `data/knowledge/relations.jsonl` | Relaciones (`rel:...`) |
| `data/knowledge/_INDICE.md` | Conteos y pendientes de revisión |
| `config/knowledge.schema.json` | Contrato JSON Schema |

El estado actual es una **semilla validada** (2 entidades, 5 hechos, 1 relación)
extraída de las páginas de identidad. El resto se puebla con la skill
`semantic-extraction`, sección por sección. Regla dura: si la cita no está en el
chunk, el validador rechaza el registro.

## Documentos y videos

Los balances, informes de gestión y documentos de gobierno corporativo no están
en HTML: viven en PDF. Los videos aportan la parte cualitativa (entrevistas,
vocería) que no aparece escrita.

```bash
make docs      # 622 PDFs inventariados -> descarga priorizada -> Gold
make videos    # canal @BancodeOccidenteCol + videos enlazados -> Gold
make media     # ambos
```

| Regla | Implementación |
|---|---|
| Solo documentos públicos enlazados desde el sitio | `documents.discover_documents()` + `robots.txt` |
| Prioridad por año y categoría | financiero/gobierno 2024+ primero; tope `--max-mb 400` |
| Texto por página | `pypdf` y encabezados `## Pagina N` |
| PDF escaneado sin texto | se omite y se registra |
| Video sin subtítulos | no entra al corpus |
| Trazabilidad | `documents_capture.jsonl` y `videos_capture.jsonl` con URL y hash |

## Noticias y hechos relevantes

La actualidad corporativa se publica como fichas Gold: hechos oficiales de la
tabla **“Información Relevante”** y prensa externa curada. `make noticias` es
independiente: no forma parte de `make all`, `make gold`, `make deliver`,
`make docs`, `make docs-finanzas`, `make videos` ni `make media`.

```bash
make noticias                              # usa Bronze; si falta, una petición puntual
uv run corpus noticias --sin-red           # solo Bronze y curaduría, sin red
uv run corpus noticias --desde 2025-01-01 --hasta 2026-10-24
```

Las fichas quedan en `data/gold/pages/noticia-*.md` y `hecho-*.md`, con su fila
en `corpus.jsonl` y el índice `data/gold/_NOTICIAS.md`. La curaduría externa
vive en `data/noticias/prensa.yaml`; `make clean` no la borra. Si el sitio
responde `403`, el comando se detiene y avisa: no cambia User-Agent, proxies ni
velocidad de las peticiones.

---

## Requisitos

- Python 3.13 (uv lo instala si falta)
- [uv](https://docs.astral.sh/uv/) — único gestor permitido
- `make` (GNU Make 4.x)
- Red con salida **colombiana**. El sitio está detrás de CloudFront y rechaza
  con `403` el tráfico de VPN, datacenters y bots. Ver
  [Solución de problemas](#el-sitio-devuelve-403).

## Inicio rápido

```bash
make init       # instala Python, dependencias y extras
make doctor     # verifica red, robots.txt y estado de las capas
make demo       # prueba el pipeline completo con una página local (sin red)
make all        # scraping real: discover -> fetch -> extract -> gold -> stats
```

Cuando termine, abre `data/gold/_INDICE.md`: ahí está el resumen, los
documentos por sección y la cobertura del checklist del Taller 1.

---

## Comandos

| Comando | Qué hace |
|---|---|
| `make init` | Instala el entorno (`uv python install` + `uv sync --all-extras`) |
| `make doctor` | Diagnóstico de red, `robots.txt` y estado del pipeline |
| `make discover` | Lee `robots.txt` y expande el `sitemap.xml` |
| `make fetch` | Descarga el HTML crudo → `data/raw/` (Bronze) |
| `make extract` | Limpia y convierte a Markdown → `data/processed/` (Silver) |
| `make gold` | Añade metadatos y consolida `corpus.jsonl` (Gold) |
| `make chunks` | Segmenta Gold en chunks por encabezado |
| `make knowledge` | Valida entidades/hechos/relaciones y escribe el índice |
| `make docs` | Inventaría, descarga y extrae PDFs (balances, informes) |
| `make videos` | Lista el canal, baja subtítulos y transcribe a Gold |
| `make media` | Documentos PDF + videos |
| `make noticias` | Hechos oficiales y prensa curada a Gold (independiente del pipeline) |
| `make all` | Pipeline completo |
| `make stats` | Resumen y checklist → `data/gold/_INDICE.md` |
| `make status` | Cuenta URLs/Bronze/Silver/Gold |
| `make test` / `make check` | Pruebas / lint + tipos + pruebas |
| `make health` | Integridad de Bronze/Silver/Gold y del contrato de Gold |
| `make ci` | Lo mismo que corre GitHub Actions (check + demo) |
| `make deliver` | Gold + índice + ZIP del entregable en `dist/` |
| `make clean` | Borra Silver y Gold (conserva el crudo) |
| `make clean-all` | Borra todas las capas |
| `make identity` | Fija `user.name` y `user.email` del repo |
| `make whoami` | Muestra la identidad de Git y el remoto |
| `make remote` | Configura `origin` (`OWNER=`, `REPO=`) |
| `make repo` | Crea el repositorio en GitHub (requiere `GITHUB_TOKEN`) |

El CLI también se usa directo:

```bash
uv run corpus discover
uv run corpus fetch --limit 50 --delay 2
uv run corpus all --limit 100
uv run corpus status
```

---

## Arquitectura del corpus

```
data/
├── raw/                    # BRONZE — lo que devolvió la web, tal cual
│   ├── html/               #   un .html por URL (nombre = hash de la URL)
│   ├── urls.jsonl          #   plan de captura: url, fuente, fecha
│   ├── capture.jsonl       #   url, status, fecha, bytes, sha256, archivo
│   ├── documents/          #   PDFs descargados
│   ├── videos/             #   metadatos y subtítulos .vtt
│   ├── documents_urls.jsonl / documents_capture.jsonl
│   └── videos_urls.jsonl / videos_capture.jsonl
├── processed/              # SILVER — solo el texto útil, en Markdown
│   ├── markdown/           #   un .md por página
│   └── silver.jsonl        #   + título, sección, método, chars
└── gold/                   # GOLD — lo único que entra al RAG
    ├── pages/              #   un .md por página HTML
    ├── documents/          #   un .md por PDF (balances, informes)
    ├── videos/             #   un .md por video transcrito
    ├── corpus.jsonl        #   metadatos de páginas
    ├── documents.jsonl     #   metadatos de PDFs
    ├── videos.jsonl        #   metadatos de videos
    └── _INDICE.md          #   reporte y checklist
```

**Por qué capas.** Capturar e interpretar están separados: si mejoras el
limpiador, regeneras Silver y Gold sin volver a pedirle 800 páginas al sitio.
Bronze es el respaldo histórico y nunca se edita a mano.

### Formato Gold

Cada página en `data/gold/pages/` es Markdown con frontmatter:

```yaml
---
fuente: https://www.bancodeoccidente.com.co/quienes-somos
titulo: Quiénes somos
seccion: identidad
empresa: Banco de Occidente
fecha_captura: 2026-10-23
idioma: es
tokens: 812
hash: 3f9c1a7d
palabras: 190
metodo: trafilatura
keywords: [historia, misión, visión, oficinas]
---
# Quiénes somos
## Misión
...
```

Los encabezados son fronteras de *chunk*: al partir por `##`, cada trozo queda
autocontenido. Los metadatos permiten filtrar por sección, citar la URL de
origen y saber qué re-scrapear.

---

## Qué se captura

| Sección | Contenido |
|---|---|
| `identidad` | Quiénes somos, misión, visión, historia, junta, directivos, sedes |
| `oferta` | Productos y servicios: cuentas, tarjetas, créditos, seguros, CDTs |
| `presencia` | Noticias, sala de prensa, blog, comunicados |
| `datos` | Informes, sostenibilidad, inversionistas, tarifas |
| `atencion` | Canales, sucursales, PQRS, contacto |
| `legal` | Términos, políticas, habeas data |

`make stats` evalúa las **24 casillas** del checklist del Taller 1 y marca
cuáles ya tienen evidencia en el corpus.

---

## Ética y legalidad

- Se respeta `robots.txt`: lo que está en `Disallow` no se toca
  (`/portaltransaccional/`, `/icbs-web/`, `/AjaxTx`, `/wps/`).
- Ritmo de cortesía de 1,5 s entre peticiones (decisión del proyecto;
  `robots.txt` no declara `Crawl-delay`) y pausa de 10 s cada 50.
- Identificación en cada petición: UA de navegador + header HTTP `From` con el
  contacto académico. El WAF del sitio responde `403` a cualquier UA que se
  declare bot, aunque `robots.txt` permita el contenido (ver `CONSTITUTION.md`
  §10).
- Solo información **pública**. Nada de zonas privadas, datos tras login ni
  datos personales (Ley 1581 de 2012 — Habeas Data).
- El HTML crudo se conserva para poder reprocesar sin volver a molestar al
  servidor.

---

## Solución de problemas

### El sitio devuelve 403

```
ERROR  Request blocked. We can't connect to the server for this app...
```

CloudFront rechaza la petición antes de llegar al origen. Causas:

1. **VPN activa** con salida fuera de Colombia (es la causa más común).
2. Red de datacenter, contenedor o CI.
3. Un `User-Agent` que se declara bot: el WAF responde `403` aunque
   `robots.txt` permita la página.

Diagnóstico: `make doctor`. Solución:

- Desconecta la VPN y ejecuta desde una conexión residencial colombiana.
- No cambies el UA a uno de bot: el proyecto ya usa un UA de navegador y envía
  la identificación académica en el header `From` (configurable en
  `config/site.toml`).

Si el HTML carga pero el texto sale vacío, la página necesita JavaScript:

```bash
make browser
uv run corpus fetch --browser --limit 20
```

### `make` no existe en Windows

```powershell
winget install ezwinports.make
# o
choco install make
```

En PowerShell también puedes usar `uv run corpus <comando>` sin `make`.

### Playwright no encuentra Chromium

```bash
uv run playwright install chromium
```

---

## Identidad de Git

```bash
make identity
# user.name  = Darley843
# user.email = darley.idarraga@uao.edu.co
```

Variables en el Makefile: `GIT_USER`, `GIT_EMAIL`, `REPO`.

---

## Estructura del proyecto

```
├── config/site.toml          # alcance, cortesía, filtros, secciones
├── makefile                  # todos los comandos
├── pyproject.toml            # proyecto uv (PEP 621)
├── uv.lock                   # versiones exactas (se versiona)
├── .python-version           # 3.13
├── CONSTITUTION.md           # verdad central del proyecto
├── AGENTS.md                 # contexto para agentes LLM
├── .github/workflows/ci.yml  # lint + formato + pruebas
├── .pre-commit-config.yaml   # hooks de calidad
├── src/banco_occidente_corpus/
│   ├── cli.py                # discover | fetch | extract | gold | stats
│   ├── config.py             # carga de site.toml y rutas
│   ├── discover.py           # robots.txt + sitemap index recursivo
│   ├── net.py                # httpx con reintentos y backoff
│   ├── fetch.py              # Bronze
│   ├── extract.py            # Silver (trafilatura + fallback)
│   ├── dedupe.py             # boilerplate repetido
│   ├── section.py            # clasificación en secciones
│   ├── gold.py               # Gold + frontmatter
│   ├── checklist.py          # 24 casillas del Taller 1
│   └── stats.py              # _INDICE.md
├── scripts/
│   ├── demo_offline.py       # pipeline con fixture, sin red
│   └── scrape_empresa.py     # scraper autocontenido (PEP 723)
└── test/                     # pytest + fixtures
```

---

## Referencias

- [uv — documentación](https://docs.astral.sh/uv/)
- [trafilatura](https://trafilatura.readthedocs.io/)
- [robots.txt — especificación](https://www.rfc-editor.org/rfc/rfc9309)
- [Sitemaps protocol](https://www.sitemaps.org/protocol.html)
