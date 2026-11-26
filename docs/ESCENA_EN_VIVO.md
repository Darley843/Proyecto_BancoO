# Escena en vivo: contrato de la lista, el canal, la ruta y la pantalla

**Estado:** contrato cerrado el miércoles 25 de noviembre de 2026 para
implementar el **jueves 26**. **No hay código nuevo en este cambio:** este
documento fija qué se escribe, quién lo escribe, cómo se lee y qué prueba lo
demuestra. Si una implementación necesita un campo, un archivo o un valor
distinto, primero se actualiza este documento, `escena/contratos.py`,
`app/web/escena/contrato.js` y sus pruebas en el mismo commit.

El objetivo es que el voluntario escriba por WhatsApp a Pana (el agente de
OpenClaw) y que `app/web/escena.html` muestre **su escena**, en vivo y con voces:
sus mensajes, Don Gota, la comparación de Pana, la negociación entre el agente
del joven y el del banco, el veredicto del auditor y la ficha.

## 1. Flujo y fronteras

```text
Voluntario (WhatsApp)
        │
        ▼
Meta → webhook → cola → despachador ──► OpenClaw (Pana)
                                │              │
                                │              ├─ calcular_prestamo_gota ─┐
                                │              ├─ comparar_gota_banco ───┤
                                │              ├─ negociar_opcion ───────┤
                                │              ├─ auditar_respuesta ─────┤
                                │              └─ generar_ficha_opcion ──┤
                                │                                       ▼
                                └─ canal (invitado / pana) ──► escena/publicador.py
                                                                        │
                                                                        ▼
                                                     data/escena/en_vivo.jsonl
                                                                        │
                                                                        ▼
                                        GET /api/escena/en-vivo?desde=N
                                                                        │
                                                                        ▼
                                          app/web/escena.html (tecla E)
                                          voz + subtítulo, en orden de seq
```

El MCP y la app son **procesos distintos**. Los dos escriben en el mismo archivo
y la pantalla lee por HTTP. Esa separación manda el diseño de la escritura
segura (§6) y explica la limitación del canal (§9.5).

### 1.1 Dueños y archivos

| Frente | Persona | Archivos que toca | No toca |
|---|---|---|---|
| Lista, publicador y herramientas | Nayla | `src/banco_occidente_corpus/escena/publicador.py`, `.../herramientas/lectura.py`, `.../escena/contratos.py`, `test/test_escena_publicador.py`, `test/test_herramientas_lectura.py`, `test/test_escena_contratos.py` | canal, pantalla, `app/web/` |
| Canal y ruta | Darley | `src/banco_occidente_corpus/canal/escena_vivo.py`, `.../canal/despachador.py`, `.../canal/configuracion.py`, `.../escena/api_en_vivo.py`, `app.py`, `scripts/limpiar_evento.ps1`, `test/test_canal_escena_vivo.py`, `test/test_escena_en_vivo_api.py` | publicador, pantalla |
| Pantalla | Yoldy | `app/web/escena/envivo.js`, `app/web/escena/escena.js`, `app/web/escena/contrato.js`, `app/web/escena/escena.css`, `app/web/escena.html`, `app/web/escena/rostros.js`, `test/test_web_escena.py`, `test/test_web_escena_en_vivo.py` | Python del publicador, canal |
| Tarjeta o QR y prueba de PII | Anny | `docs/img/` (solo si no lleva número), el generador local de la tarjeta, `test/test_escena_pii_en_vivo.py`, `test/test_seguridad.py` | código de los otros tres frentes |

La interfaz compartida es `escena/publicador.py` (§7). Nayla la deja lista y
con pruebas **antes de las 09:00** del jueves; Darley y Yoldy la consumen sin
editarla. Si hay que cambiarla, se avisa a los tres y se actualiza el contrato.

## 2. Decisiones cerradas

| Decisión | Valor |
|---|---|
| Archivo de la lista | `data/escena/en_vivo.jsonl` (local, ignorado por Git) |
| Interruptor | solo `ESCENA_EN_VIVO=1`; cualquier otro valor no escribe |
| Una línea | un turno `TurnoEscena` por línea, JSON compacto, UTF-8, LF |
| Orden de la pantalla | `seq` ascendente; `turno.orden` **no** ordena la lista |
| Escritura entre procesos | bloqueo exclusivo del sistema sobre `data/escena/en_vivo.lock` |
| `seq` | entero creciente basado en época en ms × 1000 + contador, corregido con el último del archivo (§6) |
| Ruta | `GET /api/escena/en-vivo?desde=<seq>`; solo en la app que escucha en `127.0.0.1` |
| Tecla de la pantalla | **E** (libre; ya están P, S, Q, V, N, T, H, R, Espacio y →) |
| Frecuencia | cada 2 s, solo con el modo en vivo abierto y la pestaña visible |
| Borrado | `scripts/limpiar_evento.ps1` borra `en_vivo.jsonl` (y `en_vivo.lock`) |
| Punto de control | jueves 26 a las **12:00**; si no está verde, la escena en vivo queda apagada (§15) |

## 3. El turno que se publica

Se reutiliza **tal cual** `TurnoEscena` de `escena/contratos.py`. El modelo
rechaza campos extra (`extra="forbid"`); no se añade ningún campo nuevo.

