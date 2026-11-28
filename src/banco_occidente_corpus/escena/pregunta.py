"""Núcleo de las preguntas del público a Pana en la escena.

`responder_pregunta` recibe una pregunta aislada y devuelve un único
`TurnoEscena` de Pana. El enrutamiento es fijo y se detiene en el primer paso
que coincide:

1. **Respuesta fija** (`guion_fijo`): coincidencia determinista de tokens contra
   las variantes de la ficha, con `umbral_fijo`. No llama al modelo.
2. **Pregunta del proyecto** (`llm`): BM25 en memoria sobre `README.md`,
   `AGENTS.md`, `CONSTITUTION.md` y `docs/`; el modelo resume el fragmento
   elegido en máximo 40 palabras.
3. **Pregunta del banco** (`llm` o `reglas`): la Ventanilla, inyectada, decide
   la ruta T (Tablero) o B (Bóveda).
4. **Todo lo demás** (`reglas`): la frase fija de rechazo.

El texto que se dice en voz **no** lleva la línea `Fuente:`: la fuente va en el
`subtitulo` del turno y, cuando hay cifras, en la `FuenteCifra` de cada
`CifraEscena` (tipo `documento` con `ruta#ancla` en los pasos 1 y 2).

La regla de datos personales se aplica al público y al voluntario. Los
integrantes del equipo y el profesor pueden preguntar sin que un teléfono,
correo o documento de la conversación convierta el turno en un rechazo; en esos
casos también se descartan los hallazgos `dato_personal` del auditor.

Si el modelo falla, se agota el tiempo o el auditor objeta, Pana responde la
frase fija de respaldo con `origen="reglas"` y sin cifras. El tiempo de la
pregunta se deja en el `LOGGER` (ruta, origen y milisegundos), nunca con la
pregunta ni con la respuesta.
"""

from __future__ import annotations

import logging
import re
import time
import tomllib
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage

from ..asistente.prompts import cargar_prompt
from ..asistente.rag import neutralizar, sanear_instrucciones
from ..asistente.validacion import (
    cifras_duras,
    contar_palabras,
    detectar_fuga_prompt,
    detectar_pii,
    es_sin_datos,
    limitar_palabras,
    limpiar_respuesta,
    normalizar_cifra_numerica,
    sanear_pregunta,
    texto_de_contenido,
)
from ..config import PROJECT_ROOT
from ..texto import normalizar
from .contratos import (
    CifraEscena,
    FuenteCifra,
    HallazgoEscena,
    TurnoEscena,
    VeredictoAuditor,
)
from .proyecto import FragmentoProyecto, RecuperadorProyecto, es_pregunta_del_proyecto

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel

LOGGER = logging.getLogger(__name__)

#: Archivo versionado con la ficha y los límites de las preguntas.
RUTA_CONFIG = PROJECT_ROOT / "config" / "escena.toml"

#: Umbral de coincidencia de tokens con las variantes de la ficha.
UMBRAL_FIJO = 0.6
#: Máximo de palabras del texto que se dice en voz.
MAX_PALABRAS = 100
#: Máximo de frases de una respuesta fija.
MAX_FRASES = 4
#: Presupuesto total de una pregunta, en segundos (punto abierto del diseño).
TIEMPO_TOTAL_SEGUNDOS = 8.0
#: Presupuesto de la llamada al modelo, en segundos.
TIEMPO_LLAMADA_SEGUNDOS = 4.0
#: Fragmentos del proyecto que se piden a BM25.
MAX_FRAGMENTOS = 3
#: Puntaje mínimo para considerar que el fragmento responde la pregunta.
PUNTAJE_MINIMO = 0.9
#: Frase fija del paso 4.
RECHAZO = (
    "No tengo información sobre eso; puedo contarles del proyecto o de los productos del banco."
)
#: Frase fija cuando el modelo falla o el auditor objeta.
RESPALDO = (
    "No puedo responder eso ahora mismo; el proyecto está documentado en docs/ "
    "y los productos y tasas del banco, en el Tablero."
)
#: Frase fija cuando el público o el voluntario dan un dato personal.
PII = (
    "Por seguridad no proceso datos personales en este espacio (Ley 1581 de "
    "2012). Puedo contarles del proyecto o de los productos del banco."
)

