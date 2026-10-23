# Corpus web — Banco de Occidente

Pipeline de extracción y limpieza del sitio público de **Banco de Occidente**
(`https://www.bancodeoccidente.com.co`) siguiendo el estándar de la Clase 2:
arquitectura **Medallion** (Bronze → Silver → Gold), `trafilatura`,
`corpus.jsonl` y gestión del proyecto con **uv**.

El resultado es el corpus que alimenta el RAG y el agente de los Módulos 2 y 3
del Taller 1.

---

## Requisitos

- Python 3.12 o 3.13 (uv lo instala si falta)
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
| `make all` | Pipeline completo |
| `make stats` | Resumen y checklist → `data/gold/_INDICE.md` |
| `make status` | Cuenta URLs/Bronze/Silver/Gold |
| `make test` / `make check` | Pruebas / lint + pruebas |
| `make clean` | Borra Silver y Gold (conserva el crudo) |
| `make clean-all` | Borra todas las capas |
| `make identity` | Fija `user.name` y `user.email` del repo |
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
│   └── documents.jsonl     #   PDFs detectados (fase posterior)
├── processed/              # SILVER — solo el texto útil, en Markdown
│   ├── markdown/           #   un .md por página
│   └── silver.jsonl        #   + título, sección, método, chars
└── gold/                   # GOLD — lo único que entra al RAG
    ├── pages/              #   un .md por página con frontmatter YAML
    ├── corpus.jsonl        #   metadatos consolidados
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
- `Crawl-delay` y pausa de 1.5 s entre peticiones (configurable).
- `User-Agent` identificable con contacto académico.
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
3. Fingerprint TLS de bot (curl, httpx, requests).

Diagnóstico: `make doctor`. Solución: **desconecta la VPN** y ejecuta desde una
conexión residencial colombiana. Si el HTML carga pero el texto sale vacío,
la página necesita JavaScript:

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
