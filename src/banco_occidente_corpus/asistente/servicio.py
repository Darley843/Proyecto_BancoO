"""Servicio del asistente para la app: ejecuta las tareas y mide el tiempo.

La app no decide nada: llama a estas funciones y muestra lo que devuelven. Las
reglas viven aqui o en los modulos que se reutilizan:

- la pregunta se limpia y se filtra por datos personales **antes** de llamar al
  modelo (``detectar_pii_pregunta`` y ``respuesta_pii``);
- Q&A acepta la version de prompt que elija la app; FAQ y resumen usan siempre
  la version por defecto (``v1``);
- la validacion posterior de ``qa``, ``faq`` y ``resumen`` queda intacta;
- los errores de contrato se devuelven como datos, no como excepciones, para
  que la app pueda mostrarlos y decidir si los cachea.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from .contexto_prompt import ContextoPrompt
from .faq import FAQ, FAQInvalida, generar_faq
from .prompts import VERSION_POR_DEFECTO, cargar_prompt
from .qa import RespuestaQA, responder
from .resumen import RespuestaResumen, ResumenInvalido, generar_resumen
from .validacion import DeteccionPII, detectar_pii, mensaje_pii, sanear_pregunta

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel

#: Identificador del prompt cuando no se llamo al modelo (pregunta con PII).
PROMPT_SIN_MODELO = "sin_modelo"


@dataclass(frozen=True, slots=True)
class ResultadoQA:
    """Respuesta de Q&A validada y el tiempo que tardo la llamada."""

    respuesta: RespuestaQA
    segundos: float
    prompt: str


@dataclass(frozen=True, slots=True)
class ResultadoFAQ:
    """FAQ generada, o los errores de validacion si no cumplio el contrato."""

    faq: FAQ | None
    errores: tuple[str, ...]
    metricas: dict[str, Any]
    segundos: float
    prompt: str


@dataclass(frozen=True, slots=True)
class ResultadoResumen:
    """Resumen generado, o los errores de validacion si no cumplio el contrato."""

    resumen: RespuestaResumen | None
    errores: tuple[str, ...]
    metricas: dict[str, Any]
    segundos: float
    prompt: str


def detectar_pii_pregunta(pregunta: str, *, contexto: ContextoPrompt) -> DeteccionPII | None:
    """Indica si la pregunta trae datos personales, sin llamar al modelo.

    Reutiliza ``validacion.detectar_pii`` con los telefonos publicos del canal
    oficial como unica lista de permitidos. La app llama a esta funcion antes de
    tocar la cache: una pregunta con datos personales no se guarda.
    """
    if not pregunta.strip():
        return None
    permitidos = contexto.canal.telefonos if contexto.canal else ()
    return detectar_pii(sanear_pregunta(pregunta), permitidos=permitidos)


def respuesta_pii(contexto: ContextoPrompt, deteccion: DeteccionPII) -> ResultadoQA:
    """Mensaje de proteccion determinista, sin modelo y sin cache."""
    canal = contexto.canal
    return ResultadoQA(
        respuesta=RespuestaQA(
            texto=mensaje_pii(deteccion.categoria, canal),
            fuente=canal.url if canal else "",
            sin_datos=False,
            avisos=("pii_bloqueada",),
        ),
        segundos=0.0,
        prompt=PROMPT_SIN_MODELO,
    )


def ejecutar_pregunta(
    modelo: BaseChatModel,
    version: str,
    pregunta: str,
    *,
    contexto: ContextoPrompt,
) -> ResultadoQA:
    """Responde una pregunta con la version de prompt indicada."""
    prompt = cargar_prompt("qa", version)
    inicio = time.perf_counter()
    respuesta = responder(modelo, prompt, contexto, pregunta)
    return ResultadoQA(
        respuesta=respuesta,
        segundos=time.perf_counter() - inicio,
        prompt=prompt.nombre,
    )


def ejecutar_faq(modelo: BaseChatModel, *, contexto: ContextoPrompt) -> ResultadoFAQ:
    """Genera las diez preguntas frecuentes con el prompt por defecto (v1)."""
    prompt = cargar_prompt("faq", VERSION_POR_DEFECTO)
    metricas: dict[str, Any] = {}
    faq: FAQ | None = None
    errores: tuple[str, ...] = ()

    inicio = time.perf_counter()
    try:
        faq = generar_faq(modelo, prompt, contexto, metricas=metricas)
    except FAQInvalida as exc:
        errores = tuple(exc.errores)
    segundos = time.perf_counter() - inicio

    return ResultadoFAQ(
        faq=faq,
        errores=errores,
        metricas=metricas,
        segundos=segundos,
        prompt=prompt.nombre,
    )


def ejecutar_resumen(
    modelo: BaseChatModel,
    tema: str = "",
    *,
    contexto: ContextoPrompt,
) -> ResultadoResumen:
    """Genera el resumen ejecutivo con el prompt por defecto (v1)."""
    prompt = cargar_prompt("resumen", VERSION_POR_DEFECTO)
    resumen: RespuestaResumen | None = None
    errores: tuple[str, ...] = ()
    metricas: dict[str, Any] = {}

    inicio = time.perf_counter()
    try:
        resumen = generar_resumen(modelo, prompt, contexto, tema)
    except ResumenInvalido as exc:
        errores = tuple(exc.errores)
    else:
        metricas = dict(resumen.metricas)
    segundos = time.perf_counter() - inicio

    return ResultadoResumen(
        resumen=resumen,
        errores=errores,
        metricas=metricas,
        segundos=segundos,
        prompt=prompt.nombre,
    )
