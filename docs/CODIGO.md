# Mapa del código: cómo leer el proyecto

Guía corta para quien pregunte por el repositorio, el código o las pruebas en la
sustentación. Es la fuente de las respuestas fijas `codigo`, `repositorio`,
`git_tokens`, `diagrama` y `pruebas` de `docs/PRESENTADOR.md` (`#p18` a `#p22`)
y de `config/escena.toml`, y también entra al recuperador del proyecto (BM25)
junto con `README.md`, `AGENTS.md`, `CONSTITUTION.md` y el resto de `docs/`.

## 1. Dónde está todo

| Pieza | Dónde | Qué hace |
|---|---|---|
| Arranque de la app | `app.py` | FastAPI + app web en `127.0.0.1:8000` (`make app`) |
| Código | `src/banco_occidente_corpus/` | Un paquete por capa |
| Pruebas | `test/` | Un archivo por módulo, sin red |
| Configuración | `config/*.toml` | Alcance, tasas, escena, canal, voz |
| Datos versionados | `data/gold/`, `data/contexto/`, `data/knowledge/` | El entregable del corpus |
| Documentación | `docs/` | Contratos, decisiones y diagramas |
| Diagramas | `docs/*.html` + `docs/*.json` | Generados con Archify |

## 2. Las capas de `src/banco_occidente_corpus/`

| Capa | Módulos | Responsabilidad |
|---|---|---|
| Corpus | `net`, `discover`, `fetch`, `extract`, `dedupe`, `section`, `gold`, `stats`, `documents`, `videos`, `news` | Bronze → Silver → Gold, sin tocar Bronze a mano |
| Conocimiento | `contexto`, `knowledge`, `checklist` | Contexto consolidado y hechos con cita |
| Asistente | `asistente/` | RAG con LangChain, DeepSeek y validación de fuente |
| Bóveda | `boveda/` | Fragmentos, embeddings con Ollama, Qdrant y recuperación híbrida |
| Sucursal | `sucursal/` | Grafo con memoria, Digiturno, costo y API |
| Canal | `canal/` | WhatsApp: webhook, firma, consentimiento, HITL y envío |
| Diagnóstico | `diagnostico/` | Entrevista, motor, semáforo, comité y «¿Y si…?» |
| Escena | `escena/` | Pana, Don Gota, negociación, auditor, preguntas y API |
| Apoyo | `tablero`, `pana`, `herramientas`, `mcp_servidor`, `arqueo`, `roba`, `simulador`, `voz` | Tablero, tarjetas, 20 tools, evaluación y juego |

El detalle archivo por archivo está en `AGENTS.md` («Mapa del código»). Si hay
diferencia entre los dos, manda `AGENTS.md`.

## 3. Cómo se lee una pregunta en la escena

1. `app/web/escena/anfitrion.js` aplica las reglas fijas del navegador.
2. `POST /api/escena/pregunta` entra por `escena/api.py`.
3. `escena/respondedor.py` arma el respondedor una sola vez.
4. `escena/pregunta.py` decide: ficha fija → proyecto (BM25) → banco → rechazo.
5. `escena/auditor.py` revisa cifras, fuentes y datos personales.
6. `app/web/escena/escena.js` pinta el turno y lo dice con voz.

Las respuestas fijas salen de `config/escena.toml [[preguntas.fijas]]` y de
`docs/PRESENTADOR.md`; el proyecto lo busca `escena/proyecto.py` en Markdown.
La entrada del voluntario (tecla V) usa `POST /api/escena/hablar`: el navegador
transcribe; con `pregunta`, `escena/api.py` interpreta con `escena/entrada.py` y
devuelve la letra o el monto con una línea de Pana. Sin `pregunta`, la frase
libre entra por `canal/despachador.py` (filtros del canal, OpenClaw con la
huella y envío por WhatsApp al voluntario activo). No se recibe audio ni se
guarda texto.

## 4. Pruebas y calidad

```bash
make fmt        # formato
make check      # ruff + ty + pytest
make demo       # pipeline completo sin red
```

- `test/conftest.py` bloquea cualquier conexión fuera de loopback: las pruebas
  no llaman a DeepSeek ni a Ollama.
- Los dobles son `FakeListChatModel`, `DeterministicFakeEmbedding` y
  recuperadores simulados.
- `.github/workflows/ci.yml` repite `make check` en cada pull request.

## 5. Git, ramas y secretos

- `main` está protegida: cada cambio entra por una rama y un pull request.
- La plantilla del PR es `.github/PULL_REQUEST_TEMPLATE.md`.
- Los commits siguen Conventional Commits en español y GGA los revisa.
- Las claves van por variables de entorno; el proyecto no lee `.env` y el
  repositorio no guarda tokens. `.env.example` solo lista los nombres.
- El único token del sistema es el del gateway local de OpenClaw, en
  `127.0.0.1`.

## 6. Diagramas

`docs/arquitectura.html`, `docs/datos.html`, `docs/canal.html`,
`docs/diagnostico.html`, `docs/agente-openclaw.html` y
`docs/despliegue-openclaw.html` son diagramas interactivos generados con
Archify desde su `.json`. La app los sirve en `/diagramas/<nombre>.html` y el
panel de recursos de la escena (tecla **G**) enlaza los seis.
