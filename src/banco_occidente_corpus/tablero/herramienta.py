"""El Tablero como herramienta de LangChain, con esquema Pydantic.

La búsqueda sigue siendo determinista (``filas_para_plantilla``): no hay modelo,
ni red, ni estado. Este módulo solo le da a la misma lógica la forma que pide la
rúbrica del Módulo 2: un ``@tool`` llamado ``consultar_tablero`` con
``args_schema`` de Pydantic que valida la entrada y devuelve las filas del CSV
tal cual, con su valor y su trazabilidad. El nodo ``tablero`` del grafo la
invoca como herramienta, de modo que la ruta que responde sin modelo y la que
usa el agente comparten una sola puerta de entrada.
"""

from __future__ import annotations

from collections.abc import Sequence

from langchain_core.tools import BaseTool, tool
from pydantic import BaseModel, ConfigDict, Field

from ..texto import normalizar
from .consultas import filas_para_plantilla
from .tipos import Fila

#: Tope de filas que acepta la herramienta en una sola consulta.
MAX_FILAS_HERRAMIENTA: int = 20
#: Largo mínimo de la consulta: menos de tres letras no identifica una tarifa.
MIN_LARGO_CONSULTA: int = 3


class ConsultaTablero(BaseModel):
    """Entrada validada de la herramienta del Tablero."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    consulta: str = Field(
        min_length=MIN_LARGO_CONSULTA,
        max_length=300,
        description="Pregunta o términos del cliente, por ejemplo «cheque de gerencia».",
    )
    producto: str | None = Field(
        default=None,
        max_length=80,
        description=(
            "Producto que debe mencionar la fila, si se conoce; "
            "por ejemplo «Credencial Gold». Si ninguna fila lo menciona, no filtra."
        ),
    )
    limite: int = Field(
        default=10,
        ge=1,
        le=MAX_FILAS_HERRAMIENTA,
        description="Máximo de filas que devuelve la herramienta.",
    )


def filas_de_consulta(
    filas: Sequence[Fila],
    consulta: str,
    producto: str | None = None,
    limite: int = 10,
) -> list[Fila]:
    """Busca en el Tablero y devuelve como mucho `limite` filas exactas.

    El filtro por producto es una pista, no una condición: si ninguna fila
    menciona el producto, se busca sobre el catálogo completo y la consulta
    decide. Así una llamada con un producto mal escrito no se queda sin datos.

    Args:
        filas: catálogo completo del Tablero.
        consulta: pregunta o términos del cliente.
        producto: nombre del producto que debería aparecer en la fila.
        limite: máximo de filas que se devuelven.

    Returns:
        Las filas más específicas que responden la consulta, en el orden del
        catálogo. Nunca inventa filas: si no hay coincidencias, devuelve vacío.
    """
    candidatas = list(filas)
    filtro = normalizar(producto).strip() if producto else ""
    if filtro:
        con_producto = [
            fila for fila in candidatas if filtro in normalizar(f"{fila.concepto} {fila.categoria}")
        ]
        if con_producto:
            candidatas = con_producto
    return filas_para_plantilla(candidatas, consulta)[:limite]


def crear_herramienta_tablero(filas: Sequence[Fila]) -> BaseTool:
    """Crea ``consultar_tablero`` cerrada sobre el catálogo del Tablero.

    La herramienta valida la entrada con :class:`ConsultaTablero` y devuelve
    ``list[dict[str, str]]`` con las columnas del CSV. No imprime, no escribe y
    no consulta la red: la misma consulta devuelve siempre las mismas filas.

    Args:
        filas: catálogo completo del Tablero.

    Returns:
        La herramienta lista para `invoke` con un diccionario de argumentos.
    """
    catalogo = tuple(filas)

    @tool("consultar_tablero", args_schema=ConsultaTablero)
    def consultar_tablero(
        consulta: str,
        producto: str | None = None,
        limite: int = 10,
    ) -> list[dict[str, str]]:
        """Busca tarifas y coberturas exactas en el Tablero del Banco de Occidente.

        Devuelve las filas del tarifario o de las tablas del sitio que coinciden
        con la consulta, con su concepto, categoría, valor, moneda,
        periodicidad, vigencia y URL de la fuente.
        """
        return [
            fila.como_dict()
            for fila in filas_de_consulta(catalogo, consulta, producto=producto, limite=limite)
        ]

    return consultar_tablero
