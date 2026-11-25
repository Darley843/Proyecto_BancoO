# Design

## Context

Ver `proposal.md` para la motivación. El estado actual que condiciona el diseño:

- `canal/webhook.py` verifica el `GET` de Meta, `canal/firma.py` valida `X-Hub-Signature-256`, `canal/cola.py` procesa fuera del webhook y `canal/despachador.py` aplica identidad, autorización, consentimiento y turno. El hilo del grafo es `wa:<usuario_id>` y el perfil vive bajo `("perfil", sha256(usuario_id))`.
- `canal/identidad.py` normaliza el número a E.164 y lo convierte en `usuario_id = HMAC-SHA256(número, WHATSAPP_ID_SALT)` dentro de la petición; el número en claro no se persiste ni se registra.
- `mcp_servidor/servidor.py` expone por **stdio** y solo lectura tres herramientas (`consultar_tasa`, `simular_cuota`, `buscar_en_boveda`) sobre el Tablero y la Bóveda. No abre puertos y ninguna herramienta escribe.
- `diagnostico/motor.py` y `diagnostico/calculo.py` resuelven cuota, tasa, semáforo y capacidad; `diagnostico/comite.py` aporta `auditar_texto`; `diagnostico/escenarios.py` resuelve «¿Y si…?».
- `escena/gota.py`, `escena/comparacion.py` y `escena/negociacion.py` (cambio `demo-gota-a-gota`) aportan el cálculo del gota, la comparación con la usura y la mesa acotada; el agente los reutiliza cuando existan y no depende de la pantalla ni de la API de la escena.
- `arqueo/metricas.py` ya mide `recall@k` y `nDCG@k` con `K_RECALL = 10`; `scikit-learn` y `httpx` ya son dependencias.
- `docs/OPERACION_WHATSAPP.md` documenta el túnel con `cloudflared` para exponer el webhook y la app escucha solo en `127.0.0.1`.
- Restricciones duras: solo `uv`; sin `.env`; sin secretos versionados; sin datos personales; pruebas sin red, sin DeepSeek y sin Ollama; toda función pública con anotaciones y docstring en español.
- Calendario: piezas separadas el lunes 23 y el martes 24; **integración completa y seguridad en verde el miércoles 25 a las 18:00**; jueves 26 solo correcciones, documentación, un ensayo y la etiqueta `entrega-final` a las 18:00; viernes 27 dos ensayos completos; sustentación el sábado 28.

## Goals / Non-Goals

**Goals:**

- Que un invitado real converse por WhatsApp con el agente `pana` de OpenClaw y reciba respuestas con cifras trazables.
- Que el agente use veinte herramientas de nuestro MCP, con esquemas Pydantic y permisos explícitos.
- Que el canal nunca quede sin respuesta: si OpenClaw falla, responde el grafo actual.
- Que el workspace, la memoria y la bitácora respeten la Ley 1581 y no mezclen datos de invitados.
- Que la entrega sea reproducible: configuración versionada, sin secretos, con auditoría de seguridad y pruebas offline.

**Non-Goals:**

- Un canal de WhatsApp propio de OpenClaw.
- Un segundo motor de mensajería o un reemplazo del webhook de Meta.
- Persistir conversaciones de clientes reales o publicar servicios fuera de loopback.
- Cambiar los umbrales del diagnóstico, la usura, el Tablero o el comité.
- Reescribir la escena `demo-gota-a-gota`; solo se cierran sus tareas descartadas o reemplazadas.

## Decisions

### 1. Topología de canales

WhatsApp va **solo** por Meta. OpenClaw no tiene canal de WhatsApp y no se le inventa uno: es el motor del agente detrás del despachador.

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
                                   MCP HTTP :8765 (20 herramientas)
                                                  │
                                                  ▼
                                   texto ──► despachador ──► EnviadorMeta ──► WhatsApp
                                     └── fallo o timeout ──► grafo actual
