"""Pruebas del motor del diagnóstico: contratos, entrevista y personas.

El motor real (`diagnostico.motor`) se prueba contra una tabla Gold temporal con
las tasas de la vigencia 2026-11 y contra las personas sintéticas versionadas en
`data/evaluacion/personas_sinteticas.json`. Así la corrida es determinista, no
depende de la red ni de la fecha en que se ejecute `make check`, y cubre el
camino completo de la entrevista: ids canónicos → `entrada_desde_respuestas` →
`calcular`.
"""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from banco_occidente_corpus.canal.contratos import EntradaDiagnostico, ResultadoDiagnostico
from banco_occidente_corpus.config import PROJECT_ROOT
from banco_occidente_corpus.diagnostico.motor import (
    calcular,
    cargar_config,
    entrada_desde_respuestas,
)
from banco_occidente_corpus.tablero.tasas import (
    FilaTasa,
    TasaNoDisponible,
    escribir_tabla,
)

#: Personas sintéticas del Taller, alineadas con docs/DIAGNOSTICO.md.
RUTA_PERSONAS = PROJECT_ROOT / "data" / "evaluacion" / "personas_sinteticas.json"
#: Primer día de la vigencia de la tabla de prueba.
VIGENCIA_DESDE = date(2026, 11, 1)
#: Último día de la vigencia de la tabla de prueba.
VIGENCIA_HASTA = date(2026, 11, 30)
#: Fecha de consulta fija: dentro de la vigencia y sin depender del día de la corrida.
FECHA_CONSULTA = date(2026, 11, 16)
#: Huella del PDF de tasas de la vigencia.

SHA_EJEMPLO = "989be43a0ed19eb33e2057cd01c1ae612b6f15544eaaf41af6348846a6ff1b7f"
#: URL de la fuente de las tasas.
FUENTE = "https://www.bancodeoccidente.com.co/documents/d/guest/tasas-personas-bdo"
#: Prefijos que identifican una respuesta de la entrevista.
PREFIJOS = frozenset(
    {"objetivo", "vinculacion", "ingresos", "gastos", "cuotas", "cuota_trasladar", "monto", "plazo"}
)


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
        desde: tasa E.A. mínima publicada.
        hasta: tasa E.A. máxima publicada.
        segmento: segmento del Tablero, si el producto tiene varios.
        plazo_dias: plazo del CDT en días, si el producto lo publica.

    Returns:
        La fila lista para escribir la tabla.
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
        sha256_pdf=SHA_EJEMPLO,
        fecha_extraccion=VIGENCIA_DESDE,
    )


@pytest.fixture()
def raiz_tasas(tmp_path: Path) -> Path:
    """Crea una tabla Gold temporal con las tasas de la vigencia 2026-11."""
    filas = [
        _fila("libre_inversion", "0.2056", "0.2817"),
        _fila("compra_cartera", "0.1746", "0.2817"),
        _fila("libranza", "0.1539", "0.2431", "Libre inversión"),
        _fila("libranza", "0.1471", "0.2343", "Compra de cartera"),
        _fila("vivienda", "0.1517", "0.1854", "Crédito hipotecario"),
        _fila("ahorro", "0.0001", "0.0001", "De 0 a $5.000.000"),
        _fila("ahorro", "0.0010", "0.0010", "De $100.000.001 a $3.000.000.000"),
        _fila("cdt", "0.0005", "0.0005", "$500M- $99 MM", 30),
        _fila("cdt", "0.1100", "0.1100", "$500M- $99 MM", 90),
        _fila("cdt", "0.1205", "0.1205", "$500M- $99 MM", 1080),
        _fila("cdt", "0.1215", "0.1215", "$500 MM - 10.000 MM", 1080),
    ]
    escribir_tabla(tmp_path / "tasas-personas-2026-11.jsonl", filas)
    return tmp_path


def _personas() -> dict[str, dict[str, Any]]:
    """Carga las personas sintéticas indexadas por su id.

    Returns:
        El diccionario persona por id.
    """
    datos = json.loads(RUTA_PERSONAS.read_text(encoding="utf-8"))
    return {persona["id"]: persona for persona in datos["personas"]}


