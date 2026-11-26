# Material de contingencia

Qué mostrar y qué hacer si algo falla durante la sustentación del **sábado 28
de noviembre de 2026** (tarea 4.7 de `agente-openclaw`). En la sustentación
nadie del equipo habla: si el jurado pregunta qué pasó, responde Pana por la
tecla **Q**, y el equipo actúa en silencio desde su puesto.

| Documento | Para qué |
|---|---|
| [`LISTA_DEMO.md`](./LISTA_DEMO.md), sección 6 | El plan B completo, paso a paso |
| [`PITCH.md`](./PITCH.md) | Los 15 minutos y los roles |
| [`ESCENA.md`](./ESCENA.md) | Las teclas de la pantalla |

## 1. Capturas de respaldo

Si la pantalla no se puede mostrar en vivo, estas capturas cuentan la misma
historia. Se tomaron con los turnos de ejemplo y **solo datos inventados**: no
tienen números de teléfono, huellas, nombres ni tokens.

| Captura | Qué muestra | Cuándo usarla |
|---|---|---|
| [`escena-presentacion.png`](./capturas/escena-presentacion.png) | Pana abre la sustentación y presenta la actividad | Minuto 0 |
| [`escena-comparacion.png`](./capturas/escena-comparacion.png) | Pana compara: Don Gota cobra 791,61 % E.A., 27,9 veces la usura; el banco, 28,17 % E.A. | Minuto 3:30 |
| [`escena-veredicto.png`](./capturas/escena-veredicto.png) | El auditor da su veredicto y el panel muestra las tres cifras del cierre | Minuto 6 |
| [`escena-herramientas.png`](./capturas/escena-herramientas.png) | Panel «Pana está usando» (tecla H): herramienta, dueña, resultado y latencia | Parte técnica |
| [`escena-pregunta.png`](./capturas/escena-pregunta.png) | Pana responde «¿Qué pasa si algo falla en vivo?» por la tecla Q | Preguntas |

⏳ **Capturas del canal de WhatsApp** (se toman en la integración, con un
teléfono del equipo y datos inventados): el aviso de la Ley 1581 con
**Acepto**, una respuesta de tarifas con su fuente y la ficha final de la
opción. Antes de guardarlas se recorta la barra de estado del teléfono y
cualquier número visible.

## 2. Si falla una pieza

Nayla decide el salto. Cada fila dice qué ve el público, quién
actúa y qué responde Pana si el jurado pregunta por la **Q**.

| Si falla | Qué ve el público | Quién actúa y qué hace | Si preguntan, Pana dice |
|---|---|---|---|
| El gateway de OpenClaw | Nada raro: los invitados siguen recibiendo respuesta | Nadie en vivo: el canal pasa solo al grafo (`motor="grafo"`). Si no vuelve, Nayla pone `OPENCLAW_ACTIVO=0` y reinicia `make app` | «¿Qué pasa si algo falla en vivo?» → respuesta P17: el canal contesta con el flujo anterior |
| El túnel o Meta | Los invitados dejan de recibir respuesta; el panel H se queda quieto | Darley reinicia `cloudflared`, copia la URL nueva y la pega en Meta (unos 2 minutos). Mientras tanto, la escena sigue en la pantalla | P17: todo continúa por la pantalla mientras vuelve WhatsApp |
| El número o la SIM | Ningún invitado recibe respuesta | Darley revisa el modo evento (`WHATSAPP_EVENTO`) y la ventana `desde`/`hasta`. Si no se arregla en un minuto, se sigue solo con la escena y las capturas de la sección 1 | P17 |
| DeepSeek o su saldo | La negociación usa frases de reglas en vez del modelo | Nayla pasa a modo demo (`SUCURSAL_DEMO=1`) y reinicia `make app` | «¿Por qué DeepSeek?» → P5; la negociación sigue con la política determinista |
| Ollama | Las preguntas sobre documentos del banco dan un error explicable | Nayla arranca Ollama; la escena y las tarifas no dependen de él | — |
| La voz o el audio | La escena sigue con subtítulos | Yoldy pulsa **S** y avanza con Espacio | — |
| La negociación tarda más de 15 s | — | Anny pulsa **N** (núcleo) | — |
| La pantalla completa | — | Yoldy muestra las capturas de la sección 1, en orden | — |
| Internet | No hay WhatsApp, DeepSeek ni voces de Edge | App en modo demo, escena proyectada con voces de Piper y `make simular` | P17 |

La regla de [`LISTA_DEMO.md`](./LISTA_DEMO.md): el plan B se activa en menos
de un minuto y la demo no se detiene. Si el tiempo no alcanza, se recortan
primero las voces, después la pantalla y después DeepSeek; **nunca** el
veredicto, OpenClaw, las 20 herramientas ni la seguridad.

## 3. Antes del sábado

- [ ] Tomar las capturas del canal en la integración del miércoles 25 y
      guardarlas en `docs/capturas/` sin números visibles.
- [ ] En el ensayo del viernes, probar una vez cada fila de la sección 2 y
      anotar cuánto tardó en volver.
- [ ] Tener las capturas abiertas en una pestaña de Edge aparte, lista para
      mostrarla con Alt + Tab.