| Campo | Regla |
|---|---|
| `id` | Identificador del módulo que produjo el turno. Puede repetirse entre emisiones; la identidad de la lista es `seq`. |
| `orden` | Orden dentro de la escena de origen. La pantalla en vivo **no** ordena por este campo. |
| `personaje` | `pana`, `don_gota`, `joven`, `agente_joven`, `agente_banco`, `auditor` y el nuevo `invitado`. |
| `texto` | Lo que se dice y se subtitula. Máximo 4.000 caracteres al publicar. |
| `subtitulo` | Texto alterno; si falta, la pantalla lee `texto`. |
| `cifras` | Las del módulo, con su `fuente`; vacío si el turno no cita cifras. |
| `escenario` | El del motor, o `null`. |
| `origen` | `guion_fijo`, `motor`, `llm`, `reglas`, `entrada_voz` y el nuevo `canal`. |
| `hallazgos` | Los del auditor, o vacío. |

### 3.1 Dos extensiones aditivas obligatorias

La escena en vivo necesita un personaje y un origen que hoy no existen en el
contrato. Son **aditivos**: no cambian los campos ni el significado de los
valores actuales.

1. `PersonajeEscena` acepta `"invitado"`. Es el voluntario escribiendo por
   WhatsApp. Va **solo en subtítulo**, sin voz (no tiene entrada en
   `config/voz.toml`). En la pantalla se etiqueta «Invitado».
2. `OrigenTurno` acepta `"canal"`. Distingue un turno que sale del canal
   (mensaje del invitado o respuesta de Pana por WhatsApp) de uno que sale de
   una herramienta (`origen="herramienta"` en el sobre de la lista).

En el mismo commit se actualizan:

- `src/banco_occidente_corpus/escena/contratos.py` (los dos `Literal`).
- `app/web/escena/contrato.js` (`PERSONAJES`, `ORIGENES`, `FICHAS` y
  `pasoDelTurno`).
- `test/test_escena_contratos.py` y `test/test_web_escena.py` (los conjuntos
  esperados).
- `app/web/escena/rostros.js`: un dibujo de respaldo para `invitado` (puede
  reutilizar el del joven o un SVG neutro). **No** se exige un `.webp` nuevo ni
  una foto real; la prueba de retratos se ajusta a los seis personajes con voz.
- `docs/ESCENA.md`: la tabla de personajes y orígenes, y la tecla **E**.

`config/voz.toml` **no** recibe una entrada para `invitado`: la pantalla nunca
llama a la voz para ese personaje.

## 4. La lista `data/escena/en_vivo.jsonl`

### 4.1 Formato

Una línea JSON por turno. Ejemplo (con saltos solo para leerlo):

```json
{
  "seq": 1795705500123007,
  "ts": "2026-11-26T15:05:00.123+00:00",
  "origen": "herramienta",
  "turno": {
    "id": "gota.oferta.v1",
    "orden": 1,
    "personaje": "don_gota",
    "texto": "¿Necesitas $1.000.000? Te los presto hoy...",
    "subtitulo": null,
    "cifras": [],
    "escenario": null,
    "origen": "guion_fijo",
    "hallazgos": []
  }
}
```

En el archivo va **en una sola línea**, sin indentación.

| Campo exterior | Tipo | Regla |
|---|---|---|
| `seq` | entero | Creciente y único en el archivo. No es un contador consecutivo; la pantalla lo trata como opaco. |
| `ts` | string | ISO 8601 con zona, en UTC. Se usa para mostrar y depurar; no ordena. |
| `origen` | `"herramienta"` o `"canal"` | Quién publicó: el MCP o el despachador. |
| `turno` | objeto | `TurnoEscena.model_dump(mode="json")` exacto: sin claves extra. |

### 4.2 Reglas de la lista

- **Una emisión, una línea por turno.** Un lote de Don Gota son cuatro líneas
  con `seq` consecutivos y el mismo `ts`; la comparación son tres; la
  negociación, una por turno; el auditor y la ficha, una cada uno.
- **Solo se añade.** Nunca se edita ni se borra una línea mientras el evento
  corre. Una corrección se publica como un turno nuevo.
- **No se publica un turno inválido.** Se valida con Pydantic antes de escribir.
- **Serialización:** `Decimal` como texto (lo que produce
  `model_dump(mode="json")`), tuplas como listas, `None` como `null`. La pantalla
  acepta el decimal como número o como texto.
- **Límites:** 4.000 caracteres de `texto`; 16 KiB por línea; si un turno los
  supera, no se publica y se registra solo el código. El archivo no rota durante
  el evento; se borra al terminar.
- **Sin datos personales.** No se escriben números de teléfono, correos,
  documentos, nombres de personas, huellas HMAC ni la pregunta cruda cuando el
  detector encuentra PII (§13). Tampoco se escriben argumentos de herramientas,
  prompts, tokens ni rutas internas.
- **Codificación:** UTF-8 sin BOM, saltos `\n`. En Windows se abre con
  `newline="\n"` para no escribir `\r\n`.

### 4.3 Git

`data/escena/` ya está ignorado. Se comprueba antes de implementar:

```powershell
git check-ignore -v data/escena/en_vivo.jsonl
```

Debe imprimir la regla de `.gitignore` (hoy la línea de `data/escena/`). El
índice vectorial y las SQLite no se tocan. `test_seguridad.py` amplía
`RUTAS_IGNORADAS` con `data/escena/en_vivo.jsonl` y `data/escena/en_vivo.lock`.

## 5. El interruptor `ESCENA_EN_VIVO`

