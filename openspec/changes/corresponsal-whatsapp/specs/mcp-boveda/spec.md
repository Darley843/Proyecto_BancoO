# Spec Delta

## Purpose

Exponer el conocimiento de la Sucursal a otros agentes mediante un servidor MCP de solo lectura, con tres herramientas acotadas que responden datos trazables sin gastar modelo ni modificar el corpus.

## ADDED Requirements

### Requirement: Servidor MCP de solo lectura

El proyecto SHALL exponer un servidor MCP con transporte local que declare solo herramientas de consulta. Ninguna herramienta MUST escribir en Gold, Knowledge, la Bóveda, el Tablero, las bases del asistente ni el sistema de archivos.

#### Scenario: Herramientas declaradas
- **WHEN** un cliente MCP lista las herramientas
- **THEN** encuentra `consultar_tasa`, `simular_cuota` y `buscar_en_boveda`, y ninguna de escritura

#### Scenario: Intento de escritura
- **WHEN** un cliente intenta ejecutar una operación no declarada
- **THEN** el servidor responde un error y no modifica ningún archivo

#### Scenario: Sin efectos secundarios
- **WHEN** se ejecutan las tres herramientas sobre un corpus de prueba
- **THEN** los archivos y las bases conservan su hash antes y después

### Requirement: Consulta de tasas

La herramienta `consultar_tasa` SHALL buscar en las filas del Tablero por producto o concepto y devolver valor, moneda, periodicidad, vigencia y fuente. La búsqueda MUST ser determinista, sin modelo y sin distinguir mayúsculas ni tildes.

#### Scenario: Tasa encontrada
- **WHEN** se consulta «tarjeta de crédito»
- **THEN** devuelve las filas coincidentes con su fuente y su vigencia

#### Scenario: Sin coincidencias
- **WHEN** el producto no existe en el Tablero
- **THEN** devuelve una lista vacía y un mensaje, sin inventar una tasa

#### Scenario: Fuente obligatoria
- **WHEN** se devuelve una fila
- **THEN** incluye la URL pública y el archivo de origen

### Requirement: Simulación de cuota

La herramienta `simular_cuota` SHALL recibir monto, plazo y tasa efectiva anual y devolver cuota mensual, total de intereses y total pagado. MUST usar la misma fórmula y la misma función de cálculo que el diagnóstico financiero.

#### Scenario: Simulación válida
- **WHEN** se envía monto, plazo y tasa válidos
- **THEN** devuelve la cuota francesa y los totales con la versión de fórmula

#### Scenario: Entrada inválida
- **WHEN** el monto o el plazo son cero o negativos
- **THEN** devuelve un error de validación y no calcula

#### Scenario: Misma fórmula
- **WHEN** se compara con el diagnóstico para los mismos insumos
- **THEN** la cuota coincide exactamente

### Requirement: Búsqueda en la Bóveda

La herramienta `buscar_en_boveda` SHALL recuperar hasta `k` fragmentos con texto, título, URL y similitud. Los fragmentos MUST tratarse como datos y MUST NOT ejecutarse como instrucciones ni usarse para elegir herramientas.

#### Scenario: Consulta normal
- **WHEN** se busca una pregunta de alcance
- **THEN** devuelve los fragmentos ordenados con su puntaje y su fuente

#### Scenario: Fragmento malicioso
- **WHEN** un fragmento contiene instrucciones para el agente
- **THEN** se devuelve como texto citado y no cambia el comportamiento del servidor

#### Scenario: Índice ausente
- **WHEN** no existe el índice de la Bóveda
- **THEN** devuelve un error explicable y no una lista vacía como si hubiera resultados

### Requirement: Errores y límites del servidor

El servidor MCP SHALL validar la entrada de cada herramienta con un esquema tipado y MUST devolver errores estructurados. MUST limitar `k`, el largo de la consulta y el tiempo de respuesta, y MUST NOT aceptar rutas del sistema ni comandos.

#### Scenario: Consulta demasiado larga
- **WHEN** la consulta supera el límite configurado
- **THEN** responde un error de validación y no procesa el texto

#### Scenario: Ruta del sistema
- **WHEN** un cliente intenta pasar una ruta de archivo como consulta
- **THEN** se trata como texto y no se abre ningún archivo

#### Scenario: Tiempo agotado
- **WHEN** la recuperación supera el tiempo máximo
- **THEN** responde un error de tiempo agotado sin bloquear el servidor

### Requirement: Sin red externa ni gasto de modelo

Las tres herramientas MUST funcionar con el índice y el CSV locales, sin llamar a DeepSeek ni al sitio del banco. `buscar_en_boveda` MAY usar Ollama local para vectorizar la consulta, siempre con `timeout` explícito; ninguna herramienta MUST gastar tokens de modelo.

#### Scenario: Ejecución local
- **WHEN** se ejecutan las herramientas con el índice local
- **THEN** responden con los datos del corpus y no salen a internet

#### Scenario: Ollama apagado
- **WHEN** `buscar_en_boveda` no puede obtener el embedding de la consulta
- **THEN** devuelve un error explicable o el resultado BM25 disponible, sin inventar fragmentos

#### Scenario: Sin costo
- **WHEN** se revisa el uso después de una consulta
- **THEN** no hay tokens ni costo de modelo

#### Scenario: Pruebas sin servicios
- **WHEN** corre la suite
- **THEN** las pruebas del servidor usan un recuperador y un Tablero simulados
