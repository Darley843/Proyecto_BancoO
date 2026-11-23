"""Pruebas de la selección del voluntario por fila y silla (tarea 5.4)."""

from __future__ import annotations

import pytest

from banco_occidente_corpus.escena.contratos import SeleccionVoluntario
from banco_occidente_corpus.escena.voluntario import (
    rangos_voluntario,
    seleccionar_voluntario,
)


def test_los_rangos_salen_del_toml() -> None:
    """La escena trae ocho filas y seis sillas."""
    assert rangos_voluntario() == (8, 6)


def test_la_misma_semilla_da_la_misma_silla() -> None:
    """Con semilla fija, la selección se repite en dos corridas."""
    primera = seleccionar_voluntario(semilla=7)
    segunda = seleccionar_voluntario(semilla=7)
    assert primera == segunda
    assert 1 <= primera.fila <= primera.filas
    assert 1 <= primera.silla <= primera.sillas
    assert primera.metodo == "azar"


def test_semillas_distintas_cambian_la_seleccion() -> None:
    """El azar no está fijo por defecto: dos semillas distintas no coinciden."""
    selecciones = set()
    for semilla in range(20):
        seleccion = seleccionar_voluntario(semilla=semilla)
        selecciones.add((seleccion.fila, seleccion.silla))
    assert len(selecciones) > 1


def test_generador_inyectado_no_toca_el_azar_del_sistema() -> None:
    """Un generador falso permite fijar la fila y la silla en una prueba."""

    class Fijo:
        """Generador que siempre devuelve el mismo valor."""

        def randint(self, a: int, b: int) -> int:
            """Devuelve el extremo inferior del rango."""
            return a

    seleccion = seleccionar_voluntario(filas=5, sillas=4, generador=Fijo())
    assert seleccion == SeleccionVoluntario(fila=1, silla=1, filas=5, sillas=4, metodo="azar")


def test_seleccion_manual_valida_el_rango() -> None:
    """La fila y la silla a mano se aceptan si existen."""
    seleccion = seleccionar_voluntario(filas=8, sillas=6, fila=3, silla=5)
    assert seleccion.metodo == "manual"
    assert (seleccion.fila, seleccion.silla) == (3, 5)
    with pytest.raises(ValueError, match="fuera del rango"):
        seleccionar_voluntario(filas=8, sillas=6, fila=9, silla=1)
    with pytest.raises(ValueError, match="fila y silla"):
        seleccionar_voluntario(filas=8, sillas=6, fila=3)


def test_no_se_puede_combinar_semilla_y_generador() -> None:
    """Las dos fuentes de azar no se mezclan."""
    with pytest.raises(ValueError, match="no los dos"):
        seleccionar_voluntario(semilla=1, generador=object())  # type: ignore[arg-type]


def test_rangos_invalidos() -> None:
    """Filas o sillas fuera de 1 a 100 se rechazan."""
    with pytest.raises(ValueError):
        seleccionar_voluntario(filas=0, sillas=6)
    with pytest.raises(ValueError):
        seleccionar_voluntario(filas=8, sillas=101)
