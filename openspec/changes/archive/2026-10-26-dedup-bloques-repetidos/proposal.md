# Proposal

## Why

En el inventario actual, Gold tiene 244 páginas (184 del sitio, 40 hechos y 20 noticias). Las tarjetas de producto y las llamadas a la acción se repiten en decenas de páginas: la línea más repetida aparece en 62 de las 184 páginas del sitio y hay bloques de 2-3 líneas en 20-31 páginas. La regla actual `find_boilerplate` exige `max(5, 35 %)` —64 páginas sobre 184— y se aplica en Silver, así que no mide estos casos; `unique_ratio` no se usa. El equipo decidió no borrar ni modificar nada de Gold, por lo que hace falta un diagnóstico medible, offline y repetible antes de decidir cualquier política de deduplicación.

## What Changes

- Añadir en `dedupe.py` un análisis de solo lectura de `data/gold/pages/*.md` que detecte líneas repetidas y bloques de 2-3 líneas consecutivas, indique en cuántas páginas aparece cada bloque y guarde hasta tres páginas de ejemplo.
- Excluir del análisis las fichas `hecho-*` y `noticia-*`; documentos y videos quedan fuera porque no viven en `pages/`.
- Comparar sin distinguir mayúsculas ni tildes, pero mostrar el texto original en el reporte.
- Contar cada página una sola vez por bloque, aunque el bloque se repita dentro de la misma página.
- Generar `data/gold/_REPETIDOS.md` con: total de páginas analizadas, porcentaje de texto repetido para umbrales de 5, 10 y 20 páginas, top 20 de bloques con su número de páginas y ejemplos, y uso de `unique_ratio` (global, promedio y páginas con menor ratio).
- Añadir `uv run corpus repetidos` y un target `make repetidos` independiente. No se encadenan en `make all`, `make gold` ni `make deliver`, y no hacen ninguna petición a la web.
- Añadir pruebas offline con fixtures pequeñas: bloque repetido, no doble conteo por página, tildes/mayúsculas, exclusión de fichas de noticias y ausencia de modificaciones en Gold.
- Documentar en `docs/ESTANDAR.md` y `CONSTITUTION.md` que la deduplicación de Gold es solo de medición y que el Bronze actual no permite regenerar las 184 páginas del sitio.

Fuera de alcance: eliminar líneas o bloques de Gold, reescribir `corpus.jsonl`, cambiar `find_boilerplate` o la limpieza de Silver, tocar Bronze, descargar nada, añadir dependencias, modificar `make all`/`gold`/`deliver`/`docs`/`videos`/`media`, y actualizar `README.md` o `AGENTS.md`.

## Capabilities

### New Capabilities

- `corpus-dedupe`: detección y medición de repeticiones en el corpus Gold, con umbrales por número de páginas, reporte reproducible y garantía de solo lectura sobre el entregable.

### Modified Capabilities

- Ninguna. No hay specs principales registradas y este cambio no altera requisitos existentes.

## Impact

- Código: `src/banco_occidente_corpus/dedupe.py` (análisis y reporte), `cli.py` (subcomando `repetidos`), `config.py` (ruta `_REPETIDOS.md`), `makefile` (solo target `repetidos`).
- Pruebas: nuevo `test/test_dedupe.py` con fixtures creadas en `tmp_path`; sin red.
- Datos: `data/gold/_REPETIDOS.md` nuevo. `data/gold/pages/`, `corpus.jsonl`, `documents/`, `videos/` quedan estrictamente de solo lectura.
- Documentación: `docs/ESTANDAR.md` §1, §3 y §7; `CONSTITUTION.md` §7 y §14.
- Sin dependencias nuevas. Sin cambios en Bronze, Silver, Knowledge ni en los targets existentes.
- Limitación documentada: Bronze local conserva 1 HTML y Silver 0 archivos, por lo que hoy no se pueden regenerar las 184 páginas del sitio; el reporte se apoya en el Gold versionado.
