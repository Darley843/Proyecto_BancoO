# Tasks

## 1. Núcleo de análisis en `dedupe.py`

- [x] 1.1 Añadir las estructuras tipadas del reporte, las constantes de umbrales/top/tamaño y la carga de páginas Gold con separación de frontmatter, filtro de `hecho-*`/`noticia-*` y exclusión de archivos `_*`; toda función nueva debe llevar docstring en español y anotaciones. Verificar con `uv run pytest test/test_dedupe.py -k "paginas or excluye"` que solo se analizan las páginas del sitio y que documentos/videos no se leen.
- [x] 1.2 Implementar la normalización de comparación (mayúsculas y tildes), la construcción de líneas de contenido consecutivas y la detección de bloques de 1, 2 y 3 líneas con conteo único por página y hasta tres ejemplos. Verificar con pruebas de bloque de tarjeta repetido, línea suelta, bloque repetido dos veces en una página y variantes con mayúsculas/tildes.
- [x] 1.3 Implementar el porcentaje de texto repetido para 5, 10 y 20 páginas mediante cobertura única de líneas, y las métricas de `unique_ratio` global, promedio y páginas con menor ratio. Verificar con pruebas de tres umbrales, bloques solapados y página con alta repetición interna.

## 2. Reporte `_REPETIDOS.md`

- [ ] 2.1 Añadir `Paths.repetitions_file` en `config.py` para resolver `data/gold/_REPETIDOS.md` y verificar con una prueba que la ruta apunta al archivo correcto sin crear artefactos adicionales.
- [ ] 2.2 Implementar el renderizado Markdown con total de páginas, tabla de umbrales, top 20 con tamaño/páginas/ejemplos y sección de `unique_ratio`, con orden determinista y escape de `|`. Verificar con una prueba que el reporte contiene esas secciones, no supera 20 bloques y conserva tildes en el texto mostrado.
- [ ] 2.3 Implementar la escritura del reporte con `utf-8`, saltos `\n` y sin fecha, de modo que dos ejecuciones produzcan el mismo contenido. Verificar con una prueba que solo se crea `_REPETIDOS.md` y que los hashes de todas las páginas, `corpus.jsonl`, `documents.jsonl` y `videos.jsonl` no cambian.

## 3. CLI y Makefile

- [ ] 3.1 Añadir `cmd_repetidos` y el subcomando `repetidos` en `cli.py`, sin importar `HttpClient` ni usar `net.py`; el comando debe imprimir páginas analizadas, porcentajes por umbral y la ruta del reporte. Verificar con `uv run corpus repetidos --help` y una prueba que bloquea conexiones de red y comprueba que el comando termina correctamente.
- [ ] 3.2 Añadir solo el target `make repetidos` al `makefile` y verificar con `make help` que aparece, que `make repetidos` ejecuta el subcomando y que `make all`, `make gold` y `make deliver` no lo contienen; revisar el diff del Makefile para confirmar que no se modificó ningún otro target.

## 4. Documentación

- [ ] 4.1 Actualizar `docs/ESTANDAR.md` §1 para corregir la reprocesabilidad real (Bronze con 1 HTML, Silver vacío, 184 páginas web en Gold), §3 para declarar la deduplicación de Gold como solo medición y §7 para incluir `_REPETIDOS.md` y `make repetidos` como artefacto independiente. Verificar que las rutas, comandos y cifras coinciden con `make status` y con el reporte generado.
- [ ] 4.2 Actualizar `CONSTITUTION.md` §7 con `_REPETIDOS.md`, la regla de que Gold no se edita y el límite actual de Bronze, y §14 con el pendiente de re-capturar Bronze para poder regenerar las 184 páginas. Verificar que el contrato de Gold no cambia y que el texto distingue la deduplicación de Silver de la medición de Gold.
- [ ] 4.3 Añadir la explicación de `make repetidos` en la documentación actualizada (comando, ausencia de red, independencia de `all`/`gold`/`deliver`) y verificar que el texto no promete eliminar contenido ni regenerar Gold desde Bronze.

## 5. Verificación de integración

- [ ] 5.1 Ejecutar `make fmt` y `make check`; verificar que lint, tipos y todas las pruebas pasan al 100 %.
- [ ] 5.2 Ejecutar `make demo` y `make health`; verificar que el pipeline offline y el contrato de Gold siguen funcionando sin depender del reporte.
- [ ] 5.3 Ejecutar `make repetidos` sobre el Gold real; verificar que el reporte declara 184 páginas analizadas, las filas de 5/10/20, el top 20 y la sección de `unique_ratio`, y que `git status` solo muestra `_REPETIDOS.md` como dato nuevo.
- [ ] 5.4 Ejecutar `make repetidos` dos veces y comparar el hash de `_REPETIDOS.md`; verificar que es idéntico. Revisar el diff final y confirmar que no cambiaron páginas de Gold ni `corpus.jsonl`, que no se añadieron dependencias, que no hay peticiones HTTP nuevas y que `make all`/`gold`/`deliver` permanecen intactos.

## Workflow follow-up

- Archivar el cambio cuando la revisión del proyecto esté satisfecha.
- Verificar que la spec principal `corpus-dedupe` quedó creada y que el reporte archivado conserva las cifras del inventario revisado.