def _ids(persona: dict[str, Any]) -> list[str]:
    """Extrae de los turnos los ids canónicos de la entrevista.

    Args:
        persona: persona sintética con su lista de turnos.

    Returns:
        Los ids elegidos, en el orden de la entrevista.
    """
    return [
        str(turno["valor"])
        for turno in persona["turnos"]
        if turno.get("tipo") in {"lista", "boton"}
        and str(turno["valor"]).split(".", 1)[0] in PREFIJOS
    ]


def _diagnostico(ident: str, raiz: Path) -> ResultadoDiagnostico:
    """Corre el camino completo de una persona sintética.

    Args:
        ident: id de la persona en el JSON.
        raiz: tabla Gold de prueba.

    Returns:
        El resultado del motor real para esa persona.
    """
    persona = _personas()[ident]
    entrada = entrada_desde_respuestas(_ids(persona))
    return calcular(entrada, hoy=FECHA_CONSULTA, raiz=raiz)


def test_cargar_config_lee_umbrales_valores_y_aplicabilidad() -> None:
    """El TOML es la fuente de umbrales y de valores de cálculo."""
    config = cargar_config()

    assert config.verde_hasta == Decimal("0.30")
    assert config.amarillo_hasta == Decimal("0.40")
    assert config.umbral_vivienda == Decimal("0.30")
    assert config.valores["ingresos.DE_5M_A_8M"] == Decimal(6_500_000)
    assert config.claves["gastos.DE_2M_A_3M"] == "gastos"
    assert "libre_inversion" in config.aplica_a["monto.DE_10M_A_20M"]


def test_entrada_desde_respuestas_toma_los_valores_del_toml() -> None:
    """El canal envía ids; el motor los traduce a cifras y las declara."""
    entrada = entrada_desde_respuestas(
        {
            "objetivo": "objetivo.libre_inversion",
            "vinculacion": "vinculacion.empleado",
            "ingresos": "ingresos.DE_5M_A_8M",
            "gastos": "gastos.DE_2M_A_3M",
            "cuotas": "cuotas.NINGUNA",
            "monto": "monto.DE_10M_A_20M",
            "plazo": "plazo.48",
        }
    )

    assert entrada.producto == "libre_inversion"
    assert entrada.vinculacion == "empleado"
    assert entrada.ingreso_mensual == Decimal(6_500_000)
    assert entrada.gastos_mensuales == Decimal(2_500_000)
    assert entrada.cuotas_deudas == Decimal(0)
    assert entrada.monto_credito == Decimal(15_000_000)
    assert entrada.plazo_meses == 48
    assert entrada.rango_usado["ingresos"] == "ingresos.DE_5M_A_8M"


def test_entrada_desde_respuestas_acepta_un_iterable_de_ids() -> None:
    """Una lista de ids de la entrevista basta para construir la entrada."""
    entrada = entrada_desde_respuestas(
        [
            "objetivo.ahorro",
            "vinculacion.empleado",
            "ingresos.MENOS_2M",
            "gastos.DE_1M_A_2M",
            "cuotas.NINGUNA",
        ]
    )

    assert entrada.producto == "ahorro"
    assert entrada.monto_credito is None
    assert entrada.plazo_meses is None


