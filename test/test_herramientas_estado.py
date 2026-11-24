"""Pruebas de las herramientas de estado del agente `pana` (12–16)."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from banco_occidente_corpus.herramientas import estado

USUARIO = "a" * 64
OTRO = "b" * 64


@pytest.fixture
def bases(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Aísla la base del canal y el store de perfil en una carpeta temporal."""
    canal = tmp_path / "canal.sqlite"
    monkeypatch.setenv(estado.VARIABLE_CANAL, str(canal))
    monkeypatch.setenv(estado.VARIABLE_PERFIL, str(tmp_path / "perfil.sqlite"))
    estado._PENDIENTES.clear()
    yield canal
    estado._PENDIENTES.clear()


def test_consentimiento_exige_aceptacion(bases: Path) -> None:
    """Sin aceptación explícita no se guarda nada."""
    rechazo = estado.registrar_consentimiento(USUARIO, acepta=False)
    assert not rechazo.ok
    assert rechazo.error is not None
    assert rechazo.error.codigo == "sin_confirmacion"

    aceptado = estado.registrar_consentimiento(USUARIO, acepta=True)
    assert aceptado.ok
    assert aceptado.datos["estado"] == "aceptado"
    assert bases.exists()


def test_olvidar_mis_datos_usa_dos_pasos(bases: Path) -> None:
    """El borrado solo ocurre con el token del primer paso y una sola vez."""
    estado.registrar_consentimiento(USUARIO, acepta=True)
    primero = estado.olvidar_mis_datos(USUARIO)
    assert primero.ok
    assert primero.datos["requiere_confirmacion"] is True
    token = str(primero.datos["token"])

    sin_token = estado.olvidar_mis_datos(USUARIO, confirmar=True)
    assert not sin_token.ok
    assert sin_token.error is not None
    assert sin_token.error.codigo == "confirmacion_invalida"

    confirmado = estado.olvidar_mis_datos(USUARIO, confirmar=True, token=token)
    assert confirmado.ok
    assert confirmado.datos["borrado"] is True
    assert confirmado.datos["estado"] == "sin_consentimiento"

    repetido = estado.olvidar_mis_datos(USUARIO, confirmar=True, token=token)
    assert not repetido.ok


def test_solicitar_asesor_abre_un_solo_caso(bases: Path) -> None:
    """El caso se abre una vez y solo lo ve la huella que lo pidió."""
    primero = estado.solicitar_asesor(USUARIO, motivo="necesito_ayuda")
    assert primero.ok
    token = str(primero.datos["token"])

    confirmado = estado.solicitar_asesor(
        USUARIO,
        motivo="necesito_ayuda",
        confirmar=True,
        token=token,
    )
    assert confirmado.ok
    id_caso = str(confirmado.datos["caso"])
    assert id_caso

    consulta = estado.consultar_caso(USUARIO)
    assert consulta.ok
    assert consulta.datos["total"] == 1
    assert consulta.datos["casos"][0]["id_caso"] == id_caso

    ajena = estado.consultar_caso(OTRO)
    assert ajena.ok
    assert ajena.datos["total"] == 0


def test_generar_tarjeta_pana_sin_imagen_trae_el_texto() -> None:
    """La tarjeta se puede devolver solo como texto equivalente."""
    salida = estado.generar_tarjeta_pana(
        [
            "objetivo.libre_inversion",
            "vinculacion.empleado",
            "ingresos.DE_3M_A_5M",
            "gastos.DE_1M_A_2M",
            "cuotas.NINGUNA",
            "monto.DE_5M_A_10M",
            "plazo.36",
        ]
    )
    assert salida.ok
    assert "Libre inversión" in str(salida.datos["texto"])
    assert "png_base64" not in salida.datos
