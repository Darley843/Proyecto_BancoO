# Lista de verificación de la demo

Qué revisar antes de la sustentación para que el canal de WhatsApp, la app web
y el comité funcionen en vivo, y qué hacer si algo falla. Complementa
`docs/OPERACION_WHATSAPP.md`, que tiene la puesta en marcha paso a paso, y
`docs/SEGURIDAD.md` §5.1 (trazas solo para la demo).

La demo corre en el **computador de Nayla**; los comandos asumen esa máquina.

Regla general: **los secretos solo viven en la sesión de PowerShell**. Nada de
esta lista se escribe en el repositorio, en capturas ni en el chat del grupo.

## 1. El día anterior

### Código y entorno

- [ ] `main` al día y con los PR de la demo fusionados: #139 (Ley 1581) y
      #149 (entrevista por WhatsApp). El HITL con el asesor y la latencia, si
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
- [ ] El índice está en **Qdrant**, no solo en Chroma: `data/boveda/indice.json`
      dice `"almacen": "qdrant"` y la colección pesa varios MB.
  ```powershell
  Get-Content data\boveda\indice.json
  (Get-Item data\boveda\qdrant\collection\boveda\storage.sqlite).Length
  ```
  Si falta la línea `almacen` o la colección pesa unos 12 KB, la búsqueda
  vectorial no devuelve nada y la Ventanilla responde solo con BM25, sin aviso.
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

### Meta y WhatsApp

- [ ] Token permanente de Meta vigente (60 días desde que se generó).
- [ ] App publicada (*Live*) y cuenta de WhatsApp suscrita a la app
      (`docs/OPERACION_WHATSAPP.md`, pasos 7 y 8).
- [ ] Nayla agregada como desarrolladora o administradora de la app de Meta,
      para que pueda actualizar el webhook ella misma si el túnel se cae.
- [ ] Los **cinco números autorizados** en Meta, incluido el del profesor,
      cada uno con el código confirmado.
- [ ] Sus huellas en `[autorizados]` de `config/whatsapp.toml`, generadas con
      la misma `WHATSAPP_ID_SALT` que se usará en la demo:
  ```powershell
  uv run python -m banco_occidente_corpus.canal.identidad --huella "+57 300 123 4567"
  ```
  Las huellas reales se editan **solo en el computador de la demo**: nunca se
  hace `git add` ni commit de `config/whatsapp.toml` con ellas (el repositorio
  es público).
- [ ] `version_aviso` en `config/whatsapp.toml` corresponde al texto vigente
      del aviso (`2026-11-20`, con la mención de DeepSeek). Si el aviso vuelve a
      cambiar, se sube otra vez: así los números de prueba aceptan el texto
      nuevo (Decreto 1377 de 2013, art. 8).

### DeepSeek

- [ ] Saldo suficiente en `platform.deepseek.com`. Un comité cuesta alrededor
      de un centavo de dólar y el tope diario de la app es US$ 0,20
      (`SUCURSAL_TOPE_USD` lo cambia solo para esa sesión).
- [ ] La clave de DeepSeek de la app va en `..\whatsapp-env.ps1`, junto con las
      variables del canal y fuera del repositorio, para que la ventana de la app
      la cargue con el mismo comando. Se comprueba sin mostrarla:
  ```powershell
  [bool]$env:DEEPSEEK_API_KEY
  ```
  Nunca se escribe en el chat, en una captura ni en el repositorio.

### Escena «Pana vs. el gota a gota» (pantalla y voces)

