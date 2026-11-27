# Pantalla de la escena «Pana vs. el gota a gota»

Pantalla para el proyector del sábado: los agentes hablan con voz y subtítulos,
y un panel muestra el escenario, el semáforo, las cifras con su fuente y el
veredicto del auditor.

```powershell
make app
# abrir http://127.0.0.1:8000/escena.html
```

## Pana como anfitrión

Antes de la escena, **Pana abre la actividad**: se presenta, presenta a cada
agente (cada uno dice una frase con su voz) y anuncia la actividad práctica. Al
final, el paso **Preguntas** deja que el público le pregunte por micrófono.
Todo vive en `app/web/escena/anfitrion.js` y `app/web/escena/microfono.js`.

| Parte | Cómo funciona |
|---|---|
| Presentación (paso 1) | Siete turnos fijos (`origen: "guion_fijo"`): Pana, Don Gota, agente del joven, agente del banco, auditor y Pana otra vez. `GET /api/escena/introduccion` puede reemplazarlos; si no responde, se usa el guion del archivo |
| Abrir preguntas | Botón «Preguntas» o tecla **Q**. La primera vez Pana invita a preguntar y avisa que el micrófono usa el reconocimiento de voz de Microsoft Edge |
| Micrófono | Botón «Hablar»: reconocimiento de voz del navegador en `es-CO`, una sola frase; al oírla, Pana responde. Si no hay micrófono o falla, se escribe la pregunta y se pulsa Enter |
| Respuesta | Se muestra la pregunta («Pregunta del público») y Pana responde con voz y subtítulos |

Cómo decide Pana qué responder (gana la primera regla que aplica):

1. Pregunta vacía o de más de 300 caracteres, o con algo que parece un documento,
   un celular o un correo → frase fija para repetir o para no dar datos.
2. **Karol G o Shakira** (con o sin tildes, «karolg», «la bichota») → frase fija:
   al profesor Jan le gustan mucho, al equipo también, pero no tienen nada que
   ver con el proyecto.
3. `POST /api/escena/pregunta` con `{"pregunta": "…"}` (tarea 6.13): el servidor
   enruta a la ficha de preguntas del profesor (`docs/PRESENTADOR.md`), al
   proyecto (BM25 sobre `README.md` y `docs/`) o al banco (Ventanilla), y
   devuelve `{"tema": "…", "turno": {…}}` con un turno de Pana del contrato
   (`escena/respondedor.py`). La audiencia la fija el servidor (`publico`): un
   campo de más en la petición es un 422. En la pantalla la Ventanilla no
   responde: las preguntas de tasas y productos reciben el rechazo, que invita
   al WhatsApp del canal, y el panel muestra el QR. Sin `DEEPSEEK_API_KEY` o con
   `SUCURSAL_DEMO`, las respuestas fijas funcionan igual y las del proyecto usan
   la frase de respaldo.
4. Si el servidor no responde: una **ficha corta de respaldo** en `anfitrion.js`
   (menos de 40 palabras por respuesta) contesta lo más probable del proyecto
   (gota a gota, agentes, Bóveda y Qdrant, DeepSeek, voces, WhatsApp,
   privacidad, público, equipo, actividad, repositorio, tokens, código,
   diagramas y pruebas); lo demás: «No tengo información sobre eso…». Quien
   presenta ve el aviso.
   Si el servidor responde pero solo con su rechazo o su respaldo fijo
   (`pana.pregunta.rechazo.v1`, `pana.pregunta.respaldo.v1`) y la ficha corta
   sí tiene la respuesta, gana la ficha.

La pregunta del público es un dato no confiable: no se guarda y nunca cambia lo
que hace Pana.

## Panel de recursos (tecla G)

El panel `escena-recursos` se abre con **G** o con su botón, en cualquier paso
(incluso en vivo). Trae, en orden:

| Recurso | Qué hace | De dónde sale |
|---|---|---|
| **QR del repositorio** | El público escanea y abre el repositorio público del proyecto | `GET /api/escena/repositorio/qr.png`, dibujado en memoria con `segno` desde `URL_REPOSITORIO` |
| **Abrir repositorio** | Abre el repositorio en otra pestaña | `GET /api/escena/repositorio`, que devuelve la URL; el HTML no lleva URLs externas |
| **QR de WhatsApp** | El público escanea y pregunta por el canal | `GET /api/escena/whatsapp/qr.png`, dibujado en memoria con `segno` |
| **Diagramas de Archify** | Abre arquitectura, flujo de datos, canal, diagnóstico y los dos de OpenClaw | `GET /diagramas/<nombre>.html` (lista cerrada de seis archivos de `docs/`) |

