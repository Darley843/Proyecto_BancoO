# Workspace de Pana en OpenClaw

OpenClaw es el gateway local del agente `pana` (ver el cambio OpenSpec
`agente-openclaw`). El workspace es la carpeta que el agente lee en cada turno:
identidad, reglas, público, memoria y bitácora. **El repositorio es la fuente
de verdad**; el workspace que usa el gateway vive en WSL y se actualiza con el
script de sincronización.

## Qué es cada archivo

| Archivo | Qué es | ¿Se versiona? |
|---|---|---|
| `SOUL.md` | Identidad y tono de Pana. | Sí |
| `AGENTS.md` | Reglas, límites, datos, herramientas y guion de la escena. | Sí |
| `USER.md` | Público genérico de la demo, sin personas reales. | Sí |
| `IDENTITY.md` | Nombre y emoji de Pana. | Sí |
| `MEMORY.md.example` | Plantilla de la memoria local. | Sí |
| `memory/AAAA-MM-DD.md.example` | Plantilla de la bitácora diaria. | Sí |
| `MEMORY.md` | Memoria local de la ejecución. | No: `.gitignore` |
| `memory/*.md` | Bitácora local por día. | No: `.gitignore` |
| `openclaw.json` | Copia redactada de la configuración del gateway. | Sí |

`SOUL.md`, `AGENTS.md`, `USER.md` e `IDENTITY.md` se envían al modelo en cada
turno: mantenlos cortos (2.500 caracteres cada uno; `AGENTS.md` hasta 4.000).

- **SOUL.md** responde a «quién soy y cómo hablo».
- **AGENTS.md** responde a «qué puedo y qué no puedo hacer». Si hay conflicto,
  manda `AGENTS.md`.
- **USER.md** describe a quién le hablo, siempre en genérico. Nunca escribas
  datos de una persona real.
- **IDENTITY.md** es la ficha mínima del personaje.

`MEMORY.md` y la bitácora son locales, se crean desde las plantillas `.example`
y se borran al terminar el evento. No guardan nombres, números, montos, deudas,
documentos ni textos de invitados; solo aprendizajes generales y conteos
agregados. `AGENTS.md` lo prohíbe de forma explícita.

## Cómo se sincroniza

El gateway corre dentro de WSL y lee el workspace en:

```text
\\wsl$\OpenClawGateway\home\openclaw\.openclaw\workspaces\pana
```

