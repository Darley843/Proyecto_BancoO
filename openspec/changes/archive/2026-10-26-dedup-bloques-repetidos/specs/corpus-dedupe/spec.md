# Spec Delta

## Purpose

Detectar y medir repeticiones de líneas y bloques en las páginas web de Gold, sin modificar el entregable, para decidir con evidencia cualquier política de deduplicación.

## ADDED Requirements

### Requirement: Alcance del análisis

El sistema SHALL analizar únicamente los archivos Markdown de `data/gold/pages/` cuyo nombre no empiece por `hecho-` ni `noticia-`, y MUST NOT leer `data/gold/documents/` ni `data/gold/videos/`. El frontmatter YAML no se considera texto analizable.

#### Scenario: Solo páginas web del sitio

- **WHEN** `data/gold/pages/` contiene páginas del sitio y fichas de noticias
- **THEN** el análisis incluye solo las páginas del sitio y reporta ese total

#### Scenario: Fichas de noticias excluidas

- **WHEN** una ficha `hecho-*` o `noticia-*` contiene un bloque que se repite en varias páginas
- **THEN** el bloque no se cuenta y la ficha no aparece entre las páginas analizadas

#### Scenario: Documentos y videos excluidos

- **WHEN** `data/gold/documents/` o `data/gold/videos/` contienen un bloque repetido
- **THEN** el bloque no se cuenta y esos archivos no aparecen en el reporte

### Requirement: Detección de líneas y bloques consecutivos

El sistema SHALL detectar líneas repetidas y bloques de 2 o 3 líneas de contenido consecutivas, considerando consecutivas las líneas que quedan tras descartar líneas vacías, separadores, enlaces sueltos y ruido de Markdown.

#### Scenario: Bloque de tarjeta de producto

- **WHEN** tres líneas consecutivas con el título y la descripción de una tarjeta se repiten en varias páginas
- **THEN** el sistema las detecta como un bloque de 3 líneas con su número de páginas

#### Scenario: Línea suelta repetida

- **WHEN** una sola línea de contenido se repite en varias páginas
- **THEN** el sistema también la detecta como un bloque de 1 línea

### Requirement: Comparación insensible a mayúsculas y tildes

El sistema SHALL comparar el texto sin distinguir mayúsculas ni tildes y SHALL mostrar en el reporte la grafía original de la primera aparición.

#### Scenario: Mayúsculas distintas

- **WHEN** una página escribe "Solicita tu tarjeta" y otra "SOLICITA TU TARJETA"
- **THEN** ambas apariciones cuentan para el mismo bloque

#### Scenario: Tildes distintas

- **WHEN** una página escribe "Cuenta de Nómina" y otra "Cuenta de Nomina"
- **THEN** ambas apariciones cuentan para el mismo bloque y el reporte conserva "Nómina"

### Requirement: Conteo único por página

El sistema SHALL contar cada página una sola vez por bloque, aunque el mismo bloque aparezca varias veces dentro de esa página.

#### Scenario: Bloque repetido dentro de una página

- **WHEN** un bloque aparece dos veces en una página y una vez en otras cuatro páginas
- **THEN** el bloque reporta cinco páginas y no seis apariciones

### Requirement: Porcentaje repetido por umbral

El sistema SHALL calcular, para umbrales de 5, 10 y 20 páginas, el porcentaje de líneas de contenido que pertenecen a al menos un bloque presente en un número de páginas mayor o igual al umbral. Los solapamientos entre bloques MUST contarse una sola vez.

#### Scenario: Tres umbrales

- **WHEN** se genera el reporte
- **THEN** incluye una fila para cada umbral de 5, 10 y 20 páginas con su porcentaje

#### Scenario: Bloques solapados

- **WHEN** una línea pertenece a un bloque de 1 línea y a un bloque de 2 líneas que superan el mismo umbral
- **THEN** la línea se cuenta una sola vez en el porcentaje

### Requirement: Reporte de repeticiones en Gold

El sistema SHALL escribir `data/gold/_REPETIDOS.md` con el total de páginas analizadas, las filas de umbrales 5/10/20 y el top 20 de bloques ordenado por número de páginas.

#### Scenario: Reporte completo

- **WHEN** termina el análisis
- **THEN** `data/gold/_REPETIDOS.md` existe y contiene el total de páginas, los tres umbrales y el top 20

#### Scenario: Páginas de ejemplo

- **WHEN** un bloque del top 20 aparece en varias páginas
- **THEN** el reporte muestra hasta tres identificadores de página como ejemplo

### Requirement: Orden determinista del top 20

El sistema SHALL listar como máximo 20 bloques, con su tamaño en líneas, número de páginas y ejemplos. El orden MUST ser determinista cuando dos bloques empatan en número de páginas.

#### Scenario: Más de veinte bloques

- **WHEN** se detectan más de veinte bloques
- **THEN** el reporte lista exactamente veinte

#### Scenario: Empate en número de páginas

- **WHEN** dos bloques aparecen en el mismo número de páginas
- **THEN** el desempate produce el mismo orden en ejecuciones sucesivas

### Requirement: Uso de unique_ratio

El sistema SHALL reportar la proporción de contenido único global, el promedio por página y las páginas con menor proporción de contenido único.

#### Scenario: Página muy repetitiva

- **WHEN** una página repite muchas de sus propias líneas
- **THEN** su proporción de contenido único es menor y aparece entre las páginas destacadas del reporte

#### Scenario: Resumen de unique_ratio

- **WHEN** se genera el reporte
- **THEN** incluye el valor global, el promedio por página y la lista de páginas con menor proporción

### Requirement: Solo medición sobre Gold

El sistema MUST NOT crear, modificar ni eliminar páginas de Gold, `corpus.jsonl`, `documents.jsonl`, `videos.jsonl` ni ningún otro artefacto. La única escritura permitida es `data/gold/_REPETIDOS.md`.

#### Scenario: Ejecución repetida

- **WHEN** se ejecuta el análisis dos veces sobre el mismo Gold
- **THEN** los hashes de todas las páginas y del corpus no cambian

#### Scenario: Reporte idempotente

- **WHEN** se repite la ejecución con los mismos datos
- **THEN** el contenido de `_REPETIDOS.md` es idéntico

### Requirement: Comando y target sin red

El sistema SHALL exponer `uv run corpus repetidos` y `make repetidos`. Ambos MUST funcionar sin peticiones HTTP y MUST NOT encadenarse en `make all`, `make gold` ni `make deliver`.

#### Scenario: Ejecución offline

- **WHEN** no hay acceso a la red
- **THEN** el comando termina correctamente y genera el reporte

#### Scenario: Independencia de los targets existentes

- **WHEN** se revisan `make all`, `make gold` y `make deliver`
- **THEN** ninguno ejecuta `repetidos`
