"""Pruebas de la voz y la pantalla de la escena: las cifras se leen en pesos.

La pantalla conserva el formato colombiano en los subtítulos y traduce solo el
texto que va a la voz con ``paraVoz`` (``app/web/escena/voz_cifras.js``). Las
etiquetas cortas de la entrevista se expanden a cifras completas para la escena
con ``paraPantalla`` (``app/web/escena/pantalla_cifras.js``). Las pruebas
ejecutan esas funciones puras con Node, si está instalado, y comprueban que
``escena.js`` las llama en el punto donde pinta el subtítulo y donde entrega el
texto a la voz.
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

TEXTOS_VOZ = (
    "$28.000.000",
    "$823.104",
    "$2.000.000",
    "$1.000.000",
    "$1.500.000",
    "$59.636 – $66.400",
    "$20 a $50 millones",
    "$3 a $5 millones",
    "$1 a $2 millones",
    "$20 millones",
    "Menos de $500 mil",
    "$1 millón",
    "Más de $50 millones",
    "Entre $500 mil y $5 millones",
    "28,17 %",
    "791,61 % E.A.",
    "2,09 % M.V.",
    "texto *en negrita* y _cursiva_",
    "36 meses y 4 turnos",
    "mira https://ejemplo.com/pagina ahora",
)


def _leer(nombre: str) -> str:
    """Lee un archivo de la pantalla de la escena."""
    return (ESCENA / nombre).read_text(encoding="utf-8")


def _ejecutar(modulo: str, funcion: str, texto: str) -> str:
    """Ejecuta una función pura del módulo de cifras con Node."""
    assert NODE
    url = (ESCENA / modulo).as_uri()
    programa = (
        f"import {{ {funcion} }} from {json.dumps(url)};\n"
        f"console.log(JSON.stringify({funcion}({json.dumps(texto)})));\n"
    )
    salida = subprocess.run(
        [NODE, "--input-type=module", "-e", programa],
        capture_output=True,
        encoding="utf-8",
        timeout=30,
        check=True,
    )
    return json.loads(salida.stdout)


def _para_voz(texto: str) -> str:
    """Ejecuta ``paraVoz`` con Node y devuelve el texto para la voz."""
    return _ejecutar("voz_cifras.js", "paraVoz", texto)


def _para_pantalla(texto: str) -> str:
    """Ejecuta ``paraPantalla`` con Node y devuelve el texto para la escena."""
    return _ejecutar("pantalla_cifras.js", "paraPantalla", texto)


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


def test_el_modulo_de_pantalla_se_sirve_y_no_toca_el_dom() -> None:
    """pantalla_cifras.js se sirve, no usa innerHTML ni enlaces externos."""
    app = FastAPI()
    app.mount("/", StaticFiles(directory=WEB, html=True), name="web")
    respuesta = TestClient(app).get("/escena/pantalla_cifras.js")
    assert respuesta.status_code == 200
    assert "export function paraPantalla" in respuesta.text
    codigo = _leer("pantalla_cifras.js")
    assert "innerHTML" not in codigo
    assert "document." not in codigo
    assert "https://" not in codigo


def test_escena_js_pinta_las_cifras_completas_y_llama_a_para_voz() -> None:
    """El subtítulo usa paraPantalla; la conversión a voz sigue en decirComo."""
    codigo = _leer("escena.js")
    assert 'import { paraVoz } from "./voz_cifras.js";' in codigo
    assert 'import { paraPantalla } from "./pantalla_cifras.js";' in codigo
    assert "decirComo(turno.personaje, paraVoz(turno.texto)" in codigo
    assert "subtitulo.textContent = paraPantalla(turno.subtitulo || turno.texto);" in codigo
    assert 'porId("escena-texto").textContent = paraPantalla(turno.texto);' in codigo


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
        ("$20 a $50 millones", "de veinte a cincuenta millones de pesos"),
        ("$3 a $5 millones", "de tres a cinco millones de pesos"),
        ("$1 a $2 millones", "de uno a dos millones de pesos"),
        ("$20 millones", "veinte millones de pesos"),
        ("Menos de $500 mil", "Menos de quinientos mil pesos"),
        ("$1 millón", "un millón de pesos"),
        ("Más de $50 millones", "Más de cincuenta millones de pesos"),
        (
            "Entre $500 mil y $5 millones",
            "Entre quinientos mil pesos y cinco millones de pesos",
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


@requiere_node
def test_para_voz_nunca_deja_dolares() -> None:
    """Ningún texto de prueba deja «$» ni «dólar» en la salida para la voz."""
    for texto in TEXTOS_VOZ:
        salida = _para_voz(texto)
        assert "$" not in salida, f"«{texto}» dejó un «$»: {salida!r}"
        assert "dólar" not in salida.lower(), f"«{texto}» dijo dólares: {salida!r}"
        assert "dolar" not in salida.lower(), f"«{texto}» dijo dolares: {salida!r}"


@pytest.mark.parametrize(
    ("texto", "esperado"),
    [
        ("$20 a $50 millones", "$20.000.000 a $50.000.000"),
        ("$3 a $5 millones", "$3.000.000 a $5.000.000"),
        ("$1 a $2 millones", "$1.000.000 a $2.000.000"),
        ("$20 millones", "$20.000.000"),
        ("Menos de $500 mil", "Menos de $500.000"),
        ("$1 millón", "$1.000.000"),
        ("Más de $50 millones", "Más de $50.000.000"),
        ("Entre $500 mil y $5 millones", "Entre $500.000 y $5.000.000"),
        ("$28.000.000", "$28.000.000"),
        ("$59.636 – $66.400", "$59.636 – $66.400"),
        ("36 meses y 4 turnos", "36 meses y 4 turnos"),
    ],
)
@requiere_node
def test_para_pantalla_expande_las_cifras_completas(texto: str, esperado: str) -> None:
    """Las etiquetas cortas se ven completas en la escena, sin tocar WhatsApp."""
    assert _para_pantalla(texto) == esperado
