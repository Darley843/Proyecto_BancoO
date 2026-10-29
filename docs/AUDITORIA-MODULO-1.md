# Auditoría del Módulo 1 — Base de conocimiento semántico y Q&A

**Empresa:** Banco de Occidente
**Insumo auditado:** `Actividad del Módulo 1.docx` (Creación de la Base de Conocimiento Semántico y Sistema Q&A)
**Fecha de la auditoría:** 2026-10-29
**Método:** revisión del repositorio (`docs/`, `src/`, `app/`, `config/`, `data/`) y ejecución de `make health` y `make check`.

> Esta auditoría compara lo que pide la actividad con lo que existe hoy en el
> repositorio. Los estados son: **Cumple**, **Parcial**, **Falta** y
> **No verificable desde el repo**. La nota proyectada al final es una
> estimación del auditor, no una nota oficial.

## 1. Veredicto general

El proyecto **cumple el núcleo técnico de la actividad** y lo supera en varios
puntos (trazabilidad Bronze/Silver/Gold, validación anti-alucinación, pruebas
automatizadas, respeto de `robots.txt`). Lo que falta no es pipeline: es
**empaquetar el entregable escrito y la demostración**.

| Bloque de la actividad | Estado | Comentario |
|---|---|---|
| 1. Investigación y alcance | **Cumple** con una salvedad | Redes sociales identificadas pero no capturadas (decisión documentada) |
| 2. Base de conocimiento (scraping, limpieza, chunking) | **Cumple** | 181 páginas + 190 PDF + 32 videos; 1 388 chunks web; contexto consolidado |
| 3. Aplicativo (modelo, LangChain, prompt) | **Cumple** con una decisión por confirmar | DeepSeek Flash por API en lugar de Ollama/OpenAI literal |
| 4. Interfaz de prueba | **Cumple** | Streamlit con 4 pestañas y las tres tareas |
| 5. Pruebas y documentación | **Parcial** | 20 preguntas hechas; **no existe el informe consolidado ni el guion de la demo** |

## 2. Checklist punto por punto de la actividad

### 2.1 Asignación de empresa y análisis inicial (15 %)

| # | Requisito | Estado | Evidencia en el repo | Brecha / acción |
|---|---|---|---|---|
| 1.1 | Empresa del Top 50 asignada e identificada | Cumple | `README.md`, `docs/FUENTES.md`, todo el corpus es de Banco de Occidente | — |
| 1.2 | Investigación del sitio oficial ("Quiénes somos", productos, sostenibilidad, informes, noticias) | Cumple | 181 páginas web, 190 PDF, 32 videos; `docs/FUENTES.md` con inventario y reglas | — |
| 1.3 | Perfiles en redes sociales (LinkedIn, Instagram, Facebook…) | Parcial | `docs/ALCANCE.md`: identificadas y **no capturadas** porque sus términos prohíben el scraping | Llevar la justificación al informe y, si se quiere cubrir, curar a mano 3–5 publicaciones públicas citando fecha y URL |
| 1.4 | Apariciones en medios locales y nacionales | Cumple | 20 fichas de prensa curada (Portafolio, La República, El Tiempo, El Colombiano, Valora, Forbes, CAF) en `data/gold/pages` | — |
| 1.5 | Definición del alcance: qué preguntas debe responder un cliente nuevo | Cumple | `docs/ALCANCE.md`: 20 preguntas con cobertura esperada (sí / parcial / no) y "fuera del alcance" | — |

### 2.2 Construcción de la base de conocimiento semántico (25 %)