#: Quién pregunta; solo el público y el voluntario pasan por el filtro de PII.
Audiencia = Literal["publico", "voluntario", "equipo", "profesor"]
#: Ruta efectiva, útil para el registro.
RutaPregunta = Literal["fija", "proyecto", "banco", "rechazo", "respaldo"]

#: Línea `Fuente:` del modelo o de la Ventanilla.
_FUENTE = re.compile(r"^\s*Fuente:\s*(?P<resto>.+?)\s*$", re.IGNORECASE | re.MULTILINE)
#: `Fuente:` al final de una misma línea, sin salto.
_FUENTE_EN_LINEA = re.compile(r"\s+Fuente:\s*(?P<resto>[^\n]+?)\s*$", re.IGNORECASE)
#: Ruta Markdown con ancla opcional, para comprobar la cita del modelo.
_RUTA_DOCUMENTO = re.compile(r"(?P<ruta>[A-Za-z0-9_./-]+\.md)(?:#(?P<ancla>[A-Za-z0-9_-]+))?")
#: Cifra con $, %, COP o dígitos; misma forma que la validación del asistente.
_NUMERO = re.compile(r"(?:\$|COP\s*)?(?:\d[\d\s.,\-]*\d|\d)(?:\s?[%％])?")
#: Palabra normalizada para comparar la ficha.
_PALABRA = re.compile(r"\w+")


@dataclass(frozen=True, slots=True)
class EntradaFija:
    """Respuesta literal de la ficha para una de las preguntas probables."""

    id: str
    variantes: tuple[str, ...]
    respuesta: str
    fuente: str
    cifras: tuple[CifraEscena, ...] = ()


@dataclass(frozen=True, slots=True)
class FichaPreguntas:
    """Ficha versionada del paso 1 y las frases fijas de Pana."""

    entradas: tuple[EntradaFija, ...] = ()
    umbral_fijo: float = UMBRAL_FIJO
    rechazo: str = RECHAZO
    respaldo: str = RESPALDO
    pii: str = PII


@dataclass(frozen=True, slots=True)
class LimitesPregunta:
    """Límites de la pregunta: palabras, reloj y puntaje del proyecto.

    El tiempo total es un punto abierto del diseño: se mide con las cuatro
    rutas y se ajusta en `config/escena.toml [preguntas]` sin cambiar el
    contrato.
    """

    max_palabras: int = MAX_PALABRAS
    tiempo_total_segundos: float = TIEMPO_TOTAL_SEGUNDOS
    tiempo_llamada_segundos: float = TIEMPO_LLAMADA_SEGUNDOS
    puntaje_minimo: float = PUNTAJE_MINIMO
    max_fragmentos: int = MAX_FRAGMENTOS


@dataclass(frozen=True, slots=True)
class RespuestaVentanilla:
    """Respuesta de la Ventanilla para una pregunta del banco.

    La ruta `T` viene del Tablero y la `B` de la Bóveda. La `X` no se usa como
    texto: el enrutador devuelve la frase fija de rechazo del paso 4.
    """

    texto: str
    ruta: Literal["T", "B", "X"] = "B"
    origen: Literal["llm", "reglas"] = "reglas"
    cifras: tuple[CifraEscena, ...] = ()
    fuente: str | None = None
    subtitulo: str | None = None


#: Ventanilla inyectable: recibe la pregunta y devuelve su respuesta o `None`.
Ventanilla = Callable[[str], RespuestaVentanilla | None]
#: Auditor inyectable: devuelve un veredicto, hallazgos sueltos o nada.
AuditorPregunta = Callable[
    [TurnoEscena],
    VeredictoAuditor | Sequence[HallazgoEscena] | HallazgoEscena | None,
]


