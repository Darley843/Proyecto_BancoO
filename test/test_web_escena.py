"""Pruebas sin navegador de la pantalla de la escena «Pana vs. el gota a gota».

Comprueban que los turnos de ejemplo cumplen el contrato del turno (plan de
cierre, sección 6), que las cifras de ejemplo cuadran con las fórmulas y con
``config/tasas.toml``, y que la página se sirve y no carga nada de internet.
"""

from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

RAIZ = Path(__file__).resolve().parents[1]
WEB = RAIZ / "app" / "web"
ESCENA = WEB / "escena"

PERSONAJES = {"pana", "don_gota", "joven", "agente_joven", "agente_banco", "auditor"}
ORIGENES = {"guion", "motor", "modelo", "reglas"}
FUENTES = {"motor", "simulador", "Tablero"}
SEMAFOROS = {"", "verde", "amarillo", "rojo"}
CAMPOS = {"personaje", "texto", "cifras", "escenario", "origen", "hallazgos"}


def _turnos() -> list[dict[str, Any]]:
    """Lee los turnos de ejemplo."""
    datos = json.loads((ESCENA / "turnos-ejemplo.json").read_text(encoding="utf-8"))
    return datos["turnos"]


def _cifras() -> dict[str, float]:
    """Junta todas las cifras de los turnos por nombre (la última gana)."""
    return {c["nombre"]: c["valor"] for t in _turnos() for c in t["cifras"]}


def test_cada_turno_cumple_el_contrato() -> None:
    """Campos exactos y valores dentro de los conjuntos del contrato."""
    for posicion, turno in enumerate(_turnos()):
        assert set(turno) == CAMPOS, posicion
        assert turno["personaje"] in PERSONAJES, posicion
        assert turno["origen"] in ORIGENES, posicion
        assert turno["texto"].strip(), posicion
        assert isinstance(turno["hallazgos"], list), posicion
        assert set(turno["escenario"]) == {"monto", "plazo", "semaforo"}, posicion
        assert turno["escenario"]["semaforo"] in SEMAFOROS, posicion
        for cifra in turno["cifras"]:
            assert set(cifra) == {"nombre", "valor", "fuente"}, posicion
            assert cifra["fuente"] in FUENTES, posicion
            assert isinstance(cifra["valor"], int | float), posicion


def test_los_cinco_que_hablan_aparecen() -> None:
    """El ejemplo recorre a todos los personajes y cierra el auditor."""
    turnos = _turnos()
    assert {t["personaje"] for t in turnos} == PERSONAJES
    assert turnos[-1]["personaje"] == "auditor"


def test_don_gota_nunca_sale_de_un_modelo() -> None:
    """Regla del plan: Don Gota sale del guion o del código, nunca del modelo."""
    assert all(t["origen"] != "modelo" for t in _turnos() if t["personaje"] == "don_gota")


def test_cifras_de_don_gota_siguen_el_diseno() -> None:
    """Fórmulas del design.md §2: 20 % mensual, ciclo de 30 días, 36 renovaciones."""
    cifras = _cifras()
    monto = cifras["monto"]
    mensual = cifras["tasa_mensual_don_gota"]
    assert cifras["plazo_meses"] == 36
    assert cifras["interes_mensual_don_gota"] == monto * mensual
    assert cifras["cuota_diaria_don_gota"] == (monto + monto * mensual) / 30
    assert cifras["total_don_gota"] == monto + monto * mensual * 36
    assert cifras["tea_don_gota"] == pytest.approx((1 + mensual) ** 12 - 1, abs=1e-4)


def test_cifras_del_banco_salen_del_motor() -> None:
    """Cuota y total del banco son los del motor con la tasa máxima publicada."""
    from datetime import date
    from decimal import Decimal

    from banco_occidente_corpus.canal.contratos import EntradaDiagnostico
    from banco_occidente_corpus.diagnostico.motor import calcular

    cifras = _cifras()
    entrada = EntradaDiagnostico.model_validate(
        {
            "producto": "libre_inversion",
            "vinculacion": "empleado",
            "ingreso_mensual": Decimal(1_500_000),
            "gastos_mensuales": Decimal(750_000),
            "cuotas_deudas": Decimal(0),
            "monto_credito": Decimal(int(cifras["monto"])),
            "plazo_meses": int(cifras["plazo_meses"]),
            "rango_usado": {},
        }
    )
    resultado = calcular(entrada, hoy=date(2026, 11, 27))
    assert cifras["cuota_banco"] == int(resultado.cuota_mensual.hasta)
    assert cifras["total_banco"] == int(resultado.total_pagado.hasta)
    assert cifras["tea_banco"] == float(resultado.tasa_ea.hasta)
    assert resultado.semaforo == _turnos()[-1]["escenario"]["semaforo"]