- Solo el valor exacto **`ESCENA_EN_VIVO=1`** activa la escritura. `0`, vacío,
  `true`, `sí` o la variable ausente no escriben nada.
- Se consulta **en cada publicación**, no al importar el módulo. Apagar la
  variable detiene la escritura de inmediato, sin reiniciar.
- Sin el interruptor no se crea `data/escena/`, no se abre el archivo, no se
  toca el bloqueo y no se escribe una sola línea. La ruta devuelve una lista
  vacía (§10).
- El interruptor no vive en `config/` ni en `.env`: es una variable de la
  sesión. **La app y el MCP deben tenerla en su propio proceso.** Si solo la
  tiene uno, la escena queda a medias:

```powershell
# Ventana del MCP
$env:ESCENA_EN_VIVO = "1"
make agente-mcp

# Ventana de la app
$env:ESCENA_EN_VIVO = "1"
make app
```

- El gateway de OpenClaw no necesita la variable: solo llama al MCP.
- Pruebas: con la variable ausente y con `0`, el archivo no existe y la ruta
  responde vacía; con `1`, escribe; apagarla entre dos llamadas detiene la
  segunda.

## 6. Escritura segura entre procesos y `seq`

### 6.1 Estrategia elegida: bloqueo y archivo único

Se usa **un solo archivo** y un **bloqueo exclusivo del sistema** sobre un
archivo centinela. No se usa “un archivo por proceso”: la pantalla y el borrado
necesitan una sola lista.

- Archivo de datos: `data/escena/en_vivo.jsonl`.
- Archivo de bloqueo: `data/escena/en_vivo.lock` (vacío o con un byte; nunca se
  lee como datos).
- Bloqueo: `msvcrt.locking` en Windows y `fcntl.flock` en POSIX, sobre el
  centinela. Es un bloqueo asesor del sistema operativo: se libera solo si el
  proceso muere, no deja archivos “pegados” como un `O_EXCL`.
- Además hay un `threading.Lock` en el proceso para ordenar hilos antes de
  pedir el bloqueo del sistema.
- Espera máxima: **2 s**. Si no se consigue, el lote se descarta (no se bloquea
  la herramienta ni la respuesta al invitado), se registra `bloqueo_ocupado` sin
  texto y se devuelve una lista vacía de `seq`.
- Sección crítica: leer el último `seq` válido del archivo, calcular los `seq`
  del lote, escribir todas las líneas, `flush`, `os.fsync`, soltar el bloqueo.
- La lectura **no** toma el bloqueo. Un lector puede ver la última línea a
  medias; la ignora y la vuelve a leer en el siguiente sondeo. Nunca se avanza
  `ultimo` con una línea incompleta.
- Se asume que la app y el MCP corren en el **mismo host y ven la misma ruta**
  (Windows). El MCP es un proceso de Windows; el gateway puede estar en WSL,
  pero quien escribe es el MCP. Si alguien mueve el MCP a WSL con otra vista del
  sistema de archivos, el bloqueo deja de ser confiable: en ese caso no se
  enciende la escena en vivo.

### 6.2 Cálculo de `seq`

`seq` no es un contador de líneas; es un identificador monotónico que sobrevive
al borrado del archivo:

```text
ahora_ms  = época actual en milisegundos
candidato = ahora_ms * 1000 + (contador_del_proceso % 1000)
seq       = max(último_seq_válido_del_archivo + 1, candidato)
```

- `contador_del_proceso` empieza en 0 y sube con cada turno del lote.
- El `max` con el último del archivo garantiza que dos procesos no repitan
  `seq` y que el orden no retroceda aunque el reloj se ajuste.
- Los valores son grandes (≈ 1,76 × 10¹⁵ en 2026) pero caben con holgura en el
  entero seguro de JavaScript (9 × 10¹⁵); la pantalla no hace aritmética con
  ellos, solo los compara.
- Si el archivo se borra y se vuelve a crear, el `seq` nuevo sigue siendo mayor
  que el anterior (mientras el reloj no retroceda). Aun así, el procedimiento de
  borrado pide salir del modo en vivo y volver a entrar con **E** para reiniciar
  el cursor de la pantalla (§12).
- Un lote usa `seq` consecutivos a partir del primero y un solo `ts`; así cuatro
  turnos de Don Gota se leen como una unidad.

### 6.3 Lectura tolerante

- Se lee el archivo completo o, si supera 2 MB, sus últimos 2 MB.
- Se ignoran líneas vacías, líneas que no son JSON, líneas con `seq` no entero
  y líneas cuyo `turno` no valida con `TurnoEscena`.
- Se ordena por `seq` ascendente y se devuelven como máximo **200** turnos con
  `seq > desde`. Si hay más, la pantalla vuelve a pedir con el nuevo `ultimo`.
- `ultimo = max(desde, seq del último turno devuelto)`. Si no hay turnos
  nuevos, `ultimo = desde`.
- Si el archivo no existe, la lista es vacía y `ultimo = desde`; la ruta **no**
  crea la carpeta ni el archivo.

## 7. Publicador: interfaz compartida

`src/banco_occidente_corpus/escena/publicador.py` (Nayla) expone dos funciones.
Son la única puerta de escritura y lectura del archivo; nadie más abre
`en_vivo.jsonl`.

```text
publicar_turnos(
    turnos: Iterable[TurnoEscena],
    *,
    origen: Literal["herramienta", "canal"],
    permitidos: Iterable[str] = (),
    ruta: Path | None = None,
) -> tuple[int, ...]
```