def cargar_limites_pregunta(ruta: Path | None = None) -> LimitesPregunta:
    """Lee `[preguntas]` de `config/escena.toml` y completa los límites.

    Args:
        ruta: archivo TOML alternativo; por defecto `config/escena.toml`.

    Returns:
        Los límites validados. Las palabras nunca pasan de 100, el máximo del
        contrato; los tiempos y el puntaje mínimo se toman del TOML porque el
        límite de tiempo es un punto abierto.
    """
    archivo = RUTA_CONFIG if ruta is None else Path(ruta)
    if not archivo.exists():
        return LimitesPregunta()
    with archivo.open("rb") as fh:
        datos = tomllib.load(fh)
    seccion = datos.get("preguntas", {})
    if not isinstance(seccion, dict):
        seccion = {}
    return LimitesPregunta(
        max_palabras=min(MAX_PALABRAS, max(1, int(seccion.get("max_palabras", MAX_PALABRAS)))),
        tiempo_total_segundos=max(
            0.1, float(seccion.get("tiempo_total_segundos", TIEMPO_TOTAL_SEGUNDOS))
        ),
        tiempo_llamada_segundos=max(
            0.1, float(seccion.get("tiempo_llamada_segundos", TIEMPO_LLAMADA_SEGUNDOS))
        ),
        puntaje_minimo=max(0.0, float(seccion.get("puntaje_minimo", PUNTAJE_MINIMO))),
        max_fragmentos=max(1, int(seccion.get("max_fragmentos", MAX_FRAGMENTOS))),
    )


def cargar_ficha(ruta: Path | None = None, raiz: Path | None = None) -> FichaPreguntas:
    """Carga la ficha del paso 1 y las frases fijas desde el TOML.

    Cada entrada declara `id`, `variantes`, `respuesta`, `fuente` y, si cita
    cifras, sus valores con ancla. Una entrada sin `fuente` o cuya fuente no
    exista dentro de `raiz` no se carga, como pide el diseño.

    Args:
        ruta: archivo TOML alternativo; por defecto `config/escena.toml`.
        raiz: raíz contra la que se comprueba la fuente; por defecto la del
            repositorio.

    Returns:
        La ficha con las entradas válidas y las frases del TOML.
    """
    archivo = RUTA_CONFIG if ruta is None else Path(ruta)
    if not archivo.exists():
        return FichaPreguntas()
    with archivo.open("rb") as fh:
        datos = tomllib.load(fh)
    seccion = datos.get("preguntas", {})
    if not isinstance(seccion, dict):
        seccion = {}
    base = Path(raiz).resolve() if raiz is not None else PROJECT_ROOT.resolve()
    entradas: list[EntradaFija] = []
    for datos_entrada in seccion.get("fijas", []):
        if not isinstance(datos_entrada, dict):
            continue
        fuente = str(datos_entrada.get("fuente", "")).strip()
        if not fuente or not _fuente_existe(base, fuente):
            continue
        entrada = _entrada_desde_toml(datos_entrada, fuente)
        if entrada is not None:
            entradas.append(entrada)
    return FichaPreguntas(
        entradas=tuple(entradas),
        umbral_fijo=max(0.0, min(1.0, float(seccion.get("umbral_fijo", UMBRAL_FIJO)))),
        rechazo=str(seccion.get("rechazo", RECHAZO)).strip() or RECHAZO,
        respaldo=str(seccion.get("respaldo", RESPALDO)).strip() or RESPALDO,
        pii=str(seccion.get("pii", PII)).strip() or PII,
    )


