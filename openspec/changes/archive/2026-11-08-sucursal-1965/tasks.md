# Tasks

## 1. PR 0 — Dependencias (Darley — pendiente)

- [x] 1.1 Añadir con `uv add` las dependencias del diseño: `langgraph`, `langgraph-checkpoint-sqlite`, `langchain-chroma`, `langchain-classic`, `langchain-community`, `langchain-ollama`, `rank-bm25`, `fastapi`, `uvicorn[standard]` y `scikit-learn`; añadir `sqlalchemy` solo si las pruebas de `SqliteSaver` lo exigen. Verificar con `uv sync` que `uv.lock` cambia solo por `uv` y que `make check` sigue en verde.
- [x] 1.2 Comprobar que los imports nuevos cargan en el entorno del proyecto con `uv run python -c "import langgraph, chromadb, fastapi, sklearn, langchain_classic, langchain_community, langchain_ollama, rank_bm25"`; verificar que Streamlit sigue instalado para no romper `make app` antes del retiro.
- [x] 1.3 Añadir a `.gitignore` `data/boveda/` y confirmar que `data/asistente/` ya está ignorado; verificar con `git check-ignore -v data/boveda/chroma data/asistente/memoria.sqlite` que ambos quedan fuera de Git.
- [x] 1.4 Documentar la decisión de dependencias en `CONSTITUTION.md` §3 y §11 (tabla de stack y fila del historial) y verificar que el texto coincide con `pyproject.toml`; el PR no debe incluir código de los paquetes nuevos.

## 2. PR 2 — Plantilla de PR (Anny — hecho en #43)

- [x] 2.1 Verificar que `.github/PULL_REQUEST_TEMPLATE.md` incluye las partes de la sucursal (Bóveda, Digiturno, Ventanilla, Tablero, Cámara, Arqueo, Pantallas, Infraestructura), costo, seguridad, arquitectura, estándar y revisión; comprobar que ninguna persona puede aprobar su propio PR y que se referencia el cambio `sucursal-1965`.
- [x] 2.2 Verificar que la plantilla exige `make check`, `make demo`, `make status` si se tocó el corpus, GGA, capturas de pantalla, índice vectorial no versionado, fragmentos tratados como datos y peticiones al banco solo por `net.py`; revisar el renderizado en un PR de prueba.

## 3. Set de preguntas de fase 2 (Anny — hecho en #44)

- [x] 3.1 Verificar que `config/evaluacion/preguntas_fase2.toml` tiene 44 preguntas con `tipo` (`alcance`, `tabla`, `seguimiento`, `fuera`), `ruta_esperada` (`B`, `T`, `X`), `fuentes_esperadas` y `previa` solo en las de seguimiento; comprobar los conteos 20/12/6/6 y que cada URL esperada existe exactamente en `data/gold/corpus.jsonl`.
- [x] 3.2 Verificar que las 12 preguntas de tipo `tabla` apuntan al tarifario (41 a 44) y a las páginas de asistencias, Cuota Protegida, promociones y proyectos de vivienda, y que las 6 de tipo `fuera` incluyen saldo, cédula, consejo de inversión, otro banco, inyección de prompt y clima; ejecutar `uv run pytest test/test_preguntas_fase2.py`.

## 4. Métricas del Arqueo (Anny — hecho en #45)

- [x] 4.1 Verificar que `arqueo/metricas.py` expone `hit_at_k`, `mrr`, `exactitud`, `citas_correctas`, `resumen_uso`, `mcnemar` y la dataclass `Tarifas` con `TARIFAS_DEEPSEEK_FLASH` y `TARIFAS_DEEPSEEK_FLASH_PICO`; ejecutar `uv run pytest test/test_arqueo_metricas.py` y comprobar los casos de listas vacías, `k <= 0`, pares incompletos y `p = 1` sin discordancias.
- [x] 4.2 Hacer que `acierta_terminos` use `banco_occidente_corpus.texto.normalizar` (``casefold``, NFKD y eliminación de marcas combinantes), la misma función que reutiliza `asistente/evaluacion.py`, y añadir pruebas con «petición»/«peticion» y con «línea» frente a «linea» en los dos sentidos; verificar que el resto de la suite de métricas sigue pasando.
- [x] 4.3 Verificar que `TARIFAS_DEEPSEEK_FLASH` y `TARIFAS_DEEPSEEK_FLASH_PICO` son la única fuente de precios y que el docstring declara la franja de pico (01:00–04:00 y 06:00–10:00 UTC de lunes a viernes); comprobar que ningún otro archivo del repo repite esos valores.