- [ ] `main` con la pantalla (#169), las voces (#171) y el arreglo de las
      voces sin internet (`fix/voz-sin-internet`) fusionados.
- [ ] Voces de Piper descargadas **después de fusionar el #171**: el Auditor
      usa un modelo nuevo (`es_ES-carlfm-x_low`). Son el respaldo de todos los
      personajes; necesita internet solo esta vez:
  ```powershell
  make voz-modelo
  ```
- [ ] **Microsoft Edge** instalado y con internet: Pana habla con
      «Microsoft Gonzalo Online (Natural)» y el agente del joven con
      «Microsoft Juan Online (Natural)». En otro navegador o sin internet
      vuelven a su voz de Piper (suena, pero menos natural). Ojo: sin el
      arreglo de las voces sin internet, Edge no vuelve a Piper sino que
      cambia por su cuenta a una voz local de Windows.
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

### Ensayo general

- [ ] Recorrer la **prueba de humo** completa (sección 3) con `WHATSAPP_MODO=real`.
- [ ] En el paso 4, la respuesta dice **1965** (no el fragmento de 1991–1993
      que sale en modo demo; ver la nota al final de la sección 3).
- [ ] Tomar capturas de cada flujo como respaldo. La sustentación es en vivo y
      sin video: las capturas solo se usan si algo no se puede mostrar.

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
- [ ] La escena abierta en **Edge**, en pantalla completa (F11), en
      `http://127.0.0.1:8000/escena.html`, con el volumen probado.

**Ventana 2: el túnel.**

```powershell
cloudflared tunnel --url http://127.0.0.1:8000
```

Si `cloudflared` no está instalado: `winget install --id Cloudflare.cloudflared`
y abrir una ventana nueva.

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
- [ ] **Calentamiento de la latencia:** enviar al menos **30 mensajes** por el
      canal antes de mostrar la vista Operación. Con menos de 30 corridas por
      flujo, p50 y p95 se marcan como muestra insuficiente (`MINIMO_CORRIDAS`
      en `sucursal/operacion.py`). Es correcto mostrarlo así, pero con 30 la
      cifra ya es concluyente. El ensayo general ya produce esos mensajes,
      porque cada botón de la entrevista cuenta como uno. Como mezclan pasos
      rápidos con diagnósticos de unos 4 s, p50 y p95 son del canal completo;
      separarlos por flujo queda para el #150.

## 3. Prueba de humo, en el orden de la demo

| # | Qué se hace | Qué debe pasar |
|---|---|---|
| 1 | `hola` por WhatsApp | Aviso de la Ley 1581 con **Acepto** y **Ahora no**; menciona a DeepSeek como proveedor externo |
| 2 | **Acepto** | Confirmación; el consentimiento queda guardado |
| 3 | «¿Cuál es la cuota de manejo de la tarjeta débito?» | Respuesta del Tablero (`T`) con su fuente |
| 4 | «¿En qué año se fundó el Banco de Occidente?» | Respuesta de la Bóveda (`B`) con cita; dice **1965** |
| 5 | «¿Qué clima hace hoy en Cali?» | Rechazo (`X`) con la respuesta estándar |
| 6 | «¿Me alcanza para un crédito?» | Arranca la entrevista del diagnóstico por WhatsApp |
| 7 | Entrevista con la persona `empleada_verde` | Verde y tarjeta de Pana |
| 8 | Entrevista con `pensionado_amarillo` | La recomendación del comité llega completa en una sola respuesta (unos 4 s) |
| 9 | Entrevista con `independiente_rojo` | Comité y prueba de estrés; mientras no entre el HITL, la oferta de asesor es solo texto |
| 10 | «¿Y si lo pago en 60 meses?» | Tarjeta de antes y después |
| 11 | «Olvida mis datos» | Confirmación de revocación; el siguiente `hola` vuelve a pedir el aviso |
| 12 | Web → Ventanilla: «¿me alcanza para un crédito?» | Ticket **D** verde |
| 13 | Web → Roba la Bóveda: las tres ideas | Defensa resistida; **Exportar resumen** descarga el JSON sin datos personales |
| 14 | Web → Operación | Mensajes, consentimientos, casos y Roba con datos reales; p50 y p95 del canal después del calentamiento |
| 15 | Comité en pantalla: `uv run python scripts/demo_comite.py` | Posturas de Riesgo, Comercial y Auditor; costo y tiempo |

Los pasos 6 a 11 usan la entrevista por WhatsApp (#149). En la web, la
Ventanilla sigue mostrando el ticket `D` (paso 12). Las respuestas de las
entrevistas salen de `data/evaluacion/personas_sinteticas.json`.
Se usan **solo datos inventados**: nadie escribe sus ingresos reales.

Durante la entrevista se responde con los botones o la lista: un texto libre
repite la pregunta. «Cancelar» la deja, «nuevo» la reinicia y una entrevista a
medias vence a los 30 minutos (`entrevista_ttl_minutos`). El «¿Y si…?» del paso
10 compara contra el último diagnóstico del mismo número, durante 24 horas.

Para la sustentación de Roba la Bóveda: en modo demo mide sobre todo las
**defensas determinísticas** (puerta de PII, Digiturno y respuestas fijas). La
robustez del modelo frente a la inyección se muestra con el caso 5
(`SUCURSAL_DEMO_INYECCION`).

En **modo demo** la Ventanilla no llama al modelo: responde con el fragmento
principal de la Bóveda. Probado el 21 de noviembre: «¿En qué año se fundó el
Banco de Occidente?», que además es el primer ejemplo de la Ventanilla, trae
el fragmento de 1991–1993 y no el de 1965. Para mostrar la Bóveda en modo demo
se usa «¿Cuál es el propósito o misión del banco?», que contesta con la página
*Nuestro Banco*, o «¿Puedo abrir una cuenta en línea?».

## 4. Plan B

| Si falla… | Qué hacer |
|---|---|
| El túnel se cae | Reiniciar `cloudflared`, copiar la URL nueva, actualizar el callback en Meta (Nayla o Darley) y verificar (unos 2 minutos) |
| Meta no entrega los mensajes | Mostrar el flujo con la app web y el simulador: `make simular` firma las conversaciones de las personas, las entrega al webhook real con el enviador falso y muestra por persona el semáforo, el comité y el «¿Y si…?»; también las capturas del ensayo |
| `ErrorEnvio: destino no autorizado` | Falta la huella del número o cambió la sal: regenerarla, pegarla en `config/whatsapp.toml` y reiniciar la app |
| DeepSeek falla o se alcanza el tope | Ventanilla en modo demo (`$env:SUCURSAL_DEMO = "1"` y reiniciar la app); para la Bóveda, «¿Cuál es el propósito o misión del banco?» en vez de la pregunta del año (nota de la sección 3); el comité se muestra con la corrida grabada del ensayo |
| Ollama o el índice no responden | La Ventanilla y Roba responden 503: arrancar Ollama, revisar `data/boveda/indice.json` y, si no se recupera, usar las capturas |
| La escena no suena (sin parlantes, voz que no carga) | Marcar **Solo subtítulos (respaldo)** (tecla S) y pasar los turnos con la barra espaciadora: el público lee los subtítulos y las cifras |
| Pana suena con la voz de Piper o con una voz de Windows, y no con Gonzalo | Falta internet o no se abrió en Edge: abrir la escena en Edge; si no hay red, seguir con Piper o con solo subtítulos |
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
- [ ] `git status` limpio: **no hacer commit de `config/whatsapp.toml` con
      huellas reales**. Para dejarlo como estaba:
  ```powershell
  git restore config/whatsapp.toml
  ```

## 6. Responsables (propuesta; se confirma en el grupo)

| Tarea | Responsable |
|---|---|
| Esta lista y la prueba de humo | Anny |
| Computador de la demo, túnel y callback | Nayla |
| App de Meta, huellas de los números y respaldo del callback | Darley |
| Tasas del Tablero y comité | Nayla |
| Tablero de operación, latencia y calentamiento | Yoldy |
| Pantalla de la escena, voces y modo solo subtítulos | Yoldy |
| Capturas de respaldo y guion de la sustentación | Yoldy |
