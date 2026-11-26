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
   clientes (Ley 1581 de 2012). **Excepción acotada:** la memoria de perfil
   (`sucursal/perfil.py`) guarda solo el nombre y la empresa que el usuario
   declara, en `data/asistente/perfil.sqlite` (local, ignorado por Git), bajo un
   `perfil_id` aleatorio y hasheado. No se cachea, no se registra en logs y
   nunca se envía al modelo; se borra con «olvida mi perfil». No cubre datos de
   terceros, documentos, teléfonos, correos ni información de clientes.
   **Segunda excepción acotada, solo del canal de WhatsApp:** el número entrante
   se normaliza a E.164 y se convierte en
   `usuario_id = HMAC-SHA256(número, WHATSAPP_ID_SALT)` dentro de la petición;
   el número en claro no se persiste, no se registra en logs y nunca se envía al
   modelo. Solo se guarda el hash, el nombre y el rol que la persona declare,
   con consentimiento previo. **Tercera excepción, solo para el voluntario activo
   de la escena:** `canal/escena_vivo.py` guarda el destino normalizado en RAM
   mientras dura el TTL, únicamente para que `POST /api/escena/hablar` envíe la
   respuesta y la ficha por WhatsApp; no se persiste, no se registra, no se
   envía al modelo y se borra al vencer. Sigue prohibido capturar teléfonos del
   sitio o de terceros.
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
make fragmentos  # fragmentos de la Bóveda desde chunks y hechos (sin red)
make indice      # indexa la Bóveda con Ollama (web + PDF de producto + hechos)
make indice-completo  # añade el resto de PDF y los videos
make tablero     # tarifario + tablas de Gold -> data/estructurados/tablero.csv
make app         # Sucursal 1965: FastAPI + app web en 127.0.0.1:8000
make agente-mcp  # servidor MCP del agente pana con las 20 tools en 127.0.0.1:8765
make herramientas # catálogo de las 20 tools y sus esquemas Pydantic (JSON=1)
make probar-openclaw # cliente de OpenClaw contra el gateway (token en el entorno)
make traza       # últimas llamadas a las tools, sin datos personales
make simular     # canal completo con las personas sintéticas y el enviador falso (sin red)
make arqueo      # data/evaluacion/arqueo.json y docs/ARQUEO.md (sin DeepSeek)
make migrar-qdrant # copia un índice Chroma ya construido a Qdrant sin revectorizar
make evaluar     # 20 preguntas del alcance -> docs/RESULTADOS_20_PREGUNTAS.md
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
| `boveda-rag` | Operar, medir y diagnosticar la Bóveda RAG (fragmentos, Chroma y Ollama) |
| `polanco-standard-auditor` | Auditar el repo contra el estándar Python + IA de Jan Polanco y proponer un roadmap no destructivo (vendor; fuera de `ruff`) |

Úsalas antes de tocar el pipeline o la capa Knowledge; no dupliques sus reglas
aquí. Se pueden mencionar como `@corpus-extraction`, `@semantic-extraction`,
`@boveda-rag` y `@polanco-standard-auditor`.

`polanco-standard-auditor` es código de terceros en `.opencode/skills/` y está
excluida del lint en `pyproject.toml` (`extend-exclude`): no se reformatea con
`make fmt`. Su evaluador es stdlib puro y se ejecuta con
`uv run python .opencode/skills/polanco-standard-auditor/scripts/evaluate_polanco_standard.py .`

Origen: `github.com/stiwardprieto/stiward-prieto-skills` (MIT, ver
`.opencode/skills/polanco-standard-auditor/LICENSE`), commit `8610f0b`. Para
actualizarla, copiar la carpeta completa: no es un solo `SKILL.md`, también
trae `references/` y `scripts/`.

## Herramientas del agente (MCP)

`opencode.json` declara los servidores MCP: `docs-langchain` y
`reference-langchain` (remotos, solo consulta) y `scrapling` (local, navegación
ad hoc). Scrapling corre en su propio entorno con
`uvx --from "scrapling[ai,fetchers]>=0.5" scrapling mcp` y **no** es dependencia del
pipeline: no entra en `uv.lock`, no escribe en Bronze/Silver/Gold y ningún
`uv run`/`make` puede desinstalarlo. Si lo usas contra el sitio del banco,
aplican igual `robots.txt`, el ritmo de cortesía de 1,5 s y el header `From`
(ver `CONSTITUTION.md` §3).

