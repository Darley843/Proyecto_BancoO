# Proposal

## Why

La sustentación del Taller 3 es el **sábado 28 de noviembre de 2026** y se evalúa con los lineamientos del Módulo 3: agente con herramientas, memoria, sandbox, productización y despliegue avanzado. Hoy la Sucursal 1965 responde por la Ventanilla y por WhatsApp con el grafo propio, pero el invitado no puede usar el agente desde su propio teléfono y no existe un agente que razone con herramientas sobre tasas, diagnóstico, comité y Bóveda.

El canal de WhatsApp ya está construido y probado (webhook de Meta, firma `X-Hub-Signature-256`, consentimiento de la Ley 1581, huella HMAC y autorización de números), y el proyecto ya tiene las piezas de conocimiento: Tablero, motor del diagnóstico, comité con auditor, Bóveda y el servidor MCP de solo lectura con tres herramientas. Falta el agente que las use con un catálogo amplio y el modo evento que permita que invitados reales participen durante la demo sin comprometer datos personales.

OpenClaw entra como **gateway local del agente `pana`**: recibe el mensaje por su API compatible con OpenAI, llama a las herramientas por MCP y devuelve el texto. WhatsApp sigue siendo solo de Meta; OpenClaw no tiene ni tendrá canal de WhatsApp en este cambio. Si OpenClaw falla, el despachador responde con el grafo actual para no dejar al invitado sin contestación.

## What Changes

- Añadir el **gateway de OpenClaw** como motor del agente `pana`: `POST http://127.0.0.1:18789/v1/chat/completions`, `model` `openclaw:pana`, `user` `wa:<huella>`, token en `OPENCLAW_GATEWAY_TOKEN` y **solo el mensaje nuevo**; el hilo lo guarda el gateway.
- Añadir un **catálogo de veinte herramientas MCP** con esquemas Pydantic de entrada y salida, en un servidor HTTP de loopback aparte del servidor stdio de solo lectura: once de Nayla, cinco de Darley y cuatro de Anny.
- Añadir el **respaldo al grafo actual** cuando el gateway falla, se agota el `timeout` o devuelve un error, con la trazabilidad del motor usado en cada turno.
- Añadir el **modo evento** para invitados: número real registrado en Meta, token permanente, consentimiento previo, ventana de demo, tope de invitados y de turnos por huella, y borrado al terminar.
- Versionar el **workspace del agente** (`SOUL.md`, `AGENTS.md` y `USER.md`) sin secretos ni datos personales, con `MEMORY.md` y la bitácora **fuera de Git** y plantillas `.example`.
- Añadir **permisos y sandbox**: `mcp tools` acotado al catálogo, `tools.deny`, `fs.workspaceOnly` y `openclaw security audit` como compuerta de entrega.
- Habilitar la **red espejo de WSL** para que el gateway alcance el MCP en `127.0.0.1` del host, sin publicar nada en `0.0.0.0`.
- Medir lo que pide el Módulo 3: `recall@10` y `nDCG@10` de la Bóveda y una proyección **t-SNE** de los embeddings, con semilla fija y sin red.
- Cerrar la entrega con README, guía de despliegue, LICENSE MIT, diagramas, pantalla en vivo y pitch, y con la etiqueta `entrega-final` el jueves 26 a las 18:00.

## Capabilities

### New Capabilities

- `agente-openclaw`: el contrato del gateway, el catálogo de veinte herramientas, el respaldo al grafo, la confirmación de las acciones destructivas, el workspace sin secretos, el sandbox y la persistencia del hilo. El delta vive en `specs/agente-openclaw/spec.md` y no duplica requisitos de `canal-whatsapp`, `mcp-boveda`, `diagnostico-financiero`, `comite-credito`, `tablero-tarifas` ni `sucursal-agente`.

### Modified Capabilities

Ninguna. El canal, el MCP de solo lectura, el motor, el comité, el Tablero y la Sucursal conservan sus requisitos; este cambio los compone detrás de un agente y añade solo el contrato y la operación del gateway.

