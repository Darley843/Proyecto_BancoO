"""Utilidades compartidas por las herramientas del agente `pana`."""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ValidationError

from ..canal.contratos import EntradaDiagnostico, ResultadoDiagnostico
from ..cifras_legibles import formatear_pesos
from ..diagnostico.motor import calcular, entrada_desde_respuestas
from .esquemas import LIMITES_MONTO, ErrorHerramienta, SalidaHerramienta


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


def aplicar_monto_exacto(
    herramienta: str,
    entrada: EntradaDiagnostico,
    monto: int,
) -> EntradaDiagnostico | SalidaHerramienta:
    """Reemplaza el valor del rango por el monto exacto, si cabe en sus límites.

    Args:
        herramienta: nombre del catálogo, para el sobre de error.
        entrada: entrada del diagnóstico con el valor de cálculo del rango.
        monto: monto exacto que dijo el invitado, en pesos.

    Returns:
        La entrada con el monto exacto, o el error `entrada_invalida` con los
        límites del rango elegido.
    """
    ident = next(
        (valor for valor in entrada.rango_usado.values() if valor.startswith("monto.")),
        None,
    )
    if ident is None:
        return error(
            herramienta,
            "entrada_invalida",
            "El producto no lleva monto de crédito; no se puede aplicar un monto exacto.",
        )
    limites = LIMITES_MONTO.get(ident)
    if limites is None:
        return error(
            herramienta,
            "entrada_invalida",
            f"El rango {ident} no declara límites de monto.",
        )
    desde, hasta = limites
    if not desde <= monto <= hasta:
        salida = error(
            herramienta,
            "entrada_invalida",
            (
                f"El monto {monto} no cabe en el rango {ident}: desde "
                f"{formatear_pesos(Decimal(desde))} hasta {formatear_pesos(Decimal(hasta))}."
            ),
        )
        salida.datos.update(
            {
                "monto": monto,
                "rango": ident,
                "limites": {"desde": desde, "hasta": hasta},
            }
        )
        return salida
    return entrada.model_copy(update={"monto_credito": Decimal(monto)})


def diagnostico_de(
    respuestas: list[str],
    monto: int | None = None,
    *,
    herramienta: str = "diagnostico",
) -> ResultadoDiagnostico | SalidaHerramienta:
    """Convierte las respuestas de la entrevista en un diagnóstico calculado.

    Args:
        respuestas: ids canónicos elegidos en la entrevista.
        monto: monto exacto que dijo el invitado; si se pasa, reemplaza el valor
            de cálculo del rango dentro de sus límites.
        herramienta: nombre del catálogo, para el sobre de error del monto.

    Returns:
        El resultado determinista del motor o el error del monto exacto.

    Raises:
        ValueError: si las respuestas no forman una entrevista completa.
        ValidationError: si la entrada no cumple el contrato.
    """
    entrada = entrada_desde_respuestas(respuestas)
    if monto is not None:
        ajustada = aplicar_monto_exacto(herramienta, entrada, monto)
        if isinstance(ajustada, SalidaHerramienta):
            return ajustada
        entrada = ajustada
    return calcular(entrada)
