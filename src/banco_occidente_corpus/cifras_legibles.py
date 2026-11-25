"""Cifras legibles en formato colombiano para copiar y auditar.

Las herramientas del agente devuelven cada cifra dos veces: el valor de máquina
(``valor``, con la convención del motor) y el texto que la persona lee
(``valor_legible``, como ``791,61 % E.A.``, ``$80.000`` o ``$16.400.000``). El
modelo copia el texto y no recalcula ni reinterpreta la escala: ``7,9161`` es
una fracción de tasa, no ``7,916 %``.

Cada bloque agrega también ``cifras_permitidas``: los textos legibles listos
para pasarlos a ``auditar_respuesta`` como respaldo de la respuesta.

El módulo es determinista y no depende de nada del proyecto; por eso lo pueden
usar tanto la escena como el servidor MCP y las herramientas del agente.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any, Literal

#: Unidad de una cifra legible.
UnidadLegible = Literal[
    "pesos",
    "porcentaje",
    "porcentaje_ea",
    "meses",
    "dias",
    "veces",
    "puntos",
]
#: Tope de cifras permitidas que acepta `auditar_respuesta`.
MAXIMO_CIFRAS_PERMITIDAS: int = 40


def _decimal(valor: object) -> Decimal:
    """Convierte un valor finito en decimal sin arrastrar el ruido del `float`.

    Args:
        valor: número, texto o `Decimal`.

    Returns:
        El decimal validado.

    Raises:
        ValueError: si el valor no es un decimal finito.
    """
    try:
        numero = Decimal(str(valor))
    except InvalidOperation as error:
        raise ValueError(f"el valor no es un decimal válido: {valor!r}") from error
    if not numero.is_finite():
        raise ValueError(f"el valor debe ser un decimal finito: {valor!r}")
    return numero


def _cuantizar(valor: Decimal, decimales: int) -> Decimal:
    """Redondea un decimal con la precisión indicada y `ROUND_HALF_UP`.

    Args:
        valor: decimal que se redondea.
        decimales: cifras decimales que se conservan.

    Returns:
        El decimal redondeado.
    """
    return valor.quantize(Decimal(1).scaleb(-decimales), rounding=ROUND_HALF_UP)


def formatear_pesos(valor: Decimal | int | float | str) -> str:
    """Escribe un monto en pesos con separador de miles y signo.

    Args:
        valor: monto en pesos.

    Returns:
        El texto, como ``$1.000.000`` o ``-$1.643.023``.
    """
    entero = int(_cuantizar(_decimal(valor), 0))
    signo = "-" if entero < 0 else ""
    return f"{signo}${abs(entero):,}".replace(",", ".")


def formatear_porcentaje(valor: Decimal | int | float | str) -> str:
    """Escribe una fracción como porcentaje con coma decimal.

    Los ceros de dos decimales se omiten al final: ``0,20`` sale ``20 %`` y
    ``7,9161`` sale ``791,61 %``.

    Args:
        valor: fracción, donde 0,20 es 20 %.

    Returns:
        El texto con su signo de porcentaje.
    """
    centenas = _cuantizar(_decimal(valor) * 100, 2)
    texto = f"{centenas:.2f}".replace(".", ",").removesuffix(",00")
    return f"{texto} %"


def formatear_tasa_ea(valor: Decimal | int | float | str) -> str:
    """Escribe una tasa efectiva anual con su unidad.

    Args:
        valor: tasa como fracción, donde 0,2834 es 28,34 % E.A.

    Returns:
        El texto, como ``28,34 % E.A.`` o ``791,61 % E.A.``.
    """
    return f"{formatear_porcentaje(valor)} E.A."


def formatear_puntos(valor: Decimal | int | float | str) -> str:
    """Escribe una diferencia de tasas en puntos porcentuales.

    Args:
        valor: puntos porcentuales, donde 763,27 es la diferencia entre
            791,61 % y 28,34 %.

    Returns:
        El texto, como ``763,27 puntos porcentuales``.
    """
    cuantizado = _cuantizar(_decimal(valor), 2)
    return f"{cuantizado:.2f}".replace(".", ",") + " puntos porcentuales"


def formatear_veces(valor: Decimal | int | float | str) -> str:
    """Escribe un ratio de comparación con un decimal y la palabra «veces».

    Args:
        valor: número de veces.

    Returns:
        El texto, como ``6,8 veces``.
    """
    cuantizado = _cuantizar(_decimal(valor), 1)
    texto = f"{cuantizado:.1f}".replace(".", ",").removesuffix(",0")
    return f"{texto} veces"


def formatear_meses(meses: int | Decimal | float | str) -> str:
    """Escribe un plazo en meses con su unidad.

    Args:
        meses: número de meses.

    Returns:
        El texto, como ``36 meses`` o ``1 mes``.
    """
    entero = int(_cuantizar(_decimal(meses), 0))
    return f"{entero} mes" if entero == 1 else f"{entero} meses"


def formatear_dias(dias: int | Decimal | float | str) -> str:
    """Escribe un plazo en días con su unidad.

    Args:
        dias: número de días.

    Returns:
        El texto, como ``30 días``.
    """
    entero = int(_cuantizar(_decimal(dias), 0))
    return f"{entero} día" if entero == 1 else f"{entero} días"


def cifra(
    campo: str,
    valor: object,
    valor_legible: str,
    unidad: UnidadLegible,
    *,
    etiqueta: str | None = None,
) -> dict[str, Any]:
    """Arma una cifra con su valor de máquina y su texto legible.

    Args:
        campo: nombre del campo al que corresponde en la salida.
        valor: valor de máquina; `Decimal` se serializa como texto.
        valor_legible: texto en formato colombiano listo para copiar.
        unidad: unidad de la cifra.
        etiqueta: nombre legible; por defecto, el del campo.

    Returns:
        El diccionario con ``campo``, ``etiqueta``, ``valor``,
        ``valor_legible`` y ``unidad``.
    """
    texto_valor = str(valor) if isinstance(valor, Decimal) else valor
    return {
        "campo": campo,
        "etiqueta": etiqueta or campo,
        "valor": texto_valor,
        "valor_legible": valor_legible,
        "unidad": unidad,
    }


def bloque_cifras(cifras: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Agrupa las cifras y sus textos para la auditoría.

    Args:
        cifras: cifras armadas con `cifra`.

    Returns:
        ``cifras`` y ``cifras_permitidas``, sin textos repetidos y con el tope
        que acepta ``auditar_respuesta``.
    """
    lista = [dict(item) for item in cifras]
    permitidas: list[str] = []
    for item in lista:
        texto = str(item.get("valor_legible", "")).strip()
        if texto and texto not in permitidas:
            permitidas.append(texto)
    return {
        "cifras": lista,
        "cifras_permitidas": permitidas[:MAXIMO_CIFRAS_PERMITIDAS],
    }


def anotar(datos: dict[str, Any], cifras: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Agrega a una salida las cifras, sus permitidas y un `_legible` por campo.

    Args:
        datos: salida de la herramienta que se completa en el lugar.
        cifras: cifras armadas con `cifra`.

    Returns:
        El mismo diccionario, con ``cifras``, ``cifras_permitidas`` y
        ``<campo>_legible`` para cada cifra.
    """
    bloque = bloque_cifras(list(cifras))
    datos.update(bloque)
    for item in bloque["cifras"]:
        datos[f"{item['campo']}_legible"] = item["valor_legible"]
    return datos


__all__ = [
    "MAXIMO_CIFRAS_PERMITIDAS",
    "UnidadLegible",
    "anotar",
    "bloque_cifras",
    "cifra",
    "formatear_dias",
    "formatear_meses",
    "formatear_pesos",
    "formatear_porcentaje",
    "formatear_puntos",
    "formatear_tasa_ea",
    "formatear_veces",
]