```

El consentimiento, la autorización de números, la firma, la deduplicación y la cola no cambian: el gateway entra **después** de esas compuertas.

### 2. Contrato del gateway

`canal/openclaw.py` encapsula el contrato y no deja que el despachador conozca detalles HTTP.

```http
POST http://127.0.0.1:18789/v1/chat/completions
Authorization: Bearer ${OPENCLAW_GATEWAY_TOKEN}
Content-Type: application/json

{"model": "openclaw:pana", "user": "wa:<huella>", "messages": [{"role": "user", "content": "<mensaje nuevo>"}]}
```

- **Solo el mensaje nuevo**: el gateway guarda el hilo por `user`; no se reenvía historial ni se duplica la memoria.
- `user` es `wa:<huella>`, nunca el número en claro ni el nombre del invitado.
- `timeout` explícito de `config/openclaw.toml`, **sin reintentos**: un reintento del gateway duplicaría el turno; la deduplicación por id de mensaje ya cubre a Meta.
- La respuesta se extrae de `choices[0].message.content`; un cuerpo vacío, un `finish_reason` anómalo o un error HTTP se tratan como fallo.
- `OPENCLAW_GATEWAY_TOKEN` se lee del entorno en el arranque. Sin token, el canal informa que el motor OpenClaw queda deshabilitado y usa el grafo; no hay valor por defecto.

### 3. Respaldo al grafo

`Despachador` recibe un `motor` con dos implementaciones: `OpenClaw` y el grafo actual. El orden es:

1. Si `OPENCLAW_ACTIVO=1` y hay token, se intenta el gateway.
2. Si hay `timeout`, error de conexión, `5xx` o respuesta inválida, se responde con el grafo y se registra `motor="grafo"` y el motivo, sin PII.
3. Si el gateway responde, se envía su texto y se registra `motor="openclaw"`.

El hilo del grafo sigue siendo `wa:<usuario_id>`; el del gateway lo administra OpenClaw. **No se migran hilos**: cada motor conserva el suyo y la trazabilidad declara cuál respondió. Un fallback a mitad de conversación no reinyecta el historial del gateway en el grafo.

### 4. Catálogo de veinte herramientas

El servidor nuevo `sucursal-agente` (`mcp_servidor/agente.py`) declara exactamente veinte herramientas, cada una con modelos Pydantic `<Nombre>Entrada` y `<Nombre>Salida` (`extra="forbid"`, docstring en español y anotaciones). Reutiliza la lógica existente; no reimplementa cálculos.

| # | Herramienta | Dueña | Reutiliza |
|---|---|---|---|
| 1 | `consultar_tasa` | Nayla | `tablero/tasas.py` y la herramienta MCP actual |
| 2 | `simular_cuota` | Nayla | `diagnostico/calculo.py` |
| 3 | `verificar_usura` | Nayla | `tablero/tasas.py` y `config/tasas.toml` |
| 4 | `diagnosticar_capacidad` | Nayla | `diagnostico/motor.py` |
| 5 | `comparar_escenario` | Nayla | `diagnostico/escenarios.py` |
| 6 | `convocar_comite` | Nayla | `diagnostico/comite.py` |
| 7 | `calcular_prestamo_gota` | Nayla | `escena/gota.py` |
| 8 | `comparar_gota_banco` | Nayla | `escena/comparacion.py` |
| 9 | `negociar_opcion` | Nayla | `escena/negociacion.py` |
| 10 | `generar_ficha_opcion` | Nayla | motor + `pana/` |
| 11 | `responder_sobre_proyecto` | Nayla | `escena/proyecto.py` (BM25, sin Ollama) |
| 12 | `registrar_consentimiento` | Darley | `canal/consentimiento.py` |
| 13 | `olvidar_mis_datos` | Darley | `canal/consentimiento.py` y `sucursal/perfil.py` |
| 14 | `solicitar_asesor` | Darley | `canal/hitl.py` y `canal/almacen.py` |
| 15 | `consultar_caso` | Darley | `canal/almacen.py` |
| 16 | `generar_tarjeta_pana` | Darley | `pana/` |
| 17 | `buscar_en_documentos` | Anny | `boveda/recuperador.py` (envuelve `buscar_en_boveda`) |
| 18 | `consultar_tarifas` | Anny | `tablero/construir.py` y `data/estructurados/tablero.csv` |
| 19 | `clasificar_pregunta` | Anny | `sucursal/digiturno.py` |
| 20 | `auditar_respuesta` | Anny | `diagnostico/comite.py::auditar_texto` |

Reglas del catálogo:

- Las herramientas de lectura (`1`–`11`, `15`, `17`–`20`) no escriben en Gold, Bóveda, Tablero ni bases.
- Las de estado (`12`, `13`, `14`, `16`) escriben solo en `data/asistente/` (canal y perfil) bajo el `usuario_id`; nunca en el corpus.
- `13` y `14` no se ejecutan sin confirmación explícita (ver decisión 8).
- `buscar_en_documentos` convive con `buscar_en_boveda`: la primera es el nombre que ve el agente y la segunda se conserva para no romper el servidor de solo lectura.
- Los errores devuelven un sobre común `{"ok": false, "codigo": "...", "mensaje": "..."}` sin trazas ni rutas absolutas.

### 5. Transporte MCP y red espejo de WSL

- El servidor stdio `boveda-occidente` **no se toca**: sigue siendo de solo lectura y con tres herramientas.
- `sucursal-agente` usa transporte **HTTP** y escucha solo en `127.0.0.1:8765`; el puerto y el host salen de `config/openclaw.toml` y una prueba fija que nunca se publica en `0.0.0.0`.
- OpenClaw corre dentro de WSL. La conexión al host se resuelve con `networkingMode=mirrored` en `.wslconfig`; se verifica con una petición desde WSL a `http://127.0.0.1:8765` y con un turno real del agente.
- No se añade un token propio al MCP en esta versión: el control es el loopback y la lista `mcp tools`. Si el gateway deja de ser local, se abre una decisión aparte (pregunta abierta).