El número de WhatsApp **no vive en el repositorio**: `escena/recursos.py` lo lee
de la variable de entorno `PANA_WHATSAPP_NUMERO` (solo dígitos, formato
internacional). Sin la variable, `GET /api/escena/whatsapp` responde
`{"disponible": false}`, el QR devuelve 404 y la pantalla oculta el bloque; el
número nunca se escribe en un log ni en la respuesta JSON. El QR del repositorio
no depende de variables: la URL es pública y está versionada en `recursos.py`.

El túnel público no expone estas rutas: solo pasan `/webhooks/whatsapp` y
`/health`. Las preguntas de productos y tasas siguen sin responderse en la
pantalla: el rechazo invita a WhatsApp y el QR está en el panel G. Las preguntas
del proyecto que el profesor suele hacer —repositorio, tokens, código, diagramas
y pruebas— son respuestas fijas (`repositorio`, `git_tokens`, `codigo`,
`diagrama` y `pruebas` en `config/escena.toml`, con fuente en
`docs/PRESENTADOR.md#p18` a `#p22`), así que funcionan sin modelo, sin red y sin
Ollama.

## De dónde salen los turnos

1. `GET /api/escena/proyectado`: la escena precalculada por
   `make escena-proyectada` (`data/escena/proyectado.json`). Lo que responde se
   guarda en `sessionStorage` de esa pestaña.
2. Si el servidor no responde: la última escena guardada en esa pestaña, con el
   sello «Escena guardada (sin servidor)». Sirve si la app se cae y hay que
   recargar la página.
3. Si tampoco hay: `app/web/escena/turnos-ejemplo.json`, con el sello «Turnos de
   ejemplo».

Ambos devuelven una `Escena` (al menos `{"turnos": [...], "veredicto": {...}}`).
Cada turno sigue `TurnoEscena` (`src/banco_occidente_corpus/escena/contratos.py`,
decisión 1 del cambio `demo-gota-a-gota`), validado en el navegador por
`app/web/escena/contrato.js`:

| Campo | Valores |
|---|---|
| `id`, `orden` | identidad y posición del turno |
| `personaje` | `pana`, `don_gota`, `joven`, `agente_joven`, `agente_banco`, `auditor`, `invitado` (el voluntario de WhatsApp, solo en subtítulo) |
| `texto` / `subtitulo` | lo que se dice en voz / lo que se lee (si falta, se lee `texto`) |
| `cifras` | lista de `{etiqueta, valor, valor_legible, unidad, fuente}`; `fuente` es `{tipo, referencia}` con `tipo` `config`, `gold`, `motor`, `calculo_gota`, `usura`, `guion` o `documento`. La pantalla muestra `valor_legible` y no calcula nada |
| `escenario` | `EscenarioEscena` del motor (`codigo`, `monto`, `plazo_meses`, `semaforo`…) o `null` |
| `origen` | `guion_fijo`, `motor`, `llm`, `reglas`, `entrada_voz` o `canal` (los viejos `guion` y `modelo` se rechazan) |
| `hallazgos` | `{codigo, turno_id, detalle, gravedad}` del auditor |

El **veredicto del auditor** (`conforme`, `con observaciones`, `objeta`) llega
aparte y se muestra como «Auditor: …» sin colores; el **semáforo del crédito**
(`verde`, `amarillo`, `rojo`) sale del escenario y se muestra como «Semáforo del
crédito: …». Pueden diferir: un crédito en rojo con un auditor conforme es
posible.

Un turno que no cumple el contrato no se dice: la pantalla muestra el error.
El paso de la escena (2 Voluntario a 7 Veredicto) se deduce de quién habla; el
paso 1 es la presentación y el 8 las preguntas.

## Los rostros

Cada personaje con voz sale con un **retrato en 3D** (`app/web/escena/rostros/<personaje>.webp`,
384 × 384, menos de 60 KB cada uno) dentro de un círculo con borde de su color; el
que habla brilla. Los retratos se **generaron con IA** a partir de una descripción
escrita por el equipo: son personajes inventados, no fotos de personas reales.

Si un retrato no carga, la pantalla usa el dibujo plano de respaldo de
`app/web/escena/rostros.js` (solo figuras SVG). En el dibujo la boca se mueve
mientras el personaje habla; el voluntario no tiene voz, así que la suya no. El
`invitado` no tiene `.webp`: usa siempre el dibujo de respaldo y va solo en
subtítulo.

Para cambiar un retrato basta con reemplazar el `.webp` con el mismo nombre
(cuadrado, de los hombros hacia arriba, fondo liso del color del personaje).

