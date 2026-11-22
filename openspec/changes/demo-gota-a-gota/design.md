# Design

## Context

Ver `proposal.md` para la motivación. El estado actual que condiciona el diseño:

- `config/voz.toml` ya define los seis personajes de la escena (`pana`, `don_gota`, `joven`, `agente_joven`, `agente_banco`, `auditor`) y `app/web/voz.js` ya expone `decirComo(personaje, texto, {alTerminar, soloSubtitulos})`.
- `diagnostico/motor.py` convierte los ids de la entrevista en una `EntradaDiagnostico` y devuelve un `ResultadoDiagnostico` con cuota, tasa E.A., totales, semáforo, razón de endeudamiento, margen y aviso. `diagnostico/calculo.py` hace la aritmética en `Decimal` y lee la tabla Gold de tasas.
- `diagnostico/comite.py` ya tiene `PosturaAgente`, `EscenarioComite`, `construir_escenarios` y `auditar`, con las comprobaciones de cifras duras, promesas de aprobación, productos, PII y aviso orientativo.
- `config/tasas.toml` tiene la usura vigente, su fuente y su resolución; `tablero/tasas.py` la valida.
- `app/web/` es una SPA con vistas que se cargan por `import()` desde `app.js`; `app.py` registra los routers antes de montar los estáticos y escucha solo en `127.0.0.1`. La escena **no** entra en esa SPA: el PR #169 de Yoldy (rama `feat/pantalla-escena`) añade la página aparte `app/web/escena.html` con sus módulos en `app/web/escena/`, pensada para proyectar a pantalla completa.
- `simulador/` recorre el canal de WhatsApp con el enviador falso; `make simular` no se toca.
- Restricciones duras: solo `uv`; sin `.env`; sin secretos en el repositorio; sin datos personales; sin cambios en Bronze, Silver, Gold, tasas ni Bóveda; pruebas sin red, sin DeepSeek y sin Ollama; toda función pública con anotaciones y docstring en español.
- Calendario: revisión y congelamiento del contrato el **domingo 22 de noviembre**; construcción del lunes 23 al miércoles 25; ensayo general y congelamiento el **jueves 26 a las 18:00**; demo el **viernes 27**.

## Goals / Non-Goals

**Goals:**

- Entregar una escena en vivo de menos de seis minutos, con un voluntario aleatorio y un personaje inventado, sin guion escrito ni video.
- Hacer visibles y auditables las cifras: Don Gota calcula con código, Pana compara con el motor y la usura, los agentes negocian solo sobre una mesa precalculada y el auditor revisa todo.
- Separar con claridad el **semáforo del crédito** (resultado financiero del motor) del **veredicto del auditor** (`conforme`, `con_observaciones`, `objeta`).
- Tener un plan B operativo con solo subtítulos y clics, perfiles seguros y un núcleo Don Gota/Pana/auditor.
- Mantener la suite offline y el servidor local.

**Non-Goals:**

- Aprobación real de crédito, asesoría legal o una acusación contra una persona real. Don Gota es un personaje ficticio.
- Un modelo local de reconocimiento de voz o una dependencia nueva de transcripción.
- Cambiar el grafo de la Sucursal, el comité, el Gold o el canal de WhatsApp.
- Persistir datos del voluntario, grabar audio o publicar la app fuera de loopback.

## Decisions

### 1. Un contrato único: `TurnoEscena`

La escena es una lista ordenada de `TurnoEscena`. La voz, los subtítulos, la entrada por voz y el auditor consumen el mismo objeto; la pantalla no calcula cifras ni decide rutas.

