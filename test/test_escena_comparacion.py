"""Pruebas de Pana: comparación con el motor, usura, artículo 305 y fuentes."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from banco_occidente_corpus.canal.contratos import EntradaDiagnostico
from banco_occidente_corpus.diagnostico import motor
from banco_occidente_corpus.escena.comparacion import (
    ARTICULO_305,
    ESTADO_TASA_NO_DISPONIBLE,
    ESTADO_USURA_SIN_CERTIFICAR,
    alertas_comparacion,
    comparar_gota_banco,
    turnos_pana_comparacion,
)
from banco_occidente_corpus.escena.gota import (
    SUPUESTO_RENOVACION,
    PrestamoGota,
    calcular_prestamo_gota,
    cargar_config_gota,
)
from banco_occidente_corpus.tablero.tasas import (
    ConfiguracionTasas,
    FilaTasa,
    TasaNoDisponible,
    cargar_config_tasas,
    escribir_tabla,
)

#: Primer día de la vigencia de la tabla de prueba.
VIGENCIA_DESDE = date(2026, 11, 1)
#: Último día de la vigencia de la tabla de prueba.
VIGENCIA_HASTA = date(2026, 11, 30)
#: Fecha fija de consulta, dentro de la vigencia y lejos del día de la corrida.
FECHA_CONSULTA = date(2026, 11, 16)
#: Huella del PDF de tasas de la vigencia.
SHA_EJEMPLO = "989be43a0ed19eb33e2057cd01c1ae612b6f15544eaaf41af6348846a6ff1b7f"
#: URL de la fuente de las tasas.
FUENTE = "https://www.bancodeoccidente.com.co/documents/d/guest/tasas-personas-bdo"


def _fila(producto: str, desde: str, hasta: str) -> FilaTasa:
    """Construye una fila de la tabla Gold de prueba.

    Args:
        producto: clave canónica del producto.
        desde: tasa E.A. mínima publicada.
        hasta: tasa E.A. máxima publicada.

    Returns:
        La fila lista para escribir la tabla.
    """
    return FilaTasa(
        producto=producto,
        tipo_tasa="fija",
        tasa_ea_desde=Decimal(desde),
        tasa_ea_hasta=Decimal(hasta),
        vigencia_desde=VIGENCIA_DESDE,
        vigencia_hasta=VIGENCIA_HASTA,
        fuente=FUENTE,
        sha256_pdf=SHA_EJEMPLO,
        fecha_extraccion=VIGENCIA_DESDE,
    )


@pytest.fixture()
def raiz_tasas(tmp_path: Path) -> Path:
    """Crea una tabla Gold temporal con la tasa de libre inversión."""
    escribir_tabla(
        tmp_path / "tasas-personas-2026-11.jsonl",
        [_fila("libre_inversion", "0.2056", "0.2817")],
    )
    return tmp_path


@pytest.fixture()
def config_usura(tmp_path: Path) -> ConfiguracionTasas:
    """Carga una usura de prueba sin tocar `config/tasas.toml`."""
    ruta = tmp_path / "tasas.toml"
    ruta.write_text(
        "\n".join(
            (
                "[usura]",
                "tasa_ea = 0.2834",
                'vigencia_desde = "2026-11-01"',
                'vigencia_hasta = "2026-11-30"',
                'fuente = "https://www.superfinanciera.gov.co/"',
                'resolucion = "Resolución 1707 de 2026"',
                'exceptuados = ["vivienda", "ahorro", "cdt"]',
                "",
            )
        ),
        encoding="utf-8",
    )
    return cargar_config_tasas(ruta)


def _entrada(monto: Decimal = Decimal("1000000")) -> EntradaDiagnostico:
    """Perfil mínimo de prueba para el motor del diagnóstico.

    Args:
        monto: monto del crédito.

    Returns:
        La entrada normalizada del diagnóstico.
    """
    return EntradaDiagnostico(
        producto="libre_inversion",
        vinculacion="empleado",
        ingreso_mensual=Decimal("3000000"),
        gastos_mensuales=Decimal("1000000"),
        cuotas_deudas=Decimal("0"),
        monto_credito=monto,
        plazo_meses=36,
    )


def _prestamo(monto: str = "1000000") -> PrestamoGota:
    """Calcula el préstamo de Don Gota con la configuración real.

    Args:
        monto: monto del préstamo.

    Returns:
        El préstamo determinista.
    """
    return calcular_prestamo_gota(Decimal(monto), config=cargar_config_gota())


def test_comparacion_coincide_con_el_motor(
    raiz_tasas: Path, config_usura: ConfiguracionTasas
) -> None:
    """El banco usa el mismo monto y horizonte y el extremo máximo del motor."""
    prestamo = _prestamo()
    entrada = _entrada()
    esperado = motor.calcular(entrada, hoy=FECHA_CONSULTA, raiz=raiz_tasas)

    comparacion = comparar_gota_banco(
        prestamo,
        entrada,
        raiz=raiz_tasas,
        config_tasas=config_usura,
        hoy=FECHA_CONSULTA,
    )

    assert comparacion.monto == prestamo.monto
    assert comparacion.plazo_meses == prestamo.meses_horizonte == 36
    assert esperado.tasa_ea is not None
    assert comparacion.tasa_ea_banco == esperado.tasa_ea.hasta == Decimal("0.2817")
    assert esperado.total_pagado is not None
    assert comparacion.total_banco == esperado.total_pagado.hasta
    assert comparacion.total_gota == prestamo.total_pagado_horizonte
    assert comparacion.diferencia == comparacion.total_gota - comparacion.total_banco
    assert comparacion.usura_ea == Decimal("0.2834")
    assert comparacion.usura_vigencia == "2026-11-01/2026-11-30"
    assert comparacion.veces_usura is not None and comparacion.veces_usura > 1


def test_los_turnos_de_pana_citan_el_articulo_305_y_el_supuesto(
    raiz_tasas: Path, config_usura: ConfiguracionTasas
) -> None:
    """La plantilla fija incluye el artículo 305, el supuesto y la usura."""
    comparacion = comparar_gota_banco(
        _prestamo(),
        _entrada(),
        raiz=raiz_tasas,
        config_tasas=config_usura,
        hoy=FECHA_CONSULTA,
    )

    turnos = turnos_pana_comparacion(comparacion)

    assert [turno.id for turno in turnos] == [
        "pana.golpe.v1",
        "pana.tasa.v1",
        "pana.ley.v1",
    ]
    assert [turno.orden for turno in turnos] == [8, 9, 10]
    assert all(turno.origen == "motor" for turno in turnos)
    assert all(turno.personaje == "pana" for turno in turnos)
    assert all(len(turno.texto.split()) <= 40 for turno in turnos)
    assert "casi 6 veces lo que pagarías con el banco" in turnos[0].texto
    assert "renuevas cada mes durante tres años" in turnos[0].texto
    assert SUPUESTO_RENOVACION not in turnos[2].texto
    assert "27,9 veces" in turnos[1].texto
    assert ARTICULO_305 in turnos[2].texto
    assert "artículo 305" in turnos[2].texto
    assert "Usura vigente: 28,34 % E.A." in turnos[2].texto
    assert turnos[0].escenario is not None
    assert turnos[0].escenario.codigo == "comparacion"
    assert turnos[0].escenario.total_pagado == comparacion.total_gota
    veces = next(cifra for cifra in turnos[0].cifras if cifra.unidad == "veces")
    assert veces.valor == Decimal("5.72")
    assert veces.valor_legible == "6"


def test_el_ratio_del_total_redondea_sin_mentir(
    raiz_tasas: Path, config_usura: ConfiguracionTasas
) -> None:
    """«Casi» solo cuando redondea hacia arriba y «más de» cuando hacia abajo."""
    comparacion = comparar_gota_banco(
        _prestamo(),
        _entrada(),
        raiz=raiz_tasas,
        config_tasas=config_usura,
        hoy=FECHA_CONSULTA,
    )

    def golpe(veces: str) -> str:
        """Devuelve el texto del turno del golpe para un ratio dado.

        Args:
            veces: ratio del total que se quiere citar.

        Returns:
            El texto del primer turno de Pana.
        """
        ajustada = comparacion.model_copy(update={"veces_total": Decimal(veces)})
        return turnos_pana_comparacion(ajustada)[0].texto

    assert "casi 6 veces lo que pagarías con el banco" in golpe("5.72")
    assert "más de 6 veces lo que pagarías con el banco" in golpe("6.30")
    assert "Es 6 veces lo que pagarías con el banco" in golpe("6.00")


def test_ninguna_cifra_del_turno_queda_sin_fuente(
    raiz_tasas: Path, config_usura: ConfiguracionTasas
) -> None:
    """Cada cifra declara su fuente y su texto legible aparece en el turno."""
    comparacion = comparar_gota_banco(
        _prestamo(),
        _entrada(),
        raiz=raiz_tasas,
        config_tasas=config_usura,
        hoy=FECHA_CONSULTA,
    )

    turnos = turnos_pana_comparacion(comparacion)

    assert all(turno.cifras for turno in turnos)
    for turno in turnos:
        for cifra in turno.cifras:
            assert cifra.fuente.referencia
            assert cifra.valor_legible in turno.texto


def test_usura_sin_certificar_no_calcula_el_ratio(raiz_tasas: Path, tmp_path: Path) -> None:
    """Con usura 0,0 la comparación deja el ratio vacío y lo declara."""
    ruta = tmp_path / "tasas-sin-certificar.toml"
    ruta.write_text(
        "\n".join(
            (
                "[usura]",
                "tasa_ea = 0.0",
                'vigencia_desde = "2026-11-01"',
                'vigencia_hasta = "2026-11-30"',
                "",
            )
        ),
        encoding="utf-8",
    )

    comparacion = comparar_gota_banco(
        _prestamo(),
        _entrada(),
        raiz=raiz_tasas,
        config_tasas=cargar_config_tasas(ruta),
        hoy=FECHA_CONSULTA,
    )

    assert comparacion.usura_ea is None
    assert comparacion.usura_vigencia is None
    assert comparacion.fuente_usura is None
    assert comparacion.veces_usura is None
    assert ESTADO_USURA_SIN_CERTIFICAR in comparacion.supuestos
    assert alertas_comparacion(comparacion) == (ESTADO_USURA_SIN_CERTIFICAR,)
    turnos = turnos_pana_comparacion(comparacion)
    assert any("no hay usura certificada" in turno.texto for turno in turnos)


def test_tasa_no_disponible_sube_desde_el_motor(
    tmp_path: Path, config_usura: ConfiguracionTasas
) -> None:
    """Si el Tablero no publica la tasa, no se inventa: sube el código."""
    with pytest.raises(TasaNoDisponible) as error:
        comparar_gota_banco(
            _prestamo(),
            _entrada(),
            raiz=tmp_path / "vacia",
            config_tasas=config_usura,
            hoy=FECHA_CONSULTA,
        )

    assert error.value.codigo == ESTADO_TASA_NO_DISPONIBLE
