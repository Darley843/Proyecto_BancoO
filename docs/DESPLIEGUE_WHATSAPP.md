# Despliegue del canal de WhatsApp (Meta + túnel + modo evento)

Guía única para poner el canal en producción con un número propio, levantar el
túnel, verificar el webhook y abrir el **modo evento** sin saltarse el
consentimiento. Complementa [`OPERACION_WHATSAPP.md`](./OPERACION_WHATSAPP.md),
que explica el diseño del canal; aquí están los pasos y los enlaces.

Todo lo que se pega en Meta está marcado con **Meta**; lo que se ejecuta en
PowerShell, con **PowerShell**. Los secretos van **solo** en
`whatsapp-env.ps1`, fuera del repositorio.

## 0. Ruta rápida (dos ventanas)

| # | Dónde | Qué haces |
|---|---|---|
| 1 | PowerShell | Crear `..\whatsapp-env.ps1` fuera del repo (§2.1) |
| 2 | PowerShell (ventana 1) | `cd` al repo, cargar el `.ps1`, `$env:WHATSAPP_MODO = "real"` y `make app` (§6) |
| 3 | PowerShell (ventana 2) | `cloudflared tunnel --url http://127.0.0.1:8000` y copiar la URL (§5) |
| 4 | Meta | Pegar `https://<url>/webhooks/whatsapp` en **Webhook → Editar → URL de devolución de llamada** (§3.1 y §4.5) |
| 5 | WhatsApp | Escribir «hola» desde un número autorizado (§7) |

La URL del túnel se pega en **un solo lugar de Meta**: el webhook de la app. No
va en el «Paso 1», ni en WhatsApp Manager, ni en `whatsapp-env.ps1`.

## 1. Datos del canal (sin secretos)

Los identificadores reales **no viven en el repositorio**: este documento los
muestra como marcadores y los valores verdaderos van en `whatsapp-env.ps1`, un
nivel arriba del proyecto y fuera de Git.

| Dato | Marcador | Dónde se usa |
|---|---|---|
| App | `Prueba1` (App ID `<APP_ID>`) | developers.facebook.com |
| Cuenta de WhatsApp (WABA) | `<WABA_ID>` | WhatsApp Manager |
| Número del canal | `<NUMERO_DEL_BOT>` | Los invitados escriben aquí |
| `PHONE_NUMBER_ID` | `<PHONE_NUMBER_ID>` | `WHATSAPP_PHONE_NUMBER_ID` |
| Nombre visible | `Sucursal 1965 UAO` | Revisión de Meta |
| `name_status` | `AVAILABLE_WITHOUT_REVIEW` | No requiere revisión |

> Los valores de los marcadores salen del panel de Meta (sección 3) y se copian
> solo en `whatsapp-env.ps1`. El número de prueba compartido de Meta se conserva
> como respaldo, con su propio límite de 5 destinatarios. No se elimina.

## 2. Variables de entorno: archivo, carga y precedencia

### 2.1 Dónde vive el archivo

`whatsapp-env.ps1` está **un nivel arriba** de `ProyectoAvance1`, nunca dentro
del repositorio:

```text
3.tecnicasAvanzadaDeIA_AplicadasEnModeloDeLenguaje\
├── whatsapp-env.ps1        ← credenciales (fuera de Git)
└── ProyectoAvance1\        ← este repositorio
```

Ruta absoluta típica:

```text
D:\...\SegundoSemestre\3.tecnicasAvanzadaDeIA_AplicadasEnModeloDeLenguaje\whatsapp-env.ps1
```

Si no existe, se crea una vez:

```powershell
cd "D:\...\3.tecnicasAvanzadaDeIA_AplicadasEnModeloDeLenguaje"
notepad whatsapp-env.ps1
```

`.env` **no** se usa: el proyecto no lo lee (`docs/SEGURIDAD.md` §4).

### 2.2 Contenido del archivo