```python
PersonajeEscena = Literal["pana", "don_gota", "joven", "agente_joven", "agente_banco", "auditor"]
OrigenTurno = Literal["guion_fijo", "motor", "llm", "reglas", "entrada_voz"]


class FuenteCifra(BaseModel):
    """Origen verificable de una cifra de la escena."""

    tipo: Literal["config", "gold", "motor", "calculo_gota", "usura", "guion"]
    referencia: str
    vigencia: str | None = None
    sha256: str | None = None


class CifraEscena(BaseModel):
    """Cifra que un turno dice, con su valor de máquina y su texto legible."""

    etiqueta: str
    valor: Decimal
    valor_legible: str
    unidad: Literal["pesos", "porcentaje_ea", "porcentaje", "meses", "dias", "veces"]
    fuente: FuenteCifra


class EscenarioEscena(BaseModel):
    """Escenario precalculado por el motor, con la decisión del código."""

    codigo: str
    descripcion: str
    producto: str
    monto: Decimal
    plazo_meses: int | None
    cuota_mensual: Decimal | None
    total_pagado: Decimal | None
    total_intereses: Decimal | None
    semaforo: Literal["verde", "amarillo", "rojo"] | None
    razon_endeudamiento: Decimal | None
    margen_despues_cuota: Decimal | None
    aceptable: bool
    ofertable: bool


class HallazgoEscena(BaseModel):
    """Hallazgo del auditor sobre un turno concreto."""

    codigo: str
    turno_id: str | None
    detalle: str
    gravedad: Literal["alta", "media"]


class TurnoEscena(BaseModel):
    """Unidad que comparten voz, subtítulos, entrada por voz y auditor."""

    id: str
    orden: int
    personaje: PersonajeEscena
    texto: str
    subtitulo: str | None = None
    cifras: tuple[CifraEscena, ...] = ()
    escenario: EscenarioEscena | None = None
    origen: OrigenTurno
    hallazgos: tuple[HallazgoEscena, ...] = ()


class PrestamoGota(BaseModel):
    """Resultado determinista del préstamo de Don Gota."""

    version_formula: str
    monto: Decimal
    tasa_mensual: Decimal
    dias_ciclo: int
    meses_horizonte: int
    interes_mensual: Decimal
    total_ciclo: Decimal
    cuota_diaria: Decimal
    intereses_horizonte: Decimal
    total_pagado_horizonte: Decimal
    tasa_ea: Decimal
    supuesto: str
    fuente: FuenteCifra


class ComparacionGota(BaseModel):
    """Comparación de Pana entre Don Gota, el banco y la usura."""

    monto: Decimal
    plazo_meses: int
    tasa_ea_banco: Decimal
    tasa_ea_gota: Decimal
    usura_ea: Decimal | None
    usura_vigencia: str | None
    total_banco: Decimal
    total_gota: Decimal
    diferencia: Decimal
    veces_total: Decimal | None
    veces_usura: Decimal | None
    articulo_305: str
    supuestos: tuple[str, ...]
    fuente_usura: FuenteCifra | None


class RespuestaEscena(BaseModel):
    """Respuesta del voluntario a una de las cuatro preguntas."""

    pregunta: Literal["monto", "ingresos", "gastos", "deudas"]
    letra: Literal["A", "B", "C", "D", "E", "F"]
    opcion_id: str
    texto: str
    valor: Decimal


class PerfilEscena(BaseModel):
    """Perfil ficticio que sostiene la escena; no contiene datos personales."""

    personaje: str
    proposito: str
    monto_declarado: Decimal
    monto_calculo: Decimal
    respuestas: tuple[RespuestaEscena, ...]
    vinculacion: Literal["empleado"] = "empleado"
    plazo_meses: Literal[36] = 36
    producto: Literal["libre_inversion"] = "libre_inversion"
    confirmado: bool


class SeleccionVoluntario(BaseModel):
    """Fila y silla elegidas al azar; no identifica a la persona."""

    fila: int
    silla: int
    filas: int
    sillas: int
    metodo: Literal["azar", "manual"]


class VeredictoAuditor(BaseModel):
    """Veredicto del auditor, independiente del semáforo del crédito."""

    veredicto: Literal["conforme", "con_observaciones", "objeta"]
    hallazgos: tuple[HallazgoEscena, ...]
    turnos_revisados: tuple[str, ...]
    reglas: tuple[str, ...]
    alternativas: tuple[str, ...] = ()


class Escena(BaseModel):
    """Escena completa que consume la pantalla."""

    id: str
    modo: Literal["vivo", "seguro", "nucleo", "proyectado"]
    perfil: PerfilEscena
    seleccion: SeleccionVoluntario | None
    diagnostico: ResultadoDiagnostico
    gota: PrestamoGota
    comparacion: ComparacionGota
    escenarios: tuple[EscenarioEscena, ...]
    turnos: tuple[TurnoEscena, ...]
    veredicto: VeredictoAuditor
    sellos: dict[str, str] = {}


class NegociacionEscena(BaseModel):
    """Turnos de la negociación y veredicto sobre la escena completa."""

    turnos: tuple[TurnoEscena, ...]
    escenarios: tuple[EscenarioEscena, ...]
    veredicto: VeredictoAuditor
    registro: tuple[str, ...] = ()
```

