# Spec Delta

## Purpose

Fijar el contrato del agente `pana` de OpenClaw como motor del canal de WhatsApp de la Sucursal 1965, con su catálogo de veinte herramientas, su respaldo y su operación segura. No repite requisitos de `canal-whatsapp`, `mcp-boveda`, `diagnostico-financiero`, `comite-credito` ni `tablero-tarifas`: solo cubre lo que el gateway añade.

## ADDED Requirements

### Requirement: Contrato del gateway

El despachador SHALL enviar cada mensaje nuevo al gateway con `POST /v1/chat/completions`, `model` `openclaw:pana`, `user` `wa:<huella>` y el token de `OPENCLAW_GATEWAY_TOKEN`. MUST NOT enviar el número en claro ni el historial de la conversación.

#### Scenario: Mensaje nuevo
- **WHEN** el invitado envía un texto después del consentimiento
- **THEN** el despachador envía solo ese texto, con `user` `wa:<huella>` y el token del entorno

#### Scenario: Número fuera de la petición
- **WHEN** el despachador construye el cuerpo y las cabeceras
- **THEN** el número en claro no aparece en ninguno de los dos

#### Scenario: Token ausente
- **WHEN** el proceso arranca sin `OPENCLAW_GATEWAY_TOKEN`
- **THEN** el motor OpenClaw queda deshabilitado y el canal responde con el grafo, sin valor por defecto

### Requirement: Catálogo de veinte herramientas

El servidor MCP del agente SHALL declarar exactamente veinte herramientas con esquema Pydantic de entrada y salida, y OpenClaw MUST habilitarlas con `mcp tools`. Cualquier herramienta fuera del catálogo MUST rechazarse sin ejecutarse.

#### Scenario: Catálogo completo
- **WHEN** un cliente MCP lista las herramientas del servidor del agente
- **THEN** encuentra las veinte acordadas, cada una con su esquema y su dueña

#### Scenario: Herramienta fuera del catálogo
- **WHEN** el agente intenta invocar una herramienta no declarada
- **THEN** el servidor responde `ok: false` y no ejecuta nada

### Requirement: Respaldo al grafo

Si el gateway falla, excede el `timeout` o devuelve un error, el despachador SHALL responder con el grafo actual y MUST NOT dejar el mensaje sin respuesta. La trazabilidad MUST declarar el motor que respondió.

#### Scenario: Timeout del gateway
- **WHEN** el gateway no responde dentro del `timeout` configurado
- **THEN** el despachador responde con el grafo y registra `motor="grafo"`

#### Scenario: Error del gateway
- **WHEN** el gateway responde un `5xx` o un cuerpo inválido
- **THEN** el invitado recibe la respuesta del grafo en menos de dos segundos

#### Scenario: Respuesta válida
- **WHEN** el gateway responde con contenido válido
- **THEN** el despachador envía ese texto y registra `motor="openclaw"`

### Requirement: Confirmación antes de acciones destructivas

`olvidar_mis_datos` y `solicitar_asesor` SHALL exigir confirmación explícita del invitado antes de ejecutarse. Sin confirmación MUST NOT borrar datos ni abrir un caso de asesor.

#### Scenario: Sin confirmación
- **WHEN** el invitado pide borrar sus datos o un asesor y no confirma
- **THEN** no se borra nada ni se crea un caso

#### Scenario: Con confirmación
- **WHEN** el invitado confirma la acción pedida
- **THEN** el borrado o el caso se ejecuta una sola vez y queda trazado por huella

#### Scenario: Cancelación
- **WHEN** el invitado responde «no» o no vuelve a escribir
- **THEN** la intención se cierra sin efectos y sin reintentos automáticos

### Requirement: Workspace sin secretos

El workspace SHALL versionar `SOUL.md`, `AGENTS.md` y `USER.md` sin secretos ni datos personales. `MEMORY.md` y la bitácora MUST quedar fuera de Git, con plantillas `.example`, y `AGENTS.md` MUST prohibir guardar números, nombres o datos financieros de invitados.

#### Scenario: Archivos versionados
- **WHEN** se revisa el repositorio
- **THEN** `SOUL.md`, `AGENTS.md` y `USER.md` están versionados y `USER.md` describe un público genérico

#### Scenario: Memoria local
- **WHEN** se ejecuta `git check-ignore` sobre `MEMORY.md` y la bitácora
- **THEN** ambas rutas quedan ignoradas y solo se versionan sus plantillas `.example`

#### Scenario: Intento de guardar datos
- **WHEN** el agente intenta escribir un número, un nombre o un dato financiero en `MEMORY.md`
- **THEN** la regla de `AGENTS.md` lo prohíbe y el dato no se persiste

### Requirement: Sandbox y auditoría de seguridad

OpenClaw SHALL ejecutarse en sandbox con `tools.deny` para shell y escritura fuera del workspace, `fs.workspaceOnly` activo y `mcp tools` acotado al catálogo. `openclaw security audit` MUST quedar sin hallazgos altos antes de la entrega.

#### Scenario: Auditoría en verde
- **WHEN** se ejecuta `openclaw security audit` antes de la etiqueta `entrega-final`
- **THEN** no hay hallazgos altos y el resultado queda en `docs/AGENTE_OPENCLAW.md`

#### Scenario: Herramienta denegada
- **WHEN** el agente intenta ejecutar shell o abrir un navegador
- **THEN** la herramienta está denegada y el turno continúa sin efectos en el host

#### Scenario: Escritura fuera del workspace
- **WHEN** el agente intenta leer o escribir fuera de `openclaw/workspace/`
- **THEN** `fs.workspaceOnly` lo impide y el intento queda en la bitácora sin PII

### Requirement: Hilo persistente

El hilo del invitado SHALL sobrevivir al reinicio del gateway y conservar el contexto del turno anterior. La memoria MUST guardarse en `MEMORY.md` local y MUST NOT contener datos personales ni financieros del invitado.

#### Scenario: Reinicio del gateway
- **WHEN** el gateway se reinicia y el invitado envía una pregunta de seguimiento
- **THEN** el agente conserva el contexto del turno anterior

#### Scenario: Continuidad sin PII
- **WHEN** se revisa la memoria después de varios turnos
- **THEN** no hay números, nombres ni datos financieros del invitado