- Devuelve los `seq` escritos, en orden. Con el interruptor apagado devuelve
  `()`.
- Valida cada turno; descarta los inválidos y los que traen PII. No lanza
  excepciones hacia la herramienta ni hacia el canal: un `OSError`, un bloqueo
  ocupado o un turno inválido se registran por código y la función sigue.
- `permitidos` son los teléfonos públicos del banco que el detector de PII no
  debe marcar (los del canal oficial). Las herramientas lo omiten; el canal lo
  pasa.
- `ruta` es solo para pruebas (`tmp_path`); por defecto
  `PROJECT_ROOT / "data" / "escena" / "en_vivo.jsonl"`.

```text
leer_turnos(
    desde: int = 0,
    *,
    limite: int = 200,
    ruta: Path | None = None,
) -> tuple[tuple[dict[str, object], ...], int]
```

- Devuelve `(registros, ultimo)`; cada registro es
  `{"seq", "ts", "origen", "turno"}`.
- No escribe, no crea carpetas y no toma el bloqueo.
- Es la función que usa la ruta de §10; las pruebas pueden llamarla directo.

### 7.1 Qué nunca hace el publicador

- No calcula cifras, no decide rutas, no llama a un modelo, no hace red.
- No guarda el texto en logs: solo `seq`, código de descarte y conteo.
- No publica argumentos de herramientas ni la pregunta cruda.
- No reordena ni deduplica por `turno.id`: la identidad es `seq`.

## 8. Herramientas (Nayla)

Las cinco herramientas publican **después** de calcular y **solo** si su
resultado es correcto. El sobre de la herramienta no cambia: la publicación es
un efecto lateral local, no un campo de la respuesta.

| Herramienta | Fuente de los turnos | Cuántos | `personaje` | `turno.origen` | `orden` sugerido |
|---|---|---|---|---|---|
| `calcular_prestamo_gota` | `escena.gota.turnos_don_gota(prestamo, perfil="vivo")` | 4 | `don_gota` | `guion_fijo` | 1–4 |
| `comparar_gota_banco` | `escena.comparacion.turnos_pana_comparacion(comparacion, orden_inicial=8)` | 3 | `pana` | `guion_fijo` | 8–10 |
| `negociar_opcion` | `resultado.negociacion.turnos` | 1–4 | `agente_joven` y `agente_banco` | `llm` o `reglas` | 11+ |
| `auditar_respuesta` | `escena.auditor.turno_auditor(veredicto, orden=90)` | 1 | `auditor` | `reglas` | 90 |
| `generar_ficha_opcion` | un `TurnoEscena` nuevo con el `texto` de la ficha | 1 | `pana` | `reglas` | 91 |

### 8.1 Reglas por herramienta

- **`calcular_prestamo_gota`.** Usa el `PrestamoGota` que ya calculó, con
  `perfil="vivo"` fijo para que las frases sean reproducibles. No usa el perfil
  del invitado: la herramienta no lo recibe. Publica los cuatro turnos con
  `origen="herramienta"` en el sobre.
- **`comparar_gota_banco`.** Usa la `ComparacionGota` ya calculada y
  `orden_inicial=8`. Publica los tres turnos de Pana (golpe, tasa y ley), cada
  uno con sus cifras y fuentes.
- **`negociar_opcion`.** Publica `resultado.negociacion.turnos` tal como salen,
  uno por línea. No publica el `veredicto` que también devuelve la herramienta:
  el veredicto de la escena lo publica `auditar_respuesta`. Si un turno no es de
  `agente_joven` o `agente_banco`, no se publica desde aquí.
- **`auditar_respuesta`.** Convierte su salida en un `VeredictoAuditor`
  (`veredicto`, `hallazgos`, `turnos_revisados=()`, `reglas=()`,
  `alternativas=()`) y llama a `turno_auditor(..., orden=90)`. Publica un turno
  de auditor, incluso si el veredicto es `objeta`: objetar es parte de la
  escena. La llamada de cierre del recorrido debe ser **una sola**; si el agente
  la usa después de cada mensaje, la pantalla mostrará varios veredictos y el
  guion debe evitarlo.
- **`generar_ficha_opcion`.** Publica un turno de Pana con
  `id="vivo.ficha.v1"`, `texto=resultado["texto"]`,
  `subtitulo="Ficha de la opción"`, `origen="reglas"` y `cifras=()`. El PNG no
  viaja en la lista: solo su texto equivalente. Si `texto` viene vacío, no se
  publica.

### 8.2 Fallos y bordes

- Si la herramienta devuelve `ok=False`, no se publica nada.
- Si el módulo de la escena lanza (`ValueError`, `TasaNoDisponible`, etc.), la
  herramienta responde como hoy y no se publica el lote.
- Si el turno supera 4.000 caracteres o 16 KiB, se descarta solo ese turno; los
  demás del lote siguen.
- Si el interruptor está apagado, no se publica y la herramienta responde
  exactamente igual que hoy.
- Las demás herramientas del catálogo **no** publican: `consultar_tasa`,
  `simular_cuota`, `verificar_usura`, `diagnosticar_capacidad`,
  `comparar_escenario`, `convocar_comite`, `responder_sobre_proyecto`,
  `buscar_en_documentos`, `consultar_tarifas`, `clasificar_pregunta` y las de
  estado. La escena en vivo no cambia su contrato.

## 9. Canal (Darley)

### 9.1 Activación con `ESCENA`