Invariantes:

1. La pantalla **MUST NOT** calcular cifras ni cambiar un `TurnoEscena`; solo lo pinta.
2. Toda `CifraEscena` **MUST** declarar una `FuenteCifra` verificable.
3. Los turnos de Don Gota **MUST** ser `origen="guion_fijo"`; nunca `origen="llm"`.
4. Los turnos de la negociación con LLM **MUST NOT** contener dígitos ni nombres de color en el `argumento`; las cifras las pone la plantilla desde el `EscenarioEscena`.
5. El auditor **MUST** revisar todos los turnos y su veredicto **MUST** ser la última palabra sobre el cierre.
6. La escena **MUST NOT** persistir el perfil del voluntario ni grabar audio.

La página `app/web/escena.html` valida del lado del cliente con `app/web/escena/contrato.js`, espejo de `TurnoEscena`: `fuente` con `tipo` y `referencia`, `valor_legible`, `unidad`, los cinco orígenes (`guion_fijo`, `motor`, `llm`, `reglas`, `entrada_voz`), el `escenario` completo y el `veredicto` del auditor en un campo aparte del `semaforo`. Ese espejo **MUST** seguir al contrato de Python; si diverge, la página no pinta el turno.

`CifraEscena.valor` usa la misma convención que el motor: las tasas son fracciones (`0.2834` es 28,34 % E.A.) y los pesos son unidades. `valor_legible` es el texto que se muestra; la plantilla y la tarjeta usan el mismo `valor_legible` para que no diverjan.

Ejemplo de turno de Pana:

```json
{
  "id": "pana.comparacion.v1",
  "orden": 8,
  "personaje": "pana",
  "texto": "Con Don Gota, por $1.000.000, en 36 meses pagarías $7.200.000 solo de intereses: $8.200.000 en total. Eso equivale a 791,61 % E.A. Si renuevas cada mes durante tres años, el supuesto es ese. La usura vigente es 28,34 % E.A.",
  "cifras": [
    {
      "etiqueta": "intereses en 36 meses",
      "valor": "7200000",
      "valor_legible": "$7.200.000",
      "unidad": "pesos",
      "fuente": {
        "tipo": "calculo_gota",
        "referencia": "escena.gota#intereses_horizonte"
      }
    },
    {
      "etiqueta": "tasa E.A. de Don Gota",
      "valor": "7.9161",
      "valor_legible": "791,61 % E.A.",
      "unidad": "porcentaje_ea",
      "fuente": {
        "tipo": "calculo_gota",
        "referencia": "escena.gota#tasa_ea"
      }
    },
    {
      "etiqueta": "usura vigente",
      "valor": "0.2834",
      "valor_legible": "28,34 % E.A.",
      "unidad": "porcentaje_ea",
      "fuente": {
        "tipo": "usura",
        "referencia": "config/tasas.toml#usura.tasa_ea",
        "vigencia": "2026-11-01/2026-11-30"
      }
    }
  ],
  "escenario": {
    "codigo": "comparacion",
    "descripcion": "Mismo monto y mismo horizonte de 36 meses",
    "producto": "libre_inversion",
    "monto": "1000000",
    "plazo_meses": 36,
    "cuota_mensual": null,
    "total_pagado": "8200000",
    "total_intereses": "7200000",
    "semaforo": null,
    "razon_endeudamiento": null,
    "margen_despues_cuota": null,
    "aceptable": false,
    "ofertable": false
  },
  "origen": "motor",
  "hallazgos": []
}
```

### 2. Don Gota: banco de frases y aritmética determinista

`config/escena.toml [gota]` guarda `tasa_mensual = 0.20`, `dias_ciclo = 30`, `meses_horizonte = 36` y un banco de frases fijas con variables (`oferta`, `presion_diaria`, `renovacion`, `cierre`). La frase se elige por índice determinista a partir del perfil; no se genera con LLM.

Fórmulas en `Decimal` y `ROUND_HALF_UP`:

```text
interes_mensual        = monto * tasa_mensual
total_ciclo            = monto + interes_mensual
cuota_diaria           = total_ciclo / dias_ciclo
intereses_horizonte    = interes_mensual * meses_horizonte
total_pagado_horizonte = monto + intereses_horizonte
tasa_ea                = (1 + tasa_mensual) ** 12 - 1
```

Con `$1.000.000`: interés mensual `$200.000`, total del ciclo `$1.200.000`, cuota diaria `$40.000`, intereses de 36 meses `$7.200.000`, total neto `$8.200.000` y `791,61 % E.A.`.

La escena **MUST** decir en voz el supuesto: “si renuevas cada mes durante tres años”. La E.A. es la equivalente compuesta de la tasa mensual; el total de intereses es simple porque el capital no baja. El `PrestamoGota.supuesto` lleva ese texto y la plantilla lo incluye; la UI lo muestra también en el panel de trazabilidad.

Alternativa descartada: capitalizar el 20 % mes a mes. Con 36 meses el total se vuelve exponencial (`1,20^36`) y la comparación deja de ser creíble para una audiencia; el supuesto de renovación sin capitalizar es más defendible y se declara.

### 3. Pana: comparación con el motor, la usura y el artículo 305

- Banco: `diagnostico.motor.calcular` con el mismo monto, `libre_inversion`, 36 meses y `vinculacion="empleado"`. Se usa el extremo **máximo** de `tasa_ea`, `cuota_mensual`, `total_pagado` y `total_intereses`, igual que el semáforo (`base_semaforo="tasa_maxima"`). La tarjeta puede mostrar el rango completo; la frase comparativa usa el máximo.
- Gota: el `PrestamoGota` anterior, con el mismo monto y el mismo horizonte de 36 meses.
- Usura: `config/tasas.toml [usura]`. Si `tasa_ea = 0` o no hay certificación, la comparación **MUST NOT** calcular el ratio; muestra `usura_sin_certificar` y el auditor no puede dar `conforme`.
- Si la tabla Gold no tiene tasa del producto, la escena **MUST NOT** inventar una; muestra `tasa_no_disponible`, usa el núcleo y el auditor no da `conforme`.
- Pana incluye una frase fija, con la usura vigente y su vigencia:

  > “Si alguien te cobra por encima del interés de usura, incurre en el delito de usura (Código Penal, artículo 305). La usura vigente es {usura} E.A., del {desde} al {hasta}.”

  La frase es informativa y no acusa a una persona real; Don Gota es un personaje ficticio. El texto y la usura salen de `config/tasas.toml`; no se escriben a mano en el prompt ni en la UI.
- La comparación declara sus supuestos en `ComparacionGota.supuestos` y la UI los muestra en el panel: mismo monto, mismo horizonte, tasa máxima del banco, renovación mensual sin capitalizar y usura vigente.

**Dos resultados distintos.** El `EscenarioEscena.semaforo` es el resultado financiero del motor (`verde`, `amarillo`, `rojo`). El `VeredictoAuditor.veredicto` es el cumplimiento de reglas (`conforme`, `con_observaciones`, `objeta`) y no usa colores. La pantalla los muestra separados: “Semáforo del crédito: rojo” y “Auditor: conforme” son posibles a la vez. Pana sugiere alternativas formales si el veredicto es `objeta` **o** si el mejor escenario queda en rojo o sin acuerdo.

### 4. Negociación: mesa precalculada, cuatro turnos, 15 segundos

Antes de llamar al modelo, `construir_mesa` calcula con el motor:

| Código | Monto | Plazo | Producto | ¿Ofertable? |
|---|---|---|---|---|
| `base` | el del perfil | 36 | libre inversión | sí |
| `plazo_mas_largo_48` | igual | 48 | libre inversión | sí |
| `plazo_mas_largo_60` | igual | 60 | libre inversión | sí |
| `monto_20_por_ciento_menos` | 80 % | 36 | libre inversión | sí |
| `monto_40_por_ciento_menos` | 60 % | 36 | libre inversión | sí |
| `compra_de_cartera` | igual | 36 | compra de cartera | sí, si hay deudas |
| `estres_de_ingreso` | igual | 36 | libre inversión | no: es prueba, no oferta |

