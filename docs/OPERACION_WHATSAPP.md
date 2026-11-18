# Operación del canal de WhatsApp

Guía completa para conectar la Sucursal 1965 con WhatsApp Cloud API: crear la app
de Meta, obtener credenciales, levantar el webhook, exponerlo con un túnel y
probar la recepción de mensajes reales.

Todo lo que se pega en Meta y todo lo que se ejecuta en PowerShell está marcado.
Los secretos van **solo** en la sesión: el proyecto no lee `.env`.

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
| Deduplicación, cola y despachador | tareas 2.3 y 2.9 | en curso |

Mientras la cola y el despachador no estén en `main`, el webhook valida la firma
y responde `200 EVENT_RECEIVED`, pero todavía no responde al usuario.

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

El comando lee `WHATSAPP_ID_SALT`, imprime solo la huella y no muestra la sal.

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

En la app → **Webhooks** → objeto **`Whatsapp Business Account`** (no `User`):

| Campo de Meta | Qué pegar |
|---|---|
| **URL de devolución de llamada** | `https://<url-del-tunel>/webhooks/whatsapp` |
| **Token de verificación** | el valor de `WHATSAPP_VERIFY_TOKEN` |
| **Campos del webhook** | activar **Suscribirse** en `messages` |

Pulsa **Verificar y guardar**. Meta hace un `GET` y debe responder 200 con el
`hub.challenge`; en la ventana 1 aparece la petición.

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

Ese `POST 200` es la prueba de que Meta entrega, el túnel funciona y la firma es
válida. La respuesta al usuario llega con las tareas 2.3 y 2.9.

## Estado verificado

Configuración comprobada el **17 de noviembre de 2026**:

| Dato | Valor |
|---|---|
| App | `Prueba1` · App ID `000000000000000` · publicada |
| Portafolio | `Sucursal 1965 UAO` |
| WABA ID | `000000000000000`, suscrita a `Prueba1` |
| Número de prueba | `+1 (555) 555-0100` |
| Phone Number ID | `000000000000001` |
| Webhook | verificado con `hub.challenge` |
| Entrega real | `POST /webhooks/whatsapp 200 OK` |
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

## Flujo de un mensaje

1. Meta hace `POST /webhooks/whatsapp` con el cuerpo crudo firmado.
2. El canal valida `X-Hub-Signature-256` y responde 200 de inmediato.
3. El número se normaliza a E.164 y se convierte en `usuario_id`.
4. Sin consentimiento, se envía el aviso de la Ley 1581 con «Acepto» y «Ahora
   no»; sin aceptación no se invoca el grafo.
5. Con consentimiento, el despachador decide si el turno va al grafo de
   preguntas, al diagnóstico o a un asesor.

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