def responder_pregunta(
    pregunta: str,
    *,
    ficha: FichaPreguntas,
    recuperador: RecuperadorProyecto,
    ventanilla: Ventanilla,
    auditor: AuditorPregunta | None = None,
    modelo: BaseChatModel | None = None,
    limites: LimitesPregunta | None = None,
    audiencia: Audiencia = "publico",
) -> TurnoEscena:
    """Responde una pregunta del público con el turno aislado de Pana.

    El orden manda: ficha fija, proyecto, Ventanilla y rechazo. No hay memoria
    conversacional ni se guarda la pregunta. Si el modelo falla, se agota el
    tiempo o el auditor objeta, el turno vuelve con la frase fija de respaldo y
    `origen="reglas"`.

    Args:
        pregunta: texto del público; se sanea antes de usarlo.
        ficha: respuestas fijas, umbral y frases de rechazo, respaldo y PII.
        recuperador: recuperador BM25 del proyecto, ya construido.
        ventanilla: dependencia del banco; recibe la pregunta y devuelve ruta,
            texto y fuentes, o `None` si no puede responder.
        auditor: auditor inyectable; con `None` no se agregan hallazgos.
        modelo: modelo de chat para el paso 2; con `None` se usa el respaldo.
        limites: límites de palabras, reloj y puntaje; por defecto los del
            diseño.
        audiencia: público, voluntario, equipo o profesor. La regla de datos
            personales solo se aplica a los dos primeros. **Nunca debe venir de
            la petición HTTP**: el endpoint la fija en el servidor (`"publico"`
            para la pantalla) para que nadie pueda saltarse la revisión de datos
            personales desde el cliente. Por defecto es `"publico"`.

    Returns:
        Un `TurnoEscena` de Pana. El texto hablado nunca contiene la línea
        `Fuente:`; la fuente va en `subtitulo` y en las cifras.

    Raises:
        ValueError: si la pregunta queda vacía después de sanearla.
    """
    inicio = time.monotonic()
    registro: list[str] = []
    ajustes = limites or LimitesPregunta()
    limpia = sanear_pregunta(pregunta)

    if _aplica_pii(audiencia) and detectar_pii(limpia) is not None:
        registro.append("pii en la pregunta")
        return _finalizar(_turno_pii(ficha), "rechazo", registro, inicio)

    entrada = _buscar_fija(limpia, ficha, ajustes)
    if entrada is not None:
        turno = _turno_fijo(entrada)
        return _auditar(turno, "fija", ficha, auditor, audiencia, ajustes, registro, inicio)

    if es_pregunta_del_proyecto(limpia):
        fragmentos = _buscar_proyecto(recuperador, limpia, ajustes, registro)
        turno = _responder_proyecto(
            limpia, fragmentos, modelo, ajustes, registro, inicio, audiencia
        )
        if turno is not None:
            return _auditar(turno, "proyecto", ficha, auditor, audiencia, ajustes, registro, inicio)
        if fragmentos and fragmentos[0].puntaje >= ajustes.puntaje_minimo:
            return _finalizar(_turno_respaldo(ficha, (), ajustes), "respaldo", registro, inicio)

    try:
        respuesta = ventanilla(limpia)
    except Exception as exc:  # noqa: BLE001 - la escena no se detiene por la Ventanilla
        registro.append(f"fallo de la Ventanilla ({type(exc).__name__})")
        return _finalizar(_turno_respaldo(ficha, (), ajustes), "respaldo", registro, inicio)
    if respuesta is not None and respuesta.ruta in {"T", "B"}:
        turno = _turno_banco(respuesta, ajustes, audiencia)
        if turno is not None:
            return _auditar(turno, "banco", ficha, auditor, audiencia, ajustes, registro, inicio)
        return _finalizar(_turno_respaldo(ficha, (), ajustes), "respaldo", registro, inicio)

    return _finalizar(_turno_rechazo(ficha), "rechazo", registro, inicio)


def _entrada_desde_toml(datos: dict[str, Any], fuente: str) -> EntradaFija | None:
    """Convierte una tabla TOML en `EntradaFija`, o `None` si le faltan campos."""
    identificador = str(datos.get("id", "")).strip()
    respuesta = str(datos.get("respuesta", "")).strip()
    if not identificador or not respuesta:
        return None
    variantes = datos.get("variantes", [])
    if isinstance(variantes, str):
        variantes = [variantes]
    limpias = tuple(str(valor).strip() for valor in variantes if str(valor).strip())
    if not limpias:
        return None
    cifras = tuple(
        _cifra_desde_toml(dato, fuente)
        for dato in datos.get("cifras", [])
        if isinstance(dato, dict)
    )
    return EntradaFija(
        id=identificador,
        variantes=limpias,
        respuesta=respuesta,
        fuente=fuente,
        cifras=cifras,
    )


def _cifra_desde_toml(datos: dict[str, Any], fuente: str) -> CifraEscena:
    """Construye una `CifraEscena` desde la forma completa o la abreviada."""
    if "fuente" in datos and "etiqueta" in datos:
        return CifraEscena.model_validate(datos)
    ruta = fuente.split("#", 1)[0]
    ancla = str(datos.get("ancla", "")).strip()
    referencia = f"{ruta}#{ancla}" if ancla else fuente
    valor = Decimal(str(datos["valor"]))
    unidad = str(datos.get("unidad", "veces"))
    if unidad not in {"pesos", "porcentaje_ea", "porcentaje", "meses", "dias", "veces"}:
        unidad = "veces"
    return CifraEscena(
        etiqueta=str(datos.get("etiqueta", f"dato citado en {referencia}")),
        valor=valor,
        valor_legible=str(datos.get("valor_legible", datos["valor"])),
        unidad=unidad,
        fuente=FuenteCifra(tipo="documento", referencia=referencia),
    )


