"""Tablero de tasas: tarifario PDF y tablas de Gold convertidos en filas."""

from __future__ import annotations

from .consultas import (
    Comparacion,
    buscar_filas,
    comparar_filas,
    concepto_sin_franquicia,
    filas_para_plantilla,
)
from .herramienta import (
    MAX_FILAS_HERRAMIENTA,
    ConsultaTablero,
    crear_herramienta_tablero,
    filas_de_consulta,
)
from .tipos import COLUMNAS, Fila

__all__ = [
    "COLUMNAS",
    "MAX_FILAS_HERRAMIENTA",
    "Comparacion",
    "ConsultaTablero",
    "Fila",
    "buscar_filas",
    "comparar_filas",
    "concepto_sin_franquicia",
    "crear_herramienta_tablero",
    "filas_de_consulta",
    "filas_para_plantilla",
]