## Piezas de la fase 2

| Pieza | Entrada | Contrato | Pruebas |
|---|---|---|---|
| Canal de WhatsApp | `canal/webhook.py` → `canal/cola.py` → `canal/despachador.py` → `canal/envio.py` | `docs/OPERACION_WHATSAPP.md` | `test/test_canal_*.py` |
| Modo evento | `canal/evento.py` + `[evento]` de `config/whatsapp.toml` | `docs/DESPLIEGUE_WHATSAPP.md` | `test/test_canal_evento.py` |
| Diagnóstico guiado | `canal/entrevista.py` + `diagnostico/motor.py` | `docs/DIAGNOSTICO.md` | `test/test_diagnostico_*.py`, `test/test_canal_entrevista.py` |
| Comité de crédito | `diagnostico/comite.py` | `docs/COMITE.md` | `test/test_diagnostico_comite.py` |
| MCP de solo lectura | `uv run python -m banco_occidente_corpus.mcp_servidor` | `docs/MCP.md` | `test/test_mcp_servidor.py` |
| Roba la Bóveda | `roba/` + `/api/roba/*` | `docs/ROBA_BOVEDA.md` | `test/test_roba_*.py`, `test/test_web_roba.py` |
| Simulador sin red | `make simular` + `simulador/` | este archivo | `test/test_simulador_*.py` |

Tasas 2026: las responde el **Tablero** (`data/gold/tasas/tasas-personas-AAAA-MM.jsonl`
→ `data/estructurados/tablero.csv`), no la Bóveda. La Bóveda cubre la ruta B
(preguntas de producto y política); el Tablero cubre la ruta T (tasa, cuota y
tarifa). El diagnóstico usa solo el Tablero para la tasa y nunca inventa una.

