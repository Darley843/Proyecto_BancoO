"""Pruebas de la identidad del canal: E.164 y huella HMAC (sin red)."""

from __future__ import annotations

import pytest

from banco_occidente_corpus.canal.identidad import (
    calcular_usuario_id,
    main,
    normalizar_numero,
)

SAL = "sal-de-prueba"
"""Sal ficticia de las pruebas."""

NUMERO = "300 123 4567"
"""Número nacional escrito como lo haría una persona."""


def test_normaliza_variantes_al_mismo_e164() -> None:
    """Espacios, guiones, paréntesis y prefijos no cambian la identidad."""
    variantes = [
        "3001234567",
        "+57 300 123 4567",
        "57-300-123-4567",
        "0057 300 123 4567",
        "(300) 123 4567",
    ]

    assert {normalizar_numero(numero) for numero in variantes} == {"+573001234567"}


def test_numero_internacional_conserva_su_prefijo() -> None:
    """Un número de otro país no se prefija con 57."""
    assert normalizar_numero("+1 555 010 9999") == "+15550109999"


def test_diez_digitos_siempre_se_prefijan() -> None:
    """Diez dígitos son nacionales; el prefijo no se adivina por el contenido."""
    assert normalizar_numero("5730012345") == "+575730012345"


def test_ocho_digitos_es_un_numero_valido() -> None:
    """El límite inferior de E.164 se acepta tal cual."""
    assert normalizar_numero("60123456") == "+60123456"


def test_diecisiete_digitos_falla() -> None:
    """Por encima de quince dígitos no es E.164."""
    with pytest.raises(ValueError):
        normalizar_numero("1" * 16)


def test_numero_demasiado_corto_falla() -> None:
    """Menos de ocho dígitos no es un número E.164."""
    with pytest.raises(ValueError):
        normalizar_numero("123")


def test_huella_determinista_y_hexadecimal() -> None:
    """El mismo número da la misma huella y siempre son 64 hex."""
    huella = calcular_usuario_id(NUMERO, SAL)

    assert huella == calcular_usuario_id("+573001234567", SAL)
    assert len(huella) == 64
    assert all(caracter in "0123456789abcdef" for caracter in huella)


def test_sal_distinta_cambia_la_identidad() -> None:
    """Sin la sal correcta no se reconstruye el usuario."""
    assert calcular_usuario_id(NUMERO, SAL) != calcular_usuario_id(NUMERO, "otra-sal")


def test_sal_vacia_falla() -> None:
    """El canal no puede identificar usuarios sin sal."""
    with pytest.raises(ValueError):
        calcular_usuario_id(NUMERO, "")


def test_la_huella_no_contiene_el_numero() -> None:
    """La identidad persistible no arrastra dígitos del número."""
    huella = calcular_usuario_id(NUMERO, SAL)

    assert "3001234567" not in huella
    assert "573001234567" not in huella


def test_cli_imprime_la_huella(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """``--huella`` imprime el hash y nada más."""
    monkeypatch.setenv("WHATSAPP_ID_SALT", SAL)

    assert main(["--huella", NUMERO]) == 0
    assert capsys.readouterr().out.strip() == calcular_usuario_id(NUMERO, SAL)


def test_cli_sin_sal_falla(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Sin ``WHATSAPP_ID_SALT`` el comando avisa y no imprime una huella falsa."""
    monkeypatch.delenv("WHATSAPP_ID_SALT", raising=False)

    assert main(["--huella", NUMERO]) == 2
    assert "WHATSAPP_ID_SALT" in capsys.readouterr().err


def test_cli_con_numero_invalido_falla(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Un número inválido sale con código 2 y un mensaje en stderr."""
    monkeypatch.setenv("WHATSAPP_ID_SALT", SAL)

    assert main(["--huella", "12"]) == 2
    assert "inválido" in capsys.readouterr().err
