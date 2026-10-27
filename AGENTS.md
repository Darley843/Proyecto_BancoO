# AGENTS.md — contexto para agentes LLM

Este repositorio construye el **corpus web de Banco de Occidente** para el
Taller 1 del curso TAAML (UAO). Antes de tocar código, lee
[`CONSTITUTION.md`](./CONSTITUTION.md): es la fuente única de verdad.

## Reglas que no se negocian

1. **`uv` es el único gestor de entorno y dependencias.** No uses `pip`, no
   crees `requirements.txt`, no edites `uv.lock` a mano.
   - Añadir dependencia: `uv add <paquete>` (o `uv add --dev <paquete>`).
   - Prueba puntual: `uv run --with <paquete> ...` o cabecera PEP 723.
2. **No toques `data/raw/` (Bronze) a mano.** Es el respaldo histórico. Para
   rehacer Silver/Gold usa `make clean && make extract && make gold`.
3. **Gold es el entregable.** Si cambias el formato, actualiza
   `CONSTITUTION.md` §7 y `docs/ESTANDAR.md` en el mismo commit.
4. **Respeta el sitio.** `robots.txt` manda: nada de `Disallow`. Mantén el
   ritmo de cortesía **decidido por el proyecto** (1,5 s entre peticiones, más
   pausa de 10 s cada 50) y el header `From` con el contacto académico.
   `robots.txt` del banco **no declara `Crawl-delay`**: los 1,5 s son una
   decisión nuestra, no una directiva del sitio. No subas el ritmo para
   "terminar rápido".
5. **Sin datos personales.** Nada de zonas tras login ni información de
   clientes (Ley 1581 de 2012).
6. **Commits:** Conventional Commits en español (`feat:`, `fix:`, `docs:`,
   `test:`, `chore:`). La CI y los hooks deben quedar en verde.

## Comandos de referencia

```bash
make help        # lista de targets
make init        # uv python install + uv sync --all-extras
make doctor      # diagnóstico de red y estado
make demo        # pipeline completo sin red (fixture)
make all         # captura real: discover -> fetch -> extract -> gold -> stats
make docs        # PDFs: inventario -> descarga -> Gold (balances, informes)
make videos      # YouTube: canal -> subtítulos -> transcripción Gold
make media       # documentos + videos
make noticias    # hechos oficiales + prensa curada (independiente de all/gold/deliver/docs/videos/media)
make contexto    # prompt del asistente desde Gold (data/contexto/)
make app         # app Streamlit del asistente (llama a asistente/)
make check       # lint + typecheck + pruebas
make health      # integridad de las capas y del contrato de Gold
make identity    # fija user.name / user.email del repo
```

El CLI también funciona directo: `uv run corpus <comando>`. La capa Contexto es
la excepción: se ejecuta como módulo, sin pasar por el CLI:
`uv run python -m banco_occidente_corpus.contexto` (o `make contexto`). No hace
peticiones de red: solo lee Gold y mide con `stable_tokens`.

## Skills del proyecto

Viven en `.opencode/skills/` y se cargan bajo demanda:

| Skill | Para qué |
|---|---|
| `corpus-extraction` | Captura, regeneración y diagnóstico del pipeline (Bronze/Silver/Gold) |
| `semantic-extraction` | Convertir Gold en entidades/hechos/relaciones con cita y validación |

Úsalas antes de tocar el pipeline o la capa Knowledge; no dupliques sus reglas
aquí. Se pueden mencionar como `@corpus-extraction` y `@semantic-extraction`.

## Herramientas del agente (MCP)

`opencode.json` declara los servidores MCP: `docs-langchain` y
`reference-langchain` (remotos, solo consulta) y `scrapling` (local, navegación
ad hoc). Scrapling se instala con el grupo `mcp` y **no** es dependencia del
pipeline: no escribe en Bronze/Silver/Gold. Si lo usas contra el sitio del banco,
aplican igual `robots.txt`, el ritmo de cortesía de 1,5 s y el header `From`
(ver `CONSTITUTION.md` §3).

## Mapa del código

| Archivo | Responsabilidad |
|---------|-----------------|
| `src/banco_occidente_corpus/net.py` | HTTP: UA, `From`, delay, reintentos |
| `.../discover.py` | `robots.txt` + sitemap index + filtros de alcance |
| `.../fetch.py` | Bronze: guarda HTML crudo + `capture.jsonl` |
| `.../extract.py` | Silver: `trafilatura` + fallback BeautifulSoup |
| `.../dedupe.py` | Elimina boilerplate repetido |
| `.../section.py` | Clasifica páginas y extrae keywords |
| `.../gold.py` | Gold: Markdown + frontmatter + `corpus.jsonl` |
| `.../contexto.py` | Contexto: prompt del asistente desde Gold, config propia y entrada `python -m` |
| `.../checklist.py` | 24 casillas del Taller 1 |
| `.../stats.py` | Genera `data/gold/_INDICE.md` |
| `.../documents.py` | PDFs: inventario, descarga y extracción a Gold |
| `.../videos.py` | YouTube: canal, subtítulos y transcripción a Gold |
| `.../news.py` | Noticias: hechos oficiales, prensa curada, Gold e índice |
| `app/streamlit_app.py` | App Streamlit: capa delgada que delega en `asistente/` |
| `scripts/tasks.py` | Tareas portables del Makefile |

## Verificación antes de dar algo por terminado

```bash
make fmt
make check       # debe pasar 100 %
make demo        # el pipeline completo sigue funcionando sin red
make status      # URLs / Bronze / Silver / Gold
```

Si tocaste el corpus, revisa `data/gold/_INDICE.md` y confirma que la cobertura
del checklist no bajó.

## Reglas de revisión (GGA)

Instrucciones para quien revisa (GGA): el código a revisar ya viene completo en este mensaje. No ejecutes comandos ni leas otros archivos; revisa solo el contenido recibido. Escribe la línea `STATUS: PASSED` o `STATUS: FAILED` al comienzo de tu respuesta y después la lista de violaciones.

REJECT if:
- Se usa `pip`, se crea `requirements.txt` o se edita `uv.lock` a mano.
- Una petición HTTP no pasa por `net.py`, no tiene `timeout`, no envía el User-Agent y el header `From` del proyecto, o usa `verify=False`.
  La regla anterior cubre el sitio del banco y las fuentes del corpus; las llamadas a la API del modelo desde `asistente/` van por el cliente de LangChain, con `timeout`, sin claves en el código y sin leer `.env`.
- Se descarga una URL sin consultar antes `robots.txt` o se baja el ritmo de cortesía de 1,5 s entre peticiones (decisión del proyecto; `robots.txt` no declara `Crawl-delay`).
- Se captura una página con login, formulario, simulador o datos personales (Ley 1581 de 2012).
- Se usa cualquier técnica para evadir protecciones anti-bot o captchas.
- `extract.py` hace peticiones de red: debe recibir HTML ya descargado.
- Hay secretos, tokens o claves en el código, o se lee un archivo `.env`.
- Cambia el formato de Gold sin actualizar `CONSTITUTION.md` §7 en el mismo commit.
- Hay código nuevo en `src/` sin su prueba en `test/`.
- Una función pública no tiene anotaciones de tipo o docstring.

REQUIRE:
- Pruebas sin red: el HTML de ejemplo vive dentro de `test/`.

## Recordatorio final

Siguen vigentes las reglas del inicio: solo `uv`; Bronze no se toca a mano; Gold es el contrato; `robots.txt`, 1.5 s y header `From`; sin datos personales.
