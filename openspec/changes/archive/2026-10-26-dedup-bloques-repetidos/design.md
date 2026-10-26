# Design

## Context

Ver `proposal.md` para la motivación y `specs/corpus-dedupe/spec.md` para los requisitos. El estado actual que condiciona el diseño es:

- Gold contiene 244 páginas: 184 del sitio, 40 `hecho-*` y 20 `noticia-*`. Los documentos PDF y los videos viven en `data/gold/documents/` y `data/gold/videos/`, fuera de `pages/`.
- `dedupe.py` solo se usa hoy en la limpieza de Silver. `find_boilerplate()` exige `max(min_docs, 35 %)`; sobre 184 páginas son 64, y la línea más repetida del inventario actual aparece en 62. `unique_ratio()` existe pero no se llama.
- Bronze local conserva 1 HTML y Silver 0 archivos. `make clean && make extract && make gold` no puede regenerar las 184 páginas del sitio; el Gold versionado es la única fuente disponible para medir.
- El proyecto usa `uv`, Ruff, `ty`, pytest sin red y docstrings en español con anotaciones de tipo para toda función nueva.

## Goals / Non-Goals

**Goals:**

- Producir un diagnóstico determinista y offline de repeticiones en las páginas web de Gold.
- Medir líneas y bloques de 2-3 líneas con umbrales absolutos de 5, 10 y 20 páginas.
- Escribir un único reporte nuevo, `data/gold/_REPETIDOS.md`, sin tocar el resto de Gold.
- Dejar el comando y el target aislados, fáciles de ejecutar y de probar con fixtures pequeñas.
- Corregir la documentación sobre la reprocesabilidad real de Bronze.

**Non-Goals:**

- Eliminar o reescribir contenido de Gold.
- Cambiar `find_boilerplate`, `strip_boilerplate` ni el comportamiento de Silver.
- Inferir una política de deduplicación o aplicarla automáticamente.
- Medir fichas de noticias, PDFs o videos.
- Añadir dependencias, caché, base de datos o servicios externos.
- Cambiar `make all`, `make gold`, `make deliver`, `make docs`, `make videos` o `make media`.

## Decisions

### 1. Análisis dentro de `dedupe.py`, sin acoplarlo a Silver

Se añaden funciones nuevas en `dedupe.py` y se conservan intactas `find_boilerplate`, `strip_boilerplate` y `unique_ratio`. La API prevista es:

- `analyze_gold_repetitions(pages_dir: Path, *, thresholds: tuple[int, ...] = (5, 10, 20), top: int = 20, max_block_lines: int = 3) -> RepetitionReport`
- `render_repetitions_report(report: RepetitionReport) -> str`
- `write_repetitions_report(config: Config) -> Path`

`RepetitionReport` agrupa páginas analizadas, líneas de contenido, resultados por umbral, top de bloques y métricas de `unique_ratio`. Así las pruebas pueden verificar datos sin depender del Markdown y el CLI solo imprime un resumen.

Alternativa descartada: un módulo `repetitions.py` separado. El usuario pidió explícitamente la función en `dedupe.py` y el alcance es pequeño.

### 2. Lectura limitada a `pages/` y exclusión por prefijo

Se recorren solo `data/gold/pages/*.md`, ordenados por nombre. Se excluyen los stems que empiezan por `hecho-` o `noticia-`, y por defensa los que empiezan por `_`. Documentos y videos no se leen porque no están en `pages/`; el reporte lo declara. El frontmatter se separa con un parser mínimo local (delimitador `---`) para no importar `knowledge.py` ni arrastrar `jsonschema` a la ruta de extracción.

Alternativa descartada: reutilizar `knowledge.load_page()`. Funciona, pero acopla `dedupe.py` a una capa superior y a dependencias que no necesita.

### 3. Normalización solo para comparar; el reporte conserva el original

Se añade un normalizador interno que aplica el mismo tratamiento de Markdown y espacios que `normalize_line`, más `unicodedata.normalize("NFKD")` y eliminación de marcas combinantes. `normalize_line` no se modifica para no alterar la deduplicación de Silver. El texto que se muestra en el reporte se toma de la primera aparición encontrada, con su grafía y tildes originales.

Alternativa descartada: cambiar `normalize_line` para que ignore tildes. Mejora la comparación, pero cambia el comportamiento existente de Silver sin que este cambio lo requiera.

### 4. Bloques sobre líneas de contenido consecutivas

Cada página se reduce a una lista de líneas de contenido: se eliminan líneas vacías, separadores, enlaces sueltos y ruido mediante `is_noise`. La lista resultante define la adyacencia. Para cada tamaño 1, 2 y 3 se generan las tuplas de claves normalizadas; en cada página se usa un `set` antes de incrementar el contador, de modo que una página cuenta una sola vez por bloque. Los ejemplos se guardan en orden de archivo y se limitan a tres.

Alternativa descartada: contar apariciones totales. Infla los bloques que se repiten dentro de una misma página y contradice el requisito de conteo único por página.

### 5. Porcentaje por cobertura única de líneas

Para cada umbral se marcan los índices de línea cubiertos por cualquier bloque cuyo número de páginas sea mayor o igual al umbral. La unión de índices evita doble conteo cuando un bloque de 1 línea está contenido en uno de 2 o 3. El porcentaje es `líneas cubiertas / total de líneas de contenido` sobre todas las páginas analizadas, redondeado a un decimal.

