# Lista de verificación de la demo

Qué revisar antes de la sustentación para que el canal de WhatsApp, la app web
y el comité funcionen en vivo, y qué hacer si algo falla. Complementa
`docs/OPERACION_WHATSAPP.md`, que tiene la puesta en marcha paso a paso, y
`docs/SEGURIDAD.md` §5.1 (trazas solo para la demo).

Regla general: **los secretos solo viven en la sesión de PowerShell**. Nada de
esta lista se escribe en el repositorio, en capturas ni en el chat del grupo.

## 1. El día anterior

### Código y entorno

- [ ] `main` al día y con los PR de la demo fusionados: #139 (Ley 1581),
      #149 (entrevista por WhatsApp), el HITL con el asesor y la latencia, si
      ya entraron.
- [ ] En la máquina de la demo:
  ```powershell
  git switch main
  git pull
  uv sync --all-extras
  make check
  ```
  `make check` en verde. Si Windows bloquea una DLL o `.venv` da «Acceso
  denegado», cerrar todo lo que use el proyecto y reconstruir el entorno con
  `Remove-Item -Recurse -Force .venv` y `uv sync --all-extras`.

### Bóveda, Ollama y Tablero

- [ ] Ollama encendido y con el modelo de embeddings del proyecto:
  ```powershell
  ollama list
  ```
- [ ] Índice de la Bóveda presente: `data/boveda/indice.json` existe. Si falta,
      `make indice` (usa Ollama y tarda). Sin índice, la Ventanilla y Roba la
      Bóveda responden 503.
- [ ] Tasas del Tablero: si el banco publicó una tabla nueva, regenerarla
      (Nayla). Si no, la demo muestra la alerta `vigencia_vencida`, y es lo
      honesto.

### Meta y WhatsApp

- [ ] Token permanente de Meta vigente (60 días desde que se generó).
- [ ] App publicada (*Live*) y cuenta de WhatsApp suscrita a la app
      (`docs/OPERACION_WHATSAPP.md`, pasos 7 y 8).
- [ ] Los **cinco números autorizados** en Meta, incluido el del profesor,
      cada uno con el código confirmado.
- [ ] Sus huellas en `[autorizados]` de `config/whatsapp.toml`, generadas con
      la misma `WHATSAPP_ID_SALT` que se usará en la demo:
  ```powershell
  uv run python -m banco_occidente_corpus.canal.identidad --huella "+57 300 123 4567"
  ```
- [ ] Si el texto del aviso cambió desde el último ensayo, subir `version_aviso`
      en `config/whatsapp.toml`: así los números de prueba vuelven a aceptar el
      aviso vigente (Decreto 1377 de 2013, art. 8).

### DeepSeek

- [ ] Saldo suficiente en `platform.deepseek.com`. Un comité cuesta alrededor
      de un centavo de dólar y el tope diario de la app es US$ 0,20
      (`SUCURSAL_TOPE_USD` lo cambia solo para esa sesión).
- [ ] La clave ya está en las variables de usuario de Windows. Se comprueba sin
      mostrarla:
  ```powershell
  [bool]$env:DEEPSEEK_API_KEY
  ```
  Nunca se escribe a mano en la terminal ni en el chat.

### Ensayo general

- [ ] Recorrer la **prueba de humo** completa (sección 3) con `WHATSAPP_MODO=real`.
- [ ] Grabar un video corto o tomar capturas de cada flujo: es el plan B.

## 2. Una hora antes

Tres ventanas de PowerShell, todas desde la raíz del repositorio.

**Ventana 1: la app.**

```powershell
. "..\whatsapp-env.ps1"
$env:WHATSAPP_MODO = "real"
Get-ChildItem Env: | Where-Object Name -match 'LANGSMITH|LANGCHAIN'
make app
```

- [ ] La consulta de `LANGSMITH|LANGCHAIN` no muestra nada, salvo que el grupo
      decida mostrar trazas (`docs/SEGURIDAD.md` §5.1).
- [ ] La app queda en `http://127.0.0.1:8000` y `GET /health` responde 200.

**Ventana 2: el túnel.**

```powershell
& "$HOME\cloudflared.exe" tunnel --url http://127.0.0.1:8000
```

- [ ] Copiar la URL `https://….trycloudflare.com`. Es **variable**: cada vez
      que el túnel se reinicia cambia.
- [ ] En Meta → Webhooks → *Whatsapp Business Account*: actualizar la URL de
      devolución de llamada a `https://<url-del-tunel>/webhooks/whatsapp` y
      pulsar **Verificar y guardar**.

**Ventana 3: comprobaciones.**

```powershell
. "..\whatsapp-env.ps1"
curl.exe "http://127.0.0.1:8000/webhooks/whatsapp?hub.mode=subscribe&hub.verify_token=$env:WHATSAPP_VERIFY_TOKEN&hub.challenge=12345"
curl.exe "https://<url-del-tunel>/webhooks/whatsapp?hub.mode=subscribe&hub.verify_token=$env:WHATSAPP_VERIFY_TOKEN&hub.challenge=12345"
```