## 5. PR 3 — Fragmentos (Nayla — pendiente)

- [x] 5.1 Crear `boveda/__init__.py` y `boveda/tipos.py` con la dataclass `Fragmento` y el `Protocol` `Recuperador` de la sección Contratos, con docstrings en español; verificar con una prueba que un fragmento acepta los nueve campos y que un recuperador simulado cumple la firma `buscar(consulta, k=5)`.
- [x] 5.2 Implementar `boveda/fragmentos.py`: lectura de `chunks_web.jsonl` y `chunks.jsonl`, fusión de chunks consecutivos de la misma página mientras el acumulado tenga menos de 80 tokens (salvo el último), partición de los de más de 400 tokens por párrafos sin romper tablas, descarte de ruido con `dedupe.is_noise` y `dedupe.normalize_line`, e id estable `frag:<sha256>`. Verificar con fixtures en `tmp_path` que el fragmento fusionado llega a 80 tokens, que el último corto se conserva y que dos ejecuciones dan los mismos ids.
- [x] 5.3 Añadir los hechos de `data/knowledge/facts.jsonl` como tipo `hecho verificado`, con `url`, `seccion` y `encabezado` de la evidencia, omitiendo hechos sin URL o con PII; verificar con fixtures los casos indexado, sin evidencia y con dato personal, y que el conteo de omitidos se reporta.
- [x] 5.4 Verificar que `boveda/fragmentos.py` no hace red ni escribe en Gold, Knowledge ni `data/boveda/`; ejecutar `uv run pytest test/test_boveda_fragmentos.py` y `make check`.

## 6. PR 4 — Índice (Nayla — pendiente)

- [x] 6.1 Implementar `boveda/embeddings.py` con `OllamaEmbeddings` (`nomic-embed-text-v2-moe`), `base_url` configurable (en `config/sucursal.toml`, con `OLLAMA_BASE_URL` y `OLLAMA_HOST` como respaldo) y los prefijos `search_document: ` y `search_query: ` desactivables; verificar con `DeterministicFakeEmbedding` y un espía que el texto indexado y el consultado llevan el prefijo correcto y que la bandera lo desactiva.
- [x] 6.2 Implementar `boveda/almacen.py` con el Protocol `AlmacenVectorial` y `ChromaAlmacen` persistente en `data/boveda/chroma`, colección `boveda` y `hnsw:space: cosine` fijado al crear; verificar con `tmp_path` que la métrica declarada es coseno, que el conteo persiste entre instancias y que `reiniciar` deja la colección vacía.
- [x] 6.3 Implementar `boveda/indice.py` para los alcances `base` (páginas web, PDF con `categoria_documento: producto`, hechos) y `completo` (añade PDF restantes y videos), escribiendo `data/boveda/indice.json` con modelo, prefijos, alcance, fragmentos y dimensión; verificar con un Gold mínimo en `tmp_path` que el alcance base excluye un PDF financiero y el completo lo incluye.
- [x] 6.4 Añadir los targets `make indice` y `make indice-completo` con los comandos del paquete y verificar que `make help` los lista, que `make indice` no toca `data/gold/` y que `git status` no muestra `data/boveda/`; comprobar la reconstrucción idempotente borrando el índice y repitiendo el conteo.
- [x] 6.5 Actualizar `docs/MODELADO.md` con la decisión de Ollama, `nomic-embed-text-v2-moe`, Chroma, métrica coseno, prefijos y alcance de cada target; verificar que los comandos y rutas documentados coinciden con el Makefile y con `config/sucursal.toml`.

## 7. PR 5 — Recuperador (Nayla — pendiente)