- El texto se normaliza (minúsculas, sin espacios sobrantes). La palabra exacta
  **`ESCENA`** activa al invitado como voluntario.
- Se reconoce **después** de la autorización y del consentimiento de la Ley
  1581, y **antes** de la entrevista, del escenario y del motor de OpenClaw. El
  comando no se reenvía a Pana ni se publica como mensaje del invitado. Si el
  invitado tenía una entrevista del diagnóstico a medias, `ESCENA` la deja
  (equivale a cancelarla) para que el siguiente mensaje sea de la escena.
- Si `ESCENA_EN_VIVO` no está en `1`, el canal responde con una frase fija
  («La escena en vivo no está activada») y no publica nada. No se trata como una
  pregunta de crédito.
- Con el interruptor encendido, Pana confirma con una frase fija («Escena en
  vivo activada. Escribe tu primera pregunta.»), la envía por WhatsApp y
  publica esa confirmación como un turno `pana` con `origen="canal"`. Así la
  pantalla sabe que hay voluntario.

### 9.2 Memoria del voluntario (en memoria, con TTL)

- `canal/escena_vivo.py` guarda **un solo** voluntario activo:
  `{"huella": <usuario_id HMAC>, "vence": <datetime UTC>}`.
- Se guarda en memoria del proceso; no va a SQLite, no se versiona y se pierde
  al reiniciar. Nunca se guarda el número en claro.
- TTL configurable en `config/whatsapp.toml [evento]`:

```toml
# Minutos que la huella del voluntario queda activa para la escena en vivo.
escena_ttl_minutos = 180
```

- `ESCENA` fija `vence = ahora + ttl` y, si ya había otro voluntario, lo
  reemplaza. Cada mensaje del voluntario **renueva** el vencimiento (TTL
  deslizante); así no se corta a mitad del recorrido.
- Al vencer, el invitado deja de publicar; puede escribir `ESCENA` otra vez.
- Un segundo invitado que escribe `ESCENA` reemplaza al primero de inmediato.
  El anterior sigue recibiendo respuestas privadas, pero no se publica.
- El acceso a la ranura se protege con un `threading.Lock`; el trabajador del
  canal es uno, pero las pruebas y un reinicio no deben dejar estados a medias.

### 9.3 Qué se publica

| Evento | `personaje` | `id` | `texto` | `origen` |
|---|---|---|---|---|
| Mensaje del voluntario | `invitado` | `canal.invitado.v1` | Su texto saneado; `subtitulo=null` | `canal` |
| Respuesta de Pana | `pana` | `canal.pana.v1` | El texto exacto que se envió, recortado a 4.000 | `canal` |
| Confirmación de `ESCENA` | `pana` | `canal.pana.escena.v1` | La frase fija de activación | `canal` |

- El turno del invitado se publica **antes** de llamar al motor; así el orden de
  la lista es: invitado → turnos de herramientas → respuesta de Pana.
- La respuesta de Pana se publica **después** de que `enviar` termina bien. Si
  el envío falla, no se publica una respuesta que el invitado no recibió.
- `orden=0` en los turnos del canal: no ordena nada; la pantalla usa `seq`. La
  identidad de la emisión es `seq`, no `id`.
- Si la respuesta es solo una imagen o una tarjeta sin texto, no hay turno de
  Pana en la lista; el texto y la imagen siguen su camino por WhatsApp.
- Si el mensaje del invitado es un botón o una lista, se publica su `texto`
  visible (nunca el `id_boton` interno).

### 9.4 Los demás invitados no se publican

Solo la huella activa publica. Para cualquier otro invitado:

- su mensaje **no** entra en la lista;
- la respuesta de Pana **no** entra en la lista;
- su conversación privada sigue funcionando igual que hoy.

Esto es deliberado: el público no debe ver los datos ni las preguntas de otros
invitados.

### 9.5 Limitación documentada: el MCP no sabe quién llamó

El MCP recibe la llamada de OpenClaw, no del invitado. No hay forma de saber si
quien provocó `calcular_prestamo_gota` fue el voluntario u otro invitado. Por
eso:

- **Durante la escena solo el voluntario hace el recorrido del crédito.**
- Los demás invitados pueden saludar, preguntar por productos o pedir un
  asesor, pero no deben pedir el préstamo de Don Gota, la comparación, la
  negociación, la auditoría ni la ficha.
- Si otro invitado dispara una herramienta, sus turnos sí se publican (no
  llevan PII), pero su mensaje no; la escena puede saltar. Es un riesgo
  operativo, no de privacidad. Quien facilita lo evita con la tarjeta y con la
  frase de apertura.

No se añade `usuario_id` a las herramientas para arreglarlo: cambiaría el
catálogo y el contrato del MCP a un día del evento. Queda como limitación
conocida y como trabajo posterior si la escena se conserva.

### 9.6 PII en el canal

- Antes de publicar el mensaje del invitado se aplica
  `asistente.validacion.detectar_pii` (con `permitidos` para los teléfonos
  públicos del banco) y el saneado de nombres de §13.
- Si hay teléfono, correo, documento o tarjeta, **no se publica el mensaje
  crudo**. El canal responde con la frase fija de PII y publica **esa respuesta**
  de Pana, que no contiene el dato.
- Si la respuesta de Pana trae PII (por ejemplo, porque repite un nombre o un
  número), no se publica; se registra el código y la pantalla no la muestra.
- `ESCENA` no se publica como mensaje del invitado; solo su confirmación.

