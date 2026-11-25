"""Pruebas del formato colombiano de las cifras legibles."""

from __future__ import annotations

from decimal import Decimal

from banco_occidente_corpus.cifras_legibles import (
    MAXIMO_CIFRAS_PERMITIDAS,
    anotar,
    bloque_cifras,
    cifra,
    formatear_dias,
    formatear_meses,
    formatear_pesos,
    formatear_porcentaje,
    formatear_puntos,
    formatear_tasa_ea,
    formatear_veces,
)


def test_pesos_y_porcentajes_llevan_punto_de_miles_y_coma_decimal() -> None:
    """El texto es el que una persona copia en un mensaje de WhatsApp."""
    assert formatear_pesos(Decimal("16400000")) == "$16.400.000"
    assert formatear_pesos(Decimal("-524")) == "-$524"
    assert formatear_porcentaje(Decimal("0.20")) == "20 %"
    assert formatear_porcentaje(Decimal("7.9161")) == "791,61 %"
    assert formatear_tasa_ea(Decimal("7.9161")) == "791,61 % E.A."
    assert formatear_puntos(Decimal("763.27")) == "763,27 puntos porcentuales"
    assert formatear_veces(Decimal("5.72")) == "5,7 veces"
    assert formatear_meses(36) == "36 meses"
    assert formatear_meses(1) == "1 mes"
    assert formatear_dias(30) == "30 días"


def test_bloque_cifras_deduplica_las_permitidas() -> None:
    """Dos campos con el mismo texto dejan una sola cifra permitida."""
    bloque = bloque_cifras(
        [
            cifra("monto", 2_000_000, "$2.000.000", "pesos"),
            cifra("monto_otra_vez", 2_000_000, "$2.000.000", "pesos"),
            cifra("tasa_ea", Decimal("7.9161"), "791,61 % E.A.", "porcentaje_ea"),
        ]
    )
    assert bloque["cifras"][0]["valor_legible"] == "$2.000.000"
    assert bloque["cifras_permitidas"] == ["$2.000.000", "791,61 % E.A."]
    assert len(bloque["cifras_permitidas"]) <= MAXIMO_CIFRAS_PERMITIDAS


def test_anotar_agrega_el_legible_por_campo() -> None:
    """Cada cifra queda también en `<campo>_legible` para copiarla directo."""
    datos: dict[str, object] = {"monto": 2_000_000}
    anotar(datos, [cifra("monto", 2_000_000, "$2.000.000", "pesos")])
    assert datos["monto_legible"] == "$2.000.000"
    assert datos["cifras_permitidas"] == ["$2.000.000"]