```powershell
# Fuera del repositorio. No se versiona y no se comparte.
$env:WHATSAPP_PHONE_NUMBER_ID = "<PHONE_NUMBER_ID>"
$env:WHATSAPP_APP_SECRET      = "<App Secret de Prueba1>"
$env:WHATSAPP_VERIFY_TOKEN    = "<token alfanumérico inventado>"
$env:WHATSAPP_ACCESS_TOKEN    = "<token del usuario del sistema>"
$env:WHATSAPP_ID_SALT         = "<sal aleatoria, no se cambia nunca>"

# Modo seguro por defecto: no sale a Meta hasta que la ventana lo cambie.
$env:WHATSAPP_MODO            = "falso"
# Opcional: enciende el modo evento sin editar el TOML.
# $env:WHATSAPP_EVENTO        = "1"
```

Generar la sal una sola vez (48 caracteres alfanuméricos):

```powershell
-join ((48..57) + (65..90) + (97..122) | Get-Random -Count 48 |
  ForEach-Object { [char]$_ })
```

| Variable | Para qué sirve | Secreta | Si está mal |
|---|---|---|---|
| `WHATSAPP_PHONE_NUMBER_ID` | Número desde el que responde el bot | No | El envío falla con `400`/`404` |
| `WHATSAPP_APP_SECRET` | Verifica `X-Hub-Signature-256` | Sí | Meta recibe `403`; no entra ningún mensaje |
| `WHATSAPP_VERIFY_TOKEN` | Reto `GET` del webhook | Trátala como secreta | «Verificar y guardar» falla |
| `WHATSAPP_ACCESS_TOKEN` | Enviar respuestas por `graph.facebook.com` | Sí | El mensaje entra, la respuesta falla con `401` |
| `WHATSAPP_ID_SALT` | `usuario_id = HMAC-SHA256(número, sal)` | Sí, irrecuperable | Si falta, el canal no procesa (200 y silencio); si cambia, se invalidan huellas y consentimientos |
| `WHATSAPP_MODO` | `falso` registra sin enviar; `real` envía | No | En `falso` el teléfono no recibe nada |
| `WHATSAPP_EVENTO` | `1` enciende el modo evento; `0` lo apaga | No | Manda sobre `[evento] activo`, pero no mueve `desde`/`hasta` |

**La sal no se cambia.** Las huellas de `config/whatsapp.toml` y los
consentimientos guardados se calculan con ella; otra sal produce otros
`usuario_id` y deja los consentimientos huérfanos. Si se pierde, hay que
regenerar todas las huellas con `--huella` (§7.2).

**La sal tampoco se configura aparte.** Viaja dentro de `whatsapp-env.ps1`, que
es el mismo archivo que se carga en la ventana de la app; no se pega en Meta y
el túnel no la usa. Si la app arranca sin `WHATSAPP_ID_SALT`, `app.py` no crea
el despachador: el webhook responde `200` pero no procesa nada y el teléfono
queda en silencio.

### 2.3 Cómo se cargan en la ventana

Las variables viven **solo en la ventana de PowerShell** donde se cargan. Cada
ventana nueva empieza sin ellas. Desde la carpeta del repo:

```powershell
cd "D:\...\ProyectoAvance1"
. "..\whatsapp-env.ps1"
```

El punto inicial (`.`) ejecuta el archivo en la sesión actual. Si PowerShell
bloquea el script por la política de ejecución:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
. "..\whatsapp-env.ps1"
```

Comprobar sin imprimir secretos:

```powershell
@("WHATSAPP_PHONE_NUMBER_ID","WHATSAPP_APP_SECRET","WHATSAPP_VERIFY_TOKEN",
  "WHATSAPP_ACCESS_TOKEN","WHATSAPP_ID_SALT") |
  ForEach-Object { "$_ = $([bool](Get-Item "env:$_" -ErrorAction SilentlyContinue))" }

