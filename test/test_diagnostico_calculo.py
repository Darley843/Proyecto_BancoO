"""Pruebas del motor de cálculo del diagnóstico, sin red ni modelo.

La tabla Gold se construye en un directorio temporal con las mismas tasas de la
vigencia 2026-11 del Tablero. Así las pruebas son deterministas, no dependen de
`data/gold/` y cubren el filtro de segmentos y la exclusión de spreads.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Literal

import pytest

from banco_occidente_corpus.diagnostico.calculo import (
    EntradaCalculo,
    TasaProducto,
    calcular,
    capacidad_pago,
    cuota_francesa,
    evaluar,
    razon_endeudamiento,
    semaforo,
    tasa_de_tablero,
    tasa_mensual,
)
from banco_occidente_corpus.tablero.tasas import (
    FilaTasa,
    TasaNoDisponible,
    escribir_tabla,
)

#: Huella de ejemplo con el largo del PDF real.
SHA_EJEMPLO = "989be43a0ed19eb33e2057cd01c1ae612b6f15544eaaf41af6348846a6ff1b7f"
#: URL del PDF de tasas que se publica en la tabla Gold.
FUENTE = "https://www.bancodeoccidente.com.co/documents/d/guest/tasas-personas-bdo"
#: Primer día de la vigencia de la tabla de prueba.
VIGENCIA_DESDE = date(2026, 11, 1)
#: Último día de la vigencia de la tabla de prueba.
VIGENCIA_HASTA = date(2026, 11, 30)
#: Fecha de extracción de la tabla de prueba.
FECHA_EXTRACCION = date(2026, 11, 16)
#: Fecha de consulta fija: dentro de la vigencia y sin depender del día de la corrida.
FECHA_CONSULTA = date(2026, 11, 16)
#: Tolerancia en pesos para comparar cuotas verificadas con PAGO de Excel.
TOLERANCIA = Decimal(1)


def _fila(
    producto: str,
    desde: str,
    hasta: str,
    *,
    segmento: str | None = None,
    plazo_dias: int | None = None,
    tipo_tasa: Literal["fija", "spread_ipc", "spread_ibr"] = "fija",
) -> FilaTasa:
    """Construye una fila de la tabla Gold de prueba."""
    return FilaTasa(
        producto=producto,
        segmento=segmento,
        tipo_tasa=tipo_tasa,
        plazo_dias=plazo_dias,
        tasa_ea_desde=Decimal(desde),
        tasa_ea_hasta=Decimal(hasta),
        vigencia_desde=VIGENCIA_DESDE,
        vigencia_hasta=VIGENCIA_HASTA,
        fuente=FUENTE,
        sha256_pdf=SHA_EJEMPLO,
        fecha_extraccion=FECHA_EXTRACCION,
    )


@pytest.fixture()
def raiz_tasas(tmp_path: Path) -> Path:
    """Crea una tabla Gold temporal con las tasas del Tablero 2026-11."""
    filas = [
        _fila("libre_inversion", "0.2056", "0.2817"),
        _fila("compra_cartera", "0.1746", "0.2817"),
        _fila("libranza", "0.1539", "0.2431", segmento="Libre inversión"),
        _fila("libranza", "0.1471", "0.2343", segmento="Compra de cartera"),
        _fila("libranza", "0.1430", "0.2300", segmento="Retanqueo"),
        _fila("vivienda", "0.1517", "0.1854", segmento="Crédito hipotecario"),
        _fila("vivienda", "0.1452", "0.1819", segmento="Leasing habitacional"),
        _fila("ahorro", "0.0001", "0.0001", segmento="De 0 a $5.000.000"),
        _fila("ahorro", "0.0010", "0.0010", segmento="De $100.000.001 a $3.000.000.000"),
        _fila("cdt", "0.0005", "0.0005", segmento="$500M- $99 MM", plazo_dias=30),
        _fila("cdt", "0.1100", "0.1100", segmento="$500M- $99 MM", plazo_dias=90),
        _fila("cdt", "0.1205", "0.1205", segmento="$500M- $99 MM", plazo_dias=1080),
        _fila("cdt", "0.1215", "0.1215", segmento="$500 MM - 10.000 MM", plazo_dias=1080),
        _fila(
            "cdt",
            "0.9999",
            "0.9999",
            segmento="IPC",
            plazo_dias=90,
            tipo_tasa="spread_ipc",
        ),
    ]
    escribir_tabla(tmp_path / "tasas-personas-2026-11.jsonl", filas)
    return tmp_path


def _laura() -> EntradaCalculo:
    """Insumos de Laura: libre inversión de 15 millones a 48 meses."""
    return EntradaCalculo(
        producto="libre_inversion",
        ingreso_mensual=Decimal(6_500_000),
        gastos_mensuales=Decimal(2_500_000),
        cuotas_deudas=Decimal(0),
        monto_credito=Decimal(15_000_000),
        plazo_meses=48,
        vinculacion="empleado",
    )


def _andres() -> EntradaCalculo:
    """Insumos de Andrés: 35 millones a 36 meses con cuotas altas."""
    return EntradaCalculo(
        producto="libre_inversion",
        ingreso_mensual=Decimal(2_500_000),
        gastos_mensuales=Decimal(1_500_000),
        cuotas_deudas=Decimal(750_000),
        monto_credito=Decimal(35_000_000),
        plazo_meses=36,
        vinculacion="independiente",
    )


def _jaime() -> EntradaCalculo:
    """Insumos de Jaime: libranza de pensionado de 15 millones a 36 meses."""
    return EntradaCalculo(
        producto="libranza",
        ingreso_mensual=Decimal(4_000_000),
        gastos_mensuales=Decimal(1_500_000),
        cuotas_deudas=Decimal(750_000),
        monto_credito=Decimal(15_000_000),
        plazo_meses=36,
        vinculacion="pensionado",
    )


def test_tasa_mensual_de_24_por_ciento() -> None:
    """Una E.A. de 24 % equivale a 1,808758 % mensual, sin redondear."""
    assert tasa_mensual(Decimal("0.24")) == Decimal("0.018087582483510674531353084")


def test_tasa_mensual_cero_y_fuera_de_rango() -> None:
    """La tasa cero es cero y una tasa mayor que 1 se rechaza."""
    assert tasa_mensual(Decimal(0)) == Decimal(0)
    with pytest.raises(ValueError):
        tasa_mensual(Decimal("1.10"))


def test_cuota_francesa_10_millones_a_36_meses() -> None:
    """Valor verificado con PAGO de Excel: 380.380,61; tolerancia ±1 peso."""
    cuota = cuota_francesa(Decimal(10_000_000), tasa_mensual(Decimal("0.24")), 36)
    assert abs(cuota - Decimal("380380.61")) <= TOLERANCIA


def test_cuota_francesa_con_tasa_cero() -> None:
    """Con tasa cero la cuota reparte el capital entre los meses."""
    assert cuota_francesa(Decimal(10_000_000), Decimal(0), 36) == Decimal("277778")


def test_cuota_francesa_rechaza_plazo_invalido() -> None:
    """Un plazo de cero no se puede simular."""
    with pytest.raises(ValueError):
        cuota_francesa(Decimal(1_000_000), Decimal("0.02"), 0)


def test_capacidad_y_razon_con_compra_de_cartera() -> None:
    """La capacidad comparable descuenta las cuotas trasladadas."""
    capacidad = capacidad_pago(
        Decimal(4_000_000),
        Decimal(1_500_000),
        Decimal(1_500_000),
        Decimal(1_500_000),
    )
    razon = razon_endeudamiento(
        Decimal(1_500_000),
        Decimal(1_000_000),
        Decimal(4_000_000),
        Decimal(1_500_000),
    )
    assert capacidad == Decimal("2500000.00")
    assert razon == Decimal("0.2500")


def test_semaforo_verde_amarillo_y_rojo() -> None:
    """Los umbrales por defecto separan verde, amarillo y rojo."""
    assert semaforo(Decimal("0.25"), Decimal(500_000), Decimal(1_000_000)) == "verde"
    assert semaforo(Decimal("0.35"), Decimal(500_000), Decimal(1_000_000)) == "amarillo"
    assert semaforo(Decimal("0.45"), Decimal(500_000), Decimal(1_000_000)) == "rojo"


def test_semaforo_capacidad_negativa_y_cuota_sobre_capacidad() -> None:
    """La capacidad negativa o la cuota que no cabe siempre son rojo."""
    assert semaforo(Decimal("0.10"), Decimal(100_000), Decimal(-1)) == "rojo"
    assert semaforo(Decimal("0.10"), Decimal(1_001_000), Decimal(1_000_000)) == "rojo"


def test_semaforo_respeta_umbrales_configurados() -> None:
    """Cambiar los umbrales cambia el color del mismo caso."""
    razon = Decimal("0.35")
    assert semaforo(razon, Decimal(0), Decimal(1), Decimal("0.36"), Decimal("0.40")) == "verde"
    assert semaforo(razon, Decimal(0), Decimal(1), Decimal("0.30"), Decimal("0.34")) == "rojo"


def test_semaforo_rechaza_umbrales_invertidos() -> None:
    """Un umbral verde mayor que el amarillo es un error de configuración."""
    with pytest.raises(ValueError):
        semaforo(Decimal("0.10"), Decimal(0), Decimal(1), Decimal("0.50"), Decimal("0.40"))


def test_tasa_de_tablero_lee_vigencia_y_fuente(raiz_tasas: Path) -> None:
    """La tasa se lee de la tabla Gold con su vigencia, fuente y sha256."""
    tasa = tasa_de_tablero("libre_inversion", FECHA_CONSULTA, raiz=raiz_tasas)
    assert tasa.ea_desde == Decimal("0.2056")
    assert tasa.ea_hasta == Decimal("0.2817")
    assert tasa.vigencia_desde == VIGENCIA_DESDE
    assert tasa.vigencia_hasta == VIGENCIA_HASTA
    assert tasa.fuente == FUENTE
    assert tasa.sha256_pdf == SHA_EJEMPLO


def test_tasa_de_tablero_filtra_segmentos(raiz_tasas: Path) -> None:
    """Vivienda usa crédito hipotecario y libranza usa libre inversión."""
    vivienda = tasa_de_tablero("vivienda", FECHA_CONSULTA, raiz=raiz_tasas)
    libranza = tasa_de_tablero("libranza", FECHA_CONSULTA, raiz=raiz_tasas)
    assert vivienda.segmento == "Crédito hipotecario"
    assert vivienda.ea_desde == Decimal("0.1517")
    assert vivienda.ea_hasta == Decimal("0.1854")
    assert libranza.segmento == "Libre inversión"
    assert libranza.ea_desde == Decimal("0.1539")
    assert libranza.ea_hasta == Decimal("0.2431")


def test_tasa_de_tablero_excluye_spreads(raiz_tasas: Path) -> None:
    """Un spread IPC no se presenta como tasa del producto."""
    cdt = tasa_de_tablero("cdt", FECHA_CONSULTA, raiz=raiz_tasas)
    assert cdt.ea_hasta == Decimal("0.1205")
    assert all(tramo.ea_hasta < Decimal("0.5") for tramo in cdt.tramos)


def test_tasa_de_tablero_ahorro_usa_el_tramo_de_saldo_mas_bajo(raiz_tasas: Path) -> None:
    """La referencia del ahorro es el tramo más bajo, no el máximo del producto."""
    tasa = tasa_de_tablero("ahorro", FECHA_CONSULTA, raiz=raiz_tasas)

    assert tasa.tramo == "De 0 a $5.000.000"
    assert (tasa.ea_desde, tasa.ea_hasta) == (Decimal("0.0001"), Decimal("0.0001"))
    assert (tasa.rango_completo_desde, tasa.rango_completo_hasta) == (
        Decimal("0.0001"),
        Decimal("0.0010"),
    )


def test_tasa_de_tablero_cdt_rango_por_plazo_del_monto_minimo(raiz_tasas: Path) -> None:
    """El CDT se informa por plazo para el monto mínimo, con la envolvente aparte."""
    tasa = tasa_de_tablero("cdt", FECHA_CONSULTA, raiz=raiz_tasas)

    assert tasa.tramo == "De $500 mil a $99 millones"
    assert (tasa.ea_desde, tasa.ea_hasta) == (Decimal("0.0005"), Decimal("0.1205"))
    assert [tramo.etiqueta for tramo in tasa.tramos] == [
        "30 días (1 mes)",
        "90 días (3 meses)",
        "1080 días (3 años)",
    ]
    assert (tasa.rango_completo_desde, tasa.rango_completo_hasta) == (
        Decimal("0.0005"),
        Decimal("0.1215"),
    )


def test_tasa_de_tablero_sin_producto(tmp_path: Path) -> None:
    """Un producto sin tasa publicada se detiene con `tasa_no_disponible`."""
    with pytest.raises(TasaNoDisponible):
        tasa_de_tablero("libre_inversion", raiz=tmp_path / "vacia")


def test_laura_verde_con_cuota_en_rango(raiz_tasas: Path) -> None:
    """Valor verificado con PAGO de Excel: 498.002,71; tolerancia ±1 peso."""
    resultado = calcular(_laura(), hoy=FECHA_CONSULTA, raiz=raiz_tasas)
    assert resultado.cuota_max is not None
    assert abs(resultado.cuota_max - Decimal("498002.71")) <= TOLERANCIA
    assert resultado.cuota_min is not None
    assert resultado.cuota_min <= resultado.cuota_max
    assert resultado.razon_endeudamiento == Decimal("0.0766")
    assert resultado.semaforo == "verde"
    assert resultado.margen_despues_cuota == Decimal(3_501_997)
    assert resultado.base_semaforo == "tasa_maxima"
    assert resultado.tasa is not None
    assert resultado.tasa.ea_hasta == Decimal("0.2817")
    assert resultado.tasa.fuente == FUENTE
    assert "orientativo" in resultado.aviso
    assert "No es una aprobación" in resultado.aviso


def test_vigencia_vencida_en_credito_tambien_alerta(raiz_tasas: Path) -> None:
    """Una tasa de crédito vencida también se marca y se explica en el motivo."""
    resultado = calcular(_laura(), raiz=raiz_tasas, hoy=date(2026, 12, 1))

    assert "vigencia_vencida" in resultado.alertas
    assert any("tasa de libre inversión" in motivo for motivo in resultado.motivos)
    assert any("no incluye la fecha de hoy" in motivo for motivo in resultado.motivos)


def test_diciembre_consulta_la_vigencia_mas_reciente_con_alerta(raiz_tasas: Path) -> None:
    """Una fecha de diciembre no detiene la consulta: usa noviembre y avisa."""
    diciembre = date(2026, 12, 5)

    tasa = tasa_de_tablero("libre_inversion", diciembre, raiz=raiz_tasas)
    resultado = calcular(_laura(), fecha=diciembre, hoy=diciembre, raiz=raiz_tasas)

    assert tasa.vigencia_hasta == VIGENCIA_HASTA
    assert resultado.cuota_max is not None
    assert resultado.semaforo == "verde"
    assert "vigencia_vencida" in resultado.alertas
    assert any("del 1 al 30 de noviembre de 2026" in motivo for motivo in resultado.motivos)


def test_andres_rojo_porque_la_cuota_supera_la_capacidad(raiz_tasas: Path) -> None:
    """Valor verificado con PAGO de Excel: 1.393.022,71; tolerancia ±1 peso."""
    resultado = calcular(_andres(), hoy=FECHA_CONSULTA, raiz=raiz_tasas)
    assert resultado.cuota_max is not None
    assert abs(resultado.cuota_max - Decimal("1393022.71")) <= TOLERANCIA
    assert resultado.razon_endeudamiento == Decimal("0.8572")
    assert resultado.capacidad_pago == Decimal("250000.00")
    assert resultado.margen_despues_cuota == Decimal(-1_143_023)
    assert resultado.semaforo == "rojo"
    assert any("margen" in motivo for motivo in resultado.motivos)


def test_jaime_amarillo_con_libranza_de_pensionado(raiz_tasas: Path) -> None:
    """Valor verificado con PAGO de Excel: 572.541,25; tolerancia ±1 peso."""
    resultado = calcular(_jaime(), hoy=FECHA_CONSULTA, raiz=raiz_tasas)
    assert resultado.cuota_max is not None
    assert abs(resultado.cuota_max - Decimal("572541.25")) <= TOLERANCIA
    assert resultado.razon_endeudamiento == Decimal("0.3306")
    assert resultado.semaforo == "amarillo"
    assert resultado.tasa is not None
    assert resultado.tasa.segmento == "Libre inversión"
    assert resultado.tasa.ea_hasta == Decimal("0.2431")


def test_libranza_con_independiente_no_se_simula(raiz_tasas: Path) -> None:
    """La libranza exige empleado o pensionado: se explica y no hay semáforo."""
    entrada = EntradaCalculo(
        producto="libranza",
        ingreso_mensual=Decimal(4_000_000),
        gastos_mensuales=Decimal(1_500_000),
        cuotas_deudas=Decimal(750_000),
        monto_credito=Decimal(15_000_000),
        plazo_meses=36,
        vinculacion="independiente",
    )
    resultado = calcular(entrada, hoy=FECHA_CONSULTA, raiz=raiz_tasas)
    assert resultado.semaforo is None
    assert resultado.cuota_max is None
    assert resultado.tasa is None
    assert any("convenio" in motivo for motivo in resultado.motivos)
    assert any("libre inversión" in recomendacion for recomendacion in resultado.recomendaciones)


def test_ahorro_sin_semaforo_y_con_capacidad(raiz_tasas: Path) -> None:
    """El ahorro no tiene semáforo: informa capacidad y tasas de captación."""
    entrada = EntradaCalculo(
        producto="ahorro",
        ingreso_mensual=Decimal(2_000_000),
        gastos_mensuales=Decimal(1_500_000),
        cuotas_deudas=Decimal(0),
        vinculacion="empleado",
    )
    resultado = calcular(entrada, raiz=raiz_tasas, hoy=date(2026, 11, 16))
    assert resultado.semaforo is None
    assert resultado.capacidad_ahorro == Decimal("500000.00")
    assert resultado.margen_despues_cuota is None
    assert resultado.cuota_max is None
    assert {tasa.producto for tasa in resultado.tasas_captacion} == {"ahorro", "cdt"}
    assert any("tramo «De 0 a $5.000.000»" in motivo for motivo in resultado.motivos)
    assert any("CDT depende del plazo y del monto" in motivo for motivo in resultado.motivos)


def test_ahorro_sin_capacidad_orienta_a_revisar_los_gastos_fijos(raiz_tasas: Path) -> None:
    """Con capacidad cero no se recomienda ahorrar: se revisan los gastos fijos."""
    entrada = EntradaCalculo(
        producto="ahorro",
        ingreso_mensual=Decimal(2_000_000),
        gastos_mensuales=Decimal(2_000_000),
        cuotas_deudas=Decimal(0),
        vinculacion="empleado",
    )
    resultado = calcular(entrada, raiz=raiz_tasas, hoy=date(2026, 11, 16))

    assert resultado.capacidad_ahorro == Decimal(0)
    assert any("gastos fijos" in recomendacion for recomendacion in resultado.recomendaciones)
    assert all("automatiza" not in recomendacion for recomendacion in resultado.recomendaciones)


def test_vigencia_vencida_agrega_alerta_y_motivo(raiz_tasas: Path) -> None:
    """Si la vigencia no cubre la fecha de hoy, el resultado lo advierte."""
    entrada = EntradaCalculo(
        producto="ahorro",
        ingreso_mensual=Decimal(2_000_000),
        gastos_mensuales=Decimal(1_500_000),
        cuotas_deudas=Decimal(0),
        vinculacion="empleado",
    )
    resultado = calcular(entrada, raiz=raiz_tasas, hoy=date(2026, 12, 1))

    assert resultado.alertas == ("vigencia_vencida",)
    assert any("no incluye la fecha de hoy" in motivo for motivo in resultado.motivos)
    assert any("del 1 al 30 de noviembre de 2026" in motivo for motivo in resultado.motivos)


def test_compra_de_cartera_informa_ahorro_mensual(raiz_tasas: Path) -> None:
    """La compra de cartera descuenta la cuota trasladada y estima el ahorro."""
    entrada = EntradaCalculo(
        producto="compra_cartera",
        ingreso_mensual=Decimal(4_000_000),
        gastos_mensuales=Decimal(1_000_000),
        cuotas_deudas=Decimal(1_500_000),
        cuota_trasladar=Decimal(1_500_000),
        monto_credito=Decimal(35_000_000),
        plazo_meses=60,
        vinculacion="empleado",
    )
    resultado = calcular(entrada, hoy=FECHA_CONSULTA, raiz=raiz_tasas)
    assert resultado.razon_endeudamiento == Decimal("0.2572")
    assert resultado.semaforo == "verde"
    assert resultado.ahorro_mensual is not None
    assert resultado.ahorro_mensual > 0
    assert any("reduce la cuota" in motivo for motivo in resultado.motivos)


def test_carolina_compra_de_cartera_ajusta_capacidad(raiz_tasas: Path) -> None:
    """Carolina: capacidad comparable y margen; PAGO de Excel 1.028.880,28."""
    entrada = EntradaCalculo(
        producto="compra_cartera",
        ingreso_mensual=Decimal(4_000_000),
        gastos_mensuales=Decimal(1_500_000),
        cuotas_deudas=Decimal(1_500_000),
        cuota_trasladar=Decimal(1_500_000),
        monto_credito=Decimal(35_000_000),
        plazo_meses=60,
        vinculacion="empleado",
    )
    resultado = calcular(entrada, hoy=FECHA_CONSULTA, raiz=raiz_tasas)
    assert resultado.cuota_max is not None
    assert abs(resultado.cuota_max - Decimal("1028880.28")) <= TOLERANCIA
    assert resultado.capacidad_pago == Decimal(2_500_000)
    assert resultado.margen_despues_cuota == Decimal(1_471_120)
    assert resultado.razon_endeudamiento == Decimal("0.2572")
    assert resultado.semaforo == "verde"
    assert resultado.ahorro_mensual == Decimal(471_120)


def test_capacidad_negativa_es_rojo_sin_simular(tmp_path: Path) -> None:
    """Con capacidad negativa no se consulta la tasa ni se simula el crédito."""
    entrada = EntradaCalculo(
        producto="libre_inversion",
        ingreso_mensual=Decimal(2_000_000),
        gastos_mensuales=Decimal(1_200_000),
        cuotas_deudas=Decimal(1_000_000),
        monto_credito=Decimal(10_000_000),
        plazo_meses=36,
        vinculacion="empleado",
    )
    resultado = calcular(entrada, hoy=FECHA_CONSULTA, raiz=tmp_path / "vacia")
    assert resultado.semaforo == "rojo"
    assert resultado.cuota_max is None
    assert resultado.capacidad_pago == Decimal("-200000.00")
    assert resultado.margen_despues_cuota is None
    assert resultado.tasa is None
    assert any("capacidad" in motivo for motivo in resultado.motivos)


def test_vivienda_rojo_si_la_cuota_supera_el_30_por_ciento(raiz_tasas: Path) -> None:
    """En vivienda, una cuota sobre 30 % del ingreso fuerza rojo."""
    entrada = EntradaCalculo(
        producto="vivienda",
        ingreso_mensual=Decimal(10_000_000),
        gastos_mensuales=Decimal(4_000_000),
        cuotas_deudas=Decimal(0),
        monto_credito=Decimal(220_000_000),
        plazo_meses=240,
        vinculacion="empleado",
    )
    resultado = calcular(entrada, hoy=FECHA_CONSULTA, raiz=raiz_tasas)
    assert resultado.razon_endeudamiento == Decimal("0.3249")
    assert resultado.semaforo == "rojo"
    assert any("vivienda" in motivo.lower() for motivo in resultado.motivos)
    assert resultado.tasa is not None
    assert resultado.tasa.segmento == "Crédito hipotecario"


def test_rango_de_cuota_con_tasa_minima_y_maxima() -> None:
    """La cuota se informa como rango y el semáforo usa la tasa máxima."""
    tasa = TasaProducto(
        producto="libre_inversion",
        segmento=None,
        ea_desde=Decimal("0.1850"),
        ea_hasta=Decimal("0.2490"),
        vigencia_desde=VIGENCIA_DESDE,
        vigencia_hasta=VIGENCIA_HASTA,
        fuente=FUENTE,
        sha256_pdf=SHA_EJEMPLO,
    )
    entrada = EntradaCalculo(
        producto="libre_inversion",
        ingreso_mensual=Decimal(5_000_000),
        gastos_mensuales=Decimal(2_000_000),
        cuotas_deudas=Decimal(0),
        monto_credito=Decimal(10_000_000),
        plazo_meses=36,
        vinculacion="empleado",
    )
    resultado = evaluar(entrada, tasa, hoy=FECHA_CONSULTA)
    assert resultado.cuota_min is not None
    assert resultado.cuota_max is not None
    assert resultado.cuota_min < resultado.cuota_max
    assert resultado.tasa_mensual_max == tasa_mensual(Decimal("0.2490"))
    assert resultado.base_semaforo == "tasa_maxima"
    assert resultado.semaforo == "verde"


def test_calculo_reproducible(raiz_tasas: Path) -> None:
    """Dos corridas con los mismos insumos producen exactamente lo mismo."""
    primera = calcular(_laura(), hoy=FECHA_CONSULTA, raiz=raiz_tasas)
    segunda = calcular(_laura(), hoy=FECHA_CONSULTA, raiz=raiz_tasas)
    assert primera == segunda


def test_compra_de_cartera_exige_cuota_trasladada(raiz_tasas: Path) -> None:
    """Sin cuota trasladada la compra de cartera no se puede calcular."""
    entrada = EntradaCalculo(
        producto="compra_cartera",
        ingreso_mensual=Decimal(4_000_000),
        gastos_mensuales=Decimal(1_500_000),
        cuotas_deudas=Decimal(1_500_000),
        monto_credito=Decimal(35_000_000),
        plazo_meses=60,
    )
    with pytest.raises(ValueError):
        calcular(entrada, hoy=FECHA_CONSULTA, raiz=raiz_tasas)