def _fuente_existe(raiz: Path, fuente: str) -> bool:
    """Comprueba que la fuente de la ficha sea un archivo dentro de la raíz."""
    ruta = fuente.split("#", 1)[0].strip()
    if not ruta:
        return False
    archivo = (raiz / ruta).resolve()
    try:
        archivo.relative_to(raiz)
    except ValueError:
        return False
    return archivo.is_file()


def _aplica_pii(audiencia: Audiencia) -> bool:
    """Indica si a esa audiencia se le aplica la regla de datos personales."""
    return audiencia in {"publico", "voluntario"}


def _finalizar(
    turno: TurnoEscena,
    ruta: RutaPregunta,
    registro: Sequence[str],
    inicio: float,
) -> TurnoEscena:
    """Registra ruta, origen y tiempo sin guardar la pregunta ni la respuesta."""
    milisegundos = (time.monotonic() - inicio) * 1000
    detalle = f" registro={' | '.join(registro)}" if registro else ""
    LOGGER.info(
        "evento=escena_pregunta ruta=%s origen=%s ms=%.1f%s",
        ruta,
        turno.origen,
        milisegundos,
        detalle,
    )
    return turno


def _auditar(
    turno: TurnoEscena,
    ruta: RutaPregunta,
    ficha: FichaPreguntas,
    auditor: AuditorPregunta | None,
    audiencia: Audiencia,
    limites: LimitesPregunta,
    registro: list[str],
    inicio: float,
) -> TurnoEscena:
    """Pasa el turno por el auditor y lo reemplaza si objeta."""
    hallazgos, veredicto_objeta = _invocar_auditor(auditor, turno)
    hallazgos = _filtrar_hallazgos(hallazgos, audiencia)
    objeta = any(hallazgo.gravedad == "alta" for hallazgo in hallazgos) or (
        veredicto_objeta and bool(hallazgos)
    )
    if objeta:
        registro.append("auditor objeta; se usa el respaldo")
        return _finalizar(_turno_respaldo(ficha, hallazgos, limites), "respaldo", registro, inicio)
    if hallazgos:
        turno = turno.model_copy(update={"hallazgos": hallazgos})
    return _finalizar(turno, ruta, registro, inicio)


def _invocar_auditor(
    auditor: AuditorPregunta | None,
    turno: TurnoEscena,
) -> tuple[tuple[HallazgoEscena, ...], bool]:
    """Normaliza la salida del auditor a hallazgos y una decisión de objeción."""
    if auditor is None:
        return (), False
    try:
        resultado = auditor(turno)
    except Exception as exc:  # noqa: BLE001 - sin auditoría no se confía en el texto
        LOGGER.warning("evento=escena_pregunta auditor_error=%s", type(exc).__name__)
        return (), True
    if resultado is None:
        return (), False
    if isinstance(resultado, VeredictoAuditor):
        hallazgos = tuple(resultado.hallazgos)
        objeta = resultado.veredicto == "objeta" or any(
            hallazgo.gravedad == "alta" for hallazgo in hallazgos
        )
        return hallazgos, objeta
    if isinstance(resultado, HallazgoEscena):
        return (resultado,), resultado.gravedad == "alta"
    hallazgos = tuple(resultado)
    return hallazgos, any(hallazgo.gravedad == "alta" for hallazgo in hallazgos)


def _filtrar_hallazgos(
    hallazgos: Sequence[HallazgoEscena],
    audiencia: Audiencia,
) -> tuple[HallazgoEscena, ...]:
    """Quita `dato_personal` cuando pregunta el equipo o el profesor."""
    if audiencia not in {"equipo", "profesor"}:
        return tuple(hallazgos)
    return tuple(hallazgo for hallazgo in hallazgos if hallazgo.codigo != "dato_personal")


def _buscar_proyecto(
    recuperador: RecuperadorProyecto,
    pregunta: str,
    limites: LimitesPregunta,
    registro: list[str],
) -> list[FragmentoProyecto]:
    """Pide fragmentos al BM25 y deja en el registro si no hubo coincidencia."""
    try:
        fragmentos = recuperador.buscar(pregunta, k=limites.max_fragmentos)
    except Exception as exc:  # noqa: BLE001 - el paso 2 no detiene la escena
        registro.append(f"fallo del BM25 ({type(exc).__name__})")
        return []
    if not fragmentos:
        registro.append("BM25 sin fragmentos; sigue al paso 3")
    return fragmentos


