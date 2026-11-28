"""Pruebas de la voz y la pantalla de la escena: las cifras se leen en pesos.

La pantalla conserva el formato colombiano en los subtítulos y traduce solo el
texto que va a la voz con ``paraVoz`` (``app/web/escena/voz_cifras.js``). Esa
conversión vive una sola vez en ``app/web/voz.js``, así la escena guionada, la
lista en vivo, Piper y la voz del navegador reciben el mismo texto. Las etiquetas
cortas de la entrevista se expanden a cifras completas para la escena con
``paraPantalla`` (``app/web/escena/pantalla_cifras.js``). Las pruebas ejecutan
esas funciones puras con Node, si está instalado, y comprueban que ``escena.js``
no repite la conversión.
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
    "$7,5 millones",
    "$7,5 mil",
    "Menos de $500 mil",
    "$1 millón",
    "Son $1.234.567.",
    "20 % al mes",
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


def test_la_conversion_a_voz_vive_en_voz_js_y_no_se_repite_en_escena() -> None:
    """El subtítulo usa paraPantalla; la voz convierte una sola vez en voz.js."""
    escena = _leer("escena.js")
    voz = (WEB / "voz.js").read_text(encoding="utf-8")
    assert 'import { paraVoz } from "./escena/voz_cifras.js";' in voz
    assert 'import { paraVoz } from "./voz_cifras.js";' not in escena
    assert "paraVoz(" not in escena
    assert "decirComo(turno.personaje, turno.texto" in escena
    assert "adelantarVoz(siguiente.personaje, siguiente.texto)" in escena
    assert "const limpio = paraVoz(texto);" in voz
    assert "subtitulo.textContent = paraPantalla(turno.subtitulo || turno.texto);" in escena
    assert 'porId("escena-texto").textContent = paraPantalla(turno.texto);' in escena


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
        ("👋 ✅ 🎙 Hola", "Hola"),
        (
            "Listo, gastos menos de $1.000.000. 💚 ¿Cuánto pagas hoy en cuotas de "
            "créditos o tarjetas? A. No tengo cuotas B. Menos de $500.000 "
            "C. Entre $500.000 y $1.000.000",
            "Listo, gastos menos de un millón de pesos. ¿Cuánto pagas hoy en cuotas "
            "de créditos o tarjetas? Responde A, B o C.",
        ),
        (
            "¿Cuánto pagas?\nA · Nada\nB · Poco\nC · Mucho",
            "¿Cuánto pagas? Responde A, B o C.",
        ),
        (
            "Elige una: A) Uno B) Dos",
            "Elige una: Responde A o B.",
        ),
        (
            "La tasa es 28,17 % E.A. y la mensual 2,09 % M.V.",
            "La tasa es veintiocho coma diecisiete por ciento efectivo anual y la "
            "mensual dos coma cero nueve por ciento mes vencido",
        ),
    ],
)
@requiere_node
def test_para_voz_traduce_cifras_y_deja_el_resto(texto: str, esperado: str) -> None:
    """Montos, rangos, porcentajes y marcas de WhatsApp quedan listos para la voz."""
    assert _para_voz(texto) == esperado


@requiere_node
def test_para_voz_deja_igual_un_texto_sin_opciones_ni_emojis() -> None:
    """Una frase normal no cambia y el texto sin listas conserva su sentido."""
    assert _para_voz("Hola, ¿cómo estás?") == "Hola, ¿cómo estás?"
    assert _para_voz("Marca A. y sigue") == "Marca A. y sigue"


@requiere_node
def test_un_turno_en_vivo_quita_el_emoji_y_anuncia_las_letras() -> None:
    """El texto que llega por la lista en vivo anuncia las letras, no las opciones."""
    turno = (
        "💚 ¿Cuánto pagas hoy en cuotas? "
        "A. No tengo cuotas B. Menos de $500.000 C. Entre $500.000 y $1.000.000"
    )
    salida = _para_voz(turno)
    assert salida == "¿Cuánto pagas hoy en cuotas? Responde A, B o C."
    assert "No tengo cuotas" not in salida


@requiere_node
def test_las_opciones_de_seis_letras_se_anuncian_sin_leer_su_texto() -> None:
    """Seis opciones producen «Responde A, B, C, D, E o F.» y no leen el texto."""
    texto = (
        "Elige tu producto: "
        "A. Libre inversión B. Vehículo nuevo C. Vehículo usado "
        "D. Vivienda E. Libranza F. Compra de cartera"
    )
    salida = _para_voz(texto)

    assert salida == "Elige tu producto: Responde A, B, C, D, E o F."
    for opcion in ("Libre inversión", "Vehículo", "Vivienda", "Libranza", "cartera"):
        assert opcion not in salida


@requiere_node
def test_las_opciones_de_tres_letras_usan_o_antes_de_la_ultima() -> None:
    """Tres opciones producen «Responde A, B o C.» sin leer su texto."""
    salida = _para_voz("¿Cuánto pagas? A. Nada B. Poco C. Mucho")

    assert salida == "¿Cuánto pagas? Responde A, B o C."
    assert "Nada" not in salida and "Poco" not in salida and "Mucho" not in salida


@requiere_node
def test_las_siglas_no_se_confunden_con_una_lista_de_opciones() -> None:
    """«E.A.» y «M.V.» no son opciones: sin lista, el texto sigue su curso."""
    assert _para_voz("E.A. y M.V. sin lista") == "efectivo anual. y mes vencido. sin lista"
    assert _para_voz("La tasa es 28,17 % E.A.") == (
        "La tasa es veintiocho coma diecisiete por ciento efectivo anual"
    )
    assert "Responde A" not in _para_voz("E.A. y M.V. sin lista")


@requiere_node
def test_las_opciones_tambien_se_anuncian_en_lineas_separadas() -> None:
    """«A. …» en renglones distintos produce el mismo anuncio de letras."""
    assert _para_voz("Elige:\nA. Uno\nB. Dos\nC. Tres") == ("Elige: Responde A, B o C.")


@requiere_node
def test_para_voz_no_deja_espacios_dobles_al_quitar_emojis() -> None:
    """Los emojis se van sin dejar huecos entre las palabras."""
    salida = _para_voz("Hola 👋  💚 mundo 🎬")

    assert salida == "Hola mundo"
    assert "  " not in salida


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


@requiere_node
def test_para_voz_conserva_el_espacio_despues_del_porcentaje_sin_sigla() -> None:
    """El «%» sin sigla no se come el espacio: «20 % al mes» suena con pausa."""
    assert _para_voz("20 % al mes") == "veinte por ciento al mes"
    assert _para_voz("20 % E.A. al mes") == "veinte por ciento efectivo anual al mes"


@requiere_node
def test_montos_con_coma_decimal_y_escala_en_voz_y_pantalla() -> None:
    """«$7,5 millones» se lee con «coma» y se muestra con la cifra completa."""
    assert _para_voz("$7,5 millones") == "siete coma cinco millones de pesos"
    assert _para_voz("$7,5 mil") == "siete coma cinco mil pesos"
    assert _para_pantalla("$7,5 millones") == "$7.500.000"
    assert _para_pantalla("$7,5 mil") == "$7.500"


@requiere_node
def test_la_voz_y_la_pantalla_conservan_el_punto_final_de_la_frase() -> None:
    """El punto de miles solo cuenta si va seguido de dígitos."""
    assert _para_voz("Son $1.234.567.") == (
        "Son un millón doscientos treinta y cuatro mil quinientos sesenta y siete pesos."
    )
    assert _para_pantalla("Son $1.234.567.") == "Son $1.234.567."


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
        ("*Verde: va bien* y _cursiva_", "Verde: va bien y cursiva"),
        ("mira https://ejemplo.com/pagina ahora", "mira ahora"),
        (
            "*$30 millones* a 60 meses\nhttps://ejemplo.com/tasas\n_Orientativo._",
            "$30.000.000 a 60 meses\nOrientativo.",
        ),
    ],
)
@requiere_node
def test_para_pantalla_expande_las_cifras_completas(texto: str, esperado: str) -> None:
    """Las etiquetas cortas se ven completas en la escena, sin tocar WhatsApp."""
    assert _para_pantalla(texto) == esperado
