"""Pruebas del modo «En vivo» de la pantalla de la escena (tarea 6.3).

Contrato: ``docs/ESCENA_EN_VIVO.md``, §11 y §14 (fila de Yoldy). Las pruebas
estáticas leen los archivos de ``app/web``; las de la cola ejecutan las
funciones puras de ``envivo.js`` con Node, si está instalado (sin red y sin
navegador).
"""

from __future__ import annotations

import json
import re
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


def test_la_tecla_e_y_el_boton_existen() -> None:
    """La tecla E alterna el modo y el botón «En vivo» tiene aria-pressed."""
    html = (WEB / "escena.html").read_text(encoding="utf-8")
    codigo = _leer("escena.js")
    assert 'id="escena-en-vivo"' in html
    assert 'aria-pressed="false"' in html.split('id="escena-en-vivo"')[1].split(">")[0]
    assert 'id="escena-envivo-estado"' in html
    assert "E en vivo" in html
    assert 'tecla === "e"' in codigo
    assert "alternarEnVivo" in codigo


def test_envivo_js_se_sirve() -> None:
    """envivo.js se sirve como los demás módulos de la escena."""
    app = FastAPI()
    app.mount("/", StaticFiles(directory=WEB, html=True), name="web")
    respuesta = TestClient(app).get("/escena/envivo.js")
    assert respuesta.status_code == 200
    assert "crearSondeo" in respuesta.text
    assert 'from "./envivo.js"' in _leer("escena.js")


def test_contrato_js_incluye_invitado_y_canal() -> None:
    """Las dos extensiones aditivas del contrato (§3.1) están en contrato.js."""
    codigo = _leer("contrato.js")
    personajes = re.search(r"export const PERSONAJES = Object\.freeze\(\[(.*?)\]\);", codigo, re.S)
    origenes = re.search(r"export const ORIGENES = Object\.freeze\(\[(.*?)\]\);", codigo, re.S)
    assert personajes and origenes
    assert '"invitado"' in personajes.group(1)
    assert '"canal"' in origenes.group(1)
    assert 'invitado: { nombre: "Invitado" }' in _leer("escena.js")


@pytest.mark.parametrize("archivo", ["envivo.js", "escena.js", "contrato.js"])
def test_sin_urls_externas_ni_innerhtml_ni_storage(archivo: str) -> None:
    """Nada de internet, nada de innerHTML y el cursor no se guarda en storage."""
    codigo = _leer(archivo)
    assert "innerHTML" not in codigo
    assert not re.search(r"https?://", codigo)
    if archivo == "envivo.js":
        assert "localStorage" not in codigo
        assert "sessionStorage" not in codigo


def test_el_sondeo_cumple_el_contrato() -> None:
    """Cada 1 s con setTimeout, techo de 1,5 s, sin caché y parado si la pestaña se oculta."""
    codigo = _leer("envivo.js")
    assert "setInterval" not in codigo
    assert "INTERVALO_MS = 1000" in codigo
    assert "ESPERA_MS = 1500" in codigo
    assert 'cache: "no-store"' in codigo
    assert "AbortController" in codigo
    assert "document.hidden" in codigo
    assert "visibilitychange" in codigo
    assert '"/api/escena/en-vivo"' in codigo


def test_el_invitado_no_pide_voz_en_escena_js() -> None:
    """escena.js pregunta a pideVoz antes de llamar a la voz."""
    codigo = _leer("escena.js")
    assert "pideVoz(turno.personaje" in codigo
    assert 'SIN_VOZ = Object.freeze(["invitado"])' in _leer("envivo.js")


def _turno(personaje: str = "pana", texto: str = "Hola") -> dict[str, object]:
    """Turno mínimo válido de TurnoEscena."""
    return {
        "id": "prueba",
        "orden": 0,
        "personaje": personaje,
        "texto": texto,
        "subtitulo": None,
        "cifras": [],
        "escenario": None,
        "origen": "canal",
        "hallazgos": [],
    }


def _node(expresion: str) -> object:
    """Evalúa una expresión con las funciones puras de envivo.js y devuelve su JSON."""
    assert NODE
    url = (ESCENA / "envivo.js").as_uri()
    programa = f"import * as m from {json.dumps(url)};\nconsole.log(JSON.stringify({expresion}));\n"
    salida = subprocess.run(
        [NODE, "--input-type=module", "-e", programa],
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )
    return json.loads(salida.stdout)


