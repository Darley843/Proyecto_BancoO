# Spec Delta

## Purpose

Preparar fragmentos verificables del corpus, indexarlos con embeddings locales y recuperarlos por similitud y por términos, para que el asistente responda con citas y sin enviar el corpus completo al modelo.

## ADDED Requirements

### Requirement: Fragmentos desde los chunks de Gold

La Bóveda SHALL construir fragmentos desde los chunks de `make chunks`. Los encabezados repetidos del menú MUST NOT usarse como encabezado del fragmento ni anteponerse a su texto. Los chunks cortos SHALL fusionarse preferentemente con sus hermanos de sección (mismo padre, mismo nivel y misma familia de encabezado normalizada) y el tope de 400 tokens MUST aplicarse al agrupar. Cada fragmento MUST conservar id estable, texto, URL, título, sección, encabezado, tipo y tokens.

#### Scenario: Encabezado de menú repetido

- **WHEN** el `heading` de un chunk se repite en el menú de varias páginas
- **THEN** no se usa como `encabezado` del fragmento ni se antepone a su texto, y se resuelve con el encabezado no repetido más cercano de su ruta

#### Scenario: Fragmento corto con hermanos de sección

- **WHEN** un chunk queda por debajo de 80 tokens y tiene un hermano de sección
- **THEN** se fusiona primero con ese hermano, entendiendo por hermano el chunk con el mismo padre, el mismo nivel y la misma familia de encabezado (su primera palabra significativa, normalizada sin tildes ni mayúsculas)

#### Scenario: Tope de 400 tokens al agrupar

- **WHEN** la fusión de un chunk corto con sus hermanos supera 400 tokens
- **THEN** el grupo no se forma: el fragmento se cierra antes del límite y el chunk sobrante abre el siguiente

#### Scenario: Último fragmento corto

- **WHEN** el último chunk de una página queda por debajo de 80 tokens y no hay otro que lo siga
- **THEN** se conserva como fragmento final aunque no llegue a 80 tokens

#### Scenario: Ruido de navegación

- **WHEN** un chunk contiene líneas de menú, migas de pan o enlaces sueltos
- **THEN** esas líneas no llegan al texto del fragmento

#### Scenario: Identificador estable

- **WHEN** se reconstruye el índice dos veces con el mismo Gold
- **THEN** cada fragmento conserva el mismo id

### Requirement: Límite de 400 tokens

Ningún fragmento MUST superar 400 tokens. Un bloque que no es tabla se parte por líneas; una línea que lo supera se parte por oraciones (punto seguido de espacio) y, como último recurso, en ventanas de 400 tokens.

#### Scenario: Bloque no tabla largo

- **WHEN** un bloque que no es tabla supera 400 tokens
- **THEN** se parte por líneas, luego por oraciones y como último recurso en ventanas de 400 tokens

#### Scenario: Ningún fragmento supera el límite

- **WHEN** se construyen los fragmentos
- **THEN** ninguno supera 400 tokens y el resumen reporta cero fragmentos por encima del límite

### Requirement: Tablas largas partidas por filas

Una tabla Markdown que supera 400 tokens SHALL partirse por filas repitiendo en cada parte la fila de encabezado y el separador. El reporte SHALL distinguir las tablas enteras de las tablas partidas por filas y contar en cuántas partes quedó cada tabla partida.

#### Scenario: Tabla larga partida por filas

- **WHEN** una tabla Markdown supera 400 tokens
- **THEN** se parte por filas y cada parte repite la fila de encabezado y el separador

#### Scenario: Reporte de tablas

- **WHEN** el resumen reporta las tablas del corpus
- **THEN** separa las tablas enteras de las tablas partidas por filas y cuenta en cuántas partes quedó cada tabla partida

### Requirement: Hechos verificados como fragmentos

La Bóveda SHALL incorporar los hechos de `data/knowledge/facts.jsonl` como fragmentos de tipo `hecho verificado`, con la URL y la sección de su evidencia y el valor del hecho como texto. MUST NOT indexar hechos sin evidencia ni fragmentos con datos personales.

#### Scenario: Hecho indexado

- **WHEN** un hecho trae `evidence.url`, `evidence.section` y `value`
- **THEN** aparece en el índice con tipo `hecho verificado` y la URL de su evidencia

#### Scenario: Hecho sin evidencia

- **WHEN** un hecho no trae URL de evidencia
- **THEN** no se indexa y el conteo de omitidos lo registra

### Requirement: Embeddings locales con prefijos

El sistema SHALL generar embeddings con Ollama usando `nomic-embed-text-v2-moe` y MUST aplicar el prefijo `search_document: ` al indexar y `search_query: ` al consultar. Los prefijos MUST poder desactivarse por configuración para el experimento.

