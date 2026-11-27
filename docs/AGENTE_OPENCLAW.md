# Agente `pana` sobre OpenClaw: workspace y veinte herramientas

Este documento cubre el entregable del **Módulo 3** que pide OpenClaw, el
workspace y las veinte herramientas tipadas: qué está versionado, cómo se
arranca y cómo se demuestra cada pieza. El cambio OpenSpec vive en
[`openspec/changes/agente-openclaw/`](../openspec/changes/agente-openclaw/).

## 1. Estado del entregable

| Pieza | Dónde | Estado |
|---|---|---|
| Workspace `SOUL.md`, `AGENTS.md`, `USER.md`, `IDENTITY.md` | `openclaw/workspace/pana/` | Versionado (PR #190) |
| `MEMORY.md` y bitácora diaria, fuera de Git | `openclaw/workspace/pana/` + semillas versionadas | Versionadas las semillas; la memoria real local se ignora |
| Configuración redactada del gateway | `openclaw/openclaw.json` | Versionada, sin secretos |
| Servidor MCP con veinte herramientas | `src/banco_occidente_corpus/herramientas/` | Implementado y probado |
| Entrada del servidor | `python -m banco_occidente_corpus.mcp_servidor.agente` | `make agente-mcp` |
| Cliente del gateway y respaldo al grafo | `src/banco_occidente_corpus/canal/openclaw.py` | Implementado y probado (25-nov) |
| Traza local de herramientas | `data/asistente/trazas/herramientas.jsonl` | `make traza` |
| Gateway, token y auditoría | WSL + `OPENCLAW_GATEWAY_TOKEN` | Operativo (26-nov): 0 críticas y 2 advertencias justificadas |
| WhatsApp real de punta a punta | Meta + despachador + gateway + MCP | Verificado el 26-nov; evidencia en [`EVIDENCIA.md`](./EVIDENCIA.md) |

**Estado final (26 de noviembre de 2026).** Todas las piezas están en `main` y
la operación real quedó verificada en el computador de la demo: un invitado
escribió por WhatsApp, aceptó el aviso de la Ley 1581, recorrió la escena con
las herramientas y Pana retomó la conversación después de reiniciar WSL, el
gateway, el MCP y la app. La tabla de evidencia, con fecha, comando y archivo de
cada afirmación, está en [`EVIDENCIA.md`](./EVIDENCIA.md) («Evidencia de Nayla —
semana del 24 al 26 de noviembre de 2026»).

El servidor **stdio** `boveda-occidente` (`make` no lo arranca; se invoca con
`python -m banco_occidente_corpus.mcp_servidor`) conserva sus tres herramientas
de solo lectura. El servidor nuevo es otro proceso, por HTTP y en loopback.

## 2. Arquitectura

```text
Invitado (WhatsApp)
   │  mensaje nuevo
   ▼
Meta Cloud API ──► webhook (firma) ──► cola ──► despachador
                                                  │  user = wa:<huella>
                                                  ▼
                                   POST /v1/chat/completions
                                                  │
                                        gateway OpenClaw :18789
                                                  │  agente pana
                                                  ▼
                                   MCP HTTP :8765/mcp (20 herramientas)
                                                  │
                                                  ▼
                                   texto ──► despachador ──► WhatsApp
                                     └── fallo o timeout ──► grafo actual
```

WhatsApp va **solo** por Meta. OpenClaw no tiene canal de WhatsApp en este
cambio: es el motor del agente detrás del despachador.

Tres fronteras separan la arquitectura de la red y se comprueban por separado:

- **Antes del motor manda el canal.** Autorización, consentimiento, ventana del
  evento, cuota, comandos que empiezan por «/» y datos personales se resuelven
  en el despachador; lo que no pasa esas puertas no llega al gateway (§4.1 y
  [`SEGURIDAD.md`](./SEGURIDAD.md) §3.9).
- **El gateway no ejecuta ni sale del workspace.** `exec.security: "deny"`,
  `tools.deny`, `tools.fs.workspaceOnly` y permisos elevados apagados; además
  los comandos del gateway están desactivados, así que «/think high» es texto
  normal (§6 y [`openclaw/README.md`](../openclaw/README.md), «Defensa en
  profundidad»).
- **El túnel solo publica el webhook.** `/webhooks/whatsapp` y `/health`
  responden desde fuera; la pantalla, `/docs`, la API y la ruta en vivo dan
  `404` y solo existen en `127.0.0.1:8000` ([`SEGURIDAD.md`](./SEGURIDAD.md)
  §3.12).

## 3. Catálogo de veinte herramientas

Cada herramienta declara un modelo `Pydantic` de entrada (`extra="forbid"`) y
devuelve el sobre común `SalidaHerramienta` (`ok`, `datos`, `error`, `traza_id`).
El catálogo completo se imprime con `make herramientas` y sus esquemas con
`make herramientas JSON=1`. La ficha de las veinte —entrada, salida, fuente,
confirmación, módulo delegado y cuándo no usarla—, las herramientas del gateway
que Pana tiene bloqueadas y la evidencia de control de la alucinación viven en
[`docs/HERRAMIENTAS.md`](./HERRAMIENTAS.md), que se regenera con
`make herramientas-doc`.

| # | Herramienta | Dueña | Reutiliza |
|---|---|---|---|
| 1 | `consultar_tasa` | Nayla | `mcp_servidor/servidor.py` y el Tablero |
| 2 | `simular_cuota` | Nayla | `diagnostico/calculo.py` |
| 3 | `verificar_usura` | Nayla | `config/tasas.toml` |
| 4 | `diagnosticar_capacidad` | Nayla | `diagnostico/motor.py` |
| 5 | `comparar_escenario` | Nayla | `diagnostico/escenarios.py` |
| 6 | `convocar_comite` | Nayla | `diagnostico/comite.py` |
| 7 | `calcular_prestamo_gota` | Nayla | `escena/gota.py` |
| 8 | `comparar_gota_banco` | Nayla | `escena/comparacion.py` |
| 9 | `negociar_opcion` | Nayla | `escena/negociacion.py` |
| 10 | `generar_ficha_opcion` | Nayla | `pana/desde_diagnostico.py` (texto) |
| 11 | `responder_sobre_proyecto` | Nayla | `escena/proyecto.py` (BM25, sin modelo) |
| 12 | `registrar_consentimiento` | Darley | `canal/consentimiento.py` |
| 13 | `olvidar_mis_datos` | Darley | `canal/consentimiento.py` y `sucursal/perfil.py` |
| 14 | `solicitar_asesor` | Darley | `canal/almacen.py` |
| 15 | `consultar_caso` | Darley | `canal/almacen.py` |
| 16 | `generar_tarjeta_pana` | Darley | `pana/desde_diagnostico.py` (PNG opcional) |
| 17 | `buscar_en_documentos` | Anny | `mcp_servidor/conocimiento.py` (#198), sobre `buscar_en_boveda` |
| 18 | `consultar_tarifas` | Anny | `mcp_servidor/conocimiento.py` (#198), sobre el Tablero |
| 19 | `clasificar_pregunta` | Anny | `mcp_servidor/control.py` (#199), sobre el Digiturno |
| 20 | `auditar_respuesta` | Anny | `mcp_servidor/control.py` (#199) y `diagnostico/comite.py::auditar_texto` |

Reglas del catálogo:

- Las herramientas de lectura (1–11, 15, 17–20) no escriben en Gold, Bóveda,
  Tablero ni bases del asistente.
- Las de estado (12–14 y 16) escriben solo en `data/asistente/`, siempre bajo
  la huella HMAC; nunca en el corpus.
- `olvidar_mis_datos` y `solicitar_asesor` exigen **dos pasos**: el primero
  devuelve `requiere_confirmacion: true` y un token de 16 caracteres; el segundo
  solo ejecuta si el token coincide y está vigente (5 minutos). Sin confirmación
  no se borra nada ni se abre un caso.
- `convocar_comite` necesita `DEEPSEEK_API_KEY`. Sin clave no inventa una
  deliberación: devuelve los escenarios precalculados y
  `codigo="modelo_no_disponible"`.
- `consultar_tasa`, `simular_cuota` y `buscar_en_documentos` envuelven las tres
  herramientas existentes; no duplican cálculos ni cifras.

## 4. Cómo se arranca

```bash
make agente-mcp          # MCP del agente en http://127.0.0.1:8765/mcp
make herramientas        # tabla de las 20 herramientas
make herramientas JSON=1 # contrato JSON completo (entradas Pydantic)
make traza               # últimas 20 llamadas registradas
```

El puerto y el host salen de `config/openclaw.toml`:

```toml
[mcp]
host = "127.0.0.1"
puerto = 8765
ruta = "/mcp"
```

`cargar_configuracion_mcp()` rechaza cualquier host que no sea loopback. Una
prueba fija que `crear_servidor()` nunca recibe un host público.

Para conectarlo al gateway, el bloque versionado de `openclaw/openclaw.json` es:

```json
"mcp": {
  "servers": {
    "sucursal": {
      "url": "http://127.0.0.1:8765/mcp",
      "transport": "streamable-http",
      "enabled": true,
      "connectionTimeoutMs": 5000,
      "requestTimeoutMs": 8000,
      "toolFilter": {"include": ["consultar_tasa", "…las veinte…"]}
    }
  }
}
```

Dos detalles de OpenClaw que importan:

1. `agents.entries.pana.tools.alsoAllow` incluye `bundle-mcp`. El perfil
   `minimal` no expone los servidores MCP por sí solo; sin `bundle-mcp` el
   servidor conecta pero sus herramientas no llegan al modelo.
2. `toolFilter.include` es la lista cerrada de las veinte. Un nombre que no esté
   allí no se descubre. El `mcp.servers` real vive en WSL; la copia del
   repositorio se actualiza con `scripts/exportar_config_openclaw.ps1` después
   de replicar este bloque allí.

### 4.1 Cliente del canal y respaldo

`canal/openclaw.py` es el único punto que habla con
`http://127.0.0.1:18789/v1/chat/completions`:

- Solo se activa con `OPENCLAW_ACTIVO=1` y `OPENCLAW_GATEWAY_TOKEN`. Sin token,
  con `fallback_forzado = true` o sin `site.contact`, el despachador responde
  con el grafo; no hay token por defecto.
- El cuerpo lleva `model = openclaw:pana`, `user = wa:<huella>` y **un solo**
  mensaje. No viajan el número, el historial, el perfil ni los fragmentos.
- Usa `httpx` con `timeout` de `gateway.timeout_segundos` (45 s de techo, 3 s
  para conectar), el User-Agent y el header `From` de `config/site.toml`; el
  host debe ser loopback, no hay reintentos y nunca se usa `verify=False`.
- Ante timeout, error de red, `5xx`, `401`, cuerpo inválido o contenido vacío,
  devuelve `None` y el despachador llama al grafo. El invitado recibe **una**
  respuesta: la del gateway o la del respaldo, nunca las dos.
- El orden del turno no cambia: autorización, consentimiento, entrevista,
  escenario y HITL corren antes del motor. Los textos que empiezan por `/` no
  se reenvían (el gateway tiene sus propios comandos) y los que traen PII se
  quedan en el grafo, que aplica la política completa.
- La tabla `mensajes` guarda `motor` (`openclaw`, `grafo` o `canal`) para que la
  operación sepa quién respondió. Una base anterior recibe la columna al
  arrancar, sin perder datos.

Prueba de humo, con el gateway encendido y el token en la misma sesión:

```powershell
$env:OPENCLAW_ACTIVO = "1"
$env:OPENCLAW_GATEWAY_TOKEN = "<token>"
make probar-openclaw PREGUNTA="¿Cuál es la tasa de libre inversión?"
```

`make probar-openclaw` usa `scripts/probar_openclaw.py`: sale con 0 si el
gateway responde, 1 si el gateway falla (el canal usaría el grafo) y 2 si falta
el interruptor, el token o `site.contact`. No imprime el token y usa una huella
de prueba de 64 hexadecimales.

## 5. Traza visible

Cada llamada deja una línea JSON en `data/asistente/trazas/herramientas.jsonl`
(carpeta ignorada por Git):

```json
{"id": "513d8c6e06d5", "momento": "2026-11-23T23:25:37+00:00",
 "herramienta": "verificar_usura", "ok": true, "codigo": null,
 "latencia_ms": 0.252, "argumentos": {"tasa_ea": 0.35, "producto": null}}
```

- `traza_id` viaja dentro de la respuesta MCP: el panel de operación y la
  pantalla en vivo pueden señalar la llamada exacta.
- Los textos libres (`texto`, `pregunta`, `mensaje`, `consulta`, `producto`,
  `motivo`, `nombre`, `empresa`) **no** se guardan: solo su longitud. La huella
  se recorta a 12 caracteres. No hay números, nombres ni montos de invitados.
- `make traza` imprime hora, herramienta, estado, latencia y argumentos no
  sensibles. La traza se borra con la carpeta `data/asistente/` o al cerrar el
  evento.
- La trazabilidad del turno vive en `mensajes.motor`, no en la traza de
  herramientas: `openclaw` si respondió el gateway, `grafo` si respondió el
  respaldo y `canal` si fue una respuesta determinista del canal.

## 6. Seguridad

- **Loopback**: el MCP escucha en `127.0.0.1:8765`; el gateway en
  `127.0.0.1:18789`. Nada se publica en `0.0.0.0`.
- **Sin secretos**: `openclaw/openclaw.json` referencia
  `${OPENCLAW_GATEWAY_TOKEN}`; el token real vive en WSL. `config/openclaw.toml`
  no contiene claves.
- **Pydantic cerrado**: cada entrada usa `extra="forbid"` y límites de largo,
  rango y patrón. Una huella debe ser HMAC de 64 hexadecimales; un número de
  teléfono en claro no pasa la validación.
- **Dos pasos**: las dos acciones con efecto irreversible piden confirmación
  explícita y consumen el token una sola vez.
- **Herramientas fuera del catálogo**: el servidor MCP responde
  `Unknown tool` y no ejecuta nada.
- **Fragmentos como datos**: `buscar_en_documentos` devuelve los fragmentos con
  su aviso; el agente no los interpreta como instrucciones.
- **Sin PII en la traza**: la prueba
  `test_herramientas_traza.py::test_con_traza_registra_y_no_guarda_texto_libre`
  comprueba que un teléfono dictado no llega al archivo.

## 7. Pruebas

```bash
uv run pytest test/test_mcp_agente.py test/test_herramientas_lectura.py \
  test/test_herramientas_estado.py test/test_herramientas_traza.py
```

| Prueba | Qué comprueba |
|---|---|
| `test_mcp_agente.py` | Las 20 herramientas, el reparto 11/5/4, esquemas cerrados con entrada y salida, herramienta desconocida rechazada y host loopback |
| `test_herramientas_lectura.py` | Tasa, usura, gota, diagnóstico, escenario, negociación, ficha, proyecto, tarifas, Digiturno y auditor |
| `test_herramientas_estado.py` | Consentimiento, borrado y asesor en dos pasos, caso aislado por huella y tarjeta |
| `test_herramientas_traza.py` | Traza, error de validación estable, firma conservada y redacción de textos |
| `test_canal_openclaw.py` | Cuerpo sin historial, `user = wa:<huella>`, sin número, timeout, error de red, `5xx`, cuerpo inválido, sin token y sin reintentos |
| `test_canal_despachador.py` | OpenClaw primero, respaldo al grafo, una sola respuesta, comandos `/` y PII fuera del gateway, y `motor` en la traza |

Todas corren sin red, sin `DEEPSEEK_API_KEY` y con Ollama apagado. La prueba de
`buscar_en_documentos` usa un doble del recuperador para no depender del índice.
El cliente del gateway usa `httpx.MockTransport`: no necesita el gateway
encendido ni `OPENCLAW_GATEWAY_TOKEN`.

## 8. Cómo se verifica que todo funciona

La verificación tiene dos capas: lo que corre sin red en `make check` (§7) y lo
que solo se ve con las piezas encendidas. Esta es la segunda, con el resultado de
la semana del 24 al 26 de noviembre; el detalle, la fecha y el archivo de cada
afirmación están en [`EVIDENCIA.md`](./EVIDENCIA.md).

| # | Qué se comprueba | Cómo | Resultado del 26-nov |
|---|---|---|---|
| 1 | El repositorio queda en verde sin red, sin clave y con Ollama apagado | `make check` y `openspec validate agente-openclaw --strict` | En verde; es la compuerta de cada commit |
| 2 | El gateway responde y ve las veinte herramientas | `wsl -d OpenClawGateway -- openclaw health`; después `openclaw daemon stop`, `openclaw mcp doctor sucursal --probe` y `openclaw daemon start` | Health correcto y `sucursal: ok` con la lista cerrada |
| 3 | No hay hallazgos críticos ni altos | `openclaw security audit` | 0 críticas y 2 advertencias justificadas (#209) |
| 4 | El gateway contesta y usa herramientas | `make probar-openclaw PREGUNTA="¿Cuál es la tasa de libre inversión?"` y `make traza` | Respondió y la traza mostró la herramienta elegida |
| 5 | El recorrido real por WhatsApp | Un teléfono de la lista escribe «hola», acepta el aviso y pide una tasa o un diagnóstico; luego `make traza` | Consentimiento, `consultar_tasa` y la escena completa con `motor="openclaw"` |
| 6 | Un invitado fuera de la lista entra con el modo evento | `WHATSAPP_EVENTO=1` con la ventana vigente y un número que no está en `[autorizados]` | Recibió el aviso, aceptó y conversó con Pana; la cuota se respetó |
| 7 | La memoria sobrevive al reinicio | Reiniciar WSL, el gateway, el MCP y la app; la misma persona hace una pregunta de seguimiento | Pana retomó el hilo («¿seguimos con lo de la moto?») sin guardar PII |
| 8 | La escena en vivo publica y se ve | `ESCENA_EN_VIVO=1` en el MCP y en la app, `ESCENA` y el código del voluntario, pantalla en **E** | Turnos de Don Gota, Pana, los dos agentes y el auditor, con voz y cifras en pesos |
| 9 | El túnel no abre nada más que el webhook | Desde fuera, `/health` y `/api/estado`; `uv run pytest test/test_tunel_publico.py` | `/health` responde `200`; `/api/estado` y `/escena.html`, `404` (#229) |

**Lo que queda.** Dos piezas no se presentan como hechas: responder a las notas
de voz y cerrar por WhatsApp el recorrido de «olvida mis datos» con su
confirmación. El borrado del evento (`make limpiar-evento CONFIRMAR=1`) se corre
igual el viernes después de los ensayos y el sábado después de la sustentación
(§9).

## 9. Limpieza al terminar el evento

La decisión 9 del design pide borrar perfiles, memorias y bitácoras al cerrar
el evento y dejar solo métricas agregadas. Para la parte de OpenClaw y del
computador de la demo, el contrato es
[`scripts/limpiar_evento.ps1`](../scripts/limpiar_evento.ps1), que se ejecuta
en modo de prueba con `make limpiar-evento` y borra de verdad solo con
`make limpiar-evento CONFIRMAR=1`. Se corre el viernes después de los ensayos
y el sábado después de la sustentación
([`LISTA_DEMO.md`](./LISTA_DEMO.md), sección 7).

Qué hace, en orden:

1. Lista las sesiones con
   `openclaw sessions list --agent pana --limit all --json` y las borra en
   lotes de 25 con `openclaw sessions delete <claves...> --agent pana --yes`.
   La sesión principal `agent:pana:main` no se toca: OpenClaw la protege y el
   comando falla si se intenta.
2. Olvida las memorias derivadas con
   `openclaw memory forget --agent pana --session <clave>`, en lotes de 20.
   Se eligió `--session` por clave y no `--since` porque borra exactamente lo
   derivado de las sesiones que se acaban de eliminar, sin arrastrar memorias
   de otras sesiones del mismo agente.
3. `memory forget` es **offline-only**: exige propiedad exclusiva del estado.
   Por eso, solo con `-Confirmar`, el script detiene el gateway
   (`openclaw daemon stop`), ejecuta el olvido, limpia el índice derivado con
   `openclaw memory reset --agent pana --yes` y vuelve a arrancar el gateway
   (`openclaw daemon start`) en un bloque `finally`, aunque algo falle. En modo
   de prueba no detiene nada: solo informa qué olvidaría.
4. Purga los archivos archivados de las sesiones en la base SQLite del agente
   dentro de WSL (`openclaw-agent.sqlite`), con python3 y el módulo `sqlite3`:
   comprueba que existan `session_transcript_archives` y
   `session_transcript_cold_archives` (si falta alguna, lo avisa y sigue),
   cuenta sus filas en modo de prueba y, con `-Confirmar`, hace `DELETE FROM`
   en las dos, `PRAGMA wal_checkpoint(TRUNCATE)` y `VACUUM`. Esa purga corre en
   la misma ventana en que el gateway ya está detenido para el olvido, informa
   cuántas filas borró y el tamaño de la base antes y después, no toca ninguna
   otra tabla y no deja copia de respaldo de esas dos.
5. Borra `MEMORY.md`, `DREAMS.md` y todo el contenido de
   `memory\` del workspace de WSL, incluidos `dreaming\` y
   `.dreams\session-corpus\`, sin filtrar por extensión. Nunca toca los
   `.example`, las semillas (`MEMORY.semilla.md` y `memory\semilla.md`) ni los
   archivos versionados `SOUL.md`, `AGENTS.md`, `USER.md` e `IDENTITY.md`. Los
   archivos reales se regeneran desde las semillas con
   `scripts\sembrar_memoria.ps1`.
6. Borra en Windows `data/asistente/trazas/herramientas.jsonl` si existe.
   **No** borra `data/evaluacion/inyeccion.json`: es la evidencia de la tarea
   3.5 que cita [`INYECCION.md`](./INYECCION.md) y no guarda el texto de las
   respuestas ni datos de invitados.

**Archivos archivados.** `openclaw sessions delete` archiva el transcript
dentro de la base SQLite del agente (tablas `session_transcript_archives` y
`session_transcript_cold_archives`); por diseño, esos archivos retenidos pueden
seguir siendo elegibles para la búsqueda de memoria. OpenClaw 2026.11.6 no
expone un comando que purgue ese blob, y la promesa del consentimiento es
borrar los datos de los invitados. Por eso `-PurgarArchivos` hace la purga
dentro de WSL sobre `~/.openclaw/agents/pana/agent/openclaw-agent.sqlite`, sin
copia de respaldo de esas dos tablas (una copia conservaría lo que se quiere
borrar). El resto de la base no se respalda ni se modifica. Esa purga se prueba
el viernes después de los ensayos, antes de usarla el sábado
([`LISTA_DEMO.md`](./LISTA_DEMO.md), sección 7).

**Canal de WhatsApp.** El script no toca perfiles, consentimientos ni casos
del canal: son de Darley y se borran aparte. Al apagar el evento los
consentimientos aceptados se conservan hasta ese borrado.