- `agente_joven` y `agente_banco` usan prompts versionados en `config/prompts/negociacion_joven_v1.md` y `negociacion_banco_v1.md`; se añaden a `TAREAS` de `asistente/prompts.py`.
- El modelo responde `PropuestaNegociacion` (`codigo`, `decision`, `argumento`). El orquestador valida el código contra la mesa, descarta argumentos con dígitos o nombres de color y pone las cifras desde el `EscenarioEscena`. El modelo no recibe umbrales ni puede cambiarlos.
- Máximo **4 turnos**. Presupuesto: **15 segundos en total** y **4 segundos por llamada**. Temperatura 0, sin razonamiento y sin reintentos. El reloj se controla con `ThreadPoolExecutor` y `future.result(timeout=min(4, restante))`; al agotarse, se usa la política determinista para ese turno y los siguientes.
- La aceptación es código: el banco solo acepta `semaforo in {verde, amarillo}` y `margen >= 0`. Si el LLM dice “acepto” sobre un rojo, el orquestador lo convierte en rechazo y registra el intento en `NegociacionEscena.registro`.
- En `SUCURSAL_DEMO=1` o sin `DEEPSEEK_API_KEY` se usa directamente la política determinista, con los mismos cuatro turnos y `origen="reglas"`.

Secuencia determinista:

1. `agente_joven` propone el `base` o el mejor escenario aceptable que más se acerque al monto pedido.
2. `agente_banco` acepta si es aceptable; si no, contrapropone el mejor escenario aceptable o rechaza.
3. `agente_joven` acepta la contrapropuesta o propone la siguiente.
4. `agente_banco` cierra con el escenario aceptado o con `sin_acuerdo`.

La mesa no incluye el estrés como oferta; el auditor puede citarlo como prueba, pero ningún agente puede “venderlo”.

### 5. Auditor: reglas en código y veredicto sin colores

- Se extrae de `diagnostico/comite.py` una función pública `auditar_texto(...)` con las comprobaciones existentes: cifras duras, promesas de aprobación, productos, PII y aviso orientativo. `auditar` pasa a usarla **sin cambiar su comportamiento**; `test_diagnostico_comite.py` es el guardián.
- `escena/auditor.py` añade:
  - `cifra_inventada`: una cifra del texto no está en las `CifraEscena` del turno.
  - `fuente_ausente`: una `CifraEscena` no tiene referencia válida o su valor no coincide con el motor, el config o el Gold.
  - `promesa_aprobacion`: “aprobado”, “te lo apruebo”, “garantizado”, etc.
  - `recomienda_gota`: Pana, el agente del joven, el del banco o el auditor recomiendan el gota a gota. Don Gota está exento porque es el antagonista que lo ofrece; sus cifras sí se auditan.
  - `semaforo_alterado`: un turno dice un color distinto al del escenario del motor.
  - `dato_personal`: teléfono, correo, documento o nombre real.
  - `sin_negociacion`, `sin_acuerdo`, `tasa_no_disponible`, `usura_sin_certificar`, `vigencia_vencida`: observaciones medias.
- Mapeo de gravedad a veredicto: cualquier hallazgo **alto** → `objeta`; solo medios → `con_observaciones`; ninguno → `conforme`. El veredicto **MUST NOT** usar colores.
- Si el veredicto es `objeta`, Pana cierra con las alternativas fijas: **microcrédito, cooperativas y entidades vigiladas por la Superfinanciera**, sin prometer aprobación. Si el semáforo del mejor escenario es rojo o no hay acuerdo, también las ofrece, aunque el auditor esté `conforme`.
- El auditor no usa modelo. Su turno es corto; los hallazgos completos van en `hallazgos` y en el panel de trazabilidad. La UI **MUST NOT** habilitar un cierre verde si el veredicto es `objeta`.

### 6. Entrada por voz, confirmación y voluntario