- [x] 7.1 Implementar `boveda/recuperador.py` con `EnsembleRetriever` de `langchain_classic`, `BM25Retriever` en memoria y pesos leídos de `config/sucursal.toml`; verificar con `DeterministicFakeEmbedding` que dos configuraciones de pesos producen órdenes diferentes sobre un corpus de prueba.
- [x] 7.2 Recalcular el `puntaje` de cada candidato como `1 - distancia coseno`, también para los que solo devuelve BM25; verificar con una prueba que todos los puntajes están entre 0 y 1, que el orden respeta los pesos y que `buscar` sin `k` devuelve como máximo cinco.
- [x] 7.3 Añadir la sección `[recuperacion]` de `config/sucursal.toml` (`k`, `peso_vectorial`, `peso_bm25`; los prefijos ya viven en `[embeddings]`) con validación de tipos y valores; verificar con pruebas de configuración inválida y con una prueba de contrato de que el recuperador real y el simulado satisfacen `Recuperador`.
- [x] 7.4 Documentar en `docs/MODELADO.md` el híbrido, el significado único de `puntaje` y cómo se eligen los pesos; verificar que el texto no promete normalizar BM25 y que el Arqueo puede variar los pesos desde configuración.

## 8. PR 6 — Prompt v2 y RAG (Anny — hecho)

- [x] 8.1 Crear `config/prompts/qa_v2.md` con frontmatter `version: v2`, `tarea: qa`, secciones `## Sistema` y `## Recordatorio`, `<fragmentos>` numerados con su `Fuente`, citas `[n]`, lista final `Fuentes:` y la regla de tratar los fragmentos como datos; verificar con `cargar_prompt("qa", "v2")` que el contrato de `prompts.py` se cumple y que `v0`/`v1` no cambian.
- [x] 8.2 Implementar `asistente/rag.py` con `formatear_fragmentos`, `validar_citas` y el adaptador `ContextoRag` que reutiliza las comprobaciones atómicas de `asistente.validacion` (frase fija, cifras inventadas, fuga, PII y tope de palabras); verificar con `FakeListChatModel` los casos cita válida, cita fuera de rango, fuente inventada, cifra inventada, fuga de prompt y PII.
- [x] 8.3 Añadir pruebas del prompt v2 y de la integración con `servicio`/`cli` sin red; verificar que `versiones_disponibles("qa")` incluye `v2` y que una respuesta sin cita cae en la frase fija con aviso.
- [x] 8.4 Documentar en `docs/EXPERIMENTOS_PROMPTS.md` la diferencia entre `qa_v1` (contexto completo) y `qa_v2` (fragmentos citados); verificar que el documento explica el formato `[n]`, la lista de fuentes y la validación posterior.

## 9. PR 7 — Tablero con tarifario y tablas web (Darley — pendiente)

- [x] 9.1 Crear `tablero/__init__.py`, `tablero/tipos.py` con la dataclass `Fila` y el escritor del CSV con las diez columnas en orden; verificar con una prueba que el encabezado es exacto, que el archivo es UTF-8 y que dos escrituras del mismo contenido son idénticas.
- [x] 9.2 Implementar `tablero/tarifas.py` con la máquina de estados de categoría y periodicidad, el patrón «concepto, valor y fecha» y la normalización de fecha a ISO; verificar con fixtures las líneas `Cuota de Manejo Tarjeta Débito $16.700 20-nov-25`, una con `+ IVA`, una con `+ Seguro2` y una sin fecha.
- [x] 9.3 Implementar `tablero/tablas_web.py` con el lector de tablas Markdown (pipes escapados incluidos) y adaptadores para asistencias de tarjetas, viajes nacionales, Cuota Protegida, promociones, asistencia vehicular y proyectos de vivienda; verificar con fixtures que se obtienen `USD 2.000`, `USD 10.000`, `EUR 20.000`, 30 días, 90 días, 200, 20 % y 407,027,630 con su fuente.
- [x] 9.4 Implementar `tablero/construir.py` para unir ambas fuentes, ordenar de forma determinista y escribir `data/estructurados/tablero.csv`; verificar que `make tablero` regenera el archivo sin red y que el cruce con las 8 preguntas de tabla da 8 de 8 o falla con el detalle de la pregunta sin fila.
- [x] 9.5 Implementar `buscar_filas` y `comparar_filas` como funciones puras, sin tildes ni mayúsculas en la comparación, sin modelo ni red; verificar con pruebas de búsqueda por concepto, comparación Visa/Mastercard, comparación con filas solo en un lado y búsqueda sin coincidencias.
- [x] 9.6 Documentar en `docs/MODELADO.md` el esquema del CSV, el origen `tarifario`/`tabla_web`, la trazabilidad `pagina`/`fuente` y la regla de no inventar valores; verificar que el documento coincide con `tablero/tipos.py` y con `make tablero`.