@pytest.mark.parametrize(
    ("respuestas", "mensaje"),
    [
        (
            ["vinculacion.empleado", "ingresos.DE_2M_A_3M", "gastos.DE_1M_A_2M", "cuotas.NINGUNA"],
            "objetivo",
        ),
        (
            [
                "objetivo.libre_inversion",
                "ingresos.DE_2M_A_3M",
                "gastos.DE_1M_A_2M",
                "cuotas.NINGUNA",
            ],
            "vinculación",
        ),
        (
            [
                "objetivo.libre_inversion",
                "vinculacion.empleado",
                "gastos.DE_1M_A_2M",
                "cuotas.NINGUNA",
            ],
            "ingresos",
        ),
        (
            [
                "objetivo.libre_inversion",
                "vinculacion.empleado",
                "ingresos.DE_2M_A_3M",
                "gastos.DE_1M_A_2M",
                "cuotas.NINGUNA",
                "monto.DE_10M_A_20M",
            ],
            "plazo",
        ),
        (["objetivo.cdt", "vinculacion.empleado"], "objetivo"),
        (["ingresos.NO_EXISTE"], "no es una opción"),
        (
            [
                "objetivo.vivienda",
                "vinculacion.empleado",
                "ingresos.DE_5M_A_8M",
                "gastos.DE_2M_A_3M",
                "cuotas.NINGUNA",
                "monto.DE_100M_A_200M",
                "plazo.36",
            ],
            "no aplica",
        ),
        (
            [
                "objetivo.ahorro",
                "vinculacion.empleado",
                "ingresos.MENOS_2M",
                "gastos.DE_1M_A_2M",
                "cuotas.NINGUNA",
                "monto.HASTA_5M",
            ],
            "no lleva monto ni plazo",
        ),
    ],
)
def test_entrada_desde_respuestas_rechaza_lo_incompleto(
    respuestas: list[str], mensaje: str
) -> None:
    """Una respuesta faltante, desconocida o incoherente no inventa valores."""
    with pytest.raises(ValueError, match=mensaje):
        entrada_desde_respuestas(respuestas)


def test_laura_verde(raiz_tasas: Path) -> None:
    """Laura: libre inversión que cabe con margen."""
    resultado = _diagnostico("empleada_verde", raiz_tasas)

    assert resultado.semaforo == "verde"
    assert resultado.cuota_mensual is not None
    assert resultado.cuota_mensual.desde <= resultado.cuota_mensual.hasta
    assert resultado.razon_endeudamiento == Decimal("0.0766")
    assert resultado.base_semaforo == "tasa_maxima"
    assert resultado.fuente_tasa == FUENTE
    assert "No es una aprobación" in resultado.aviso


def test_andres_rojo(raiz_tasas: Path) -> None:
    """Andrés: la cuota máxima supera su capacidad de pago."""
    resultado = _diagnostico("independiente_rojo", raiz_tasas)

    assert resultado.semaforo == "rojo"
    assert resultado.margen_despues_cuota is not None
    assert resultado.margen_despues_cuota < 0
    assert resultado.alertas == []
    assert any("margen" in motivo for motivo in resultado.motivos)


def test_jaime_amarillo(raiz_tasas: Path) -> None:
    """Jaime: la libranza entra en el rango amarillo."""
    resultado = _diagnostico("pensionado_amarillo", raiz_tasas)

    assert resultado.semaforo == "amarillo"
    assert resultado.razon_endeudamiento == Decimal("0.3306")
    assert resultado.fuente_tasa == FUENTE


def test_valentina_ahorro_sin_semaforo(raiz_tasas: Path) -> None:
    """Valentina: sin semáforo, con capacidad cero y tasas de captación."""
    resultado = _diagnostico("joven_ahorro", raiz_tasas)

    assert resultado.semaforo is None
    assert resultado.cuota_mensual is None
    assert resultado.tasa_ea is None
    assert resultado.razon_endeudamiento is None
    assert resultado.margen_despues_cuota is None
    assert resultado.capacidad_pago == Decimal(0)
    assert {tasa.producto for tasa in resultado.tasas_captacion} == {"ahorro", "cdt"}


def test_ahorro_de_referencia_es_el_tramo_mas_bajo(raiz_tasas: Path) -> None:
    """El ahorro presenta el tramo que empieza, no el máximo de la envolvente."""
    resultado = _diagnostico("joven_ahorro", raiz_tasas)
    ahorro = next(tasa for tasa in resultado.tasas_captacion if tasa.producto == "ahorro")

    assert ahorro.referencia == "De 0 a $5.000.000"
    assert ahorro.tasa_ea.desde == Decimal("0.0001")
    assert ahorro.tasa_ea.hasta == Decimal("0.0001")
    assert ahorro.rango_completo is not None
    assert ahorro.rango_completo.desde == Decimal("0.0001")
    assert ahorro.rango_completo.hasta == Decimal("0.0010")
    assert any("tramo «De 0 a $5.000.000»" in motivo for motivo in resultado.motivos)


