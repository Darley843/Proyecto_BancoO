"""Pruebas del puente entre el motor del diagnóstico y las tarjetas de Pana.

Se corre el motor real (`diagnostico.motor.calcular`) contra una tabla Gold
temporal y las personas sintéticas versionadas, y se comprueba que cada
resultado produce la tarjeta que le corresponde, con los mismos datos en la
imagen y en el texto. Nada se escribe en disco salvo la tabla temporal.
"""

from __future__ import annotations

import io
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Literal

import pytest
from PIL import Image

from banco_occidente_corpus.canal.contratos import EntradaDiagnostico, ResultadoDiagnostico
from banco_occidente_corpus.diagnostico.escenarios import (
    CambioEscenario,
    ComparacionEscenario,
    FotoResultado,
)
from banco_occidente_corpus.diagnostico.motor import calcular
from banco_occidente_corpus.pana.desde_diagnostico import (
    FRASE_AHORRO_SIN_MARGEN,
    FRASE_VIVIENDA,
    SinTarjeta,
    datos_ahorro,
    datos_diagnostico,
    datos_escenario,
    datos_no_aplica,
    datos_tarjeta,
    escenario_y_texto,
    tarjeta_y_texto,
    vigencia_corta,
)
from banco_occidente_corpus.pana.tarjetas import (
    AVISO,
    PESO_MAXIMO,
    DatosAhorro,
    DatosDiagnostico,
    DatosNoAplica,
    pesos,
)
from banco_occidente_corpus.tablero.tasas import FilaTasa, escribir_tabla

#: Vigencia de la tabla de prueba.
VIGENCIA_DESDE = date(2026, 11, 1)
VIGENCIA_HASTA = date(2026, 11, 30)
#: Fecha fija de consulta, dentro de la vigencia.
HOY = date(2026, 11, 16)
#: Fuente larga (URL) del Tablero: no debe llegar a la tarjeta.
FUENTE = "https://www.bancodeoccidente.com.co/documents/d/guest/tasas-personas-bdo"


def _fila(
    producto: str,
    desde: str,
    hasta: str,
    segmento: str | None = None,
    plazo_dias: int | None = None,
) -> FilaTasa:
    """Construye una fila de la tabla Gold de prueba.

    Args:
        producto: clave canónica del producto.
        desde: tasa E.A. mínima.
        hasta: tasa E.A. máxima.
        segmento: segmento del Tablero, si aplica.
        plazo_dias: plazo del CDT en días, si aplica.

    Returns:
        La fila lista para escribir.
    """
    return FilaTasa(
        producto=producto,
        segmento=segmento,
        tipo_tasa="fija",
        plazo_dias=plazo_dias,
        tasa_ea_desde=Decimal(desde),
        tasa_ea_hasta=Decimal(hasta),
        vigencia_desde=VIGENCIA_DESDE,
        vigencia_hasta=VIGENCIA_HASTA,
        fuente=FUENTE,
        sha256_pdf="0" * 64,
        fecha_extraccion=VIGENCIA_DESDE,
    )


@pytest.fixture()
def raiz(tmp_path: Path) -> Path:
    """Tabla Gold temporal con tasas de crédito, ahorro y CDT."""
    filas = [
        _fila("libre_inversion", "0.2056", "0.2817"),
        _fila("compra_cartera", "0.1746", "0.2817"),
        _fila("libranza", "0.1539", "0.2431", "Libre inversión"),
        _fila("vivienda", "0.1517", "0.1854", "Crédito hipotecario"),
        _fila("ahorro", "0.0001", "0.0001", "De 0 a $5.000.000"),
        _fila("ahorro", "0.0010", "0.0010", "De $100.000.001 a $3.000.000.000"),
        _fila("cdt", "0.1100", "0.1100", "$500M- $99 MM", 90),
        _fila("cdt", "0.1205", "0.1205", "$500M- $99 MM", 1080),
    ]
    escribir_tabla(tmp_path / "tasas-personas-2026-11.jsonl", filas)
    return tmp_path


