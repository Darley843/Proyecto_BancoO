"""Metricas de uso del modelo: tokens, razonamiento, cache y motivo de fin.

DeepSeek Flash razona antes de responder: esos tokens consumen ``max_tokens`` y
pueden dejar el contenido vacio con ``finish_reason="length"``. Aqui se leen
``usage_metadata`` y ``response_metadata`` de LangChain, que ya mapean
``reasoning_tokens`` a ``output_token_details.reasoning`` y los aciertos de
cache de DeepSeek a ``input_token_details.cache_read``.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from langchain_core.messages import BaseMessage


@dataclass(frozen=True, slots=True)
class UsoModelo:
    """Uso normalizado de una respuesta del modelo."""

    entrada: int | None = None
    salida: int | None = None
    razonamiento: int | None = None
    cache: int | None = None
    finish_reason: str | None = None

    @property
    def vacio(self) -> bool:
        """Indica si no se recibio ninguna metrica util."""
        return self == UsoModelo()


def extraer_metricas(respuesta: BaseMessage) -> dict[str, Any]:
    """Recoge uso y metadatos de una respuesta para el informe y ``--verbose``."""
    return {
        "uso": getattr(respuesta, "usage_metadata", None),
        "respuesta": getattr(respuesta, "response_metadata", None),
    }


def _entero(valor: object) -> int | None:
    """Devuelve el entero si el valor lo es; ignora booleanos y otros tipos."""
    if isinstance(valor, int) and not isinstance(valor, bool):
        return valor
    return None


def _detalle(fuente: object, clave: str) -> int | None:
    """Lee un entero de un detalle anidado (``Mapping`` o ``None``)."""
    if isinstance(fuente, Mapping):
        return _entero(fuente.get(clave))
    return None


def _partes(metricas: Mapping[str, Any] | None) -> tuple[Mapping[str, Any], Mapping[str, Any]]:
    """Separa ``uso`` y ``respuesta`` del diccionario de metricas."""
    if not isinstance(metricas, Mapping):
        return {}, {}
    uso = metricas.get("uso")
    metadatos = metricas.get("respuesta")
    return (
        uso if isinstance(uso, Mapping) else {},
        metadatos if isinstance(metadatos, Mapping) else {},
    )


def leer_uso(metricas: Mapping[str, Any] | None) -> UsoModelo:
    """Normaliza tokens y ``finish_reason``, con respaldo en el uso crudo."""
    uso, metadatos = _partes(metricas)
    crudo = metadatos.get("token_usage")

    entrada = _entero(uso.get("input_tokens"))
    salida = _entero(uso.get("output_tokens"))
    razonamiento = _detalle(uso.get("output_token_details"), "reasoning")
    cache = _detalle(uso.get("input_token_details"), "cache_read")
    if isinstance(crudo, Mapping):
        if entrada is None:
            entrada = _entero(crudo.get("prompt_tokens"))
        if salida is None:
            salida = _entero(crudo.get("completion_tokens"))
        if razonamiento is None:
            razonamiento = _detalle(crudo.get("completion_tokens_details"), "reasoning_tokens")
        if cache is None:
            cache = _entero(crudo.get("prompt_cache_hit_tokens"))
        if cache is None:
            cache = _detalle(crudo.get("prompt_tokens_details"), "cached_tokens")

    finish = metadatos.get("finish_reason")
    return UsoModelo(
        entrada=entrada,
        salida=salida,
        razonamiento=razonamiento,
        cache=cache,
        finish_reason=finish if isinstance(finish, str) else None,
    )


def _numero(valor: int | None) -> str:
    """Formatea un contador o ``n/d`` cuando el proveedor no lo informa."""
    return f"{valor:,}" if valor is not None else "n/d"


def formatear_metricas(metricas: Mapping[str, Any] | None) -> str:
    """Devuelve una linea legible con tokens, razonamiento, cache y fin.

    Devuelve cadena vacia si la respuesta no trae metricas, para que el CLI no
    imprima una linea sin datos.
    """
    uso = leer_uso(metricas)
    if uso.vacio:
        return ""
    return (
        f"entrada={_numero(uso.entrada)}, salida={_numero(uso.salida)}, "
        f"razonamiento={_numero(uso.razonamiento)}, caché={_numero(uso.cache)}, "
        f"finish_reason={uso.finish_reason or 'n/d'}"
    )


def diagnostico_respuesta_vacia(metricas: Mapping[str, Any] | None) -> str:
    """Explica una respuesta vacia con el motivo de fin y el razonamiento gastado."""
    uso = leer_uso(metricas)
    return (
        "respuesta vacía: "
        f"finish_reason={uso.finish_reason or 'desconocido'}, "
        f"tokens de razonamiento={_numero(uso.razonamiento)}, "
        f"tokens de salida={_numero(uso.salida)}, "
        f"aciertos de caché={_numero(uso.cache)}"
    )