# No son secretos: se pueden mostrar.
"WHATSAPP_MODO   = $env:WHATSAPP_MODO"
"WHATSAPP_EVENTO = $env:WHATSAPP_EVENTO"
```

### 2.4 Precedencia

1. `whatsapp-env.ps1` define los valores base.
2. Una asignación posterior en la **misma** ventana gana:
   `$env:WHATSAPP_MODO = "real"`, `$env:WHATSAPP_EVENTO = "1"`.
3. Si la variable no existe, manda `config/whatsapp.toml` (`canal.modo`,
   `[evento] activo`).
4. `make app` hereda el entorno de esa ventana; no lee el `.ps1` por su cuenta.

## 3. Enlaces de Meta

Sustituye `<APP_ID>` por el App ID de `Prueba1` (no se guarda en el
repositorio).

| Qué | Enlace |
|---|---|
| Panel de apps | <https://developers.facebook.com/apps/> |
| App `Prueba1` | `https://developers.facebook.com/apps/<APP_ID>/` |
| **Webhook: aquí se pega la URL del túnel** | `https://developers.facebook.com/apps/<APP_ID>/whatsapp-business/wa-settings/` |
| Configuración de la API (Paso 1) | `https://developers.facebook.com/apps/<APP_ID>/whatsapp-business/wa-dev-console/` |
| Webhooks de la app (objeto WABA) | `https://developers.facebook.com/apps/<APP_ID>/webhooks/` |
| WhatsApp Manager → Números de teléfono | <https://business.facebook.com/wa/manage/phone-numbers/> |
| Configuración del negocio (personas, activos, sistema) | <https://business.facebook.com/settings/> |
| Usuarios del sistema (token permanente) | <https://business.facebook.com/settings/system-users> |

> El botón `+ Agregar` de **Business Settings → Cuentas de WhatsApp** crea otra
> WABA, no un número. Los números se agregan desde el panel de la app o desde
> WhatsApp Manager.

### 3.1 Dónde se pega la URL del túnel

La URL del túnel se escribe **una sola vez**, en el webhook de la app:

1. Abre
   `https://developers.facebook.com/apps/<APP_ID>/whatsapp-business/wa-settings/`
   (o **Panel de apps → Prueba1 → WhatsApp → Configuración**).
2. Baja a la tarjeta **Webhook** y pulsa **Editar**.
3. En **URL de devolución de llamada** pega
   `https://<url-del-túnel>/webhooks/whatsapp`. El path es obligatorio; no
   agregues `/` al final y no uses `127.0.0.1` ni `localhost`.
4. En **Token de verificación** pega el valor de `WHATSAPP_VERIFY_TOKEN`.
5. Pulsa **Verificar y guardar**. Meta hace un `GET /webhooks/whatsapp`; debe
   quedar en verde y aparecer `GET /webhooks/whatsapp ... 200 OK` en la ventana
   de la app. La app y el túnel tienen que estar arriba **antes** de pulsar.
6. Confirma que el campo **`messages`** está suscrito.

Si tu panel muestra el menú **Webhooks** de la app
(`https://developers.facebook.com/apps/<APP_ID>/webhooks/`), el objeto es
**`WhatsApp Business Account`**, no `User`: allí está el mismo campo.

No hay otro lugar en Meta donde vaya la URL. El **Paso 1** (`wa-dev-console`)
no la pide y WhatsApp Manager solo administra números.

> Cada vez que se reinicia el túnel rápido cambia el subdominio. Si eso pasa,
> repite solo estos seis pasos: no hay que tocar tokens, números ni el `.ps1`.

## 4. Meta, paso a paso

### 4.1 Agregar el número

**Meta** → App `Prueba1` → **WhatsApp** → **Paso 2: Configuración de producción**
→ `Registra tu número de teléfono de WhatsApp` → **Agregar número de teléfono**.

| Campo | Valor |
|---|---|
| Número | `+57` y los 10 dígitos |
| Nombre visible | `Sucursal 1965 UAO` |
| Categoría | la de la app |
| Descripción | la de la app |

El número debe **no haber tenido WhatsApp** y la SIM debe recibir **SMS o
llamada**. Si Meta dice que ya está registrado, la SIM es reciclada: se cambia.

### 4.2 Verificar el número

Meta envía un código por **SMS**; si no llega en dos minutos, por **llamada de
voz**. Al terminar, el número queda `Registrado` y aparece el
`PHONE_NUMBER_ID` que va en `WHATSAPP_PHONE_NUMBER_ID`.

### 4.3 Nombre visible

Se envía en el mismo formulario. Estados posibles:

| `name_status` | Significa |
|---|---|
| `AVAILABLE_WITHOUT_REVIEW` | Sin revisión pendiente; se usa ya |
| `PENDING_REVIEW` | En revisión (24 h – 5 días) |
| `APPROVED` | Aprobado |
| `REJECTED` | Rechazado; hay que cambiarlo |

El nombre no puede suplantar una marca: `Sucursal 1965 UAO` pasa; cualquier
variante con el nombre del banco no.

### 4.4 Suscribir la WABA a la app

**Meta** → mismo panel → tarjeta de la cuenta → interruptor **`Suscribir
webhooks`** en verde.

Sin esta suscripción, la app recibe los eventos del botón «Probar» pero **no los
mensajes reales**. Es el error más común: el webhook está configurado, pero la
cuenta no está suscrita.

Verificación (PowerShell), con el **WABA ID**, no el Messaging Account ID:

```powershell
$base = "https://graph.facebook.com/v23.0"
$tok  = $env:WHATSAPP_ACCESS_TOKEN
$waba = "<WABA_ID>"

Invoke-RestMethod "$base/$waba/subscribed_apps?access_token=$tok" | ConvertTo-Json -Depth 6
```

Debe listar `Prueba1` con el App ID `<APP_ID>`. Si responde
`(#200) Provide valid app ID`, el ID no es la WABA o la app no está asignada:
**Configuración → Cuentas → Cuentas de WhatsApp → la cuenta → Asignar
activos → Apps → Prueba1**.

### 4.5 Webhook (callback)

**Meta** → App `Prueba1` → **WhatsApp** → **Configuración** → tarjeta
**Webhook** → **Editar**. Enlace directo en §3.1.

| Campo | Valor |
|---|---|
| URL de devolución de llamada | `https://<url-del-túnel>/webhooks/whatsapp` |
| Token de verificación | el de `WHATSAPP_VERIFY_TOKEN` |

Pulsa **Verificar y guardar**: Meta hace un `GET /webhooks/whatsapp` y debe
responder `200` con el `hub.challenge`. Después confirma que el campo
**`messages`** está suscrito.

Antes de pulsar, comprueba el camino completo desde fuera:

```powershell
curl.exe "https://<url-del-túnel>/health"
```

Si ese comando no responde `200`, Meta tampoco podrá verificar. Revisa que la
app escuche en `127.0.0.1:8000` y que el túnel apunte a ese puerto.

> La URL cambia cada vez que se reinicia el túnel rápido de Cloudflare. Si
> cambia, hay que volver a editar el callback. Para el evento, usar un túnel con
> nombre fijo.

### 4.6 Token del usuario del sistema

**Meta** → <https://business.facebook.com/settings/system-users> → usuario
`sucursal-1965-bot` → **Generar token** → app `Prueba1` → caducidad 60 días →
permisos `whatsapp_business_messaging` y `whatsapp_business_management`.

Se guarda en `whatsapp-env.ps1` y se comparte **solo** por gestor de secretos.
Comprobar vigencia y app:

```powershell
$base = "https://graph.facebook.com/v23.0"
$tok  = $env:WHATSAPP_ACCESS_TOKEN

Invoke-RestMethod "$base/debug_token?input_token=$tok&access_token=$tok" |
  Select-Object -ExpandProperty data | Select-Object app_id, expires_at, scopes
```

### 4.7 Información de pago (opcional)

Necesaria solo para **mensajes iniciados por la empresa** (plantillas). Los
mensajes de servicio —el invitado escribe primero— son gratuitos. Si se agrega,
usar tarjeta del grupo o virtual y fijar un **límite de gasto** en Facturación.

## 5. Levantar el túnel (ventana 2)

Se abre **después** de la app (o antes, pero debe quedar arriba antes de
verificar el webhook):

```powershell
& "$HOME\cloudflared.exe" tunnel --url http://127.0.0.1:8000
```

Copia la URL `https://algo.trycloudflare.com` y actualiza el callback del punto
4.5. El túnel apunta a `127.0.0.1:8000`; si la app se reinicia en el mismo
puerto, la URL no cambia y Meta sigue funcionando.

