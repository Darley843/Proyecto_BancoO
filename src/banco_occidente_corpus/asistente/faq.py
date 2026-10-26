"""FAQ del asistente con salida estructurada y validacion contra el contexto.

DeepSeek Flash en modo pensamiento rechaza ``function_calling`` con el error
400 ``Thinking mode does not support this tool_choice``. Por eso el metodo
principal es ``json_mode``: el esquema Pydantic viaja en el prompt y el modelo
debe responder solo JSON. Si alguien vuelve a ``function_calling`` y aparece
ese 400 concreto, se reintenta una vez con ``json_mode``.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, Literal

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from langchain_core.runnables import Runnable
from pydantic import BaseModel, Field, ValidationError

from .contexto_prompt import ContextoPrompt
from .metricas import extraer_metricas
from .prompts import Prompt
from .validacion import (
    cifras_duras,
    cifras_inventadas,
    detectar_pii,
    url_en_contexto,
)

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel

#: Metodo de salida estructurada; ``json_mode`` evita el 400 de tool_choice.
METODO_ESTRUCTURADO: Literal["function_calling", "json_mode"] = "json_mode"

#: Respaldo automatico ante el 400 concreto de ``tool_choice``.
METODO_RESPALDO: Literal["function_calling", "json_mode"] = "json_mode"

TOTAL_PREGUNTAS = 10


class Fuente(BaseModel):
    """Fuente de una pregunta frecuente."""

    url: str = Field(description="URL exacta de una linea 'Fuente:' del contexto")


class PreguntaFrecuente(BaseModel):
    """Pregunta, respuesta y fuente de la FAQ."""

    pregunta: str = Field(description="Pregunta frecuente de un cliente nuevo")
    respuesta: str = Field(description="Respuesta breve basada solo en el contexto")
    fuente: Fuente


class FAQ(BaseModel):
    """Las diez preguntas frecuentes del asistente."""

    preguntas: list[PreguntaFrecuente] = Field(
        min_length=TOTAL_PREGUNTAS,
        max_length=TOTAL_PREGUNTAS,
        description="Exactamente diez preguntas frecuentes",
    )


_ESQUEMA_JSON = json.dumps(FAQ.model_json_schema(), ensure_ascii=False, indent=2)

#: Instruccion de ``json_mode``: sin ella DeepSeek no conoce la forma esperada.
INSTRUCCION_JSON = (
    "Responde solo con un objeto JSON válido, sin texto adicional, sin comentarios "
    "y sin cercas de código. Debe cumplir exactamente este esquema JSON Schema:\n"
    f"{_ESQUEMA_JSON}"
)


class FAQInvalida(RuntimeError):
    """La FAQ generada no cumple el contrato tras el reintento."""

    def __init__(self, errores: list[str]) -> None:
        self.errores = errores
        super().__init__("; ".join(errores) or "FAQ invalida")


def construir_mensajes_faq(
    prompt: Prompt,
    contexto: ContextoPrompt,
    *,
    json_mode: bool = True,
) -> list[BaseMessage]:
    """Arma el mensaje de sistema con el contexto y el humano con la tarea.

    Con ``json_mode`` añade el esquema JSON esperado y la orden de responder
    solo JSON, porque el proveedor no recibe el esquema por otra via.
    """
    sistema = f"<contexto>\n{contexto.texto}\n</contexto>\n\n{prompt.sistema}"
    recordatorio = prompt.recordatorio or (
        "Genera diez preguntas frecuentes con respuesta y fuente del contexto."
    )
    humano = (
        f"<reglas_clave>\n{recordatorio}\n</reglas_clave>\n\n"
        "Genera ahora las diez preguntas frecuentes."
    )
    if json_mode:
        humano = f"{humano}\n\n{INSTRUCCION_JSON}"
    return [SystemMessage(content=sistema), HumanMessage(content=humano)]


def validar_faq(faq: FAQ, contexto: ContextoPrompt) -> list[str]:
    """Comprueba cantidad, contenido, fuentes, cifras y PII de la FAQ."""
    errores: list[str] = []
    if len(faq.preguntas) != TOTAL_PREGUNTAS:
        errores.append(f"se esperaban {TOTAL_PREGUNTAS} preguntas y llegaron {len(faq.preguntas)}")

    permitidos = contexto.canal.telefonos if contexto.canal else ()
    cifras_contexto = cifras_duras(contexto.texto)

    for indice, item in enumerate(faq.preguntas, 1):
        if not item.pregunta.strip():
            errores.append(f"pregunta {indice} vacia")
        if not item.respuesta.strip():
            errores.append(f"respuesta {indice} vacia")
        if not url_en_contexto(item.fuente.url, contexto.urls):
            errores.append(f"fuente {indice} fuera del contexto: {item.fuente.url}")
        inventadas = cifras_inventadas(
            item.respuesta,
            cifras_contexto=cifras_contexto,
        )
        if inventadas:
            errores.append(f"cifras no presentes en el contexto en la respuesta {indice}")
        if detectar_pii(item.respuesta, permitidos=permitidos):
            errores.append(f"datos personales en la respuesta {indice}")

    return errores


def _es_error_tool_choice(exc: BaseException) -> bool:
    """Reconoce el 400 concreto de DeepSeek contra ``tool_choice``."""
    texto = str(exc).casefold()
    return "tool_choice" in texto and ("thinking" in texto or "does not support" in texto)


def _crear_runnable(
    modelo: BaseChatModel,
    metodo: Literal["function_calling", "json_mode"],
) -> Runnable[Any, Any]:
    """Crea el runnable de salida estructurada y conserva el mensaje crudo."""
    return modelo.with_structured_output(FAQ, method=metodo, include_raw=True)


def _invocar_estructurado(
    runnable: Runnable[Any, Any],
    mensajes: list[BaseMessage],
) -> tuple[FAQ, dict[str, Any]]:
    """Invoca la salida estructurada y devuelve la FAQ con sus metricas."""
    resultado = runnable.invoke(mensajes)
    metricas: dict[str, Any] = {}

    if isinstance(resultado, dict) and "parsed" in resultado:
        error = resultado.get("parsing_error")
        if isinstance(error, BaseException):
            raise error
        crudo = resultado.get("raw")
        if isinstance(crudo, BaseMessage):
            metricas = extraer_metricas(crudo)
        resultado = resultado.get("parsed")

    faq = resultado if isinstance(resultado, FAQ) else FAQ.model_validate(resultado)
    return faq, metricas


def _intentar_estructurado(
    modelo: BaseChatModel,
    mensajes: list[BaseMessage],
    runnables: dict[str, Runnable[Any, Any]],
) -> tuple[FAQ, dict[str, Any]]:
    """Intenta el metodo principal y, ante el 400 de ``tool_choice``, usa JSON.

    Los runnables se cachean para no reconstruirlos en cada reintento de
    validacion y para conservar el mismo objeto ante el proveedor.
    """
    metodo = METODO_ESTRUCTURADO
    runnable = runnables.get(metodo)
    if runnable is None:
        runnable = runnables[metodo] = _crear_runnable(modelo, metodo)

    try:
        return _invocar_estructurado(runnable, mensajes)
    except Exception as exc:
        if metodo == METODO_RESPALDO or not _es_error_tool_choice(exc):
            raise
        respaldo = runnables.get(METODO_RESPALDO)
        if respaldo is None:
            respaldo = runnables[METODO_RESPALDO] = _crear_runnable(modelo, METODO_RESPALDO)
        return _invocar_estructurado(
            respaldo,
            [*mensajes, HumanMessage(content=INSTRUCCION_JSON)],
        )


def generar_faq(
    modelo: BaseChatModel,
    prompt: Prompt,
    contexto: ContextoPrompt,
    *,
    metricas: dict[str, Any] | None = None,
) -> FAQ:
    """Genera la FAQ estructurada y la reintenta una vez si no cumple.

    ``metricas`` es un diccionario opcional que se rellena con el uso del modelo
    (tokens, razonamiento y cache) para que el CLI pueda mostrarlo.
    """
    mensajes = construir_mensajes_faq(
        prompt,
        contexto,
        json_mode=METODO_ESTRUCTURADO == "json_mode",
    )
    errores: list[str] = []
    runnables: dict[str, Runnable[Any, Any]] = {}

    for _ in range(2):
        try:
            faq, uso = _intentar_estructurado(modelo, mensajes, runnables)
            if metricas is not None:
                metricas.clear()
                metricas.update(uso)
            errores = validar_faq(faq, contexto)
        except (ValidationError, ValueError, TypeError, StopIteration) as exc:
            errores = [str(exc)]
        else:
            if not errores:
                return faq

        mensajes = [
            *mensajes,
            HumanMessage(
                content=(
                    "La respuesta anterior no cumple: "
                    + "; ".join(errores)
                    + ". Corrige y devuelve exactamente diez preguntas con fuente del contexto."
                )
            ),
        ]

    raise FAQInvalida(errores)


def render_markdown(faq: FAQ, prompt: Prompt, modelo: str) -> str:
    """Renderiza la FAQ como Markdown con fuente por pregunta."""
    lineas = [
        "# Preguntas frecuentes — Banco de Occidente",
        "",
        (
            "Generado con el corpus público del banco "
            f"(prompt `{prompt.nombre}`, modelo `{modelo}`)."
        ),
        "",
    ]
    for indice, item in enumerate(faq.preguntas, 1):
        lineas.extend(
            [
                f"{indice}. **{item.pregunta.strip()}**",
                "",
                f"   {item.respuesta.strip()}",
                "",
                f"   Fuente: {item.fuente.url.strip()}",
                "",
            ]
        )
    return "\n".join(lineas).rstrip() + "\n"