def _responder_proyecto(
    pregunta: str,
    fragmentos: Sequence[FragmentoProyecto],
    modelo: BaseChatModel | None,
    limites: LimitesPregunta,
    registro: list[str],
    inicio: float,
    audiencia: Audiencia,
) -> TurnoEscena | None:
    """Resume el mejor fragmento del proyecto o devuelve `None` para el respaldo."""
    if not fragmentos:
        return None
    mejor = fragmentos[0]
    if mejor.puntaje < limites.puntaje_minimo:
        registro.append(f"BM25 bajo ({mejor.puntaje:.2f}); sigue al paso 3")
        return None
    if modelo is None:
        registro.append("sin modelo; se usa el respaldo")
        return None
    try:
        mensajes = _mensajes_proyecto(pregunta, mejor)
    except Exception as exc:  # noqa: BLE001 - un prompt ausente no rompe la escena
        registro.append(f"prompt no disponible ({type(exc).__name__})")
        return None
    crudo = _llamar_modelo(modelo, mensajes, limites, registro, inicio)
    if crudo is None:
        return None
    turno = _turno_proyecto(mejor, crudo, limites, audiencia)
    if turno is None:
        registro.append("respuesta del modelo descartada; se usa el respaldo")
    return turno


def _mensajes_proyecto(pregunta: str, fragmento: FragmentoProyecto) -> list[BaseMessage]:
    """Arma el bloque `<fragmentos>` neutralizado y la pregunta del público."""
    prompt = cargar_prompt("pregunta_proyecto")
    bloque = "\n".join(
        (
            "<fragmentos>",
            f"[1] {neutralizar(sanear_instrucciones(fragmento.titulo))}",
            f"Seccion: {neutralizar(sanear_instrucciones(fragmento.ancla))}",
            f"Fuente: {fragmento.referencia}",
            "",
            neutralizar(sanear_instrucciones(fragmento.texto)),
            "</fragmentos>",
        )
    )
    sistema = f"{bloque}\n\n{prompt.sistema}"
    partes = [f"<pregunta>\n{pregunta}\n</pregunta>"]
    if prompt.recordatorio:
        partes.insert(0, f"<reglas_clave>\n{prompt.recordatorio}\n</reglas_clave>")
    return [SystemMessage(content=sistema), HumanMessage(content="\n\n".join(partes))]


def _llamar_modelo(
    modelo: BaseChatModel,
    mensajes: Sequence[BaseMessage],
    limites: LimitesPregunta,
    registro: list[str],
    inicio: float,
) -> str | None:
    """Llama al modelo con el reloj de la pregunta y devuelve el texto crudo."""
    restante = limites.tiempo_total_segundos - (time.monotonic() - inicio)
    if restante <= 0:
        registro.append("tiempo total agotado; se usa el respaldo")
        return None
    ejecutor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="escena_pregunta")
    try:
        futuro = ejecutor.submit(modelo.invoke, list(mensajes))
        try:
            respuesta = futuro.result(
                timeout=min(limites.tiempo_llamada_segundos, max(0.001, restante))
            )
        except TimeoutError:
            registro.append("tiempo de la llamada agotado; se usa el respaldo")
            return None
        except Exception as exc:  # noqa: BLE001 - el modelo no detiene la escena
            registro.append(f"fallo del modelo ({type(exc).__name__}); se usa el respaldo")
            return None
        return texto_de_contenido(getattr(respuesta, "content", respuesta))
    finally:
        ejecutor.shutdown(wait=False, cancel_futures=True)


def _sin_enlaces_ni_listas(texto: str) -> str:
    """Deja la respuesta del modelo como texto hablado, sin URL ni viñetas.

    Args:
        texto: respuesta cruda del modelo.

    Returns:
        El texto en un párrafo, sin enlaces ni marcas de lista y con máximo
        cuatro frases.
    """
    sin_url = re.sub(r"https?://\S+", " ", texto)
    lineas = [re.sub(r"^\s*(?:[-*•]|\d+[.)])\s+", "", linea) for linea in sin_url.splitlines()]
    plano = " ".join(" ".join(lineas).split())
    frases = [frase for frase in re.split(r"(?<=[.!?…])\s+", plano) if frase.strip()]
    return " ".join(frases[:MAX_FRASES]).strip()