## 10. PR 8 — Digiturno (Darley — pendiente)

- [x] 10.1 Crear `sucursal/__init__.py`, `sucursal/tipos.py` con `Turno` y `sucursal/digiturno.py` con el orden de reglas: PII, fuera de alcance, tarifas/coberturas, duda y ruta por defecto; verificar con pruebas los cinco casos y que PII y fuera de alcance no llaman al modelo.
- [x] 10.2 Implementar la clasificación dudosa con DeepSeek a temperatura 0 y `json_mode`, esquema Pydantic `{letra, motivo}` y respaldo a `B` si la salida no es válida; verificar con `FakeListChatModel` una respuesta válida, un JSON roto y una letra desconocida, sin red.
- [x] 10.3 Añadir a `config/sucursal.toml` las palabras de tarifas y los patrones de fuera de alcance, y cargarlos con validación; verificar con pruebas que «¿cuál es el saldo de mi cuenta?» (pregunta 35) y las consultas de otro banco, clima, inversión y prompt caen en `X`, que «¿cómo abro mi cuenta de nómina?» no cae en `X` y sigue la ruta `B`, y que «cuota de manejo» cae en `T`.
- [x] 10.4 Verificar que el digiturno no persiste la pregunta ni datos personales y que el número de turno no se guarda en las SQLite; ejecutar `make check`.

## 11. PR 9 — Grafo con recuperador simulado (Darley — pendiente)

- [x] 11.1 Implementar `sucursal/grafo.py` con el `StateGraph` de nodos `reformular`, `digiturno`, `boveda`, `tablero`, `rechazo` y `redactar`, y compilarlo con `SqliteSaver` en `data/asistente/memoria.sqlite`; verificar con un recuperador simulado que cumple `Recuperador` y `FakeListChatModel` que el grafo responde de punta a punta sin red.
- [x] 11.2 Verificar el aislamiento por `thread_id` con dos conversaciones simultáneas y que el historial se recorta con `trim_messages` y `count_tokens_approximately` antes de llamar al modelo; comprobar que `data/asistente/memoria.sqlite` se crea fuera de Git.
- [x] 11.3 Implementar la reformulación condicionada: solo con historial y pregunta de seguimiento; verificar con pruebas que el primer turno no reformula, que «¿Y cuánto cuesta?» sí reformula y que una pregunta autónoma con historial no reformula.
- [x] 11.4 Implementar la respuesta del Tablero con plantilla sin modelo cuando hay de una a tres filas o más filas del mismo concepto (hasta diez) y paso a la Bóveda con turno `B` cuando hay cero, más de diez o varios conceptos; verificar con pruebas que en 1–3 filas `uso_modelo` es falso y el costo es cero, que las filas del mismo concepto también usan plantilla y que 0, 10+ o conceptos distintos no la usan.
- [x] 11.5 Verificar que el grafo rechaza PII antes de entrar en la memoria y que un fallo del modelo en `redactar` cae en la frase fija sin romper el hilo; ejecutar `make check`.

## 12. PR 10a — Servidor y servicios (Darley — pendiente)