> **Qué queda público.** El túnel rápido publica todo el origen, pero la app
> solo deja pasar `/webhooks/whatsapp` y `/health` cuando la petición viene de
> Cloudflare; `/api/...`, `/docs` y la pantalla responden `404`. No hay que
> configurar nada: la guarda vive en `app.py` y su detalle y residual están en
> [`SEGURIDAD.md`](./SEGURIDAD.md) §3.12.

Comprobar desde fuera, con la app y el túnel arriba:

```powershell
curl.exe "https://<url-del-túnel>/health"        # 200, o 503 si falta el índice
curl.exe -s -o NUL -w "%{http_code}" "https://<url-del-túnel>/api/estado"
# 404: la API no es pública
```

Si `cloudflared` no está instalado:

```powershell
winget install --id Cloudflare.cloudflared -e
# o
Invoke-WebRequest -Uri "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe" `
  -OutFile "$HOME\cloudflared.exe"
```

Copia la URL que imprime el recuadro, por ejemplo
`https://algo-nuevo.trycloudflare.com`, y actualiza el callback del punto 4.5.

- El túnel apunta a `127.0.0.1:8000`; si la app se reinicia en el mismo puerto,
  la URL no cambia y Meta sigue funcionando.
- **No cierres esta ventana.** El túnel rápido cambia de subdominio en cada
  arranque; si se cae o se reinicia, la URL cambia y hay que repetir §3.1.
- Esta ventana **no** necesita `whatsapp-env.ps1`: el túnel no lee credenciales.

Comprobar de punta a punta:

```powershell
curl.exe "https://<url-del-túnel>/health"
```

## 6. Levantar la app (ventana 1)

Todo en la **misma** ventana: cargar el `.ps1`, fijar el modo y arrancar.

```powershell
cd "D:\...\ProyectoAvance1"
. "..\whatsapp-env.ps1"        # credenciales (una vez por ventana)
$env:WHATSAPP_MODO = "real"    # envía de verdad por Meta
$env:WHATSAPP_EVENTO = "1"     # solo si vas a abrir el modo evento
make app
```

Debe quedar en `http://127.0.0.1:8000` y escuchar **solo** en loopback:

```powershell
curl.exe "http://127.0.0.1:8000/health"
```

Notas de orden:

- El `.ps1` se carga **primero**; las asignaciones `$env:` posteriores ganan en
  esa ventana (§2.4).
- Si abres otra ventana para `make app`, vuelve a cargar el `.ps1`: las
  variables no se heredan entre ventanas.
- Sin `WHATSAPP_ID_SALT` en esa ventana, la app arranca pero el canal queda
  apagado: el webhook responde `200` y el teléfono no recibe nada.
- `make app` **no recarga código**: tras cambiar código, `config/whatsapp.toml`,
  huellas o variables, hay que reiniciarlo.
- `WHATSAPP_EVENTO` solo enciende el interruptor; la ventana `desde`/`hasta`
  sigue saliendo del TOML (§8).

### 6.1 Qué reiniciar y qué no

| Pieza | ¿Reiniciar al cambiar código o variables? | Por qué |
|---|---|---|
| App (`make app`) | Sí | Lee el entorno y la configuración al arrancar |
| Túnel (`cloudflared`) | No | Apunta a `127.0.0.1:8000`; si la app vuelve al mismo puerto, la URL no cambia |

La única excepción es que el túnel se caiga o se cierre: al levantarlo de nuevo
cambia la URL y hay que repetir §3.1 en Meta. Por eso se deja esa ventana
quieta.

## 7. Pruebas del canal

### 7.1 Negativa: número no autorizado

Con el modo evento **apagado**, escribir desde un teléfono que no esté en
`[autorizados]`.

| Dónde | Esperado |
|---|---|
| Consola | `POST /webhooks/whatsapp 200` y `destino no autorizado para el modo real` |
| Teléfono | Silencio |

Que el teléfono no reciba nada es **correcto**: el envío real solo autoriza
destinos de la lista. La prueba demuestra Meta → túnel → firma → bloqueo.

### 7.2 Positiva: número autorizado

1. Generar la huella:

