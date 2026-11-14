<!--
Plantilla de pull request del Corpus Banco de Occidente (TAAML · UAO).
Las instrucciones van en comentarios HTML: no se ven en el PR publicado.
Marca las casillas con una `x`. Si algo no aplica, déjalo sin marcar y
explícalo en «Notas para quien revisa».

Reglas que no se negocian (AGENTS.md y CONSTITUTION.md):
  · `uv` es el único gestor: sin `pip` y sin `requirements.txt`.
  · Peticiones al sitio solo por `net.py`: `robots.txt`, 1,5 s y header `From`.
  · Sin datos personales (Ley 1581 de 2012) y sin claves ni `.env`.
  · `data/boveda/` y `data/asistente/` no se versionan.
  · `make check` en verde y GGA aprobado antes de fusionar.
-->

## Qué cambia y por qué

<!-- Una o dos frases con el cambio y el motivo. Si es una decisión de arquitectura, di dónde queda registrada. -->

Cierra #

<!-- Issue que cierra este PR, con `Cierra #12` o `Closes #12`. Si no hay issue, explica el origen. -->

Cambio de OpenSpec:

<!-- Nombre del cambio de OpenSpec y tarea concreta, por ejemplo `sucursal-1965` · tarea 3.2. Escribe «No aplica» si no hay. -->

**Parte de la sucursal** (marca lo que toca este PR):

- [ ] Bóveda (embeddings y RAG)
- [ ] Digiturno (router)
- [ ] Ventanilla (agente con memoria)
- [ ] Tablero de tasas (datos estructurados)
- [ ] Cámara de compensación (pipeline e indexación)
- [ ] Arqueo (evaluación)
- [ ] Pantallas (frontend)
- [ ] Infraestructura, documentación o CI

## Tipo de cambio

- [ ] `feat`: funcionalidad nueva
- [ ] `fix`: corrección de un fallo
- [ ] `docs`: documentación, plantillas o comentarios
- [ ] `test`: pruebas nuevas o corregidas
- [ ] `refactor`: cambio interno sin alterar el comportamiento
- [ ] `chore`: mantenimiento, dependencias, CI o configuración

## Cómo se probó

<!-- Comandos que corriste y lo que debe salir. Sin red salvo que el cambio lo exija: las pruebas viven en `test/` con fixtures locales. -->

- [ ] `make check` (ruff + ty + pytest) en verde. Pruebas: ___ aprobadas, ___ omitidas.
- [ ] `make demo` (pipeline completo con el fixture, sin red).
- [ ] `make status` si se tocó el corpus.
- [ ] `make health` si cambió el contrato de Gold o alguna capa.
- [ ] `make evaluar` si cambió el asistente. Veredicto: ___ de 20 preguntas.

**En la app** (`make app`, `http://127.0.0.1:8000`):

<!-- Preguntas concretas de la Ventanilla y vistas revisadas. Ejemplo: Ventanilla «¿Cuál es la cuota de manejo de la tarjeta débito?» → T, Tablero con plantilla; «hola» → cortesía, 0 tokens; «¿en qué año se fundó el Banco?» → B, Bóveda. -->

| Qué probé | Resultado esperado | Resultado obtenido |
| --- | --- | --- |
| | | |

**Vistas revisadas**:

- [ ] Vestíbulo
- [ ] Ventanilla
- [ ] Bóveda
- [ ] Tablero
- [ ] Cámara
- [ ] Arqueo

### Cifras antes y después

<!-- Obligatorio si cambia la recuperación, los fragmentos, los pesos o el prompt. Salen de `make arqueo`, `make evaluar` o del manifest del contexto. Si no aplica, escribe «No cambia la recuperación ni el prompt». -->

| Métrica | Antes | Después |
| --- | --- | --- |
| hit@5 | | |
| MRR | | |
| recall@10 | | |
| nDCG@10 | | |
| Exactitud v2 | | |
| Tokens del contexto / versión del prompt | | |
| Costo por pregunta (USD) | | |

