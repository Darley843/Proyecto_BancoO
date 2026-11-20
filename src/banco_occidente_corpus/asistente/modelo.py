"""Creacion del chat model de DeepSeek para el asistente.

La clave se lee **solo** de ``DEEPSEEK_API_KEY`` en el entorno. El proyecto no
carga archivos ``.env`` ni guarda claves en el repositorio. Las llamadas van al
API del modelo, no al sitio del banco: usan el cliente de LangChain con timeout
y reintentos acotados.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel

#: Modelo Flash vigente en la API de DeepSeek (DeepSeek-V4.1-Flash-1017).
MODELO_POR_DEFECTO = "deepseek-flash"

#: Variable de entorno con la clave; el proyecto no lee archivos .env.
VARIABLE_API_KEY = "DEEPSEEK_API_KEY"

TIMEOUT_POR_DEFECTO = 60.0
REINTENTOS_POR_DEFECTO = 2

_MENSAJE_CLAVE = (
    "Falta DEEPSEEK_API_KEY. Defínela en la sesión actual:\n"
    '  PowerShell: $env:DEEPSEEK_API_KEY = "<tu-clave>"\n'
    '  bash/zsh:   export DEEPSEEK_API_KEY="<tu-clave>"\n'
    "Este proyecto no lee archivos .env ni guarda claves en el repositorio."
)


@dataclass(frozen=True, slots=True)
class ParametrosTarea:
    """Temperatura y tope de tokens que usa cada tarea del asistente.

    Los topes cubren el razonamiento de DeepSeek Flash ademas del contenido; con
    valores bajos el razonamiento agotaba ``max_tokens`` y la respuesta llegaba
    vacia con ``finish_reason="length"``.
    """

    temperatura: float
    max_tokens: int


#: Parametros fijos por tarea: Q&A y FAQ a temperatura 0, resumen a 0.2.
#: El comite pide 3.000 tokens porque el razonamiento consume el tope y el JSON
#: de la postura quedaba cortado con 1.200.
PARAMETROS_POR_TAREA: dict[str, ParametrosTarea] = {
    "qa": ParametrosTarea(temperatura=0.0, max_tokens=2_000),
    "faq": ParametrosTarea(temperatura=0.0, max_tokens=8_000),
    "resumen": ParametrosTarea(temperatura=0.2, max_tokens=4_000),
    "comite": ParametrosTarea(temperatura=0.0, max_tokens=3_000),
}


def parametros_de(tarea: str) -> ParametrosTarea:
    """Devuelve temperatura y tope de tokens de una tarea del asistente."""
    try:
        return PARAMETROS_POR_TAREA[tarea]
    except KeyError as exc:
        disponibles = ", ".join(sorted(PARAMETROS_POR_TAREA))
        raise ValueError(f"Tarea desconocida: {tarea}. Usa una de: {disponibles}.") from exc


class FaltaApiKey(RuntimeError):
    """No hay ``DEEPSEEK_API_KEY`` en el entorno."""


def api_key_desde_entorno() -> str:
    """Devuelve la clave de la API o falla con instrucciones si no esta definida."""
    clave = os.environ.get(VARIABLE_API_KEY, "").strip()
    if not clave:
        raise FaltaApiKey(_MENSAJE_CLAVE)
    return clave


def crear_modelo(
    *,
    modelo: str = MODELO_POR_DEFECTO,
    temperatura: float = 0.0,
    max_tokens: int | None = None,
    timeout: float = TIMEOUT_POR_DEFECTO,
    max_retries: int = REINTENTOS_POR_DEFECTO,
    razonamiento: bool = True,
) -> BaseChatModel:
    """Crea un ``ChatDeepSeek`` configurado para el asistente.

    La importacion es perezosa para que ``--help`` funcione sin clave ni red.

    Args:
        modelo: nombre del modelo en la API.
        temperatura: temperatura de muestreo.
        max_tokens: tope de tokens de salida, razonamiento incluido.
        timeout: tiempo maximo de cada peticion, en segundos.
        max_retries: reintentos del cliente HTTP de LangChain.
        razonamiento: si es ``False`` desactiva el modo de pensamiento con
            ``reasoning_effort="none"``; el comite lo compara en su demo.
    """
    from langchain_deepseek import ChatDeepSeek

    opciones: dict[str, Any] = {
        "model": modelo,
        "api_key": api_key_desde_entorno(),
        "temperature": temperatura,
        "max_tokens": max_tokens,
        "timeout": timeout,
        "max_retries": max_retries,
    }
    if not razonamiento:
        opciones["reasoning_effort"] = "none"
    return ChatDeepSeek(**opciones)


def crear_modelo_para(
    tarea: str,
    *,
    modelo: str = MODELO_POR_DEFECTO,
    timeout: float = TIMEOUT_POR_DEFECTO,
    max_retries: int = REINTENTOS_POR_DEFECTO,
    razonamiento: bool = True,
) -> BaseChatModel:
    """Crea el modelo con la temperatura y el tope que fija la tarea."""
    parametros = parametros_de(tarea)
    return crear_modelo(
        modelo=modelo,
        temperatura=parametros.temperatura,
        max_tokens=parametros.max_tokens,
        timeout=timeout,
        max_retries=max_retries,
        razonamiento=razonamiento,
    )
