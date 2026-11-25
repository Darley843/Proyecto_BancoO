# Pitch de la sustentación: Pana presenta

Guion de los 15 minutos del **sábado 28 de noviembre de 2026, 8:00 a. m.**
(tarea 4.6 de `agente-openclaw`). No hay diapositivas y **nadie del equipo
habla**: Pana presenta, conduce la actividad y responde las preguntas. El
equipo opera en silencio desde sus puestos.

| Documento | Para qué |
|---|---|
| [`LISTA_DEMO.md`](./LISTA_DEMO.md) | Encendido, prueba de humo y plan B |
| [`DEMO_GOTA_A_GOTA.md`](./DEMO_GOTA_A_GOTA.md) | La escena: flujo, cifras y roles |
| [`ESCENA.md`](./ESCENA.md) | La pantalla y sus teclas |
| [`PRESENTADOR.md`](./PRESENTADOR.md) | Las 17 respuestas fijas de Pana |
| [`PREGUNTAS_FRECUENTES.md`](./PREGUNTAS_FRECUENTES.md) | Las 30 respuestas escritas sobre el proyecto |

**Enlace de la demo:** `http://127.0.0.1:8000/escena.html` en el computador
de Nayla, en Edge y en pantalla completa (F11). El número de WhatsApp va solo
en las tarjetas de los invitados, nunca en el repositorio.

## 1. Roles

| Quién | Puesto | Qué hace en silencio |
|---|---|---|
| Nayla | Computador de la demo | Lleva el reloj de la escena, elige el momento de cada bloque y **decide el plan B** |
| Yoldy | Pantalla | Pasa los turnos (Espacio), abre la entrada del voluntario (V), las herramientas en vivo (H) y las preguntas (Q); cronometra; activa solo subtítulos (S) si falla el audio |
| Darley | Voluntario y WhatsApp | Acompaña al voluntario y su micrófono; vigila Meta, el túnel y el modo evento |
| Anny | Invitados y auditor | Reparte las tarjetas con el número y los datos inventados; vigila el veredicto y la trazabilidad (T); ejecuta el salto a núcleo (N) |

## 2. Minuto a minuto

| Minuto | Bloque | En la pantalla | Quién opera | Qué tiene que quedar claro |
|---|---|---|---|---|
| 0:00 – 1:00 | **Presentación** | Los 7 turnos de `INTRODUCCION`: Pana, Don Gota, los dos agentes y el auditor se presentan | Yoldy (Espacio) | Qué es Pana, para quién es (jóvenes con su primer crédito) y que el gota a gota cobra cerca de 791 % E.A. |
| 1:00 – 1:30 | **Invitación** | Último turno: «los demás pueden escribirme por WhatsApp» | Anny (tarjetas) | Los invitados escriben **con datos inventados**; el resto sigue en la pantalla |
| 1:30 – 2:30 | **Voluntario** | Entrada del voluntario (V): monto, ingresos, gastos y deudas con letras A–F | Darley (micrófono), Yoldy (V) | Pana confirma las cuatro respuestas; nadie da datos reales |
| 2:30 – 3:30 | **Don Gota** | Cuatro turnos fijos: interés mensual, total y cuota diaria | Yoldy | Don Gota es un guion, nunca un modelo |
| 3:30 – 4:30 | **Pana compara** | Golpe de 36 renovaciones, tasa E.A. frente a la usura y artículo 305 | Yoldy | **Cifras 1 y 2:** la usura (28,34 % E.A.) y la tasa del banco |
| 4:30 – 6:00 | **Negociación** | Agente del joven y agente del banco, hasta cuatro turnos | Yoldy; Anny (N si pasa de 15 s) | Dos opciones: cuota más baja o menos total pagado |
| 6:00 – 7:00 | **Veredicto y cierre** | El auditor dice su veredicto y Pana cierra según ese veredicto | Yoldy | **Cifra 3:** el veredicto (`conforme`, `con_observaciones` u `objeta`); Pana nunca dice «aprobado» |
| 7:00 – 12:00 | **Parte técnica** | Herramientas en vivo (H) con lo que piden los invitados por WhatsApp; preguntas del jurado por la Q | Yoldy (H, Q); Anny (T si piden la trazabilidad) | Que es un agente con 20 herramientas, que las cifras salen de código y que hay respaldo si algo cae |
| 12:00 – 15:00 | **Preguntas** | Apertura de preguntas de Pana; cada pregunta por la Q, escrita o dictada | Yoldy | Pana responde con sus fichas; si no sabe, lo dice |

