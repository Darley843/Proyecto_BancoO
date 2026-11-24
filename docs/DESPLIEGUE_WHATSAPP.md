# Despliegue del canal de WhatsApp (Meta + túnel + modo evento)

Guía única para poner el canal en producción con un número propio, levantar el
túnel, verificar el webhook y abrir el **modo evento** sin saltarse el
consentimiento. Complementa [`OPERACION_WHATSAPP.md`](./OPERACION_WHATSAPP.md),
que explica el diseño del canal; aquí están los pasos y los enlaces.

Todo lo que se pega en Meta está marcado con **Meta**; lo que se ejecuta en
PowerShell, con **PowerShell**. Los secretos van **solo** en
`whatsapp-env.ps1`, fuera del repositorio.

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

## 2. Variables de entorno (fuera del repositorio)

Archivo `..\whatsapp-env.ps1`, un nivel arriba de `ProyectoAvance1`:

```powershell
$env:WHATSAPP_PHONE_NUMBER_ID = "<PHONE_NUMBER_ID>"
$env:WHATSAPP_APP_SECRET      = "<App Secret de Prueba1>"
$env:WHATSAPP_VERIFY_TOKEN    = "<cadena alfanumérica inventada>"
$env:WHATSAPP_ACCESS_TOKEN    = "<token del usuario del sistema>"
$env:WHATSAPP_ID_SALT         = "<sal aleatoria, no se cambia nunca>"
$env:WHATSAPP_MODO            = "real"
# Opcional: enciende el modo evento sin editar el TOML.
# $env:WHATSAPP_EVENTO        = "1"
```

| Variable | Secreta | De dónde sale | Si está mal |
|---|---|---|---|
| `WHATSAPP_APP_SECRET` | Sí | App → Configuración → Básica → Clave secreta | Meta recibe `403`; no entra ningún mensaje |
| `WHATSAPP_VERIFY_TOKEN` | Trátala como secreta | La inventas y la pegas también en Meta | «Verificar y guardar» falla |
| `WHATSAPP_ACCESS_TOKEN` | Sí | Usuario del sistema `sucursal-1965-bot` | El mensaje entra, la respuesta falla con `401` |
| `WHATSAPP_ID_SALT` | Sí, irrecuperable | La inventas una vez | Cambian todas las huellas y los consentimientos quedan huérfanos |
| `WHATSAPP_MODO` | No | `falso` o `real` | En `falso` la respuesta se registra pero no sale a Meta |

Cargar en cada ventana nueva:

```powershell
. "..\whatsapp-env.ps1"
```

Verificar:

```powershell
@("WHATSAPP_PHONE_NUMBER_ID","WHATSAPP_APP_SECRET","WHATSAPP_VERIFY_TOKEN",
  "WHATSAPP_ACCESS_TOKEN","WHATSAPP_ID_SALT") |
  ForEach-Object { "$_ = $([bool](Get-Item "env:$_" -ErrorAction SilentlyContinue))" }
```

## 3. Enlaces de Meta

| Qué | Enlace |
|---|---|
| Panel de apps | <https://developers.facebook.com/apps/> |
| App `Prueba1` | `https://developers.facebook.com/apps/<APP_ID>/` |
| Configuración de WhatsApp (webhooks, número) | `https://developers.facebook.com/apps/<APP_ID>/whatsapp-business/wa-settings/` |
| Configuración de la API (Paso 1) | `https://developers.facebook.com/apps/<APP_ID>/whatsapp-business/wa-dev-console/` |
| WhatsApp Manager → Números de teléfono | <https://business.facebook.com/wa/manage/phone-numbers/> |
| Configuración del negocio (personas, activos, sistema) | <https://business.facebook.com/settings/> |
| Usuarios del sistema (token permanente) | <https://business.facebook.com/settings/system-users> |

> El botón `+ Agregar` de **Business Settings → Cuentas de WhatsApp** crea otra
> WABA, no un número. Los números se agregan desde el panel de la app o desde
> WhatsApp Manager.

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

**Meta** → App `Prueba1` → **WhatsApp** → `Configurar webhooks` → **Editar**.

| Campo | Valor |
|---|---|
| URL de devolución de llamada | `https://<url-del-túnel>/webhooks/whatsapp` |
| Token de verificación | el de `WHATSAPP_VERIFY_TOKEN` |

Pulsa **Verificar y guardar**: Meta hace un `GET /webhooks/whatsapp` y debe
responder `200` con el `hub.challenge`. Después confirma que el campo
**`messages`** está suscrito.

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
Invoke-RestMethod "$base/debug_token?input_token=$tok&access_token=$tok" |
  Select-Object -ExpandProperty data | Select-Object app_id, expires_at, scopes
```

### 4.7 Información de pago (opcional)

Necesaria solo para **mensajes iniciados por la empresa** (plantillas). Los
mensajes de servicio —el invitado escribe primero— son gratuitos. Si se agrega,
usar tarjeta del grupo o virtual y fijar un **límite de gasto** en Facturación.

## 5. Levantar el túnel

```powershell
& "$HOME\cloudflared.exe" tunnel --url http://127.0.0.1:8000
```

Copia la URL `https://algo.trycloudflare.com` y actualiza el callback del punto
4.5. El túnel apunta a `127.0.0.1:8000`; si la app se reinicia en el mismo
puerto, la URL no cambia y Meta sigue funcionando.

## 6. Levantar la app

```powershell
. "..\whatsapp-env.ps1"
$env:WHATSAPP_MODO = "real"
make app
```

Debe quedar en `http://127.0.0.1:8000` y escuchar **solo** en loopback.

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
| `403` en la consola | `APP_SECRET` no coincide | Copiar la clave de la app y reiniciar |
| La consola procesa pero el teléfono no recibe | `WHATSAPP_MODO = falso` | Poner `real` y reiniciar |
| `destino no autorizado para el modo real` | El destino no está en la lista ni dentro de la ventana del evento | Agregar la huella o ajustar `desde`/`hasta` |
| No responde a un número desconocido aunque `WHATSAPP_EVENTO = 1` | La ventana `desde`/`hasta` del TOML no cubre el momento de la prueba | Ajustar la ventana y reiniciar `make app` |
| `(#200) Provide valid app ID` | ID equivocado o app sin activo asignado | Usar el WABA ID y asignar la app |
| «Verificar y guardar» falla | Túnel apagado o token distinto | Revisar cloudflared y `VERIFY_TOKEN` |
| Responde cualquier cosa a «tasas» | Pregunta sin producto | Preguntar por producto («tasa de libre inversión») |
| `ErrorEnvio: faltan credenciales` | Token o `PHONE_NUMBER_ID` vacíos | Cargar `whatsapp-env.ps1` |

## 10. Checklist de la rúbrica

- [ ] Número verificado y visible en WhatsApp Manager.
- [ ] `name_status` sin revisión pendiente.
- [ ] WABA suscrita a la app (`subscribed_apps` lista `Prueba1`).
- [ ] Callback verificado y campo `messages` suscrito.
- [ ] `whatsapp-env.ps1` cargado en la ventana de la app.
- [ ] Túnel arriba apuntando a `127.0.0.1:8000`.
- [ ] Prueba negativa con el evento apagado: número desconocido no recibe respuesta.
- [ ] Prueba positiva: consentimiento y respuesta con fuente.
- [ ] Ventana `desde`/`hasta` ajustada a la fecha del ensayo.
- [ ] Invitado sin registro recorre la entrevista, la tarjeta y el comité.
- [ ] Modo evento encendido con cuotas y apagado probado.
- [ ] `make check` en verde.
