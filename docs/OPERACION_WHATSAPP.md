# Operación del canal de WhatsApp

Guía completa para conectar la Sucursal 1965 con WhatsApp Cloud API: crear la app
de Meta, obtener credenciales, levantar el webhook, exponerlo con un túnel y
probar la recepción y la respuesta a mensajes reales.

Todo lo que se pega en Meta y todo lo que se ejecuta en PowerShell está marcado.
Los secretos van **solo** en la sesión: el proyecto no lee `.env`.

> Para el despliegue completo con número propio, túnel, webhook y modo evento,
> ver [`DESPLIEGUE_WHATSAPP.md`](./DESPLIEGUE_WHATSAPP.md).

## Alcance y estado

El canal vive en `src/banco_occidente_corpus/canal/` y reutiliza el grafo de la
Sucursal: WhatsApp es un transporte, no otra inteligencia.

| Pieza | Archivo | Estado |
|---|---|---|
| Contratos Pydantic | `canal/contratos.py` | completo |
| Verificación y firma del webhook | `canal/webhook.py`, `canal/firma.py` | completo |
| Identidad E.164 y huella HMAC | `canal/identidad.py` | completo |
| Consentimiento Ley 1581 | `canal/consentimiento.py` | completo |
| Envío falso y real | `canal/envio.py` | completo |
| Deduplicación, cola y despachador | `canal/cola.py`, `canal/despachador.py` | completo |

Con la cola y el despachador, un mensaje autorizado recibe respuesta del grafo.
En modo `falso` el envío se registra en `envios` pero no sale a WhatsApp; para
que el usuario lo reciba hay que usar `WHATSAPP_MODO=real`.

El **19 de noviembre de 2026** el circuito completo quedó verificado con un
mensaje real: 14 turnos respondidos, 3 consentimientos aceptados y 4 envíos
registrados en `data/asistente/whatsapp.sqlite`.

### Modo evento

La lista `[autorizados]` solo atiende a los números de prueba. El **modo evento**
abre el canal a cualquier número **durante una ventana**, sin saltarse la ley: el
primer mensaje recibe el aviso de la Ley 1581 y sin «Acepto» no se procesa nada.

| Control | Clave | Efecto |
|---|---|---|
| Ventana | `[evento] desde` / `hasta` | Fuera de la ventana vuelve la lista cerrada |
| Cuota por persona | `max_por_hora`, `max_por_usuario` | Aviso de cuota al excederse (30/hora y 40 en total) |
| Tope global | `max_total` | Cierra el evento completo (300 mensajes) |
| Interruptor | `activo` o `WHATSAPP_EVENTO=1` | El entorno manda sobre el TOML |
| Alcance | — | El mismo de la lista: entrevista, tarjeta y comité tras aceptar |

El envío real sigue exigiendo autorización: huella en `[autorizados]` o, en
evento, un mensaje entrante de esa huella dentro de la ventana de servicio de 24
horas que exige Meta. Así el bot nunca inicia una conversación.

El paso a paso de Meta, túnel, webhook y apagado está en
[`DESPLIEGUE_WHATSAPP.md`](./DESPLIEGUE_WHATSAPP.md); las pruebas viven en
`test/test_canal_evento.py`.

### Escena en vivo (`ESCENA`)

El voluntario escribe **`ESCENA` y el código de cuatro dígitos** de la sesión
por WhatsApp y su recorrido se publica en la lista que reproduce `escena.html`
en modo «En vivo». El comando se reconoce **después** del consentimiento y
**antes** de la entrevista, del escenario y del motor: cancela una entrevista a
medias y no se reenvía a Pana.

| Control | Valor | Efecto |
|---|---|---|
| Interruptor | `ESCENA_EN_VIVO=1` | Sin él, el comando responde «La escena en vivo no está activada» y no escribe nada |
| Código | `ESCENA_CODIGO` | Cuatro dígitos de la sesión, solo en la tarjeta del voluntario; sin código o con otro código el mensaje sigue su curso privado y no publica |
| Vigencia | `[evento] escena_ttl_minutos` (180) | Cada mensaje del voluntario renueva el vencimiento |
| Voluntarios | uno solo | Otro `ESCENA` no reemplaza al activo; se cambia reiniciando la app o al vencer |
| Orden | invitado, herramientas y Pana | El mensaje del invitado se publica antes del motor; la respuesta, después del envío |
| PII | `detectar_pii` y nombres | Un mensaje con teléfono, correo, documento o tarjeta no se publica; sí la frase fija de Pana |
| Borrado | `scripts/limpiar_evento.ps1 -Confirmar` | Borra `data/escena/en_vivo.jsonl` y `en_vivo.lock` |