```powershell
uv run python -m banco_occidente_corpus.canal.identidad --huella "+57XXXXXXXXXX"
```

2. Pegarla en `config/whatsapp.toml` → `[autorizados] huellas` (sin commitear).
3. Reiniciar `make app` (la configuración se lee al arrancar).
4. Escribir «hola»: debe llegar el aviso de la Ley 1581 con `Acepto` / `Ahora no`
   y, tras aceptar, la respuesta del grafo con su fuente.

## 8. Modo evento

Abre el canal a cualquier número durante una ventana, con consentimiento previo,
cuota por persona y tope global. El alcance es el **mismo** que el de la lista:
quien acepta recorre la entrevista, el diagnóstico con su tarjeta y el comité.
El evento solo cambia la puerta de entrada, los contadores y el cierre.

### 8.1 Dónde se configura

El modo evento se configura en **dos lugares** y no son intercambiables:

| Qué | Dónde | Qué controla |
|---|---|---|
| Ventana, cuotas y estado inicial | `config/whatsapp.toml`, sección `[evento]` | `desde`, `hasta`, `max_por_hora`, `max_por_usuario`, `max_total` y `activo` |
| Encendido rápido | `WHATSAPP_EVENTO` en PowerShell | Solo `activo`; **no** mueve las fechas |

`config/whatsapp.toml` termina con:

```toml
[evento]
activo = false
desde = "2026-11-28T08:00:00-05:00"
hasta = "2026-11-28T20:00:00-05:00"
max_por_hora = 30
max_por_usuario = 40
max_total = 300
```

Para el ensayo del **sábado 28 de noviembre** deja esas fechas y enciende con
`WHATSAPP_EVENTO=1` o con `activo = true`. La ventana cubre la jornada completa
(08:00 a 20:00, hora de Colombia); el tope global de 300 mensajes y las cuotas
por persona son los que limitan el gasto, no la hora de cierre.

Para **probar antes del evento**, cambia la ventana para que cubra el momento de
la prueba y reinicia `make app`:

```toml
[evento]
activo = true
desde = "2026-11-26T00:00:00-05:00"
hasta = "2026-11-26T23:59:00-05:00"
```

> Las fechas llevan zona horaria. Sin `-05:00` se interpretan como UTC, no como
> hora de Colombia. La configuración se lee al arrancar: después de editar el
> TOML hay que reiniciar `make app`.

En la **misma ventana** de PowerShell donde se arranca la app:

```powershell
. "..\whatsapp-env.ps1"
$env:WHATSAPP_EVENTO = "1"    # WHATSAPP_EVENTO=0 apaga y manda sobre el TOML
$env:WHATSAPP_MODO = "real"
make app
```

`WHATSAPP_EVENTO` manda sobre `activo` del TOML, pero **no** sobre `desde` ni
`hasta`. Si el interruptor está en `1` y la ventana no cubre el momento, el
número desconocido sigue sin recibir respuesta aunque el webhook reciba el
`POST 200`.

### 8.2 Qué cambia

| Pieza | Lista cerrada | Modo evento |
|---|---|---|
| Autorización | Solo `[autorizados]` | Cualquier número dentro de la ventana |
| Primer mensaje | «no autorizado» | Aviso de la Ley 1581 |
| Sin «Acepto» | — | No se procesa nada |
| Cuota | No aplica | 30/hora y 40 en total por persona |
| Tope global | No aplica | 300 mensajes |
| Diagnóstico | Completo | Completo: entrevista, tarjeta y comité |
| Envío real | Solo huellas | Huellas o ventana de servicio de 24 h |

El costo de la ventana está acotado por los contadores: cada mensaje cuesta
alrededor de 0,2 centavos, así que los 300 del tope global suman menos de un
dólar.

### 8.3 Apagar

```powershell
$env:WHATSAPP_EVENTO = "0"
# o editar activo = false en el TOML
# y reiniciar make app
```

Al apagarlo, el canal vuelve a la lista cerrada y deja de responder a
desconocidos. Los consentimientos ya aceptados se conservan.

### 8.4 Antes del evento

