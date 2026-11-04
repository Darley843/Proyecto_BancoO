"""Pruebas sin red ni navegador de la app web de la sucursal (PR 12).

Comprueban la tarea 15.1 (armazón y seis vistas sin framework) y la forma de
los datos de ejemplo de la tarea 15.2 contra el contrato de ``design.md``.
Cuando el PR 10 publique los modelos Pydantic de la API, la comparación de
campos se hará contra esos modelos en lugar de las claves escritas aquí.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

RAIZ = Path(__file__).resolve().parents[1]
WEB = RAIZ / "app" / "web"
DATOS = WEB / "datos-ejemplo"

VISTAS = ("vestibulo", "ventanilla", "boveda", "tablero", "camara", "arqueo")

# Claves de primer nivel de cada respuesta, copiadas del contrato "API JSON".
CONTRATO: dict[str, set[str]] = {
    "estado": {
        "modo_demo",
        "gasto_hoy_usd",
        "tope_usd",
        "indice_listo",
        "fragmentos_indexados",
        "modelo_embeddings",
    },
    "preguntar": {
        "turno",
        "turno_numero",
        "ruta",
        "motivo",
        "uso_modelo",
        "reformulada",
        "respuesta",
        "fuentes",
        "tokens_entrada",
        "tokens_salida",
        "tokens_cache",
        "costo_usd",
        "tiempo_s",
        "cache",
    },
    "tablero": {"filas", "total"},
    "mapa": {"puntos", "pregunta", "top"},
    "pipeline": {"etapas", "fuentes", "repeticiones", "indexacion"},
    "arqueo": {"disponible", "datos", "error"},
    "vestibulo": {"hitos"},
}

CAMPOS_FILA = {
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
}
CAMPOS_FRAGMENTO = {
    "id",
    "texto",
    "url",
    "titulo",
    "seccion",
    "encabezado",
    "tipo",
    "tokens",
    "puntaje",
}


def leer(nombre: str) -> Any:
    """Lee un archivo de ``datos-ejemplo/`` como JSON."""
    return json.loads((DATOS / f"{nombre}.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("nombre", sorted(CONTRATO))
def test_datos_ejemplo_tienen_las_claves_del_contrato(nombre: str) -> None:
    """Cada archivo de ejemplo tiene exactamente las claves de su endpoint."""
    assert set(leer(nombre)) == CONTRATO[nombre]


def test_no_sobran_archivos_de_ejemplo() -> None:
    """Solo existen los siete archivos que pide la tarea 15.2."""
    assert {ruta.stem for ruta in DATOS.glob("*.json")} == set(CONTRATO)


def test_preguntar_usa_letras_y_rutas_validas() -> None:
    """El turno es B, T o X y la ruta es una de las tres del Digiturno."""
    datos = leer("preguntar")
    assert datos["turno"] in {"B", "T", "X"}
    assert datos["ruta"] in {"boveda", "tablero", "rechazo"}
    assert all(
        {"n", "titulo", "url", "seccion", "tipo", "similitud"} <= set(f) for f in datos["fuentes"]
    )


def test_tablero_tiene_filas_completas() -> None:
    """Cada fila trae todas las columnas del CSV y ``total`` coincide."""
    datos = leer("tablero")
    assert all(set(fila) == CAMPOS_FILA for fila in datos["filas"])
    assert datos["total"] == len(datos["filas"])


def test_mapa_tiene_coordenadas_entre_0_y_100() -> None:
    """Puntos y pregunta vienen normalizados de 0 a 100, como hace el servidor."""
    datos = leer("mapa")
    coordenadas = [*datos["puntos"], datos["pregunta"]]
    assert all(0 <= p["x"] <= 100 and 0 <= p["y"] <= 100 for p in coordenadas)
    assert all(set(f) == CAMPOS_FRAGMENTO for f in datos["top"])
    assert all(0 <= f["puntaje"] <= 1 for f in datos["top"])


def test_vistas_existen_y_exportan_render() -> None:
    """Hay un archivo por vista y cada uno exporta ``render``."""
    for vista in VISTAS:
        codigo = (WEB / "vistas" / f"{vista}.js").read_text(encoding="utf-8")
        assert "export async function render(contenedor, estado)" in codigo


def test_navegacion_lleva_a_las_seis_vistas() -> None:
    """``index.html`` tiene un enlace y un contenedor por cada vista."""
    html = (WEB / "index.html").read_text(encoding="utf-8")
    for vista in VISTAS:
        assert f'href="#{vista}"' in html
        assert f'id="vista-{vista}"' in html


def test_sin_librerias_externas_ni_html_inyectado() -> None:
    """No se carga nada desde internet y ningún archivo usa ``innerHTML``."""
    archivos = [WEB / "index.html", *WEB.rglob("*.js")]
    for archivo in archivos:
        texto = archivo.read_text(encoding="utf-8")
        assert not re.search(r"""(src|href)=["']https?://""", texto), archivo.name
        assert "innerHTML" not in texto, archivo.name


def test_funciones_javascript_documentadas() -> None:
    """Toda función de JavaScript va precedida de un comentario JSDoc."""
    patron = re.compile(r"^(export )?(async )?function \w+", re.MULTILINE)
    for archivo in WEB.rglob("*.js"):
        texto = archivo.read_text(encoding="utf-8")
        for coincidencia in patron.finditer(texto):
            previo = texto[: coincidencia.start()].rstrip()
            assert previo.endswith("*/"), f"{archivo.name}: {coincidencia.group(0)}"
