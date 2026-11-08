# sucursal-agente Specification

## Purpose

Decidir la ruta de cada pregunta, responder con recuperación o con datos estructurados, mantener memoria por conversación y controlar el gasto, detrás de una API JSON local que consume la app web.

## Requirements

### Requirement: Digiturno por reglas

El digiturno SHALL asignar primero por reglas deterministas: datos personales y preguntas fuera de alcance van a `X` sin llamar al modelo; la historia, identidad y gobierno del banco van a `B` sin llamar al modelo; las palabras de tarifas y coberturas proponen `T`; las dudas van a DeepSeek a temperatura 0 con salida JSON; el resto va a `B`. La letra `T` es provisional y se confirma solo si el Tablero puede responder con plantilla (1–3 filas o más del mismo concepto, hasta 10). Cada turno MUST registrar letra, número, ruta, motivo y si usó el modelo.

#### Scenario: Dato personal

- **WHEN** la pregunta incluye una cédula, un teléfono personal o una tarjeta
- **THEN** el turno es `X` con motivo de privacidad y no se llama al modelo

#### Scenario: Consulta de saldo

- **WHEN** la pregunta pide el saldo de una cuenta
- **THEN** el turno es `X` porque requiere datos del cliente

#### Scenario: Apertura de cuenta

- **WHEN** la pregunta es «¿cómo abro mi cuenta de nómina?»
- **THEN** el turno no es `X` y sigue la ruta `B`, porque «mi cuenta» no es un patrón de rechazo

#### Scenario: Historia e identidad del banco

- **WHEN** la pregunta es «¿Cuándo y dónde se fundó el banco?» o «¿Quién es el presidente?»
- **THEN** el turno es `B` antes de llamar al modelo; la historia y la identidad están dentro del alcance

#### Scenario: Tema de tarifas

- **WHEN** la pregunta menciona cuota de manejo, tarifa o cobertura
- **THEN** el turno propone `T` sin consultar al modelo y el Tablero decide si se confirma

#### Scenario: Tarifas demasiado amplias

- **WHEN** una pregunta de tarifas devuelve más de tres filas de varios conceptos o más de diez del mismo
- **THEN** el turno final es `B` y responde la Bóveda, no una plantilla de tabla

#### Scenario: Caso dudoso

- **WHEN** las reglas no deciden y hay modelo disponible
- **THEN** se llama a DeepSeek a temperatura 0 pidiendo una salida JSON válida

#### Scenario: Ruta por defecto

- **WHEN** ninguna regla ni la duda resuelta cambian la ruta
- **THEN** el turno es `B`

### Requirement: Grafo con memoria por conversación

El grafo SHALL ejecutar los pasos reformular, digiturno, recuperar de Bóveda o Tablero o rechazar, y redactar. MUST persistir la memoria con `SqliteSaver` en `data/asistente/memoria.sqlite`, aislar cada conversación por `thread_id` y recortar el historial con `trim_messages` y `count_tokens_approximately`.

#### Scenario: Aislamiento por sesión

- **WHEN** dos `thread_id` distintos conversan a la vez
- **THEN** ninguna respuesta usa el historial de la otra sesión

#### Scenario: Historial largo

- **WHEN** una conversación supera el presupuesto de tokens configurado
- **THEN** el historial se recorta antes de llamar al modelo y la respuesta sigue citando fuentes

#### Scenario: Memoria local fuera de Git

- **WHEN** se revisa Git después de conversar
- **THEN** `data/asistente/` no aparece versionado

### Requirement: Reformulación solo cuando hace falta

El sistema SHALL reformular la pregunta únicamente cuando existe historial en el hilo y la pregunta es de seguimiento. En el primer turno o en una pregunta autónoma MUST usar la pregunta original.

#### Scenario: Primer turno

- **WHEN** el hilo no tiene historial
- **THEN** no se reformula y se responde la pregunta tal como llegó

#### Scenario: Seguimiento

- **WHEN** el hilo tiene historial y la pregunta empieza con «¿Y…?» o depende del turno anterior
- **THEN** se reformula antes de recuperar y la respuesta indica la pregunta reformulada

### Requirement: Tablero responde con plantilla sin modelo

