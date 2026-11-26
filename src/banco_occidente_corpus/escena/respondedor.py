"""Respondedor real de las preguntas del público en la pantalla de la escena.

Arma, una sola vez por proceso, lo que necesita `responder_pregunta`: la ficha
de `config/escena.toml [preguntas]` (las 17 respuestas fijas de
`docs/PRESENTADOR.md`), el recuperador BM25 de la documentación del proyecto,
el auditor determinista y, si hay clave y no es modo demo, el modelo que
resume el fragmento del proyecto.

Las preguntas sobre productos y tasas del banco no pasan por aquí: la
Ventanilla de la escena devuelve `None` y Pana responde con su frase de
rechazo, que invita a preguntar por el proyecto. Esas preguntas se responden
por WhatsApp, donde están las herramientas de tasas y tarifas.

Las pruebas viven en ``test/test_escena_api_pregunta.py``.
"""

from __future__ import annotations

import threading
from collections.abc import Callable

from ..asistente.modelo import crear_modelo
from .auditor import auditar_turno
from .contratos import HallazgoEscena, TurnoEscena
from .negociacion import modo_demo
from .pregunta import (
    RespuestaVentanilla,
    cargar_ficha,
    cargar_limites_pregunta,
    responder_pregunta,
)
from .proyecto import crear_recuperador_proyecto

#: Firma del respondedor que usa la API: pregunta del público → turno de Pana.
Respondedor = Callable[[str], TurnoEscena]

#: Tope de tokens de la respuesta del modelo (40 palabras caben de sobra).
MAX_TOKENS_RESPUESTA = 160

_CANDADO = threading.Lock()
_RESPONDEDOR: Respondedor | None = None


def _sin_ventanilla(_pregunta: str) -> RespuestaVentanilla | None:
    """Ventanilla de la pantalla: las preguntas del banco van por WhatsApp.

    Args:
        _pregunta: pregunta ya saneada; no se usa ni se guarda.

    Returns:
        Siempre `None`, para que Pana use su frase de rechazo.
    """
    return None


def _auditor(turno: TurnoEscena) -> tuple[HallazgoEscena, ...]:
    """Pasa la respuesta de Pana por las reglas del auditor de la escena.

    Args:
        turno: turno que Pana va a decir.

    Returns:
        Los hallazgos; uno de gravedad alta hace que se use el respaldo.
    """
    return auditar_turno(turno)


def crear_respondedor() -> Respondedor:
    """Construye el respondedor con la ficha, el recuperador y el modelo.

    Sin `DEEPSEEK_API_KEY` o con `SUCURSAL_DEMO` no se crea el modelo: las
    respuestas fijas siguen funcionando y las del proyecto usan la frase de
    respaldo.

    Returns:
        Una función que recibe la pregunta del público y devuelve el turno.
    """
    ficha = cargar_ficha()
    limites = cargar_limites_pregunta()
    recuperador = crear_recuperador_proyecto()
    modelo = (
        None
        if modo_demo()
        else crear_modelo(
            temperatura=0.0,
            max_tokens=MAX_TOKENS_RESPUESTA,
            timeout=limites.tiempo_llamada_segundos,
            max_retries=0,
            razonamiento=False,
        )
    )

    def responder(pregunta: str) -> TurnoEscena:
        """Responde una pregunta; la audiencia la fija el servidor, no el cliente.

        Args:
            pregunta: texto del público, sin sanear.

        Returns:
            El turno de Pana.
        """
        return responder_pregunta(
            pregunta,
            ficha=ficha,
            recuperador=recuperador,
            ventanilla=_sin_ventanilla,
            auditor=_auditor,
            modelo=modelo,
            limites=limites,
            audiencia="publico",
        )

    return responder


def respondedor_compartido() -> Respondedor:
    """Devuelve el respondedor del proceso, creándolo la primera vez.

    Returns:
        El mismo respondedor en cada llamada.
    """
    global _RESPONDEDOR
    with _CANDADO:
        if _RESPONDEDOR is None:
            _RESPONDEDOR = crear_respondedor()
        return _RESPONDEDOR


def tema_del_turno(turno: TurnoEscena) -> str:
    """Nombre corto de la ruta que respondió, para la pantalla.

    Args:
        turno: turno devuelto por `responder_pregunta`.

    Returns:
        `ficha`, `proyecto`, `fuera_de_tema`, `datos_personales` o `respaldo`.
    """
    identificador = turno.id or ""
    if identificador.startswith("pana.pregunta.fija."):
        return "ficha"
    return {
        "pana.pregunta.proyecto.v1": "proyecto",
        "pana.pregunta.banco.v1": "banco",
        "pana.pregunta.rechazo.v1": "fuera_de_tema",
        "pana.pregunta.pii.v1": "datos_personales",
    }.get(identificador, "respaldo")
