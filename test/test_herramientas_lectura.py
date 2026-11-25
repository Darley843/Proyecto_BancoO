"""Pruebas de las herramientas de lectura y cálculo del agente `pana`."""

from __future__ import annotations

import json
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
    """El diagnóstico se arma con las respuestas y el monto exacto del invitado."""
    salida = lectura.diagnosticar_capacidad(RESPUESTAS, monto=7_500_000)
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


def test_calcular_prestamo_gota_trae_cifras_legibles() -> None:
    """Con $2.000.000 la tasa E.A. se copia como 791,61 % y no como 7,916 %."""
    salida = lectura.calcular_prestamo_gota(2_000_000)
    assert salida.ok
    datos = salida.datos
    assert datos["tasa_ea_legible"] == "791,61 % E.A."
    assert datos["cuota_diaria_legible"] == "$80.000"
    assert datos["total_pagado_horizonte_legible"] == "$16.400.000"
    assert "791,61 % E.A." in datos["cifras_permitidas"]
    assert datos["metadatos"]["version_formula"] == "gota-v1"
    texto = json.dumps(
        {clave: valor for clave, valor in datos.items() if clave != "metadatos"},
        ensure_ascii=False,
    )
    assert "gota-v1" not in texto


def test_comparar_gota_banco_trae_las_tasas_legibles() -> None:
    """La comparación entrega la tasa del gota y la del banco sin ambigüedad."""
    salida = lectura.comparar_gota_banco(2_000_000, RESPUESTAS)
    assert salida.ok
    comparacion = salida.datos["comparacion"]
    assert comparacion["tasa_ea_gota_legible"] == "791,61 % E.A."
    assert comparacion["tasa_ea_banco_legible"].endswith("% E.A.")
    assert comparacion["usura_ea_legible"] == "28,34 % E.A."
    assert "$16.400.000" in salida.datos["cifras_permitidas"]


def test_consultar_tasa_y_simular_cuota_traen_texto_legible() -> None:
    """Los rangos de tasa y cuota llevan su `valor_legible` y sus permitidas."""
    tasa = lectura.consultar_tasa("libre inversión")
    assert tasa.ok
    assert tasa.datos["resumen"]["tasa_ea_desde_legible"].endswith("% E.A.")
    assert tasa.datos["resumen"]["valor_legible"].endswith("% E.A.")
    assert any("% E.A." in cifra for cifra in tasa.datos["cifras_permitidas"])

    cuota = lectura.simular_cuota("libre inversión", 15_000_000, 48)
    assert cuota.ok
    assert cuota.datos["tasa_ea"]["valor_legible"].endswith("% E.A.")
    assert cuota.datos["tasa_mensual"]["valor_legible"].endswith("% mensual")
    assert cuota.datos["cuota_mensual"]["valor_legible"].startswith("$")
    assert "version_formula" not in cuota.datos
    assert cuota.datos["metadatos"]["version_formula"]


def test_verificar_usura_trae_las_tasas_legibles() -> None:
    """La usura y su exceso se leen en la misma escala que la tasa de entrada."""
    salida = lectura.verificar_usura(7.9161)
    assert salida.ok
    assert salida.datos["tasa_ea_legible"] == "791,61 % E.A."
    assert salida.datos["usura_ea_legible"] == "28,34 % E.A."
    assert salida.datos["exceso_puntos_legible"] == "763,27 puntos porcentuales"


def test_auditar_respuesta_objeta_la_tasa_mal_escalada() -> None:
    """«7.916% E.A.» no está respaldado por la cifra legible de la herramienta."""
    salida = lectura.auditar_respuesta(
        "Don Gota cobra 7.916% E.A.",
        cifras_permitidas=["791,61 % E.A."],
    )
    assert salida.ok
    assert salida.datos["veredicto"] == "objeta"
    assert any("cifra_inventada" in hallazgo for hallazgo in salida.datos["hallazgos"])


def test_auditar_respuesta_objeta_un_monto_fuera_de_las_permitidas() -> None:
    """«$2.400.000 al mes» se objeta cuando solo está permitido el pago diario."""
    salida = lectura.auditar_respuesta(
        "Pagarías $2.400.000 al mes solo para no crecer la deuda.",
        cifras_permitidas=["$80.000"],
    )
    assert salida.ok
    assert salida.datos["veredicto"] == "objeta"
    assert any("cifra_inventada" in hallazgo for hallazgo in salida.datos["hallazgos"])


def test_auditar_respuesta_acepta_las_cifras_legibles_de_la_herramienta() -> None:
    """La respuesta que copia `valor_legible` queda conforme."""
    calculo = lectura.calcular_prestamo_gota(2_000_000)
    salida = lectura.auditar_respuesta(
        "Don Gota cobra 791,61 % E.A. y la cuota diaria es $80.000.",
        cifras_permitidas=calculo.datos["cifras_permitidas"],
    )
    assert salida.ok
    assert salida.datos["veredicto"] == "conforme"