El canal tiene dos modos. `WHATSAPP_MODO=falso` (y `make simular`) recorre el
webhook con `EnviadorFalso`: no toca Meta ni necesita `DEEPSEEK_API_KEY`. El
modo `real` exige token vigente, app publicada, números autorizados con huella
en `config/whatsapp.toml` (local, nunca versionado) y consentimiento previo; es
un ensayo de demo, no una prueba de `make check`. No se guardan números en
claro, nombres de terceros ni textos libres: solo `usuario_id` HMAC, nombre y
rol declarados, con consentimiento.

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
| `.../boveda/fragmentos.py` | Fragmentos deterministas desde chunks y hechos (sin red) |
| `.../boveda/embeddings.py` | Embeddings locales con Ollama, prefijos y `timeout` |
| `.../boveda/almacen.py` | Qdrant local y Chroma opcional en `data/boveda/` con distancia coseno |
| `.../boveda/rutas.py` | Rutas y nombres de los almacenes de la Bóveda |
| `.../boveda/migracion.py` | Copia el índice de Chroma a Qdrant sin recalcular embeddings |
| `.../boveda/indice.py` | Índice por alcance (`base`/`completo`) y `indice.json` |
| `.../boveda/recuperador.py` | Recuperación híbrida vectorial + BM25 con pesos |
| `.../boveda/mapa.py` | Mapa PCA 2D de 0 a 100 y proyección de la pregunta |
| `.../tablero/tarifas.py` | Tarifario PDF → filas «concepto, valor y fecha» |
| `.../tablero/tablas_web.py` | Lector de tablas Markdown y adaptadores por página |
| `.../tablero/construir.py` | Une fuentes, escribe el CSV y cruza las 12 preguntas |
| `.../pana/` | Pana: dibujo del personaje y tarjetas PNG en memoria con su texto equivalente |
| `.../arqueo/metricas.py` | hit@5, MRR, exactitud, McNemar y tarifas de DeepSeek |
| `.../arqueo/experimentos.py` | Barrido de pesos y evaluación v2 con el grafo |
| `.../arqueo/informe.py` | `arqueo.json` y `ARQUEO.md` con recuperación, costo y McNemar |
| `.../arqueo/cache_embeddings.py` | Caché de embeddings para las corridas del Arqueo |
| `.../sucursal/tipos.py` | Turno y letras B/T/X |
| `.../sucursal/digiturno.py` | Reglas de enrutamiento y clasificación de dudas |
| `.../sucursal/perfil.py` | Memoria de perfil (nombre y empresa) sobre el store de LangGraph |
| `.../canal/identidad.py` | Número en E.164 y `usuario_id` HMAC; comando `--huella` para autorizar números |
| `.../canal/consentimiento.py` | Aviso de la Ley 1581, aceptación, rechazo y revocación con borrado |
| `.../canal/entrada.py` | Extrae y normaliza texto, botones y listas del payload de Meta |
| `.../canal/cola.py` | Cola de un trabajador para procesar fuera del webhook |
| `.../canal/despachador.py` | Identidad, autorización, consentimiento y respuesta del canal |
| `.../canal/firma.py` | Verifica `X-Hub-Signature-256` antes de procesar el payload |
| `.../canal/webhook.py` | Verificación de Meta y recepción del webhook |
| `.../canal/entrevista.py` | Entrevista del diagnóstico por WhatsApp y tarjeta |
| `.../canal/hitl.py` | `interrupt()`, botones Contactar/Descartar y caso de asesor |
| `.../canal/envio.py` | Cliente de Meta: `timeout`, User-Agent y `From` |
| `.../canal/openclaw.py` | Cliente del gateway OpenClaw: 45 s de techo, sin reintentos, UA, `From` y respaldo al grafo |
| `.../canal/escena_vivo.py` | `ESCENA` activa al voluntario, TTL en memoria y publicación de invitado y Pana |
| `.../escena/api_en_vivo.py` | `GET /api/escena/en-vivo`: solo lectura, 200 turnos y `no-store` |
| `.../escena/recursos.py` | QR del repositorio y de WhatsApp (`PANA_WHATSAPP_NUMERO`) y los diagramas de `docs/` |
| `.../canal/almacen.py` | Mensajes, consentimientos y casos en SQLite |
| `.../diagnostico/motor.py` | Contratos del canal → cálculo → `ResultadoDiagnostico` |
| `.../diagnostico/calculo.py` | Tasa mensual y cuota francesa |
| `.../diagnostico/escenarios.py` | «¿Y si…?» con `thread_id` nuevo |
| `.../diagnostico/comite.py` | Comité de crédito con auditor determinístico |
| `.../roba/` | Roba la Bóveda: clasificador, marcador, respondedor e API |
| `.../simulador/` | Recorrido sintético del canal con `EnviadorFalso` |
| `.../sucursal/operacion.py` | Panel de operación y latencias p50/p95 |
| `.../canal/entrevista.py` | Entrevista del diagnóstico por WhatsApp: pasos, comandos y tarjeta |
| `.../canal/hitl.py` | HITL del asesor: `interrupt()`, botones Contactar/Descartar y caso |
| `.../sucursal/grafo.py` | StateGraph con memoria, rutas y redacción |
| `.../sucursal/ajustes.py` | Tope de gasto, TTL y modo demo |
| `.../sucursal/costo.py` | Tarifas valle/pico, gasto diario y caché |
| `.../sucursal/api.py` | Endpoints de estado, datos y trazabilidad |
| `.../mcp_servidor/servidor.py` | Servidor MCP de solo lectura: tasas, cuota y búsqueda en la Bóveda |
| `.../mcp_servidor/agente.py` | Entrada del MCP del agente `pana` por HTTP en loopback (20 tools) |
| `.../herramientas/catalogo.py` | Las 20 tools del agente, su dueña y su entrada Pydantic |
| `.../herramientas/lectura.py` | Tools 1–11 y 17–20: Tablero, motor, escena, Bóveda y auditor |
| `.../herramientas/estado.py` | Tools 12–16: consentimiento, borrado, asesor y tarjeta |
| `.../herramientas/traza.py` | Traza JSONL de cada llamada, sin textos libres ni PII |
| `.../herramientas/servidor.py` | Servidor MCP HTTP con las 20 tools y el host loopback |
| `openclaw/` | Workspace de Pana, `openclaw.json` redactado y scripts de sincronización |
| `.../live_capture.py` | Captura en vivo en carpeta temporal, con etapas para la app |
| `app.py` | Arranque de FastAPI y la app web en `127.0.0.1:8000` |
| `app/web/` | App web de la Sucursal 1965 (HTML/CSS/JS) que consume la API |
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

