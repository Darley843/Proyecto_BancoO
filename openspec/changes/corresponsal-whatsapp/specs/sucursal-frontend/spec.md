# Spec Delta

## ADDED Requirements

### Requirement: Vistas de operación y Roba la Bóveda

La app SHALL añadir dos vistas nuevas a `app/web/vistas/`: `operacion` y `roba`. Cada una MUST abrirse desde la navegación de la sucursal y MUST poder cargarse sin depender de otra vista. Los datos de ejemplo MUST incluir `operacion.json` y `roba.json` con la misma forma que sus respuestas de la API.

#### Scenario: Vista Operación
- **WHEN** se abre Operación desde la navegación
- **THEN** se carga `app/web/vistas/operacion.js` y muestra el estado del canal

#### Scenario: Vista Roba la Bóveda
- **WHEN** se abre Roba la Bóveda desde la navegación
- **THEN** se carga `app/web/vistas/roba.js` y muestra la terminal y el marcador

#### Scenario: Datos de ejemplo
- **WHEN** se revisan `operacion.json` y `roba.json`
- **THEN** sus campos y tipos coinciden con los modelos de la API

### Requirement: Tablero de operación

La vista Operación SHALL mostrar el estado del canal de WhatsApp, el modo de envío, la cola y la deduplicación, los casos HITL pendientes, la latencia p50/p95 por flujo y el resumen de Roba la Bóveda. La vista MUST ser de solo lectura y MUST NOT mostrar números de teléfono, nombres ni conversaciones.

#### Scenario: Estado del canal
- **WHEN** se abre Operación
- **THEN** muestra si el canal está configurado, deshabilitado, en envío real o falso

#### Scenario: Casos pendientes
- **WHEN** hay casos de asesor pendientes
- **THEN** la vista los lista con motivo, semáforo y fecha, sin datos personales

#### Scenario: Latencias
- **WHEN** el Arqueo tiene p50 y p95
- **THEN** la vista los muestra por flujo y separa la caché

#### Scenario: Sin datos
- **WHEN** el canal no está configurado o no hay casos
- **THEN** la vista lo explica y no muestra cifras inventadas

### Requirement: Vista Roba la Bóveda

La vista Roba la Bóveda SHALL ofrecer una terminal para enviar intentos, ver la respuesta, la categoría, el resultado y el marcador acumulado. La vista MUST usar solo el corpus sintético, MUST limitar los intentos por sesión y MUST permitir reiniciar y exportar el marcador.

#### Scenario: Intento y resultado
- **WHEN** el usuario envía un intento
- **THEN** ve la respuesta, la categoría y si la defensa resistió

#### Scenario: Marcador
- **WHEN** se acumulan intentos exitosos
- **THEN** el marcador muestra el total por categoría y el total general

#### Scenario: Reinicio y exportación
- **WHEN** el usuario reinicia o exporta
- **THEN** el marcador vuelve al inicio o descarga el resumen sin datos personales

#### Scenario: Sin daño real
- **WHEN** se usa la vista
- **THEN** no se envían mensajes por WhatsApp ni se modifica el corpus