- [x] 12.1 Implementar `sucursal/api.py` con `GET /api/estado`, `/api/tablero`, `/api/pipeline`, `/api/vestibulo`, `/api/arqueo` y `/api/boveda/mapa`, y los modelos Pydantic de respuesta; verificar con `TestClient` que cada endpoint devuelve la forma del contrato y que un archivo de arqueo ausente devuelve `disponible: false`.
- [x] 12.2 Implementar `sucursal/costo.py` con `tarifas_para(momento_utc)`, `GastoDiario` y `CacheRespuestas`; verificar con pruebas la hora valle, la hora pico, el tope alcanzado, la sobrescritura de `SUCURSAL_TOPE_USD` para la sesión, el acierto de caché, la clave por pregunta reformulada/ruta/versión y el TTL.
- [x] 12.3 Implementar el modo demo con `SUCURSAL_DEMO=1`: sin cliente DeepSeek, costo cero y sin escritura de gasto; verificar con pruebas que arranca sin `DEEPSEEK_API_KEY` y que `/api/estado` informa `modo_demo: true`.
- [x] 12.4 Verificar que `app.py` y `make app` levantan uvicorn solo en `127.0.0.1:8000`, que `config/sucursal.toml` no repite precios de DeepSeek y que el endpoint del mapa responde con un estado explicable cuando `data/boveda/mapa.json` aún no existe.
- [x] 12.5 Documentar en `README.md` el arranque de la app, las variables `DEEPSEEK_API_KEY`, `OLLAMA_HOST` y `SUCURSAL_DEMO`, y la dirección local; verificar que los comandos documentados funcionan tal cual.

## 13. PR 10b — Endpoint `preguntar` (Nayla — pendiente)

- [x] 13.1 Conectar `POST /api/preguntar` al grafo: validar `{pregunta, thread_id}`, invocar el grafo, mapear `Turno` y la respuesta al JSON del contrato y devolver los errores como `{error: {codigo, mensaje}}`; verificar con `TestClient` y un grafo simulado los casos 200, pregunta vacía, índice ausente y falta de clave fuera de demo.
- [x] 13.2 Integrar caché, gasto y métricas: devolver `cache: true` con costo cero en un acierto, sumar el gasto solo cuando hubo modelo y no cachear turnos `X`; verificar con pruebas que el segundo request de la misma pregunta no gasta y que un rechazo no escribe caché.
- [x] 13.3 Verificar que el endpoint no registra la pregunta ni datos personales en logs y que el `thread_id` no se usa como dato personal; ejecutar `make check` y una prueba de humo con `TestClient`.
- [x] 13.4 Actualizar el ejemplo de request/response en `README.md` y verificar que coincide con los modelos Pydantic y con `app/web/datos-ejemplo/preguntar.json`.

## 14. PR 11 — Mapa PCA (Yoldy — pendiente)

- [x] 14.1 Implementar `boveda/mapa.py` con `PCA(n_components=2)` sobre los vectores del índice, escritura de `data/boveda/mapa.json`, proyección de la pregunta con la misma transformación y normalización en el servidor de `x` e `y` a 0–100; verificar con `DeterministicFakeEmbedding` que hay un punto por fragmento, que todas las coordenadas están entre 0 y 100, que son finitas y que dos ejecuciones con los mismos vectores dan el mismo resultado.
- [x] 14.2 Integrar el mapa en `/api/boveda/mapa` y en `make indice`: regenerar `mapa.json` al indexar y calcularlo una vez si falta; verificar con `TestClient` que la respuesta trae puntos y pregunta normalizados entre 0 y 100, el top de fragmentos, y que sin pregunta `pregunta` es `null`.
- [x] 14.3 Verificar que el mapa es solo exploratorio y no interviene en la recuperación ni en el Arqueo; documentar esa limitación en `docs/MODELADO.md` y comprobar que ninguna prueba de recuperación depende de PCA.

## 15. PR 12 — Base del frontend (Yoldy — pendiente)

- [x] 15.1 Crear `app/web/index.html`, `app/web/estilos.css` y `app/web/app.js` con la navegación de la sucursal y los seis contenedores de vista; verificar que las seis vistas (`vestibulo`, `ventanilla`, `boveda`, `tablero`, `camara`, `arqueo`) se cargan y que no hay framework ni paso de build.
- [x] 15.2 Crear `app/web/datos-ejemplo/` con `estado.json`, `preguntar.json`, `tablero.json`, `mapa.json`, `pipeline.json`, `arqueo.json` y `vestibulo.json`; verificar con una prueba de forma contra los modelos Pydantic que campos y tipos coinciden.
- [x] 15.3 Implementar `app.py` para montar la API y los archivos de `app/web/`, y cambiar `make app` a `uv run python app.py`; verificar con `TestClient` que `/` sirve el HTML y que la escucha configurada es `127.0.0.1:8000`.
- [x] 15.4 Documentar en `README.md` la estructura de `app/web/`, el modo de datos de ejemplo y la diferencia entre abrir la maqueta y usar la API; verificar que las rutas documentadas existen.