El interruptor se consulta en cada publicación: apagarlo detiene la escritura
sin reiniciar la app, y la app y el MCP lo necesitan en su propio proceso. El
código nunca va en `config/`, no se versiona y no se registra en logs.

**Limitación conocida.** El MCP no sabe qué invitado llamó a una herramienta:
publica el turno, pero no el mensaje de quien lo provocó. Por eso, durante la
escena solo el voluntario hace el recorrido del crédito; los demás invitados
pueden saludar, preguntar por productos o pedir un asesor.

Las pruebas viven en `test/test_canal_escena_vivo.py` y
`test/test_escena_en_vivo_api.py`; la ruta solo responde en la app de
`127.0.0.1` y el túnel la deja fuera.

## Puesta en marcha desde cero

### 0. Antes de empezar

- Cuenta de Facebook con correo y teléfono verificados y 2FA activo.
- Los cinco números de prueba (los cuatro del grupo y el del profesor), con
  WhatsApp activo y sus dueños disponibles para confirmar el código.
- Un gestor de contraseñas para los valores que se generan.
- Windows con PowerShell y `uv` funcionando en el repositorio.

### 1. Crear la app en Meta (navegador)

1. Entra a `developers.facebook.com/apps` → **Create app**.
2. Caso de uso: **Conectarte con los clientes a través de WhatsApp**.
3. Nombre: `Sucursal 1965 UAO`. Correo de contacto: el del grupo.
4. Portafolio comercial: crea `Sucursal 1965 UAO` si no existe.
5. **Create app**.

Anota el **App ID** (aparece arriba, en el panel de la app).

> No crees varias apps ni varias cuentas de WhatsApp para “probar”: cada intento
> deja cuentas huérfanas. Si ya hay duplicados, conserva una y elimina el resto
> en **Business settings → Cuentas → Cuentas de WhatsApp**.

### 2. Agregar WhatsApp y obtener las credenciales (navegador)

1. En la app: **WhatsApp → Configurar**.
2. Entra a **Paso 1. Pruébalo**.
3. Copia de la pantalla:

| Dato | Dónde aparece | Secreto |
|---|---|---|
| Número de prueba | «Número de prueba» | No |
| **Phone Number ID** | debajo del número | No |
| **WABA ID** | «Identificador de la cuenta de mensajes» | No |
| Token temporal | «Token de acceso» | Sí (24 h) |

4. El **App Secret** está en **Configuración de la app → Básica → Clave secreta
   de la app → Mostrar**. Es secreto.

> No repitas el asistente «Create your WhatsApp profile»: si pide revisión de
> nombre (hasta 5 días), ciérralo. El número de prueba sale del Paso 1.

### 3. Token permanente de usuario del sistema (navegador)

1. `business.facebook.com/settings` → **Usuarios → Usuarios del sistema**.
2. **Agregar** → nombre `sucursal-1965-bot` → rol **Administrador**.
3. Si al generar el token dice **«No hay permisos disponibles»**:
   - Ve a **Cuentas → Apps → Agregar → Conectar un identificador de la app** y
     pega el App ID.
   - En **Usuarios del sistema → sucursal-1965-bot → Activos asignados →
     Asignar activos → Apps → la app → Administrar app**.
4. **Generar token** → selecciona la app → caducidad **60 días** → permisos:
   - `whatsapp_business_messaging`
   - `whatsapp_business_management`
5. Copia el token: no se vuelve a mostrar.

### 4. Inventar el Verify Token (PowerShell)

No lo da Meta. Debe ser **alfanumérico** (sin `ñ`, tildes, espacios ni signos),
porque viaja en una URL:

```powershell
# Cualquier cadena sirve; esta es una forma de generarla
-join ((48..57) + (97..122) | Get-Random -Count 24 | ForEach-Object { [char]$_ })
```

