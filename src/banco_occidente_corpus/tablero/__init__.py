"""Tablero de tasas: tarifario PDF y tablas de Gold convertidos en filas."""

from __future__ import annotations

from .consultas import Comparacion, buscar_filas, comparar_filas
from .tipos import COLUMNAS, Fila

__all__ = ["COLUMNAS", "Comparacion", "Fila", "buscar_filas", "comparar_filas"]