| # | Requisito | Estado | Evidencia en el repo | Brecha / acción |
|---|---|---|---|---|
| 2.1 | Web scraping con librerías de Python | Cumple | `discover.py` (robots + sitemap), `net.py`, `fetch.py`; extracción con `trafilatura` y respaldo BeautifulSoup | — |
| 2.2 | Limpieza del HTML | Cumple | `extract.py` (Silver) + `dedupe.py` (boilerplate) + Gold con frontmatter | — |
| 2.3 | Segmentación (chunking) semánticamente coherente | Cumple | `make chunks`: 1 388 chunks web y 14 279 con PDF y videos; corte por `##`, mínimo 40 caracteres, `chunk_id` estable, metadatos `url/section/heading` | Ver 2.6 |
| 2.4 | Base de conocimiento entregada en el repositorio | Cumple | `data/gold/` (241 documentos versionados), `data/knowledge/chunks_web.jsonl`, `data/contexto/` | — |
| 2.5 | Consolidación en un **archivo de texto limpio** | Cumple | `data/contexto/contexto_banco.md`: 166 647 de 175 000 tokens, 191 documentos | — |
| 2.6 | Calidad de los chunks | Parcial | `MODELADO.md` §2 documenta que algunos chunks arrancan con restos de menú ("Canales digitales / Segmentos / Mesa de dinero") | Aplicar el detector de líneas comunes de la capa Contexto antes de indexar (queda para el Módulo 2) |
| 2.7 | Todo lo capturado entra al conocimiento | Parcial | 191 de 241 documentos en el contexto; el presupuesto deja fuera 50 y todos los PDF y videos | Explicarlo como límite del Módulo 1 (el Módulo 2 lo resuelve con recuperación) |
| 2.8 | Capa semántica de entidades, hechos y relaciones | Parcial | `data/knowledge/`: **2 entidades, 6 hechos, 1 relación**, 7 pendientes de revisión, confianza media 0,949; `make health` OK | Es una semilla validada. Ampliarla (contacto, productos, sedes, directivos) o declarar en el informe que la base semántica del Módulo 1 es Gold + contexto y esto es un prototipo |
| 2.9 | Sin datos personales, login ni formularios | Cumple | `config/site.toml` excluye formularios y `/portaltransaccional`; `docs/FUENTES.md` lo justifica | — |

### 2.3 Construcción del aplicativo (25 %)

| # | Requisito | Estado | Evidencia en el repo | Brecha / acción |
|---|---|---|---|---|
| 3.1 | Elección de modelo (Ollama o API privada) | Cumple con salvedad | DeepSeek Flash (`deepseek-flash`) vía `langchain-deepseek`, `asistente/modelo.py` | `MODELADO.md` deja "pendiente confirmar con el profesor". Cerrar esa decisión antes de la sustentación y tener un plan B (Ollama) si el docente lo exige |
| 3.2 | Framework de LLM (LangChain o LlamaIndex) | Cumple | LangChain (`ChatDeepSeek`, runnables, salida estructurada) | — |
| 3.3 | **Tres tareas: Resumen, FAQ y Q&A** | Cumple | `asistente/resumen.py`, `asistente/faq.py`, `asistente/qa.py`; prompts `resumen_v1`, `faq_v1`, `qa_v1` | — |
| 3.4 | Consolidar el texto limpio en el prompt de sistema | Cumple | `contexto_banco.md` va completo en el mensaje de sistema | — |
| 3.5 | Prompt robusto: responder solo con el contexto | Cumple | `config/prompts/qa_v1.md`, reglas 1–9 | — |
| 3.6 | Instrucciones para evitar alucinaciones | Cumple | Frase fija si no hay dato, cita obligatoria, y validación posterior (`asistente/validacion.py`) que reemplaza respuestas sin URL, con cifras inventadas o con PII | — |
| 3.7 | Experimentación con prompts (zero-shot, formato) | Cumple | `qa_v0` (línea base sin reglas) vs `qa_v1`; `docs/EXPERIMENTOS_PROMPTS.md` con pruebas reales y métricas de tokens/caché | — |
| 3.8 | Prompt versionado | Cumple | `config/prompts/*.md` con frontmatter (`version`, `tarea`, `fecha`) | — |
| 3.9 | Streamlit/Gradio con campo de pregunta y área de respuesta | Cumple | `app.py` → `app/streamlit_app.py`, 4 pestañas | — |
| 3.10 | Las tres funcionalidades visibles en la app | Cumple | Pestañas Preguntas, Preguntas frecuentes (10) y Resumen ejecutivo, más Scraping | — |
| 3.11 | App funcional sin clave de API | Parcial | Hay captura `docs/capturas/app-sin-clave.png` y degradación controlada | Verificarlo en el ensayo de la demo |
| 3.12 | Código limpio y bien organizado | Cumple | 309 pruebas, `ruff` y `ty` en verde, CI, módulos con responsabilidad única, `make check` | — |