def _credito(
    raiz: Path,
    producto: Literal["libre_inversion", "compra_cartera", "vivienda", "libranza"] = (
        "libre_inversion"
    ),
    *,
    ingreso: int = 4_000_000,
    gastos: int = 1_500_000,
    cuotas: int = 0,
    monto: int = 15_000_000,
    plazo: int = 48,
    vinculacion: Literal["empleado", "independiente", "pensionado"] = "empleado",
    trasladar: int | None = None,
) -> ResultadoDiagnostico:
    """Corre el motor real para un crédito con datos inventados.

    Args:
        raiz: tabla Gold de prueba.
        producto: producto de crédito.
        ingreso: ingreso mensual.
        gastos: gastos mensuales.
        cuotas: cuotas de deudas actuales.
        monto: monto del crédito.
        plazo: plazo en meses.
        vinculacion: forma de recibir ingresos.
        trasladar: cuota que se traslada en compra de cartera.

    Returns:
        El resultado del motor.
    """
    entrada = EntradaDiagnostico(
        producto=producto,
        vinculacion=vinculacion,
        ingreso_mensual=Decimal(ingreso),
        gastos_mensuales=Decimal(gastos),
        cuotas_deudas=Decimal(cuotas),
        cuota_trasladar=Decimal(trasladar) if trasladar is not None else None,
        monto_credito=Decimal(monto),
        plazo_meses=plazo,
    )
    return calcular(entrada, hoy=HOY, raiz=raiz)


def _ahorro(raiz: Path, *, ingreso: int, gastos: int) -> ResultadoDiagnostico:
    """Corre el motor real para un ahorro con datos inventados.

    Args:
        raiz: tabla Gold de prueba.
        ingreso: ingreso mensual.
        gastos: gastos mensuales.

    Returns:
        El resultado del motor.
    """
    entrada = EntradaDiagnostico(
        producto="ahorro",
        vinculacion="empleado",
        ingreso_mensual=Decimal(ingreso),
        gastos_mensuales=Decimal(gastos),
        cuotas_deudas=Decimal(0),
    )
    return calcular(entrada, hoy=HOY, raiz=raiz)


def _es_png_cuadrado(contenido: bytes) -> bool:
    """Comprueba que los bytes sean un PNG de 1080 × 1080 y de menos de 1 MB.

    Args:
        contenido: bytes de la tarjeta.

    Returns:
        True si cumple.
    """
    with Image.open(io.BytesIO(contenido)) as img:
        return img.format == "PNG" and img.size == (1080, 1080) and len(contenido) < PESO_MAXIMO


def test_credito_verde_da_tarjeta_de_diagnostico(raiz: Path) -> None:
    """Un crédito verde usa la cuota, el semáforo y la tasa máxima del motor."""
    resultado = _credito(raiz)
    datos = datos_tarjeta(resultado)

    assert isinstance(datos, DatosDiagnostico)
    assert resultado.cuota_mensual is not None and resultado.tasa_mensual is not None
    assert datos.semaforo == resultado.semaforo == "verde"
    assert datos.producto == "Libre inversión"
    assert datos.monto == Decimal(15_000_000)
    assert datos.plazo_meses == 48
    assert datos.cuota_min == resultado.cuota_mensual.desde
    assert datos.cuota_max == resultado.cuota_mensual.hasta
    assert datos.tasa_mensual_pct == (resultado.tasa_mensual.hasta * 100).quantize(Decimal("0.01"))
    assert datos.tasa_vigencia == "nov. 2026"
    assert datos.tasa_fuente == "Tasas publicadas por el Banco de Occidente"
    assert "cabe con margen" in datos.razon
    assert datos.ahorro_mensual is None


def test_la_fuente_se_dice_para_la_persona_y_el_texto_cita_el_pdf(raiz: Path) -> None:
    """La tarjeta dice quién publica la tasa y el texto lleva el enlace al PDF."""
    resultado = _credito(raiz)
    datos = datos_diagnostico(resultado)
    _, texto = tarjeta_y_texto(resultado)

    assert resultado.fuente_tasa == FUENTE
    assert datos.tasa_fuente == "Tasas publicadas por el Banco de Occidente"
    assert datos.tasa_enlace == FUENTE
    assert "Tasas publicadas por el Banco de Occidente, nov. 2026" in texto
    assert FUENTE in texto
    assert "Tablero" not in texto


def test_el_ahorro_tambien_cita_el_pdf(raiz: Path) -> None:
    """La tarjeta de ahorro lleva la misma fuente y el enlace en el texto."""
    _, texto = tarjeta_y_texto(_ahorro(raiz, ingreso=3_000_000, gastos=1_500_000))

    assert "Tasas publicadas por el Banco de Occidente" in texto
    assert FUENTE in texto


def test_amarillo_y_rojo_explican_el_color(raiz: Path) -> None:
    """La razón corta cambia con el color y cita el porcentaje del ingreso."""
    amarillo = datos_diagnostico(
        _credito(raiz, ingreso=4_000_000, cuotas=750_000, monto=15_000_000, plazo=36)
    )
    rojo = datos_diagnostico(
        _credito(raiz, ingreso=2_500_000, gastos=1_500_000, cuotas=750_000, monto=35_000_000)
    )

    assert amarillo.semaforo == "amarillo"
    assert "cabe, pero justo" in amarillo.razon
    assert "%" in amarillo.razon
    assert rojo.semaforo == "rojo"
    assert "cabe" in rojo.razon  # «no cabe» (sin margen) o «aprieta demasiado»