## 16. PR 13 — Ventanilla (Nayla — pendiente)

- [x] 16.1 Implementar `app/web/vistas/ventanilla.js`: envía `{pregunta, thread_id}`, guarda el hilo en `sessionStorage` y muestra turno, número, ruta, motivo, reformulada, respuesta, fuentes, tokens, costo, tiempo y caché; verificar con la API real una primera pregunta y un seguimiento en el mismo hilo.
- [x] 16.2 Mostrar los estados de error y de índice ausente sin perder el hilo, y permitir reintentar; verificar apagando la API y volviendo a encenderla.
- [x] 16.3 Verificar que la vista no decide rutas, no calcula costos y no escribe preguntas en `localStorage`; revisar el archivo y la prueba de forma de `preguntar.json`.

## 17. PR 14 — Bóveda (vista) (Yoldy — pendiente)

- [x] 17.1 Implementar `app/web/vistas/boveda.js` con el mapa de puntos, la posición de la pregunta y la lista del top de fragmentos con título, sección, tipo y similitud; verificar con `mapa.json` y con la API una consulta real.
- [x] 17.2 Mostrar el estado «índice no listo» cuando la API lo informe y no dibujar un mapa vacío como si hubiera datos; verificar deteniendo el índice o apuntando a un directorio sin `data/boveda/`.
- [x] 17.3 Verificar que la vista no usa librerías externas ni hace peticiones distintas de `/api/boveda/mapa`; revisar el archivo y la red del navegador.

## 18. PR 15 — Tablero (vista) (Yoldy — pendiente)

- [x] 18.1 Implementar `app/web/vistas/tablero.js` con la tabla de filas, el filtro de texto y los enlaces a la fuente en otra pestaña; verificar con `tablero.json` y con `/api/tablero?q=cuota` que el filtro y las columnas coinciden con el CSV.
- [x] 18.2 Mostrar un estado vacío claro cuando no hay filas y no inventar valores; verificar con una búsqueda sin coincidencias.
- [x] 18.3 Verificar que la vista muestra concepto, valor, moneda, periodicidad, vigencia, origen y fuente, y que no recalcula ni compara filas en el navegador.

## 19. PR 16 — Cámara (Yoldy — pendiente)

- [x] 19.1 Implementar `app/web/vistas/camara.js` con las etapas de `panel.pipeline_summary`, sus métricas, avisos y la etapa de indexación; verificar con `pipeline.json` y con la API que se ven discover, fetch, extract, dedupe, gold e indexación.
- [x] 19.2 Mostrar los avisos de Bronze/Silver y el estado del índice sin confundirlos con errores; verificar con un `pipeline.json` sin índice y con otro con índice listo.

## 20. PR 17 — Vestíbulo (Yoldy — pendiente)

- [x] 20.1 Implementar `app/web/vistas/vestibulo.js` con los hitos de `config/vestibulo.toml` (año, texto, URL) y una entrada clara a la Ventanilla; verificar con `vestibulo.json` y con la API que los hitos coinciden con el TOML.
- [x] 20.2 Verificar que el vestíbulo funciona sin clave ni índice, porque es la pantalla de bienvenida, y que no hace llamadas al modelo.

## 21. PR 18 — Arqueo (vista) (Anny — hecho)

- [x] 21.1 Implementar `app/web/vistas/arqueo.js` con hit@5, MRR, exactitud, citas correctas, costo y el resultado de McNemar; verificar con `arqueo.json` de ejemplo y, cuando exista el reporte real, con `/api/arqueo` que las cifras coinciden.
- [x] 21.2 Mostrar el estado «sin arqueo» cuando `disponible` es falso y no presentar métricas vacías como resultados; verificar sin `data/evaluacion/arqueo.json`.
- [x] 21.3 Verificar que la vista distingue recuperación, evaluación v1/v2 y costo, y que no recalcula métricas en el navegador.