def test_el_ejemplo_se_declara_ejemplo() -> None:
    """El JSON dice que es maquetación y que lo reemplaza make escena-proyectada."""
    datos = json.loads((ESCENA / "turnos-ejemplo.json").read_text(encoding="utf-8"))
    assert "EJEMPLO DE MAQUETACIÓN" in datos["descripcion"]
    assert "make escena-proyectada" in datos["descripcion"]


def test_cifras_del_banco_usan_la_usura_y_quedan_debajo() -> None:
    """La usura de ejemplo es la de config/tasas.toml y la TEA del banco no la pasa."""
    with (RAIZ / "config" / "tasas.toml").open("rb") as fh:
        usura = tomllib.load(fh)["usura"]["tasa_ea"]
    cifras = _cifras()
    assert cifras["usura"] == usura
    assert cifras["tea_banco"] <= usura < cifras["tea_don_gota"]


def test_la_pagina_carga_sus_archivos_locales() -> None:
    """escena.html usa su CSS y su JS, sin URLs externas."""
    html = (WEB / "escena.html").read_text(encoding="utf-8")
    assert 'href="escena/escena.css"' in html
    assert 'src="escena/escena.js"' in html
    for archivo in (WEB / "escena.html", *ESCENA.glob("*.*")):
        texto = archivo.read_text(encoding="utf-8")
        assert not re.search(r"""(src|href)=["']https?://""", texto), archivo.name
        assert "innerHTML" not in texto, archivo.name


def test_ids_que_usa_el_js_existen_en_el_html() -> None:
    """Cada porId("...") de escena.js tiene su elemento en escena.html."""
    html = (WEB / "escena.html").read_text(encoding="utf-8")
    codigo = (ESCENA / "escena.js").read_text(encoding="utf-8")
    fijos = set(re.findall(r'porId\("([a-z-]+)"\)', codigo))
    assert fijos
    for identificador in fijos:
        assert f'id="{identificador}"' in html, identificador


def test_el_contrato_js_declara_los_mismos_conjuntos() -> None:
    """contrato.js y esta prueba usan los mismos personajes, orígenes y fuentes."""
    codigo = (ESCENA / "contrato.js").read_text(encoding="utf-8")
    for valor in PERSONAJES | ORIGENES | FUENTES:
        assert f'"{valor}"' in codigo, valor


def test_cada_personaje_tiene_rostro_con_boca() -> None:
    """rostros.js dibuja a los seis (respaldo) y escena.js usa los retratos."""
    codigo = (ESCENA / "rostros.js").read_text(encoding="utf-8")
    bloque = re.search(r"const DIBUJOS = Object\.freeze\(\{(.*?)\}\);", codigo, re.S)
    assert bloque
    claves = set(re.findall(r"^\s*([a-z_]+)(?::|,)", bloque.group(1), re.M))
    assert claves == PERSONAJES
    assert codigo.count('class: "escena__boca"') == len(PERSONAJES)
    assert "retrato(personaje)" in (ESCENA / "escena.js").read_text(encoding="utf-8")


def test_cada_personaje_tiene_retrato_liviano() -> None:
    """Hay un retrato .webp por personaje y ninguno pesa más de 60 KB."""
    retratos = {archivo.stem: archivo for archivo in (ESCENA / "rostros").glob("*.webp")}
    assert set(retratos) == PERSONAJES
    for nombre, archivo in retratos.items():
        assert archivo.stat().st_size < 60_000, nombre
        assert archivo.read_bytes()[8:12] == b"WEBP", nombre


@pytest.mark.parametrize(
    "ruta",
    [
        "/escena.html",
        "/escena/escena.js",
        "/escena/contrato.js",
        "/escena/rostros.js",
        "/escena/rostros/pana.webp",
        "/escena/escena.css",
        "/escena/turnos-ejemplo.json",
    ],
)
def test_la_app_sirve_la_escena(ruta: str) -> None:
    """Los archivos de la escena se sirven como estáticos."""
    from fastapi import FastAPI
    from fastapi.staticfiles import StaticFiles

    app = FastAPI()
    app.mount("/", StaticFiles(directory=WEB, html=True), name="web")
    assert TestClient(app).get(ruta).status_code == 200