### 2.4 Pruebas, documentación y presentación (20 %)

| # | Requisito | Estado | Evidencia en el repo | Brecha / acción |
|---|---|---|---|---|
| 5.1 | Al menos 20 preguntas del alcance | Cumple | `config/evaluacion/preguntas_alcance.toml` (20) y `make evaluar` | — |
| 5.2 | Evaluar precisión y coherencia | Cumple | `docs/RESULTADOS_20_PREGUNTAS.md`: 19 correctas + 1 rechazo correcto (automático); revisión humana 15 correctas, 3 parciales, 1 incorrecta, 1 rechazo correcto | Ver brecha P0-2 (pregunta 14) |
| 5.3 | Ejemplos de preguntas y respuestas | Cumple | Las 20 respuestas completas en `RESULTADOS_20_PREGUNTAS.md` | — |
| 5.4 | Discusión de limitaciones | Cumple | Contexto al tope, una sola fuente por respuesta, cifras mal emparejadas | Llevarlas al informe, no solo a `EXPERIMENTOS_PROMPTS.md` |
| 5.5 | **Informe con las 5 secciones** (problema, solución, datos, modelado, resultados) | **Falta** | El material existe disperso en 8 documentos + README, pero **no hay un informe consolidado** | **Crear `docs/INFORME-MODULO-1.md`** (o PDF) que integre y cite los anexos |
| 5.6 | Presentación en vivo de 15 min, sin PowerPoint, con demo | **Falta** | App lista y 11 capturas en `docs/capturas/` | Escribir guion de 15 min con reparto por integrante y plan de contingencia (sin red / sin clave / 403) |

## 3. Checklist de la rúbrica

| Criterio | Peso | Qué pide | Evidencia | Proyección |
|---|---:|---|---|---:|
| Análisis de la empresa y estrategia de datos | 15 % | Investigación clara + alcance + calidad de los datos | `ALCANCE.md`, `FUENTES.md`, 241 documentos Gold | 13/15 |
| Procesamiento de datos y tareas LLM | 25 % | Consolidación en archivo limpio + Resumen, FAQ y Q&A con LangChain | `contexto_banco.md`, tres módulos de tarea, LangChain | 24/25 |
| Prompt Engineering | 25 % | Eficacia, contexto, anti-alucinación, documentación de experimentos | `qa_v1`, `qa_v0`, `validacion.py`, `EXPERIMENTOS_PROMPTS.md` | 23/25 |
| Implementación y calidad de la app | 15 % | Dashboard funcional y presentado, tres funcionalidades, código limpio | 4 pestañas, 309 pruebas, CI verde | 14/15 |
| Documentación escrita | 10 % | Informe claro y con profundidad técnica | **No hay informe consolidado** | 4/10 |
| Presentación oral y demo | 10 % | Claridad de arquitectura + demo fluida | App y capturas; **sin guion** | 7/10 |
| **Total estimado** | **100 %** | | | **85/100** |

El techo real hoy es la documentación escrita: con el informe consolidado y un
ensayo de la demo, la proyección sube a ~93/100 sin tocar el pipeline.

## 4. Brechas priorizadas

### P0 — bloquean nota o sustentación

- [ ] **Informe consolidado.** Un solo documento con: descripción del problema, planteamiento de la solución (RAG como núcleo), preparación de los datos (scraping, limpieza, chunking), modelado (embeddings, LLM del Módulo 2, base vectorial, diseño del prompt) y resultados (tabla de las 20 preguntas, calidad, limitaciones). Fuente: `README.md`, `ALCANCE.md`, `FUENTES.md`, `ESTANDAR.md` §1/§3/§7, `MODELADO.md`, `EXPERIMENTOS_PROMPTS.md`, `RESULTADOS_20_PREGUNTAS.md`.
- [ ] **Pregunta 14 (CDT) marcada "incorrecta".** La respuesta dice "$500.000 con plazo mínimo de 30 días" y la fuente dice "$500.000 desde 90 días y $1.000.000 desde 30". Opciones: (a) corregir la validación para que cada monto se empareje con su plazo, (b) regenerar solo esa respuesta y volver a revisarla, o (c) dejarla como limitación explícita en la sección de resultados. Para la nota conviene (a) o (b): una respuesta incorrecta en el entregable pesa más que la explicación.
- [ ] **Guion de la demo (15 min).** Reparto por integrante, orden de pestañas, 5 preguntas de respaldo, qué hacer si falla la red, la clave o el WAF (403), y qué decir cuando el corpus no tiene el dato (la frase fija es una fortaleza, no un fallo).