def test_cdt_informa_el_rango_por_plazo_del_monto_minimo(raiz_tasas: Path) -> None:
    """El CDT no publica un solo porcentaje: depende del plazo y del monto."""
    resultado = _diagnostico("joven_ahorro", raiz_tasas)
    cdt = next(tasa for tasa in resultado.tasas_captacion if tasa.producto == "cdt")

    assert cdt.referencia == "De $500 mil a $99 millones"
    assert cdt.tasa_ea.desde == Decimal("0.0005")
    assert cdt.tasa_ea.hasta == Decimal("0.1205")
    assert cdt.rango_completo is not None
    assert cdt.rango_completo.hasta == Decimal("0.1215")
    assert [tramo.etiqueta for tramo in cdt.tramos] == [
        "30 días (1 mes)",
        "90 días (3 meses)",
        "1080 días (3 años)",
    ]
    assert any("depende del plazo y del monto" in motivo for motivo in resultado.motivos)


def test_capacidad_cero_orienta_a_revisar_los_gastos_fijos(raiz_tasas: Path) -> None:
    """Sin capacidad de ahorro la recomendación es revisar los gastos fijos."""
    resultado = _diagnostico("joven_ahorro", raiz_tasas)

    assert resultado.capacidad_pago == Decimal(0)
    assert any("gastos fijos" in recomendacion for recomendacion in resultado.recomendaciones)
    assert all("automatiza" not in recomendacion for recomendacion in resultado.recomendaciones)


def test_vigencia_vencida_en_el_ahorro_alerta_y_lo_explica(tmp_path: Path) -> None:
    """La tasa de ahorro del 4 al 9 de noviembre ya venció el 18 de noviembre."""
    filas = [
        _fila("ahorro", "0.0001", "0.0001", "De 0 a $5.000.000").model_copy(
            update={"vigencia_desde": date(2026, 11, 4), "vigencia_hasta": date(2026, 11, 9)}
        )
    ]
    escribir_tabla(tmp_path / "tasas-personas-2026-11.jsonl", filas)
    entrada = entrada_desde_respuestas(
        [
            "objetivo.ahorro",
            "vinculacion.empleado",
            "ingresos.MENOS_2M",
            "gastos.DE_1M_A_2M",
            "cuotas.NINGUNA",
        ]
    )
    resultado = calcular(entrada, hoy=date(2026, 11, 18), raiz=tmp_path)

    assert resultado.alertas == ["vigencia_vencida"]
    assert any("del 4 al 9 de noviembre de 2026" in motivo for motivo in resultado.motivos)
    assert any("18 de noviembre de 2026" in motivo for motivo in resultado.motivos)


def test_carolina_compra_de_cartera_verde_con_ahorro(raiz_tasas: Path) -> None:
    """Carolina: compra de cartera verde y ahorro mensual de $471.120."""
    resultado = _diagnostico("compra_cartera", raiz_tasas)

    assert resultado.semaforo == "verde"
    assert resultado.capacidad_pago == Decimal("2500000.00")
    assert resultado.ahorro_mensual_estimado == Decimal(471_120)
    assert resultado.cuota_mensual is not None


@pytest.mark.parametrize(
    "ident",
    ["empleada_verde", "independiente_rojo", "pensionado_amarillo", "joven_ahorro"],
)
def test_personas_coinciden_con_el_semaforo_del_json(ident: str, raiz_tasas: Path) -> None:
    """El semáforo esperado del JSON coincide con el motor, sin tocar la regla."""
    persona = _personas()[ident]

    assert _diagnostico(ident, raiz_tasas).semaforo == persona["esperado"]["semaforo"]