## 10. Ruta `GET /api/escena/en-vivo` (Darley)

Se crea `src/banco_occidente_corpus/escena/api_en_vivo.py` con
`crear_router_en_vivo()` y se monta en `app.py` **antes** de los estáticos, junto
a los demás routers. No se toca `escena/api.py` para evitar conflictos.

```http
GET /api/escena/en-vivo?desde=0
```

Respuesta (modelo Pydantic cerrado, `extra="forbid"`):

```json
{
  "turnos": [
    {
      "seq": 1795705500123007,
      "ts": "2026-11-26T15:05:00.123+00:00",
      "origen": "herramienta",
      "turno": { "id": "gota.oferta.v1", "orden": 1, "personaje": "don_gota", "texto": "...", "subtitulo": null, "cifras": [], "escenario": null, "origen": "guion_fijo", "hallazgos": [] }
    }
  ],
  "ultimo": 1795705500123007
}
```

| Regla | Valor |
|---|---|
| `desde` | entero ≥ 0; por defecto 0. Devuelve solo `seq > desde`. Un valor inválido responde 422. |
| `turnos` | Registros completos `{seq, ts, origen, turno}`, en orden ascendente de `seq`, máximo 200. |
| `ultimo` | `max(desde, seq del último turno devuelto)`; si no hay nuevos, `desde`. |
| Archivo ausente | `{"turnos": [], "ultimo": desde}`, sin crear nada. |
| Interruptor apagado | `{"turnos": [], "ultimo": desde}`; no se lee el archivo. |
| Línea inválida | Se ignora; la ruta no falla por una línea a medias o corrupta. |
| Escritura | Ninguna: no crea archivos, no abre SQLite, no toca el bloqueo. |
| Caché | `Cache-Control: no-store`; la pantalla pide `cache: "no-store"`. |
| Host | La app ya escucha solo en `127.0.0.1`; la ruta no se publica en `0.0.0.0`, no se añade túnel ni CORS. |
| Errores | 422 para `desde` inválido; 200 con lista vacía para archivo ausente o interruptor apagado. |

La ruta no devuelve la ruta del archivo, ni el bloqueo, ni la huella, ni el
número. Tampoco registra el texto de los turnos.

## 11. Pantalla (Yoldy)

### 11.1 Tecla y modo

- La tecla **E** entra y sale del modo «En vivo». También hay un botón «En
  vivo» en `escena.html` con `aria-pressed`.
- Al entrar: se pausa la reproducción normal de la escena, se limpia la cola, se
  fija `desde=0` y se hace el primer sondeo de inmediato. Se muestran todos los
  turnos que ya existan, en orden, y luego los nuevos.
- Al salir: se detiene el sondeo, se vacía la cola y la escena normal queda en
  pausa, en el mismo punto en que estaba. El modo en vivo no borra la escena
  proyectada ni la guardada.
- **R** en modo en vivo reinicia la lista (`desde=0`, cola vacía) y vuelve a
  reproducir. **P** pausa o reanuda la cola; **Espacio** salta al siguiente
  turno; **S** sigue alternando solo subtítulos. Las demás teclas conservan su
  comportamiento, pero **N** y **Q** no deben mezclar la escena normal con la
  lista en vivo: si se usan, primero se sale del modo en vivo.

### 11.2 Sondeo

- Cada **2 s**, con `setTimeout` después de cada respuesta (nunca `setInterval`),
  para que no se solapen dos peticiones.
- `fetch("/api/escena/en-vivo?desde=" + encodeURIComponent(desde), {cache:
  "no-store", signal})` con `AbortController` y techo de 1,5 s.
- Se detiene con la pestaña oculta (`document.hidden`) y se reanuda con un
  sondeo inmediato al volver. Se detiene al salir del modo.
- Si la ruta falla, el estado dice «Sin conexión (reintentando)» y se vuelve a
  intentar a los 2 s; no se pierde la cola.
- El estado muestra «En vivo», «Esperando el primer turno», el último `seq` y
  cuántos turnos hay en cola. No muestra datos personales.

### 11.3 Reproducción

- Se valida cada registro con `erroresDelTurno` de `contrato.js`. Un turno
  inválido no se dice: se muestra «Turno descartado: …» en la barra de estado y
  se sigue con el siguiente. `ultimo` ya avanzó, así que no se repite.
- La cola se ordena por `seq` y se deduplica por `seq`. Se reproduce **un turno
  a la vez**, en orden estricto; los nuevos se añaden al final.
- Para `pana`, `don_gota`, `agente_joven`, `agente_banco` y `auditor` se usa
  `decirComo(turno.personaje, turno.texto, {alTerminar, soloSubtitulos})`, con
  la voz de `app/web/voz.js`.
- Para `invitado` **no se llama a la voz**: se muestra el subtítulo y se avanza
  con un tiempo de lectura (`max(2 s, 55 ms por letra)`, con techo de 6 s). Es
  el único personaje sin voz.
- Si el modo solo subtítulos está activo, ningún personaje llama a la voz y se
  usa el mismo tiempo de lectura.
- El subtítulo es `turno.subtitulo ?? turno.texto`, completo, en el
  `aria-live` que ya existe. Si el navegador bloquea el audio, se cae a
  subtítulos para ese turno y se avisa en la barra; la cola sigue.
- El avatar de `invitado` es el dibujo de respaldo de `rostros.js` (puede
  reutilizar el del joven o un SVG neutro). No se usa una foto real ni un
  `.webp` nuevo obligatorio.
