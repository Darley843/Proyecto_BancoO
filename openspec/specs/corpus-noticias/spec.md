# corpus-noticias Specification

## Purpose

Incorporar al corpus Gold hechos relevantes oficiales y fichas de prensa externa fechadas y trazables, sin copiar artículos completos ni datos personales, para que el RAG pueda citar la actualidad del Banco de Occidente entre 2025 y hoy.

## Requirements

### Requirement: Selección de hechos relevantes oficiales

El sistema SHALL extraer de la tabla “Información Relevante” de la página de inversionistas solo hitos materiales publicados entre el 2025-01-01 y la fecha de ejecución, con un máximo de 40 fichas.

#### Scenario: Selección dentro de la ventana

- **WHEN** la tabla contiene eventos de 2024, 2025 y 2026
- **THEN** el sistema incluye únicamente los eventos con fecha entre 2025-01-01 y la fecha de ejecución

#### Scenario: Exclusión de dividendos rutinarios

- **WHEN** el evento es un aviso mensual de pago de dividendos
- **THEN** el sistema no genera una ficha y lo registra como excluido por rutinario

#### Scenario: Tope de hitos materiales

- **WHEN** hay más de 40 hitos materiales en la ventana
- **THEN** el sistema conserva como máximo 40 y reporta cuántos quedaron fuera por el tope

### Requirement: Ficha de prensa externa mínima

El sistema SHALL guardar de cada noticia de prensa externa solo título, fecha de publicación, medio, enlace original y resumen propio; MUST NOT guardar el cuerpo del artículo, imágenes, audio ni PDFs de prensa.

#### Scenario: Ficha externa completa

- **WHEN** una noticia externa fue verificada y aceptada
- **THEN** la ficha contiene título, fecha, medio, enlace y resumen propio, sin cuerpo del artículo

#### Scenario: Contenido no permitido

- **WHEN** la entrada de prensa incluye párrafos copiados, una imagen o un PDF
- **THEN** el sistema rechaza la ficha y explica que solo se admite la ficha mínima

### Requirement: Verificación humana de prensa externa

El sistema SHALL mantener una ficha externa en estado `pendiente` hasta que una persona abra el enlace original y confirme que corresponde al Banco de Occidente de Colombia y que la fecha es correcta.

#### Scenario: Ficha sin verificar

- **WHEN** una ficha externa no tiene confirmación humana de enlace, empresa y fecha
- **THEN** el sistema la deja en `pendiente` y no la publica en Gold

#### Scenario: Enlace o fecha incorrectos

- **WHEN** el enlace corresponde a otra entidad o la fecha no coincide con la publicación
- **THEN** el sistema rechaza la ficha y reporta el motivo

### Requirement: Contrato Gold de las fichas

El sistema SHALL escribir cada ficha como Markdown con frontmatter en `data/gold/pages/noticia-*.md` o `data/gold/pages/hecho-*.md`, y SHALL añadir su fila a `data/gold/corpus.jsonl` con `fuente`, `titulo`, `seccion`, `fecha_publicacion`, `tipo`, `origen`, `medio`, `resumen`, `tokens` y `hash`.

#### Scenario: Ficha con contrato completo

- **WHEN** se genera una ficha oficial o externa
- **THEN** el archivo y la fila de `corpus.jsonl` contienen los campos obligatorios del contrato

#### Scenario: Regeneración idempotente

- **WHEN** se ejecuta la ingesta dos veces sin cambios en la fuente
- **THEN** no se duplican fichas ni filas de `corpus.jsonl`

### Requirement: Enlace con documentos Gold existentes

El sistema SHALL buscar cada anexo oficial en `data/gold/documents.jsonl` por URL canónica y, si existe, SHALL añadir `documento_id`, `documento_archivo` y `documento_titulo` a la ficha y un enlace relativo al documento Gold. MUST NOT descargar, copiar ni re-extraer el PDF.

#### Scenario: Anexo ya extraído

