"""Pruebas sin red ni navegador del Tablero de tasas de la sucursal (PR 15).

Comprueban las tareas 18.2 (estado vacío sin inventar valores) y 18.3 (la
vista muestra concepto, valor, moneda, periodicidad, vigencia, origen y fuente,
sin recalcular ni comparar filas). La 18.1 se completa al verificar contra
``/api/tablero?q=cuota`` cuando exista el CSV del PR 7 y la API del PR 10.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

RAIZ = Path(__file__).resolve().parents[1]
WEB = RAIZ / "app" / "web"
EJEMPLO = WEB / "datos-ejemplo" / "tablero.json"
VISTA = WEB / "vistas" / "tablero.js"

COLUMNAS_CSV = (
    "concepto",
    "categoria",
    "valor",
    "moneda",
    "recargos",
    "periodicidad",
    "vigente_desde",
    "origen",
    "pagina",
    "fuente",
)


def leer_ejemplo() -> dict[str, Any]:
    """Lee ``app/web/datos-ejemplo/tablero.json``."""
    return json.loads(EJEMPLO.read_text(encoding="utf-8"))


def leer_vista() -> str:
    """Lee el código de la vista Tablero."""
    return VISTA.read_text(encoding="utf-8")


def bloque_css() -> str:
    """Devuelve el bloque CSS del Tablero, entre sus marcadores."""
    css = (WEB / "estilos.css").read_text(encoding="utf-8")
    inicio = css.index("/* --- tablero (PR 15) --- */")
    fin = css.index("/* --- fin tablero --- */", inicio)
    return css[inicio:fin]


def test_filas_de_ejemplo_tienen_las_diez_columnas() -> None:
    """Cada fila trae exactamente las diez columnas del CSV, todas como texto."""
    datos = leer_ejemplo()
    assert datos["total"] == len(datos["filas"])
    assert len(datos["filas"]) >= 10
    for fila in datos["filas"]:
        assert tuple(fila) == COLUMNAS_CSV
        assert all(isinstance(valor, str) for valor in fila.values())
        assert fila["origen"] in {"tarifario", "tabla_web"}
        assert fila["moneda"] in {"COP", "USD", "EUR"}
        assert fila["fuente"].startswith("https://")


def test_vigencia_de_ejemplo_es_fecha_iso_o_vacia() -> None:
    """La vigencia viene normalizada a ISO (``AAAA-MM-DD``) o vacía."""
    for fila in leer_ejemplo()["filas"]:
        assert fila["vigente_desde"] == "" or re.fullmatch(
            r"\d{4}-\d{2}-\d{2}", fila["vigente_desde"]
        )


@pytest.mark.parametrize("fila", leer_ejemplo()["filas"], ids=lambda fila: fila["concepto"])
def test_valor_de_ejemplo_sale_de_su_pagina_de_gold(fila: dict[str, str]) -> None:
    """El valor de cada fila de ejemplo aparece en su página de Gold (no se inventa)."""
    pagina = (RAIZ / fila["pagina"]).read_text(encoding="utf-8")
    fuente = re.search(r"^fuente: (.+)$", pagina, re.MULTILINE)
    assert fuente is not None
    assert fuente.group(1).strip() == fila["fuente"]
    assert fila["valor"] in pagina


def test_vista_consulta_la_api_con_q() -> None:
    """La vista envía ``q`` a ``/api/tablero`` y no hace peticiones propias."""
    codigo = leer_vista()
    assert 'estado.pedir("tablero", { consulta: { q } })' in codigo
    for prohibido in ("fetch(", "innerHTML", "localStorage", "sessionStorage", '"preguntar"'):
        assert prohibido not in codigo, prohibido


def test_vista_muestra_las_columnas_pedidas() -> None:
    """Están las columnas de la tarea 18.3 y la moneda va junto al valor."""
    codigo = leer_vista()
    for clave in (
        "concepto",
        "valor",
        "recargos",
        "periodicidad",
        "vigente_desde",
        "origen",
        "fuente",
    ):
        assert f'["{clave}",' in codigo, clave
    assert "fila.moneda" in codigo


def test_vista_no_recalcula_ni_inventa() -> None:
    """La vista no hace cuentas con los valores y muestra «—» si falta un dato."""
    codigo = leer_vista()
    for prohibido in ("parseFloat", "parseInt", "Number(fila", "toFixed", ".reduce(", "Math."):
        assert prohibido not in codigo, prohibido
    assert 'defecto = "—"' in codigo
    assert "no inventa cifras" in codigo


def test_vista_tiene_estado_vacio_y_error() -> None:
    """Hay estado vacío con la consulta, error con reintento y resumen accesible."""
    codigo = leer_vista()
    assert "No hay filas para «${q}»." in codigo
    assert "Reintentar" in codigo
    assert 'setAttribute("role", "alert")' in codigo
    assert 'setAttribute("aria-live", "polite")' in codigo


def test_filtro_local_solo_en_la_maqueta() -> None:
    """El filtro del navegador solo corre en modo de ejemplo; con la API filtra el servidor."""
    codigo = leer_vista()
    assert codigo.count("filtrarEnMaqueta(") == 2
    llamada = codigo.index("filtrarEnMaqueta(filas, q)")
    assert 'if (estado.modo === "ejemplo") {' in codigo[llamada - 120 : llamada]


def test_enlaces_de_fuente_validados() -> None:
    """La fuente solo se enlaza si es http/https y abre en otra pestaña sin ``opener``."""
    codigo = leer_vista()
    assert "esUrlSegura(url)" in codigo
    assert 'enlace.target = "_blank"' in codigo
    assert 'enlace.rel = "noopener noreferrer"' in codigo


def test_estilos_del_tablero_usan_variables_y_su_prefijo() -> None:
    """El bloque del Tablero usa solo variables de la base y clases ``.tablero``."""
    bloque = bloque_css()
    sin_comentarios = re.sub(r"/\*.*?\*/", "", bloque, flags=re.DOTALL)
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b", sin_comentarios)
    assert not re.search(r"\b(rgba?|hsla?)\(", sin_comentarios)
    for selector in re.findall(r"([^{}]+)\{", sin_comentarios):
        for parte in selector.split(","):
            limpio = parte.strip()
            if limpio and not limpio.startswith("@"):
                assert limpio.startswith(".tablero"), limpio
