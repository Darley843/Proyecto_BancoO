# Lista de verificación de la demo

Qué revisar antes de la sustentación final para que los invitados le escriban a
Pana por WhatsApp, el agente responda con sus herramientas y la escena se vea
en la pantalla, y qué hacer si algo falla.

**Sábado 28 de noviembre de 2026, 8:00 a. m.** Son 15 minutos sin
diapositivas: 7 de pitch con la demo, 5 de discusión técnica y 3 de preguntas.
Los invitados de las empresas (entre ellas, Banco de Occidente) le escriben al
bot desde su propio teléfono.

| Documento | Qué tiene |
|---|---|
| [`DESPLIEGUE.md`](./DESPLIEGUE.md) | Cómo se instala y se enciende cada pieza |
| [`OPERACION_WHATSAPP.md`](./OPERACION_WHATSAPP.md) | Meta, token y webhook, paso a paso |
| [`DESPLIEGUE_WHATSAPP.md`](./DESPLIEGUE_WHATSAPP.md) | Número propio, túnel y modo evento (sección 8) |
| [`DEMO_GOTA_A_GOTA.md`](./DEMO_GOTA_A_GOTA.md) | La escena: flujo, cifras, roles y plan B |
| [`ESCENA.md`](./ESCENA.md) | La pantalla: teclas, voces y trazabilidad |
| [`SEGURIDAD.md`](./SEGURIDAD.md) | §5.1: trazas solo para la demo |

La demo corre en el **computador de Nayla**; los comandos asumen esa máquina.

Reglas generales:

- **Los secretos solo viven en la sesión de PowerShell.** Nada de esta lista se
  escribe en el repositorio, en capturas ni en el chat del grupo.
- **Los invitados usan datos inventados.** Ningún número de teléfono, nombre ni
  cédula de un invitado entra al repositorio, a esta lista ni al chat del grupo.
- **Pana simula y recomienda; nunca aprueba.** La decisión final es del banco.