## Impact

- **Código nuevo**: `src/banco_occidente_corpus/canal/openclaw.py` (cliente del gateway), `src/banco_occidente_corpus/mcp_servidor/agente.py` (servidor HTTP de veinte herramientas, con su `main()`), `src/banco_occidente_corpus/canal/modo_evento.py` (ventana y límites de invitados).
- **Código tocado**: `canal/despachador.py` (OpenClaw primero y respaldo al grafo), `canal/consentimiento.py`, `makefile` (`agente-mcp`), `README.md`, `docs/OPERACION_WHATSAPP.md`, `docs/SEGURIDAD.md` y `CONSTITUTION.md` (excepción de red del cliente local).
- **Configuración nueva**: `config/openclaw.toml` (URL, modelo, `timeout`, respaldo) y `openclaw/openclaw.json` (agente, modelos principal y alternativo, MCP, permisos y sandbox), versionados y **sin secretos**; `config/whatsapp.toml [evento]` con la ventana y los topes.
- **Workspace**: `openclaw/workspace/SOUL.md`, `AGENTS.md` y `USER.md` versionados; `MEMORY.md`, `bitacora/` y el estado del gateway en `.gitignore`, con plantillas `.example`.
- **Dependencias**: ninguna nueva. Se reutilizan `httpx`, `pydantic`, `mcp` y `scikit-learn`, que ya están en `uv.lock`. OpenClaw se instala fuera del proyecto, como `scrapling`, y no entra en `uv.lock` ni en `make check`.
- **Pruebas**: `test/test_canal_openclaw.py`, `test/test_canal_modo_evento.py`, `test/test_mcp_agente.py` y pruebas por herramienta. Todas con dobles (`httpx.MockTransport`, `FakeOpenClaw`), sin red, sin gateway, sin `DEEPSEEK_API_KEY` y con Ollama apagado.
- **Riesgos controlados**: el gateway puede no arrancar o cambiar de claves de configuración (se valida el lunes y se congela; plan B: gateway en Windows); WSL puede no soportar red espejo (plan B: gateway en el host); el invitado puede escribir datos personales (regla en `AGENTS.md`, memoria local y borrado); Meta puede limitar el número (modo evento con tope y `EnviadorFalso` para ensayos).

## Out of Scope

- Un canal de WhatsApp dentro de OpenClaw: WhatsApp va **solo** por Meta.
- Un segundo proveedor de mensajería, llamadas, audio o video por WhatsApp.
- Migrar el hilo del gateway al grafo o al revés: cada motor conserva el suyo y la respuesta declara cuál respondió.
- Publicar el gateway, el MCP o la app fuera de `127.0.0.1`.
- Capturar o conservar números, nombres o datos financieros de invitados; nada de clientes reales.
- Cambiar la escena `demo-gota-a-gota` más allá de cerrar las tareas que el Módulo 3 descarta o reemplaza.

## Success Criteria

- El servidor MCP lista exactamente veinte herramientas con esquema JSON válido y ninguna fuera del catálogo.
- Un invitado real escribe por WhatsApp, recibe la respuesta del agente `pana` con al menos una herramienta invocada y el turno completo queda por debajo de 8 s p95.
- Con el gateway apagado o lento, el despachador responde con el grafo en menos de 2 s y el invitado nunca queda sin contestación.
- El hilo sobrevive al reinicio del gateway y una pregunta de seguimiento conserva el contexto del turno anterior.
- `openclaw security audit` queda sin hallazgos altos; `tools.deny` bloquea shell y escritura fuera del workspace.
- `git grep` no encuentra secretos y los registros y la base no contienen números en claro.
- `recall@10` y `nDCG@10` quedan medidos y documentados, y la proyección t-SNE es reproducible con semilla fija.
- `make check` queda en verde con el gateway apagado, sin `DEEPSEEK_API_KEY` y con Ollama apagado.
- La etiqueta `entrega-final` queda puesta el jueves 26 a las 18:00 y el viernes 27 se completan dos ensayos.
