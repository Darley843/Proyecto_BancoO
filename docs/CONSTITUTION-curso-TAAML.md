# CONSTITUTION — TAAML

> **Verdad central del proyecto.** Este documento define el propósito, el stack, la
> estructura, las convenciones y el flujo de trabajo de `TAAML`. Si algo aquí
> contradice al código o a los decks, el código manda **y este archivo se actualiza**.

> ⚠️ **Directiva de mantenimiento:** cada vez que se realicen cambios significativos
> (nuevas funcionalidades, cambios arquitectónicos, adición de clases/decks o ajustes
> de tecnologías), **se debe actualizar este archivo en el mismo commit** para mantener
> la verdad central del proyecto bien documentada.

---

## 0. Identidad del proyecto

| Campo | Valor |
|-------|-------|
| **Nombre** | TAAML |
| **Nombre completo** | Técnicas Avanzadas de IA aplicadas en Modelos de Lenguaje |
| **Institución** | Universidad Autónoma de Occidente (UAO) — Facultad de Ingeniería |
| **Programa** | Maestría en Inteligencia Artificial y Ciencias de Datos |
| **Código** | 561378 · 3 créditos · Obligatoria · Componente de profundización |
| **Prerrequisitos** | Programación intermedia (Python), *Procesamiento de datos secuenciales*, Fundamentos de Deep Learning |
| **Programa oficial** | `docs/programa-curso-TAAML.md` (Markdown de trabajo) · `docs/programa-curso-TAAML-SIGED-2026.pdf` (SIGED) |
| **Descripción** | Material del curso TAAML: clases (decks Slidev), apuntes, ejemplos de código y recursos. |
| **Repositorio** | https://github.com/hamsomp3/TAAML |
| **Autoría** | Jan Polanco V. — hamsomp3@gmail.com |
| **Licencia** | MIT |
| **Rama principal** | `main` |
| **Estado** | En construcción 🚧 |

## 1. Propósito y no-propósito

### Propósito

Reunir, versionar y mantener el material del curso **Técnicas Avanzadas de IA aplicadas
en Modelos de Lenguaje (TAAML)** de la **Universidad Autónoma de Occidente (UAO)**: las
presentaciones de cada clase (construidas con Slidev), los apuntes y la documentación de
apoyo, los maquetados institucionales para el aula virtual, las rúbricas de evaluación y
los ejemplos de código ejecutables que las acompañan. Está dirigido al docente y a los
estudiantes del curso.

### No-propósito

- No es un **producto de software** ni una librería publicable en PyPI: el paquete
  `taaml` existe solo para alojar y probar los ejemplos del curso.
- No es un **sitio web desplegado** ni reemplaza a la plataforma oficial de gestión del
  curso (LMS, aula virtual, calificaciones).
- No almacena **datos personales de estudiantes** reales (las rúbricas usan *fixtures*
  sintéticos / listas de ejemplo).
- No es un **framework de IA**: se enseñan y demuestran técnicas, no se mantiene una
  librería de producción.

## 2. Alcance

### Dentro del alcance

- **Presentaciones de clase** con Slidev (un deck por sesión, integrados en un monolito).
- **Apuntes y documentación** del temario en `docs/`.
- **Maquetados institucionales** (Moodle) y **rúbricas** de evaluación (UAO).
- **Ejemplos de código** Python ejecutables y probados que demuestran las técnicas.
- **Recursos de apoyo** (imágenes, diagramas, notebooks convertidos a `.py`).
- **Trazabilidad del curso**: Hub de 16 sesiones, temario y estado de cada sesión.

### Fuera del alcance (por ahora)

- Despliegue público de los decks o de un sitio de documentación (existe la config, no el deploy).
- Contenido con datos personales o calificaciones reales.
- Modelos pesados / datasets versionados en el repositorio (se referencian, no se suben).
- Traducciones a otros idiomas.

### Fases

| Fase | Descripción | Estado |
|------|-------------|:------:|
| **Fase 1** | Estandarización del repositorio (estructura, `uv`, Ruff, pre-commit, CI). | ✅ |
| **Fase 2** | Monolito Slidev (`slides/`) con capa UAO, Hub de 16 sesiones y **Archify** activado. | ✅ |
| **Fase 3** | Temario completo (16 clases) y ejemplos de código por técnica. | 🚧 |
| **Fase 4** | Exportación de material (PDF por clase) y publicación opcional. | 🚧 |

### Módulos del curso (según el programa oficial SIGED)

| Módulo | Contenido | Ponderación |
|--------|-----------|:-----------:|
| **Módulo 1** | Introducción a los LLMs e Ingeniería de Prompts | 30% |
| **Módulo 2** | Aplicaciones, Recuperación Semántica y Memoria | 30% |
| **Módulo 3** | Agentes, Productización y Despliegue Avanzado | 40% |

- Evaluación por **talleres incrementales** (Taller 1 = 30%, Taller 2 = 30%, Taller 3 = 40%)
  sobre un proyecto integrador de una empresa del Valle del Cauca, con **sustentación en vivo**
  (sin PowerPoint). Bonus transversal de excelencia científica (t-SNE) de hasta +10% en el M3.
- Metodología **ABP** (*Aprendizaje Basado en Proyectos*) + **live coding**.
- Contenido detallado (1.1–3.6), rúbricas de cada taller y bibliografía:
  [`docs/programa-curso-TAAML.md`](./docs/programa-curso-TAAML.md).
- **Rutas del Módulo 3:** Ruta A (FastAPI + Function Calling + webhooks/n8n + PostgresSaver)
  o Ruta B (Agent OS **OpenFang** con manifiestos `HAND.toml`).

> El **cronograma de las 16 sesiones** tiene **fechas** definidas: **viernes 6:30 p.m. y sábados 8:00 a.m.** La cohorte arrancó el **16/10/2026** (las fechas del **09/10 y 10/10** quedaron suspendidas por fuerza mayor) y cierra el **28/11/2026**. Las dos sesiones suspendidas se **reponen los miércoles 21 y 28 de octubre de 2026, 6:30–9:30 p.m., por Webex** (anuncio 003; enlaces pendientes de la USU) y se **insertan en la secuencia como 3.ª y 6.ª sesión**, no al final. Los **títulos por sesión** siguen pendientes de definir (Clases 1–4 ya los tienen).

## 3. Stack técnico

