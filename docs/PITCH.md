# Pitch de la sustentación: Pana presenta

Guion de los 15 minutos del **sábado 28 de noviembre de 2026, 8:00 a. m.**
(tarea 4.6 de `agente-openclaw`). No hay diapositivas y **nadie del equipo
habla**: Pana presenta, conduce la actividad y responde las preguntas. El
equipo opera en silencio desde sus puestos.

**Formato interactivo.** Un voluntario del público escribe a Pana por WhatsApp
y la pantalla muestra **su** escena, en vivo y con voces: sus mensajes, la
oferta de Don Gota, la comparación de Pana, la negociación entre los dos
agentes y el veredicto del auditor. Al final, la ficha de la opción le llega
al celular. El voluntario también puede responder el perfil **hablando** por la
entrada **V**: el navegador transcribe y `POST /api/escena/hablar` le devuelve la
interpretación y la línea de Pana. Con **Hablar con Pana**, la frase libre pasa
por los filtros del canal y la respuesta y la ficha llegan a su WhatsApp. Para el cierre, la tecla **G** abre el panel
de recursos con el QR del repositorio, el QR de WhatsApp (si hay número) y los
seis diagramas de Archify. El contrato técnico está en
[`ESCENA_EN_VIVO.md`](./ESCENA_EN_VIVO.md); si el punto de control del jueves 26
no queda en verde, se usa la versión B de la sección 2.

| Documento | Para qué |
|---|---|
| [`LISTA_DEMO.md`](./LISTA_DEMO.md) | Encendido, prueba de humo y plan B |
| [`DEMO_GOTA_A_GOTA.md`](./DEMO_GOTA_A_GOTA.md) | La escena: flujo, cifras y roles |
| [`ESCENA.md`](./ESCENA.md) | La pantalla y sus teclas (E = modo en vivo) |
| [`ESCENA_EN_VIVO.md`](./ESCENA_EN_VIVO.md) | Contrato de la escena en vivo y su plan B |
| [`PRESENTADOR.md`](./PRESENTADOR.md) | Las 22 respuestas fijas de Pana (`#p1` a `#p22`) |
| [`CODIGO.md`](./CODIGO.md) | Mapa corto del código, las pruebas y el repositorio |
| [`PREGUNTAS_FRECUENTES.md`](./PREGUNTAS_FRECUENTES.md) | Las 31 respuestas escritas sobre el proyecto |

**Enlace de la demo:** `http://127.0.0.1:8000/escena.html` en el computador
de Nayla, en Edge y en pantalla completa (F11). El número de WhatsApp va solo
en las tarjetas de los invitados, nunca en el repositorio.

## 1. Roles

| Quién | Puesto | Qué hace en silencio |
|---|---|---|
| Nayla | Computador de la demo | Lleva el reloj, vigila el gateway, el MCP y la lista en vivo, y **decide el plan B** |
| Yoldy | Pantalla | Pasa la presentación (Espacio), entra y sale del modo en vivo (E), pausa la cola si hace falta (P), abre las herramientas (H), las preguntas (Q) y los recursos (G); cronometra; activa solo subtítulos (S) si falla el audio |
| Darley | Voluntario y WhatsApp | Acompaña al voluntario, su celular y la entrada por voz (V); vigila Meta, el túnel, el modo evento y que el voluntario haya escrito el código de la escena |
| Anny | Invitados y auditor | Reparte a los invitados la tarjeta o el QR («responde Acepto» y dos sugerencias) y entrega **solo al voluntario** la tarjeta con el código de la escena; vigila el veredicto y la trazabilidad (T) |

## 2. Minuto a minuto

### Versión A: escena en vivo (si el punto de control queda en verde)

