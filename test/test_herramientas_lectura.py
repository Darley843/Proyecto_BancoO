"""Pruebas de las herramientas de lectura y cálculo del agente `pana`."""

from __future__ import annotations

from decimal import Decimal

import pytest

from banco_occidente_corpus.herramientas import lectura

RESPUESTAS = [
    "objetivo.libre_inversion",
    "vinculacion.empleado",
    "ingresos.DE_3M_A_5M",
    "gastos.DE_1M_A_2M",
    "cuotas.NINGUNA",
    "monto.DE_5M_A_10M",
    "plazo.36",
]


def test_consultar_tasa_lee_el_tablero() -> None:
    """La tasa vigente se devuelve con su fuente y su vigencia."""
    salida = lectura.consultar_tasa("libre inversión")
    assert salida.ok
    assert salida.datos["producto"] == "libre_inversion"
    assert salida.datos["resumen"]["fuente"]


def test_verificar_usura_compara_contra_el_limite_certificado() -> None:
    """Una tasa por encima de la usura se marca con su exceso en puntos."""
    salida = lectura.verificar_usura(0.35)
    assert salida.ok
    assert salida.datos["excede"] is True
    assert salida.datos["exceso_puntos"] == 6.66
    assert salida.datos["fuente"].startswith("https://")


def test_calcular_prestamo_gota_no_usa_modelo() -> None:
    """El gota a gota sale de la aritmética de la escena."""
    salida = lectura.calcular_prestamo_gota(1_000_000)
    assert salida.ok
    assert Decimal(str(salida.datos["interes_mensual"])) == Decimal("200000")
    assert Decimal(str(salida.datos["cuota_diaria"])) == Decimal("40000")
    assert "20 % mensual" in str(salida.datos["resumen"])


def test_diagnosticar_capacidad_devuelve_el_resultado_del_motor() -> None:
    """El diagnóstico se arma con las respuestas de la entrevista."""
    salida = lectura.diagnosticar_capacidad(RESPUESTAS)
    assert salida.ok
    resultado = salida.datos["resultado"]
    assert resultado["entrada"]["producto"] == "libre_inversion"
    assert resultado["semaforo"] in {"verde", "amarillo", "rojo"}


def test_comparar_escenario_no_modifica_el_original() -> None:
    """El «¿Y si…?» devuelve su tendencia y el escenario separado."""
    salida = lectura.comparar_escenario(RESPUESTAS, "plazo_meses", 60)
    assert salida.ok
    comparacion = salida.datos["comparacion"]
    assert comparacion["tendencia"] in {"mejora", "igual", "empeora"}
    assert comparacion["thread_escenario"].endswith(":esc")


def test_negociar_opcion_sin_modelo_es_determinista(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sin modelo, la mesa se recorre con reglas y termina en máximo 4 turnos."""
    monkeypatch.setenv("SUCURSAL_DEMO", "1")
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    salida = lectura.negociar_opcion(RESPUESTAS)
    assert salida.ok
    assert 1 <= len(salida.datos["turnos"]) <= 4
    assert salida.datos["veredicto"]["veredicto"] in {
        "conforme",
        "con_observaciones",
        "objeta",
    }


def test_generar_ficha_opcion_tiene_texto_equivalente() -> None:
    """La ficha siempre trae su texto, sin depender de la imagen."""
    salida = lectura.generar_ficha_opcion(RESPUESTAS)
    assert salida.ok
    assert "Libre inversión" in str(salida.datos["texto"])
    assert int(salida.datos["png_bytes"]) > 0


def test_responder_sobre_proyecto_cita_la_fuente() -> None:
    """El corpus del proyecto se cita como `ruta#ancla`."""
    salida = lectura.responder_sobre_proyecto("¿cómo hicieron el RAG híbrido?")
    assert salida.ok
    assert int(salida.datos["total"]) >= 1
    fragmento = salida.datos["fragmentos"][0]
    assert "#" in str(fragmento["fuente"])
    assert len(str(fragmento["texto"]).split()) <= 41


def test_buscar_en_documentos_traduce_el_error_del_indice(monkeypatch) -> None:
    """Si la Bóveda no está, la herramienta devuelve un error explicable."""

    def falso(pregunta: str, k: int = 5) -> dict[str, object]:
        return {"error": {"codigo": "indice_ausente", "mensaje": "falta el índice"}}

    monkeypatch.setattr(lectura, "buscar_en_boveda", falso)
    salida = lectura.buscar_en_documentos("requisitos de ahorro")
    assert not salida.ok
    assert salida.error is not None
    assert salida.error.codigo == "indice_ausente"


def test_consultar_tarifas_lee_el_csv_del_tablero() -> None:
    """El Tablero responde con filas exactas y su fuente."""
    salida = lectura.consultar_tarifas("cheque de gerencia", limite=2)
    assert salida.ok
    filas = salida.datos["filas"]
    assert filas
    assert "fuente" in filas[0]


def test_clasificar_y_auditar_son_deterministas() -> None:
    """El Digiturno y el auditor no necesitan modelo."""
    turno = lectura.clasificar_pregunta("¿cuál es la tasa de libre inversión?")
    assert turno.ok
    assert turno.datos["letra"] == "T"

    auditor = lectura.auditar_respuesta("Tu crédito está aprobado y te lo garantizo.")
    assert auditor.ok
    assert auditor.datos["conforme"] is False
    assert auditor.datos["veredicto"] == "objeta"
