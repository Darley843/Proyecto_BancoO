"""Utilidades compartidas por las herramientas del agente `pana`."""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any

from pydantic import BaseModel, ValidationError

from ..canal.contratos import ResultadoDiagnostico
from ..diagnostico.motor import calcular, entrada_desde_respuestas
from .esquemas import ErrorHerramienta, SalidaHerramienta


def ok(herramienta: str, datos: dict[str, Any]) -> SalidaHerramienta:
    """Arma una salida exitosa con el nombre de la herramienta.

    Args:
        herramienta: nombre del catálogo.
        datos: resultado serializable de la herramienta.

    Returns:
        El sobre común con ``ok=True``.
    """
    return SalidaHerramienta(ok=True, herramienta=herramienta, datos=datos)


def error(herramienta: str, codigo: str, mensaje: str) -> SalidaHerramienta:
    """Arma una salida de error con un código estable y sin trazas internas.

    Args:
        herramienta: nombre del catálogo.
        codigo: código estable que el agente puede explicar.
        mensaje: explicación breve para la persona.

    Returns:
        El sobre común con ``ok=False``.
    """
    return SalidaHerramienta(
        ok=False,
        herramienta=herramienta,
        error=ErrorHerramienta(codigo=codigo, mensaje=mensaje[:300]),
    )


def mensaje_de_validacion(exc: ValidationError) -> str:
    """Resume una validación de Pydantic sin repetir el valor recibido.

    Args:
        exc: error de validación de la entrada.

    Returns:
        Un mensaje corto con el primer campo rechazado.
    """
    primero = exc.errors()[0] if exc.errors() else {}
    campo = ".".join(str(parte) for parte in primero.get("loc", ())) or "entrada"
    motivo = str(primero.get("msg", "valor inválido"))
    return f"El campo «{campo}» no es válido: {motivo}"[:300]


def como_json(valor: Any) -> Any:
    """Convierte modelos, dataclasses y tuplas en datos serializables.

    Args:
        valor: resultado de una herramienta o un fragmento de él.

    Returns:
        Diccionarios, listas y escalares listos para JSON.
    """
    if isinstance(valor, BaseModel):
        return valor.model_dump(mode="json")
    if is_dataclass(valor) and not isinstance(valor, type):
        return {clave: como_json(dato) for clave, dato in asdict(valor).items()}
    if isinstance(valor, dict):
        return {str(clave): como_json(dato) for clave, dato in valor.items()}
    if isinstance(valor, (list, tuple, set, frozenset)):
        return [como_json(dato) for dato in valor]
    if isinstance(valor, (str, int, float, bool)) or valor is None:
        return valor
    return str(valor)


def diagnostico_de(respuestas: list[str]) -> ResultadoDiagnostico:
    """Convierte las respuestas de la entrevista en un diagnóstico calculado.

    Args:
        respuestas: ids canónicos elegidos en la entrevista.

    Returns:
        El resultado determinista del motor.

    Raises:
        ValueError: si las respuestas no forman una entrevista completa.
        ValidationError: si la entrada no cumple el contrato.
    """
    entrada = entrada_desde_respuestas(respuestas)
    return calcular(entrada)
