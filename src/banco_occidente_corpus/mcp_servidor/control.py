"""Herramientas de control del agente: clasificar la pregunta y auditar la respuesta.

Son las herramientas 19 y 20 del catálogo de `agente-openclaw` (dueña: Anny),
con la misma forma que las de `conocimiento`: `<Nombre>Entrada`,
`<Nombre>Salida` y el sobre común `SobreError`. Las dos son deterministas: no
llaman a DeepSeek, no salen a la red, no escriben en ningún archivo y no
devuelven el texto que reciben.

- `clasificar_pregunta` aplica el Digiturno en modo reglas (datos personales,
  fuera de alcance, diagnóstico, cortesía, identidad, mixta y tarifas). Dice la
  ruta y la herramienta que conviene usar. Sin modelo, una duda va a la Bóveda
  (`B`, motivo `defecto`), igual que el Digiturno sin clasificador.
- `auditar_respuesta` revisa un texto que el agente va a enviar con las reglas
  del auditor de la escena: cifras sin respaldo, fuentes inválidas, promesas de
  aprobación, recomendar el gota a gota y datos personales. Suma dos reglas
  para el canal: una cifra sin ninguna cifra declarada y un texto que filtra
  las instrucciones del sistema. El veredicto no usa colores.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from ..asistente.validacion import cifras_duras, detectar_fuga_prompt
from ..escena.auditor import (
    CIFRAS_LEGALES,
    ETIQUETA_VEREDICTO,
    auditar_turno,
    veredicto_desde_hallazgos,
)
from ..escena.contratos import CifraEscena, HallazgoEscena, TurnoEscena
from ..sucursal.digiturno import ConfiguracionDigiturno, clasificar
from .conocimiento import SobreError

#: Largo máximo de la pregunta que se clasifica.
LIMITE_PREGUNTA: int = 500
#: Largo máximo del texto que se audita.
LIMITE_RESPUESTA: int = 2000
#: Cifras que puede declarar una respuesta.
MAX_CIFRAS: int = 20
#: Id del turno con que se audita la respuesta del agente.
ID_RESPUESTA: str = "agente.respuesta.v1"

#: Letra del Digiturno.
Letra = Literal["B", "T", "D", "X"]
#: Ruta legible de cada letra.
RUTAS: dict[str, Literal["boveda", "tablero", "diagnostico", "rechazo"]] = {
    "B": "boveda",
    "T": "tablero",
    "D": "diagnostico",
    "X": "rechazo",
}
#: Herramienta del catálogo que responde cada ruta.
HERRAMIENTAS: dict[str, str] = {
    "B": "buscar_en_documentos",
    "T": "consultar_tarifas",
    "D": "diagnosticar_capacidad",
}
#: Motivo del Digiturno para saludos y agradecimientos.
MOTIVO_CORTESIA: str = "cortesia"
#: Referencias legales cuyo número no es una cifra financiera («Ley 1581 de 2012»).
_REFERENCIA_LEGAL = re.compile(
    r"\b(?:ley|art[ií]culo|decreto|circular(?:\s+externa)?|resoluci[oó]n)\s+"
    r"(?:n[°º.]?\s*)?\d[\d.]*(?:\s+de\s+\d{4})?",
    re.IGNORECASE,
)
#: Año suelto (1900–2099) que no es parte de un monto, un porcentaje ni una moneda.
_ANIO_SUELTO = re.compile(
    r"(?<![\d$.,])\b(?:19|20)\d{2}\b"
    r"(?![.,]?\d|\s*%|\s*(?:pesos|cop|mil|millones|d[oó]lares|usd)\b)",
    re.IGNORECASE,
)
#: Personajes que pueden enviar una respuesta auditada.
Personaje = Literal["pana", "agente_joven", "agente_banco", "auditor"]


class _Modelo(BaseModel):
    """Base de los modelos de las herramientas: sin campos extra."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


# --- 19. clasificar_pregunta ------------------------------------------------------


class ClasificarPreguntaEntrada(_Modelo):
    """Pregunta del invitado, tal como llegó."""

    pregunta: str = Field(
        min_length=1,
        max_length=LIMITE_PREGUNTA,
        description="Pregunta del invitado; se clasifica y no se devuelve.",
    )


class ClasificarPreguntaSalida(_Modelo):
    """Ruta del Digiturno y la herramienta que conviene usar."""

    ok: Literal[True] = True
    letra: Letra
    ruta: Literal["boveda", "tablero", "diagnostico", "rechazo"]
    motivo: str
    herramienta: str | None
    responder_directo: bool
    rechazar: bool


