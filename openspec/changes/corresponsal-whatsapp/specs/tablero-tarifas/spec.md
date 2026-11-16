# Spec Delta

## ADDED Requirements

### Requirement: Captura del PDF vigente de tasas

El Tablero SHALL capturar en Bronze la página `/tarifas` y ejecutar `corpus docs discover` para inventariar el PDF vigente `https://www.bancodeoccidente.com.co/documents/d/guest/tasas-personas-bdo`. MUST NOT requerir `corpus docs extract` ni regenerar las páginas, los documentos o los índices existentes de Gold.

#### Scenario: /tarifas en Bronze
- **WHEN** se captura `/tarifas` y se ejecuta `corpus docs discover`
- **THEN** el inventario incluye el PDF `tasas-personas-bdo` con su URL y su prioridad

#### Scenario: Gold existente intacto
- **WHEN** termina la captura del PDF
- **THEN** las páginas, los documentos y los índices que ya estaban en Gold no se reescriben

### Requirement: Inventario acotado y descarga sin filtro por tipo

Tras el descubrimiento, SHALL respaldar el inventario completo en `data/raw/documents_urls.original.jsonl` y dejar en `data/raw/documents_urls.jsonl` solo las URLs `tasas-personas-bdo` y `tarifas-persona-bdo`. Después SHALL ejecutar `corpus docs fetch --priority-max 3 --max-mb 50 --delay 1.5`. MUST NOT usar filtro por tipo porque `tasas-personas-bdo` se clasifica como `otro`.

#### Scenario: Inventario acotado con respaldo
- **WHEN** se filtra el inventario a las dos URLs de tasas y tarifario
- **THEN** el respaldo conserva el inventario completo y solo esas dos URLs quedan en `documents_urls.jsonl`

#### Scenario: Clasificación «otro»
- **WHEN** el inventario clasifica `tasas-personas-bdo` como `otro`
- **THEN** no se usa `--tipo` y la descarga lo incluye por estar en el inventario acotado

### Requirement: Tabla Gold versionada de tasas

La extracción SHALL usar `pypdfium2` y escribir una tabla Gold versionada por vigencia con producto, segmento, plazo en días cuando el producto lo publica (CDT), tasa E.A. desde y hasta, tasa M.V. desde y hasta, vigencia desde y hasta, URL de la fuente, `sha256` del PDF y fecha de extracción. MUST conservar la vigencia publicada (1–30 de noviembre de 2026 en la versión inicial) y MUST NOT inventar filas ausentes.

#### Scenario: Tabla versionada en Gold
- **WHEN** el módulo extrae el PDF
- **THEN** escribe una tabla Gold identificada por la vigencia, con una fila por producto, segmento y plazo, y cada fila incluye los doce campos del contrato, la URL, el `sha256` y la fecha de extracción

#### Scenario: Rango de tasa
- **WHEN** el PDF publica una tasa E.A. desde 18,50 % hasta 24,90 % para un producto
- **THEN** la fila conserva ambos extremos y la M.V. correspondiente, sin reducirlos a un promedio

#### Scenario: M.V. coherente con la E.A.
- **WHEN** el PDF publica la M.V. junto a la E.A. de un producto
- **THEN** la M.V. cumple `(1 + E.A.) ** (1/12) - 1` con tolerancia de 0,01 puntos porcentuales y una fila incoherente no se publica

#### Scenario: CDT por plazo y monto
- **WHEN** el PDF publica el CDT con plazos y rangos de monto
- **THEN** cada cruce plazo × monto es una fila con su `plazo_dias` y su tasa impresa, y los plazos sin tasa no se inventan

#### Scenario: Producto ausente
- **WHEN** el PDF no publica uno de los productos esperados
- **THEN** no se crea una fila para ese producto y la extracción lo informa

### Requirement: Cobertura de productos y exclusión de mora

La tabla SHALL cubrir los productos que publique el PDF: libre inversión, compra de cartera, crédito rotativo, libranza, vehículo nuevo, vehículo usado, vivienda, tarjeta de crédito, ahorro y CDT. MUST excluir la mora, las comisiones y los descuentos de la tabla de colocación.

#### Scenario: Producto publicado
- **WHEN** el PDF publica libranza y CDT
- **THEN** la tabla tiene una fila por cada producto con su segmento y su vigencia

#### Scenario: Mora, comisión o descuento
- **WHEN** el PDF publica una tasa de mora, una comisión o un descuento
- **THEN** no se registra como tasa de colocación en la tabla

### Requirement: Consulta determinista de la tasa vigente

El Tablero SHALL exponer una consulta que devuelva el rango E.A./M.V., la vigencia, la URL, el `sha256` y la fecha de extracción del producto. MUST leer la tabla Gold de la vigencia más reciente que contenga la fecha consultada y MUST informar `tasa_no_disponible` si no hay fila. MUST NOT usar la Bóveda ni una cifra escrita en el código.

#### Scenario: Un segmento
- **WHEN** el producto tiene una sola fila vigente
- **THEN** la consulta devuelve su rango, su vigencia, su URL, su `sha256` y su fecha de extracción

#### Scenario: Varias vigencias
- **WHEN** el producto tiene dos tablas con vigencias distintas
- **THEN** la consulta devuelve la más reciente y no mezcla tasas de períodos diferentes