Instrucciones para quien revisa (GGA): el código a revisar ya viene completo en este mensaje. No ejecutes comandos ni leas otros archivos; revisa solo el contenido recibido. Escribe la línea `STATUS: PASSED` o `STATUS: FAILED` al comienzo de tu respuesta y después la lista de violaciones. El modelo de amenazas y las mitigaciones viven en `docs/SEGURIDAD.md`.

REJECT if:
- Se usa `pip`, se crea `requirements.txt` o se edita `uv.lock` a mano.
- Una petición HTTP no pasa por `net.py`, no tiene `timeout`, no envía el User-Agent y el header `From` del proyecto, o usa `verify=False`.
  La regla anterior cubre el sitio del banco y las fuentes del corpus; las llamadas a la API del modelo desde `asistente/` van por el cliente de LangChain, con `timeout`, sin claves en el código y sin leer `.env`.
  Las llamadas a Ollama desde `boveda/` van por `langchain-ollama` con `timeout` explícito (`embeddings.timeout_segundos`); no aplican `robots.txt`, `From` ni 1,5 s porque el destino es local y no es scraping, pero el `timeout` sí es obligatorio.
  Las llamadas del canal de WhatsApp a la API de Meta (`graph.facebook.com`, desde `canal/envio.py`) van con `timeout` explícito, el User-Agent del proyecto y el header `From`; no aplican `robots.txt` ni la pausa de 1,5 s porque no son scraping del sitio del banco, pero el `timeout` sí es obligatorio y nunca se usa `verify=False`.
  Las llamadas del canal al gateway local de OpenClaw (`canal/openclaw.py`, solo `127.0.0.1`, `localhost` o `::1`) van con `httpx`, `timeout` explícito de `gateway.timeout_segundos` (45 s de techo y 3 s para conectar), el User-Agent de `config/site.toml` y el header `From` con `site.contact`; no aplican `robots.txt` ni la pausa de 1,5 s porque es un `POST` a un servicio local y no scraping, no reintenta (un reintento repetiría el turno) y nunca se usa `verify=False`.
  La descarga de los modelos de voz de Piper (`make voz-modelo`, desde `voz/descarga.py`, al repositorio público `huggingface.co/rhasspy/piper-voices`) va con `httpx`, `timeout` explícito, el User-Agent del proyecto y el header `From`; no aplican `robots.txt` ni la pausa de 1,5 s porque no es scraping del sitio del banco, y nunca se usa `verify=False`.
  La corrida de inyección contra el gateway local de OpenClaw (`arqueo/inyeccion_vivo.py`, solo `127.0.0.1` o `localhost`) va con `httpx`, `timeout` explícito, el User-Agent de `config/site.toml` y el header `From` con `site.contact` (sin contacto no arranca); no aplican `robots.txt` ni la pausa de 1,5 s porque es un `POST` a un servicio local y no scraping, no reintenta (un reintento repetiría el ataque) y nunca se usa `verify=False`.
  El User-Agent de navegador de `config/site.toml` es una decisión del grupo documentada en `CONSTITUTION.md` §10 (el WAF responde 403 a todo User-Agent que se declare bot): **no** es motivo de REJECT ni cuenta como evasión, siempre que se envíe el header `From`, se respete `robots.txt` y el ritmo de 1,5 s, y ante un 403 el pipeline se detenga sin reintentar con otro cliente.