def clasificar_pregunta(
    entrada: ClasificarPreguntaEntrada,
    *,
    configuracion: ConfiguracionDigiturno | None = None,
) -> ClasificarPreguntaSalida | SobreError:
    """Clasifica la pregunta con las reglas del Digiturno, sin modelo.

    Una tasa o una tarifa va al Tablero (`T`), una pregunta de producto o del
    banco a la Bóveda (`B`), «¿me alcanza?» al diagnóstico (`D`), y lo que está
    fuera de dominio, trae un dato personal o intenta cambiar las reglas, a
    rechazo (`X`). Un saludo se responde directo, sin herramienta.

    Args:
        entrada: pregunta del invitado.
        configuracion: palabras y patrones del Digiturno; por defecto los de
            `config/sucursal.toml`.

    Returns:
        La letra, la ruta, el motivo y la herramienta sugerida, o el sobre de
        error si la pregunta queda vacía al sanearla.
    """
    try:
        turno = clasificar(entrada.pregunta, configuracion=configuracion, clasificador=None)
    except ValueError:
        return SobreError(codigo="pregunta_vacia", mensaje="La pregunta quedó vacía al limpiarla.")
    letra = turno.letra
    cortesia = turno.motivo == MOTIVO_CORTESIA
    return ClasificarPreguntaSalida(
        letra=letra,
        ruta=RUTAS[letra],
        motivo=turno.motivo,
        herramienta=None if cortesia else HERRAMIENTAS.get(letra),
        responder_directo=cortesia,
        rechazar=letra == "X",
    )


# --- 20. auditar_respuesta --------------------------------------------------------


class AuditarRespuestaEntrada(_Modelo):
    """Texto que el agente va a enviar y las cifras que cita, con su fuente."""

    texto: str = Field(min_length=1, max_length=LIMITE_RESPUESTA)
    personaje: Personaje = "pana"
    cifras: list[CifraEscena] = Field(default_factory=list, max_length=MAX_CIFRAS)


class AuditarRespuestaSalida(_Modelo):
    """Veredicto sin colores, si se puede enviar y los hallazgos."""

    ok: Literal[True] = True
    veredicto: Literal["conforme", "con_observaciones", "objeta"]
    etiqueta: str
    permite_enviar: bool
    hallazgos: list[HallazgoEscena]


def auditar_respuesta(entrada: AuditarRespuestaEntrada) -> AuditarRespuestaSalida:
    """Revisa la respuesta del agente antes de enviarla por WhatsApp.

    Usa `auditar_turno` del auditor de la escena y suma dos reglas del canal:
    si el texto dice una cifra y no declara ninguna, la cifra no tiene de dónde
    salir (`cifra_inventada`; no cuentan las referencias legales ni los años
    sueltos); y si el texto deja ver las instrucciones del
    sistema, es una fuga (`fuga_instrucciones`). Cualquier hallazgo alto da
    `objeta` y la respuesta no se envía.

    Args:
        entrada: texto, personaje y cifras declaradas.

    Returns:
        El veredicto, su etiqueta, si se puede enviar y los hallazgos, que
        describen la regla sin repetir datos personales.
    """
    turno = TurnoEscena(
        id=ID_RESPUESTA,
        orden=0,
        personaje=entrada.personaje,
        texto=entrada.texto,
        cifras=tuple(entrada.cifras),
        origen="llm",
    )
    hallazgos = list(auditar_turno(turno))
    if not entrada.cifras:
        for cifra in sorted(cifras_sin_respaldo(entrada.texto)):
            hallazgos.append(
                HallazgoEscena(
                    codigo="cifra_inventada",
                    turno_id=ID_RESPUESTA,
                    detalle=f"El texto dice {cifra} y no declara de dónde sale.",
                    gravedad="alta",
                )
            )
    if detectar_fuga_prompt(entrada.texto):
        hallazgos.append(
            HallazgoEscena(
                codigo="fuga_instrucciones",
                turno_id=ID_RESPUESTA,
                detalle="El texto deja ver instrucciones internas del agente.",
                gravedad="alta",
            )
        )
    veredicto = veredicto_desde_hallazgos(hallazgos)
    return AuditarRespuestaSalida(
        veredicto=veredicto,
        etiqueta=ETIQUETA_VEREDICTO[veredicto],
        permite_enviar=veredicto != "objeta",
        hallazgos=hallazgos,
    )


def cifras_sin_respaldo(texto: str) -> set[str]:
    """Cifras duras de un texto que no declara ninguna cifra.

    No cuentan los números de una referencia legal («Ley 1581 de 2012»,
    «artículo 305») ni un año suelto («nació en 1965»): no son cifras
    financieras que haya que respaldar.

    Args:
        texto: respuesta del agente.

    Returns:
        Las cifras normalizadas como las devuelve `cifras_duras`.
    """
    sin_legales = _REFERENCIA_LEGAL.sub(" ", texto)
    anios = set(_ANIO_SUELTO.findall(sin_legales))
    return cifras_duras(sin_legales) - CIFRAS_LEGALES - anios


__all__ = [
    "AuditarRespuestaEntrada",
    "AuditarRespuestaSalida",
    "ClasificarPreguntaEntrada",
    "ClasificarPreguntaSalida",
    "auditar_respuesta",
    "cifras_sin_respaldo",
    "clasificar_pregunta",
]