def test_vivienda_sobre_el_30_explica_el_tope(raiz: Path) -> None:
    """La alerta de vivienda manda sobre la frase del semáforo."""
    datos = datos_diagnostico(
        _credito(
            raiz,
            "vivienda",
            ingreso=10_000_000,
            gastos=4_000_000,
            monto=220_000_000,
            plazo=240,
        )
    )

    assert datos.semaforo == "rojo"
    assert datos.razon == FRASE_VIVIENDA


def test_compra_de_cartera_lleva_el_ahorro_mensual(raiz: Path) -> None:
    """Si el traslado baja la cuota, la tarjeta muestra cuánto se ahorra."""
    resultado = _credito(
        raiz,
        "compra_cartera",
        cuotas=1_500_000,
        trasladar=1_500_000,
        monto=35_000_000,
        plazo=60,
    )
    datos = datos_diagnostico(resultado)
    _, texto = tarjeta_y_texto(resultado)

    assert datos.ahorro_mensual == resultado.ahorro_mensual_estimado
    assert datos.ahorro_mensual is not None and datos.ahorro_mensual > 0
    assert pesos(datos.ahorro_mensual) in texto


def test_compra_de_cartera_sin_ahorro_no_lo_muestra(raiz: Path) -> None:
    """Si el traslado no baja la cuota, no se muestra un ahorro negativo."""
    resultado = _credito(
        raiz,
        "compra_cartera",
        cuotas=200_000,
        trasladar=200_000,
        monto=35_000_000,
        plazo=60,
    )

    assert resultado.ahorro_mensual_estimado is not None
    assert resultado.ahorro_mensual_estimado <= 0
    assert datos_diagnostico(resultado).ahorro_mensual is None


def test_ahorro_da_tarjeta_sin_semaforo(raiz: Path) -> None:
    """El ahorro usa la capacidad y hasta tres tasas de captación."""
    resultado = _ahorro(raiz, ingreso=3_000_000, gastos=1_500_000)
    datos = datos_tarjeta(resultado)

    assert isinstance(datos, DatosAhorro)
    assert datos.capacidad_ahorro == resultado.capacidad_pago
    assert [tasa.etiqueta for tasa in datos.tasas][0] == "Cuenta de ahorros"
    assert any(tasa.etiqueta.startswith("CDT") for tasa in datos.tasas)
    assert all(len(tasa.etiqueta) <= 30 for tasa in datos.tasas)
    assert datos.tasa_vigencia == "nov. 2026"


def test_ahorro_sin_margen_lo_dice(raiz: Path) -> None:
    """Con capacidad cero la frase invita a liberar margen primero."""
    datos = datos_ahorro(_ahorro(raiz, ingreso=1_500_000, gastos=1_500_000))

    assert datos.capacidad_ahorro == 0
    assert datos.razon == FRASE_AHORRO_SIN_MARGEN


def test_libranza_de_independiente_no_aplica(raiz: Path) -> None:
    """La libranza de un independiente da la tarjeta «no aplica»."""
    resultado = _credito(raiz, "libranza", vinculacion="independiente")
    datos = datos_tarjeta(resultado)

    assert isinstance(datos, DatosNoAplica)
    assert datos.producto == "Libranza"
    assert datos.semaforo is None
    assert "convenio" in datos.razon
    assert "libre inversión" in datos.alternativa


def test_capacidad_negativa_no_aplica(tmp_path: Path) -> None:
    """Sin capacidad no se simula: tarjeta «no aplica» y no se lee la tasa."""
    resultado = _credito(tmp_path / "vacia", ingreso=2_000_000, gastos=1_200_000, cuotas=1_000_000)
    datos = datos_tarjeta(resultado)

    assert isinstance(datos, DatosNoAplica)
    assert datos.semaforo == "rojo"
    assert "superan tu ingreso" in datos.razon
    assert "Ordena primero" in datos.alternativa


def test_un_resultado_sin_cuota_ni_alerta_no_tiene_tarjeta(raiz: Path) -> None:
    """Un crédito sin cuota y sin alerta conocida se rechaza con `SinTarjeta`."""
    resultado = _credito(raiz).model_copy(update={"cuota_mensual": None})

    with pytest.raises(SinTarjeta):
        datos_tarjeta(resultado)
    with pytest.raises(SinTarjeta):
        datos_no_aplica(resultado)