def test_libranza_de_independiente_no_aplica(raiz_tasas: Path) -> None:
    """La libranza de un independiente se explica sin simular crédito."""
    entrada = entrada_desde_respuestas(
        [
            "objetivo.libranza",
            "vinculacion.independiente",
            "ingresos.DE_3M_A_5M",
            "gastos.DE_1M_A_2M",
            "cuotas.DE_500K_A_1M",
            "monto.DE_10M_A_20M",
            "plazo.36",
        ]
    )
    resultado = calcular(entrada, hoy=FECHA_CONSULTA, raiz=raiz_tasas)

    assert resultado.semaforo is None
    assert resultado.cuota_mensual is None
    assert resultado.alertas == ["libranza_no_aplica"]
    assert any("convenio" in motivo for motivo in resultado.motivos)


def test_capacidad_negativa_es_rojo_sin_cuota(tmp_path: Path) -> None:
    """Sin capacidad no se consulta la tasa ni se simula una cuota."""
    entrada = EntradaDiagnostico(
        producto="libre_inversion",
        vinculacion="empleado",
        ingreso_mensual=Decimal(2_000_000),
        gastos_mensuales=Decimal(1_200_000),
        cuotas_deudas=Decimal(1_000_000),
        monto_credito=Decimal(10_000_000),
        plazo_meses=36,
    )
    resultado = calcular(entrada, raiz=tmp_path / "vacia")

    assert resultado.semaforo == "rojo"
    assert resultado.cuota_mensual is None
    assert resultado.alertas == ["capacidad_negativa"]
    assert resultado.fuente_tasa is None


def test_vivienda_sobre_el_30_por_ciento_alerta(raiz_tasas: Path) -> None:
    """Vivienda con primera cuota sobre el 30 % del ingreso es rojo y avisa."""
    entrada = EntradaDiagnostico(
        producto="vivienda",
        vinculacion="empleado",
        ingreso_mensual=Decimal(10_000_000),
        gastos_mensuales=Decimal(4_000_000),
        cuotas_deudas=Decimal(0),
        monto_credito=Decimal(220_000_000),
        plazo_meses=240,
    )
    resultado = calcular(entrada, hoy=FECHA_CONSULTA, raiz=raiz_tasas)

    assert resultado.semaforo == "rojo"
    assert resultado.alertas == ["vivienda_30"]


def test_los_umbrales_salen_de_la_configuracion(raiz_tasas: Path) -> None:
    """Un umbral distinto cambia el color del mismo caso."""
    entrada = entrada_desde_respuestas(_ids(_personas()["empleada_verde"]))
    config = cargar_config()

    verde = calcular(entrada, raiz=raiz_tasas, config=config)
    estricto = calcular(
        entrada, raiz=raiz_tasas, config=replace(config, verde_hasta=Decimal("0.05"))
    )

    assert verde.semaforo == "verde"
    assert estricto.semaforo == "amarillo"


def test_tasa_ausente_se_detiene(tmp_path: Path) -> None:
    """Sin tabla Gold el cálculo no inventa la tasa."""
    entrada = entrada_desde_respuestas(_ids(_personas()["empleada_verde"]))

    with pytest.raises(TasaNoDisponible):
        calcular(entrada, raiz=tmp_path / "vacia")


def test_resultado_reproducible_desde_el_json(raiz_tasas: Path) -> None:
    """El resultado guardado se reproduce con sus insumos y su versión."""
    original = _diagnostico("compra_cartera", raiz_tasas)

    recuperado = ResultadoDiagnostico.model_validate_json(original.model_dump_json())
    repetido = calcular(recuperado.entrada, hoy=FECHA_CONSULTA, raiz=raiz_tasas)

    assert recuperado == original
    assert repetido.model_copy(update={"escenario_de": None}) == original
    assert recuperado.entrada.rango_usado["monto"] == "monto.DE_20M_A_50M"


def test_todas_las_personas_tienen_ids_del_guion() -> None:
    """Cada persona usa solo prefijos canónicos de la entrevista."""
    for persona in _personas().values():
        for ident in _ids(persona):
            assert ident.split(".", 1)[0] in PREFIJOS, ident
