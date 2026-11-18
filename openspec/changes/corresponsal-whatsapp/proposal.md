# Proposal

## Why

La Sucursal 1965 ya responde por la Ventanilla web, pero la entrega final del taller pide demostrar el mismo asistente en el canal donde el cliente realmente conversa: WhatsApp. Hoy no existe webhook, identificación por número, consentimiento, diagnóstico financiero guiado, escalamiento a un asesor ni una medición del filtro de dominio y de la latencia del canal. Sin esas piezas el proyecto no puede probar que el grafo, la Bóveda y el Tablero funcionan fuera de la maqueta local.

El plazo es corto: del 16 al 23 de noviembre de 2026, con congelamiento el sábado 21. Por eso el cambio se limita a la Vía 2 (webhook propio en FastAPI, sin N8N), reutiliza el grafo y los datos ya construidos, y deja la llamada por WhatsApp como un experimento con decisión temprana el martes 17: si no es viable con el número de prueba, se documenta y se descarta sin bloquear el resto.

## What Changes

- Añadir la capa **Canal WhatsApp** sobre Meta Cloud API con número de prueba y cinco números autorizados: verificación `GET`, firma `X-Hub-Signature-256`, deduplicación por id de mensaje, respuesta 200 inmediata con procesamiento en segundo plano, y envío real o falso según configuración.
- Identificar al usuario por su número con `usuario_id = HMAC(número, ID_SALT)`. Guardar fuera del repositorio el perfil mínimo (nombre y rol cliente/asesor), aislar `thread_id` y namespace del Store por usuario, y exigir consentimiento de la Ley 1581 de 2012 con un botón «Acepto» antes de la primera respuesta funcional.
- Añadir el **Diagnóstico financiero guiado**: entrevista por rangos, cálculo determinístico en Python con tasas del Tablero (tasa E.A. a mensual, cuota francesa, razón de endeudamiento y capacidad de pago), semáforo, recomendaciones y aviso de que el resultado es orientativo.
- Añadir **HITL con el asesor**: `interrupt()` en casos rojos o cuando el usuario pide asesoría, botones Contactar/Descartar y reanudación con `Command(resume=...)` sobre el mismo checkpoint.
- Añadir **«¿Y si…?»**: bifurcación del checkpoint del diagnóstico para comparar escenarios sin alterar la conversación original.
- Añadir el **Comité de crédito** con tres roles (riesgo, comercial y auditor), una sola ronda y solo para casos rojos o amarillos, con salida estructurada y trazable.
- Añadir **Roba la Bóveda**: terminal web de ataque con intentos, clasificación y marcador.
- Añadir un **servidor MCP de solo lectura** con `consultar_tasa`, `simular_cuota` y `buscar_en_boveda`.
- Extender el **Arqueo** con el filtro de dominio (casos fuera de tema, tasa de fuga y de rechazo indebido con intervalo de Wilson) y con latencia p50/p95 por flujo, mínimo 30 corridas y separación de caché.
- Añadir el **tablero de operación** para ver estado del canal, cola, casos HITL, latencias y marcador de Roba la Bóveda.
- Documentar el **experimento de llamada por WhatsApp**, con decisión el martes 17 y resultado explícito (adoptado o descartado).
- Fijar en Pydantic los contratos compartidos `MensajeEntrante`, `RespuestaCanal`, `PerfilUsuario`, `EntradaDiagnostico`, `ResultadoDiagnostico` y `CasoAsesor`.

## Capabilities

### New Capabilities

- `canal-whatsapp`: webhook de Meta Cloud API, firma, deduplicación, respuesta inmediata y procesamiento en segundo plano, envío real/falso, identificación por número, perfiles aislados, consentimiento y números autorizados.
- `diagnostico-financiero`: entrevista guiada, cálculo determinístico de tasa mensual, cuota francesa, endeudamiento y capacidad de pago, semáforo, recomendaciones, HITL y escenarios «¿Y si…?».
- `comite-credito`: comité de tres roles con una ronda, casos rojos o amarillos, salida estructurada y auditoría de la decisión.
- `mcp-boveda`: servidor MCP de solo lectura con consulta de tasas, simulación de cuota y búsqueda en la Bóveda.
- `roba-boveda`: terminal web de ataque, clasificación de intentos y marcador.

### Modified Capabilities

- `arqueo-evaluacion`: se añaden el filtro de dominio con tasa de fuga y de rechazo indebido (IC de Wilson) y la latencia p50/p95 por flujo con separación de caché.
- `sucursal-agente`: el grafo debe admitir interrupciones HITL, reanudación y bifurcación de checkpoints, además de hilos y namespaces por usuario.
- `tablero-tarifas`: se añade una consulta determinista de la tasa de interés vigente que alimenta el diagnóstico y la simulación.
- `sucursal-frontend`: se añaden la vista de operación del canal y la terminal de Roba la Bóveda.

## Impact

- Código nuevo: `src/banco_occidente_corpus/canal/` (webhook, firma, deduplicación, cliente Meta, identidad, consentimiento y contratos Pydantic), `diagnostico/` (entrevista, cálculo, semáforo, HITL y escenarios), `comite/` (roles y esquema), `mcp_servidor/` (servidor de solo lectura) y `roba/` (clasificación y marcador).
- Código tocado: `sucursal/grafo.py` (interrupt, resume y fork), `sucursal/preguntar.py` (hilo y perfil por usuario), `sucursal/api.py` y `app.py` (rutas del webhook y de operación), `app/web/` (tablero de operación y Roba la Bóveda), `arqueo/` (métricas de dominio y latencia) y `tablero/` (tasa para simulación).
- Configuración nueva: `config/whatsapp.toml`, `config/diagnostico.toml` y prompts del comité. Las credenciales (`WHATSAPP_VERIFY_TOKEN`, `WHATSAPP_APP_SECRET`, `WHATSAPP_ACCESS_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID`, `WHATSAPP_ID_SALT`) viven solo en el entorno; nunca en el repositorio ni en un `.env` leído por el código.
- Dependencia nueva: SDK `mcp` para el servidor de solo lectura. WhatsApp usa `httpx` con `timeout` explícito; no se añade N8N ni un framework de mensajería.
- Datos nuevos no versionados: `data/asistente/whatsapp.sqlite` (deduplicación, consentimiento y cola de salida) y los checkpoints de diagnóstico. `data/asistente/` sigue fuera de Git.
- Pruebas nuevas sin red: payloads simulados al webhook, cinco números autorizados ficticios, envío falso, `FakeListChatModel`, `DeterministicFakeEmbedding` y recuperador simulado. Ninguna prueba llama a Meta, a DeepSeek ni a Ollama.
- Riesgos controlados: el webhook sigue escuchando en `127.0.0.1` y el túnel es externo al proceso; los fragmentos y mensajes de WhatsApp se tratan como datos, nunca como instrucciones; el consentimiento y los perfiles viven fuera del repositorio; el envío real solo se habilita con las cinco números autorizados y el número de prueba.