## 22. Experimentos del Arqueo (Anny — en curso)

- [x] 22.1 Implementar en `arqueo/experimentos.py` el cargador de las 44 preguntas con `tipo`, `ruta_esperada`, `fuentes_esperadas` y `previa`, sin romper el cargador de v1; verificar con pruebas los conteos 20/12/6/6, los campos obligatorios y una pregunta de seguimiento sin `previa` que debe fallar.
- [x] 22.2 Implementar el barrido de recuperación con los pesos `1/0`, `0/1`, `0.2/0.8`, `0.4/0.6`, `0.6/0.4` y `0.8/0.2`, sin reindexar al cambiar pesos, calculando `hit_at_k(k=5)` y `mrr(k=5)` con `arqueo/metricas.py`; para los prefijos, construir un único índice sin prefijos en `data/boveda/experimentos/sin_prefijos` y medirlo con los pesos por defecto. Verificar con `DeterministicFakeEmbedding` y un corpus mínimo que no hay llamadas a DeepSeek y que las dos líneas base aparecen en el reporte.
- [x] 22.3 Implementar `evaluar_v2` para `make evaluar VERSION=v2`: envía la `previa` en el mismo `thread_id` antes de la pregunta de seguimiento y escribe `data/evaluacion/resultados_v2.jsonl` y `docs/RESULTADOS_FASE2.md` sin sobrescribir v1; verificar con un grafo simulado que el hilo y el orden de los mensajes son correctos.
- [x] 22.4 Integrar McNemar sobre las 20 preguntas de alcance con `revision_humana.toml` y `revision_humana_v2.toml`, creando esta última con la revisión de las respuestas v2; convertir veredictos a aciertos y excluir los pares sin revisión; verificar con fixtures los casos `b`, `c`, empate y revisión faltante. Código y pruebas en el PR de la A4; `revision_humana_v2.toml` con la revisión humana de v2 en el PR de la A6.
- [x] 22.5 Escribir `data/evaluacion/arqueo.json` y `docs/ARQUEO.md` sin fecha ni rutas absolutas, con recuperación, evaluación, McNemar, costo y conteo por tipo; verificar que dos ejecuciones con los mismos datos son idénticas y que las cifras del Markdown coinciden con el JSON.
- [x] 22.6 Añadir `make arqueo` y verificar que funciona sin `DEEPSEEK_API_KEY`, que no está encadenado a `all`, `gold` ni `deliver`, y que `make help` lo lista; documentar el comando y la interpretación del reporte en `docs/ARQUEO.md`.

## 23. Retiro de Streamlit (Darley — hecho)

- [x] 23.1 Eliminar `app/streamlit_app.py`, `app/scraping_ui.py` y la dependencia `streamlit` con `uv remove streamlit`; verificar que `make check` y `make demo` pasan sin Streamlit instalado y que `make app` sigue levantando uvicorn.
- [x] 23.2 Actualizar `CONSTITUTION.md` §3 y §4, `AGENTS.md` (mapa del código y comandos), `README.md` y `docs/ESTANDAR.md` para quitar Streamlit y describir la app web; verificar que no quedan referencias activas con una búsqueda de «streamlit» en código, `pyproject.toml`, Makefile y documentación.
- [x] 23.3 Verificar que el retiro no borra `app/web/`, `app.py`, los datos de ejemplo ni la API, y que `git status` no incluye `data/asistente/` ni `data/boveda/`.

## 24. Skill boveda-rag (Nayla — pendiente)

- [x] 24.1 Crear `.opencode/skills/boveda-rag/SKILL.md` con frontmatter, propósito, cuándo usarla y el flujo para construir el índice, consultar, diagnosticar Ollama/Chroma y revisar citas; verificar que la skill se carga y que sus comandos coinciden con `make indice`, `make arqueo` y `make app`.
- [x] 24.2 Añadir la skill a la tabla de `.opencode/skills/` en `AGENTS.md` y a la documentación de skills; verificar que el enlace y el nombre son correctos y que no duplica las reglas de `corpus-extraction` ni `semantic-extraction`.
- [x] 24.3 Documentar en la skill las reglas de seguridad: fragmentos como datos, sin PII, índice no versionado, servidor solo local y pruebas sin red; verificar que cada regla apunta al archivo o comando que la hace cumplir.

