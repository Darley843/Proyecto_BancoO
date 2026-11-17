# Operación del canal de WhatsApp

Guía para levantar el corresponsal de la Sucursal 1965 en WhatsApp Cloud API,
registrar el callback en Meta y probar sin exponer datos personales.

## Alcance y estado

El canal vive en `src/banco_occidente_corpus/canal/` y reutiliza el grafo de la
Sucursal: WhatsApp es un transporte, no otra inteligencia.

Estado de las piezas:

| Pieza | Archivo | Estado |
|---|---|---|
| Contratos Pydantic | `canal/contratos.py` | completo |
| Verificación y firma del webhook | `canal/webhook.py`, `canal/firma.py` | completo |
| Identidad E.164 y huella HMAC | `canal/identidad.py` | completo |
| Consentimiento Ley 1581 | `canal/consentimiento.py` | completo |
| Envío falso y real | `canal/envio.py` | completo |
| Deduplicación, cola y despachador | tareas 2.3 y 2.9 | en curso |

Mientras la cola y el despachador no estén en `main`, el webhook valida la
firma y responde `200 EVENT_RECEIVED`, pero todavía no encola el turno.

## Requisitos

- Una app de tipo **Business** en `developers.facebook.com` con el producto
  WhatsApp y su número de prueba.
- `Phone Number ID`, `App Secret` y un token permanente de usuario del sistema.
- Un túnel HTTPS (cloudflared o ngrok) para que Meta alcance el equipo.
- Los números de prueba autorizados: el del grupo y el del profesor.

## Variables de entorno

Los secretos van **solo** en la sesión; el repositorio no lee `.env`. El archivo
`.env.example` es una referencia de nombres, no un archivo que se cargue.

| Variable | Para qué |
|---|---|
| `WHATSAPP_VERIFY_TOKEN` | Cadena que tú eliges; Meta la repite en la verificación `GET` |
| `WHATSAPP_APP_SECRET` | Secreto de la app; valida `X-Hub-Signature-256` |
| `WHATSAPP_ACCESS_TOKEN` | Token permanente para enviar mensajes |
| `WHATSAPP_PHONE_NUMBER_ID` | Número del negocio que envía |
| `WHATSAPP_ID_SALT` | Sal del HMAC que convierte el número en `usuario_id` |
| `WHATSAPP_MODO` | `falso` o `real`; sobrescribe `canal.modo` del TOML |

En PowerShell:

```powershell
$env:WHATSAPP_VERIFY_TOKEN = "..."
$env:WHATSAPP_APP_SECRET = "..."
$env:WHATSAPP_ACCESS_TOKEN = "..."
$env:WHATSAPP_PHONE_NUMBER_ID = "..."
$env:WHATSAPP_ID_SALT = "..."
$env:WHATSAPP_MODO = "falso"
```

Sin `WHATSAPP_VERIFY_TOKEN` o `WHATSAPP_APP_SECRET`, el webhook responde 503 a
propósito: el canal queda deshabilitado en vez de usar un valor por defecto.

## Arranque local

```powershell
make app
```

La Sucursal escucha solo en `http://127.0.0.1:8000`. El túnel se lanza aparte y
reenvía a ese loopback; nunca se abre uvicorn en `0.0.0.0`.

## Túnel HTTPS

Con cloudflared:

```powershell
cloudflared tunnel --url http://127.0.0.1:8000
```

Con ngrok:

```powershell
ngrok http 8000
```

La URL pública del túnel es la base del callback. Si el túnel gratuito cambia de
subdominio, hay que actualizar el callback en Meta.

## Registro del callback en Meta

En la app de Meta → WhatsApp → Configuración → Webhook:

- **Callback URL:** `https://<subdominio-del-tunel>/webhooks/whatsapp`
- **Verify token:** el mismo valor de `WHATSAPP_VERIFY_TOKEN`.
- **Suscripción:** `messages`.

Meta hace un `GET` con `hub.mode=subscribe`, `hub.verify_token` y
`hub.challenge`. El canal devuelve el reto en texto plano si el token coincide;
si no, responde 403 y no revela el token esperado.

## Números autorizados

El número en claro no se guarda: se convierte en una huella HMAC. Para
autorizar un número, calcula su huella y pégala en `config/whatsapp.toml`,
sección `[autorizados]`:

```powershell
python -m banco_occidente_corpus.canal.identidad --huella "+57 300 123 4567"
```

El comando imprime solo la huella; no imprime la sal ni el número. Repite el
procedimiento para los cinco números de prueba.

## Modos falso y real

- **`falso`** (por defecto): `EnviadorFalso` registra el envío en
  `data/asistente/whatsapp.sqlite` y devuelve `fake:<uuid>`. Es el modo de la
  suite y de los ensayos.
- **`real`**: `EnviadorMeta` hace `POST` a `graph.facebook.com` con `timeout` de
  10 s, User-Agent, header `From` y reintentos solo en 429/5xx. Exige que el
  destino esté entre las huellas autorizadas.

Cambiar de modo no requiere tocar código:

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

## Comprobaciones rápidas

Con la app levantada y el token en la sesión:

```powershell
curl.exe "http://127.0.0.1:8000/webhooks/whatsapp?hub.mode=subscribe&hub.verify_token=$env:WHATSAPP_VERIFY_TOKEN&hub.challenge=12345"
```

Debe responder `12345` en texto plano. Un token distinto devuelve 403 y, sin
variable de entorno, 503.

## Problemas frecuentes

| Síntoma | Causa probable |
|---|---|
| Meta dice «callback verification failed» | Token distinto o túnel caído |
| `GET` responde 503 | Falta `WHATSAPP_VERIFY_TOKEN` en la sesión |
| `POST` responde 401 | App Secret distinto o cuerpo reserializado; la firma va sobre los bytes originales |
| `POST` responde 503 | Falta `WHATSAPP_APP_SECRET` |
| No llega ningún mensaje | El callback no está suscrito a `messages` o la URL del túnel cambió |

## Seguridad y datos personales

- El número en claro solo existe en memoria; se persiste el hash.
- El token y el App Secret no se escriben en logs, en la base ni en el
  repositorio.
- El perfil (nombre y rol) vive fuera de Git y no se envía al modelo.
- El túnel se apaga al terminar cada ensayo; el servidor sigue en `127.0.0.1`.
- Los mensajes entrantes y los fragmentos son datos, nunca instrucciones.

## Limitaciones conocidas

- El número de prueba de Meta permite escribir a cinco destinatarios y solo
  dentro de la ventana de 24 h desde el último mensaje del usuario.
- No se admiten llamadas, audios, imágenes ni pagos.
- No hay verificación empresarial ni número de producción: es una demo
  académica.