### P1 — mejoran la nota con poco esfuerzo

- [ ] **Cerrar la decisión del modelo.** Pasar de "pendiente confirmar con el profesor" a "se eligió DeepSeek Flash por X, Y, Z" con comparación frente a Ollama y OpenAI/Gemini (costo, privacidad, latencia, calidad en español).
- [ ] **Ampliar o encuadrar la capa Knowledge.** Con 2 entidades y 6 hechos se lee como prototipo. Ampliarla a ~15–20 entidades y ~30 hechos (contacto, líneas, productos, sedes, directivos, filiales) o declarar en el informe que la base semántica del Módulo 1 es Gold + contexto consolidado.
- [ ] **Actualizar cifras obsoletas en la documentación.** `MODELADO.md` dice 14 490 chunks, el archivo real tiene 14 279. El contexto es 166 647 tokens (no 167 057). Un revisor que cuente encontrará la diferencia.
- [ ] **Regenerar el entregable.** `dist/corpus-gold-2026-10-23.zip` es anterior al contexto de noticias y al de hoy: correr `make deliver` antes de subir.
- [ ] **Justificar la exclusión de redes sociales** con la política de redes que ya está en Gold (`/legal-politicas/redes-sociales`) y, si se puede, curar 3–5 publicaciones públicas a mano.

### P2 — Módulo 2 o pulido

- [ ] Filtrar restos de menú en los chunks antes de indexar.
- [ ] Añadir al informe la comparación de costo/tokens por pregunta (187 k de entrada) y por qué el Módulo 2 la reduce.
- [ ] Incluir en el informe la captura de la app en cada pestaña (`docs/capturas/`).
- [ ] Revisar los 7 hechos de Knowledge que siguen en `review: pending`.

## 5. Riesgos para la sustentación

| Riesgo | Impacto | Mitigación |
|---|---|---|
| El docente espera Ollama u OpenAI literal | Medio | Argumentar la elección y ofrecer demo con Ollama si lo pide |
| La app depende de `DEEPSEEK_API_KEY` y de red | Alto en vivo | Ensayo previo, capturas de respaldo, y `make demo` (sin red) como plan B |
| El sitio responde 403 por WAF | Medio | Ya está documentado; mostrar Gold versionado y explicar que el pipeline se detiene sin evadir |
| Preguntar algo fuera del alcance en vivo | Bajo (es una fortaleza) | Guion: usar la pregunta 1 (horario) para mostrar el rechazo correcto con canal oficial |
| 187 k tokens por pregunta parecen ineficientes | Bajo | Explicar la caché (>99 %) y que el Módulo 2 introduce recuperación |

## 6. Lo que no se puede verificar desde el repo

- Que la app responda en vivo con la clave del equipo (no hay clave en el repo, correcto).
- La calidad de la sustentación y el reparto del trabajo entre los 4 integrantes.
- Que el grupo haya hecho la investigación de redes sociales más allá de identificarlas.

## 7. Evidencia de la auditoría

```
make health  -> URLs 196 | Bronze 193 | Silver 193 | Gold 241 | PDF 190 | Videos 32
                Knowledge 2 entidades, 6 hechos, 1 relación | RESULTADO: OK
make check   -> ruff OK | ty OK | 309 passed
Conteos      -> chunks_web.jsonl 1 388 líneas | chunks.jsonl 14 279 líneas
Contexto     -> 166 647 / 175 000 tokens | 241 leídas, 191 incluidas, 50 excluidas
Evaluación   -> 20 preguntas | automático 19 correctas + 1 rechazo correcto
                humano 15 correctas, 3 parciales, 1 incorrecta, 1 rechazo correcto
```