#### Scenario: Prefijos activos

- **WHEN** se indexa un fragmento y luego se consulta con la configuración por defecto
- **THEN** el texto enviado a Ollama lleva `search_document: ` y `search_query: ` respectivamente

#### Scenario: Prefijos desactivados

- **WHEN** la configuración desactiva los prefijos
- **THEN** el texto se envía sin prefijo y el índice lo declara en sus metadatos

#### Scenario: Sin Ollama en las pruebas

- **WHEN** corre la suite de pruebas
- **THEN** no se hace ninguna petición a Ollama

### Requirement: Almacén vectorial persistente con coseno

El sistema SHALL persistir el índice en `data/boveda/chroma` y MUST crear la colección con métrica coseno fijada al crearla. El índice MUST poder reconstruirse desde cero sin modificar Gold ni la capa Knowledge.

#### Scenario: Métrica de la colección

- **WHEN** se crea la colección por primera vez
- **THEN** su métrica declarada es coseno

#### Scenario: Reconstrucción

- **WHEN** se borra `data/boveda/` y se vuelve a ejecutar la indexación
- **THEN** el índice se reconstruye con el mismo número de fragmentos

#### Scenario: Avance y tiempo de espera agotado

- **WHEN** `make indice` vectoriza por lotes y un lote supera `timeout_segundos`
- **THEN** la salida muestra el avance de cada lote terminado (`lote 3/15 · 192/952 fragmentos · 2 min 10 s`) y, si un lote agota el tiempo, un mensaje sin traceback indica qué lote falló, que el índice anterior queda intacto y cómo subir el timeout o revisar Ollama con `ollama ps`, con código de salida 1

#### Scenario: Índice fuera de Git

- **WHEN** se revisa el estado de Git después de indexar
- **THEN** `data/boveda/` no aparece como archivo versionado

### Requirement: Alcance de cada índice

`make indice` SHALL indexar las páginas web de Gold, los documentos PDF con `categoria_documento: producto` y los hechos verificados. `make indice-completo` SHALL añadir el resto de documentos PDF y los videos transcritos.

#### Scenario: Índice base

- **WHEN** se ejecuta `make indice`
- **THEN** el índice reporta páginas web, documentos de producto y hechos, y no incluye estados financieros

#### Scenario: Índice completo

- **WHEN** se ejecuta `make indice-completo`
- **THEN** el índice incluye además los PDF restantes y los videos con transcripción

### Requirement: Recuperación híbrida con pesos configurables

El recuperador SHALL combinar la búsqueda vectorial y BM25 con `EnsembleRetriever`, usando pesos configurables para cada componente. SHALL devolver fragmentos ordenados por relevancia y con `puntaje` entre 0 y 1 igual a 1 menos la distancia coseno.

#### Scenario: Pesos por configuración

- **WHEN** se sube el peso de BM25 y se baja el vectorial
- **THEN** el orden de los fragmentos cambia según esos pesos

#### Scenario: Puntaje normalizado

- **WHEN** el recuperador devuelve un fragmento
- **THEN** su `puntaje` está entre 0 y 1

#### Scenario: k por defecto

- **WHEN** se llama `buscar` sin indicar `k`
- **THEN** devuelve como máximo cinco fragmentos

### Requirement: Mapa 2D del corpus

El sistema SHALL proyectar los fragmentos indexados a dos dimensiones con PCA y SHALL ubicar la pregunta en la misma proyección, para que la vista Bóveda muestre el corpus, la consulta y los fragmentos recuperados. Las coordenadas `x` e `y` de los puntos y de la pregunta MUST normalizarse en el servidor de 0 a 100 antes de exponerlas.

#### Scenario: Puntos del mapa

- **WHEN** se pide el mapa de la Bóveda
- **THEN** cada punto trae coordenadas normalizadas entre 0 y 100, sección y título

#### Scenario: Pregunta proyectada

- **WHEN** el mapa se pide con una pregunta
- **THEN** la respuesta incluye la coordenada normalizada de la pregunta y el top de fragmentos recuperados

### Requirement: Contrato de fragmento y recuperador

`boveda/tipos.py` SHALL declarar la dataclass `Fragmento` y el `Protocol` `Recuperador`. Toda implementación del recuperador MUST cumplir `buscar(consulta: str, k: int = 5) -> list[Fragmento]` y devolver los campos del contrato.

#### Scenario: Implementación conforme

- **WHEN** una clase implementa `buscar` con esa firma
- **THEN** se acepta como `Recuperador` sin heredar de una clase concreta

#### Scenario: Campos completos

- **WHEN** se inspecciona un fragmento recuperado
- **THEN** trae id, texto, url, titulo, seccion, encabezado, tipo, tokens y puntaje
