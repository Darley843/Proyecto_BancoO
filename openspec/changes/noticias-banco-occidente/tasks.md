# Tasks

## 1. Configuración y fuente curada

- [x] 1.1 Añadir las rutas de noticias en `config.py` y la sección `[noticias]` en `config/site.toml`; verificar que `uv run python -c "from banco_occidente_corpus.config import load_config; c=load_config(); print(c.paths.news_source)"` carga sin error y muestra `data/noticias`.
- [x] 1.2 Crear `data/noticias/prensa.yaml` con la plantilla de campos y `data/noticias/README.md` con criterios de selección y verificación; verificar que el YAML de ejemplo se carga con `yaml.safe_load` y que el README documenta los 15-20 límites.
- [x] 1.3 Registrar 15-20 fichas de prensa externa, primero en `pendiente` y luego en `verificado` tras la verificación manual del usuario, cada una con título, fecha, medio, enlace original y resumen propio; verificar que el YAML carga y que no contiene cuerpo del artículo.
- [x] 1.4 Añadir una prueba de configuración que compruebe las rutas nuevas y que `[noticias]` tiene `desde`, `hasta`, `prensa` y `max_por_evento`; verificar con `uv run pytest test/test_news.py -k config`.

## 2. Parser oficial y privacidad

- [ ] 2.1 Implementar `parse_fecha_es` con los meses en español y probar `Octubre 19-2026`, `Septiembre 01-2026`, `Enero 2-2025` y una fecha inválida; verificar con `uv run pytest test/test_news.py -k fecha`.
- [ ] 2.2 Implementar `parse_hechos_relevantes` seleccionando la tabla por encabezados `Fecha/Tema/Resumen/Anexo Descargable`, con filtro `desde/hasta`, enlace de anexo normalizado y tope de 40; verificar con un fixture que incluya una fila con PDF, una con “No aplica”, una de 2024 y una tabla de accionistas que debe ignorarse.
- [ ] 2.3 Implementar la derivación de título y resumen oficial, y la exclusión de avisos mensuales de dividendos; verificar que un fixture con dividendos no genera ficha y que un hito material sí la genera.
- [ ] 2.4 Implementar la validación de PII para título y resumen (cédula, NIT, correo y teléfono); verificar que una ficha con cada dato se rechaza y que la tabla de accionistas nunca llega al render.
- [ ] 2.5 Actualizar `docs/FUENTES.md` con la tabla de hechos relevantes, el enlace “Ver Anexo” y la exclusión explícita de la tabla de accionistas; verificar que las rutas y encabezados documentados coinciden con el fixture y con `test_news.py`.
- [ ] 2.6 Implementar `vincular_documento(anexo, indice)` leyendo `data/gold/documents.jsonl` por URL canónica, con variantes `?download=true` y host alterno `www`/`portalpublico`; verificar con pruebas de coincidencia, no coincidencia y que no se invoca ninguna función de descarga o extracción.

## 3. Prensa externa y validación

- [ ] 3.1 Implementar `load_prensa` y `validar_ficha` con campos obligatorios, fecha ISO, URL `http(s)`, `estado` permitido y resumen no vacío; verificar con pruebas de campo faltante, fecha inválida, URL inválida y estado desconocido.
- [ ] 3.2 Implementar `deduplicar` por `id`, por `fuente` y por `evento`+`medio`, con máximo dos coberturas externas por evento; verificar con un YAML que repita URL y evento y comprobar que no se duplican fichas.
- [ ] 3.3 Aplicar la regla de verificación: una ficha `pendiente` no se publica en Gold y una `verificado` sí; verificar con dos entradas de prueba y comprobar que solo aparece la verificada.
- [ ] 3.4 Documentar en `data/noticias/README.md` el diccionario de campos, el vocabulario de `temas` y el procedimiento de verificación humana; verificar que el README menciona los cinco datos mínimos y que prohíbe copiar el artículo.

## 4. Renderizado Gold, corpus e índice