- `escena/entrada.py` es un parser determinista, sin LLM y sin red. Reconoce letras A–F (incluye “be”, “ce”, “de”, “efe”, “letra B”), montos (“1.500.000”, “1,5 millones”, “ocho millones”, “dos palos”, “20 lucas”) y confirmaciones (“sí”, “confirmo”, “dale”, “no”, “cambia”).
- La transcripción la hace el navegador con `SpeechRecognition` en español. La UI **MUST** mostrar el aviso de que el navegador puede usar un servicio externo y **MUST** ofrecer teclado y tarjetas A–F como respaldo. No se graba audio; el texto se descarta al confirmar.
- El voluntario se elige por fila y silla con `secrets.SystemRandom` en vivo y semilla fija en pruebas. No se pide nombre; el voluntario inventa un personaje ficticio. Si dice un dato personal, Pana lo redirige y no lo guarda.
- Pana confirma en voz las cuatro respuestas y el monto. Sin confirmación no se avanza; a los dos intentos se usa el perfil seguro y se avisa en pantalla.
- Regla del monto: si el monto declarado cae dentro del rango de la letra, se usa ese monto exacto; si no, se usa el `valor` del rango y Pana lo dice. Nunca se recorta en silencio.
- Valores fijos: `vinculacion="empleado"`, `plazo_meses=36`, `producto="libre_inversion"`. Las cuatro preguntas son `monto`, `ingresos`, `gastos` y `deudas` (`cuotas` en el TOML).

### 7. Pantalla, voces, avatares y subtítulos