- La pantalla no calcula cifras, no usa `innerHTML` y no guarda la lista en
  `localStorage` ni `sessionStorage`. El cursor `desde` vive solo en memoria.

### 11.4 Qué se ve

| Turno | Voz | Subtítulo | Etiqueta |
|---|---|---|---|
| `invitado` | no | sí, completo | «Invitado» |
| `pana` | sí | sí | «Pana» |
| `don_gota` | sí | sí | «Don Gota» |
| `agente_joven` | sí | sí | «Agente del joven» |
| `agente_banco` | sí | sí | «Agente del banco» |
| `auditor` | sí | sí | «Auditor» |

El paso de la escena se sigue deduciendo con `pasoDelTurno`; `invitado` cae en
«Voluntario» por defecto y no retrocede.

## 12. Borrado

`scripts/limpiar_evento.ps1` debe borrar, además de lo que ya borra, estos dos
archivos. Si la rama integrada todavía no trae el script, se toma del #220
antes del punto de control:

- `data/escena/en_vivo.jsonl`
- `data/escena/en_vivo.lock`

Reglas:

- El modo de prueba (sin `-Confirmar`) solo lista lo que borraría; no toca la
  lista.
- Con `-Confirmar`, borra los dos archivos y deja la carpeta `data/escena/`
  (los JSON de la escena proyectada se regeneran aparte).
- El borrado se hace **con la pantalla fuera del modo en vivo y, si es posible,
  con la app y el MCP detenidos**. Al reiniciar se limpia la memoria del
  voluntario activo.
- Después del borrado, la variable `ESCENA_EN_VIVO` se apaga (`0` o se elimina)
  y se reinicia la app. Si la pantalla queda abierta, se sale con **E** y se
  vuelve a entrar para reiniciar `desde=0`.
- Prueba: una prueba de documento/script comprueba que el nombre
  `data/escena/en_vivo.jsonl` aparece en la lista de archivos del script; la
  prueba de modo de prueba verifica que no borra.

## 13. Privacidad y datos personales

### 13.1 Lo que nunca entra en la lista

- Números de teléfono, correos, documentos, tarjetas, direcciones.
- Nombres de personas reales. Solo se permiten los nombres de los personajes
  (Pana, Don Gota, auditor, agentes) y los datos públicos del banco.
- Huellas HMAC, `usuario_id`, `remitente`, `id_mensaje` de Meta.
- La pregunta cruda cuando el detector encuentra PII.
- Argumentos de herramientas, prompts, tokens, rutas internas, secretos.
- Textos de otros invitados.

### 13.2 Detector y saneado

- Detector: `asistente.validacion.detectar_pii` (el que ya usa el asistente),
  con `permitidos` para los teléfonos públicos del canal oficial.
- Se aplica a `texto` y `subtitulo` antes de escribir, tanto en las herramientas
  como en el canal.
- Nombres: se enmascaran las formas «me llamo …», «soy …» y «mi nombre es …»
  con `[nombre]`; si después del saneado el detector sigue encontrando PII, el
  turno no se publica.
- El publicador es la última barrera: aunque una herramienta o el canal se
  equivoquen, no escribe un turno con PII.
- Los logs solo llevan códigos (`pii`, `bloqueo_ocupado`, `turno_invalido`) y
  conteos; nunca el texto.

### 13.3 Residual y regla de operación

El detector no reconoce todos los nombres propios. Por eso la tarjeta y la
apertura piden **no escribir nombres, cédulas, teléfonos ni correos**, y el
voluntario usa un personaje ficticio. La prueba de Anny cubre los patrones
conocidos; la regla de operación cubre el resto.

## 14. Pruebas mínimas

Sin red, sin DeepSeek, sin Ollama y sin gateway. Las pruebas usan `tmp_path` y
`monkeypatch` para `ESCENA_EN_VIVO`; no tocan `data/escena/` real.

| Dueño | Archivo | Casos mínimos |
|---|---|---|
| Nayla | `test/test_escena_publicador.py` | Apagado no crea nada; encendido escribe una línea por turno; lote de 4 con `seq` consecutivos; dos hilos y dos procesos no corrompen ni repiten `seq`; turno inválido y turno con PII no se escriben; lector con `desde`, límite, línea a medias y archivo ausente; no hay texto en logs. |
| Nayla | `test/test_herramientas_lectura.py` (ampliar) | Las cinco herramientas publican 4/3/1–4/1/1 con los personajes correctos; con el interruptor apagado no publican; un error de la herramienta no publica; la ficha es un turno de Pana; el auditor es un turno de auditor. |
| Darley | `test/test_canal_escena_vivo.py` | `ESCENA` activa solo tras consentimiento; TTL y renovación; un segundo `ESCENA` reemplaza; otro invitado no publica; invitado → Pana en orden; PII no publica el crudo y sí la frase fija; apagado no escribe; reinicio pierde la memoria. |
| Darley | `test/test_escena_en_vivo_api.py` | `desde` filtra y `ultimo` avanza; máximo 200; archivo ausente; interruptor apagado; línea corrupta ignorada; la ruta no crea ni modifica archivos; `desde` inválido da 422; la app sigue en `127.0.0.1`. |
| Yoldy | `test/test_web_escena.py` y `test/test_web_escena_en_vivo.py` | `E` está en el teclado y el botón existe; `envivo.js` se sirve; `contrato.js` incluye `invitado` y `canal`; no hay URLs externas ni `innerHTML`; no se guarda en storage; la cola se ordena y deduplica por `seq` (función pura); el invitado no pide voz. |
| Anny | `test/test_escena_pii_en_vivo.py` y `test/test_seguridad.py` | Un teléfono, un correo y un documento falsos no aparecen en la lista, la ruta, los logs ni la tarjeta; la tarjeta/QR no lleva el número real ni datos de invitados; `data/escena/en_vivo.jsonl` y `.lock` están ignorados; el script de limpieza los nombra. |