- Se descarga una URL sin consultar antes `robots.txt` o se baja el ritmo de cortesía de 1,5 s entre peticiones (decisión del proyecto; `robots.txt` no declara `Crawl-delay`).
- Se captura una página con login, formulario, simulador o datos personales (Ley 1581 de 2012).
- Se usa cualquier técnica para evadir protecciones anti-bot o captchas.
- `extract.py` hace peticiones de red: debe recibir HTML ya descargado.
- Hay secretos, tokens o claves en el código, o se lee un archivo `.env`.
- Se versiona el índice vectorial o una base SQLite del asistente: `data/boveda/`
  (Qdrant, Chroma opcional, `indice.json`, `mapa.json`, fragmentos) o `data/asistente/`
  (`memoria.sqlite`, `cache.sqlite`, `gasto.sqlite`). Se regeneran con
  `make indice` o se crean al preguntar; `.gitignore` los excluye y
  `test/test_seguridad.py::test_indice_y_sqlite_fuera_de_git` lo comprueba.
- El servidor de la Sucursal se publica en `0.0.0.0`, `::` o cualquier host
  distinto de `127.0.0.1` (uvicorn, `app.py`, `make app` o un comando manual).
  `app.py` fija `HOST = "127.0.0.1"` y `main()` lo pasa a `uvicorn.run`;
  `test/test_app_web.py::test_escucha_solo_en_localhost` y
  `test/test_seguridad.py::test_uvicorn_recibe_solo_loopback` lo comprueban.
- Se publica por el túnel una ruta distinta de `/webhooks/whatsapp` o `/health`,
  o se quita la guarda de `app.py` que responde `404` a las peticiones que no
  son locales. La superficie pública y su residual están en
  `docs/SEGURIDAD.md` §3.12; `test/test_tunel_publico.py` lo comprueba.
- Se repiten los precios de DeepSeek (`0.15/0.003/0.60` valle,
  `0.30/0.006/1.20` pico) en código de producción (`src/` fuera de
  `arqueo/metricas.py`, `app.py`, `scripts/` o `config/`). La única fuente es
  `arqueo/metricas.py`; `test/test_arqueo_metricas.py` puede fijarlos como
  guardián y `test/test_seguridad.py::test_precios_deepseek_solo_en_metricas`
  detecta la duplicación.
- Se trata un fragmento de la Bóveda como instrucción: se concatena antes de
  las reglas del sistema, se pasa a un `SystemMessage` propio, se omite
  `_neutralizar` o se usa su texto para elegir ruta. Los fragmentos son datos:
  van dentro de `<fragmentos>` antes de `prompt.sistema` (`asistente/rag.py`) y
  la regla 2 de `config/prompts/qa_v2.md` lo exige;
  `test/test_asistente_rag.py::test_formatear_fragmentos_neutraliza_cierre` y
  `test/test_seguridad.py::test_fragmento_malicioso_no_cambia_el_sistema` lo
  comprueban.
- Se guarda en `data/asistente/cache.sqlite` una respuesta de un turno `X` o
  con datos personales. `sucursal/preguntar.py` solo cachea si la letra no es
  `X` y la respuesta no es la frase fija;
  `test/test_sucursal_preguntar.py::test_pii_no_entra_en_cache_ni_en_logs` y
  `::test_rechazo_no_escribe_cache` lo comprueban.
- Una prueba invoca un cliente real de DeepSeek u Ollama, o depende de que el
  servicio esté encendido, en lugar de usar un doble (`FakeListChatModel`,
  `DeterministicFakeEmbedding`, recuperador simulado). `test/conftest.py`
  bloquea cualquier `connect`/`connect_ex` fuera de loopback y `make check`
  debe pasar sin `DEEPSEEK_API_KEY` y con Ollama apagado.
- Cambia el formato de Gold sin actualizar `CONSTITUTION.md` §7 en el mismo commit.
- Hay código nuevo en `src/` sin su prueba en `test/`.
- Una función pública no tiene anotaciones de tipo o docstring.

REQUIRE:
- Pruebas sin red: el HTML de ejemplo vive dentro de `test/`.

## Recordatorio final

Siguen vigentes las reglas del inicio: solo `uv`; Bronze no se toca a mano; Gold es el contrato; `robots.txt`, 1.5 s y header `From`; sin datos personales.
