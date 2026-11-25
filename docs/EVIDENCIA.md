# Evidencia para la rúbrica

Tabla de evidencia de la entrega final (tarea 3.7 de `agente-openclaw`). Cada
fila dice qué se afirma, con qué comando se comprueba, en qué archivo está y qué
resultado dio. Sirve para la discusión técnica: quien defiende un ítem abre el
archivo o corre el comando en vivo.

Cada sección la completa quien es responsable del ítem. Las filas con **⏳**
esperan una pieza que todavía no está en `main`; el número de PR indica dónde
está mientras tanto.

## 2.2 RAG sobre Qdrant (6 %) — Anny

| Qué se afirma | Cómo se comprueba | Dónde | Resultado |
|---|---|---|---|
| La Bóveda es un índice vectorial en Qdrant local, sin servidor aparte | `make indice` | `src/banco_occidente_corpus/boveda/indice.py`, `boveda/almacen.py`, `data/boveda/` (no versionado) | 869 fragmentos, `nomic-embed-text-v2-moe`, 768 dimensiones, con prefijos de consulta y documento |
| La búsqueda es híbrida: vectores para el sentido y BM25 para nombres exactos | `uv run pytest test/test_mcp_servidor.py` | `boveda/recuperador.py` (`EnsembleRetriever`) | Pesos por defecto 0,6 vectorial y 0,4 BM25; si Ollama falla, cae a BM25 y lo declara |
| Cada respuesta cita el documento y el fragmento | `uv run pytest test/test_mcp_conocimiento.py` | `mcp_servidor/conocimiento.py` (`buscar_en_documentos`, #198) | Cada fragmento vuelve con título, URL, posición, puntaje y una cita «Título — URL»; sin coincidencias no inventa |
| Los fragmentos son datos, no instrucciones | `uv run pytest test/test_inyeccion.py` | `mcp_servidor/servidor.py` (`AVISO_DATOS`), `test/test_inyeccion.py` (#200) | Un fragmento envenenado viaja como dato y su eco no pasa el auditor |

## 2.3 Evaluación del conocimiento (4 % y bonus) — Anny

| Qué se afirma | Cómo se comprueba | Dónde | Resultado |
|---|---|---|---|
| La recuperación se mide con preguntas cuya fuente se conoce | `make arqueo` | `docs/ARQUEO.md`, `data/evaluacion/arqueo.json`, `config/evaluacion/preguntas_fase2.toml` | 36 preguntas con fuente: 22 de la Bóveda y 14 del Tablero |
| hit@5 y su incertidumbre | `make arqueo` | `docs/ARQUEO.md` («Recuperación por configuración») | 0,75 (27 de 36), Wilson 95 % de 0,59 a 0,86; MRR 0,58 |
| recall@10 y nDCG@10 | `make arqueo` | `docs/ARQUEO.md`, `arqueo/metricas.py` | recall@10 0,82 y nDCG@10 0,64 con los pesos por defecto; sin las preguntas del Tablero, 0,71 y 0,52 |
| El híbrido mejora a BM25 solo | `make arqueo` | `docs/ARQUEO.md` | hit@5 0,75 frente a 0,53 con BM25 solo (0/1) |
| Proyección t-SNE de los embeddings, con su lectura | `uv run python -m banco_occidente_corpus.arqueo.proyeccion` | `docs/PROYECCION.md`, `docs/img/proyeccion_tsne.svg`, `data/evaluacion/proyeccion.json` (#193) | Confiabilidad 0,95; pureza de vecindario 0,66 (al azar, 0,22); los 9 fallos se explican en 4 causas |
| La t-SNE es reproducible | `uv run pytest test/test_arqueo_proyeccion.py` | `arqueo/proyeccion.py` (#193) | Semilla 1965, inicio PCA y coseno; la misma semilla da las mismas coordenadas |
| Evaluación de respuestas, v1 frente a v2 | `make arqueo` | `docs/ARQUEO.md` («Evaluación v1 y v2», «McNemar») | v1 acierta 16 de 20 y v2 11 de 20; McNemar p = 0,0625: con 5 pares discordantes ninguna diferencia podría ser significativa |
| Filtro de dominio | `make arqueo` | `docs/ARQUEO.md` («Filtro de dominio»), `data/evaluacion/filtro_dominio.jsonl` | Con el modelo, 0 de 50 preguntas fuera de tema se cuelan en tres corridas; las reglas solas deciden el 22,8 % de los casos, sin errores |

## 1.1 Function calling: herramientas 17 a 20 — Anny

| Herramienta | Qué hace | Dónde | Pruebas |
|---|---|---|---|
| 17 `buscar_en_documentos` | Fragmentos de la Bóveda citados | `mcp_servidor/conocimiento.py` (#198) | `test/test_mcp_conocimiento.py` (31, con la 18) |
| 18 `consultar_tarifas` | Tarifas y tasas del Tablero; si la pregunta no nombra producto, pide cuál y lista los rangos | `mcp_servidor/conocimiento.py` (#198) | Incluye el hallazgo de «Tasas» con el Tablero real |
| 19 `clasificar_pregunta` | Ruta del Digiturno y herramienta sugerida | `mcp_servidor/control.py` (#199) | `test/test_mcp_control.py` (35, con la 20) |
| 20 `auditar_respuesta` | Veredicto sin colores antes de enviar; `permite_enviar` | `mcp_servidor/control.py` (#199) | Cifras, fuentes, promesas, gota a gota, datos personales y fuga de instrucciones |

Las cuatro reciben `<Nombre>Entrada` y devuelven `<Nombre>Salida` o el sobre
`{"ok": false, "codigo", "mensaje"}`, con `extra="forbid"`. Son de solo lectura,
deterministas y no llaman a DeepSeek.

Límite conocido: sin modelo, `clasificar_pregunta` solo decide lo que cubren las
reglas (el 22,8 % del conjunto del filtro de dominio); una duda va a la Bóveda.
En el agente, el resto lo decide el modelo con las reglas de `AGENTS.md`.

## 4.2 Seguridad: inyección y auditoría — Anny (con Nayla)

| Qué se afirma | Cómo se comprueba | Dónde | Resultado |
|---|---|---|---|
| El auditor de la escena es código, no un prompt | `uv run pytest test/test_escena_auditor.py` | `escena/auditor.py`, `diagnostico/comite.py` (`auditar_texto`, `negada_antes`) | Seis reglas altas y cinco medias; veredicto conforme, con observaciones u objeta, sin colores |
| «Sin duda está aprobado» no pasa | `uv run pytest test/test_escena_auditor.py` | `test/test_escena_auditor.py` | La negación vale solo de forma inmediata, en la misma cláusula; «sin duda» y «no solo» no niegan |
| Catálogo de inyección directa e indirecta | `uv run pytest test/test_inyeccion.py` | `config/evaluacion/inyeccion.toml`, `arqueo/inyeccion.py`, `docs/INYECCION.md` (#200) | 15 ataques (11 directos y 4 indirectos); 49 pruebas de las tres capas: Digiturno, herramientas y auditor |
| ⏳ El agente real resiste la inyección | Corrida del miércoles con el gateway | `docs/INYECCION.md` («Resultados»), `data/evaluacion/inyeccion.json` | Pendiente |

## 3.6 Invitados — Anny y Darley

| Qué se afirma | Cómo se comprueba | Dónde | Resultado |
|---|---|---|---|
| ⏳ Un invitado no registrado entra solo con consentimiento y dentro de la ventana | Prueba conjunta del miércoles | `canal/modo_evento.py`, `test/test_canal_modo_evento.py` | Pendiente |
| ⏳ No se guardan números ni nombres y el tope por huella no se salta reiniciando | Prueba conjunta del miércoles | Base del canal y registros | Pendiente |

## Ítems de Nayla — 24 de noviembre de 2026

Todo lo de esta sección se comprobó el 24 de noviembre de 2026 con el gateway
en WSL y el MCP en `127.0.0.1:8765`.

| Qué se afirma | Cómo se comprueba | Dónde | Resultado |
|---|---|---|---|
| El router elige la herramienta según la pregunta y no busca cuando lo saludan | `make traza` | Traza de `sucursal` en `data/asistente/trazas/herramientas.jsonl` (local, no versionada), `herramientas/traza.py` | «¿Cuál es la tasa de un CDT a 360 días por 10 millones?» llamó `sucursal__consultar_tasa`; «Hola, buenas tardes» no llamó ninguna herramienta |
| La memoria por capas conserva el hilo por huella aunque se reinicie el gateway | Petición a la API con `user: "wa:huella-prueba-memoria"` y reinicio del gateway | `openclaw/workspace/pana/MEMORY.md.example`, `memory/AAAA-MM-DD.md.example` (locales y en `.gitignore`); traza de las llamadas en `data/asistente/trazas/herramientas.jsonl` (local, no versionada) | Después del reinicio el agente recordó el personaje (Lucía y su moto); `MEMORY.md` y la bitácora son locales y sin datos de invitados |
| El gateway escucha solo en loopback, exige token y declara modelo principal y alternativo | Revisión del archivo versionado y `diff` contra la configuración de WSL | `openclaw/openclaw.json` (#190 y #189) | Copia versionada sin secretos (`${OPENCLAW_GATEWAY_TOKEN}`), `bind: "loopback"`, `deepseek/deepseek-flash` con alternativo `deepseek/deepseek-v4-pro` |
| El workspace define a Pana y respeta los límites del proyecto | Tres preguntas al agente (proyecto, aprobación y configuración) | `openclaw/workspace/pana/` (`SOUL.md`, `AGENTS.md`, `USER.md`, `IDENTITY.md`), #190 | Se presenta como proyecto académico, no promete aprobaciones y no revela su configuración |
| El gateway ve las 20 herramientas y solo esas | `openclaw mcp doctor sucursal --probe` (con el gateway apagado) | `openclaw/openclaw.json` (`mcp.servers.sucursal.toolFilter`), `mcp_servidor/agente.py` (#189 y #208) | `sucursal: ok` y la lista cerrada de 20 herramientas |
| La auditoría del gateway queda sin críticas y las herramientas peligrosas están bloqueadas | `openclaw security audit` | `openclaw/README.md` («Auditoría de seguridad»), `openclaw/openclaw.json` (`agents.entries.pana.tools.deny`, `tools.fs.workspaceOnly`), #209 | De 7 a 2 advertencias y 0 críticas; las herramientas peligrosas quedan bloqueadas, `exec.security: deny` no rompe el MCP y las sesiones están aisladas entre agentes |

## Ítems del resto del equipo

| Ítem | Responsable | Qué falta documentar aquí |
|---|---|---|
| 1.1 Herramientas 1 a 16 | Nayla y Darley | ⏳ Archivo, pruebas y PR de cada herramienta |
| 2.1 Pipeline del M1 | Todos | ⏳ Comando que reconstruye el corpus y conserva la fuente |
| 3.2 WhatsApp en producción | Darley | ⏳ SIM real en Meta, modo evento y prueba desde tres teléfonos |
| 4.1 Código y pruebas | Todos | `make check` en verde: 2534 pruebas en main (sin red, sin DeepSeek y sin Ollama) |
| 4.3 Documentación | Yoldy | README, `docs/DESPLIEGUE.md` (#191), `docs/DIAGRAMAS.md` (#192), LICENSE MIT (#194) |
| 5.1 y 5.2 Pitch y discusión técnica | Todos | ⏳ Guion del pitch de 7 minutos y reparto de la discusión |

## Para la discusión técnica (Anny, en un minuto)

1. **RAG**: Qdrant local con 869 fragmentos y búsqueda híbrida; cada respuesta
   cita documento y fragmento.
2. **Evaluación**: con 36 preguntas, hit@5 0,75, recall@10 0,82 y nDCG@10 0,64.
   El híbrido gana a BM25 solo (0,75 frente a 0,53). Lo reportamos con su
   intervalo de confianza porque 36 preguntas son pocas.
3. **t-SNE**: el plano es confiable (0,95). Los fallos se explican: un PDF
   específico le gana al catálogo, dos etiquetas son discutibles y «noticias
   recientes» pide un filtro por fecha, no por significado.
4. **Seguridad**: el auditor es código. Ninguna respuesta con una promesa, el
   gota a gota, un dato personal o una fuga de instrucciones llega al invitado,
   y lo probamos con 15 ataques.