| Personaje | Cómo se ve |
|---|---|
| Pana | el mismo joven de buzo gris de las tarjetas (`pana/personaje.py`) |
| Don Gota | prestamista con gorra, bigote, cadena dorada y diente de oro |
| Joven (voluntario) | pelo crespo, chaqueta de jean y audífonos al cuello |
| Agente del joven | robot amable de pantalla azul con gorra al revés |
| Agente del banco | robot formal con diadema de atención y corbatín |
| Auditor | persona mayor con gafas redondas y corbata |
| Invitado | el voluntario con el teléfono en la mano (sin retrato `.webp`) |

## Cómo se maneja

| Control | Qué hace |
|---|---|
| Empezar / Pausar (tecla P) | reproduce los turnos seguidos, cada uno con la voz de su personaje |
| Siguiente turno (Espacio o →) | pasa al siguiente sin esperar |
| Solo subtítulos (tecla S) | **modo de respaldo**: no suena nada y avanza de a un turno por clic; las respuestas a preguntas salen solo en texto |
| Preguntas (tecla Q) | abre o cierra el cuadro de preguntas del público |
| Entrada por voz (tecla V) | abre la captura del perfil del voluntario (`escena:captura`). El botón **Hablar** transcribe con el navegador y manda el texto a `POST /api/escena/hablar`, que devuelve la interpretación y la línea de Pana; si no entiende, Pana pide repetir y no avanza. El botón **Hablar con Pana** manda una frase libre: si hay voluntario activo, pasa por los filtros del canal y el motor, y la respuesta y la ficha llegan por WhatsApp. Si falla el micrófono, se escribe o se usa el perfil seguro ([`LISTA_DEMO.md`](./LISTA_DEMO.md), sección 6.2) |
| Núcleo (tecla N) | **plan B**: sigue solo con Don Gota, Pana y el auditor, sin repetir lo ya dicho, y deja la escena en pausa |
| Trazabilidad (tecla T) | muestra u oculta el panel para quien facilita (empieza oculto) |
| Herramientas (tecla H) | muestra u oculta, a la vista del público, las últimas herramientas que usó Pana: nombre, dueña, si salió bien y cuánto tardó. Lee `GET /api/herramientas/traza` cada 2 s solo mientras está abierto; nunca muestra argumentos ni huellas. Con el servidor MCP apagado dice que todavía no hay llamadas |
| Recursos (tecla G) | muestra u oculta el panel con el QR del repositorio, el enlace para abrirlo, el QR de WhatsApp (si hay número) y los seis diagramas de Archify. Se puede abrir en cualquier paso |
| En vivo (tecla E) | entra o sale del **modo en vivo**: deja la escena guardada en pausa y reproduce, en orden, los turnos que publican el canal y las herramientas mientras el voluntario escribe por WhatsApp. Ver [Modo en vivo](#modo-en-vivo-tecla-e) |
| Reiniciar (tecla R) | vuelve al inicio con la escena completa y borra la escena guardada en la pestaña  (en vivo: vuelve a pedir la lista desde el principio) |

## Modo en vivo (tecla E)

Contrato completo: [`ESCENA_EN_VIVO.md`](./ESCENA_EN_VIVO.md), §11. La
pantalla lo implementa en `app/web/escena/envivo.js`.

- **Entrar (E o botón «En vivo»).** Detiene la escena guionada, limpia el
  escenario y empieza desde el **último turno** de la lista: el primer sondeo
  (`desde=0`) solo mueve el cursor y los turnos viejos no se reproducen. Desde
  ahí suenan los nuevos.
- **Entrada del voluntario (V) en vivo.** El panel solo muestra la
  conversación con Pana: el botón grande «Toca y habla con Pana», lo que se
  escuchó («Escuché: …») y el aviso de que el reconocimiento puede usar un
  servicio externo. El texto va a `POST /api/escena/hablar`. Las tarjetas A–F,
  el campo del monto y los botones Hablar, Enviar y Perfil seguro se ocultan
  (fuera del modo En vivo siguen igual). Después de enviar, el panel se cierra
  solo en 1,5 s para no tapar los subtítulos; si Pana no responde, se vuelve a
  abrir con el error.
- **Sondeo.** Cada 2 s, una petición a la vez, con techo de 1,5 s y sin caché.
  Con la pestaña oculta se detiene y al volver pide de inmediato. El cursor
  `desde` vive solo en memoria.
- **Cola.** Se ordena y se deduplica por `seq`, y suena un turno a la vez. Un
  turno que no cumple el contrato no se dice: la barra muestra «Turno
  descartado» y la cola sigue. El publicador tampoco repite un turno idéntico
  al último del mismo personaje (mismo `id` y mismo texto), así que el
  veredicto del auditor se dice una sola vez aunque Pana lo audite en cada
  mensaje con cifras.
- **Quién habla.** Pana, Don Gota, los dos agentes y el auditor con su voz. El
  **invitado** (el voluntario escribiendo por WhatsApp) sale **solo en
  subtítulo**, con la etiqueta «Invitado», en su propia silla, y se lee
  entre 2 y 6 segundos. Con **S** nadie usa la voz.
- **Teclas en vivo.** **P** pausa o reanuda la cola (sigue llegando lo nuevo),
  **Espacio** corta el turno actual y sigue con el próximo, **R** vuelve a
  pedir la lista desde el principio. **Q**, **N** y **V** salen primero del
  modo en vivo para no mezclar las dos escenas.
- **Barra de estado.** «En vivo · esperando el primer turno», el último `seq`,
  cuántos turnos hay en cola o «Sin conexión (reintentando)». Nunca muestra
  datos personales.
- **Salir (E otra vez).** Para el sondeo, vacía la cola y devuelve la escena
  guardada al mismo turno en que estaba, en pausa.

El otro extremo lo pone el canal: el voluntario escribe `ESCENA` y el código de
cuatro dígitos de la sesión por WhatsApp y
`canal/escena_vivo.py` publica su mensaje y la respuesta de Pana con
`ESCENA_EN_VIVO=1`; `escena/api_en_vivo.py` sirve la ruta. El detalle está en
[`OPERACION_WHATSAPP.md`](./OPERACION_WHATSAPP.md), sección «Escena en vivo».
Si el publicador no está o el interruptor está apagado, la ruta responde la
lista vacía y la pantalla sigue con la escena guardada.

## Plan B en la pantalla

| Si pasa esto | Se hace esto |
|---|---|
| La negociación falla o hay que acortar | **Núcleo** (N). Pide `GET /api/escena/proyectado?modo=nucleo`; si no responde, usa el núcleo guardado en la pestaña y, si no hay, saca de la escena cargada los turnos de Don Gota, Pana y el auditor. La barra dice de dónde salió: «Núcleo (servidor)», «(guardado)» o «(escena)». El flujo en vivo puede pedir lo mismo con `document.dispatchEvent(new Event("escena:nucleo"))` |
| No hay voz o el sonido falla | **Solo subtítulos** (S) y avanzar con Espacio |
| La app se cae | `make app` otra vez y recargar: si el servidor aún no responde, la pantalla usa la escena guardada en la pestaña |
| Nada de lo anterior | los turnos de ejemplo siguen ahí, con su sello |

## Panel de trazabilidad (solo facilitador)

Con la tecla **T** (o el botón «Trazabilidad») aparece arriba a la derecha, sin
tapar los subtítulos. Empieza oculto: el público no lo ve si no se abre.

- **Resumen**: usura, tasa del banco y tasa del gota, cada una con su fuente
  (`usura`, `motor` o `gold`, `calculo_gota`), y el veredicto del auditor, que
  aparece solo después de que el auditor habla en la escena.
- **Turno actual**: `id`, `origen`, `escenario.codigo` y el modo (completa o
  núcleo).
- **Fuentes de las cifras del turno**: etiqueta, tipo y referencia (y la
  vigencia si la trae).
- **Hallazgos** del auditor con su gravedad y código, y los **sellos**
  (`Escena.sellos`) cortados a 8 caracteres.

## Proyector y portátil

La pantalla está pensada para 1920 × 1080 (proyector) y 1366 × 768 (portátil),
con el zoom del navegador al 100 % y en pantalla completa (F11). En pantallas
bajas se achican los retratos y los márgenes para que nada quede fuera; en
pantallas grandes los subtítulos crecen. El foco del teclado siempre se ve
(borde amarillo) y los subtítulos se anuncian con `aria-live`. Si Windows tiene
contraste alto, se respeta.

El joven es la persona voluntaria: habla en persona, así que su turno solo se
muestra en subtítulos. Las voces vienen de `app/web/voz.js` (ver
[`VOZ.md`](./VOZ.md)); si Piper falla, se usa la voz del navegador y los
subtítulos siguen visibles.

`turnos-ejemplo.json` es **solo un ejemplo de maquetación** (lo dice su campo
`descripcion` y la pantalla muestra el sello «Turnos de ejemplo»). Se reemplaza
por la salida de `make escena-proyectada` cuando exista (tarea 6.11 del cambio
`demo-gota-a-gota`). Mientras tanto ya sigue `TurnoEscena`: los turnos de Don
Gota y de la comparación de Pana salen del código de `escena/gota.py` y
`escena/comparacion.py`; las cifras del banco, de `diagnostico.motor.calcular`
(un millón, empleado, 36 meses, tasa máxima de noviembre de 2026). Los turnos del
voluntario y de la negociación son de ejemplo. `test/test_web_escena.py`
comprueba las cifras y, cuando `escena/contratos.py` está en main, valida cada
turno con Pydantic.