- [ ] Las dos devuelven `12345`.
- [ ] Un `hola` desde un número autorizado produce `POST /webhooks/whatsapp 200`
      en la ventana 1.

## 3. Prueba de humo, en el orden de la demo

| # | Qué se hace | Qué debe pasar |
|---|---|---|
| 1 | `hola` por WhatsApp | Aviso de la Ley 1581 con **Acepto** y **Ahora no**; menciona a DeepSeek como proveedor externo |
| 2 | **Acepto** | Confirmación; el consentimiento queda guardado |
| 3 | «¿Cuál es la cuota de manejo de la tarjeta débito?» | Respuesta del Tablero (`T`) con su fuente |
| 4 | «¿En qué año se fundó el Banco de Occidente?» | Respuesta de la Bóveda (`B`) con cita |
| 5 | «¿Qué clima hace hoy en Cali?» | Rechazo (`X`) con la respuesta estándar |
| 6 | «¿Me alcanza para un crédito?» | Invitación al diagnóstico (`D`), sin modelo |
| 7 | Entrevista con la persona `empleada_verde` | Verde y tarjeta de Pana |
| 8 | Entrevista con `pensionado_amarillo` | Mensaje «El comité está revisando tu caso…» y luego la recomendación del comité |
| 9 | Entrevista con `independiente_rojo` | Comité, prueba de estrés y oferta de asesor (HITL) |
| 10 | «¿Y si lo pago en 60 meses?» (si entró) | Tarjeta de antes y después |
| 11 | «Olvida mis datos» | Confirmación de revocación; el siguiente `hola` vuelve a pedir el aviso |
| 12 | Web → Ventanilla: «¿me alcanza para un crédito?» | Ticket **D** verde |
| 13 | Web → Roba la Bóveda: las tres ideas | Defensa resistida; **Exportar resumen** descarga el JSON sin datos personales |
| 14 | Web → Operación | Mensajes, consentimientos, casos y Roba con datos reales; latencia si ya hay mediciones |
| 15 | Comité en pantalla: `uv run python scripts/demo_comite.py` | Posturas de Riesgo, Comercial y Auditor; costo y tiempo |

Los pasos 7 a 11 necesitan la entrevista por WhatsApp (#149) en `main`, y la
oferta de asesor del paso 9, el HITL. Las respuestas de las entrevistas salen
de `data/evaluacion/personas_sinteticas.json`.
Se usan **solo datos inventados**: nadie escribe sus ingresos reales.

Para la sustentación de Roba la Bóveda: en modo demo mide sobre todo las
**defensas determinísticas** (puerta de PII, Digiturno y respuestas fijas). La
robustez del modelo frente a la inyección se muestra con el caso 5
(`SUCURSAL_DEMO_INYECCION`).

## 4. Plan B

| Si falla… | Qué hacer |
|---|---|
| El túnel se cae | Reiniciar `cloudflared`, copiar la URL nueva, actualizar el callback en Meta y verificar (unos 2 minutos) |
| Meta no entrega los mensajes | Mostrar el flujo con la app web y el simulador: `uv run python -m pytest test/test_simulador_webhook_real.py -q` firma las conversaciones de las personas contra el webhook real; también el video del ensayo |
| `ErrorEnvio: destino no autorizado` | Falta la huella del número o cambió la sal: regenerarla, pegarla en `config/whatsapp.toml` y reiniciar la app |
| DeepSeek falla o se alcanza el tope | Ventanilla en modo demo (`$env:SUCURSAL_DEMO = "1"` y reiniciar la app); el comité se muestra con la corrida grabada del ensayo |
| Ollama o el índice no responden | La Ventanilla y Roba responden 503: arrancar Ollama, revisar `data/boveda/indice.json` y, si no se recupera, usar capturas o video |
| Sin internet | Todo lo local sigue: app web en modo demo, Roba, Operación y la suite (`make check`) |

## 5. Al terminar

- [ ] Ctrl + C en la app y en el túnel: el túnel no queda abierto.
- [ ] Quitar las trazas si se encendieron:
  ```powershell
  Remove-Item Env:LANGSMITH_TRACING, Env:LANGSMITH_PROJECT, Env:LANGSMITH_API_KEY -ErrorAction SilentlyContinue
  ```
- [ ] Si un token o la clave aparecieron en pantalla, en una captura o en un
      log: **rotarlos**.
- [ ] Cada número de prueba escribe «olvida mis datos» si no se volverá a usar.
- [ ] Nada de `data/asistente/` se sube al repositorio.

## 6. Responsables (propuesta; se confirma en el grupo)

| Tarea | Responsable |
|---|---|
| Esta lista y la prueba de humo | Anny |
| Meta, túnel, callback y huellas de los números | Darley |
| Tasas del Tablero y comité | Nayla |
| Tablero de operación y latencia | Yoldy |
| Video o capturas de respaldo | Por asignar |
