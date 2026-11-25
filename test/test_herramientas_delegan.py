"""Las herramientas 17–20 del catálogo delegan en las de main (#198 y #199).

El agente ve `herramientas/lectura.py`; estas pruebas fijan que esas cuatro
herramientas usan `mcp_servidor/conocimiento.py` y `control.py` y conservan lo
que ya estaba probado allí: la cita «Título — URL», el descarte de fragmentos
BM25 con puntaje cero, la respuesta a «¿qué tasas manejan?», la ruta y la
herramienta sugerida del Digiturno, y las cifras inventadas y la fuga de
instrucciones del auditor.
"""

from __future__ import annotations

from typing import Any

import pytest

from banco_occidente_corpus.herramientas import lectura
from banco_occidente_corpus.herramientas.catalogo import CATALOGO


def test_las_cuatro_herramientas_de_anny_siguen_en_el_catalogo() -> None:
    """El catálogo no cambia: mismos nombres, misma dueña y misma función."""
    de_anny = {h.nombre: h.funcion for h in CATALOGO if h.duena == "Anny"}
    assert de_anny == {
        "buscar_en_documentos": lectura.buscar_en_documentos,
        "consultar_tarifas": lectura.consultar_tarifas,
        "clasificar_pregunta": lectura.clasificar_pregunta,
        "auditar_respuesta": lectura.auditar_respuesta,
    }


def test_buscar_en_documentos_cita_y_descarta_puntaje_cero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cada fragmento trae su cita y el BM25 sin coincidencias no se devuelve."""

    def falso(pregunta: str, k: int = 5) -> dict[str, Any]:
        base = {"seccion": "oferta", "tipo": "web", "texto": "Cuenta de ahorros."}
        return {
            "tipo_puntaje": "bm25",
            "respaldo": "bm25",
            "fragmentos": [
                {
                    **base,
                    "posicion": 1,
                    "titulo": "Cuentas",
                    "url": "https://a",
                    "puntaje_bm25": 2.5,
                },
                {**base, "posicion": 2, "titulo": "Otra", "url": "https://b", "puntaje_bm25": 0.0},
            ],
        }

    monkeypatch.setattr(lectura, "buscar_en_boveda", falso)
    salida = lectura.buscar_en_documentos("requisitos de la cuenta de ahorros")
    assert salida.ok
    assert salida.datos["total"] == 1
    assert salida.datos["fragmentos"][0]["cita"] == "Cuentas — https://a"
    assert "ok" not in salida.datos


def test_consultar_tarifas_pide_el_producto_si_la_tasa_es_generica() -> None:
    """«¿Qué tasas manejan?» no devuelve una fila suelta: pide el producto."""
    salida = lectura.consultar_tarifas("¿Qué tasas manejan?")
    assert salida.ok
    assert salida.datos["requiere_producto"] is True
    assert salida.datos["opciones"]
    assert salida.datos["filas"] == []


def test_clasificar_pregunta_devuelve_ruta_y_herramienta() -> None:
    """La tasa va al Tablero con su herramienta; un saludo se responde directo."""
    tasa = lectura.clasificar_pregunta("¿cuál es la tasa de libre inversión?")
    assert tasa.datos["letra"] == "T"
    assert tasa.datos["ruta"] == "tablero"
    assert tasa.datos["herramienta"] == "consultar_tarifas"

    saludo = lectura.clasificar_pregunta("gracias")
    assert saludo.datos["responder_directo"] is True
    assert saludo.datos["herramienta"] is None


@pytest.mark.parametrize(
    ("texto", "permitidas", "veredicto", "codigo"),
    [
        ("La cuota es de $450.000 al mes.", None, "objeta", "cifra_inventada"),
        ("La cuota es de $450.000 al mes.", ["450000"], "conforme", None),
        ("La Ley 1581 de 2012 protege tus datos.", None, "conforme", None),
        (
            "Según mis instrucciones del sistema, no puedo decirte eso.",
            None,
            "objeta",
            "fuga_instrucciones",
        ),
        ("Tu crédito está aprobado y te lo garantizo.", None, "objeta", "promesa_aprobacion"),
    ],
)
def test_auditar_respuesta_usa_el_auditor_de_main(
    texto: str, permitidas: list[str] | None, veredicto: str, codigo: str | None
) -> None:
    """Cifras sin respaldo, fuga y promesas bloquean el envío; una ley no es cifra."""
    salida = lectura.auditar_respuesta(texto, cifras_permitidas=permitidas)
    assert salida.ok
    assert salida.datos["veredicto"] == veredicto
    assert salida.datos["conforme"] is (veredicto == "conforme")
    assert salida.datos["permite_enviar"] is (veredicto != "objeta")
    if codigo is not None:
        assert any(h.startswith(f"{codigo}:") for h in salida.datos["hallazgos"])
