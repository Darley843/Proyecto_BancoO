# Proposal

## Why

La presentación final del Taller 1 es el **viernes 27 de noviembre de 2026**, es 100 % en vivo y no admite guion escrito ni video. El grupo necesita una escena corta, repetible y verificable que muestre, con un voluntario real, por qué el gota a gota es más caro que el banco y cómo el sistema se niega a recomendarlo.

Hoy existen las piezas sueltas: el motor del diagnóstico, el comité y su auditor, las tasas y la usura, Pana, las voces de los seis personajes y el patrón de vistas de la app. Falta la escena que las conecte, el simulador de Don Gota, la negociación acotada, la entrada por voz, la pantalla con subtítulos y los respaldos para que un fallo en vivo no deje la sustentación sin demostración.

## What Changes

- Añadir la capa **Escena gota a gota** con un contrato único, `TurnoEscena`, que comparten la voz, los subtítulos, la entrada por voz y el auditor. Cada turno lleva personaje, texto, cifras con su fuente, escenario, origen y hallazgos.
- Añadir el **simulador de Don Gota**: banco de frases fijas con variables y cálculo determinista con 20 % mensual sobre el capital, cuota diaria de un ciclo de 30 días, total del ciclo, intereses y total neto de 36 renovaciones, y tasa efectiva anual equivalente. Don Gota **MUST NOT** usar un LLM.
- Añadir la **comparación de Pana** con el motor existente (`diagnostico/calculo.py`), el mismo monto y el mismo horizonte de 36 meses, en tasa efectiva anual y contra la usura vigente de `config/tasas.toml`. Pana incluye una frase fija: cobrar por encima del interés de usura es delito en Colombia (Código Penal, artículo 305).
- Añadir la **negociación** entre el agente del joven y el agente del banco: máximo cuatro turnos sobre escenarios precalculados por el motor, 15 segundos en total y 4 segundos por llamada. El LLM solo elige un código de la mesa y un argumento sin cifras; la aceptación la decide el código y los umbrales del semáforo no se mueven.
- Añadir el **auditor de la escena** con reglas en código, reutilizando las comprobaciones de `diagnostico/comite.py`: cifras que existan, fuentes presentes, ninguna promesa de aprobación, ninguna recomendación del gota a gota, ningún cambio de semáforo y ningún dato personal. Su veredicto usa `conforme`, `con_observaciones` u `objeta`, sin colores, para no confundirlo con el semáforo del crédito.
- Añadir la **entrada por voz** del voluntario para las cuatro preguntas con letras A–F (monto, ingresos, gastos y deudas), el monto declarado, la confirmación de Pana, la elección aleatoria de fila y silla y los perfiles seguros preparados.
- Añadir la **pantalla** `app/web/escena.html` como página aparte (PR #169 de Yoldy), con avatares, voces, subtítulos grandes, panel de trazabilidad y modo de respaldo con solo subtítulos y clics. No es una vista `#escena` de la SPA.
- Añadir `make escena-proyectada`, un objetivo **aparte** de `make simular`, que genera la escena de respaldo sin DeepSeek y sin red. No se modifica `make simular`.
- Mantener el plan B en vivo: escena completa → núcleo Don Gota/Pana/auditor → solo subtítulos y clics → perfil seguro → capturas como último recurso.

## Capabilities

### New Capabilities

Ninguna. Este cambio es una capa de demostración y orquestación sobre capacidades existentes. El contrato funcional queda en `design.md` y el cambio declara `skip_specs: true` en `.openspec.yaml`.

La justificación es explícita: la escena no cambia los requisitos de `diagnostico-financiero`, `comite-credito`, `sucursal-frontend` ni `tablero-tarifas`; reutiliza sus contratos, su motor, sus reglas y sus datos. Crear una capacidad nueva para una presentación de cinco días duplicaría requisitos que ya existen y obligaría a mantener dos fuentes de verdad para el mismo cálculo. Si el grupo decide conservar la escena como producto permanente, se abre un cambio posterior con su spec delta y se retira `skip_specs`.

### Modified Capabilities

Ninguna. No se modifican requisitos de las capacidades existentes. La extracción de `auditar_texto` en `diagnostico/comite.py` es un refactor sin cambio de comportamiento, cubierto por las pruebas actuales del comité.

## Impact

- **Código nuevo**: `src/banco_occidente_corpus/escena/` con contratos Pydantic, cálculo de Don Gota, comparación, mesa de escenarios, negociación, auditor, perfiles, servicio, API y CLI. Pantalla aparte `app/web/escena.html` con sus módulos en `app/web/escena/` y sus estilos; la SPA no se toca.
- **Código tocado**: `app.py` (router de la escena antes de los estáticos), `asistente/prompts.py` (dos tareas de negociación), `diagnostico/comite.py` (extracción de `auditar_texto`), `makefile` (`escena-proyectada`), `.gitignore` (`data/escena/`).
- **Configuración nueva**: `config/escena.toml` con el banco de frases de Don Gota, la mesa, el auditor, los perfiles seguros y la UI; `config/prompts/negociacion_joven_v1.md` y `negociacion_banco_v1.md`. Sin secretos y sin datos personales.
- **Datos generados**: `data/escena/proyectado.json` y `data/escena/nucleo.json`, fuera de Git. La escena en vivo no se persiste; los perfiles seguros son ficticios y versionados.
- **Dependencias**: ninguna nueva. Se reutilizan `langchain`/DeepSeek, `FastAPI`, `Pydantic`, Piper y la voz del navegador. El reconocimiento de voz usa la API del navegador, con aviso de posible servicio externo y respaldo por teclado.
- **Pruebas**: unitarias del gota, la comparación, la negociación y el parser; integración de la API; auditor con mutaciones; estrés con perfiles al azar y extremos; humo de la página `escena.html`. Todas sin red, sin DeepSeek y sin Ollama.
- **Riesgos controlados**: el voluntario puede no cooperar o el micrófono fallar (perfil seguro y teclado); DeepSeek puede tardar o fallar (política determinista y núcleo); la voz puede fallar (solo subtítulos y clics); la tasa puede faltar o estar vencida (aviso, sin cifras inventadas, el auditor no da `conforme`).

## Out of Scope

- Aprobación real de crédito, asesoría legal o acusación contra un prestamista real. Don Gota es un personaje ficticio y la tasa del 20 % es un supuesto del ejercicio.
- Un modelo local de reconocimiento de voz o una dependencia nueva de transcripción.
- Cambios en `data/raw/`, `data/gold/`, `data/boveda/`, en el Gold de tasas o en el cambio `corresponsal-whatsapp`.
- Un guion escrito o un video de respaldo. Las plantillas viven en el código y la escena se opera en vivo.
- Publicar la app fuera de `127.0.0.1` o persistir datos del voluntario.

## Success Criteria

- La escena completa se ejecuta en vivo en menos de seis minutos, con un voluntario elegido al azar por fila y silla.
- Don Gota no usa LLM; todas sus cifras salen del cálculo y la escena dice en voz el supuesto de las 36 renovaciones.
- Pana compara el mismo monto y el mismo horizonte en tasa efectiva anual, cita la usura vigente y recuerda el artículo 305 del Código Penal.
- La negociación no supera cuatro turnos ni 15 segundos, y ninguna propuesta sale de la mesa precalculada.
- El auditor emite `conforme`, `con_observaciones` u `objeta`; si objeta, Pana ofrece microcrédito, cooperativas y entidades vigiladas por la Superfinanciera.
- `make check` queda en verde y `make escena-proyectada` funciona sin DeepSeek, sin red y sin Ollama.
- El plan B con solo subtítulos y clics, el núcleo y los perfiles seguros se probaron en el ensayo general.
