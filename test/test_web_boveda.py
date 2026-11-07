"""Pruebas sin red ni navegador de la vista Bóveda de la sucursal (PR 14).

Comprueban las tareas 17.1 (mapa, pregunta y top con título, sección, tipo y
similitud), 17.2 (estado «índice no listo» sin dibujar un mapa vacío) y 17.3
(sin librerías externas ni peticiones distintas de ``/api/boveda/mapa``). La
verificación con una consulta real queda para cuando existan ``boveda/mapa.py``
(PR 11) y la API (PR 10).

La maqueta ``datos-ejemplo/mapa.json`` se genera con ``scripts/mapa_ejemplo.py``
a partir de los fragmentos reales del alcance ``base``; las pruebas confirman
que el archivo sigue al día con ese script.
"""

from __future__ import annotations

import importlib.util
import json
import math
import re
from functools import cache
from pathlib import Path
from types import ModuleType
from typing import Any

from banco_occidente_corpus.boveda.fragmentos import construir_fragmentos
from banco_occidente_corpus.boveda.tipos import Fragmento
from banco_occidente_corpus.config import load_config

RAIZ = Path(__file__).resolve().parents[1]
WEB = RAIZ / "app" / "web"
EJEMPLO = WEB / "datos-ejemplo" / "mapa.json"
VISTA = WEB / "vistas" / "boveda.js"
SCRIPT = RAIZ / "scripts" / "mapa_ejemplo.py"

CAMPOS_TOP = {"id", "texto", "url", "titulo", "seccion", "encabezado", "tipo", "tokens", "puntaje"}


def leer_ejemplo() -> dict[str, Any]:
    """Lee ``app/web/datos-ejemplo/mapa.json``."""
    return json.loads(EJEMPLO.read_text(encoding="utf-8"))


def leer_vista() -> str:
    """Lee el código de la vista Bóveda."""
    return VISTA.read_text(encoding="utf-8")


@cache
def fragmentos_base() -> tuple[Fragmento, ...]:
    """Construye una vez los fragmentos reales del alcance ``base``."""
    return tuple(construir_fragmentos(load_config(), "base").fragmentos)


def cargar_script() -> ModuleType:
    """Importa ``scripts/mapa_ejemplo.py`` como módulo, sin ejecutar ``main``."""
    especificacion = importlib.util.spec_from_file_location("mapa_ejemplo", SCRIPT)
    assert especificacion is not None and especificacion.loader is not None
    modulo = importlib.util.module_from_spec(especificacion)
    especificacion.loader.exec_module(modulo)
    return modulo


def bloque_css() -> str:
    """Devuelve el bloque CSS de la Bóveda, entre sus marcadores."""
    css = (WEB / "estilos.css").read_text(encoding="utf-8")
    inicio = css.index("/* --- boveda (PR 14) --- */")
    fin = css.index("/* --- fin boveda --- */", inicio)
    return css[inicio:fin]


def test_maqueta_tiene_un_punto_por_fragmento_real() -> None:
    """Cada punto corresponde, en orden, a un fragmento real con su título y sección."""
    puntos = leer_ejemplo()["puntos"]
    fragmentos = fragmentos_base()
    assert len(puntos) == len(fragmentos)
    for punto, fragmento in zip(puntos, fragmentos, strict=True):
        assert set(punto) == {"x", "y", "seccion", "titulo"}
        assert punto["titulo"] == fragmento.titulo
        assert punto["seccion"] == fragmento.seccion


def test_top_de_la_maqueta_copia_fragmentos_reales() -> None:
    """El top trae cinco fragmentos reales, sin textos inventados, de mayor a menor similitud."""
    top = leer_ejemplo()["top"]
    por_id = {fragmento.id: fragmento for fragmento in fragmentos_base()}
    assert len(top) == 5
    for item in top:
        assert set(item) == CAMPOS_TOP
        real = por_id[item["id"]]
        assert item["texto"] == real.texto
        assert item["url"] == real.url
        assert item["titulo"] == real.titulo
        assert item["tipo"] == real.tipo
        assert 0 <= item["puntaje"] <= 1
    puntajes = [item["puntaje"] for item in top]
    assert puntajes == sorted(puntajes, reverse=True)


def test_coordenadas_finitas_entre_0_y_100() -> None:
    """Puntos y pregunta vienen normalizados de 0 a 100, como los entrega el servidor."""
    datos = leer_ejemplo()
    for punto in [*datos["puntos"], datos["pregunta"]]:
        for eje in ("x", "y"):
            assert math.isfinite(punto[eje])
            assert 0 <= punto[eje] <= 100


def test_maqueta_al_dia_con_el_script() -> None:
    """Regenerar con ``scripts/mapa_ejemplo.py`` da el archivo versionado.

    Títulos, secciones e ids deben ser idénticos; las coordenadas y los puntajes
    admiten una décima de diferencia por el redondeo de cada máquina.
    """
    nuevo = cargar_script().generar(fragmentos_base())
    guardado = leer_ejemplo()
    assert [i["id"] for i in nuevo["top"]] == [i["id"] for i in guardado["top"]]
    for actual, esperado in zip(nuevo["top"], guardado["top"], strict=True):
        assert math.isclose(actual["puntaje"], esperado["puntaje"], abs_tol=0.011)
    pares = [*zip(nuevo["puntos"], guardado["puntos"], strict=True)]
    pares.append((nuevo["pregunta"], guardado["pregunta"]))
    for actual, esperado in pares:
        assert actual.get("titulo") == esperado.get("titulo")
        assert math.isclose(actual["x"], esperado["x"], abs_tol=0.11)
        assert math.isclose(actual["y"], esperado["y"], abs_tol=0.11)