Desde la raíz del repositorio, en PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\sincronizar_workspace.ps1
```

El script:

1. Copia `openclaw/workspace/pana/` al workspace de WSL.
2. **No borra ni sobrescribe** `MEMORY.md` ni la bitácora real (`memory/*.md`
   que no sean `.example`); solo viajan las plantillas.
3. Elimina `BOOTSTRAP.md` del destino: es el archivo de arranque de OpenClaw y
   no debe quedar como una tarea pendiente del agente.
4. Falla con un mensaje claro si WSL o el destino no están disponibles.

Para usar otra ruta (por ejemplo, una copia de ensayo), pasa `-Destino`:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\sincronizar_workspace.ps1 `
  -Destino "C:\ruta\de\ensayo\pana"
```

### Orden recomendado

1. Edita y revisa los archivos en el repositorio.
2. Ejecuta `make check` y `uv run ruff format --check .`.
3. Haz el commit.
4. Sincroniza el workspace.
5. Si es la primera vez, copia `MEMORY.md.example` a `MEMORY.md` en el destino
   (o deja que OpenClaw lo cree al arrancar).
6. Al terminar el evento, borra `MEMORY.md` y `memory/*.md` del destino.

No edites el workspace de WSL a mano: el siguiente `sincronizar_workspace.ps1`
sobrescribe lo versionado. La única excepción son `MEMORY.md` y la bitácora,
que el script respeta.

## `openclaw.json`: la configuración del gateway

`openclaw.json` es una **copia redactada** de:

```text
\\wsl$\OpenClawGateway\home\openclaw\.openclaw\openclaw.json
```

La fuente de verdad es la de WSL: la edita OpenClaw y la usa el gateway. La
copia del repositorio sirve para revisar en un `diff` qué cambió en la
configuración sin exponer secretos ni datos personales. **No se edita a mano**
ni se copia a WSL: si la configuración real cambia, se vuelve a exportar.

### Qué hace cada sección

| Sección | Qué hace |
|---|---|
| `gateway` | Cómo escucha el gateway: puerto, interface, autenticación, recarga y endpoints HTTP. |
| `plugins.entries` | Plugins cargados (Anthropic, Codex, emparejamiento de dispositivos y WhatsApp). |
| `meta` | Marcas internas de migración y última versión que tocó el archivo. Solo informativo. |
| `agents.defaults` | Valores por defecto de todos los agentes: modelo principal y alternativo. |
| `agents.entries` | Los agentes declarados: `main` (la terminal) y `pana` (la escena). |
| `channels.whatsapp` | Canal de WhatsApp del gateway: apagado. |
| `mcp` | Servidor MCP local `sucursal` con las veinte herramientas y su lista cerrada `toolFilter`. |
| `talk` | Qué agente atiende la voz. |
| `tools` | Límites globales de herramientas: sistema de archivos, permisos elevados, visibilidad de sesiones y mensajería entre agentes. |

#### `gateway`: loopback, token y API de chat

- `bind: "loopback"` y `port: 18789`: el gateway solo escucha en `127.0.0.1`.
  No se publica en la red local ni en Internet, igual que la Sucursal 1965.
- `auth.mode: "token"`: exige token en cada petición. En la copia versionada el
  valor es `${OPENCLAW_GATEWAY_TOKEN}`: el token real vive solo en WSL, en la
  variable de entorno `OPENCLAW_GATEWAY_TOKEN`, y nunca entra al repositorio.
- `reload.mode: "hybrid"`: recarga en caliente unos cambios y otros requieren
  reiniciar el gateway.
- `http.endpoints.chatCompletions.enabled: true`: expone la API compatible con
  `POST /v1/chat/completions`, la misma forma que OpenAI. Es lo que permite
  hablarle al agente desde un cliente HTTP o desde la app sin usar la terminal;
  sigue protegida por el token y por el loopback.
- `nodes.commands.allow`: los comandos que un nodo (canvas, dispositivo,
  archivos, pantalla, voz, terminal) puede ejecutar. Es una lista cerrada: lo
  que no está, no se ejecuta. Desde la auditoría no incluye `screen.record`:
  grabar la pantalla no hace falta para la escena y ampliaba el permiso de los
  nodos.

#### `agents.defaults`: modelo principal y alternativo

```json
"model": { "primary": "deepseek/deepseek-flash", "fallbacks": ["deepseek/deepseek-v4-pro"] }
```

El principal es `deepseek/deepseek-flash` (rápido y barato, el que responde en
la escena). Si falla o está saturado, cae en el alternativo
`deepseek/deepseek-v4-pro`, declarado en `models` para que el gateway lo
conozca. `systemAgent.agentId: "main"` dice qué agente atiende las tareas
internas del propio sistema.

#### `agents.entries.pana`

Es el agente de la escena. Además de `workspace` (lo que sincroniza
`sincronizar_workspace.ps1`) y `agentDir`, fija tres cosas:

- **Política de herramientas** (`tools`): perfil `minimal` más una lista
  `deny` con todo lo que Pana no debe poder hacer aunque el modelo lo intente:
  ejecutar comandos o procesos, tocar archivos fuera del workspace, abrir
  navegador o descargar URLs, hablar con el gateway, los plugins, los nodos o
  los secretos, mandar mensajes por su cuenta, publicar en GitHub, lanzar
  subagentes o sesiones, administrar metas, TTS y voz, y la interfaz móvil.
  La lista vive en el gateway, no en el prompt: es defensa en profundidad. El
  `AGENTS.md` del workspace lo explica en palabras; esta lista lo hace cumplir.
- **`exec.security: "deny"`**: el perfil `minimal` no basta para cerrar la
  ejecución de comandos; esta clave la bloquea de forma explícita. No afecta a
  las herramientas del MCP, que entran por `alsoAllow: ["bundle-mcp"]` y no por
  el ejecutor del gateway (ver [Auditoría de seguridad](#auditoría-de-seguridad)).
- **`skills: []`**: vacío a propósito. Pana no carga skills del gateway; todo
  lo que sabe está en los cuatro archivos del workspace, que se envían en cada
  turno. Un skill nuevo aparecería en el `diff` de este archivo.
- **`thinkingDefault: "off"`**: sin razonamiento extendido. La respuesta sale
  sin la fase de «pensar»: menos latencia y menos tokens, que es lo que pide
  una demo en vivo con público.

#### El resto

- `channels.whatsapp`: canal del gateway **apagado** (`enabled: false`) y sin
  más claves: no hay listas de permitidos ni grupos. El WhatsApp del proyecto
  va por Meta (canal de la Sucursal 1965), no por este gateway. Si en el futuro
  la configuración real vuelve a traer teléfonos o JID de grupo, el script de
  exportación los redacta antes de versionar.
- `plugins.entries`: `device-pair` habilitado con `publicUrl` en loopback;
  `whatsapp` **apagado** como plugin (distinto de `channels.whatsapp`, que es el
  canal y también está apagado): la escena no lo usa, así que la auditoría de
  seguridad pedía cerrarlo; `anthropic` y `codex` con el catálogo de sesiones
  apagado.
- `talk.agentId: "main"`: la voz la atiende el agente de la terminal.
- `tools.fs.workspaceOnly: true`: el acceso a archivos no sale del workspace.
  `tools.elevated.enabled: false`: sin permisos elevados.

### MCP del agente `pana`

La copia versionada añade un servidor MCP local con las veinte herramientas del
agente (ver [`docs/AGENTE_OPENCLAW.md`](../docs/AGENTE_OPENCLAW.md)):

```json
"mcp": {
  "servers": {
    "sucursal": {
      "url": "http://127.0.0.1:8765/mcp",
      "transport": "streamable-http",
      "enabled": true,
      "toolFilter": {"include": ["consultar_tasa", "…las veinte…"]}
    }
  }
}
```

Además, `agents.entries.pana.tools.alsoAllow` incluye `bundle-mcp`: el perfil
`minimal` no expone los servidores MCP por sí solo. El servidor se levanta con
`make agente-mcp` en el host de Windows y escucha solo en `127.0.0.1:8765`; el
gateway lo alcanza desde WSL con la red espejo. Si el bloque no está en el
`openclaw.json` real de WSL, `openclaw mcp probe sucursal` no verá las
herramientas: replica el bloque allí y vuelve a exportar la copia redactada.

### Cómo se exporta

```powershell
powershell -ExecutionPolicy Bypass -File scripts\exportar_config_openclaw.ps1
```

El script:

1. Lee el `openclaw.json` de WSL y lo escribe en `openclaw/openclaw.json` con
   dos espacios de sangría, en el orden original de las claves y con LF.
2. Reemplaza por `${OPENCLAW_GATEWAY_TOKEN}` toda clave `token` y por
   `<SECRETO>` toda clave `apiKey`, `password` o `secret`, en cualquier nivel.
3. Reemplaza los teléfonos en formato E.164 del canal por
   `<TELEFONO_REDACTADO>` (Ley 1581 de 2012). `-ConservarDatosPersonales`
   desactiva esa redacción y solo debe usarse en copias que no se versionan.
4. Recorre el resultado: si queda un valor con pinta de clave (contiene
   `sk-...` o tiene más de 40 caracteres alfanuméricos seguidos), **falla sin
   escribir nada** y nombra la ruta del valor, nunca el valor.
5. Falla con un mensaje claro si WSL o el archivo de origen no están
   disponibles.

Para revisar contra una copia de ensayo, pasa `-Origen` y `-Destino`:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\exportar_config_openclaw.ps1 `
  -Origen "C:\ruta\de\ensayo\openclaw.json" -Destino "C:\ruta\de\ensayo\salida.json"
```

### Orden recomendado

1. Cambia la configuración en OpenClaw (terminal o app).
2. Ejecuta el script de exportación.
3. Revisa el `diff` de `openclaw/openclaw.json`: es el cambio real, sin
   secretos.
4. Haz el commit junto con la documentación que corresponda.

Lo que **nunca** entra a este archivo: el token del gateway, claves de
proveedores, contraseñas, teléfonos ni rutas con datos de personas. Si el
script falla en el paso de comprobación, no lo fuerces: agrega el patrón que
falta al `deny` correspondiente o corrige el valor en WSL.

## Auditoría de seguridad

`openclaw security audit` revisa el `openclaw.json` real de WSL. Se corrió el
**24 de noviembre de 2026** sobre esta configuración:

```text
openclaw security audit
```

| Resultado | Antes | Después |
|---|---|---|
| Críticas | 0 | 0 |
| Advertencias | 7 | 2 |

No hay hallazgos críticos ni altos: la entrega no queda bloqueada. De las siete
advertencias iniciales se corrigieron cinco cambiando configuración; las dos
restantes se aceptan con la justificación de abajo.

### Advertencias corregidas

| Advertencia | Cómo se corrigió |
|---|---|
| Sesiones compartidas: `tools.sessions` sin visibilidad acotada | `tools.sessions.visibility: "self"`: cada sesión solo ve la suya. |
| Mensajería entre agentes habilitada (`tools.agentToAgent`) | `tools.agentToAgent.enabled: false`: Pana no puede hablar con otros agentes. |
| Grabación de pantalla permitida en los nodos: `screen.record` dentro de `gateway.nodes.commands.allow` | Se quitó `screen.record` de la lista; queda `screen.snapshot`, que es lo único que usa la escena. |
| Plugin de WhatsApp habilitado sin usarse: `plugins.entries.whatsapp.enabled` | `enabled: false`. El canal del proyecto va por Meta, no por este plugin. |
| Ejecución de comandos permitida en `pana`: `agents.entries.pana.tools.exec.security` distinto de `deny` | `exec.security: "deny"`. El perfil `minimal` no lo cubría. |

Con `exec.security: "deny"` el agente **sigue usando las herramientas del MCP**:
no pasan por el ejecutor de comandos, sino por `alsoAllow: ["bundle-mcp"]` y el
servidor `sucursal`. Se probó con `consultar_tasa` en una sesión nueva del
gateway y respondió con la tasa del Tablero.

### Advertencias que quedan

| Advertencia | Justificación |
|---|---|
| `gateway.trusted_proxies_missing` | El gateway solo escucha en loopback (`bind: "loopback"`, `127.0.0.1:18789`) y el panel no se publica, así que no hay proxy delante que pueda falsificar `X-Forwarded-For`. Declarar proxies de confianza sería ruido para un servicio que nadie alcanza desde fuera. |
| `plugins.installs_unpinned_npm_specs` | Riesgo de cadena de suministro: algún plugin se instala con una especificación npm sin versión fija. Queda pendiente **fijar las versiones después de la entrega**; hacerlo ahora cambiaría el entorno del gateway en plena preparación de la demo. Se mitiga con el resto del cierre: gateway en loopback, token obligatorio y plugins sin uso apagados. |

Se vuelve a correr `openclaw security audit` antes de la etiqueta
`entrega-final`; un hallazgo crítico o alto bloquea la entrega.
