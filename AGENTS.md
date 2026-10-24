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
   `Crawl-delay` (1.5 s) y el header `From` con el contacto académico.
   No subas el ritmo para "terminar rápido".
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
make check       # lint + typecheck + pruebas
make health      # integridad de las capas y del contrato de Gold
make identity    # fija user.name / user.email del repo
```

El CLI también funciona directo: `uv run corpus <comando>`.

## Skills del proyecto

Viven en `.opencode/skills/` y se cargan bajo demanda:

| Skill | Para qué |
|---|---|
| `corpus-extraction` | Captura, regeneración y diagnóstico del pipeline (Bronze/Silver/Gold) |
| `semantic-extraction` | Convertir Gold en entidades/hechos/relaciones con cita y validación |

Úsalas antes de tocar el pipeline o la capa Knowledge; no dupliques sus reglas
aquí. Se pueden mencionar como `@corpus-extraction` y `@semantic-extraction`.

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
| `.../checklist.py` | 24 casillas del Taller 1 |
| `.../stats.py` | Genera `data/gold/_INDICE.md` |
| `.../documents.py` | PDFs: inventario, descarga y extracción a Gold |
| `.../videos.py` | YouTube: canal, subtítulos y transcripción a Gold |
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

REJECT if:
- Se usa `pip`, se crea `requirements.txt` o se edita `uv.lock` a mano.
- Una petición HTTP no pasa por `net.py`, no tiene `timeout`, no envía el User-Agent y el header `From` del proyecto, o usa `verify=False`.
- Se descarga una URL sin consultar antes `robots.txt` o se baja el `Crawl-delay` de 1.5 s.
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