### 6. Permisos, sandbox y auditoría

`openclaw/openclaw.json` versionado, sin secretos y con la estructura validada contra la versión instalada:

```json
{
  "gateway": {"host": "127.0.0.1", "port": 18789},
  "agents": {"pana": {"workspace": "openclaw/workspace", "model": "<principal>", "fallbackModel": "<alternativo>"}},
  "mcp": {"servers": {"sucursal": {"transport": "http", "url": "http://127.0.0.1:8765/mcp"}}},
  "permissions": {
    "mcp": {"tools": ["<las 20>"]},
    "tools": {"deny": ["exec", "shell", "browser"]},
    "fs": {"workspaceOnly": true}
  },
  "sandbox": {"enabled": true}
}
```

- El token **no** vive en el JSON: se referencia desde el entorno como `${OPENCLAW_GATEWAY_TOKEN}` y se documenta que el archivo no se edita para pegar secretos.
- Modelo principal y alternativo: el principal es el mismo proveedor del asistente y el alternativo un segundo modelo configurado del mismo proveedor o local; la elección exacta se fija el lunes y se documenta en `docs/AGENTE_OPENCLAW.md`.
- `mcp tools` enumera las veinte y ninguna más; `tools.deny` corta shell, ejecución y navegador; `fs.workspaceOnly` impide leer o escribir fuera del workspace.
- `openclaw security audit` corre el lunes, el miércoles antes de la integración y el jueves antes de la etiqueta; un hallazgo alto bloquea la entrega.

### 7. Workspace y memoria