def _turno_proyecto(
    fragmento: FragmentoProyecto,
    crudo: str,
    limites: LimitesPregunta,
    audiencia: Audiencia,
) -> TurnoEscena | None:
    """Convierte la salida del modelo en el turno del proyecto o la descarta."""
    texto = limpiar_respuesta(crudo)
    if not texto or es_sin_datos(texto):
        return None
    cuerpo, fuente = _separar_fuente(texto)
    if fuente is not None and not _misma_fuente(fuente, fragmento):
        return None
    if detectar_fuga_prompt(cuerpo):
        return None
    if _aplica_pii(audiencia) and detectar_pii(cuerpo) is not None:
        return None
    cuerpo = _sin_enlaces_ni_listas(cuerpo)
    cuerpo, _ = limitar_palabras(cuerpo, limites.max_palabras)
    if not cuerpo:
        return None
    cifras, inventada = _cifras_documento(cuerpo, fragmento)
    if inventada:
        return None
    return TurnoEscena(
        id="pana.pregunta.proyecto.v1",
        orden=0,
        personaje="pana",
        texto=cuerpo,
        subtitulo=f"{cuerpo} Fuente: {fragmento.referencia}",
        cifras=cifras,
        origen="llm",
    )


def _turno_fijo(entrada: EntradaFija) -> TurnoEscena:
    """Devuelve la respuesta literal de la ficha sin la línea `Fuente:` hablada."""
    texto, _ = _separar_fuente(entrada.respuesta.strip())
    return TurnoEscena(
        id=f"pana.pregunta.fija.{entrada.id}",
        orden=0,
        personaje="pana",
        texto=texto,
        subtitulo=f"{texto} Fuente: {entrada.fuente.strip()}",
        cifras=entrada.cifras,
        origen="guion_fijo",
    )


def _turno_banco(
    respuesta: RespuestaVentanilla,
    limites: LimitesPregunta,
    audiencia: Audiencia,
) -> TurnoEscena | None:
    """Convierte la respuesta de la Ventanilla en un turno de Pana."""
    texto, fuente = _separar_fuente(limpiar_respuesta(respuesta.texto))
    if not texto:
        return None
    if _aplica_pii(audiencia) and detectar_pii(texto) is not None:
        return None
    texto, _ = limitar_palabras(texto, limites.max_palabras)
    subtitulo = respuesta.subtitulo
    referencia = respuesta.fuente or fuente
    if referencia and (not subtitulo or "Fuente:" not in subtitulo):
        subtitulo = f"{subtitulo or texto} Fuente: {referencia}"
    return TurnoEscena(
        id="pana.pregunta.banco.v1",
        orden=0,
        personaje="pana",
        texto=texto,
        subtitulo=subtitulo,
        cifras=respuesta.cifras,
        origen=respuesta.origen,
    )


def _turno_rechazo(ficha: FichaPreguntas) -> TurnoEscena:
    """Frase fija del paso 4, sin consultar el texto de la pregunta."""
    return TurnoEscena(
        id="pana.pregunta.rechazo.v1",
        orden=0,
        personaje="pana",
        texto=ficha.rechazo.strip() or RECHAZO,
        origen="reglas",
    )


def _turno_pii(ficha: FichaPreguntas) -> TurnoEscena:
    """Rechazo fijo de un dato personal, sin repetir lo que dijo la persona."""
    return TurnoEscena(
        id="pana.pregunta.pii.v1",
        orden=0,
        personaje="pana",
        texto=ficha.pii.strip() or PII,
        origen="reglas",
    )


def _turno_respaldo(
    ficha: FichaPreguntas,
    hallazgos: Sequence[HallazgoEscena],
    limites: LimitesPregunta,
) -> TurnoEscena:
    """Frase fija de respaldo cuando el modelo falla o el auditor objeta."""
    texto, _ = limitar_palabras(ficha.respaldo.strip() or RESPALDO, limites.max_palabras)
    return TurnoEscena(
        id="pana.pregunta.respaldo.v1",
        orden=0,
        personaje="pana",
        texto=texto,
        origen="reglas",
        hallazgos=tuple(hallazgos),
    )


