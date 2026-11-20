"""Pruebas de la entrevista del diagnóstico (sin red).

Se usa el TOML versionado (`config/diagnostico.toml`): las preguntas, las
opciones y el orden salen del mismo archivo que lee el motor. Se comprueba que
la entrevista no repite preguntas, que respeta el producto elegido y que
rechaza respuestas fuera de la lista.
"""

from __future__ import annotations

import pytest

from banco_occidente_corpus.diagnostico.entrevista import (
    ID_ASESOR,
    ID_CANCELAR,
    ID_EMPEZAR,
    RespuestaInvalida,
    bloques,
    comando,
    pregunta_pendiente,
    registrar_respuesta,
    titulo_de,
)
from banco_occidente_corpus.diagnostico.motor import cargar_config

CONFIG = cargar_config()


def _respuestas(*ids: str) -> dict[str, str]:
    """Arma respuestas bloque → id usando la clave del propio guion."""
    return {CONFIG.claves.get(ident, ident.split(".", 1)[0]): ident for ident in ids}


def test_la_primera_pregunta_es_el_objetivo() -> None:
    """Sin respuestas, la entrevista pide el objetivo con siete filas."""
    pregunta = pregunta_pendiente({}, config=CONFIG)

    assert pregunta is not None
    assert pregunta.clave == "objetivo"
    assert pregunta.tipo == "lista"
    assert len(pregunta.opciones) == 7
    assert [opcion.id for opcion in pregunta.opciones][0] == "objetivo.libre_inversion"


def test_vinculacion_usa_botones() -> None:
    """Con el objetivo elegido, la vinculación cabe en tres botones."""
    pregunta = pregunta_pendiente(_respuestas("objetivo.libre_inversion"), config=CONFIG)

    assert pregunta is not None
    assert pregunta.clave == "vinculacion"
    assert pregunta.tipo == "botones"


def test_la_entrevista_no_repite_preguntas() -> None:
    """Cada respuesta avanza un bloque y ninguno se vuelve a preguntar."""
    respuestas = _respuestas("objetivo.libre_inversion")
    vistas: list[str] = []

    while (pregunta := pregunta_pendiente(respuestas, config=CONFIG)) is not None:
        vistas.append(pregunta.clave)
        respuestas = registrar_respuesta(
            respuestas,
            pregunta.opciones[0].titulo,
            pregunta.opciones[0].id,
            config=CONFIG,
        )

    assert vistas == ["vinculacion", "ingresos", "gastos", "cuotas", "monto", "plazo"]
    assert respuestas["plazo"].startswith("plazo.")


def test_el_ahorro_no_pregunta_monto_ni_plazo() -> None:
    """El ahorro cierra en cinco bloques y no pide monto ni plazo."""
    respuestas = _respuestas(
        "objetivo.ahorro",
        "vinculacion.empleado",
        "ingresos.DE_3M_A_5M",
        "gastos.DE_1M_A_2M",
        "cuotas.NINGUNA",
    )

    assert pregunta_pendiente(respuestas, config=CONFIG) is None


def test_compra_de_cartera_pregunta_la_cuota_a_trasladar() -> None:
    """La compra de cartera añade el bloque `cuota_trasladar` después de cuotas."""
    respuestas = _respuestas(
        "objetivo.compra_cartera",
        "vinculacion.empleado",
        "ingresos.DE_3M_A_5M",
        "gastos.DE_1M_A_2M",
        "cuotas.DE_1M_A_2M",
    )

    pregunta = pregunta_pendiente(respuestas, config=CONFIG)

    assert pregunta is not None
    assert pregunta.clave == "cuota_trasladar"
    assert "cuota" in pregunta.texto.lower()


def test_vivienda_usa_sus_propios_rangos_de_monto_y_plazo() -> None:
    """Vivienda resuelve `monto_vivienda` y `plazo_vivienda`."""
    respuestas = _respuestas(
        "objetivo.vivienda",
        "vinculacion.pensionado",
        "ingresos.DE_5M_A_8M",
        "gastos.DE_1M_A_2M",
        "cuotas.NINGUNA",
    )

    monto = pregunta_pendiente(respuestas, config=CONFIG)
    assert monto is not None
    assert monto.clave == "monto_vivienda"
    assert [opcion.id for opcion in monto.opciones] == [
        "monto.DE_100M_A_200M",
        "monto.DE_200M_A_350M",
        "monto.MAS_350M",
    ]

    respuestas = registrar_respuesta(respuestas, "", monto.opciones[0].id, config=CONFIG)
    plazo = pregunta_pendiente(respuestas, config=CONFIG)
    assert plazo is not None
    assert plazo.clave == "plazo_vivienda"
    assert [opcion.id for opcion in plazo.opciones] == ["plazo.120", "plazo.180", "plazo.240"]


def test_registrar_acepta_el_id_del_boton() -> None:
    """El id canónico del botón es suficiente para responder."""
    nuevas = registrar_respuesta({}, "Libre inversión", "objetivo.libre_inversion", config=CONFIG)

    assert nuevas == {"objetivo": "objetivo.libre_inversion"}


def test_registrar_acepta_el_titulo_del_rango() -> None:
    """Escribir el título del rango equivale a tocar la fila."""
    respuestas = _respuestas("objetivo.libre_inversion", "vinculacion.empleado")

    nuevas = registrar_respuesta(respuestas, "menos de 2 millones", config=CONFIG)

    assert nuevas["ingresos"] == "ingresos.MENOS_2M"


def test_respuesta_fuera_de_lista_se_rechaza() -> None:
    """Un texto que no es opción no avanza la entrevista."""
    with pytest.raises(RespuestaInvalida):
        registrar_respuesta({}, "quién sabe", config=CONFIG)


def test_traslado_mayor_que_las_cuotas_se_rechaza() -> None:
    """La cuota a trasladar no puede superar las cuotas actuales."""
    respuestas = _respuestas(
        "objetivo.compra_cartera",
        "vinculacion.empleado",
        "ingresos.DE_3M_A_5M",
        "gastos.DE_1M_A_2M",
        "cuotas.MENOS_500K",
    )

    with pytest.raises(RespuestaInvalida, match="no puede ser mayor"):
        registrar_respuesta(respuestas, "", "cuota_trasladar.MAS_3M", config=CONFIG)


def test_comando_reconoce_botones_y_textos() -> None:
    """Empezar, cancelar y asesor se reconocen por id o por texto."""
    assert comando("Empezar", ID_EMPEZAR) == "empezar"
    assert comando("Ahora no", ID_CANCELAR) == "cancelar"
    assert comando("Contactar", ID_ASESOR) == "asesor"
    assert comando("cancelar") == "cancelar"
    assert comando("prefiero un asesor") == "asesor"
    assert comando("4 millones") is None


def test_bloques_depende_del_producto() -> None:
    """El guion cambia con el producto elegido."""
    assert bloques(None) == ("objetivo", "vinculacion", "ingresos", "gastos", "cuotas")
    assert "cuota_trasladar" in bloques("compra_cartera")
    assert "monto" not in bloques("ahorro")
    assert "plazo" not in bloques("ahorro")


def test_titulo_de_devuelve_el_texto_visible() -> None:
    """La confirmación usa el título corto, no el id."""
    assert titulo_de("objetivo.ahorro", config=CONFIG) == "Solo ahorrar"
    assert titulo_de("vinculacion.independiente", config=CONFIG) == "Independiente"
    assert titulo_de("ingresos.MENOS_2M", config=CONFIG) == "Menos de $2 millones"