- [ ] 4.1 Implementar `render_ficha` con frontmatter completo y cuerpo limitado a título, medio, fecha, enlace y resumen; si existe documento Gold, incluir `documento_id`, `documento_archivo`, `documento_titulo` y enlace relativo `../documents/<archivo>.md`; verificar con una prueba que el cuerpo no contiene párrafos del artículo ni imágenes.
- [ ] 4.2 Implementar `merge_corpus` eliminando filas antiguas `noticia-*`/`hecho-*`, conservando las filas del sitio y evitando duplicados; verificar ejecutando la fusión dos veces y comparando el número de filas.
- [ ] 4.3 Implementar `write_noticias_index` con ventana, conteos por tipo/origen/año/medio y tabla de fichas; verificar con un conjunto de dos fichas que el índice refleja exactamente sus fechas, enlaces y documentos vinculados.
- [ ] 4.4 Extender `healthcheck.py` para exigir `fecha_publicacion`, `tipo`, `origen`, `medio` y `resumen` en páginas `noticia-*`/`hecho-*`, detectar ids duplicados y validar que `documento_archivo` exista cuando haya `documento_id`; verificar con fixtures válido e inválido.
- [ ] 4.5 Actualizar `CONSTITUTION.md` §2, §7 y §11 y `docs/ESTANDAR.md` §4 y §7 con los campos nuevos, las fichas Gold, `_NOTICIAS.md` y el enlace a documentos; verificar que los ejemplos de frontmatter y el contrato coinciden con `render_ficha` y sin reescribir las secciones de PDF y videos.

## 5. CLI, target y bloqueo

- [ ] 5.1 Implementar `build_noticias` con `desde`, `hasta`, `sin_red`, lectura de Bronze, petición puntual si falta Bronze, lectura de solo lectura de `documents.jsonl` y escritura de fichas/corpus/índice; verificar con un fixture y un `tmp_path` que no se toca la red, que se generan los tres artefactos y que no se descargan PDFs.
- [ ] 5.2 Añadir el subcomando `noticias` en `cli.py` con `--desde`, `--hasta`, `--sin-red` y `--force`; verificar que `uv run corpus noticias --help` lista las opciones.
- [ ] 5.3 Añadir solo el target `make noticias` en `makefile`; verificar que `make noticias` ejecuta el subcomando y que `make all`, `make gold`, `make deliver`, `make docs`, `make docs-finanzas`, `make videos` y `make media` no cambian en el diff.
- [ ] 5.4 Implementar la detención ante `403` o bloqueo persistente sin cambiar UA, proxies ni velocidad; verificar con un mock que el comando falla, muestra el motivo y no escribe nuevas fichas oficiales.
- [ ] 5.5 Documentar el comando y el target en `README.md` y `AGENTS.md`; verificar que la documentación indica que `make noticias` es independiente de `all`, `gold`, `deliver`, `docs`, `docs-finanzas`, `videos` y `media`.

## 6. Integración y verificación

- [ ] 6.1 Ejecutar `make fmt` y `make check`; verificar que lint, tipos y pruebas pasan al 100 %.
- [ ] 6.2 Ejecutar `make demo`; verificar que el pipeline offline sigue funcionando sin red y sin depender de noticias.
- [ ] 6.3 Ejecutar `uv run corpus noticias --sin-red` con el fixture; verificar que aparecen `data/gold/pages/noticia-*.md`, `data/gold/pages/hecho-*.md`, `data/gold/_NOTICIAS.md` y las filas correspondientes en `corpus.jsonl`, incluyendo los enlaces a documentos cuando el fixture los tenga.
- [ ] 6.4 Ejecutar `make health`; verificar que el contrato de Gold, las fichas de noticias y los enlaces a documentos son consistentes.
- [ ] 6.5 Ejecutar `make noticias` desde red residencial colombiana; si el sitio responde `403`, verificar que el comando se detiene y avisa sin evadir el bloqueo.
- [ ] 6.6 Revisar `_NOTICIAS.md` y `_INDICE.md`; verificar que hay como máximo 40 hechos oficiales, 15-20 fichas externas verificadas, ninguna tabla de accionistas, ningún cuerpo de artículo copiado y que cada anexo existente tiene su enlace a documento.
- [ ] 6.7 Comparar el inventario de `data/gold/documents/` y `data/gold/videos/` antes y después de `make noticias`; verificar que el número de archivos y sus hashes no cambian y que no aparecen PDFs nuevos.
- [ ] 6.8 Revisar el diff final; verificar que no se modificaron `make all`, `make gold`, `make deliver`, `make docs`, `make docs-finanzas`, `make videos`, `make media`, `documents.py`, `videos.py` ni `knowledge.py`, y que no se añadieron dependencias ni secretos.

## Workflow follow-up

- Archivar el cambio después de que la revisión del proyecto esté satisfecha.
- Verificar el resultado archivado y que las specs principales quedaron actualizadas.