Alternativa descartada: sumar caracteres o apariciones. Es más difícil de auditar y de explicar en la sustentación; la línea es la unidad que ya usa el proyecto.

### 6. Top 20 determinista y con tamaño visible

Los bloques se ordenan por número de páginas descendente, luego por tamaño descendente y finalmente por texto normalizado. El reporte incluye una columna de tamaño para que las líneas sueltas no oculten los bloques de 2-3 líneas. Se muestran hasta tres páginas de ejemplo y se trunca el texto largo con un límite fijo, escapando `|` para no romper la tabla.

Alternativa descartada: un top 20 por cada tamaño. Genera 60 filas y hace más difícil leer el reporte; basta con la columna de tamaño y el conteo por tamaño en el resumen.

### 7. `unique_ratio` como diagnóstico existente

Se llama a `unique_ratio()` por página y sobre la lista concatenada de líneas para obtener el valor global. El reporte incluye el global, el promedio por página y las diez páginas con menor ratio. No se cambia su definición: mide líneas únicas normalizadas por página y sigue siendo sensible a tildes, a diferencia de la detección de bloques. Esa diferencia se documenta en el reporte para no mezclar métricas.

Alternativa descartada: reimplementar `unique_ratio` con la normalización nueva. Duplicaría lógica y cambiaría una métrica existente sin necesidad.

### 8. Un solo archivo de escritura y salida determinista

Se añade `Paths.repetitions_file` en `config.py` para resolver `data/gold/_REPETIDOS.md`. `write_repetitions_report()` crea el directorio si falta y escribe solo ese archivo, con `utf-8` y saltos `\n`. El contenido no incluye fecha ni hora, para que dos ejecuciones con los mismos datos produzcan bytes idénticos. No se llama a `build_gold`, `write_jsonl` ni a ninguna función que escriba páginas o índices.

Alternativa descartada: guardar un JSON intermedio en Gold. Añade un artefacto que el usuario no pidió y que también habría que versionar.

### 9. CLI y Makefile aislados

`cli.py` gana el subcomando `repetidos`, sin opciones en esta primera versión, y `cmd_repetidos()` imprime páginas analizadas, porcentajes por umbral y la ruta del reporte. No importa `HttpClient` ni usa `net.py`. El target `make repetidos` ejecuta `$(CORPUS) repetidos` y no se añade a `all`, `gold` ni `deliver`.

Alternativa descartada: encadenarlo a `make stats`. `stats` ya escribe `_INDICE.md` y se ejecuta en `make all` y `make deliver`; mezclar un diagnóstico nuevo con el entregable habría cambiado targets existentes.

### 10. Pruebas con fixtures en `tmp_path`

Se crea `test/test_dedupe.py` con un helper que escribe páginas Gold mínimas con frontmatter. Los casos cubren: bloque de 3 líneas detectado, línea repetida, no doble conteo por página, tildes y mayúsculas, exclusión de `hecho-*`/`noticia-*`, exclusión de documentos/videos, umbrales y solapamientos, presencia del top 20 y de `unique_ratio`, y hashes de Gold sin cambios. El comando se prueba con un monkeypatch que hace fallar cualquier conexión de red.

Alternativa descartada: usar el Gold real en las pruebas. Lo hace lento, frágil y dependiente de datos que cambian.

## Risks / Trade-offs

- **Bloques solapados inflan el porcentaje** → la métrica usa la unión de índices de línea y el conteo por página usa `set`.
- **El folding de tildes puede unir textos distintos** → solo elimina marcas diacríticas, no aplica stemming ni sinónimos; el reporte muestra el texto original para revisión humana.
- **El reporte vive en Gold y `make clean` lo borra** → se documenta que Gold es el entregable versionado y que hoy Bronze no permite regenerarlo; el reporte se regenera con `make repetidos` mientras Gold exista.
- **El top 20 puede estar dominado por líneas sueltas** → se añade la columna de tamaño y un conteo por tamaño en el resumen.
- **Las cifras de la documentación se desactualizan** → se fechan como inventario del checkout actual y se verifican con `make status` antes de cerrar el cambio.
- **`unique_ratio` y la detección usan normalizaciones distintas** → se documenta la diferencia y no se presenta el ratio como porcentaje de texto repetido.
- **El análisis depende de la calidad del Markdown Gold** → se ignoran frontmatter y ruido, y el reporte permite auditar los ejemplos de página.

## Migration Plan

1. Implementar el análisis, el reporte, el comando y el target sin tocar datos existentes.
2. Ejecutar `make repetidos` sobre el Gold actual y revisar `data/gold/_REPETIDOS.md`.
3. Actualizar `docs/ESTANDAR.md` y `CONSTITUTION.md` con la medición y la limitación de Bronze.
4. Ejecutar `make fmt`, `make check`, `make demo` y `make health`.
5. Commit con el reporte y la documentación. Rollback: eliminar `_REPETIDOS.md`, revertir los cambios de código, CLI, Makefile, pruebas y documentación; ningún dato de Gold requiere restauración porque el cambio no lo modifica.

## Open Questions

Ninguna. Los umbrales, el tamaño del top, la definición del porcentaje y el alcance de las páginas quedan resueltos en este diseño y en la spec.