| Minuto | Bloque | En la pantalla | Quién opera | Qué tiene que quedar claro |
|---|---|---|---|---|
| 0:00 – 1:00 | **Presentación** | Los turnos 1 a 6 de `INTRODUCCION` (`anfitrion.js`): Pana abre, dice que el gota a gota cobra cerca de 791 % E.A. (turno 2) y se presentan Don Gota, los dos agentes y el auditor | Yoldy (Espacio) | Qué es Pana, para quién es (jóvenes con su primer crédito) y que el gota a gota cobra cerca de 791 % E.A. |
| 1:00 – 1:30 | **Invitación** | El turno 7 de `INTRODUCCION` (Pana invita al voluntario y a escribir por WhatsApp); después Yoldy pulsa **E** y la barra dice «En vivo · esperando el primer turno» | Anny (tarjetas), Darley (voluntario) | El voluntario responde **Acepto** y escribe el **código de la escena** (`ESCENA` y los cuatro dígitos de `$env:ESCENA_CODIGO`), que va **solo en su tarjeta**: si lo tuvieran todos, cualquiera se tomaría la pantalla. Los demás invitados inventan sus propios datos (la tarjeta no los trae) y no salen en la pantalla |
| 1:30 – 2:30 | **El voluntario escribe** | Sus mensajes salen en subtítulo como «Invitado» y Pana le responde con voz | Darley (acompaña), Yoldy (E ya activo) | Que es una conversación real por WhatsApp, sin nombres ni números en la pantalla |
| 2:30 – 3:30 | **Don Gota** | Los turnos de `calcular_prestamo_gota`: interés mensual, total y cuota diaria | Yoldy (P si hay que esperar) | Don Gota es un cálculo en código, nunca un modelo |
| 3:30 – 4:30 | **Pana compara** | Los turnos de `comparar_gota_banco`: tasa E.A. frente a la usura y artículo 305 | Yoldy | **Cifras 1 y 2:** la usura (28,34 % E.A.) y la tasa del banco |
| 4:30 – 6:00 | **Negociación** | Los turnos de `negociar_opcion`: agente del joven y agente del banco | Yoldy (Espacio si un turno se alarga) | Dos opciones: cuota más baja o menos total pagado |
| 6:00 – 7:00 | **Veredicto y ficha** | El turno de `auditar_respuesta` y la ficha de `generar_ficha_opcion`; la ficha llega al celular del voluntario | Yoldy; Darley (muestra el celular) | **Cifra 3:** el veredicto (`conforme`, `con_observaciones` u `objeta`); Pana nunca dice «aprobado» |
| 7:00 – 12:00 | **Parte técnica** | Yoldy sale del modo en vivo (**E**); herramientas en vivo (H) con lo que piden los invitados por WhatsApp; para el repositorio y el código abre **G** (QR del repositorio y diagramas); preguntas del jurado por la Q | Yoldy (E, H, G, Q); Anny (T si piden la trazabilidad) | Que es un agente con 20 herramientas, que las cifras salen de código, dónde está el repositorio y que hay respaldo si algo cae |
| 12:00 – 15:00 | **Preguntas** | Apertura de preguntas de Pana; cada pregunta por la Q, escrita o dictada; el voluntario también puede probar la entrada **V** si el jurado quiere hablarle a Pana | Yoldy (Q, G); Darley (V) | Pana responde con sus fichas; si no sabe, lo dice y remite a WhatsApp |

Los minutos 1:30 a 7:00 dependen de lo que escriba el voluntario: las dos
sugerencias de la tarjeta lo llevan a pedir un préstamo y a preguntar por el
gota a gota, para que Pana use las cinco herramientas en ese orden. Si a las
4:30 todavía no habló Don Gota, Nayla decide pasar a la versión B.

### Versión B: plan B del punto de control

Si a las 12:00 del jueves la escena en vivo no queda en verde
([`ESCENA_EN_VIVO.md`](./ESCENA_EN_VIVO.md), §15.3), `ESCENA_EN_VIVO=0` y:

| Minuto | Bloque | En la pantalla | Quién opera |
|---|---|---|---|
| 0:00 – 1:00 | **Presentación** | Igual que en la versión A | Yoldy (Espacio) |
| 1:00 – 1:30 | **Gancho** | 30 s de la escena guardada: Don Gota hace su oferta y Pana la compara | Yoldy (Espacio) |
| 1:30 – 7:00 | **Demo por WhatsApp** | El voluntario y los invitados escriben a Pana; el panel **H** muestra cada herramienta que usa | Darley (voluntario), Yoldy (H) |
| 7:00 – 15:00 | **Parte técnica y preguntas** | Igual que en la versión A, con el panel **G** para el repositorio y los diagramas | Yoldy (H, G, Q); Darley (V) |