requiere_node = pytest.mark.skipif(NODE is None, reason="Node no está instalado")


@requiere_node
def test_la_cola_se_ordena_y_deduplica_por_seq() -> None:
    """Los registros llegan desordenados y repetidos: salen una vez, en orden de seq."""
    registros = [
        {"seq": 30, "ts": "t", "origen": "herramienta", "turno": _turno("auditor")},
        {"seq": 10, "ts": "t", "origen": "canal", "turno": _turno("invitado")},
        {"seq": 20, "ts": "t", "origen": "canal", "turno": _turno("pana")},
        {"seq": 10, "ts": "t", "origen": "canal", "turno": _turno("invitado")},
    ]
    resultado = _node(f"m.registrosNuevos([], {json.dumps(registros)})")
    assert isinstance(resultado, dict)
    assert [r["seq"] for r in resultado["nuevos"]] == [10, 20, 30]
    assert resultado["descartados"] == []


@requiere_node
def test_la_cola_no_retrocede_ni_repite_lo_ya_encolado() -> None:
    """Un seq igual o menor que el último encolado no vuelve a entrar."""
    cola = [{"seq": 20}]
    registros = [
        {"seq": 20, "ts": "t", "origen": "canal", "turno": _turno()},
        {"seq": 15, "ts": "t", "origen": "canal", "turno": _turno()},
        {"seq": 25, "ts": "t", "origen": "canal", "turno": _turno()},
    ]
    resultado = _node(f"m.registrosNuevos({json.dumps(cola)}, {json.dumps(registros)})")
    assert isinstance(resultado, dict)
    assert [r["seq"] for r in resultado["nuevos"]] == [25]


@requiere_node
def test_un_turno_invalido_se_descarta_sin_detener_la_cola() -> None:
    """Un personaje desconocido o un registro sin seq se cuentan como descarte."""
    malo = _turno()
    malo["personaje"] = "intruso"
    registros = [
        {"seq": 1, "ts": "t", "origen": "canal", "turno": malo},
        {"ts": "t", "origen": "canal", "turno": _turno()},
        {"seq": 2, "ts": "t", "origen": "canal", "turno": _turno("don_gota")},
    ]
    resultado = _node(f"m.registrosNuevos([], {json.dumps(registros)})")
    assert isinstance(resultado, dict)
    assert [r["seq"] for r in resultado["nuevos"]] == [2]
    assert len(resultado["descartados"]) == 2
    assert "intruso" in resultado["descartados"][0]


@requiere_node
def test_seq_grande_se_compara_sin_perder_precision() -> None:
    """Los seq de época (≈1,8 × 10^15) se ordenan bien y el cursor no retrocede."""
    resultado = _node(
        "[m.compararSeq(1795705500123007, 1795705500123008),"
        " m.siguienteCursor(1795705500123008, 1795705500123007),"
        " m.siguienteCursor(0, 1795705500123007),"
        " m.siguienteCursor(5, 'basura')]"
    )
    assert resultado == [-1, 1795705500123008, 1795705500123007, 5]


@requiere_node
def test_el_invitado_no_pide_voz_y_se_lee_entre_2_y_6_segundos() -> None:
    """pideVoz y tiempoDeLectura siguen la tabla del contrato (§11.3 y §11.4)."""
    resultado = _node(
        "[m.pideVoz('invitado', false), m.pideVoz('pana', false), m.pideVoz('pana', true),"
        " m.tiempoDeLectura('hola'), m.tiempoDeLectura('x'.repeat(60)),"
        " m.tiempoDeLectura('x'.repeat(500)), m.urlEnVivo(1795705500123007)]"
    )
    assert resultado == [
        False,
        True,
        False,
        2000,
        3300,
        6000,
        "/api/escena/en-vivo?desde=1795705500123007",
    ]


def test_en_vivo_el_veredicto_queda_en_la_trazabilidad() -> None:
    """Sin escena precalculada, el veredicto sale del turno del auditor y queda en T."""
    codigo = _leer("escena.js")
    assert "veredicto: veredictoDeHallazgos(turno.hallazgos), hallazgos: turno.hallazgos" in codigo
