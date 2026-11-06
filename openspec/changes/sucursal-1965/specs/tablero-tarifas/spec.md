# Spec Delta

## Purpose

Convertir el tarifario PDF y las tablas Markdown de Gold en filas comparables de datos estructurados, para responder con cifras exactas, trazables y sin depender del modelo.

## ADDED Requirements

### Requirement: Extracción del tarifario PDF

El Tablero SHALL extraer filas de `data/gold/documents/ver-tarifas-2025-2025-a46157.md` a partir de sus líneas de texto plano, que siguen el patrón «concepto, valor y fecha de vigencia» (por ejemplo `Cuota de Manejo Tarjeta Débito $16.700 20-nov-25`). Cada fila MUST registrar concepto, categoría, valor, moneda, recargos, periodicidad, vigencia, origen `tarifario`, página y fuente.

#### Scenario: Cuota de manejo de tarjeta débito

- **WHEN** el tarifario trae `Cuota de Manejo Tarjeta Débito $16.700 20-nov-25`
- **THEN** el Tablero produce una fila con valor `16.700`, moneda `COP`, vigencia `2025-11-20` y origen `tarifario`

#### Scenario: Línea con recargo

- **WHEN** la línea incluye `+ IVA` o `+ Seguro`
- **THEN** el recargo se conserva en su columna y no se suma al valor

#### Scenario: Línea sin fecha

- **WHEN** una línea no trae fecha de vigencia
- **THEN** la fila se conserva con vigencia vacía y no se inventa una fecha

### Requirement: Extracción de tablas Markdown de Gold

El Tablero SHALL convertir en filas las tablas Markdown de las páginas de Gold sobre asistencias de tarjetas, Cuota Protegida, promociones y proyectos de vivienda, con origen `tabla_web`. MUST conservar la moneda o unidad que declara la tabla (COP, USD, EUR o porcentaje) y la URL exacta de la página.

#### Scenario: Asistencia en viajes nacionales

- **WHEN** la tabla declara `USD 2.000` para gastos médicos
- **THEN** la fila conserva `2.000`, moneda `USD` y la URL de la página de viajes nacionales

#### Scenario: Períodos de carencia

- **WHEN** la tabla de Cuota Protegida declara 30 días para desempleo y 90 días para enfermedades graves
- **THEN** el Tablero produce dos filas distintas con periodicidad diaria

#### Scenario: Promoción con descuento

- **WHEN** la tabla de promociones declara `20% de descuento` en McDonald's
- **THEN** la fila conserva `20`, unidad `%` y la vigencia que declare la página

#### Scenario: Precio de proyecto de vivienda

- **WHEN** la tabla de proyectos declara un precio desde `$407,027,630`
- **THEN** la fila conserva el monto, moneda `COP` y el proyecto como concepto

### Requirement: Esquema único de `tablero.csv`

El Tablero SHALL escribir `data/estructurados/tablero.csv` con exactamente las columnas `concepto`, `categoria`, `valor`, `moneda`, `recargos`, `periodicidad`, `vigente_desde`, `origen`, `pagina` y `fuente`. El archivo MUST ser UTF-8, con encabezado y orden determinista.

#### Scenario: Columnas del archivo

- **WHEN** termina `make tablero`
- **THEN** el CSV existe con las diez columnas en ese orden

#### Scenario: Orden determinista

- **WHEN** se ejecuta dos veces con el mismo Gold
- **THEN** el archivo resultante es idéntico

### Requirement: Cobertura de las preguntas de tabla

El Tablero SHALL cubrir las ocho preguntas de tipo `tabla` de `config/evaluacion/preguntas_fase2.toml`: para cada una MUST existir al menos una fila cuya `fuente` coincida con `fuentes_esperadas` y cuyo valor permita responderla.

#### Scenario: Ocho de ocho

- **WHEN** se cruzan las filas con las ocho preguntas de tabla
- **THEN** todas encuentran al menos una fila con la fuente esperada y el valor esperado

#### Scenario: Pregunta sin fila

- **WHEN** una pregunta de tabla no encuentra fila
- **THEN** `make tablero` lo reporta y termina con error, sin inventar el dato

### Requirement: Búsqueda y comparación deterministas

`tablero` SHALL exponer las funciones fijas `buscar_filas` y `comparar_filas`. `buscar_filas` filtra por concepto y categoría sin distinguir mayúsculas ni tildes y con coincidencia parcial: descarta palabras vacías y de pregunta, compara raíces para aceptar plurales y flexiones, y devuelve las filas con más coincidencias en vez de exigir todos los términos. `comparar_filas` compara dos grupos de filas y devuelve sus diferencias. Ninguna MUST llamar al modelo ni a la red.

#### Scenario: Búsqueda por concepto

- **WHEN** se busca «cuota de manejo»
- **THEN** devuelve las filas cuyo concepto contiene esos términos, sin distinguir tildes

#### Scenario: Pregunta natural

- **WHEN** se pregunta «¿Cuánto cuesta la cuota de manejo de la tarjeta débito?»
- **THEN** devuelve la cuota de manejo de la tarjeta débito, sin exigir que aparezcan «cuánto», «cuesta», «la» ni «de»

#### Scenario: Comparación de dos tarjetas

- **WHEN** se comparan las asistencias de Visa y Mastercard
- **THEN** la respuesta lista las filas donde el valor difiere y las que solo existen en un lado

#### Scenario: Sin coincidencias

- **WHEN** la búsqueda no encuentra filas
- **THEN** devuelve una lista vacía y no un error

### Requirement: Trazabilidad y regeneración sin red

Cada fila MUST indicar el archivo Gold de origen en `pagina` y la URL pública en `fuente`. `make tablero` MUST regenerar el CSV solo desde archivos locales y MUST NOT hacer peticiones HTTP.

#### Scenario: Fuente exacta

- **WHEN** se revisa una fila del tarifario
- **THEN** `fuente` coincide exactamente con una URL de `data/gold/corpus.jsonl` o de `documents.jsonl`

#### Scenario: Ejecución offline

- **WHEN** no hay acceso a la red
- **THEN** `make tablero` termina correctamente y regenera el CSV