Guárdalo: se usa en `.ps1` y en Meta.

### 5. Variables de entorno (PowerShell, una sola vez)

Crea un archivo **fuera del repositorio**, por ejemplo un nivel arriba:

```
...\3.tecnicasAvanzadaDeIA_AplicadasEnModeloDeLenguaje\whatsapp-env.ps1
```

Contenido (con tus valores reales, sin `< >`):

```powershell
$env:WHATSAPP_PHONE_NUMBER_ID = "<phone-number-id>"
$env:WHATSAPP_APP_SECRET      = "el-app-secret"
$env:WHATSAPP_VERIFY_TOKEN    = "<token-alfanumerico>"
$env:WHATSAPP_ACCESS_TOKEN    = "el-token-permanente"
$env:WHATSAPP_ID_SALT         = "una-cadena-aleatoria-larga"
$env:WHATSAPP_MODO            = "falso"
# Opcional: enciende el modo evento sin editar el TOML.
# $env:WHATSAPP_EVENTO        = "1"
```

Cárgalo en cada ventana donde lo necesites:

```powershell
. "..\whatsapp-env.ps1"
```

Verifica que las variables existen:

```powershell
@("WHATSAPP_APP_SECRET","WHATSAPP_VERIFY_TOKEN","WHATSAPP_PHONE_NUMBER_ID","WHATSAPP_ACCESS_TOKEN","WHATSAPP_ID_SALT") |
  ForEach-Object { "$_ = $([bool](Get-Item "env:$_" -ErrorAction SilentlyContinue))" }
```

> El archivo contiene secretos: no se copia al repositorio, no se captura y no
> se comparte. Si el proyecto se comprime, comparte solo `ProyectoAvance1`.

> El detalle de cada variable, cómo generar `WHATSAPP_ID_SALT`, la precedencia
> entre el `.ps1`, la ventana y el TOML, y dónde se pega la URL del túnel está
> en [`DESPLIEGUE_WHATSAPP.md`](./DESPLIEGUE_WHATSAPP.md) §2 y §3.1.

### 6. Autorizar los cinco números (navegador)

1. **WhatsApp → Paso 1 → Envía un mensaje desde tu número de prueba → To**.
2. **Manage phone number list** → agrega cada número en formato internacional.
3. Cada persona recibe un código por WhatsApp y lo introduce.
4. El límite del número de prueba es **5 destinatarios**.

Sin el código, el número queda agregado pero no autorizado, y Meta descarta sus
mensajes.

Además de autorizarlo en Meta, el canal compara el remitente contra las huellas
de `config/whatsapp.toml` (sección `[autorizados]`). Para generar cada huella:

```powershell
uv run python -m banco_occidente_corpus.canal.identidad --huella "+57 300 123 4567"
```

El comando lee `WHATSAPP_ID_SALT` (la misma sal que carga `whatsapp-env.ps1` en
la ventana de la app), imprime solo la huella y no muestra la sal. La sal no se
pega en Meta ni la usa el túnel.

Pega la huella en `config/whatsapp.toml`, reemplazando uno de los marcadores:

```toml
[autorizados]
huellas = [
  "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "0000000000000000000000000000000000000000000000000000000000000002",
  # ...
]
```

Sin ese paso el número queda como no autorizado y el envío real se bloquea con
`ErrorEnvio: destino no autorizado`. La configuración se lee al arrancar: hay que
reiniciar la app después de editar el TOML.

### 7. Publicar la app (navegador) — obligatorio para mensajes reales

En **modo Desarrollo**, Meta solo entrega los eventos del botón «Probar». Los
mensajes reales se consideran datos de producción y **no llegan al webhook**.

1. Completa **Configuración de la app → Básica**:
   - **URL de la política de privacidad** (por ejemplo, la de la UAO o una
     página pública del proyecto).
   - Categoría, icono de 1024×1024, correo de contacto.
2. Arriba, activa el interruptor **«Activo»** (App Mode: Development → Live).
3. Si Meta pide revisión de la app o verificación del negocio, no la inicies a
   ciegas: documenta el bloqueo y consulta al grupo.

Publicar no cambia el número de prueba ni cobra nada: solo habilita la entrega
de datos reales al webhook.