Cuando la ruta es `T` y hay de una a tres filas, el sistema SHALL responder con una plantilla determinista, sin llamar al modelo. Si hay más de tres filas, la plantilla MUST usarse solo cuando todas comparten el mismo concepto base (por ejemplo, los topes de la misma asistencia para Visa y Mastercard) y no superan diez filas. Con cero filas la consulta no se responde con una tabla: la ruta MUST pasar a `B` y responder con la Bóveda. Con más de diez filas o con varios conceptos distintos la consulta es demasiado amplia para el Tablero: la ruta MUST pasar a `B`. Una cuota genérica de «las tarjetas de crédito», sin un producto concreto, también MUST pasar a `B`.

#### Scenario: Una a tres filas

- **WHEN** la consulta al Tablero devuelve dos filas
- **THEN** la respuesta se arma con plantilla, cita la fuente y no consume tokens de DeepSeek

#### Scenario: Varias filas del mismo concepto

- **WHEN** la consulta devuelve nueve topes de la misma asistencia para Visa y Mastercard
- **THEN** la respuesta lista las nueve filas con plantilla, sin llamar al modelo

#### Scenario: Sin filas

- **WHEN** la consulta al Tablero no devuelve filas
- **THEN** el turno final es `B` y la respuesta sale de los fragmentos de la Bóveda

#### Scenario: Muchas filas

- **WHEN** la consulta devuelve once o más filas, o filas de varios productos
- **THEN** el turno final es `B` y la respuesta sale de los fragmentos de la Bóveda

#### Scenario: Cuota genérica

- **WHEN** se pregunta por la cuota de manejo de «las tarjetas de crédito» sin nombrar una
- **THEN** el turno final es `B` para que la Bóveda pregunte por la tarjeta concreta

### Requirement: Tope diario de gasto

El sistema SHALL leer el tope diario de `config/sucursal.toml`, permitir que `SUCURSAL_TOPE_USD` lo sobrescriba para una sesión y acumular el gasto en `data/asistente/gasto.sqlite`. Al alcanzar el tope, las preguntas que requieren el modelo MUST responder 429 `tope_alcanzado` sin llamar a DeepSeek; las de ruta `X` y las del Tablero con plantilla MUST seguir en 200 sin gastar.

#### Scenario: Gasto por debajo del tope

- **WHEN** el gasto acumulado es menor que el tope
- **THEN** la pregunta puede usar el modelo y el gasto se actualiza

#### Scenario: Tope alcanzado

- **WHEN** el gasto acumulado iguala o supera el tope y la pregunta requiere el modelo
- **THEN** responde HTTP 429 con `{"error": {"codigo": "tope_alcanzado", "mensaje": ...}}` y no hay llamada a DeepSeek

#### Scenario: Rutas sin modelo con el tope agotado

- **WHEN** el gasto ya alcanzó el tope y la pregunta es de ruta `X` o el Tablero la responde con plantilla
- **THEN** responde HTTP 200 sin llamar al modelo y sin sumar gasto

#### Scenario: Tope sobrescrito por entorno

- **WHEN** `SUCURSAL_TOPE_USD` define un valor para la sesión
- **THEN** el tope efectivo es ese valor y no el de `config/sucursal.toml`

### Requirement: Tarifas en un solo lugar

Las tarifas de DeepSeek SHALL vivir en `arqueo/metricas.py` (`TARIFAS_DEEPSEEK_FLASH` y `TARIFAS_DEEPSEEK_FLASH_PICO`). `sucursal/costo.py` MUST importarlas y elegir valle o pico según la hora UTC. `config/sucursal.toml` MUST NOT repetir precios.

#### Scenario: Hora valle

- **WHEN** la llamada ocurre fuera de la franja de pico
- **THEN** el costo se calcula con la tarifa valle

#### Scenario: Hora pico

- **WHEN** la llamada ocurre en la franja de pico definida
- **THEN** el costo se calcula con la tarifa pico

#### Scenario: Sin precios duplicados

- **WHEN** se revisa `config/sucursal.toml`
- **THEN** no contiene valores de tarifas de DeepSeek

### Requirement: Caché de respuestas

