"""Pruebas de la voz de la escena: las cifras se leen en pesos y en palabras.

La pantalla conserva el formato colombiano en los subtítulos y traduce solo el
texto que va a la voz con ``paraVoz`` (``app/web/escena/voz_cifras.js``). Las
pruebas ejecutan esa función pura con Node, si está instalado, y comprueban que
``escena.js`` la llama en el único punto donde entrega el texto a la voz.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.testclient import TestClient

RAIZ = Path(__file__).resolve().parents[1]
WEB = RAIZ / "app" / "web"
ESCENA = WEB / "escena"
NODE = shutil.which("node")


def _leer(nombre: str) -> str:
    """Lee un archivo de la pantalla de la escena."""
    return (ESCENA / nombre).read_text(encoding="utf-8")


def _para_voz(texto: str) -> str:
    """Ejecuta ``paraVoz`` con Node y devuelve el texto para la voz."""
    assert NODE
    url = (ESCENA / "voz_cifras.js").as_uri()
    programa = (
        f"import {{ paraVoz }} from {json.dumps(url)};\n"
        f"console.log(JSON.stringify(paraVoz({json.dumps(texto)})));\n"
    )
    salida = subprocess.run(
        [NODE, "--input-type=module", "-e", programa],
        capture_output=True,
        encoding="utf-8",
        timeout=30,
        check=True,
    )
    return json.loads(salida.stdout)


requiere_node = pytest.mark.skipif(NODE is None, reason="Node no está instalado")


def test_el_modulo_se_sirve_y_no_toca_el_dom() -> None:
    """voz_cifras.js se sirve, no usa innerHTML ni enlaces externos."""
    app = FastAPI()
    app.mount("/", StaticFiles(directory=WEB, html=True), name="web")
    respuesta = TestClient(app).get("/escena/voz_cifras.js")
    assert respuesta.status_code == 200
    assert "export function paraVoz" in respuesta.text
    codigo = _leer("voz_cifras.js")
    assert "innerHTML" not in codigo
    assert "document." not in codigo
    assert "https://" not in codigo


def test_escena_js_llama_a_para_voz_solo_antes_de_la_voz() -> None:
    """El subtítulo no cambia; la conversión va en el argumento de decirComo."""
    codigo = _leer("escena.js")
    assert 'import { paraVoz } from "./voz_cifras.js";' in codigo
    assert "decirComo(turno.personaje, paraVoz(turno.texto)" in codigo
    assert "const texto = turno.subtitulo || turno.texto;" in codigo
    assert 'porId("escena-texto").textContent = turno.texto;' in codigo


@pytest.mark.parametrize(
    ("texto", "esperado"),
    [
        ("$28.000.000", "veintiocho millones de pesos"),
        ("$823.104", "ochocientos veintitrés mil ciento cuatro pesos"),
        ("$2.000.000", "dos millones de pesos"),
        ("$1.000.000", "un millón de pesos"),
        ("$1.500.000", "un millón quinientos mil pesos"),
        (
            "$59.636 – $66.400",
            "entre cincuenta y nueve mil seiscientos treinta y seis y "
            "sesenta y seis mil cuatrocientos pesos",
        ),
        ("28,17 %", "veintiocho coma diecisiete por ciento"),
        ("791,61 % E.A.", "setecientos noventa y uno coma sesenta y uno por ciento efectivo anual"),
        ("2,09 % M.V.", "dos coma cero nueve por ciento mes vencido"),
        ("texto *en negrita* y _cursiva_", "texto en negrita y cursiva"),
        ("36 meses y 4 turnos", "36 meses y 4 turnos"),
        ("mira https://ejemplo.com/pagina ahora", "mira ahora"),
    ],
)
@requiere_node
def test_para_voz_traduce_cifras_y_deja_el_resto(texto: str, esperado: str) -> None:
    """Montos, rangos, porcentajes y marcas de WhatsApp quedan listos para la voz."""
    assert _para_voz(texto) == esperado


@requiere_node
def test_para_voz_conserva_un_monto_sin_formato_de_miles() -> None:
    """Un monto pequeño también se lee en palabras, no como dólares."""
    assert _para_voz("$823") == "ochocientos veintitrés pesos"