def _buscar_fija(
    pregunta: str,
    ficha: FichaPreguntas,
    limites: LimitesPregunta,
) -> EntradaFija | None:
    """Busca la entrada de la ficha con mayor Jaccard de tokens sobre el umbral."""
    tokens = set(_tokenizar(pregunta))
    mejor: tuple[float, EntradaFija] | None = None
    for entrada in ficha.entradas:
        if not _entrada_valida(entrada, limites):
            continue
        for variante in entrada.variantes:
            puntaje = _jaccard(tokens, set(_tokenizar(variante)))
            if puntaje >= ficha.umbral_fijo and (mejor is None or puntaje > mejor[0]):
                mejor = (puntaje, entrada)
    return mejor[1] if mejor is not None else None


def _entrada_valida(entrada: EntradaFija, limites: LimitesPregunta) -> bool:
    """Comprueba el contrato de una entrada fija antes de usarla."""
    if not entrada.respuesta.strip() or not entrada.fuente.strip() or not entrada.variantes:
        return False
    if _contar_frases(entrada.respuesta) > MAX_FRASES:
        return False
    if contar_palabras(entrada.respuesta) > limites.max_palabras:
        return False
    declaradas = {_canonica(cifra.valor) for cifra in entrada.cifras}
    return cifras_duras(entrada.respuesta) <= declaradas


def _contar_frases(texto: str) -> int:
    """Cuenta oraciones separadas por punto, cierre o salto de oración."""
    return len([frase for frase in re.split(r"(?<=[.!?…])\s+", texto.strip()) if frase.strip()])


def _jaccard(izquierda: set[str], derecha: set[str]) -> float:
    """Similitud de conjuntos de tokens, entre 0 y 1."""
    if not izquierda or not derecha:
        return 0.0
    return len(izquierda & derecha) / len(izquierda | derecha)


def _tokenizar(texto: str) -> list[str]:
    """Normaliza y divide un texto en palabras para la comparación de la ficha."""
    return _PALABRA.findall(normalizar(texto))


def _canonica(valor: Decimal) -> str:
    """Forma canónica de una cifra, igual a la de `cifras_duras`."""
    return f"{valor.normalize():f}"


def _separar_fuente(texto: str) -> tuple[str, str | None]:
    """Saca la línea `Fuente:` del texto hablado y devuelve su referencia."""
    coincidencias = list(_FUENTE.finditer(texto))
    if coincidencias:
        fuente = coincidencias[-1].group("resto").strip()
        return _FUENTE.sub("", texto).strip(), fuente
    en_linea = _FUENTE_EN_LINEA.search(texto)
    if en_linea is not None:
        return texto[: en_linea.start()].strip(), en_linea.group("resto").strip()
    return texto.strip(), None


def _misma_fuente(fuente: str, fragmento: FragmentoProyecto) -> bool:
    """Comprueba que la cita del modelo apunte al fragmento recuperado."""
    coincidencia = _RUTA_DOCUMENTO.search(fuente)
    if coincidencia is None:
        return False
    return coincidencia.group("ruta").lstrip("./") == fragmento.ruta


def _cifras_documento(
    texto: str,
    fragmento: FragmentoProyecto,
) -> tuple[tuple[CifraEscena, ...], bool]:
    """Crea las cifras del proyecto con fuente `documento` y detecta inventadas."""
    permitidas = cifras_duras(fragmento.texto)
    cifras: list[CifraEscena] = []
    vistas: set[tuple[str, str]] = set()
    inventada = False
    for coincidencia in _NUMERO.finditer(texto):
        token = coincidencia.group(0)
        normalizada = normalizar_cifra_numerica(token)
        if not normalizada:
            continue
        significativas = cifras_duras(token)
        if not significativas:
            continue
        if normalizada not in permitidas:
            inventada = True
            continue
        unidad = _unidad_cifra(token)
        clave = (normalizada, unidad)
        if clave in vistas:
            continue
        vistas.add(clave)
        cifras.append(
            CifraEscena(
                etiqueta=f"dato citado en {fragmento.referencia}",
                valor=Decimal(normalizada),
                valor_legible=token.strip(),
                unidad=unidad,
                fuente=FuenteCifra(tipo="documento", referencia=fragmento.referencia),
            )
        )
    return tuple(cifras), inventada


def _unidad_cifra(token: str) -> Literal["pesos", "porcentaje_ea", "porcentaje", "veces"]:
    """Deduce la unidad de una cifra del texto del proyecto."""
    if "%" in token or "％" in token:
        return "porcentaje"
    if "$" in token or "cop" in token.casefold():
        return "pesos"
    return "veces"