### 8. Suscribir la cuenta de WhatsApp a la app (PowerShell)

La app debe estar suscrita a la WABA, además de tener el callback configurado.
Sin esto, el botón «Probar» funciona pero los mensajes reales no llegan.

```powershell
$uri = "https://graph.facebook.com/v23.0/<WABA_ID>/subscribed_apps?access_token=$($env:WHATSAPP_ACCESS_TOKEN)"
Invoke-RestMethod $uri | ConvertTo-Json -Depth 5      # consulta
Invoke-RestMethod -Method Post $uri | ConvertTo-Json  # suscribe
```

La consulta debe mostrar tu app en `data`. La suscripción responde
`{"success": true}`.

### 9. Levantar la app y el túnel (dos ventanas de PowerShell)

**Ventana 1 — la app** (desde la raíz del repositorio):

```powershell
. "..\whatsapp-env.ps1"
$env:WHATSAPP_MODO = "real"    # sin esto la respuesta se registra pero no sale
$env:WHATSAPP_EVENTO = "1"     # solo para abrir el modo evento
make app
```

Debe quedar en `http://127.0.0.1:8000`.

**Ventana 2 — el túnel** (desde cualquier carpeta):

```powershell
& "$HOME\cloudflared.exe" tunnel --url http://127.0.0.1:8000
```

Copia la URL `https://algo.trycloudflare.com` que imprime. El túnel rápido no
tiene URL fija: si se reinicia, cambia y hay que actualizar el callback. El
dominio estático de ngrok ya no está en el plan gratuito.

**Ventana 3 — pruebas** (desde la raíz del repositorio):

```powershell
. "..\whatsapp-env.ps1"
```

### 10. Registrar el callback en Meta (navegador)

En la app → **Webhooks** → objeto **`Whatsapp Business Account`** (no `User`).
Enlace directo, campo exacto y comprobación previa:
[`DESPLIEGUE_WHATSAPP.md`](./DESPLIEGUE_WHATSAPP.md) §3.1.

| Campo de Meta | Qué pegar |
|---|---|
| **URL de devolución de llamada** | `https://<url-del-tunel>/webhooks/whatsapp` |
| **Token de verificación** | el valor de `WHATSAPP_VERIFY_TOKEN` |
| **Campos del webhook** | activar **Suscribirse** en `messages` |

Pulsa **Verificar y guardar**. Meta hace un `GET` y debe responder 200 con el
`hub.challenge`; en la ventana 1 aparece la petición.

Es el **único** lugar de Meta donde se pega la URL del túnel. Si el túnel se
reinicia y cambia el subdominio, se repite solo este paso.

> Guardar la URL **no** suscribe la cuenta: son dos pasos distintos (el 8 y este).

### 11. Probar de punta a punta

Local, en la ventana 3:

```powershell
curl.exe "http://127.0.0.1:8000/webhooks/whatsapp?hub.mode=subscribe&hub.verify_token=$env:WHATSAPP_VERIFY_TOKEN&hub.challenge=12345"
```

Por el túnel:

```powershell
curl.exe "https://<url-del-tunel>/webhooks/whatsapp?hub.mode=subscribe&hub.verify_token=$env:WHATSAPP_VERIFY_TOKEN&hub.challenge=12345"
```

Ambos deben devolver `12345`. Después, desde un número autorizado, escribe
`hola` al número de prueba. En la ventana 1 debe aparecer:

```
POST /webhooks/whatsapp HTTP/1.1" 200 OK
```

El `POST 200` es la prueba de que Meta entrega, el túnel funciona y la firma es
válida. La respuesta del grafo sale por el enviador: en modo `falso` queda en la
base; en modo `real` llega al WhatsApp del usuario.

#### 11.1 La conversación completa

Con `WHATSAPP_MODO=real` y la huella del número en `config/whatsapp.toml`:

1. `hola` → aviso de la Ley 1581 con **Acepto** y **Ahora no**.
2. **Acepto** → confirmación; el consentimiento queda guardado.
3. Una pregunta del alcance (por ejemplo, «¿cuál es la cuota de manejo de la
   tarjeta débito?») → respuesta del grafo, con sus fuentes.