La escena completa (1:30 a 7:00) dura menos de seis minutos
([`DEMO_GOTA_A_GOTA.md`](./DEMO_GOTA_A_GOTA.md), sección 1).

## 3. La parte técnica sin que nadie hable

Durante 7:00 a 12:00 la pantalla muestra el panel **«Pana está usando»**
(tecla H): cada mensaje de un invitado deja ver qué herramienta usó Pana, de qué
integrante es, si salió bien y cuánto tardó, sin datos del invitado.

Si el jurado no pregunta, Yoldy escribe en la Q estas preguntas, en este orden,
y Pana responde con su ficha:

| # | Pregunta | Ficha |
|---|---|---|
| 1 | ¿Qué es este proyecto? | `PRESENTADOR.md`, P1 |
| 2 | ¿Cómo evitan que responda cualquier cosa? | P7 |
| 3 | ¿Qué hace el auditor? | P12 |
| 4 | ¿Por qué DeepSeek? | P5 |
| 5 | ¿Cómo protegen los datos personales? | P13 |
| 6 | ¿Qué pasa si algo falla en vivo? | P17 |

⏳ Las 17 respuestas de `config/escena.toml [preguntas]` (#210) llegan a la
pantalla por `POST /api/escena/pregunta`, que aún no está en `main`. Mientras
no esté, la Q responde con la ficha corta de `anfitrion.js`.

## 4. El cierre: tres cifras

El público tiene que salir con estas tres cifras, y las tres quedan escritas en
el panel de la derecha:

| Cifra | De dónde sale | Con $1.000.000 (noviembre de 2026) |
|---|---|---|
| Usura | `config/tasas.toml [usura]` | 28,34 % E.A. |
| Tasa del banco | Motor del diagnóstico, extremo máximo | 28,17 % E.A. |
| Veredicto | Auditor | Depende del perfil del voluntario |

Con otro monto o perfil, la tasa del banco y el veredicto cambian; la usura no.

## 5. Si algo falla

| Si falla | Qué se ve | Qué se hace |
|---|---|---|
| La voz o el audio | La escena sigue con texto | Tecla S (solo subtítulos) y avanzar con Espacio |
| El voluntario o su micrófono | — | Perfil seguro ([`LISTA_DEMO.md`](./LISTA_DEMO.md), sección 6.2) |
| La negociación tarda más de 15 s | — | Tecla N (núcleo) |
| OpenClaw | Los invitados siguen recibiendo respuesta | Nada en vivo: responde el grafo |
| WhatsApp, Meta o el túnel | El panel H se queda quieto | La escena sigue; Darley reinicia el túnel (unos 2 minutos) |
| Se acaba el tiempo | — | Se recorta la parte técnica, nunca el veredicto |

El plan B completo está en [`LISTA_DEMO.md`](./LISTA_DEMO.md), sección 6.

## 6. Ensayo cronometrado (viernes 27)

- [ ] Dos ensayos completos con cronómetro; anotar el minuto real de cada
      bloque y corregir la tabla de la sección 2.
- [ ] Nadie del equipo lee ni habla: si alguien tuvo que intervenir, anotar
      dónde y qué le faltó a Pana.
- [ ] Una persona que no conoce el proyecto ve el ensayo y responde: ¿qué es
      Pana?, ¿cuáles fueron las tres cifras?
- [ ] La escena de 1:30 a 7:00 dura menos de seis minutos.
- [ ] Probar una vez cada salto de la sección 5.
