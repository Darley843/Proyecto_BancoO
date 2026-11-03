# Spec Delta

## Purpose

Ofrecer una app web propia con la metáfora de una sucursal bancaria, sin frameworks ni compilación, que consuma la API local y muestre cada área del sistema en su propia vista.

## ADDED Requirements

### Requirement: App web sin frameworks

La app SHALL servirse desde `app/web/` con HTML, CSS y JavaScript propios, sin framework de frontend, sin paso de compilación y sin dependencias de Node. MUST funcionar con el servidor local y MUST NOT contener reglas de negocio.

#### Scenario: Sin compilación

- **WHEN** se abre la app con `make app`
- **THEN** el navegador carga HTML, CSS y JavaScript sin ejecutar un build

#### Scenario: Sin reglas de negocio

- **WHEN** se revisa el JavaScript de una vista
- **THEN** solo formatea datos y llama a la API; no decide rutas, costos ni validaciones

### Requirement: Una vista por archivo

La app SHALL tener una vista por archivo en `app/web/vistas/`: `vestibulo`, `ventanilla`, `boveda`, `tablero`, `camara` y `arqueo`. Cada vista MUST poder abrirse de forma independiente desde la navegación de la sucursal.

#### Scenario: Seis vistas

- **WHEN** se revisa `app/web/vistas/`
- **THEN** existen los seis archivos y la navegación lleva a cada uno

#### Scenario: Vista aislada

- **WHEN** se abre una vista concreta
- **THEN** muestra su contenido sin depender de que otra vista se haya cargado antes

### Requirement: Datos de ejemplo con la forma de la API

La app SHALL incluir `app/web/datos-ejemplo/` con archivos cuya estructura MUST coincidir con las respuestas de la API (`estado`, `preguntar`, `tablero`, `mapa`, `pipeline`, `arqueo` y `vestibulo`). Esos datos MUST permitir revisar el diseño sin servidor ni claves.

#### Scenario: Misma forma

- **WHEN** se compara un archivo de ejemplo con su respuesta real
- **THEN** los campos y tipos coinciden

#### Scenario: Diseño sin servidor

- **WHEN** se abre una vista en modo de ejemplo
- **THEN** se pinta con los datos locales y no se llama a la API

### Requirement: Servidor y comando de arranque

`app.py` SHALL levantar uvicorn en `127.0.0.1:8000`, sirviendo la API y los archivos de `app/web/`. `make app` MUST ejecutar ese mismo arranque. El comando MUST NOT abrir un host público ni requerir Streamlit.

#### Scenario: Arranque único

- **WHEN** se ejecuta `make app`
- **THEN** queda disponible la API y la app en `http://127.0.0.1:8000`

#### Scenario: Sin Streamlit

- **WHEN** se ejecuta `make app` después del retiro
- **THEN** no se inicia ningún proceso de Streamlit

### Requirement: Ventanilla conversacional

La vista Ventanilla SHALL enviar `{pregunta, thread_id}` a `POST /api/preguntar`, mantener el `thread_id` durante la sesión del navegador y mostrar turno, ruta, motivo, respuesta, fuentes, tokens, costo, tiempo y si vino de caché.

#### Scenario: Primera pregunta

- **WHEN** el usuario escribe su primera pregunta
- **THEN** la vista crea un `thread_id`, la envía y muestra la respuesta con sus fuentes

#### Scenario: Seguimiento

- **WHEN** el usuario pregunta «¿Y cuánto cuesta?» en el mismo hilo
- **THEN** la vista reutiliza el `thread_id` y muestra la pregunta reformulada

#### Scenario: Error de la API

- **WHEN** la API responde con error
- **THEN** la vista muestra el mensaje y permite reintentar sin perder el hilo

### Requirement: Bóveda explorable

La vista Bóveda SHALL pedir `GET /api/boveda/mapa?pregunta=` y dibujar los puntos del corpus, la posición de la pregunta y el top de fragmentos con su título, sección, tipo y similitud.

#### Scenario: Mapa con consulta

- **WHEN** el usuario escribe una pregunta en la Bóveda
- **THEN** el mapa resalta la pregunta y la lista de fragmentos recuperados

#### Scenario: Sin índice

- **WHEN** la API informa que el índice no está listo
- **THEN** la vista lo explica y no dibuja un mapa vacío como si hubiera datos

### Requirement: Tablero consultable

La vista Tablero SHALL consumir `GET /api/tablero?q=` y mostrar las filas con concepto, valor, moneda, periodicidad, vigencia, origen y fuente, con un filtro de texto.

#### Scenario: Filtro de filas

- **WHEN** el usuario escribe «cuota de manejo»
- **THEN** la tabla muestra solo las filas coincidentes

#### Scenario: Fuente visible

- **WHEN** se muestra una fila
- **THEN** su enlace a la fuente pública es visible y abre en otra pestaña

### Requirement: Cámara, arqueo y vestíbulo

La vista Cámara SHALL mostrar `GET /api/pipeline` con la etapa de indexación; la vista Arqueo SHALL mostrar `GET /api/arqueo` con las métricas y la comparación v1/v2; la vista Vestíbulo SHALL mostrar `GET /api/vestibulo` con los hitos de `config/vestibulo.toml`.

#### Scenario: Pipeline visible

- **WHEN** se abre Cámara
- **THEN** se ven las etapas del pipeline y el estado de indexación

#### Scenario: Arqueo visible

- **WHEN** se abre Arqueo
- **THEN** se ven hit@5, MRR, exactitud, citas y el resultado de McNemar

#### Scenario: Vestíbulo con hitos

- **WHEN** se abre Vestíbulo
- **THEN** se ven los hitos con año, texto y enlace

### Requirement: Retiro de Streamlit

Al completar el cambio, el proyecto MUST eliminar `app/streamlit_app.py`, `app/scraping_ui.py` y la dependencia `streamlit`, y MUST actualizar la documentación y los comandos que los mencionan.

#### Scenario: Sin restos de Streamlit

- **WHEN** se busca «streamlit» en el código, `pyproject.toml`, el Makefile y la documentación
- **THEN** no quedan referencias activas

#### Scenario: Pruebas y pipeline intactos

- **WHEN** se ejecuta `make check` y `make demo` después del retiro
- **THEN** todo pasa sin Streamlit instalado