Si aparece `ErrorEnvio: destino no autorizado`, falta la huella del paso 6 o la
sal cambió desde que se generó.

## Diagnóstico de la respuesta

El texto del mensaje no se guarda ni se registra en logs: solo el estado y la
huella del número. Para saber qué pasó con un turno:

```powershell
@'
import sqlite3

with sqlite3.connect("data/asistente/whatsapp.sqlite") as c:
    print("mensajes:", c.execute("SELECT estado, COUNT(*) FROM mensajes GROUP BY estado").fetchall())
    print("consentimientos:", c.execute("SELECT COUNT(*) FROM consentimientos").fetchone()[0])
    print("envios:", c.execute("SELECT COUNT(*) FROM envios").fetchone()[0])
'@ | uv run python -
```

Estados posibles:

| Estado | Significado |
|---|---|
| `recibido` | registrado y encolado |
| `procesando` | el trabajador lo tomó |
| `respondido` | la respuesta se entregó al enviador |
| `ignorado` | número fuera de las huellas o duplicado |
| `error` | falló el grafo, el envío o la firma no se pudo validar |

Si hay `error`, mira la ventana de la app: el `logger.exception` del despachador
muestra la causa sin el número ni el texto. Los errores más comunes son
`destino no autorizado` (falta la huella) y fallos de credenciales de Meta.

## Estado verificado

Configuración comprobada el **19 de noviembre de 2026**:

| Dato | Valor |
|---|---|
| App | `Prueba1`, publicada (App Mode: Live) |
| Portafolio | `Sucursal 1965 UAO` |
| WABA | suscrita a `Prueba1` con `subscribed_apps` |
| Número de prueba | número de Meta del Paso 1 |
| Phone Number ID | el del Paso 1 |
| Webhook | verificado con `hub.challenge` |
| Entrega real | `POST /webhooks/whatsapp 200 OK` |
| Respuesta real | 14 turnos respondidos, 3 consentimientos y 4 envíos |
| Túnel | cloudflared rápido (URL variable) |

Los identificadores y el número de la tabla son de ejemplo: los reales se leen
en Meta y no se versionan, porque el repositorio es público.

Los secretos (App Secret, tokens, sal) no se documentan aquí.

## Modos falso y real

- **`falso`** (por defecto): `EnviadorFalso` registra el envío en
  `data/asistente/whatsapp.sqlite` y devuelve `fake:<uuid>`. Es el modo de la
  suite y de los ensayos.
- **`real`**: `EnviadorMeta` hace `POST` a `graph.facebook.com` con `timeout` de
  10 s, User-Agent, header `From` y reintentos solo en 429/5xx. Exige que el
  destino esté entre las huellas autorizadas.

```powershell
$env:WHATSAPP_MODO = "real"
```

### Recorrido simulado (sin Meta)

`make simular` recorre el canal con las personas sintéticas de
`data/evaluacion/personas_sinteticas.json` sin tocar Meta ni abrir puertos:
firma cada mensaje, lo entrega al webhook real dentro del proceso y registra las
respuestas con `EnviadorFalso`. A cada persona le envía el saludo, **Acepto**, su
entrevista, «¿Y si lo pago en 60 meses?», «olvida mis datos» y un reintento del
primer mensaje, y verifica una respuesta por turno, el semáforo esperado, la
tarjeta, la revocación y que el número no quede en la base. Usa un App Secret y
una sal ficticios y una base temporal, así que no necesita las variables del
canal ni toca `data/asistente/`. Sin `DEEPSEEK_API_KEY`, amarillo y rojo salen
sin comité. `--solo <id>` simula una sola persona; el comando termina con
código 0 si todas pasan.

```powershell
make simular
uv run python -m banco_occidente_corpus.simulador --solo pensionado_amarillo
```

Para mandar **un mensaje suelto** por el mismo webhook, sin Meta y sin abrir
puertos, con la app simulada dentro del proceso:

```powershell
uv run python scripts/mandar_falso.py "hola"
uv run python scripts/mandar_falso.py --boton consent:acepto Acepto
uv run python scripts/mandar_falso.py "ESCENA 1965"
```