- **WHEN** el anexo oficial coincide con un registro de `documents.jsonl`
- **THEN** la ficha incluye los campos del documento y un enlace relativo a `../documents/`, sin descargar el PDF

#### Scenario: Anexo no extraído

- **WHEN** el anexo oficial no aparece en `documents.jsonl`
- **THEN** la ficha conserva la URL `anexo`, no añade campos de documento y la ingesta continúa sin error

#### Scenario: Variantes de URL del mismo anexo

- **WHEN** el anexo usa `?download=true` o el host alterno `www`/`portalpublico`
- **THEN** el sistema lo reconoce como el mismo documento y evita duplicarlo

### Requirement: Fuente curada fuera de Gold

El sistema SHALL leer la curaduría de prensa externa desde `data/noticias/prensa.yaml` y MUST NOT depender de archivos dentro de `data/gold/` como fuente editable.

#### Scenario: Limpieza de Gold

- **WHEN** se ejecuta `make clean`
- **THEN** `data/noticias/prensa.yaml` se conserva y las fichas Gold se pueden regenerar desde ella

#### Scenario: YAML inválido

- **WHEN** `prensa.yaml` no existe o no cumple los campos obligatorios
- **THEN** el sistema falla con un mensaje que indica el archivo y el campo inválido

### Requirement: Exclusión de datos personales

El sistema MUST ignorar siempre la tabla de accionistas y MUST rechazar cualquier ficha cuyo título o resumen incluya nombres de accionistas, cédulas, NIT, correos o teléfonos personales.

#### Scenario: Página con dos tablas

- **WHEN** la página de inversionistas contiene la tabla de hechos relevantes y la tabla de accionistas
- **THEN** el sistema procesa solo la tabla de hechos relevantes

#### Scenario: Dato personal en el resumen

- **WHEN** una ficha contiene una cédula, un NIT, un correo o un teléfono
- **THEN** el sistema rechaza la ficha y no la escribe en Gold

### Requirement: Detención ante bloqueo

El sistema MUST detenerse y avisar cuando el sitio responda `403` o bloquee la petición; MUST NOT evadir el bloqueo cambiando User-Agent, usando proxies, rotando identidades o aumentando la velocidad.

#### Scenario: Respuesta 403

- **WHEN** la página de inversionistas responde `403`
- **THEN** el comando termina con error, muestra el motivo y no escribe nuevas fichas oficiales

#### Scenario: Bloqueo persistente

- **WHEN** el bloqueo continúa tras los reintentos normales
- **THEN** el comando se detiene y sugiere revisar la red, sin intentar evadir el control

### Requirement: Comando separado de noticias

El sistema SHALL ofrecer `uv run corpus noticias` y el target `make noticias`, y MUST NOT cambiar el comportamiento de `make all`, `make gold` ni `make deliver`.

#### Scenario: Ejecución del target nuevo

- **WHEN** se ejecuta `make noticias`
- **THEN** se regeneran las fichas y se actualiza `corpus.jsonl` sin ejecutar el pipeline completo

#### Scenario: Targets existentes intactos

- **WHEN** se ejecutan `make all`, `make gold` o `make deliver`
- **THEN** su comportamiento y su secuencia de pasos no incluyen la ingesta de noticias

### Requirement: Índice y trazabilidad de noticias

El sistema SHALL generar `data/gold/_NOTICIAS.md` con la ventana de fechas, el conteo por tipo, origen, año y medio, y una tabla con fecha, título, medio, enlace y evento de cada ficha publicada.

#### Scenario: Índice generado

- **WHEN** termina la ingesta con fichas publicadas
- **THEN** `_NOTICIAS.md` existe y refleja exactamente las fichas de `corpus.jsonl`

#### Scenario: Sin fichas publicadas

- **WHEN** no hay fichas verificadas dentro de la ventana
- **THEN** el índice se genera con conteos en cero y una nota de que no hubo publicaciones