```text
openclaw/workspace/
├── SOUL.md            # versionado: identidad y tono de pana
├── AGENTS.md          # versionado: reglas de operación y de datos
├── USER.md            # versionado: público genérico de la demo
├── MEMORY.md          # local, .gitignore, desde MEMORY.md.example
└── bitacora/          # local, .gitignore, JSONL por turno
```

- `SOUL.md`, `AGENTS.md` y `USER.md` se versionan sin secretos y sin datos reales; `USER.md` describe al invitado genérico de la sustentación, no a una persona.
- `MEMORY.md` y la bitácora quedan en `.gitignore` con plantillas `.example`; se crean al arrancar y se borran al terminar el evento.
- `AGENTS.md` incluye la regla dura: **nunca** escribir en `MEMORY.md` ni en la bitácora números, nombres ni datos financieros de los invitados; si el invitado los comparte, se usan en el turno y se descartan.
- El hilo sobrevive al reinicio porque el gateway persiste la sesión por `user` fuera del workspace versionado (`openclaw/state/`, ignorado); `MEMORY.md` conserva lo que el agente decidió recordar sin PII.

### 8. Confirmación de acciones destructivas

`olvidar_mis_datos` y `solicitar_asesor` son las dos únicas acciones con efecto irreversible o con apertura de caso. Ambas usan el patrón de dos pasos:

1. La herramienta devuelve `{"ok": true, "requiere_confirmacion": true, "token": "<id>"}` y el agente pregunta.
2. Solo con una confirmación explícita del invitado se ejecuta el borrado o se abre el caso.

Sin confirmación no se borra nada ni se crea un caso. Un «no» o un silencio cierran la intención sin efectos.

### 9. Modo evento para invitados

`config/whatsapp.toml [evento]` fija `activo`, `desde`, `hasta`, `maximo_invitados`, `maximo_turnos_por_invitado` y `ttl_minutos`.

- Fuera de la ventana, un número no autorizado sigue recibiendo el rechazo actual.
- Dentro de la ventana, el invitado pasa por el consentimiento de la Ley 1581 antes del primer turno funcional.
- El tope se cuenta por huella y por ventana; al agotarse, el canal responde con la frase fija y sugiere un asesor.
- Al cerrar el evento se borran perfiles, memorias y bitácoras; solo quedan métricas agregadas sin huellas.

### 10. Seguridad, datos personales y excepción de red

- El gateway y el MCP viven en loopback; el único servicio expuesto es el webhook a través del túnel de `cloudflared`.
- Las llamadas del despachador al gateway usan `httpx` con `timeout`, User-Agent del proyecto y header `From`, sin `verify=False`. No aplican `robots.txt` ni la pausa de 1,5 s porque el destino es local y no es scraping; la excepción se documenta en `docs/SEGURIDAD.md` y en `CONSTITUTION.md` en el mismo commit, igual que las excepciones de Ollama y Meta.
- La respuesta del gateway no se cachea en `data/asistente/cache.sqlite` si contiene datos personales o si el turno es de rechazo.
- El texto del invitado es dato, no instrucción: las herramientas validan argumentos con Pydantic, no ejecutan comandos y los fragmentos de la Bóveda siguen neutralizados antes de entrar al prompt.
- Los registros usan la huella, nunca el número; la bitácora guarda nombre de herramienta, argumentos no sensibles, latencia y resultado agregado.

### 11. Trazabilidad y medición

- Cada turno registra `motor` (`openclaw` o `grafo`), herramientas invocadas, latencia y si hubo respaldo. Esa traza alimenta la pantalla en vivo de Yoldy y el panel de operación.
- `recall@10` y `nDCG@10` se miden con `arqueo/metricas.py` sobre las preguntas con fuente esperada; el resultado se anota en `docs/AGENTE_OPENCLAW.md`.
- La proyección t-SNE usa `scikit-learn` con semilla fija sobre los embeddings de la Bóveda y se guarda como figura y como datos, sin red y sin volver a vectorizar.

### 12. Pruebas

