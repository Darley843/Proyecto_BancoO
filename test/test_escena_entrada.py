"""Pruebas del parser de entrada de la escena: letras, montos y confirmación.

No usan red ni modelo: leen las tarjetas de ``config/diagnostico.toml`` y
comprueban las reglas de la tarea 5.1 a 5.3.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from banco_occidente_corpus.escena.entrada import (
    CapturaEscena,
    confirmacion_de,
    interpretar,
    letra_de,
    monto_de,
)


@pytest.mark.parametrize(
    ("texto", "letra"),
    [
        ("A", "A"),
        ("be", "B"),
        ("letra C", "C"),
        ("opción D", "D"),
        ("de", "D"),
        ("efe", "F"),
        ("la E", None),
        ("a ver", None),
        ("la que sea", None),
    ],
)
def test_letra_de_reconoce_las_formas_del_guion(texto: str, letra: str | None) -> None:
    """Acepta la letra sola, su nombre y «letra X» u «opción X»."""
    assert letra_de(texto) == letra


@pytest.mark.parametrize(
    ("texto", "esperado"),
    [
        ("1.500.000", Decimal(1_500_000)),
        ("1,5 millones", Decimal(1_500_000)),
        ("ocho millones", Decimal(8_000_000)),
        ("dos palos", Decimal(2_000_000)),
        ("20 lucas", Decimal(20_000)),
        ("500 mil", Decimal(500_000)),
        ("$1.500.000", Decimal(1_500_000)),
        ("nada", None),
    ],
)
def test_monto_de_reconoce_los_giros(texto: str, esperado: Decimal | None) -> None:
    """Los montos del guion se leen sin usar coma flotante."""
    assert monto_de(texto) == esperado


def test_interpretar_usa_el_valor_de_la_tarjeta() -> None:
    """Sin monto declarado, la letra fija el valor de cálculo."""
    resultado = interpretar("A", "monto")
    assert resultado.respuesta is not None
    assert resultado.respuesta.letra == "A"
    assert resultado.respuesta.valor == Decimal(4_000_000)


def test_interpretar_usa_el_monto_declarado_si_cabe() -> None:
    """El monto declarado se usa cuando cae dentro del rango de la letra."""
    resultado = interpretar("A", "monto", monto=Decimal(3_200_000))
    assert resultado.ajustado is False
    assert resultado.respuesta is not None
    assert resultado.respuesta.valor == Decimal(3_200_000)


def test_interpretar_ajusta_y_explica_si_no_cabe() -> None:
    """Si no cabe, usa el valor del rango y lo explica; no recorta en silencio."""
    resultado = interpretar("A", "monto", monto=Decimal(9_000_000))
    assert resultado.ajustado is True
    assert resultado.mensaje is not None
    assert resultado.respuesta is not None
    assert resultado.respuesta.valor == Decimal(4_000_000)


def test_interpretar_rechaza_letra_fuera_de_rango() -> None:
    """Gastos tiene cinco tarjetas: la F no existe en esa pregunta."""
    resultado = interpretar("F", "gastos")
    assert resultado.respuesta is None
    assert resultado.mensaje is not None
    assert "A–E" in resultado.mensaje


def test_interpretar_rechaza_monto_bajo_el_limite() -> None:
    """Un monto fuera de los límites de la demo se rechaza, no se redondea."""
    resultado = interpretar("100", "monto")
    assert resultado.respuesta is None
    assert resultado.mensaje is not None


def test_interpretar_redirige_datos_personales() -> None:
    """Un teléfono no se guarda ni se repite: se pide un rango o una letra."""
    resultado = interpretar("mi celular es 300 123 4567", "ingresos")
    assert resultado.respuesta is None
    assert resultado.mensaje is not None
    assert "datos personales" in resultado.mensaje
    assert "300" not in resultado.mensaje


@pytest.mark.parametrize(
    ("texto", "esperado"),
    [
        ("sí", "si"),
        ("confirmo", "si"),
        ("dale", "si"),
        ("no", "no"),
        ("cambia", "cambia"),
        ("no, cambia", "cambia"),
        ("mmm", None),
    ],
)
def test_confirmacion_de(texto: str, esperado: str | None) -> None:
    """La confirmación es un conjunto cerrado de frases."""
    assert confirmacion_de(texto) == esperado


def _captura_completa() -> CapturaEscena:
    """Responde las cuatro preguntas con la primera tarjeta de cada una."""
    captura = CapturaEscena()
    for pregunta in ("monto", "ingresos", "gastos", "deudas"):
        assert captura.registrar(pregunta, "A").respuesta is not None
    return captura


def test_captura_exige_confirmacion_para_avanzar() -> None:
    """Sin confirmación no se avanza; «no» pide repetir."""
    captura = _captura_completa()
    assert captura.confirmar("mmm") == "repetir"
    assert captura.confirmar("no") == "repetir"
    assert captura.confirmar("sí") == "confirmado"


def test_captura_incompleta_no_confirma() -> None:
    """Si faltan respuestas, la confirmación no avanza."""
    captura = CapturaEscena()
    captura.registrar("monto", "A")
    assert captura.confirmar("sí") == "incompleto"


def test_captura_dos_intentos_pasa_a_perfil_seguro() -> None:
    """A los dos intentos fallidos se marca el perfil seguro."""
    captura = CapturaEscena()
    primero = captura.registrar("monto", "no entiendo")
    segundo = captura.registrar("monto", "sigue sin entenderse")
    assert primero.respuesta is None
    assert segundo.seguro is True
    assert captura.seguro is True


def test_captura_dos_confirmaciones_raras_pasa_a_perfil_seguro() -> None:
    """Dos respuestas que no son sí ni no también agotan los intentos."""
    captura = _captura_completa()
    assert captura.confirmar("mmm") == "repetir"
    assert captura.confirmar("otra cosa") == "seguro"


def test_captura_arma_el_perfil_confirmado() -> None:
    """El perfil sale con las cuatro respuestas y el monto de la tarjeta."""
    captura = _captura_completa()
    perfil = captura.perfil(personaje="Estudiante", proposito="Un computador")
    assert perfil.confirmado is True
    assert perfil.personaje == "Estudiante"
    assert perfil.monto_calculo == Decimal(4_000_000)
    assert len(perfil.respuestas) == 4