En las dos versiones el público sale con las mismas tres cifras (sección 4).

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
| 7 | ¿Dónde está el repositorio? ¿Puedo ver los PR? | P18 |
| 8 | ¿Qué es un token en git? | P19 |
| 9 | ¿Cómo está organizado el código? | P20 |
| 10 | ¿Tienen un diagrama de arquitectura? | P21 |
| 11 | ¿Cómo prueban el proyecto? | P22 |

Las 22 respuestas de `config/escena.toml [preguntas]` llegan a la pantalla por
`POST /api/escena/pregunta`; si el servidor no responde, la Q usa la ficha corta
de `anfitrion.js`. Las preguntas 7 a 11 también tienen respuesta aunque no haya
modelo, red ni Ollama, porque son fichas fijas y palabras clave del proyecto.

Para la parte técnica, **G** abre el panel de recursos: el QR y el enlace del
repositorio público, el QR de WhatsApp si hay número y los seis diagramas de
Archify (arquitectura, flujo de datos, canal, diagnóstico y los dos de
OpenClaw). El QR del repositorio no necesita configuración; el de WhatsApp sí
(`PANA_WHATSAPP_NUMERO`, ver [`LISTA_DEMO.md`](./LISTA_DEMO.md)).

## 4. El cierre: tres cifras

El público tiene que salir con estas tres cifras. Las tres **se dicen en la
escena** y quedan juntas en la **trazabilidad (tecla T)**; el panel de la
derecha muestra solo las cifras del turno que se está diciendo y el veredicto
solo mientras habla el auditor. Si el jurado pide verlas al final, Anny abre la
trazabilidad con **T**:

| Cifra | De dónde sale | Con $1.000.000 (noviembre de 2026) |
|---|---|---|
| Usura | `config/tasas.toml [usura]` | 28,34 % E.A. |
| Tasa del banco | Motor del diagnóstico, extremo máximo | 28,17 % E.A. |
| Veredicto | Auditor | Depende del perfil del voluntario |

Con otro monto o perfil, la tasa del banco y el veredicto cambian; la usura no.

## 5. Si algo falla

| Si falla | Qué se ve | Qué se hace |
|---|---|---|
| La lista en vivo (la barra dice «Sin conexión» más de 20 s) | La pantalla se queda en el último turno | Yoldy sale con **E** y sigue la versión B: la escena guardada y el panel H |
| Un turno llega mal | La barra dice «Turno descartado» | Nada: la cola sigue con el siguiente |
| La voz o el audio | La escena sigue con texto | Tecla S (solo subtítulos) y avanzar con Espacio |
| El voluntario no escribe o no tiene señal | La barra dice «esperando el primer turno» | Darley le presta el celular del equipo; si no hay tiempo, versión B |
| El micrófono de la entrada (V) no oye o no está | La captura pide escribir o elegir tarjeta | Se escribe la letra o el monto, o se usa el **Perfil seguro**; la escena sigue igual |
| El QR del repositorio o un diagrama no abre | El panel G muestra el enlace y los demás recursos | Se abre el enlace de texto; los diagramas se sirven desde `docs/`, sin internet |
| La negociación tarda más de 15 s | — | En vivo: Espacio pasa al siguiente turno. En la escena guardada: tecla N (núcleo) |
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
- [ ] La escena de 1:30 a 7:00 dura menos de seis minutos, en vivo y con un
      voluntario que no conoce el guion.
- [ ] Ensayar la versión B completa al menos una vez.
- [ ] Antes de empezar, borrar la lista en vivo del ensayo
      (`scripts/limpiar_evento.ps1`) para que el sábado empiece vacía.
- [ ] Probar una vez cada salto de la sección 5.