- `test/test_canal_openclaw.py`: contrato con `httpx.MockTransport`, solo mensaje nuevo, `user` con huella, timeout, `5xx`, cuerpo vacío, token ausente y ausencia del número en la petición.
- `test/test_canal_modo_evento.py`: ventana, topes, consentimiento previo, borrado y rechazo fuera de ventana.
- `test/test_mcp_agente.py`: el catálogo acordado (veinte al cierre), esquemas Pydantic, `extra="forbid"`, sobre de error y ninguna escritura en el corpus.
- `test/test_agente_herramientas_*.py`: una prueba por herramienta con dobles, sin gateway y sin modelo.
- `make check` debe pasar con el gateway apagado, sin `DEEPSEEK_API_KEY` y con Ollama apagado; `test/conftest.py` sigue bloqueando conexiones fuera de loopback.

## Risks / Trade-offs

- **Claves de configuración de OpenClaw**: pueden cambiar entre versiones. Se validan el lunes contra la versión instalada y se congelan; el plan B es dejar el gateway en el host de Windows, también en loopback.
- **Red espejo de WSL**: requiere Windows 11 reciente y reiniciar WSL. Se prueba el martes; si falla, el gateway corre en Windows y el MCP sigue en `127.0.0.1`.
- **Latencia del gateway**: un turno con varias herramientas puede superar el `timeout`. Se fija un presupuesto por turno, se limita el número de herramientas por turno y el respaldo cubre el exceso.
- **Inyección de prompt desde WhatsApp**: el invitado controla el texto. Mitigación: sandbox, `tools.deny`, argumentos validados, fragmentos como datos y `auditar_respuesta`.
- **Datos personales en memoria**: `MEMORY.md` y la bitácora son locales y se borran; `AGENTS.md` prohíbe escribirlos. Riesgo residual: el invitado dicta un dato y el agente lo repite en el turno; no se persiste.
- **Dependencia fuera de `uv`**: OpenClaw no está en `uv.lock`. Se documenta la versión y el comando de instalación; `make check` no lo necesita.
- **Meta y el número real**: el token permanente y el número pueden fallar el día del evento. El modo evento tiene topes y los ensayos usan `EnviadorFalso`.

## Migration Plan

1. Lunes 23: contrato, `config/openclaw.toml`, `openclaw.json`, cliente `canal/openclaw.py` con pruebas; SIM y token de Meta; medición y t-SNE.
2. Martes 24: respaldo en el despachador, MCP con las primeras herramientas, red espejo, workspace, modo evento y primeras herramientas del catálogo. Punto de control a las 20:00 con cada pieza por separado.
3. Miércoles 25: herramientas restantes, permisos, sandbox, auditoría de seguridad, memoria tras reinicio, pantalla y pitch. **A las 18:00, integración completa y seguridad en verde.**
4. Jueves 26: solo correcciones, documentación y un ensayo previo; **etiqueta `entrega-final` a las 18:00**.
5. Viernes 27: dos ensayos completos, incluido el respaldo.
6. Sábado 28: sustentación.

**Rollback**: `OPENCLAW_ACTIVO=0` (o `fallback_forzado = true` en `config/openclaw.toml`) devuelve el canal al grafo sin tocar el webhook, la firma ni el consentimiento. El MCP y el gateway pueden apagarse sin afectar la Ventanilla ni la app.

## Open Questions

- Nombres exactos de las claves de `openclaw.json` para permisos y sandbox en la versión instalada; se resuelven el lunes y se reflejan en `docs/AGENTE_OPENCLAW.md`.
- Modelo alternativo definitivo (segundo modelo del proveedor o uno local) y presupuesto de tokens por turno.
- Si el MCP necesita un token propio cuando el gateway deje de correr en loopback; fuera de este cambio.
- Política de retención después del evento: se propone borrar todo y conservar solo métricas agregadas; se confirma el jueves.