El sistema SHALL cachear en `data/asistente/cache.sqlite` las respuestas que usaron el modelo, con clave por pregunta reformulada normalizada (la que se envía a recuperar), ruta y versión del prompt. Un acierto MUST devolver la respuesta con `cache: true` y costo cero; los turnos `X` y los que no usaron modelo MUST NOT entrar en la caché.

#### Scenario: Pregunta repetida

- **WHEN** se repite una pregunta ya respondida y vigente en caché
- **THEN** se devuelve la respuesta guardada, `cache` es `true` y `costo_usd` es 0

#### Scenario: Seguimiento de otra conversación

- **WHEN** dos conversaciones distintas llegan a la misma pregunta reformulada
- **THEN** comparten la entrada de caché; si la reformulación difiere, no la comparten

#### Scenario: Turno rechazado

- **WHEN** la pregunta se rechaza por privacidad
- **THEN** no se escribe nada en la caché

### Requirement: Modo demo sin gasto

Con `SUCURSAL_DEMO=1` el sistema SHALL responder sin llamar a DeepSeek, con `modo_demo: true` y costo cero. MUST funcionar sin `DEEPSEEK_API_KEY` y MUST NOT escribir gasto real.

#### Scenario: Demo sin clave

- **WHEN** se arranca con `SUCURSAL_DEMO=1` y sin clave de API
- **THEN** `/api/estado` responde y las preguntas devuelven respuestas de demostración

#### Scenario: Gasto intacto

- **WHEN** se conversa en modo demo
- **THEN** `data/asistente/gasto.sqlite` no suma gasto

### Requirement: Endpoints de estado y pregunta

La API SHALL exponer `GET /api/estado` con `modo_demo`, `gasto_hoy_usd`, `tope_usd`, `indice_listo`, `fragmentos_indexados` y `modelo_embeddings`, y `POST /api/preguntar` con `{pregunta, thread_id}`. La respuesta MUST incluir turno, ruta, motivo, reformulada, respuesta, fuentes, tokens, costo, tiempo y `cache`.

#### Scenario: Estado de la sucursal

- **WHEN** se consulta `/api/estado`
- **THEN** devuelve los seis campos con el gasto del día y el estado del índice

#### Scenario: Pregunta completa

- **WHEN** se envía una pregunta con su `thread_id`
- **THEN** la respuesta trae todos los campos del contrato y las fuentes numeradas

#### Scenario: Índice ausente

- **WHEN** `data/boveda/` no existe y se pregunta por la ruta `B`
- **THEN** la API responde un error JSON explicable y no inventa una respuesta

### Requirement: Endpoints de datos y trazabilidad

La API SHALL exponer `GET /api/tablero?q=`, `GET /api/boveda/mapa?pregunta=`, `GET /api/pipeline`, `GET /api/arqueo` y `GET /api/vestibulo` con las formas JSON acordadas: filas del Tablero, puntos y top de la Bóveda, resumen del pipeline con la etapa de indexación, contenido de `arqueo.json` e hitos del vestíbulo.

#### Scenario: Tablero consultable

- **WHEN** se pide `/api/tablero?q=cuota`
- **THEN** devuelve las filas que coinciden con el filtro

#### Scenario: Mapa de la Bóveda

- **WHEN** se pide `/api/boveda/mapa?pregunta=...`
- **THEN** devuelve puntos con coordenadas, la pregunta proyectada y el top de fragmentos

#### Scenario: Pipeline con indexación

- **WHEN** se pide `/api/pipeline`
- **THEN** incluye las etapas de `panel.pipeline_summary` y el estado de indexación

#### Scenario: Arqueo y vestíbulo

- **WHEN** se piden `/api/arqueo` y `/api/vestibulo`
- **THEN** devuelven el contenido de `data/evaluacion/arqueo.json` y los hitos de `config/vestibulo.toml`

### Requirement: Servidor solo local

El servidor SHALL escuchar únicamente en `127.0.0.1:8000`. MUST NOT abrir la interfaz en `0.0.0.0` ni aceptar conexiones externas por configuración por defecto.

#### Scenario: Dirección de escucha

- **WHEN** se arranca `make app`
- **THEN** uvicorn queda escuchando en `127.0.0.1:8000`

#### Scenario: Sin exposición externa

- **WHEN** se revisa la configuración del servidor
- **THEN** no hay un host público ni un flag para abrirlo