```powershell
uv run pytest test/test_canal_evento.py -q   # ventana, cuotas y alcance
make check                                    # lint + tipos + pruebas
```

Ensayo con un número que **no** esté en `[autorizados]`, con la ventana abierta:

| Paso | Esperado |
|---|---|
| Escribir «hola» | Aviso de la Ley 1581 con `Acepto` / `Ahora no` |
| Aceptar | Respuesta con fuente |
| Pedir el diagnóstico | Rangos de la entrevista, tarjeta con Don Gota y comparación |
| Llegar al comité | Propuesta de negociación y ficha del asesor |
| Pasar la cuota | Aviso de cuota, sin llamada al modelo |

## 9. Problemas frecuentes

| Síntoma | Causa probable | Solución |
|---|---|---|
| Nada en la consola y nada en el teléfono | URL del callback vieja o `messages` no suscrito | Repetir 4.5 y 4.4 |
| El túnel se reinició y cambió el subdominio | Cloudflare rápido no conserva la URL | Repetir §3.1 con la URL nueva; no tocar tokens |
| `403` en la consola | `APP_SECRET` no coincide | Copiar la clave de la app y reiniciar |
| La consola procesa pero el teléfono no recibe | `WHATSAPP_MODO = falso` | Poner `real` y reiniciar |
| El webhook recibe `200` pero no hay consentimiento ni respuesta | Falta `WHATSAPP_ID_SALT` en la ventana de la app | Cargar el `.ps1` y reiniciar `make app` |
| `destino no autorizado para el modo real` | El destino no está en la lista ni dentro de la ventana del evento | Agregar la huella o ajustar `desde`/`hasta` |
| No responde a un número desconocido aunque `WHATSAPP_EVENTO = 1` | La ventana `desde`/`hasta` del TOML no cubre el momento de la prueba | Ajustar la ventana y reiniciar `make app` |
| `(#200) Provide valid app ID` | ID equivocado o app sin activo asignado | Usar el WABA ID y asignar la app |
| «Verificar y guardar» falla | Túnel apagado o token distinto | Revisar cloudflared y `VERIFY_TOKEN`; probar `https://<url>/health` |
| Cambié `WHATSAPP_ID_SALT` y ya no reconoce a nadie | Otra sal produce otras huellas y otros `usuario_id` | Restaurar la sal original; si no se puede, regenerar todas las huellas |
| Responde cualquier cosa a «tasas» | Pregunta sin producto | Preguntar por producto («tasa de libre inversión») |
| `ErrorEnvio: faltan credenciales` | Token o `PHONE_NUMBER_ID` vacíos | Cargar `whatsapp-env.ps1` en la ventana de la app |
| `404` en `/api/...`, `/docs` o la pantalla desde el túnel | La guarda de §3.12 solo publica el webhook y `/health` | Es lo esperado; la pantalla se abre en `127.0.0.1:8000` |

## 10. Checklist de la rúbrica

- [ ] Número verificado y visible en WhatsApp Manager.
- [ ] `name_status` sin revisión pendiente.
- [ ] WABA suscrita a la app (`subscribed_apps` lista `Prueba1`).
- [ ] `whatsapp-env.ps1` creado fuera del repo y cargado en la ventana de la app.
- [ ] `WHATSAPP_MODO = "real"` y, si aplica, `WHATSAPP_EVENTO = "1"` en esa misma ventana.
- [ ] Túnel arriba apuntando a `127.0.0.1:8000`.
- [ ] URL `https://<url-del-túnel>/webhooks/whatsapp` pegada en **Webhook → Editar → URL de devolución de llamada**, verificada y con `messages` suscrito.
- [ ] Desde fuera, `https://<url-del-túnel>/health` responde y `/api/estado` responde `404`.
- [ ] Prueba negativa con el evento apagado: número desconocido no recibe respuesta.
- [ ] Prueba positiva: consentimiento y respuesta con fuente.
- [ ] Ventana `desde`/`hasta` ajustada a la fecha del ensayo.
- [ ] Invitado sin registro recorre la entrevista, la tarjeta y el comité.
- [ ] Modo evento encendido con cuotas y apagado probado.
- [ ] `make check` en verde.