- La pantalla es la **página aparte** `app/web/escena.html` (PR #169 de Yoldy), con `app/web/escena/escena.js`, `escena.css`, `rostros.js`, `contrato.js` y `turnos-ejemplo.json`. No es una vista `#escena` de la SPA y **MUST NOT** añadir enlaces ni secciones a `app/web/index.html`; la página se abre directo en `http://127.0.0.1:8000/escena.html`, sin el resto del sitio alrededor, para proyectar.
- `app/web/escena/contrato.js` es el espejo de cliente de `TurnoEscena`: `fuente` con `tipo` y `referencia`, `valor_legible`, `unidad`, los orígenes `guion_fijo`, `motor`, `llm`, `reglas` y `entrada_voz`, el `escenario` completo y el veredicto del auditor en un campo aparte del `semaforo`. Se alinea con `escena/contratos.py` y con la salida de `make escena-proyectada`.
- `turnos-ejemplo.json` es solo andamio de maquetación. Cuando exista `make escena-proyectada`, se reemplaza por su salida real (`data/escena/proyectado.json`) y la página deja de depender de datos escritos a mano.
- Reutiliza `app/web/voz.js`: cada turno llama `decirComo(turno.personaje, turno.texto, {alTerminar, soloSubtitulos})`. El `personaje` del contrato es la misma clave de `config/voz.toml` y de `PERSONAJES`.
- Avatares vectoriales locales; Pana reutiliza `dibujar_pana` si entra el endpoint de avatar, y si no, un SVG consistente. El que habla se ilumina; los demás se atenúan.
- Subtítulos grandes, `aria-live`, alto contraste y botones: **Siguiente**, **Solo subtítulos**, **Núcleo**, **Perfil seguro**, **Reiniciar**. Teclado: espacio/Enter avanza, `S` subtítulos, `N` núcleo.
- Panel de trazabilidad para el facilitador: `id` del turno, `origen`, `escenario.codigo`, `fuente` de cada cifra y hallazgos. El público no lo ve por defecto.
- En `soloSubtitulos`, no se llama a `/api/voz`; se muestra el turno y se espera clic/tecla. Si `decirComo` devuelve `ninguna`, la UI cambia sola a ese modo.
- La escena se guarda en memoria y, si hace falta, en `sessionStorage` para sobrevivir a una recarga; no se envía a ningún servicio. El botón Reiniciar la borra.

### 8. API y CLI

La API es sin estado: no crea SQLite ni guarda perfiles. La UI conserva la escena.

| Método | Ruta | Entrada | Salida |
|---|---|---|---|
| GET | `/api/escena/opciones` | — | cuatro preguntas con letras A–F desde `config/diagnostico.toml` |
| GET | `/api/escena/perfiles` | — | perfiles seguros ficticios |
| POST | `/api/escena/voluntario` | `{filas, sillas, semilla?}` | `SeleccionVoluntario` |
| POST | `/api/escena/interpretar` | `{texto, pregunta}` | `RespuestaVoz` determinista |
| POST | `/api/escena` | `{perfil_id?, respuestas?, monto?, seleccion?}` | `Escena` de fase 1: perfil, diagnóstico, gota, comparación y turnos base |
| POST | `/api/escena/negociacion` | `{perfil, seleccion?}` | `NegociacionEscena`: cuatro turnos, escenarios y veredicto |
| GET | `/api/escena/proyectado` | `?modo=nucleo` | `Escena` precalculada desde `data/escena/*.json` |

- La fase 1 se pide al confirmar; la fase 2 se pide en paralelo. La UI empieza a hablar la fase 1 mientras la negociación se calcula. Si la fase 2 falla o tarda, la UI usa el núcleo que devuelve el mismo endpoint.
- El backend **MUST NOT** confiar en cifras del cliente: recalcula desde `PerfilEscena` y `config/`.
- `app.py` registra el router antes de los estáticos, como los routers actuales, y mantiene `HOST = "127.0.0.1"`.
- `pyproject` no cambia; no hay dependencias nuevas.

`escena/__main__.py` genera la escena de respaldo:

```text
uv run python -m banco_occidente_corpus.escena --proyectado
uv run python -m banco_occidente_corpus.escena --nucleo
uv run python -m banco_occidente_corpus.escena --perfil verde_empleado
```

El CLI no abre puertos; escribe `data/escena/proyectado.json` y `data/escena/nucleo.json` e imprime el resumen. `data/escena/` se ignora en Git.

### 9. Makefile: `make escena-proyectada`, sin tocar `make simular`

Se añade un objetivo **aparte**:

```make
.PHONY: escena-proyectada
escena-proyectada: ## Genera la escena de respaldo sin DeepSeek (no toca make simular)
	$(UV) run python -m banco_occidente_corpus.escena --proyectado
```

`make simular` queda exactamente como está. `make escena-proyectada` es el comando del plan B y del ensayo; escribe los JSON y no necesita red, DeepSeek ni Ollama.

### 10. Modo seguro y perfiles preparados

`config/escena.toml [perfiles]` contiene entre tres y cinco perfiles ficticios (verde, amarillo, rojo y un extremo). Cada uno declara `id`, `personaje`, `proposito`, `monto`, letras A–F y `esperado`. El color esperado se valida contra el motor al cargar; si no coincide, el perfil no se usa en modo seguro. El modo seguro salta el voluntario y el micrófono, pero **MUST** ejecutar el auditor.

Los perfiles no llevan nombres reales, teléfonos, correos ni documentos. La prueba de PII se aplica a sus textos.

### 11. Plan B en vivo

1. **Escena completa** con DeepSeek y voces.
2. Si la negociación falla o supera 15 s: **núcleo** automático, con Don Gota → Pana → auditor, `modo="nucleo"`.
3. Si falla la voz o el audio: **solo subtítulos y clics**.
4. Si falla el micrófono o el STT: tarjetas A–F y monto por teclado; o **perfil seguro**.
5. Si falla la API: `GET /api/escena/proyectado` con el JSON precalculado; si la app se cayó, reiniciar `make app`; capturas solo como último recurso.
6. Si falta la tasa o la usura: no se inventa nada; se muestra el aviso, se usa el núcleo y el auditor no da `conforme`.

Comandos:

```powershell
make check
make escena-proyectada
make voces-prueba
make app
# abrir http://127.0.0.1:8000/escena.html
# modo demo sin modelo:
$env:SUCURSAL_DEMO = "1"; make app
```

### 12. Trazabilidad y fuentes

`FuenteCifra` se verifica así:

| Tipo | Referencia | Verificación |
|---|---|---|
| `config` | `config/diagnostico.toml#...` | leer el TOML y comparar el valor |
| `gold` | `data/gold/tasas/...jsonl#libre_inversion` | leer la fila, comparar tasa, vigencia y `sha256` |
| `motor` | `diagnostico.motor.calcular#campo` | comparar con `ResultadoDiagnostico` |
| `calculo_gota` | `escena.gota#campo` | comparar con `PrestamoGota` |
| `usura` | `config/tasas.toml#usura.tasa_ea` | comparar con `Usura` |
| `guion` | `config/escena.toml#...` | comparar con la plantilla o el parámetro |

`Escena.sellos` guarda el `sha256` de `config/diagnostico.toml`, `config/tasas.toml`, `config/escena.toml` y la tabla Gold usada. El panel de trazabilidad los muestra truncados; el auditor usa la referencia y el valor, no el hash, para no depender de una ruta absoluta.

### 13. Pruebas

- `test_escena_gota.py`: 1.000.000 → 200.000 de interés, 1.200.000 de ciclo, 40.000 diarios, 7.200.000 de intereses a 36 meses, 8.200.000 de total y 791,61 % E.A.; redondeo; cambio de tasa en config; cero y negativos rechazados.
- `test_escena_comparacion.py`: mismo monto y horizonte; máximo de los rangos; usura vigente; `usura_sin_certificar`; `tasa_no_disponible`; artículo 305 presente; sin cifras inventadas.
- `test_escena_negociacion.py`: máximo cuatro turnos; 15 s totales y 4 s por llamada; códigos solo de la mesa; argumentos sin dígitos ni colores; el banco no acepta rojo; sin modelo funciona la política determinista; timeout → núcleo.
- `test_escena_auditor.py`: `auditar_texto` conserva el comportamiento del comité; reglas nuevas; `conforme`/`con_observaciones`/`objeta`; `objeta` bloquea el cierre verde; alternativas formales.
- `test_escena_estres.py`: 100 perfiles aleatorios con semilla y los extremos; mutaciones de cifra, fuente, promesa, gota, semáforo y PII; el auditor nunca deja pasar un hallazgo alto.
- `test_escena_entrada.py`: letras, montos, confirmación, ambigüedad, monto fuera de rango y datos personales.
- `test_escena_api.py` y `test_app_web.py`: opciones, voluntario con semilla, interpretar, escena, negociación, proyectado, router montado y `app/web/escena.html` servida con `contrato.js`; sin red.
- `test_seguridad.py`: `data/escena/` ignorado; sin secretos ni PII en `config/escena.toml`; el servidor sigue en loopback.

## Risks / Trade-offs

- **El voluntario no coopera o el micrófono falla** → Pana reintenta una vez, luego perfil seguro; las tarjetas A–F y el teclado están siempre disponibles.
- **DeepSeek tarda o falla** → 15 s totales y 4 s por llamada; política determinista y núcleo; la escena no se detiene.
- **La voz falla en el computador de la demo** → modo solo subtítulos y clics; `make voces-prueba` en el preflight; Edge como navegador recomendado.
- **La tasa está vencida o falta** → aviso visible, sin cifras inventadas, núcleo y auditor sin `conforme`; la escena es honesta sobre la limitación.
- **El auditor produce falsos positivos por números estructurales** → solo se auditan cifras financieras de turnos con `escenario` o `cifras`; fila, silla, letras y conteos de turnos se excluyen.
- **La comparación de 36 meses se malinterpreta** → la escena dice el supuesto en voz y el panel muestra “renovación mensual sin capitalizar”; no se presenta como una deuda única.
- **El reconocimiento del navegador usa un servicio externo** → aviso visible, sin datos reales, teclado como respaldo y ninguna grabación.
- **El tiempo de la presentación se alarga** → cuatro preguntas, cuatro turnos y botón Núcleo; el ensayo mide menos de seis minutos.
- **Confundir semáforo y veredicto** → el veredicto no usa colores y la UI los muestra en dos etiquetas separadas.

## Migration Plan

1. **Domingo 22**: revisión y congelamiento del contrato `TurnoEscena`, del veredicto sin colores, de los límites de 15 s/4 s y del objetivo `make escena-proyectada`.
2. **Lunes 23 a miércoles 25**: implementación por dueño, con `make check` en verde en cada rama.
3. **Jueves 26, 18:00**: congelamiento; no entran cambios funcionales. Ensayo general con un voluntario distinto al del día de la demo.
4. **Viernes 27, 08:00**: preflight en el computador de la demo (`uv sync`, `make check`, `make escena-proyectada`, `make voces-prueba`, `make app`, Gold vigente, clave de DeepSeek solo en la sesión, sin secretos).
5. **Rollback**: si la escena falla, no se toca el resto de la Sucursal; se usa el JSON de `data/escena/` y el modo solo subtítulos. El código de la escena queda aislado en `escena/` y `app/web/escena.html` se puede desactivar quitando el router y la página, sin tocar la SPA.

## Open Questions

No hay preguntas abiertas que cambien el alcance: las decisiones de la revisión del domingo 22 quedaron cerradas (sin capitalizar, `skip_specs: true`, voz del navegador con aviso, veredicto sin colores, 15 s/4 s y `make escena-proyectada`).
