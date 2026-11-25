"""Pruebas de Don Gota: aritmética en Decimal, frases fijas y turnos con fuente.

La aritmética se comprueba contra los valores del diseño con $1.000.000 y con
un monto que obliga a redondear al peso. Las frases se leen del TOML real y el
selector se prueba dos veces con el mismo perfil.
"""

from __future__ import annotations

import tomllib
from decimal import Decimal
from pathlib import Path

import pytest

from banco_occidente_corpus.cifras_legibles import formatear_tasa_ea
from banco_occidente_corpus.config import PROJECT_ROOT
from banco_occidente_corpus.escena.gota import (
    SUPUESTO_RENOVACION,
    calcular_prestamo_gota,
    cargar_config_gota,
    seleccionar_frase,
    turnos_don_gota,
)

#: Archivo real de la escena, versionado en el repositorio.
RUTA_CONFIG = PROJECT_ROOT / "config" / "escena.toml"


def test_config_del_demo_tiene_los_parametros_del_diseno() -> None:
    """El TOML declara la tasa, el ciclo, el horizonte y los cuatro grupos."""
    with RUTA_CONFIG.open("rb") as fh:
        datos = tomllib.load(fh)

    gota = datos["gota"]
    assert gota["tasa_mensual"] == 0.20
    assert gota["dias_ciclo"] == 30
    assert gota["meses_horizonte"] == 36
    assert set(gota["frases"]) == {"oferta", "presion_diaria", "renovacion", "cierre"}
    assert all(gota["frases"][grupo] for grupo in gota["frases"])


def test_prestamo_de_un_millon_coincide_con_el_diseno() -> None:
    """Con $1.000.000 salen $200.000, $1.200.000, $40.000, $7.200.000 y 791,61 %."""
    prestamo = calcular_prestamo_gota(Decimal("1000000"), config=cargar_config_gota())

    assert prestamo.interes_mensual == Decimal("200000")
    assert prestamo.total_ciclo == Decimal("1200000")
    assert prestamo.cuota_diaria == Decimal("40000")
    assert prestamo.intereses_horizonte == Decimal("7200000")
    assert prestamo.total_pagado_horizonte == Decimal("8200000")
    assert prestamo.tasa_ea == Decimal("7.9161")
    assert formatear_tasa_ea(prestamo.tasa_ea) == "791,61 % E.A."
    assert prestamo.supuesto == SUPUESTO_RENOVACION


def test_redondeo_al_peso() -> None:
    """Cada monto se redondea al peso con ROUND_HALF_UP."""
    prestamo = calcular_prestamo_gota(Decimal("1234567"), config=cargar_config_gota())

    assert prestamo.interes_mensual == Decimal("246913")
    assert prestamo.total_ciclo == Decimal("1481480")
    assert prestamo.cuota_diaria == Decimal("49383")
    assert prestamo.intereses_horizonte == Decimal("8888868")
    assert prestamo.total_pagado_horizonte == Decimal("10123435")


def test_cambio_de_tasa_en_config(tmp_path: Path) -> None:
    """La tasa se lee del TOML y no está fija en el código."""
    ruta = tmp_path / "escena.toml"
    ruta.write_text(
        "\n".join(
            (
                "[gota]",
                "tasa_mensual = 0.10",
                "dias_ciclo = 30",
                "meses_horizonte = 36",
                "",
            )
        ),
        encoding="utf-8",
    )

    prestamo = calcular_prestamo_gota(Decimal("1000000"), ruta=ruta)

    assert prestamo.interes_mensual == Decimal("100000")
    assert prestamo.total_ciclo == Decimal("1100000")
    assert prestamo.cuota_diaria == Decimal("36667")
    assert prestamo.intereses_horizonte == Decimal("3600000")
    assert prestamo.total_pagado_horizonte == Decimal("4600000")
    assert prestamo.tasa_ea == Decimal("2.1384")


@pytest.mark.parametrize("monto", ["0", "-1", "-1000000"])
def test_monto_cero_o_negativo_se_rechaza(monto: str) -> None:
    """No hay préstamo de Don Gota sin capital positivo."""
    with pytest.raises(ValueError, match="positivo"):
        calcular_prestamo_gota(Decimal(monto), config=cargar_config_gota())


def test_selector_de_frases_es_determinista() -> None:
    """Dos corridas del mismo perfil eligen la misma frase."""
    config = cargar_config_gota()
    frases = config.frases["oferta"]

    assert seleccionar_frase(frases, "verde_empleado") == seleccionar_frase(
        frases, "verde_empleado"
    )
    assert seleccionar_frase(frases, 0) == frases[0]


def test_turnos_de_don_gota_son_fijos_y_cada_cifra_tiene_fuente() -> None:
    """Los cuatro turnos son de guion fijo y cada cifra cita su origen.

    Don Gota vende lo fácil: no revela la tasa E.A., ni los totales de 36
    meses, ni el supuesto; esas cifras quedan para Pana.
    """
    config = cargar_config_gota()
    prestamo = calcular_prestamo_gota(Decimal("1000000"), config=config)

    turnos = turnos_don_gota(prestamo, "verde_empleado", config=config)

    assert [turno.id for turno in turnos] == [
        "gota.oferta.v1",
        "gota.presion.v1",
        "gota.renovacion.v1",
        "gota.cierre.v1",
    ]
    assert [turno.orden for turno in turnos] == [1, 2, 3, 4]
    assert all(turno.personaje == "don_gota" for turno in turnos)
    assert all(turno.origen == "guion_fijo" for turno in turnos)
    for turno in turnos:
        assert "E.A." not in turno.texto
        assert "$7.200.000" not in turno.texto
        assert "$8.200.000" not in turno.texto
        assert SUPUESTO_RENOVACION not in turno.texto
        assert turno.cifras
        for cifra in turno.cifras:
            assert cifra.fuente.referencia
            assert cifra.valor_legible in turno.texto