def test_vigencia_corta() -> None:
    """La vigencia se escribe como mes y año, y avisa si está vencida."""
    assert vigencia_corta(date(2026, 11, 30)) == "nov. 2026"
    assert vigencia_corta(date(2026, 12, 31), vencida=True) == "dic. 2026, vencida"
    assert vigencia_corta(None) == "sin vigencia"


def test_tasa_vencida_se_marca_en_la_tarjeta(raiz: Path) -> None:
    """Si la tabla ya no cubre hoy, la tarjeta dice «vencida»."""
    entrada = _credito(raiz).entrada
    resultado = calcular(entrada, hoy=date(2026, 12, 15), raiz=raiz)

    assert "vigencia_vencida" in resultado.alertas
    assert datos_diagnostico(resultado).tasa_vigencia == "nov. 2026, vencida"


@pytest.mark.parametrize(
    "caso",
    ["verde", "cartera", "ahorro", "ahorro_cero", "libranza", "vivienda"],
)
def test_tarjeta_y_texto_dan_png_y_texto_con_aviso(caso: str, raiz: Path) -> None:
    """Cada caso produce un PNG válido y un texto con el aviso académico."""
    resultado = {
        "verde": lambda: _credito(raiz),
        "cartera": lambda: _credito(
            raiz, "compra_cartera", cuotas=1_500_000, trasladar=1_500_000, monto=35_000_000
        ),
        "ahorro": lambda: _ahorro(raiz, ingreso=3_000_000, gastos=1_500_000),
        "ahorro_cero": lambda: _ahorro(raiz, ingreso=1_500_000, gastos=1_500_000),
        "libranza": lambda: _credito(raiz, "libranza", vinculacion="independiente"),
        "vivienda": lambda: _credito(
            raiz, "vivienda", ingreso=10_000_000, gastos=4_000_000, monto=220_000_000, plazo=240
        ),
    }[caso]()
    png, texto = tarjeta_y_texto(resultado)

    assert _es_png_cuadrado(png)
    assert AVISO in texto


def _comparacion(raiz: Path, plazo_nuevo: int) -> ComparacionEscenario:
    """Arma un «¿Y si…?» de plazo con dos corridas del motor real.

    Args:
        raiz: tabla Gold de prueba.
        plazo_nuevo: plazo del escenario.

    Returns:
        La comparación entre el plazo 36 y el nuevo.
    """
    fotos = []
    for plazo in (36, plazo_nuevo):
        r = _credito(raiz, cuotas=750_000, plazo=plazo)
        assert r.cuota_mensual is not None and r.semaforo is not None
        assert r.razon_endeudamiento is not None
        fotos.append(
            FotoResultado(
                cuota_mensual=r.cuota_mensual,
                semaforo=r.semaforo,
                razon_endeudamiento=r.razon_endeudamiento,
                capacidad_pago=r.capacidad_pago,
            )
        )
    return ComparacionEscenario(
        thread_original="hilo-original",
        thread_escenario="hilo-escenario-1",
        cambio=CambioEscenario(campo="plazo_meses", valor=Decimal(plazo_nuevo)),
        original=fotos[0],
        escenario=fotos[1],
        tendencia="mejora",
        mensaje="(no se usa en la tarjeta)",
    )


def test_escenario_de_plazo_mas_largo(raiz: Path) -> None:
    """Un plazo más largo baja la cuota y la nota lo explica."""
    comparacion = _comparacion(raiz, 60)
    datos = datos_escenario(comparacion, plazo_meses=36)
    png, texto = escenario_y_texto(comparacion, plazo_meses=36)

    assert datos.pregunta == "¿Y si lo pagas en 60 meses?"
    assert datos.antes.plazo_meses == 36
    assert datos.despues.plazo_meses == 60
    assert datos.despues.cuota_max < datos.antes.cuota_max
    assert datos.nota.startswith("Pagas menos al mes")
    assert "original no cambió" in datos.nota
    assert _es_png_cuadrado(png)
    assert "60 meses" in texto


def test_escenario_de_monto_conserva_el_plazo(raiz: Path) -> None:
    """Si cambia el monto, los dos lados llevan el plazo original."""
    base = _comparacion(raiz, 36)
    comparacion = base.model_copy(
        update={
            "cambio": CambioEscenario(campo="monto_credito", valor=Decimal(10_000_000)),
            "tendencia": "igual",
        }
    )
    datos = datos_escenario(comparacion, plazo_meses=36)

    assert datos.pregunta == "¿Y si pides $10.000.000?"
    assert datos.antes.plazo_meses == datos.despues.plazo_meses == 36
    assert datos.nota.startswith("Tu situación queda parecida.")