Comandos de cierre:

```powershell
uv run pytest test/test_escena_publicador.py test/test_escena_en_vivo_api.py `
  test/test_canal_escena_vivo.py test/test_web_escena_en_vivo.py `
  test/test_escena_pii_en_vivo.py -q
make check
openspec validate agente-openclaw --strict
```

## 15. Punto de control del jueves 26 a las 12:00

### 15.1 Agenda

| Hora | Quién | Entregable |
|---|---|---|
| 08:00 | Nayla | `publicador.py` + lector + pruebas en verde |
| 08:30 | Darley | `canal/escena_vivo.py` + ruta + pruebas base |
| 08:30 | Yoldy | `envivo.js` + tecla E + pruebas estáticas |
| 08:30 | Anny | tarjeta/QR + prueba de PII |
| 10:00 | Los cuatro | integración: `ESCENA` → una herramienta → ruta → pantalla |
| 11:30 | Los cuatro | repaso de la lista de comprobación y ensayo cronometrado |
| 12:00 | Los cuatro | **go / no-go**; se congela lo que pase y se apaga lo que no |

### 15.2 Lista de comprobación (go / no-go)

1. `make check` en verde, sin red, sin `DEEPSEEK_API_KEY` y con Ollama apagado.
2. `openspec validate agente-openclaw --strict` en verde.
3. Con `ESCENA_EN_VIVO=1`, `calcular_prestamo_gota` escribe 4 líneas; con la
   variable apagada, no crea el archivo.
4. `comparar_gota_banco`, `negociar_opcion`, `auditar_respuesta` y
   `generar_ficha_opcion` publican sus turnos con los personajes correctos.
5. Un voluntario de prueba escribe `ESCENA` y su mensaje aparece como
   `invitado`; otro invitado escribe y **no** aparece.
6. La ruta devuelve los turnos en orden, `desde` filtra y `ultimo` avanza; no
   escribe nada.
7. La pantalla en Edge entra con **E**, consulta cada 2 s, reproduce en orden,
   el invitado va solo en subtítulo y el resto con voz.
8. Un teléfono, un correo y un documento falsos no aparecen en la lista, la
   ruta, los logs ni la tarjeta.
9. `scripts/limpiar_evento.ps1 -Confirmar` borra `en_vivo.jsonl` y
   `en_vivo.lock`; el modo de prueba no borra.
10. El ensayo completo dura menos de seis minutos y el facilitador puede
    explicar la limitación de §9.5 sin leer el documento.

Si falla un punto 1, 2, 5, 6, 7 u 8, **no se enciende la escena en vivo** para
la demo: se usa el plan B. Los puntos 3, 4 y 9 pueden quedar en rojo solo si el
plan B ya está probado y el facilitador lo sabe.

### 15.3 Plan B

| Si falla | Qué se hace |
|---|---|
| El publicador o la lista | `ESCENA_EN_VIVO=0`; la pantalla sigue con la escena proyectada y el núcleo. El facilitador narra. |
| La ruta | Se oculta el botón «En vivo»; `escena.html` usa la escena proyectada. |
| El canal no publica | Quedan los turnos de las herramientas; el mensaje del voluntario lo lee el facilitador. |
| La pantalla en vivo | Se usa `escena.html` normal y `make simular` como último recurso. |
| El gateway o el MCP | El canal cae al grafo (comportamiento actual); la lista puede quedar vacía; se usa el núcleo. |
| Duda de PII | `ESCENA_EN_VIVO=0`, borrar la lista, reiniciar la app y usar la escena proyectada. |
| Todo falla | La demo sigue con la escena proyectada y la traza; no se improvisa con datos de invitados. |

Órdenes de rollback:

```powershell
$env:ESCENA_EN_VIVO = "0"
.\scripts\limpiar_evento.ps1 -Confirmar
# reiniciar make app y make agente-mcp
```

Después de las 12:00 no se aceptan cambios funcionales en la escena en vivo; a
las 18:00 se aplica el congelamiento de la tarea 5.3.

## 16. Lo que este contrato no cambia

- No cambia el contrato de las veinte herramientas ni sus esquemas de entrada.
- No cambia `TurnoEscena` en sus campos: solo añade dos valores a dos `Literal`.
- No añade dependencias, `pip`, `requirements.txt` ni toca `uv.lock`.
- No toca Bronze, Silver ni Gold.
- No crea SQLite ni escribe en `data/asistente/`.
- No hace red desde el publicador, la ruta ni la pantalla.
- No publica precios de DeepSeek ni cifras nuevas: las cifras siguen saliendo
  de los módulos de la escena y del Tablero.
- No cambia `make simular`, `make escena-proyectada` ni la escena proyectada.

Si una herramienta o la pantalla necesita algo que no está aquí, se para la
implementación y se actualiza este documento primero. La escena en vivo es un
extra de la demo; la escena proyectada y el núcleo siguen siendo el respaldo.