#### Scenario: Sin tasa
- **WHEN** el producto solo tiene cuotas, comisiones o no aparece en la tabla
- **THEN** la consulta responde `tasa_no_disponible` y no usa una cuota como tasa

#### Scenario: Valor inválido
- **WHEN** una fila declara una tasa negativa o mayor que 100 %
- **THEN** la consulta la descarta y lo informa, sin corregirla

### Requirement: Envolvente de segmentos

Si el producto tiene varios segmentos, la consulta SHALL devolver la envolvente del producto (el `desde` más bajo y el `hasta` más alto) sin promediar y MUST conservar las filas por segmento como evidencia.

#### Scenario: Varios segmentos
- **WHEN** el mismo producto aparece en dos segmentos con rangos distintos
- **THEN** la consulta devuelve la envolvente y conserva las filas por segmento como evidencia

### Requirement: Semáforo con la tasa máxima y cuota en rango

El diagnóstico SHALL calcular la cuota francesa con los dos extremos del rango de tasa E.A. y MUST mostrar la cuota como rango. El semáforo, la razón de endeudamiento y la capacidad de pago SHALL calcularse con la tasa E.A. máxima del rango y la cuota máxima. Toda respuesta que cite una tasa MUST citar la vigencia desde/hasta y la URL de la fuente.

#### Scenario: Rango de tasa
- **WHEN** el producto tiene una tasa E.A. de 18,50 % a 24,90 %
- **THEN** la cuota se informa como rango y el semáforo se decide con 24,90 %

#### Scenario: Tasa única
- **WHEN** el PDF publica un solo valor o el usuario escribe una tasa exacta
- **THEN** desde y hasta coinciden y la cuota se muestra como un valor único

#### Scenario: Vigencia citada
- **WHEN** el diagnóstico responde con una tasa
- **THEN** el texto incluye la vigencia (por ejemplo, «vigente del 1 al 30 de noviembre de 2026») y la URL de la fuente

#### Scenario: Tasa ausente
- **WHEN** no hay fila para el producto elegido
- **THEN** el diagnóstico se detiene con `tasa_no_disponible` y no inventa una tasa

### Requirement: Límite de usura del período

La tabla SHALL validar cada tasa E.A. de crédito contra la tasa de usura certificada para su vigencia, registrada en `config/tasas.toml` con su fuente. MUST rechazar la publicación de una fila cuya tasa máxima supere la usura y MUST fallar de forma explicable con `usura_sin_certificar` si la certificación del período no está registrada. La suite MUST incluir una prueba que recorra todas las filas y verifique que ninguna tasa de crédito supera la usura del período.

#### Scenario: Tasa bajo la usura
- **WHEN** todas las tasas de crédito están por debajo de la usura certificada
- **THEN** la tabla se publica y la prueba de usura pasa

#### Scenario: Tasa sobre la usura
- **WHEN** una tasa de crédito supera la usura del período
- **THEN** la extracción falla con `tasa_sobre_usura`, no publica la fila y la prueba falla

#### Scenario: Certificación ausente
- **WHEN** `config/tasas.toml` conserva el centinela sin la certificación del período
- **THEN** la extracción falla con `usura_sin_certificar` y la prueba de usura no pasa

#### Scenario: Ahorro y CDT
- **WHEN** la tabla incluye productos de ahorro o CDT
- **THEN** se identifican como no sujetos a usura y no se usan para decidir el semáforo de crédito

### Requirement: Coherencia del Digiturno con el Tablero 2026

El Digiturno SHALL enviar las preguntas de tasas y tarifas al Tablero, que responde con la tabla 2026. MUST NOT responder una tasa 2026 desde la Bóveda, que conserva el PDF Gold 2025 hasta el reindexado opcional del día del congelamiento. El reindexado de la Bóveda MUST NOT ser requisito para que el Tablero responda ni para que la suite pase.

#### Scenario: Pregunta de tasa
- **WHEN** el usuario pregunta «¿cuál es la tasa de libranza?»
- **THEN** el turno es T y la respuesta sale del Tablero con la vigencia 2026

#### Scenario: Bóveda con el PDF 2025
- **WHEN** la Bóveda todavía indexa el PDF 2025
- **THEN** la respuesta de tasas no usa ese documento y sigue citando la vigencia 2026 del Tablero

#### Scenario: Reindexado opcional
- **WHEN** el equipo reindexa la Bóveda el día del congelamiento
- **THEN** el Tablero y la suite siguen funcionando sin cambios

### Requirement: Trazabilidad y regeneración determinista

La consulta y la respuesta SHALL devolver la fila de origen, la URL, el `sha256`, la fecha de extracción y la versión del Tablero para que el diagnóstico y el MCP puedan citar de dónde salió el cálculo. La respuesta MUST NOT depender del modelo ni de la red, y `make tablero` MUST ser idéntico en dos ejecuciones con las mismas entradas.

#### Scenario: Fuente citada
- **WHEN** el diagnóstico o el MCP usan una tasa
- **THEN** el resultado incluye la vigencia, la URL y el `sha256` del PDF de esa tasa

#### Scenario: PDF actualizado
- **WHEN** cambia el `sha256` del PDF y se regenera la tabla
- **THEN** la consulta devuelve la tasa nueva, su nueva fecha de extracción y no una copia en código

#### Scenario: Ejecución offline
- **WHEN** no hay red
- **THEN** la consulta y `make tablero` funcionan con la tabla Gold y el CSV locales