Lo marcado con ⏳ depende de piezas del cambio `agente-openclaw` que entran a
`main` hasta el jueves (gateway y MCP de 20 herramientas). La dueña o el dueño
de la pieza confirma el comando exacto en [`DESPLIEGUE.md`](./DESPLIEGUE.md)
antes del ensayo del viernes. El modo evento ya está en `main` (#195) y su guía
es [`DESPLIEGUE_WHATSAPP.md`](./DESPLIEGUE_WHATSAPP.md), sección 8.

## 1. Calendario

| Cuándo | Qué se revisa de esta lista |
|---|---|
| Miércoles 25, 6:00 p. m. | Integración: la prueba de humo (sección 5) con un invitado de prueba y el respaldo con el gateway apagado (paso 14) |
| Jueves 26, 6:00 p. m. | Congelamiento: la sección 2 completa, invitados registrados y la etiqueta `entrega-final` |
| Viernes 27 | Dos ensayos completos y el preflight (sección 3) |
| Sábado 28, 7:30 a. m. | Encendido y comprobación (sección 4) |

## 2. Antes del congelamiento (jueves 26)

### Código y entorno

- [ ] `main` con el cambio `agente-openclaw` fusionado: cliente del gateway,
      respaldo al grafo, MCP con las 20 herramientas, modo evento y escena.
- [ ] En la máquina de la demo:
  ```powershell
  git switch main
  git pull
  uv sync --all-extras
  make check
  ```
  `make check` en verde, también con el gateway apagado, sin
  `DEEPSEEK_API_KEY` y con Ollama apagado. Si Windows bloquea una DLL o
  `.venv` da «Acceso denegado», cerrar todo lo que use el proyecto y
  reconstruir el entorno con `Remove-Item -Recurse -Force .venv` y
  `uv sync --all-extras`.

### Bóveda, Ollama y Tablero

- [ ] Ollama encendido y con el modelo de embeddings del proyecto:
  ```powershell
  ollama list
  ```
- [ ] Índice de la Bóveda presente: `data/boveda/indice.json` existe. Si falta,
      `make indice` (usa Ollama y tarda). Sin índice, `buscar_en_documentos`,
      la Ventanilla y Roba la Bóveda fallan.
- [ ] El índice está en **Qdrant**, no solo en Chroma: `data/boveda/indice.json`
      dice `"almacen": "qdrant"` y la colección pesa varios MB.
  ```powershell
  Get-Content data\boveda\indice.json
  (Get-Item data\boveda\qdrant\collection\boveda\storage.sqlite).Length
  ```
  Si falta la línea `almacen` o la colección pesa unos 12 KB, la búsqueda
  vectorial no devuelve nada y la Bóveda responde solo con BM25, sin aviso.
  Pasa con los índices creados antes del cambio a Qdrant. Se arregla en
  segundos, con la app cerrada y sin Ollama ni DeepSeek:
  ```powershell
  uv run python -m banco_occidente_corpus.boveda migrar-qdrant
  ```
  Comprobación: en `make arqueo`, la configuración 1/0 da hit@5 0,75 y no lo
  mismo que la 0/1 (0,53).
- [ ] Tasas del Tablero: si el banco publicó una tabla nueva, regenerarla
      (Nayla). Si no, la demo muestra la alerta `vigencia_vencida`, y es lo
      honesto.

### Meta, número y modo evento (Darley)

- [x] SIM nueva registrada y verificada en la cuenta de WhatsApp Business, con
      el nombre visible del bot aprobado. El número de prueba queda como
      respaldo.
- [ ] Token permanente del usuario del sistema en `..\whatsapp-env.ps1`, fuera
      del repositorio.
- [ ] App publicada (*Live*) y cuenta de WhatsApp suscrita a la app
      (`docs/OPERACION_WHATSAPP.md`, pasos 7 y 8).
- [ ] Nayla agregada como desarrolladora o administradora de la app de Meta,
      para que pueda actualizar el webhook ella misma si el túnel se cae.
- [ ] Modo evento en `config/whatsapp.toml [evento]`: `desde` y `hasta` cubren
      el sábado 28 de 08:00 a 20:00 (con `-05:00`; sin zona horaria se leen
      como UTC), con 30 mensajes por hora y 40 en total por persona
      (`max_por_hora` y `max_por_usuario`) y 300 en todo el evento
      (`max_total`). En el repositorio queda `activo = false`: se enciende con
      `$env:WHATSAPP_EVENTO = "1"` antes de `make app` y se apaga con `"0"`
      ([`DESPLIEGUE_WHATSAPP.md`](./DESPLIEGUE_WHATSAPP.md), sección 8).
- [ ] Para los ensayos del jueves y el viernes, la ventana se mueve a la hora
      del ensayo **solo en el computador de la demo**, sin commit, y se
      reinicia `make app`: la configuración se lee al arrancar.
- [ ] Recorrido de invitados probado (Anny y Darley, tarea 3.6) desde un
      teléfono que **no** está en `[autorizados]`:
  - dentro de la ventana, el primer mensaje recibe el aviso de la Ley 1581 y
    nada más hasta que acepta;
  - después de **Acepto**, Pana responde;
  - al pasar la cuota (30 por hora o 40 en total), llega el aviso de cuota
    sin llamar al modelo;
  - fuera de la ventana o con el evento apagado, el número no recibe
    respuesta (el webhook sí registra el `POST 200`);
  - reiniciar la app no reinicia el conteo de turnos;
  - ni el número ni un nombre aparecen en la base ni en los registros.
- [ ] Huellas de los teléfonos del equipo en `[autorizados]` de
      `config/whatsapp.toml`, para los ensayos fuera de la ventana, generadas
      con la misma `WHATSAPP_ID_SALT` que se usará en la demo:
  ```powershell
  uv run python -m banco_occidente_corpus.canal.identidad --huella "+57 300 123 4567"
  ```
  Las huellas reales se editan **solo en el computador de la demo**: nunca se
  hace `git add` ni commit de `config/whatsapp.toml` con ellas (el repositorio
  es público).
- [ ] `version_aviso` en `config/whatsapp.toml` corresponde al texto vigente
      del aviso, con la mención de DeepSeek. Si el aviso vuelve a cambiar, se
      sube otra vez: así los números de prueba aceptan el texto nuevo (Decreto
      1377 de 2013, art. 8).

### Gateway de OpenClaw y MCP (Nayla)

- [ ] ⏳ `config/openclaw.toml` y `openclaw/openclaw.json` versionados y sin
      secretos. El token vive solo en la sesión; se comprueba sin mostrarlo:
  ```powershell
  [bool]$env:OPENCLAW_GATEWAY_TOKEN
  ```
- [ ] `openclaw security audit` sin críticos ni altos, **otra vez el jueves
      antes de la etiqueta** `entrega-final`. El resultado del 24 de noviembre
      (0 críticas y 2 advertencias justificadas) está en
      [`openclaw/README.md`](../openclaw/README.md#auditoría-de-seguridad).
- [ ] ⏳ MCP `sucursal-agente` en `127.0.0.1:8765` con **exactamente 20
      herramientas** permitidas (`openclaw mcp tools`). `olvidar_mis_datos` y
      `solicitar_asesor` piden confirmación.
- [ ] ⏳ Memoria: reiniciar el gateway y hacer una pregunta de seguimiento; el
      contexto se conserva sin datos personales.
- [ ] Respaldo: con el gateway apagado, el canal responde con el grafo en
      menos de dos segundos y la trazabilidad dice `motor="grafo"`.
- [ ] Si WSL no da la red espejo (`networkingMode=mirrored`), el gateway corre
      en Windows: anotarlo en [`DESPLIEGUE.md`](./DESPLIEGUE.md), sección 5.

### DeepSeek

- [ ] Saldo suficiente en `platform.deepseek.com`. Una deliberación del comité
      cuesta menos de una décima de centavo de dólar (USD 0,0005, medido por
      Nayla) y un mensaje con el agente, entre una y dos décimas; el tope
      diario de la app es US$ 0,20 y `SUCURSAL_TOPE_USD` lo cambia solo para
      esa sesión. Con varios invitados a la vez, revisar en los ensayos si
      alcanza.
- [ ] El tope de la app **no cuenta** lo que gasta el gateway de OpenClaw,
      que llama a DeepSeek por su cuenta. Lo acota el modo evento: todo mensaje
      de un invitado pasa por el tope global de 300, y a unos 0,2 centavos por
      mensaje el evento completo cuesta menos de un dólar. Como la cuenta es
      prepagada, recargar solo lo que el grupo está dispuesto a gastar es el
      segundo tope.
- [ ] La clave de DeepSeek de la app va en `..\whatsapp-env.ps1`, junto con las
      variables del canal y fuera del repositorio. Se comprueba sin mostrarla:
  ```powershell
  [bool]$env:DEEPSEEK_API_KEY
  ```
  Nunca se escribe en el chat, en una captura ni en el repositorio.

### Escena «Pana vs. el gota a gota» (pantalla y voces)

- [ ] Voces de Piper descargadas. Son el respaldo de todos los personajes y
      necesitan internet solo esta vez:
  ```powershell
  make voz-modelo
  ```
- [ ] Escena de respaldo generada, sin DeepSeek, sin red y sin Ollama:
  ```powershell
  make escena-proyectada
  ```
  Deja `data/escena/proyectado.json`, que no se versiona.
- [ ] Panel de **Recursos (G)**: el QR del repositorio y los seis diagramas de
      Archify funcionan sin configurar nada. El QR de WhatsApp es opcional: si
      se va a mostrar, en la misma ventana de `make app` definir el número
      (solo dígitos, sin `+` ni espacios) y reiniciar la app:
  ```powershell
  $env:PANA_WHATSAPP_NUMERO = "57XXXXXXXXXX"
  ```
  Sin la variable el bloque de WhatsApp se oculta; el número no se versiona ni
  se pega en el chat. Se comprueba abriendo **Recursos (G)**: el QR del
  repositorio y el enlace **Abrir repositorio** funcionan, y cada diagrama abre
  en otra pestaña.
- [ ] Escena en vivo encendida en la **misma ventana** de `make app`, antes de
      arrancarla: el interruptor de la lista y el código de cuatro dígitos que
      activa al voluntario. El código va **solo en la tarjeta del voluntario**:
      si lo tuvieran todos, cualquiera se tomaría la pantalla.
  ```powershell
  $env:ESCENA_EN_VIVO = "1"
  $env:ESCENA_CODIGO = "XXXX"
  ```
  El código vive solo en la sesión: no va en `config/`, no se versiona y no se
  pega en el chat. Se lee al arrancar la app, así que un cambio de código exige
  reiniciarla. Se comprueba con el voluntario: en Edge, **E** deja la barra en
  «En vivo — esperando el primer turno»; el voluntario escribe `ESCENA` y los
  cuatro dígitos desde su teléfono y la lista muestra su turno; sin el
  interruptor, el canal responde «La escena en vivo no está activada» y no
  publica nada.
- [ ] Con el voluntario activo (`ESCENA` y el código), abrir **V** y probar
      **Hablar con Pana**: la frase pasa por los filtros del canal, la respuesta
      llega a su WhatsApp y, si el turno produce la ficha, también llega la
      imagen. Sin voluntario activo, el panel avisa y no envía nada.
- [ ] **Microsoft Edge** instalado y con internet: Pana habla con
      «Microsoft Gonzalo Online (Natural)» y el agente del joven con
      «Microsoft Juan Online (Natural)». En otro navegador o sin internet
      vuelven a su voz de Piper (suena, pero menos natural).
- [ ] Con `make app` encendida, abrir en Edge `http://127.0.0.1:8000/voces.html`
      y pulsar **Escuchar** en los seis personajes: Pana y el agente del joven
      con su voz de Edge; el Auditor con voz de hombre.
- [ ] Abrir en Edge `http://127.0.0.1:8000/escena.html`, pulsar **Empezar** y
      escuchar la escena completa con el sonido del proyector o los parlantes
      de la sala.
- [ ] Repetir la escena en Edge **con el wifi apagado**: Pana y el agente del
      joven deben sonar con su voz de Piper (no con una voz de Windows). Así se
      sabe qué voz sale de respaldo en este computador. Después, volver a
      encender el wifi.

### Invitados (Anny)

- [ ] Invitados registrados en la pestaña 2 del registro del evento (nombre,
      cédula y cargo) antes del jueves; Banco de Occidente está confirmado.
      Esos datos se quedan en el registro: no se copian aquí ni al repositorio.
- [ ] Tarjeta impresa para cada invitado, con el número del bot (o un código
      QR que abra el chat) y cuatro líneas:
  1. Escríbele «hola» a Pana.
  2. Lee el aviso y pulsa **Acepto**.
  3. Usa datos inventados: nunca tus ingresos ni tu cédula.
  4. Pana simula y recomienda; no aprueba créditos.

  El número va solo en la tarjeta impresa, nunca en el repositorio.

## 3. Viernes 27: ensayos y preflight

- [ ] La máquina de la demo corre la versión congelada:
  ```powershell
  git fetch --tags
  git switch --detach entrega-final
  uv sync --all-extras
  make check
  ```
- [ ] **Dos ensayos completos de 15 minutos**, uno en la mañana y uno en la
      tarde, con alguien de afuera que escribe desde su propio teléfono.
      Cronometrar 7 + 5 + 3.
- [ ] En cada ensayo se prueba al menos un salto del plan B (sección 6) y se
      anota cuánto tardó la recuperación en
      [`DEMO_GOTA_A_GOTA.md`](./DEMO_GOTA_A_GOTA.md), sección 8. La meta es
      menos de un minuto.
- [ ] Latencia: p95 del canal por debajo de 8 s. La vista Operación marca p50 y
      p95 como muestra insuficiente con menos de **30 corridas** por flujo
      (`MINIMO_CORRIDAS` en `sucursal/operacion.py`). Los ensayos ya producen
      esos mensajes, porque cada botón de la entrevista cuenta como uno.
- [ ] Capturas de contingencia de la traza y del canal (Yoldy), sin datos
      personales. La sustentación es en vivo y **sin video**: las capturas solo
      apoyan la discusión técnica si una pieza no se puede mostrar.
- [ ] Al terminar cada ensayo, cada teléfono de prueba escribe «olvida mis
      datos», para que el siguiente ensayo y el sábado empiecen limpios sin
      reiniciar el estado.

## 4. Sábado 28, 7:30 a. m.

Cada ventana de PowerShell desde la raíz del repositorio, en este orden: MCP,
gateway, app y túnel.

| Ventana | Qué | Comando |
|---|---|---|
| 1 | Servidor MCP | `make agente-mcp` (`127.0.0.1:8765/mcp`); detalle en [`DESPLIEGUE.md`](./DESPLIEGUE.md), sección 6 |
| 2 | Gateway de OpenClaw | `wsl -d OpenClawGateway` y dejar la pestaña abierta; comprobar con `wsl -d OpenClawGateway -- openclaw health` (`127.0.0.1:18789`). Detalle en [`DESPLIEGUE.md`](./DESPLIEGUE.md), sección 5 |
| 3 | App y canal | El bloque de abajo |
| 4 | Túnel | `cloudflared tunnel --url http://127.0.0.1:8000` |
| 5 | Comprobaciones | El bloque de abajo |
| Edge | Pantalla | `http://127.0.0.1:8000/escena.html` en pantalla completa (F11) |

**Ventana 3: la app.**

```powershell
. "..\whatsapp-env.ps1"
$env:WHATSAPP_MODO = "real"
$env:WHATSAPP_EVENTO = "1"
$env:OPENCLAW_ACTIVO = "1"
$env:ESCENA_EN_VIVO = "1"
$env:ESCENA_CODIGO = "XXXX"
Get-ChildItem Env: | Where-Object Name -match 'LANGSMITH|LANGCHAIN'
make app
```

- [ ] La consulta de `LANGSMITH|LANGCHAIN` no muestra nada, salvo que el grupo
      decida mostrar trazas (`docs/SEGURIDAD.md` §5.1).
- [ ] La app queda en `http://127.0.0.1:8000` y `GET /health` responde 200.
- [ ] `ESCENA_CODIGO` tiene los cuatro dígitos que lleva impresos la tarjeta del
      voluntario y es el mismo que se escribió en la sección 2. El código solo
      se dicta al voluntario: nunca se proyecta ni se pega en el chat.
- [ ] Con **E** en la pantalla, la barra dice «En vivo — esperando el primer
      turno» (si dice «Sin conexión», la app arrancó sin `ESCENA_EN_VIVO`).

**Ventana 4: el túnel.** Si `cloudflared` no está instalado:
`winget install --id Cloudflare.cloudflared` y abrir una ventana nueva.

- [ ] Copiar la URL `https://….trycloudflare.com`. Es **variable**: cada vez
      que el túnel se reinicia cambia.
- [ ] En Meta → Webhooks → *Whatsapp Business Account*: actualizar la URL de
      devolución de llamada a `https://<url-del-tunel>/webhooks/whatsapp` y
      pulsar **Verificar y guardar**.

**Ventana 5: comprobaciones.**

```powershell
. "..\whatsapp-env.ps1"
curl.exe "http://127.0.0.1:8000/health"
curl.exe "http://127.0.0.1:8000/webhooks/whatsapp?hub.mode=subscribe&hub.verify_token=$env:WHATSAPP_VERIFY_TOKEN&hub.challenge=12345"
curl.exe "https://<url-del-tunel>/webhooks/whatsapp?hub.mode=subscribe&hub.verify_token=$env:WHATSAPP_VERIFY_TOKEN&hub.challenge=12345"
```

- [ ] `/health` responde 200 y las dos comprobaciones del webhook devuelven
      `12345`.
- [ ] **Ollama encendido**: `ollama list` muestra el modelo de embeddings del
      proyecto. Sin Ollama, `buscar_en_documentos` (herramienta 17), la
      Ventanilla y Roba la Bóveda fallan; el plan B está en la sección 6.1.
- [ ] Saldo de DeepSeek suficiente y tope diario activo.
- [ ] Modo evento **activo**: la ventana 3 tiene `WHATSAPP_EVENTO = "1"` y
      `desde`/`hasta` cubren la hora actual. Si un número desconocido no
      recibe respuesta, lo primero es revisar la ventana.
- [ ] Un mensaje de prueba desde un teléfono del equipo, respondido de punta a
      punta, con `motor="openclaw"` en la trazabilidad.
- [ ] La escena abierta en **Edge**, en pantalla completa y con el volumen
      probado: dos turnos con voz y la tecla **S** (solo subtítulos).
- [ ] Las tarjetas de los invitados a la mano y un teléfono del equipo con el
      chat abierto, por si un invitado no puede escribir.

## 5. Prueba de humo, en el orden de la sustentación

La columna de herramientas dice qué debe verse en la traza del agente. Los
pasos 1 y 2 los resuelve el canal antes del agente.

| # | Qué se hace | Qué debe pasar | En la traza |
|---|---|---|---|
| 1 | `hola` desde un teléfono que no está en `[autorizados]` | Aviso de la Ley 1581 con **Acepto** y **Ahora no**; menciona a DeepSeek como proveedor externo | Canal |
| 2 | **Acepto** | Confirmación; el consentimiento queda guardado | Canal |
| 3 | «Gracias, Pana» | Respuesta de cortesía, sin buscar | Ninguna herramienta |
| 4 | «¿Cuál es la cuota de manejo de la tarjeta débito?» | La tarifa con su fuente | `clasificar_pregunta` → `consultar_tarifas` |
| 5 | «¿Qué tasas manejan?» | Pide el producto y muestra las opciones con su rango | `consultar_tarifas` |
| 6 | «¿En qué año se fundó el Banco de Occidente?» | Respuesta con cita; dice **1965** | `buscar_en_documentos` |
| 7 | «¿Qué clima hace hoy en Cali?» | Rechazo con la respuesta estándar | `clasificar_pregunta` |
| 8 | Un ataque del catálogo `config/evaluacion/inyeccion.toml` (por ejemplo, el `d01`) | Pana no cambia de reglas, no promete aprobación y no revela sus instrucciones | `auditar_respuesta` |
| 9 | «¿Me alcanza para un crédito?» | Perfil con datos inventados → Don Gota → comparación → negociación → auditor; la pantalla muestra cada turno | `diagnosticar_capacidad`, `calcular_prestamo_gota`, `comparar_gota_banco`, `negociar_opcion` |
| 10 | Final de la escena | Llega la ficha de la opción recomendada: simulación orientativa, nunca «aprobado» | `generar_ficha_opcion` |
| 11 | Perfil rojo: Pana ofrece un asesor | Pide confirmación; con **Contactar** llega «Listo, un asesor revisará tu caso…» | `solicitar_asesor` |
| 12 | «¿Y si lo pago en 60 meses?» | Tarjeta de antes y después | `comparar_escenario` |
| 13 | «Olvida mis datos» | Pide confirmación; al confirmar, revoca y el siguiente `hola` vuelve a pedir el aviso | `olvidar_mis_datos` |
| 14 | Ctrl + C en la ventana 2 (gateway) y un `hola` | Responde el grafo; la trazabilidad dice `motor="grafo"`. Volver a encender el gateway | Canal |
| 15 | Web → Operación | Mensajes, consentimientos, casos (el del paso 11 aparece como caso nuevo) y p50 y p95 del canal | — |

⏳ El detalle de los pasos 9 a 12 (botones, orden de las herramientas y qué
turno llega al WhatsApp y cuál a la pantalla) se confirma en la integración del
miércoles y se corrige aquí.

Notas:

- Se usan **solo datos inventados**: nadie escribe sus ingresos reales. Para
  los ensayos, las respuestas salen de los perfiles seguros de
  `config/escena.toml` o de `data/evaluacion/personas_sinteticas.json`.
- En el paso 11, el que pulsa **Contactar** es el cliente; el asesor no recibe
  un segundo WhatsApp, sino que ve el caso en la vista Operación (paso 15). Es
  un proyecto académico: el banco no recibe estos casos, y así se dice en la
  sustentación.
- En **modo demo** la Bóveda no llama al modelo y responde con el fragmento
  principal. Probado el 21 de noviembre: la pregunta del año trae el fragmento
  de 1991–1993 y no el de 1965. En modo demo se usa «¿Cuál es el propósito o
  misión del banco?», que contesta con la página *Nuestro Banco*, o «¿Puedo
  abrir una cuenta en línea?».

## 6. Plan B

Nayla decide el salto; quien lo ejecuta está en la tabla de responsables
(sección 8) y en los roles de la escena
([`DEMO_GOTA_A_GOTA.md`](./DEMO_GOTA_A_GOTA.md), sección 3). La regla es que el
plan B se active en menos de un minuto y que la demo no se detenga.

### 6.1 Canal y agente

| Si falla… | Qué se hace |
|---|---|
| OpenClaw (no responde, se agota el tiempo o da error) | No hay que hacer nada en vivo: el canal responde con el grafo actual y la trazabilidad dice `motor="grafo"`. Si el gateway no vuelve, forzar el grafo con `$env:OPENCLAW_ACTIVO = "0"` en la ventana 3 y reiniciar `make app` (o `fallback_forzado = true` en `config/openclaw.toml`). El webhook, la firma y el consentimiento no cambian |
| DeepSeek o su saldo | ⏳ El gateway pasa a su modelo alternativo. En la app, modo demo: `$env:SUCURSAL_DEMO = "1"` y reiniciar `make app`. La negociación usa la política determinista ([`DEMO_GOTA_A_GOTA.md`](./DEMO_GOTA_A_GOTA.md), sección 7.5) y la Bóveda usa la pregunta de la misión en vez de la del año (nota de la sección 5) |
| La pantalla o las voces | Todo sigue por WhatsApp. En la pantalla, **Solo subtítulos** (tecla S) y avanzar con la barra espaciadora; el resto de saltos en la sección 6.2 |
| Meta o el túnel | Reiniciar `cloudflared`, copiar la URL nueva, actualizar el callback en Meta (Nayla o Darley) y verificar: unos 2 minutos. Último recurso: `make simular` en la pantalla, que firma las conversaciones de las personas sintéticas y las entrega al webhook real con el enviador falso |
| `ErrorEnvio: destino no autorizado` | Con un invitado: el modo evento no está encendido (`WHATSAPP_EVENTO`) o `desde`/`hasta` no cubren la hora; `WHATSAPP_EVENTO` no mueve las fechas. Corregir y reiniciar `make app`. Con un teléfono del equipo: falta su huella o cambió la sal; regenerarla, pegarla en `config/whatsapp.toml` y reiniciar la app |
| Un invitado pasa su cuota (30 por hora o 40 en total) | Es lo esperado: recibe el aviso de cuota sin gasto de modelo; sigue con el teléfono del equipo |
| Se llega al tope global de 300 mensajes | El canal deja de atender invitados nuevos. ⏳ Darley confirma si los números de `[autorizados]` cuentan para ese tope; si no cuentan, se sigue con el teléfono del equipo |
| Ollama o el índice | `buscar_en_documentos` devuelve un error explicable y no inventa: arrancar Ollama y revisar `data/boveda/indice.json`. Mientras tanto, seguir con las tarifas y la escena, que no dependen de Ollama |
| Sin internet | No hay WhatsApp, DeepSeek ni voces de Edge: app en modo demo, escena proyectada con las voces de Piper y `make simular` |

### 6.2 La escena

El mismo orden de [`DEMO_GOTA_A_GOTA.md`](./DEMO_GOTA_A_GOTA.md), sección 8;
las teclas están en [`ESCENA.md`](./ESCENA.md).

| Paso | Cuándo se activa | Qué se hace |
|---|---|---|
| Escena completa | Todo funciona | Agente, DeepSeek y voces de Edge o de Piper |
| Núcleo | La negociación falla o supera 15 s | Tecla **N**: Don Gota → Pana → auditor, sin repetir lo ya dicho |
| Solo subtítulos | Falla la voz o el audio | Tecla **S**; se avanza con clic, espacio o Enter y el público lee las cifras |
| Perfil seguro | El voluntario no responde, no completa su perfil o falla el micrófono de la entrada por voz (tecla **V**) | Se usa un perfil ficticio preparado (`config/escena.toml`); el auditor se ejecuta igual |
| Escena proyectada | Falla la API o el plan B no se recupera | `GET /api/escena/proyectado` lee `data/escena/proyectado.json`; si la app se cayó, `make app` otra vez y recargar |
| Simulador o escena proyectada | Último recurso, todo en vivo | `make simular` o la escena proyectada; **sin video** |

### 6.3 Si el tiempo no alcanza

Se recorta en este orden: primero las voces (quedan los subtítulos), después la
pantalla (la escena sigue completa por WhatsApp) y después DeepSeek en la
negociación (política determinista). **Nunca** se recortan OpenClaw, las 20
herramientas, el WhatsApp de los invitados ni la seguridad.

### 6.4 Contingencias técnicas

Si algo falla en el encendido, esta tabla va del síntoma a la causa y al
comando. No se sube `config/whatsapp.toml` con los ajustes locales, y ningún
comando imprime tokens, números ni direcciones de túnel.

| Síntoma | Causa | Qué hacer |
|---|---|---|
| El gateway no arranca después de apagar WSL; `openclaw health` falla y habla de un candado o *lock* | El proceso anterior no se detuvo antes de cerrar Ubuntu y quedó un bloqueo huérfano | Detener, recuperar el candado y volver a arrancar. `recover-lock` imprime una línea `--confirm`; se copia **completa**, sin recortarla:<br>`wsl -d OpenClawGateway -- openclaw daemon stop`<br>`wsl -d OpenClawGateway -- openclaw gateway recover-lock`<br>`wsl -d OpenClawGateway -- openclaw gateway recover-lock --confirm <lo-que-imprime>`<br>`wsl -d OpenClawGateway -- openclaw daemon start`<br>No se borra el archivo de bloqueo a mano. Prevención: `wsl -d OpenClawGateway -- openclaw daemon stop` antes de cerrar Ubuntu |
| La consola de la app no recibe mensajes y el túnel muestra una dirección nueva | El túnel rápido cambia de subdominio al reiniciarse y Meta conserva el callback anterior, así que entrega el webhook a otro túnel | Reiniciar `cloudflared`, copiar la URL nueva y actualizarla en Meta → Webhooks → **Verificar y guardar**. Para confirmar qué callback tiene Meta, consultar `webhook_configuration` en la API de Graph y comparar `callback_url` con la URL vigente:<br>`$base = "https://graph.facebook.com/v23.0"`<br>`$tok = $env:WHATSAPP_ACCESS_TOKEN`<br>`Invoke-RestMethod "$base/<APP_ID>?fields=webhook_configuration&access_token=$tok" \| ConvertTo-Json -Depth 6`<br>Si la WABA tiene su propio callback, revisar también `subscribed_apps`. El token no se imprime |
| La app o el MCP no arrancan: puerto ocupado (`WinError 10048`, «address already in use») | Otro proceso, o una instancia anterior del proyecto, sigue escuchando en `8000` u `8765` | Ver quién tiene el puerto y cerrarlo solo si es del proyecto:<br>`Get-NetTCPConnection -LocalPort 8000,8765 -State Listen \| Select-Object LocalAddress,LocalPort,OwningProcess`<br>`Get-Process -Id <PID> \| Select-Object Id,ProcessName`<br>`Stop-Process -Id <PID>`<br>No se cambia el puerto: `openclaw.json` y `config/openclaw.toml` apuntan a `8765` |
| La pantalla queda en «En vivo — esperando el primer turno», aunque las herramientas responden | El MCP o la app arrancaron sin `ESCENA_EN_VIVO=1`; la variable se lee al arrancar cada proceso | Definirla en las dos ventanas y reiniciar **ambas** (`make agente-mcp` y `make app`):<br>`$env:ESCENA_EN_VIVO = "1"`<br>Sin el interruptor, el canal responde «La escena en vivo no está activada» y no publica |
| Un número desconocido no recibe respuesta, o recibe el aviso de cuota | La ventana `desde`/`hasta` no cubre la hora, `WHATSAPP_EVENTO` está apagado, o la persona agotó su cuota (30 por hora y 40 en total; 300 en el evento) | El webhook igual registra `POST 200`. Ajustar la ventana en `config/whatsapp.toml` **solo en el computador de la demo** (con `-05:00`) y reiniciar `make app`; `WHATSAPP_EVENTO` no mueve las fechas. Si es la cuota, es lo esperado: seguir con el teléfono del equipo. No se suben las cuotas en plena demo |
| `whatsapp-env.ps1` no carga: «la ejecución de scripts está deshabilitada» o el archivo «no tiene firma digital» | Windows marcó el archivo descargado o la política del proceso es restrictiva | Quitar la marca y habilitar *Bypass* **solo en esa ventana**:<br>`Unblock-File ..\whatsapp-env.ps1`<br>`Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass`<br>`. "..\whatsapp-env.ps1"`<br>No se cambia la política de la máquina |
| El webhook procesa pero el teléfono no recibe nada | `WHATSAPP_MODO` quedó en `"falso"`: el canal usa el enviador de prueba y no llama a Meta | Poner `$env:WHATSAPP_MODO = "real"`, comprobar `[bool]$env:WHATSAPP_ACCESS_TOKEN` y reiniciar `make app` |

## 7. Al terminar

- [ ] Apagar el **modo evento** con `$env:WHATSAPP_EVENTO = "0"` y reiniciar
      `make app`: el canal vuelve a la lista cerrada y deja de responder a
      desconocidos.
- [ ] Borrar los datos de los invitados de OpenClaw al terminar. El script
      corre en modo de prueba por defecto y solo borra con `CONFIRMAR=1`: se
      corre el **viernes 27, después de los dos ensayos**, y el **sábado 28,
      después de la sustentación**:
      ```powershell
      make limpiar-evento                 # solo muestra qué borraría
      make limpiar-evento CONFIRMAR=1     # borra de verdad
      ```
      Lista y borra las sesiones del agente `pana`, olvida sus memorias
      derivadas (detiene el gateway un momento y lo vuelve a levantar), purga
      los archivos archivados de esas sesiones, borra `MEMORY.md`, `DREAMS.md`
      y todo el contenido de `memory\` del workspace —bitácora diaria,
      `dreaming\` y `.dreams\session-corpus\`, sin filtrar por extensión—, y
      borra `data/asistente/trazas/herramientas.jsonl`. No toca los archivos
      versionados (`SOUL`, `AGENTS`, `USER`, `IDENTITY`) ni los `.example`, no
      imprime el token ni el contenido de las sesiones y no borra la sesión
      principal `agent:pana:main`, que OpenClaw protege. **Sí conserva**
      `data/evaluacion/inyeccion.json`: es la evidencia de la tarea 3.5 que cita
      `docs/INYECCION.md` y no guarda el texto de las respuestas ni datos de
      invitados, así que se versiona junto con `proyeccion.json`.
      **Archivos archivados.** `sessions delete` guarda el transcript en las
      tablas `session_transcript_archives` y
      `session_transcript_cold_archives` de `openclaw-agent.sqlite`, dentro de
      WSL. `CONFIRMAR=1` activa también `-PurgarArchivos`: en la misma ventana
      en que el gateway está detenido para `memory forget`, python3 y el módulo
      `sqlite3` dentro de WSL comprueban que las dos tablas existan, hacen
      `DELETE FROM` en ellas, `PRAGMA wal_checkpoint(TRUNCATE)` y `VACUUM`, y
      reportan las filas borradas y el tamaño de la base antes y después. **No
      hay copia de respaldo de esas dos tablas**: una copia conservaría justo
      los datos que el consentimiento promete borrar. No se toca ninguna otra
      tabla. En modo de prueba solo se cuentan las filas; el conteo se ve con
      `powershell -NoProfile -ExecutionPolicy Bypass -File scripts\limpiar_evento.ps1 -PurgarArchivos`.
      Esa purga **se prueba el viernes 27 después de los ensayos**, antes de
      usarla en el evento del sábado 28.
      Al apagar el evento los consentimientos aceptados **se conservan**. Los
      perfiles, consentimientos y casos del canal de WhatsApp son de Darley y
      se borran aparte: el script no los toca.
- [ ] Si se usó el **modo En vivo** de la escena, apagar
      `$env:ESCENA_EN_VIVO = "0"`, salir de la pantalla con **E** y, con la app
      y el MCP detenidos, dejar que el mismo script borre
      `data/escena/en_vivo.jsonl` y su bloqueo
      `data/escena/en_vivo.lock`. La carpeta `data/escena/` se conserva y la
      escena proyectada se regenera aparte con `make escena-proyectada`. En
      modo de prueba el script solo lista esos dos archivos; con `CONFIRMAR=1`
      (o `-Confirmar`) los borra. Después se reinicia la app con
      `ESCENA_EN_VIVO` apagado.
- [ ] Ctrl + C en el túnel y quitar la URL del webhook en Meta.
- [ ] Apagar el gateway, el MCP y la app.
- [ ] Quitar las trazas si se encendieron:
  ```powershell
  Remove-Item Env:LANGSMITH_TRACING, Env:LANGSMITH_PROJECT, Env:LANGSMITH_API_KEY -ErrorAction SilentlyContinue
  ```
- [ ] Si un token o una clave (Meta, DeepSeek u `OPENCLAW_GATEWAY_TOKEN`)
      apareció en pantalla, en una captura o en un log: **rotarlo**.
- [ ] Cada teléfono del equipo escribe «olvida mis datos» si no se volverá a
      usar.
- [ ] Nada de `data/asistente/`, `data/escena/` ni de la memoria o la bitácora
      del workspace de OpenClaw se sube al repositorio.
- [ ] `git status` limpio: **no hacer commit de `config/whatsapp.toml` con
      huellas reales**. Para dejarlo como estaba:
  ```powershell
  git restore config/whatsapp.toml
  ```
- [ ] Cerrar la sesión de PowerShell donde estaban las claves.

## 8. Responsables

| Tarea | Responsable |
|---|---|
| Esta lista, la prueba de humo, la inyección en vivo y los invitados | Anny |
| Computador de la demo, gateway, MCP y tasas del Tablero; decide el plan B | Nayla |
| Meta, SIM, token, modo evento, túnel y callback | Darley |
| Escena en vivo: interruptor, código del voluntario y su tarjeta; entrada por voz (V) y ficha por WhatsApp | Darley |
| Pantalla, voces, solo subtítulos, cronómetro del pitch y capturas | Yoldy |