def test_vista_solo_pide_el_mapa() -> None:
    """La vista solo usa ``/api/boveda/mapa`` vía ``estado.pedir`` y no trae librerías."""
    codigo = leer_vista()
    assert 'estado.pedir("mapa", { consulta: { pregunta } })' in codigo
    assert codigo.count("estado.pedir(") == 1
    for prohibido in ("fetch(", "innerHTML", "localStorage", "sessionStorage", "<script", "cdn"):
        assert prohibido not in codigo, prohibido
    importaciones = re.findall(r'^import .* from "(.+)";$', codigo, re.MULTILINE)
    assert importaciones == ["../comun.js"]


def test_vista_muestra_titulo_seccion_tipo_y_similitud() -> None:
    """Cada fragmento del top muestra título, sección, tipo y similitud con coma decimal."""
    codigo = leer_vista()
    for campo in ("fragmento.titulo", "fragmento.seccion", "fragmento.tipo", "fragmento.puntaje"):
        assert campo in codigo, campo
    assert (
        'toLocaleString("es-CO", { minimumFractionDigits: 2, maximumFractionDigits: 2 })' in codigo
    )


def test_sin_indice_no_dibuja_el_mapa() -> None:
    """Si ``/api/estado`` dice que el índice no está listo, se explica y se sale antes de dibujar."""
    codigo = leer_vista()
    rama = codigo.index("if (estado.resumen?.indice_listo === false) {")
    salida = codigo[rama : codigo.index("return;", rama)]
    assert "crearIndiceNoListo()" in salida
    assert "make indice" in codigo
    assert "if (puntos.length === 0) {" in codigo
    assert "crearSinPuntos()" in codigo


def test_mapa_no_calculado_muestra_el_mensaje_de_la_api() -> None:
    """Con ``disponible: false`` se explica con el ``error`` de la API, sin dibujar."""
    codigo = leer_vista()
    rama = codigo.index("if (datos?.disponible === false) {")
    salida = codigo[rama : codigo.index("return;", rama)]
    assert "crearMapaNoCalculado(avisoApi)" in salida
    assert rama < codigo.index("crearPanelMapa(puntos, marca)")


def test_pregunta_fallida_muestra_el_aviso_y_no_dice_que_no_hubo_fragmentos() -> None:
    """Si Ollama falla, el top explica el error en vez de «no encontró fragmentos»."""
    codigo = leer_vista()
    assert "crearPanelTop(pregunta, top, avisoApi)" in codigo
    aviso = codigo.index("if (avisoApi && top.length === 0) {")
    vacio = codigo.index("La Bóveda no encontró fragmentos para esta pregunta.")
    assert aviso < vacio
    assert "No se pudo buscar tu pregunta." in codigo[aviso:vacio]
    assert 'crearTexto("p", avisoApi)' in codigo[aviso:vacio]


def test_coordenadas_invalidas_no_se_dibujan() -> None:
    """Solo se dibujan puntos con ``x`` e ``y`` finitos entre 0 y 100."""
    codigo = leer_vista()
    assert "Number.isFinite(valor) && valor >= 0 && valor <= 100" in codigo
    assert "String(100 - punto.y)" in codigo


def test_maqueta_sin_pregunta_respeta_el_contrato() -> None:
    """Sin pregunta, la maqueta no muestra marca ni top, como pide el contrato."""
    codigo = leer_vista()
    assert 'if (estado.modo === "ejemplo" && !pregunta) {' in codigo
    assert "marca = null;" in codigo
    assert "top = [];" in codigo


def test_estados_de_error_y_respuestas_viejas() -> None:
    """Hay error con reintento y se descartan respuestas de consultas anteriores."""
    codigo = leer_vista()
    assert "Reintentar" in codigo
    assert 'setAttribute("role", "alert")' in codigo
    assert codigo.count("if (numero !== ultimaConsulta) {") == 2


def test_enlaces_de_fuente_validados() -> None:
    """La fuente solo se enlaza si es http/https y abre en otra pestaña sin ``opener``."""
    codigo = leer_vista()
    assert "esUrlSegura(fragmento.url)" in codigo
    assert 'enlace.target = "_blank"' in codigo
    assert 'enlace.rel = "noopener noreferrer"' in codigo


def test_estilos_de_la_boveda_usan_variables_y_su_prefijo() -> None:
    """El bloque de la Bóveda usa solo variables de la base y clases ``.boveda``."""
    bloque = bloque_css()
    sin_comentarios = re.sub(r"/\*.*?\*/", "", bloque, flags=re.DOTALL)
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b", sin_comentarios)
    assert not re.search(r"\b(rgba?|hsla?)\(", sin_comentarios)
    for selector in re.findall(r"([^{}]+)\{", sin_comentarios):
        for parte in selector.split(","):
            limpio = parte.strip()
            if limpio and not limpio.startswith("@"):
                assert limpio.startswith(".boveda"), limpio
