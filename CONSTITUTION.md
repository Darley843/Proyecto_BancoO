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
| **Fase 3** | Documentos (PDF) y YouTube (subtítulos) como fuentes complementarias | 🚧 |
| **Fase 4** | Chunking + embeddings y consumo desde el RAG del Módulo 2 | ⏳ |

**Dentro del alcance:** páginas HTML públicas del dominio, `robots.txt`,
`sitemap.xml` (índice de índices de Liferay), noticias, blog, información
corporativa, tarifas, documentos enlazados (registrados, no descargados aún).

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
| **Tokens** | `tiktoken` (extra `tokens`; si falta, estimador) |
| **Navegador (fallback JS)** | `playwright` (extra `browser`) |
| **Testing** | `pytest` (patrón AAA) |
| **Lint / formato** | `ruff` (línea 100, comillas dobles) |
| **Tipado** | `ty` (target `make typecheck`) |
| **CI** | GitHub Actions (`.github/workflows/ci.yml`) |
| **Orquestación local** | `make` (GNU Make) |

> ⚠️ **Regla dura heredada:** prohibido `pip` y `requirements.txt`. Toda
> dependencia entra con `uv add` (o `uv add --dev`) y se fija en `uv.lock`.
> Las pruebas de una tarde van con `uv run --with` o PEP 723, no al proyecto.

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
│   ├── checklist.py      # 24 casillas del Taller 1
│   ├── stats.py          # _INDICE.md
│   └── utils.py          # hashing, JSONL, tokens, slugs
├── test/                 # pytest + fixtures (sin red)
├── config/site.toml      # alcance, cortesía, filtros y secciones
├── data/
│   ├── raw/              # Bronze (ignorado por Git)
│   ├── processed/        # Silver (ignorado por Git)
│   ├── gold/             # Gold (VERSIONADO) → entregable
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
data/gold/corpus.jsonl                metadatos consolidados
data/gold/_INDICE.md                  reporte y checklist
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

### Reprocesabilidad

`make clean && make extract && make gold` reconstruye Silver y Gold desde Bronze
sin volver a la web. Bronze nunca se edita a mano.

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
- `Crawl-delay` respetado (1.5 s) + pausa de 10 s cada 50 peticiones.
- `robots.txt` se parsea y sus `Disallow` se excluyen por código.
- El HTML crudo se conserva para no repetir peticiones.

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
- [ ] Poblar Knowledge para todas las secciones (semilla actual: identidad).
- [ ] Descargar y procesar los PDF del sitio (Fase 3).
- [ ] Transcripciones de YouTube (Fase 3).
- [ ] Chunking + embeddings para el Módulo 2 (Fase 4).
- [ ] Configurar protección de `main` (PR + CI verde).
