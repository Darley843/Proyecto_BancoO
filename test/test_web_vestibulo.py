"""Pruebas sin red ni navegador del Vestíbulo de la sucursal (PR 17).

Comprueban la tarea 20.1 (hitos de ``config/vestibulo.toml`` con año, texto y
URL, y entrada a la Ventanilla) y la 20.2 (el Vestíbulo no necesita clave,
índice ni modelo). La comparación con la API real se hará cuando el PR 10
publique ``GET /api/vestibulo``.
"""

from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path
from typing import Any

RAIZ = Path(__file__).resolve().parents[1]
WEB = RAIZ / "app" / "web"
CONFIG = RAIZ / "config" / "vestibulo.toml"
EJEMPLO = WEB / "datos-ejemplo" / "vestibulo.json"
VISTA = WEB / "vistas" / "vestibulo.js"
CORPUS = RAIZ / "data" / "gold" / "corpus.jsonl"


def hitos_config() -> list[dict[str, Any]]:
    """Lee los hitos de ``config/vestibulo.toml``."""
    with CONFIG.open("rb") as archivo:
        return tomllib.load(archivo)["hito"]


def hitos_ejemplo() -> list[dict[str, Any]]:
    """Lee los hitos de ``app/web/datos-ejemplo/vestibulo.json``."""
    return json.loads(EJEMPLO.read_text(encoding="utf-8"))["hitos"]


def leer_vista() -> str:
    """Lee el código de la vista Vestíbulo."""
    return VISTA.read_text(encoding="utf-8")


def bloque_css() -> str:
    """Devuelve el bloque CSS del Vestíbulo, entre sus marcadores."""
    css = (WEB / "estilos.css").read_text(encoding="utf-8")
    inicio = css.index("/* --- vestibulo (PR 17) --- */")
    fin = css.index("/* --- fin vestibulo --- */", inicio)
    return css[inicio:fin]


def test_config_tiene_hitos_con_anio_texto_y_url() -> None:
    """Cada hito tiene exactamente año entero, texto corto y URL https."""
    hitos = hitos_config()
    assert len(hitos) >= 5
    for hito in hitos:
        assert set(hito) == {"anio", "texto", "url"}
        assert isinstance(hito["anio"], int)
        assert 1965 <= hito["anio"] <= 2026
        assert isinstance(hito["texto"], str)
        assert 0 < len(hito["texto"].strip()) <= 140
        assert hito["url"].startswith("https://")


def test_config_empieza_en_1965_y_va_en_orden() -> None:
    """La historia arranca en la fundación y los años no se repiten ni retroceden."""
    anios = [hito["anio"] for hito in hitos_config()]
    assert anios[0] == 1965
    assert anios == sorted(set(anios))


def test_urls_de_los_hitos_existen_en_gold() -> None:
    """Cada URL de un hito es una fuente capturada en Gold (no se inventan enlaces)."""
    fuentes = {
        json.loads(linea)["fuente"]
        for linea in CORPUS.read_text(encoding="utf-8").splitlines()
        if linea.strip()
    }
    for hito in hitos_config():
        assert hito["url"] in fuentes, hito["url"]


def test_datos_de_ejemplo_repiten_el_toml() -> None:
    """La maqueta muestra los mismos hitos que servirá la API desde el TOML."""
    assert hitos_ejemplo() == hitos_config()


def test_vestibulo_pide_sus_datos_y_entra_a_la_ventanilla() -> None:
    """La vista usa el contrato y tiene una entrada clara a la Ventanilla."""
    codigo = leer_vista()
    assert 'estado.pedir("vestibulo")' in codigo
    assert 'entrada.href = "#ventanilla"' in codigo
    assert "Tomar turno en la Ventanilla" in codigo
    assert "Reintentar" in codigo
    assert 'setAttribute("role", "alert")' in codigo


def test_vestibulo_no_usa_modelo_indice_ni_almacenamiento() -> None:
    """El Vestíbulo es la bienvenida: no pregunta, no busca y no guarda nada."""
    codigo = leer_vista()
    for prohibido in (
        '"preguntar"',
        '"mapa"',
        "fetch(",
        "innerHTML",
        "localStorage",
        "sessionStorage",
    ):
        assert prohibido not in codigo, prohibido


def test_vestibulo_solo_enlaza_http_o_https() -> None:
    """Los enlaces a la fuente se validan y abren en otra pestaña sin ``opener``."""
    codigo = leer_vista()
    assert "esUrlSegura(hito.url)" in codigo
    assert 'destino.protocol === "https:"' in codigo
    assert 'enlace.rel = "noopener noreferrer"' in codigo


def test_estilos_del_vestibulo_usan_variables_y_su_prefijo() -> None:
    """El bloque del Vestíbulo usa solo variables de la base y clases ``.vestibulo``."""
    bloque = bloque_css()
    sin_comentarios = re.sub(r"/\*.*?\*/", "", bloque, flags=re.DOTALL)
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b", sin_comentarios)
    assert not re.search(r"\b(rgba?|hsla?)\(", sin_comentarios)
    for selector in re.findall(r"([^{}]+)\{", sin_comentarios):
        for parte in selector.split(","):
            limpio = parte.strip()
            if limpio and not limpio.startswith("@"):
                assert limpio.startswith(".vestibulo"), limpio