| Categoría | Tecnología |
|-----------|------------|
| **Lenguaje (ejemplos)** | Python 3.13+ |
| **Gestor de paquetes y entorno (Python)** | [`uv`](https://docs.astral.sh/uv/) |
| **Build backend** | `uv_build` (src-layout) |
| **Paquete Python** | `taaml` |
| **Presentaciones** | [Slidev](https://sli.dev/) (Markdown + Vue + Tailwind) |
| **Gestor de paquetes (presentaciones)** | [`pnpm`](https://pnpm.io/) |
| **Diagramas de arquitectura** | [Archify](https://github.com/tt-a1i/archify) (HTML interactivo en `docs/`) |
| **Librerías de IA (ejemplos)** | EN EVALUACIÓN — se fijan cuando se defina cada clase |
| **Tipado estático** | [`ty`](https://github.com/astral-sh/ty) |
| **Testing** | [`pytest`](https://docs.pytest.org/) |
| **Linting / Formato (Python)** | [Ruff](https://docs.astral.sh/ruff/) |
| **Formato (decks)** | `slidev format` |
| **Pre-commit** | [pre-commit](https://pre-commit.com) |
| **CI/CD** | [GitHub Actions](.github/workflows/ci.yml) |
| **Dependencias automáticas** | [Dependabot](.github/dependabot.yml) |

> ⚠️ **Regla dura:** toda gestión de dependencias y entornos **Python** pasa por `uv`.
> Está **prohibido** `pip` y `requirements.txt`. Las presentaciones se gestionan aparte,
> en `slides/`, **únicamente con `pnpm`** (prohibido `npm`/`yarn`).

## 4. Estructura del repositorio

```text
TAAML/
├── src/taaml/                     # código del paquete (src-layout) — ejemplos del curso
├── tests/                         # pruebas de los ejemplos (pytest, patrón AAA)
├── slides/                        # MONOLITO Slidev (ver §7): un proyecto, un package.json
│   ├── slides.md                  # portada + Hub (16 sesiones) + imports + FIN DEL CURSO
│   ├── pages/claseN.md            # una clase por archivo (se importa en slides.md)
│   ├── pages/{components,layouts,snippets,setup.ts,styles.css,public,slide-top.vue}
│   │                              # symlinks → ../ para que el MODO AISLADO (slidev-cN)
│   │                              # resuelva componentes, layouts, estilos y assets
│   ├── layouts/                   # layouts propios: uao-cover, uao-default, three-cols-header
│   ├── components/                # componentes Vue compartidos:
│   │                              #   HubNavCard · AssistantPipeline · AttentionVisualizer
│   │                              #   TimelineLLM · CompanyRanking · WebEmbed
│   │                              #   PolarityLexicon · SarcasmCase · LabelingCost
│   │                              #   SelfSupervisedTasks · TaskOrigins · InContextLearning
│   │                              #   EmergentAbilities · HFHub · ModelCard
│   │                              #   EnergyBenchmark · UvBenchmark · CliTerminal
│   │                              #   FileTree · SpaceBuilder · RobotsSitemap
│   │                              #   ScrapingStack · ScrapingFlow · CaptureChecklist
│   │                              #   TokenChips · TokenBudget · MedallionLayers
│   │                              #   DataToolkit
│   │                              #   AgentAnatomy · AgenticWorkflow · ContextBudget
│   │                              #   MemoryCycle · SddCycle (Clase 3 — consolas agénticas)
│   │                              #   SamplingSimulator · SamplingQuadrant
│   │                              #   PromptStructureViewer · ReasoningComparison
│   │                              #   WindsurfLeakViewer · PromptTimeline (Clase 4)
│   │                              #   OrchestratorAnatomy · OrchestratorComparison
│   │                              #   DeepInferArchitecture · IndustryMap (Clase 5)
│   │                              #   MemorySimulator · CosineSimilarityLab
│   │                              #   EmbeddingTaxonomy · StripeFraudVisualizer
│   │                              #   LangGraphMemoryDual · EmbeddingGemmaViewer
│   │                              #   TokenizerLab (Clase 6)
│   ├── public/                    # assets globales (logo-uao.svg, img/claseN/)
│   ├── slide-top.vue              # capa institucional: logo UAO en cada diapositiva
│   ├── setup.ts / styles.css      # configuración y estilos globales
│   ├── package.json / pnpm-lock.yaml
│   ├── pnpm-workspace.yaml        # allowBuilds de playwright-chromium (export a PDF)
│   ├── qa/                        # QA de decks: overflow (Playwright), anchura de código y revelado
│   └── Makefile                   # install, dev, build, export, format
├── docs/                          # documentación, apuntes y ADRs
│   ├── programa-curso-TAAML.md    # programa del curso (Markdown, fuente de trabajo)
│   ├── programa-curso-TAAML-SIGED-2026.pdf  # programa oficial SIGED
│   ├── arquitectura.json          # FUENTE del diagrama Archify (versionada)
│   ├── arquitectura.html          # diagrama interactivo autocontenido
│   └── arquitectura.visual-check.* # recibos + capturas de evidencia
├── Rubricas/                      # suite de rúbricas de evaluación interactivas (HTML)
│   ├── index.html + moduloN.html  # motores de evaluación por módulo
│   └── data/                      # semestres en JSON + backups/
├── Moodle-Resumenes-Ejecutivos/   # SITIO CANÓNICO de maquetados HTML para Moodle
│   ├── Template.md                # guía de identidad UAO + plantillas reutilizables
│   ├── reglas_de_juego.html       # reglamento/cronograma (16 sesiones)
│   └── anuncios/                  # anuncios institucionales (los de clase: `claseN-*.html`)
├── scripts/                       # automatización del material del curso
│   └── export-clases.sh           # `make clases-pdf`: deck + anuncios → Clases/Clase N/
├── Clases/Clase N/                # PAQUETE por sesión para UAO Virtual (Clases/Clase 1..16)
│   ├── TAAML - Clase N - ….pdf   #   deck exportado (generado; se versiona)
│   ├── claseN-*.html              #   copia de los anuncios de esa clase (generado; se versiona)
│   └── …                          #   material de apoyo del docente (cheatsheets, papers)
├── .github/                       # gobernanza (PR/issue templates, CI, Dependabot, labels)
├── .opencode/rules/               # reglas para agentes (tgrep)
├── AGENTS.md                      # contexto para agentes LLM
├── CONSTITUTION.md                # este archivo — verdad central
├── README.md                      # puerta de entrada pública
├── CONTRIBUTING.md / CODE_OF_CONDUCT.md
├── Makefile                       # automatización raíz (python-* + slidev-* + clases-*)
├── pyproject.toml / uv.lock       # metadatos y dependencias (uv)
└── .pre-commit-config.yaml        # hooks de calidad (incluye slidev-format)
```

## 5. Convenciones de código

- **Estilo:** [PEP 8](https://peps.python.org/pep-0008/) y [PEP 257](https://peps.python.org/pep-0257/),
  impuesto por **Ruff** (`line-length = 100`, comillas dobles).
- **Tipado:** anotaciones en funciones y firmas públicas.
- **Nomenclatura:** `snake_case` (funciones/variables), `PascalCase` (clases),
  `UPPER_CASE` (constantes).
- **Docstrings:** en módulos, clases y funciones públicas.
- **Pruebas:** `pytest` con el patrón **AAA** (*Arrange · Act · Assert*).
- **Idioma:** UI, apuntes y commits en español; identificadores de código en inglés.
- **Notebooks:** los ejemplos se versionan como `.py` (o `.md` de Slidev), no como `.ipynb`.

## 6. Calidad y automatización

| Herramienta | Rol | Comando |
|-------------|-----|---------|
| `uv` | Entornos y dependencias (Python) | `make python-install` |
| Ruff | Lint + formato (Python) | `make python-lint` / `make python-format` |
| `ty` | Verificación de tipos | `make python-typecheck` |
| `pytest` | Pruebas | `make python-test` |
| `slidev format` | Formato de los decks | `make slidev-format` |
| `slidev-width` | Anchura del código de los decks (≤ ~70 caracteres por línea) | `make slidev-width` |
| `clicks.py` | Revelado progresivo: todo bloque visible con `<v-click>`/`<v-clicks>` | `make slidev-clicks` |
| `export-clases.sh` | Paquete por clase (deck PDF + anuncios) en `Clases/Clase N/` | `make clases-pdf` |
| `pre-commit` | Hooks antes de cada commit | `make pre-commit` |
| GitHub Actions | CI (pre-commit + ty + pytest; instala pnpm) | `.github/workflows/ci.yml` |

- Ningún commit se salta los hooks (`--no-verify` está prohibido salvo causa justificada y documentada).
- La **CI debe estar en verde** antes de fusionar un Pull Request.
- Toda dependencia Python nueva entra con `uv add` / `uv add --dev` (nunca editando `uv.lock` a mano).
- Toda dependencia de presentaciones entra con `pnpm add` dentro de `slides/` (nunca editando `pnpm-lock.yaml` a mano).
- **Validación de un deck** antes de darlo por bueno:
  1. `slidev format` sin cambios.
  2. Build aislado de la clase: `slidev build pages/claseN.md`.
  3. Build del monolito: `make slidev-build`.
  4. Escaneo de `dist/`: 0 literales `**` o `{.` en los chunks `md-*.js`.
  5. Conteos balanceados: `<v-click>` ≡ `</v-click>`, `div` de apertura ≡ cierre,
     `two-cols-header` ≡ `::left::` ≡ `::right::`.
  6. Máximos de *line-highlights* ≤ longitud real de cada bloque.
  7. En bloques `magic-move`: cada frame es un bloque **completo y válido** del mismo lenguaje.
  8. **Chequeo de overflow**: `make slidev-qa` (Playwright) → **0 slides desbordadas**.
  9. **Anchura de código**: `make slidev-width` → **0 líneas** de código con más de
     ~70 caracteres (ver *Anchura de los bloques de código*, §7).
  10. **Revelado progresivo**: `make slidev-clicks` → **0 bloques** visibles (título, subtítulo,
      párrafo, tarjeta, código o componente) fuera de `<v-click>`/`<v-clicks>` (ver *Animación*, §7).

## 7. Arquitectura del curso y de las presentaciones (Slidev)

### Monolito Slidev (decisión no negociable)

- **Un único** proyecto Slidev en `slides/` con **un solo** `package.json` y
  `pnpm-lock.yaml`. Cada clase vive en `slides/pages/claseN.md` y se importa en
  `slides/slides.md` con `src: ./pages/claseN.md`. Componentes, layouts y estilos son
  **compartidos**.
- **Frontmatter obligatorio** de cada clase:

  ```yaml
  ---
  theme: seriph
  title: "Clase N - Título Descriptivo"   # OJO: entrecomillar títulos con ':'
  info: |
    ## Clase N: Título Descriptivo
    Curso TAAML
  routeAlias: claseN
  transition: slide-left
  mdc: true
  ---
  ```

  `routeAlias` habilita la URL directa `http://localhost:3030/claseN`.

### Capa institucional UAO (logo en cada diapositiva)

- `slides/slide-top.vue` (capa por-slide, **no** `global-top.vue`) pinta el logo UAO
  arriba a la derecha en cada diapositiva. Es **template-only, sin `<script>`**: el plugin
  `slidev:context-injection` inyecta `useSlideContext()` en todo `.vue` de usuario; un
  import inexistente de `@slidev/client` rompe el render en el navegador.
- Usa `$frontmatter.layout !== 'uao-cover'` y los flags `hideLogo` / `hideHeader` para
  ocultarse (la portada y el cierre van sin capa).
- **Modo aislado:** los globs de capas usan como raíz el directorio del entry, por lo que
  `pages/` incluye symlinks a `../` de **`components`, `layouts`, `snippets`, `setup.ts`,
  `styles.css`, `public` y `slide-top.vue`** para que `make slidev-cN` (y cualquier export
  aislado) resuelva componentes, layouts, estilos y assets. Sin ellos, Slidev **no falla**:
  dibuja la slide sin los componentes.
- Layouts propios: `uao-cover` (portada/cierre con fondo oscuro y logo) y `uao-default`
  (marca de agua). Ambos sin `<script setup>`.

### Hub de navegación

`slides/slides.md` incluye, tras la portada, una diapositiva **Hub** con una tarjeta por
sesión (hoy **16**) en `grid grid-cols-2`. Clases con deck → `<HubNavCard to="/claseN">`;
clases sin deck → tarjeta `hub-soon` no clicable.

> **Regla:** usa **`HubNavCard`** (`slides/components/HubNavCard.vue`), que envuelve al
> `<Link>` de Slidev y antepone `/presenter` cuando `useNav().isPresenter` es verdadero
> (mismo patrón del `TocList` oficial). Un `<Link to="/claseN">` crudo clicado desde
> `/presenter/2` navega a `/claseN` y **abandona `/presenter/*`**, matando la vista de
> presentador. **Prohibido** `<a href>` (recarga completa) y `@click="$slidev.nav..."`.

### Reglas de sintaxis (inquebrantables)

| Regla | Especificación |
|-------|----------------|
| **Native-First** | Prohibidos `<p>`, `<b>`, `<strong>` y `<div>` decorativos donde MDC parsea Markdown; usa `**negrita**`, listas y atributos MDC `{.text-sm}`. |
| **Zona raw** | Dentro de un bloque HTML **sin líneas en blanco** (compact cards), MDC **no** parsea Markdown: `**`, `{.cls}` **y las matemáticas (`$...$`, `$$...$$`)** salen literales. Ahí el HTML inline (`<b>`, `<p class>`, `<code>`, `<br/>`) es correcto y queda exceptuado. |
| **Viñetas** | En las tarjetas HTML (zona *raw*) **no escribas `• ` dentro de `<li>`**: el deck ya pinta el marcador (`▪`) y se verían **dos viñetas**. Usa `<li>texto</li>` y deja que el estilo haga el resto. |
| **Interacción** | `<v-click>`/`<v-clicks>` en listas y tarjetas; **prohibidos los muros de texto**. `v-click` solo en nodos hoja, nunca en un contenedor padre que envuelva `<v-clicks>`. |
| **Componentes (interactivo)** | Todo elemento **interactivo** (botones, *toggles*, *sliders*, visualizadores, quizzes) es un **componente `.vue`** en `slides/components/`; el Markdown solo lo monta. Ver §7. |
| **Diagramas** | **Sin Mermaid por defecto**: prefiere **SVG** vectoriales, **componentes Vue** interactivos o imágenes. Mermaid solo si el docente lo pide de forma explícita. |
| **Animación** | **Revelación progresiva máxima**: **ningún bloque visible queda fuera de `<v-click>`/`<v-clicks>`** — título, subtítulo, párrafo, bloque de código, componente y el contenido de `::left::`/`::right::`. Verifícalo con `make slidev-clicks` (autofix: `make slidev-clicks-fix`). En **grids**, envolver las tarjetas con `<v-clicks>` **dentro** del grid (no genera wrapper → no rompe el layout). Las tablas de referencia **no** se animan fila a fila. Ver *Clics progresivos* en §7. |
| **Código** | Bloques **dinámicos** con `magic-move` cuando el código evoluciona (ver *Código dinámico* en §7) y resaltado por pasos con anotaciones de línea (`{1-3\|5-8}`). |
| **Notas del orador** | Comentarios `<!-- Notas: ... -->` (tecla `P`). |
| **Columnas** | 2 columnas independientes → `layout: two-cols-header` (`::left::`/`::right::`). 3 columnas → `three-cols-header` (`::col1::`/`::col2::`/`::col3::`, que sí admite `::bottom::`). Grid Tailwind reservado solo para galerías N-cards bajo un único `<v-clicks>` y para el Hub. |
| **Imágenes** | Viven en `slides/public/img/claseN/` (nomenclatura `clase<N>_img_<YY>.<ext>`) y se referencian con ruta absoluta. **Usa `<img src>`**: funciona en el monolito **y** en modo aislado (`make slidev-cN`), donde `![]()` compila como import y falla. Toda slide con `::right::` lleva un comentario con ambas sintaxis como plantilla. |
| **Legibilidad** | Cada bloque de código ≤ **~23 líneas visibles** y **~70 caracteres de ancho** por línea. Si excede el alto, pártelo en slides numeradas (`1/3`, `2/3`, …); si excede el ancho, usa **continuación de línea real** (`\`, backtick). Ver *Anchura de los bloques de código* en §7. |
| **Siglas** | Expande cada sigla en su **primera aparición visible**: `Nombre Completo (SIGLA)`. |

### Código dinámico (`magic-move`)

Todo bloque que muestre una **evolución** de código (construcción incremental, refactor o
un antes/después) usa **`magic-move`** para **animar la transición** entre versiones, en
lugar de un bloque estático. Es la forma estándar de mostrar código en el curso:

````md magic-move
```python
# 1. Llamada directa al modelo
respuesta = llm.invoke("Resume este informe")
```
```python
# 2. Plantilla de prompt parametrizada
from langchain_core.prompts import ChatPromptTemplate

prompt = ChatPromptTemplate.from_template("Resume en {n} puntos: {texto}")
cadena = prompt | llm
respuesta = cadena.invoke({"n": 3, "texto": informe})
```
````

- ````md magic-move```` (cuatro comillas) envuelve **bloques completos y válidos**; cada
  frame es una versión autocontenida del código (el morph solo anima lo que cambia).
- El lenguaje va en cada bloque interno (`python`, `bash`, `ts`…). Las anotaciones de línea
  (`{1-3|5-8}`) siguen aplicando **por bloque**.
- Un bloque **estático** se reserva para código sin evolución. Si el código **evoluciona**,
  `magic-move` es **obligatorio**.
- Respeta la regla de **≤ ~23 líneas visibles por frame**.

### Anchura de los bloques de código (`magic-move` incluido)

Una línea **demasiado larga** ensancha el bloque de código y, en `layout: two-cols-header`,
**aplasta la columna `::right::`**: el `<pre>` no encoge por debajo de su contenido, así que
el bloque se come el ancho de la otra columna. Regla: **ninguna línea de código supera
~70 caracteres**; si la hay, **pártela con una continuación de línea real** (no un salto
"bonito") para que el comando siga siendo **ejecutable tal cual**:

| Shell | Continuación (al final de la línea) |
|-------|-------------------------------------|
| Bash / sh / zsh | `\` |
| PowerShell | backtick `` ` `` |
| CMD | `^` |

```bash
# SÍ: continuación real (se ejecuta igual)
/bin/bash -c "$(curl -fsSL \
  https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

```powershell
# SÍ: backtick al final de la línea (se ejecuta igual)
[System.Net.ServicePointManager]::SecurityProtocol = `
  [System.Net.ServicePointManager]::SecurityProtocol -bor 3072
```

**Procedimiento (3 pasos):**

1. **Detectar** las líneas largas, solo dentro de bloques de código:

   ```bash
   make slidev-width              # todos los decks (pages/clase*.md)
   make -C slides width MAX=80    # desde slides/ (umbral opcional, por defecto 70)
   ```

   > Verde = OK. El script (`slides/qa/code-width.sh`) usa `awk` **ignorando los fences
   > externos de 4 backticks** del `magic-move` y solo mide las líneas de los bloques de
   > 3 backticks.

2. **Partir** únicamente esas líneas con la continuación del shell (`\` en bash, backtick en
   PowerShell): la continuación va **al final** de la línea y la segunda línea se indenta
   con 2 espacios.

3. **Volver a verificar**: `make slidev-width` en verde **y** `make slidev-qa` → **0 slides
   con problema**.

> ⚠️ **Gotcha (ya costó tiempo):** partir una línea **agrega una línea** al frame, y el frame
> más alto puede **desbordar la columna izquierda** aunque la slide parezca caber (la QA lo
> reporta como `overflow interno: col-left (360→390)`). Compensa el alto: une comandos con
> `;` (p. ej. `choco install make; ni Makefile`), o mueve el comando a la columna derecha /
> a una slide propia. **Ancho y alto se negocian: nunca uno a costa del otro.**

### Color, tema claro/oscuro e identidad UAO

El deck debe leerse bien en **light y dark** (Slidev permite alternarlos). Nunca uses texto
claro sobre superficie clara: los colores duros (`text-amber-300`, `bg-amber-950/20`) fallan
en light. Usa siempre el par `clase-clara dark:clase-oscura`:

| Rol | Claro | Oscuro (`dark:`) |
|-----|-------|------------------|
| Superficie neutra | `bg-white/85` | `dark:bg-zinc-900/90` |
| Superficie de código/matemáticas | `bg-slate-100` | `dark:bg-black/60` |
| Borde | `border-slate-200` | `dark:border-zinc-800` |
| Texto primario | `text-slate-900` | `dark:text-white` |
| Texto secundario | `text-slate-500` | `dark:text-zinc-400` |
| Acento — fondo (`<c>`) | `bg-<c>-100` | `dark:bg-<c>-950/50` |
| Acento — borde | `border-<c>-300` | `dark:border-<c>-800/60` |
| Acento — texto | `text-<c>-700` | `dark:text-<c>-300` |

- **Paleta:** pasteles **intensos** — `rose`, `amber`, `emerald`, `indigo`, `blue`,
  `purple`, `teal` y neutros `slate`/`zinc`.
- **Identidad UAO** (Rojo `#FF0000`, Negro `#000000`, Gris `#F4F4F6`): el rojo es un
  **acento**, no un fondo dominante. Úsalo en portadas, hitos, alertas y énfasis puntual;
  **no satures** el deck de rojo.
- Los componentes `.vue` deben exponer también sus variantes `dark:`.

### Interactividad con componentes Vue

Todo lo **interactivo** vive en un **componente `.vue`** bajo `slides/components/` (no en el
Markdown): botones, *toggles*, *sliders*, selección de estado, visualizadores dinámicos,
quizzes, calculadoras, etc.

- El deck **solo monta** el componente (`<MiComponente />`), idealmente dentro de
  `<v-click>`/`<v-clicks>` para secuenciar su aparición.
- El componente es responsable de su **estado** (`ref`, `computed`), de su **accesibilidad
  de color** (light/dark) y de **no romper el render** (sin imports inexistentes de
  `@slidev/client`).
- Ejemplos del curso: diagramas de atención/arquitecturas, simuladores de RAG, visualizador
  de embeddings, calculadoras de similitud, selector de **tokenización** (`TokenChips`),
  **presupuesto de tokens** (`TokenBudget`), **capas Medallion** (`MedallionLayers`) y catálogo
  de **librerías por etapa** (`DataToolkit`).

### Clics progresivos (regla del curso)

Se busca la **máxima revelación progresiva**: el presentador va **un clic adelante** de lo que
está explicando, de modo que cada bloque aparece con un clic y nunca se ve toda la
información de golpe. **Regla dura:** ningún bloque visible queda fuera de
`<v-click>`/`<v-clicks>`; `make slidev-clicks` lo verifica (`make slidev-clicks-fix` lo corrige).

- Títulos y bloques únicos → `<v-click>`.
- Listas, *stacks* y el contenido de `::right::` → `<v-clicks>`.
- **Grids de tarjetas** → envolver las tarjetas con `<v-clicks>` **dentro** del contenedor
  `grid` (entre la apertura y el cierre). `<v-clicks>` **no** genera un wrapper DOM
  (renderiza sus hijos directamente), así que el grid se conserva y cada tarjeta aparece con
  su propio clic:

  ```html
  <div class="grid grid-cols-3 gap-3">
    <v-clicks>
      <div class="...">tarjeta 1</div>
      <div class="...">tarjeta 2</div>
    </v-clicks>
  </div>
  ```

- No anidar un `v-click` en un contenedor padre de `<v-clicks>` (aplasta la secuencia).
- Verifica el balance: `<v-clicks>` ≡ `</v-clicks>` y `<v-click>` ≡ `</v-click>`.

### Exportación a PDF y material por clase (`make clases-pdf`)

El PDF se genera con el CLI de Playwright, **nunca** con el diálogo de impresión del navegador.
El objetivo `make clases-pdf` (script `scripts/export-clases.sh`) arma el paquete de cada sesión
para subirlo a UAO Virtual:

```bash
make clases-pdf          # todas las clases con deck → Clases/Clase N/
make clase1-pdf          # una sola clase (make clase2-pdf, …)
make clases-clean        # borra solo los artefactos generados
TIMEOUT=180000 make clases-pdf   # timeout de Slidev (ms)
CLICKS=0 make clases-pdf         # sin la progresión de clics
```

- **Entry wrapper (obligatorio).** El script escribe un entry temporal en la **raíz** de
  `slides/` (`_export.claseN.md`, con `theme: seriph` y `src: ./pages/claseN.md`) y exporta
  ese. Exportar el deck aislado (`slidev export pages/claseN.md`) deja la raíz en `pages/`
  y **los componentes salen en blanco** en el PDF: nunca lo uses para material de entrega.
- **`--with-clicks`** conserva la progresión de `v-click` / `magic-move` (PDF de estudio).
- **Qué deja en `Clases/Clase N/`:** el deck como `TAAML - Clase N - <título>.pdf` y una
  **copia** de los anuncios de esa clase. **Todo `Clases/` se versiona y se sube** (el material
  de apoyo del docente **nunca se toca ni se borra**).
- **Convención de anuncios por clase:** el archivo empieza por `clase<N>-`
  (`Moodle-Resumenes-Ejecutivos/anuncios/clase1-001-anuncio.html`). Los anuncios generales
  (`001-anuncio.html`) son de curso y no se copian.
- Requiere `playwright-chromium` (devDependency) y `slides/pnpm-workspace.yaml`
  (`onlyBuiltDependencies`/`allowBuilds`): **pnpm 10+ bloquea los scripts de build** por
  defecto y sin esa línea un clon limpio no descarga Chromium.
- Un **GIF** solo imprime su primer frame en el PDF: para material entregable usa una captura
  del estado final (ver la slide de PaLM en la Clase 1).
- **Publicación:** el paquete generado se sube al aula virtual con el MCP
  (`uao_upload_to_folder`: adjuntos + anuncio en la descripción de la carpeta). Runbook, cursos y
  gotchas en **§13**.

### Gotchas que ya costaron tiempo (no repetir)

- **YAML:** un `title` con `: ` sin comillas rompe `slidev format` con un error opaco
  (*Document with errors cannot be stringified*). **Entrecomilla siempre.**
- **pnpm 12:** el campo `pnpm.onlyBuiltDependencies` de `package.json` ya **no se lee**;
  usa `allowBuilds` (mapa) en `pnpm-workspace.yaml`. Se conserva `onlyBuiltDependencies`
  (lista) para compatibilidad con pnpm 10.
- **Layouts:** en `slides/layouts/*.vue` solo se importan exports verificados de
  `@slidev/client`. Un import inexistente **no falla en el terminal**: rompe el render.
- **Slots:** el layout nativo `two-cols-header` **no** define `::bottom::`; su contenido se
  descarta **en silencio**. Para una franja inferior usa `layout: default` o el
  `three-cols-header` propio (que sí lo soporta).
- **LaTeX/KaTeX:** no renderiza dentro de una **zona raw**: `$...$` y `$$...$$` salen
  literales. Deja una línea en blanco **después de la etiqueta que lo contiene y antes de
  su cierre** para habilitar el parseo. **No** adjuntes atributos MDC (`{.cls}`) a un bloque
  de matemáticas: rompe el parser
  (`Cannot read properties of undefined (reading 'tag')`); estílalo con un contenedor
  `<div>` con líneas en blanco. Alternativa robusta (curso Javeriana): **no metas
  matemáticas en HTML crudo** — déjala en Markdown (o dentro de `<v-click>`) o reescríbela
  con Unicode nativo (`max(R)`, `(1/|R|)·Σxᵢ`).
- **SVG/HTML sin líneas en blanco internas:** en árboles `<svg>`/`<div>` **no dejes líneas en
  blanco** entre tags: markdown-it cierra el bloque HTML y la indentación puede volverse
  `<pre><code>`, escapando el contenido y produciendo *Invalid end tag* al compilar.
  (Es el caso opuesto al de las matemáticas, donde sí se necesitan blancos.)
- **Espacios significativos (arte ASCII, tablas alineadas) en zona raw:** Vue **colapsa los
  espacios de los nodos de texto HTML** (`whitespace: 'condense'`), así que un `<div>` con arte
  ASCII pierde los saltos de línea y sale todo en una sola línea (nos pasó con `uvx pycowsay`).
  Solución: mete el arte en un **bloque de código** (```` ```text ````), donde los espacios se
  preservan; si necesitas HTML, usa `<pre>` **sin líneas en blanco internas**.
- **Anchura de código en `two-cols-header`:** una línea larga de `magic-move` **ensancha el
  bloque y aplasta `::right::`**; al partirla con `\` / backtick el frame crece **en alto** y
  puede desbordar la columna izquierda (`overflow interno: col-left`). Regla, comando `awk`
  y procedimiento en *Anchura de los bloques de código* (§7).
- **`slidev format` (Prettier) reformatea los bloques de código.** Prettier formatea el Python
  embebido y **une** una llamada partida en varias líneas si cabe… y puede dejarla en **74
  caracteres**, rompiendo la regla de los ~70. No la partas con `\`: escribe la llamada ya corta
  (p. ej. `traer = YouTubeTranscriptApi.get_transcript`) y pásale la variable.
- **Los hooks de pre-commit normalizan el código de los decks.** Al editar un bloque de código en
  `slides/pages/claseN.md`, el formato de los hooks puede reindentar los comentarios o unir líneas:
  si el commit falla con *«files were modified by this hook»*, vuelve a hacer `git add -A` y repite
  el commit. Si quieres que el paquete de la clase quede idéntico a la fuente, regenera su PDF
  (`make claseN-pdf`) después del reformateo.
- **Frontmatter YAML dentro de un bloque de código:** los *fences* protegen los `---`, así que el
  split de slides de Slidev **no** los toma por separadores (verificado con el ejemplo de la capa
  *Gold*). Puedes mostrar frontmatter real sin riesgo.
- **Viñetas duplicadas en tarjetas HTML:** escribir `• ` dentro de `<li>` produce `▪ •` (el tema
  ya añade el marcador). Ver la fila **Viñetas** de §7.
- **Tablas dentro de componentes `.vue`:** el tema `seriph` aplica `line-height` alto y
  `padding: 12px 8px` a `th`/`td`, y **gana por especificidad** a las utilidades `py-*`.
  Una tabla de ~9 filas mide ~42 px por fila y **desborda la columna** de un
  `two-cols-header`. Neutralízalo con un `<style scoped>` en el propio componente
  (`.mi-tabla, .mi-tabla th, .mi-tabla td { line-height: 1.25 }` +
  `padding-top/bottom: 4px`): el selector con `scoped` añade atributo y **sí** gana.
- **Iframes de terceros (Flourish, Artificial Analysis) en una slide:** Slidev **monta la slide
  justo antes de mostrarla**; si el iframe carga en ese instante, el sitio mide una altura
  errónea y renderiza pocas filas (p. ej. Flourish dibuja 3 de 8). Solución: montar el iframe
  **con retardo** (~700 ms) desde un componente (`slides/components/WebEmbed.vue`). Para que
  quepa más contenido se le pide un viewport mayor (`width/height = 100/zoom %`) y se escala con
  **`transform: scale(zoom)`**: con `transform` el layout queda **dentro** del contenedor y
  **no** dispara el QA; con `zoom` el layout no encoge y el panel se marca como desbordado.
  `src` admite anclas (`…/#intelligence`) para abrir el sitio en la sección deseada, y el panel
  se puede desplazar con la rueda durante la clase. Requiere internet en el aula: ten una
  captura de respaldo para los paneles que uses (en el PDF solo sale lo que alcance a pintar).

### Archify (documentación viva)

- El JSON `docs/arquitectura.json` es la **fuente tipada**; el HTML se **genera**, nunca se
  edita a mano. Regenerar = `validate` + `deliver` (perfil `showcase`, 9/9 checks).
- Convención: `docs/arquitectura.{json,html}` + `docs/arquitectura.visual-check.*` (recibos
  y capturas). El README enlaza la captura oscura al HTML interactivo.

## 8. Repositorio y Git

- **Remoto (SSH):** `git@github.com:hamsomp3/TAAML.git`
- **Rama principal:** `main`
- **Estrategia de ramas:** `feat/...`, `fix/...`, `docs/...`, `refactor/...`, `test/...`, `chore/...`; integración vía Pull Request.
- **Commits:** [Conventional Commits](https://www.conventionalcommits.org/) —
  `feat:`, `fix:`, `docs:`, `refactor:`, `style:`, `test:`, `chore:`.
- **Identidad git:** se resuelve sola dentro de `~/Desktop/Repositorios/personal/`
  (ver §12).

## 9. Flujo diario (commit + push)

```bash
# 1. Ver cambios
git status

# 2. Verificación completa (lint + formato + tipos + pruebas)
make python-check

# 3. Verificar los decks si se tocaron
make slidev-format
make slidev-width
make slidev-clicks
make slidev-build
make slidev-qa

# 4. Regenerar el material por clase (si se tocaron los decks)
make clases-pdf

# 5. Agregar y commitear (los hooks se ejecutan solos)
git add -A
git commit -m "tipo: mensaje descriptivo"

# 5. Subir a GitHub
git push
```

> **Todo lo que vive en `Clases/` se versiona** (material de apoyo del docente + el paquete
> generado: `TAAML - Clase N - *.pdf` y la copia del anuncio). `Clases/` es la carpeta que se
> sube a UAO Virtual: lo que se ve ahí, está en el repo. Se regenera con `make clases-pdf` y se
> commitea; lo único que se ignora son los ficheros del sistema (`.DS_Store`).

## 10. Historial de decisiones técnicas

| Fecha | Decisión | Motivo |
|-------|----------|--------|
| 2026-10-06 | Adoptar `uv` como gestor único de entornos y dependencias Python | Reproducibilidad; prohibido `pip`/`requirements.txt` |
| 2026-10-06 | Adoptar Ruff (lint + formato) y pre-commit | Calidad automatizada antes de cada commit |
| 2026-10-06 | Adoptar Conventional Commits | Historial legible y automatizable |
| 2026-10-06 | Adoptar licencia MIT y `CONSTITUTION.md` como fuente única de verdad | Claridad legal y operativa |
| 2026-10-06 | Un **monolito Slidev** en `slides/` (un proyecto, un `package.json`) | Evitar duplicar configuración; compartir componentes, layouts y estilos entre clases |
| 2026-10-06 | Gestionar las presentaciones con **`pnpm`** y los ejemplos con **`uv`** | Separar ecosistemas (Node/Python) sin contaminar entornos |
| 2026-10-06 | Adoptar la **capa institucional UAO** (`uao-cover`, `uao-default`, `slide-top.vue`, logos) | Identidad visual de la universidad en todas las diapositivas |
| 2026-10-06 | **Hub de 16 sesiones** (tarjetas `hub-soon` hasta definir el temario) | Navegación directa `localhost:3030/claseN` |
| 2026-10-06 | Activar **Archify** (`docs/arquitectura.json` + `.html`) | Documentación de arquitectura viva y reproducible |
| 2026-10-06 | Reutilizar del curso hermano DDPIA `Rubricas/`, `Moodle-Resumenes-Ejecutivos/` y `Clase N/` | No reinventar la gobernanza docente; el hermano ya resolvió los gotchas |
| 2026-10-06 | Makefile raíz con prefijos `python-*` / `slidev-*` | Claridad de la toolchain híbrida |
| 2026-10-06 | Usar **`magic-move`** en bloques de código que **evolucionan** | Transiciones animadas y didácticas; un bloque estático no muestra el antes/después |
| 2026-10-06 | **Interactividad** en componentes `.vue` y **color dual** (light/dark) con acentos pastel | El Markdown no mantiene estado; el deck debe leerse bien en ambos temas. Rojo UAO solo como acento |
| 2026-10-06 | Adoptar patrones del curso **DL-Javeriana**: **HubNavCard** (presenter-safe), **SVG/componentes en vez de Mermaid**, animación `v-click`, export `--with-clicks` | Reutilizar prácticas ya probadas; mejorar navegación y material de estudio |
| 2026-10-06 | **Máxima revelación progresiva** (`<v-clicks>` en todos los bloques; en grids, dentro del contenedor) e imágenes con **`<img src>`** | El presentador no improvisa: cada punto aparece con un clic; `<img>` es robusto en monolito y modo aislado |
| 2026-10-06 | **QA de layout con Playwright** (`make slidev-qa` → 0 overflows) | Detectar y corregir recortes reales de slides con datos, no a ojo |
| 2026-10-08 | Definir las **fechas de las 16 sesiones** (vie 6:30 p.m. / sáb 8:00 a.m., 09/10→28/11/2026) y publicar el **anuncio 001** de bienvenida | Arranque de la cohorte 2026-2S de la Maestría; incluye la suspensión por fuerza mayor del 09/10 y 10/10 |
| 2026-10-15 | **Anchura máxima de ~70 caracteres** por línea de código en los decks: partir con continuación real (`\`, backtick) y verificar con `awk`; en el checklist de validación del deck | Las líneas largas de `magic-move` ensanchaban el bloque y aplastaban `::right::`; partirlas sin criterio desbordaba la columna izquierda |
| 2026-10-15 | **`make clases-pdf`**: paquete por sesión (deck PDF + anuncios) en `Clases/Clase N/`, exportando con un wrapper en la raíz de `slides/` | Un solo comando deja listo el material de cada clase para subirlo en bloque a UAO Virtual; el export aislado no resuelve componentes y salían en blanco |
| 2026-10-15 | **Ningún bloque visible sin `<v-click>`**, verificado con `slides/qa/clicks.py` (`make slidev-clicks`) y autofix (`slidev-clicks-fix`) | Subtítulos, párrafos y bloques de código aparecían completos al entrar en la slide, rompiendo la revelación progresiva |
| 2026-10-15 | **Arquitectura Medallion** para el corpus del Taller 1: 🥉 `data/raw/` → 🥈 `data/processed/` → 🥇 `data/gold/`, y **Gold = Markdown + *frontmatter* YAML** como **contrato con el RAG del Módulo 2** | Separar la captura (frágil y cara) del procesamiento (reproducible): si cambia el limpiador, se regeneran Silver y Gold sin volver a la web. Los metadatos de Gold dan filtros, citas y control de refresco |
| 2026-10-15 | Slides nuevas: **tokenización (BPE)** y **prefill vs decode** en la Clase 1 (con datos **reales** de `tiktoken`); **PEP 723**, **limpieza con `trafilatura`**, **«Lost in the Middle»**, `hf-transfer`, **MoE** y **contrabando Unicode** en la Clase 2 | Explican el 90% de los comportamientos «tontos», el coste por token, por qué la inferencia local depende del ancho de banda y por qué el contexto largo **no** sustituye al RAG |
| 2026-10-15 | Anuncios por clase (`anuncios/claseN-*.html`) que `make clases-pdf` empaqueta en `Clases/Clase N/` | El paquete de cada sesión para UAO Virtual queda completo (deck + anuncio) y con el mismo lenguaje que el deck |
| 2026-10-15 | **Todo `Clases/` se versiona** (material de apoyo + PDF del deck + anuncio copiado): se retiran las reglas de `.gitignore` que excluían lo generado | `Clases/` es la carpeta que se sube a UAO Virtual; el docente quiere que lo que se ve ahí esté también en el repo y en GitHub |
| 2026-10-15 | **Publicación en UAO Virtual con el MCP `moodle-uao`**: adjuntos + anuncio HTML en la **descripción de la carpeta** de cada clase; symlink local `mcps/moodle-uao` y `opencode.json` propio que fija `UAO_COURSE_ID=16861` | El aula virtual es el canal de entrega; el MCP conduce el navegador del docente. El config por repo evita publicar en el curso equivocado (16864 = Gestión) sin tocar la config global; OpenCode lanza una instancia del MCP por proyecto. Runbook en §13 |
| 2026-10-16 | **Clase 3 = Consolas Agénticas (OpenCode)**: el agente de código *que actúa* sobre el repositorio (agentes `build`/`plan`, MCP, skills, memoria con Engram y SDD), con **5 componentes Vue** nuevos (`AgentAnatomy`, `ContextBudget`, `MemoryCycle`, `SddCycle`, `AgenticWorkflow`) | Reutiliza y adapta al formato TAAML la clase del curso hermano (ICESI), eliminando lo específico de esa institución. Da a los equipos el entorno agéntico con el que trabajarán los tres módulos |
| 2026-10-16 | **Clase 4 = Prompt Engineering Avanzado y Razonamiento**: muestreo (temperatura y Top-p), anatomía modular del prompt, salidas estructuradas, CoT/Self-Consistency/ToT, **defensa con delimitación XML**, **prompting de modelos de razonamiento (o1/o3/R1)**, **compilación con DSPy y las fronteras de TextGrad, Chain of Density y Reflexion**, el leak de Windsurf y las 26 instrucciones de VILA-Lab, con **6 componentes Vue** nuevos (`SamplingSimulator`, `SamplingQuadrant`, `PromptStructureViewer`, `ReasoningComparison`, `WindsurfLeakViewer`, `PromptTimeline`), la captura real del binario de Windsurf y el PDF de ATLAS en `Clases/Clase 4/` | Cierra el bloque de prompt engineering del Módulo 1 con evidencia de papers, un componente interactivo por concepto, defensa contra inyecciones y automatización de prompts para el nivel de maestría |
| 2026-10-17 | **Anuncio 003**: la reposición queda fijada en **miércoles 21 y miércoles 28 de octubre de 2026, 6:30–9:30 p.m., por Webex**; se insertan **cronológicamente** como **3.ª y 6.ª sesión** del curso (no al final ni en el orden del contenido), con **Clase 1** y **Clase 2** como contenido de esas sesiones. Enlaces **pendientes** hasta que la USU los entregue | Cierra la votación del anuncio 002 con una decisión operativa; separa «posición de la sesión» (cronología) de «número de clase» (material), y deja el anuncio listo para pegar solo los enlaces |
| 2026-10-17 | **Sitio web navegable del curso en UAO Virtual** (`uao_upload_website` → recurso **Archivo** con `index.html` principal, build `--base ./ --router-mode hash`): `cmid 537765`, sección General, visible. El deck solo importa las **Clases 1 y 2**; las demás tarjetas del Hub quedan como **«🔒 Próximamente»** | El curso va en la Clase 2 y el factor sorpresa importa: no se spoilean clases futuras. Publicar oculto → verificar navegación/imágenes/consola → visible. Runbook en §13 |
| 2026-10-17 | **Clase 3 activada** en el sitio (`#/clase3`) y **anuncio 003 publicado** en el foro con los enlaces Webex del 21 y 28/10: revisión `content/4`, 3 clases activas y 13 «Próximamente»; discusión `d=167706` | El curso avanza a la Clase 3 y la USU ya entregó los enlaces. El anuncio HTML canónico y el post del foro quedan alineados; los enlaces son clicables |
| 2026-10-20 | **Sitio web republicado** tras la recreación del curso: recurso nuevo `cmid 537973` (sección General, visible, `content/2`), con **4 clases activas** (1–4) y 12 «Próximamente». La Clase 4 dejó de ser «Próximamente» y su portada usa `/img/fondo-portada.svg` (el fondo aleatorio de Unsplash daba 401) | El recurso anterior (`cmid 537765`) desapareció con el curso; con la Clase 4 ya publicada en su carpeta, el deck debe reflejarla. La portada sin fondo local dejaba el título invisible sobre el degradado |
| 2026-10-20 | **Clase 5 creada y publicada**: deck `slides/pages/clase5.md` con tres componentes (`OrchestratorAnatomy`, `OrchestratorComparison`, `DeepInferArchitecture`), carpeta Moodle **537852** y sitio actualizado a `content/3` con 5 clases activas | La sesión cubre orquestadores (LangChain/LangGraph, LlamaIndex, Agno, DSPy) y serving (DeepInfer + `deepseek-recipe`); las cifras del caso DeepSeek se verificaron contra los repositorios oficiales antes de publicarlas |
| 2026-10-21 | **Clase 5 revisada y republicada**: mapa de industria interactivo (`IndustryMap`) con logos locales, papers completos en la carpeta (14 arXiv + BAIR), PDF de 187 páginas y sitio `content/6`; corregidas las etiquetas `155 B → 155 × 10¹²` y «Costo → Ingreso» de US$38/GPU-h | El mapa ordena las capas (orquestación, modelos, serving, hardware) para que los estudiantes ubiquen cada logo; la revisión contra el README y el Q&A de DeepInfer confirmó 155 **trillion** tokens/día y que US$38 es **revenue**, no costo. Los 14 IDs de arXiv ya estaban completos |
| 2026-10-21 | **Diagnóstico de identidad del curso 16861 y paquete `Clases/inicio/`**: resumen vacío, sin imagen de curso, sección 3 llamada «Nueva sección», dos «Clase 14» y ausencia de la Clase 11; se prepararon descripción corta, página Inicio, prompts de imagen, 3 heroes + social + icono y checklist. **Nombre, `shortname` y código confirmados oficiales** (no se corrigen) | El curso tenía materiales pero no identidad: sin resumen ni imagen, el estudiante no entiende qué es el curso ni cómo recorrerlo. El diagnóstico fue read-only; los cambios se aplican con el checklist. `551462` es el código interno del shell y `561378` el académico; ambos coexisten |
| 2026-10-21 | **Clase 6 creada y publicada**: deck `slides/pages/clase6.md` (**persistencia en memoria con LangGraph + embeddings vectoriales**, perspectiva LangChain) con siete componentes (`MemorySimulator`, `CosineSimilarityLab`, `EmbeddingTaxonomy`, `StripeFraudVisualizer`, `LangGraphMemoryDual`, `EmbeddingGemmaViewer`, `TokenizerLab`), enlace en el Hub e import en el monolito; memoria dividida en **short-term (checkpointers)** y **long-term (stores)**, con enlaces a la documentación oficial de LangChain; embeddings ampliados con **Gemini Embedding 2**, **EmbeddingGemma 2**, **MIEB**, la evidencia real de **Stripe** (t-SNE y tabla de recall en `slides/public/img/clase6/`) y una slide de apoyo con los videos de **DolphinGemma** y el meme de **Rick y Morty**; publicada en UAO Virtual (carpeta **537858**, sitio **`content/4`**) | Cierra el bloque de orquestación del Módulo 1 y abre el Módulo 2; se corrigieron tres datos del borrador inicial: el survey de memoria es arXiv:**2504.15965** (no 2404.16130, que es GraphRAG), el caso Stripe **sí** usa t-SNE (verificado en la imagen del hilo, aunque el texto no lo mencione) y la retención de precisión de MRL no es 98,5 %. Todas las cifras se contrastaron con arXiv, OpenAI, Google, Stripe y Cohere |
| 2026-10-21 | **Identidad y onboarding del curso 16861 aplicados**: resumen e imagen de portada; **Página “Inicio”** (`cmid 538282`), **Book “Conoce tu curso”** con 10 capítulos (`cmid 538278`) y **PDF SIGED** (`cmid 538276`) al inicio de General; resúmenes en Módulo 1/2/3 y renombre de “Nueva sección” a **Módulo 3**. Las clases viejas 12–14 siguen ocultas. **MCP `moodle-uao`** ampliado con tools/CLI de Page/Book/orden y playbook `docs/course-blueprint.md` para replicarlo en Gestión 16864 | El curso ya tiene una portada visible y una guía navegable; el resumen de `course/edit.php` no se renderiza en `topics`, por eso la Página es la portada. El Book separa el programa de la Página hub y el PDF queda como descarga oficial. La sección 3 se renombró, pero su material viejo se actualizará cuando el módulo esté listo |

## 11. Notas y tareas pendientes

- [x] Estandarizar el repositorio (estructura, `uv`, Ruff, pre-commit, CI, gobernanza).
- [x] **Monolito Slidev** en `slides/` con capa UAO y Hub de 16 sesiones.
- [x] **Archify** activado (`docs/arquitectura.{json,html}` + capturas).
- [x] Estructura docente: `Rubricas/`, `Moodle-Resumenes-Ejecutivos/`, `Clase N/`.
- [ ] Definir el **temario de las 16 sesiones** (títulos y módulos; **fechas**: vie/sáb, 16/10→28/11/2026, con reposiciones mié 21/10 y 28/10).
- [x] Definir el **mecanismo de reposición** de las sesiones suspendidas (09/10 y 10/10): miércoles 21 y 28 de octubre, 6:30–9:30 p.m., Webex (anuncio 003); se insertan como 3.ª y 6.ª sesión de la secuencia.
- [x] Añadir la **primera clase** real (`slides/pages/clase1.md`) y enlazarla en el Hub.
- [x] Añadir la **Clase 2** (`slides/pages/clase2.md`: modelos cerrados vs. pesos abiertos, local vs nube, `uv` a fondo y **web scraping** para el Taller 1) y enlazarla en el Hub.
- [x] Añadir la **Clase 3** (`slides/pages/clase3.md`: **Consolas Agénticas — OpenCode**, agentes `build`/`plan`, MCP, skills, memoria con Engram y SDD) con 5 componentes Vue nuevos y enlazarla en el Hub.
- [x] Añadir la **Clase 4** (`slides/pages/clase4.md`: **Prompt Engineering Avanzado y Razonamiento**, muestreo, anatomía del prompt, salidas estructuradas, CoT/ToT, defensa XML, modelos de razonamiento, DSPy y las fronteras de TextGrad/CoD/Reflexion) con 6 componentes Vue nuevos, la captura real de Windsurf, el PDF de ATLAS en `Clases/Clase 4/` y enlace en el Hub.
- [x] Revisar y republicar la **Clase 5** (`slides/pages/clase5.md`): mapa de industria (`IndustryMap`) con 21 logos locales, 14 papers arXiv + BAIR en la carpeta **537852**, PDF de 187 páginas y sitio `content/6`; corregidas las cifras `155 B → 155 × 10¹²` y «Costo → Ingreso».
- [x] Diagnosticar y **aplicar** la identidad del curso **16861**: resumen + imagen de portada, Página “Inicio”, Book “Conoce tu curso” (10 capítulos), PDF SIGED y resúmenes de Módulo 1/2/3; “Nueva sección” → “Módulo 3”. Se dejaron **sin tocar** nombre, shortname, fechas, idnumber y las clases viejas 12–14 (ocultas), por decisión del docente.
- [x] Documentar el **blueprint de curso** en el MCP `moodle-uao`: tools/CLI de Page/Book/orden, plantillas y `docs/course-blueprint.md` con el caso TAAML y el checklist para Gestión **16864**.
- [x] Añadir la **Clase 6** (`slides/pages/clase6.md`: **Persistencia en Memoria y Embeddings Vectoriales**, checkpointers y time travel de LangGraph, `trim_messages`/`SummarizationMiddleware`, dualidad checkpointer/store, tokenización, geometría del coseno, taxonomía de embeddings, Gemini Embedding 2, EmbeddingGemma 2, híbrido BM25+denso, evidencia de Stripe, CLIP/MIEB y benchmarks) con 7 componentes Vue nuevos, enlace en el Hub, docs oficiales enlazadas, imágenes y logos en `slides/public/img/clase6/`, videos de apoyo de DolphinGemma/Rick y Morty, y los **6 papers citados** (PDF + índice en `Clases/Clase 6/`); **publicada** en UAO Virtual (carpeta **537858**, sitio web **`content/6`** con 6 clases activas).
- [x] Reescribir los **criterios de las rúbricas** (`Rubricas/moduloN.html`) para los 3 módulos de TAAML.
- [x] Completar `Moodle-Resumenes-Ejecutivos/reglas_de_juego.html` con los 3 módulos y talleres.
- [ ] Fijar las **librerías de IA** para los ejemplos (hoy `EN EVALUACIÓN`).
- [ ] Configurar la **protección de la rama `main`** (PR obligatorio, CI verde).
- [ ] Definir la **exportación a PDF** por clase (Fase 4). → **Parcial:** `make clases-pdf` ya genera el PDF de cada clase en `Clases/Clase N/` y el **MCP de aula** publica deck + anuncio en UAO Virtual (runbook en §13); falta un comando único que encadene generación y publicación.
- [x] Integrar el **MCP de aula** (`moodle-uao`) y publicar la **Clase 1** y la **Clase 2** en UAO Virtual (curso 16861), con las carpetas alineadas al material.
- [x] Definir el **nuevo orden del temario**: **Clase 3 = Consolas Agénticas** y
  **Clase 4 = Prompt Engineering Avanzado y Razonamiento**; reflejado en el Hub.
  (Pendiente: alinear `Moodle-Resumenes-Ejecutivos/reglas_de_juego.html`.)
- [x] Producir y publicar la **Clase 3** (Consolas Agénticas) con el runbook de §13 y registrar la subida en `Moodle-Resumenes-Ejecutivos/uao-virtual/estado-curso-2026-2S.md`.
- [x] Producir y publicar la **Clase 4** (Prompt Engineering Avanzado y Razonamiento) con su anuncio y el material de lectura; subida registrada en `Moodle-Resumenes-Ejecutivos/uao-virtual/estado-curso-2026-2S.md`.
- [ ] **Anuncio 003** (reposición: miércoles 21 y 28 de octubre, 6:30–9:30 p.m., Webex): creado en `anuncios/003-anuncio.html` con los enlaces **pendientes**; publicarlo en UAO Virtual y en el foro de Anuncios **cuando la USU entregue los enlaces**.

## 12. Configuración local (no trackear)

> Configuración específica de la máquina local. **NO incluir en commits.**

El repositorio vive bajo `~/Desktop/Repositorios/personal/`, por lo que `~/.gitconfig`
aplica automáticamente el perfil personal vía `includeIf`:

```ini
[includeIf "gitdir:/Users/jan.polanco/Desktop/Repositorios/personal/**"]
    path = /Users/jan.polanco/.gitconfig-personal
```

`~/.gitconfig-personal` (perfil que manda dentro de esta carpeta):

```ini
[user]
    name = Jan Polanco V.
    email = hamsomp3@gmail.com
[core]
    sshCommand = ssh -i ~/.ssh/id_ed25519 -o IdentitiesOnly=yes
```

> La identidad global de la máquina es laboral (`jan.polanco@wizeline.com`); el perfil
> personal la **sobreescribe** dentro de esta carpeta. Guía completa (macOS/Windows) en el
> skill `jan-project-standard` → `references/git-identity.md`.

## 13. Publicación en UAO Virtual (MCP de aula)

El material de cada clase se publica en **UAO Virtual** con el MCP **`moodle-uao`**
(repo independiente: `personal/moodle-uao-mcp`; symlink local en `mcps/moodle-uao`, ver
`mcps/README.md`). El MCP conduce un **navegador real** con la sesión del docente: lee y
escribe igual que él, sin token de Web Services.

### Regla de publicación (mientras una clase está en revisión)

**No se publica nada en UAO Virtual mientras la clase está en construcción o revisión.** El
docente revisa slide por slide y suele pedir cambios; cada cambio invalida el PDF exportado y
la revisión del sitio web (`content/N`). El flujo correcto es:

1. Construir y iterar el deck **solo en el repo** (`slides/`, componentes, QA).
2. Cuando el docente declare la clase cerrada: `make claseN-pdf` y, si aplica, build del sitio.
3. Publicar **una sola vez** con `uao_upload_to_folder` / `uao_upload_website` y verificar.

Si la clase ya estaba publicada y entra en revisión, se deja como está (o se oculta) y se
re-sube al final; no se hacen subidas intermedias.

### Cursos y curso por defecto

| Curso | `courseId` | Repo del curso | Sesión por defecto |
|-------|-----------|----------------|--------------------|
| TÉCNICAS AVANZADAS DE IA APLICADAS EN MODELOS DE LENGUAJE (**TAAML**) | `16861` | este repositorio | **16861** (`opencode.json` de este repo) |
| GESTION DE PROYECTO EN IA Y CD (**Gestión**) | `16864` | DDPIA | 16864 (config global de OpenCode) |

- El `opencode.json` **de este repositorio** fija `UAO_COURSE_ID=16861`. OpenCode lanza **una
  instancia del MCP por proyecto**, así que **aquí las tools apuntan a TAAML sin pasar
  `courseId`**, y el global (16864) sigue vigente para los demás repos (DDPIA incluido).
- **Verificación** (tras tocar el config):
  ```bash
  opencode debug config          # debe listar TAAML/opencode.json entre las fuentes
  # y desde el agente:  uao_status  →  debe responder "Curso 16861"
  ```
- Si el repo del MCP cambia de sitio: actualiza el `opencode.json` global **y** el de TAAML, y
  rehaz el symlink (`ln -sfn ../../moodle-uao-mcp mcps/moodle-uao`).
- Tras `npm run build` del MCP hay que recargar: `opencode service restart` (o `opencode reload`)
  y comprobar con `opencode mcp list` (`✓ moodle-uao connected`).

### Flujo por clase (el del aula)

Cada clase vive en **su carpeta** (`mod/folder`) dentro de la sección de su módulo. Dentro van los
**adjuntos** y, en la **descripción de la carpeta**, el **anuncio HTML** de la clase (se renderiza
con la identidad UAO). `make clases-pdf` deja el paquete listo en `Clases/Clase N/`.

### Sitio web navegable del curso (Slidev en Moodle)

Además del PDF de cada clase, el deck se publica como **sitio web** en un recurso **Archivo**
(`mod_resource`) con `index.html` como **archivo principal**. Así los estudiantes navegan el deck
con su sesión de Moodle y sin dominios externos.

| Campo | Valor |
|-------|-------|
| Recurso | **Presentaciones interactivas del curso (Sitio web)** |
| `cmid` | **537973** |
| Curso | `16861` |
| Sección | General (`0`) |
| Display | Abrir (`open`) |
| Archivo principal | `index.html` |
| URL del recurso | `https://campus.uaovirtual.edu.co/mod/resource/view.php?id=537973` |
| URL directa | `https://campus.uaovirtual.edu.co/pluginfile.php/1646574/mod_resource/content/3/index.html` |

**Build Moodle-friendly + ZIP** (la base relativa y el hash son obligatorios; sin ellos los assets
se rompen y `/claseN` da 404):

```bash
cd slides
pnpm exec slidev build --base ./ --router-mode hash -o dist-moodle
rm -f taaml-moodle.zip
(cd dist-moodle && zip -qr ../taaml-moodle.zip .)   # index.html en la RAÍZ del ZIP
```

**Publicar o actualizar** (con `cmid` se actualiza in-place y se conserva el enlace):

```text
uao_upload_website({
  courseId: 16861,
  section: 0,                       # ignorado si se pasa cmid
  name: "Presentaciones interactivas del curso (Sitio web)",
  filePath: "/…/slides/taaml-moodle.zip",
  hideFile: true,                   # publicar oculto primero
  display: "open",
  mainFile: "index.html",
  cmid: 537973,                     # opcional: actualiza ese recurso
})
```

- **Regla de gating:** solo se importan en `slides/slides.md` las **clases ya dictadas**. Las
  futuras **no** llevan bloque `src:` y su tarjeta del Hub queda como **«🔒 Próximamente»**, sin
  título, para no spoilear el curso. Habilitar una clase = añadir su `src:` + convertir su tarjeta
  en `<HubNavCard>` + rebuild + `uao_upload_website` con el mismo `cmid`.
- **Verificación antes de hacerlo visible:** `index.html` carga, `#/1 → #/2` avanza, las imágenes
  cargan (sin 404 locales) y la consola no tiene errores propios. Después:
  `uao_set_activity_visibility({ cmid: 537973, visible: true })`.
- Las portadas de Clases 1, 2 y 3 usan el fondo local `/img/fondo-portada.svg` (el `layout: cover`
  del tema Seriph pedía una imagen aleatoria de Unsplash, que fallaba en redes restringidas).
- **Actualización in-place en Moodle 4.5:** el borrado del filemanager se confirma en un **modal
  Bootstrap** (`.modal.show [data-action="save"]`), no en el diálogo YUI clásico. La versión del MCP
  anterior al 2026-10-17 no lo confirmaba y dejaba filas viejas; ya está corregida en
  `moodle-uao-mcp` (y el CLI `npm run upload:website` usa la misma corrección). Para evitar
  colisiones, nombra el ZIP de cada actualización con fecha (`taaml-moodle-YYYY-MM-DD.zip`).
- **No usar una Carpeta** (`mod_folder`): esa actividad solo lista archivos y no ejecuta la SPA.

### Runbook de una clase nueva (p. ej. la Clase 3)

```bash
# 1. Producir y validar el material
make slidev-format && make slidev-width && make slidev-clicks && make slidev-qa
make clase3-pdf                # → Clases/Clase 3/ (deck + copia del anuncio)

# 2. Publicar en el aula: adjuntos + anuncio en la descripción de la carpeta
#    (tool del MCP; en terminal: cd mcps/moodle-uao && npm run upload:folder -- …)
uao_upload_to_folder({
  cmid: 537368,                # carpeta de la clase (ver estado-curso-2026-2S.md)
  files: ["Clases/Clase 3/TAAML - Clase 3 - <título>.pdf", …],
  descriptionFile: "Moodle-Resumenes-Ejecutivos/anuncios/clase3-001-anuncio.html",
  name: "Clase 3 - <título>",  # alinea el título de la carpeta con el material
})

# 3. Verificar
uao_list_folder_files({ cmid: 537368 })
```

- **Registro y cmids:** `Moodle-Resumenes-Ejecutivos/uao-virtual/estado-curso-2026-2S.md`
  (diagnóstico del curso + registro de cada publicación). El curso gemelo de Gestión tiene el suyo
  en `DDPIA/Moodle-Resumenes-Ejecutivos/uao-virtual/estado-curso-2026-2S.md`.

### Gotchas del aula virtual (ya costaron tiempo)

- **Usa la carpeta**, no `uao_upload_resource` («crear recurso» en una sección): por esa ruta las
  subidas de **más de ~1 MB** fallaron en las pruebas (el fichero no llegaba al área de borrador),
  mientras que por el **formulario de la carpeta** se subieron **26 MB en ~3 s**.
- El **foro de Anuncios** solo admite **texto plano** (el MCP teclea el mensaje) y **notifica** a
  los estudiantes: el anuncio maquetado va en la **descripción de la carpeta**.
- Moodle **sanea** ciertos caracteres del nombre del fichero (p. ej. `&` desaparece).
- **Una sesión por usuario:** si un script del MCP hace login con su propio navegador, la sesión
  del MCP se invalida → vuelve a pedir `uao_login`.
- **Un Chrome por perfil:** no corras el MCP y otro script a la vez sobre `~/.moodle-uao/profile`.
- La **primera** vez que se usa la sesión del MCP, el curso por defecto es el del proyecto: si algo
  responde con otro curso, revisa §13 (cursos y `opencode.json`) antes de escribir.