## 25. Seguridad y reglas de GGA (Nayla — hecho)

- [x] 25.1 Actualizar la sección GGA de `AGENTS.md` con los rechazos nuevos: índice vectorial versionado, servidor en `0.0.0.0`, precios de DeepSeek duplicados fuera de `arqueo/metricas.py`, fragmentos tratados como instrucciones, caché con PII y pruebas que llaman a Ollama o DeepSeek; verificar que cada regla se puede comprobar con un archivo o comando.
- [x] 25.2 Añadir pruebas de seguridad: que el servidor no acepta host público, que no se lee `.env`, que no hay claves en el código, que PII no entra en caché ni memoria y que los fragmentos con instrucciones no cambian el sistema; ejecutar `make check`.
- [x] 25.3 Escribir `docs/SEGURIDAD.md` con el modelo de amenazas (inyección en fragmentos, PII, abuso de costo, exposición del servidor, índice con datos personales) y su mitigación concreta; verificar que cada mitigación referencia una prueba o una regla de GGA.

## 26. Diagramas con Archify (Darley — hecho)

- [x] 26.1 Generar con Archify el diagrama de arquitectura: navegador → FastAPI → grafo → Bóveda/Tablero → SQLite, con Ollama local y DeepSeek como servicio externo; verificar que el diagrama se renderiza y que el comando queda documentado en `README.md`.
- [x] 26.2 Generar con Archify el diagrama de datos: Gold → chunks → fragmentos → embeddings → Chroma → recuperación → respuesta citada, y Tablero PDF/tablas → CSV → respuesta con plantilla; verificar que las rutas y los sentidos de las flechas coinciden con el diseño.
- [x] 26.3 Añadir los diagramas al `README.md` y a `docs/MODELADO.md`, y verificar que no prometen componentes fuera de alcance (Extracto, time travel, EmbeddingGemma, Matryoshka).

## 27. Integración y cierre (equipo — pendiente)

- [x] 27.1 Ejecutar `make fmt`, `make check`, `make demo` y `make health`; verificar que lint, tipos, pruebas y pipeline offline pasan al 100 % y que no hay dependencias de red en la suite.
- [x] 27.2 Ejecutar `make indice`, `make tablero` y `make arqueo` sobre el corpus real; verificar el conteo de fragmentos, las 12 de 12 preguntas de tabla y que `arqueo.json` y `ARQUEO.md` se generan sin llamar a DeepSeek.
- [x] 27.3 Arrancar `make app` y recorrer las seis vistas; verificar `/api/estado`, `/api/preguntar` con una pregunta de alcance y una de seguimiento, `/api/tablero`, `/api/boveda/mapa`, `/api/pipeline`, `/api/arqueo` y `/api/vestibulo` contra el contrato.
- [x] 27.4 Ejecutar `make evaluar VERSION=v2` con una pregunta de humo y verificar que usa el grafo, que las preguntas de seguimiento envían la previa en el mismo hilo, que los resultados van a los archivos de v2 y que v1 no se sobrescribe.
- [x] 27.5 Revisar `git status` y el diff final: sin `data/boveda/`, sin SQLite de `data/asistente/`, sin `.env`, sin claves, sin cambios en `data/raw/` ni en `data/gold/`, y sin Streamlit; confirmar que `CONSTITUTION.md`, `AGENTS.md` y `docs/ESTANDAR.md` describen el estado final.

## Workflow follow-up

- Archivar el cambio cuando la revisión del proyecto esté satisfecha y los 18 PR del plan estén fusionados.
- Verificar que las specs principales `boveda-rag`, `tablero-tarifas`, `sucursal-agente`, `sucursal-frontend` y `arqueo-evaluacion` quedaron creadas con su Purpose.
- Confirmar que el reporte `docs/ARQUEO.md` conserva las cifras del corpus y del set de 44 preguntas revisado.