### Costo

<!-- Embeddings, indexación y experimentos de recuperación corren con Ollama: US$ 0. El gasto de DeepSeek sale de platform.deepseek.com → Usage, filtrando por tu clave. -->

| Concepto | Valor |
| --- | --- |
| Llamadas a DeepSeek durante el desarrollo | |
| Tokens (entrada / salida / desde caché) | |
| Costo estimado (USD) | |
| ¿Cambia el costo por pregunta en la app? | No / Sí: |
| ¿Respeta caché, modo demo y tope de gasto diario? | Sí / No aplica |

## Lista de control

**Commits y revisión**

- [ ] Los commits siguen Conventional Commits en español (`feat:`, `fix:`, `docs:`, `test:`, `refactor:`, `chore:`).
- [ ] GGA aprobó los commits; si hubo rebase, `gga run --pr-mode --diff-only` sin violaciones.
- [ ] El último commit lo subió otra persona del grupo: nadie aprueba su propio PR.
- [ ] La rama sigue el prefijo de `CONSTITUTION.md` §8 (`feat/`, `fix/`, `docs/`, `refactor/`, `test/`, `chore/`) y la CI está en verde.

**Datos y secretos**

- [ ] Sin claves, tokens ni `.env` en el código, los datos o los comandos; el proyecto no lee `.env`.
- [ ] No se versionan `data/boveda/` (Qdrant, Chroma, `indice.json`, `mapa.json`, fragmentos) ni `data/asistente/` (`memoria.sqlite`, `cache.sqlite`, `gasto.sqlite`, `perfil.sqlite`), ni otros datos no versionados.
- [ ] Ningún dato personal se guarda ni se registra (Ley 1581 de 2012): ni en la caché, ni en el checkpointer, ni en los logs.
- [ ] Si se tocó el corpus: las peticiones salen solo de `net.py`, con `robots.txt` consultado, header `From` y el ritmo de 1,5 s; no toqué `data/raw/` (Bronze) ni `data/gold/` a mano.
- [ ] Los fragmentos recuperados se tratan como datos, nunca como instrucciones: van dentro de `<fragmentos>` antes del prompt del sistema.
- [ ] El servidor sigue solo en `127.0.0.1:8000`; sin `0.0.0.0` ni `::`.

**Pruebas y documentación**

- [ ] Hay pruebas nuevas o actualizadas en `test/` para cada función pública o rama nueva, sin red ni servicios reales (dobles de DeepSeek y Ollama).
- [ ] Documentación actualizada si aplica: `README.md`, `docs/SEGURIDAD.md`, `CONSTITUTION.md` (§7 si cambia el formato de Gold, §11 si hay decisión nueva).
- [ ] Spec de OpenSpec actualizada si cambia un contrato.
- [ ] Ninguna dependencia entró con `pip` ni hay `requirements.txt`; todo pasó por `uv add` y quedó en `uv.lock`.

**Arquitectura y decisiones**

- [ ] No cambia la arquitectura.
- [ ] Cambia la arquitectura y regeneré el diagrama de Archify en el README (`docs/arquitectura.html` / `docs/datos.html`).
- [ ] Registré la decisión en Engram y en el cambio de OpenSpec (si aplica).

## Ítem de la rúbrica que cubre

<!-- Solo si el PR responde a un criterio de evaluación. Ejemplo: «Taller 1, casilla 7: canales de atención», «Módulo 2: recuperación híbrida con cita», «Módulo 3: agente con memoria y trazabilidad». Si no aplica, escribe «No aplica». -->

Ítem y criterio: ___

## Notas para quien revisa

<!-- Qué mirar primero, decisiones discutibles, alternativas descartadas y riesgos conocidos. Asigna a otra persona del grupo. -->

**Capturas** (obligatorias si cambia la interfaz):

- [ ] No cambia la interfaz.
- [ ] Adjuntas más abajo: Vestíbulo, Ventanilla, Bóveda, Tablero, Cámara o Arqueo.