El script firma el cuerpo con un App Secret de la corrida, usa el
`TestClient` de FastAPI y acepta `--numero`. Con la ventana de `[evento]`
abierta, `ESCENA_EN_VIVO=1` y el código de la sesión en `ESCENA_CODIGO`, sirve
para ensayar la escena en vivo antes de conectar Meta. `1965` es solo el
ejemplo del contrato: usa el código que tenga la sesión.

### Ensayo con WhatsApp real (evidencia aparte)

El recorrido sintético y el ensayo real no compiten: prueban cosas distintas y
se registran por separado.

- **Sintético (`make simular`, `EnviadorFalso`):** demuestra que el canal
  completo responde una sola vez por turno, con las personas sintéticas, sin
  Meta y sin red. Es la evidencia de `make check` y de la tarea 9.3.
- **Real (`WHATSAPP_MODO=real`, `EnviadorMeta`):** demuestra que Meta entrega y
  que el número autorizado recibe la respuesta. Exige app publicada, token
  vigente, huellas autorizadas y consentimiento. Se registra en «Estado
  verificado» con fecha y conteos, y en `docs/LISTA_DEMO.md` como ensayo
  general; **nunca** se convierte en una prueba automática ni en requisito de
  `make check`.

El ensayo real del **19 de noviembre de 2026** está en «Estado verificado»
(14 turnos respondidos, 3 consentimientos y 4 envíos). Ese registro no cambia el
texto de la tarea 9.3: la casilla sigue midiendo el recorrido sintético, porque
una prueba que depende de Meta no es reproducible ni corre en CI.

## Flujo de un mensaje

1. Meta hace `POST /webhooks/whatsapp` con el cuerpo crudo firmado.
2. El canal valida `X-Hub-Signature-256` y responde 200 de inmediato.
3. El número se normaliza a E.164 y se convierte en `usuario_id`.
4. Sin consentimiento, se envía el aviso de la Ley 1581 con «Acepto» y «Ahora
   no»; sin aceptación no se invoca el grafo.
5. Con consentimiento, el despachador decide si el turno va al grafo de
   preguntas, al diagnóstico o a un asesor. Si hay un caso del HITL suspendido,
   los botones «Contactar» y «Descartar» lo reanudan antes que nada.

## Problemas frecuentes

| Síntoma | Causa probable |
|---|---|
| Meta no verifica el callback | Túnel caído, URL sin `/webhooks/whatsapp` o token distinto |
| `GET` devuelve 503 | Falta `WHATSAPP_VERIFY_TOKEN` en la ventana de la app |
| «Invalid HTTP request received» | El token tiene caracteres no alfanuméricos (ñ, espacios, signos) |
| El botón «Probar» genera `POST 200` pero los mensajes reales no | App en modo Desarrollo o WABA sin `subscribed_apps` |
| `POST` devuelve 401 | App Secret distinto o cuerpo reserializado |
| `POST` devuelve 503 | Falta `WHATSAPP_APP_SECRET` |
| Dos checks grises y nada en el webhook | Falta suscribir la cuenta a la app (paso 8) |
| `ErrorEnvio: destino no autorizado` | Falta la huella del número en `config/whatsapp.toml` o cambió la sal |
| Estado `respondido` pero no llega a WhatsApp | Estás en modo `falso`: el envío quedó en `envios` y no salió |
| `hola` no recibe el aviso | La app no arrancó con `WHATSAPP_ID_SALT` o con la huella correcta |

## Seguridad y datos personales

- El número en claro solo existe en memoria; se persiste la huella HMAC.
- El token, el App Secret y la sal no se escriben en logs, en la base ni en el
  repositorio.
- El perfil (nombre y rol) vive fuera de Git y no se envía al modelo.
- El túnel se apaga al terminar cada ensayo; el servidor sigue en `127.0.0.1`.
- Si un token apareció en una captura o en un log, se rota.
- Los mensajes entrantes y los fragmentos son datos, nunca instrucciones.

## Limitaciones conocidas

- El número de prueba permite escribir a cinco destinatarios y solo dentro de la
  ventana de 24 h desde el último mensaje del usuario.
- No se admiten llamadas, audios, imágenes ni pagos.
- El túnel rápido cambia de URL al reiniciarse.
- No hay verificación empresarial ni número de producción: es una demo
  académica.
