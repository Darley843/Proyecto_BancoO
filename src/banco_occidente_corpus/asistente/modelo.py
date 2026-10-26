"""Creacion del chat model de DeepSeek para el asistente.

La clave se lee **solo** de ``DEEPSEEK_API_KEY`` en el entorno. El proyecto no
carga archivos ``.env`` ni guarda claves en el repositorio. Las llamadas van al
API del modelo, no al sitio del banco: usan el cliente de LangChain con timeout
y reintentos acotados.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

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
) -> BaseChatModel:
    """Crea un ``ChatDeepSeek`` configurado para el asistente.

    La importacion es perezosa para que ``--help`` funcione sin clave ni red.
    """
    from langchain_deepseek import ChatDeepSeek

    return ChatDeepSeek(
        model=modelo,
        api_key=api_key_desde_entorno(),
        temperature=temperatura,
        max_tokens=max_tokens,
        timeout=timeout,
        max_retries=max_retries,
    )
