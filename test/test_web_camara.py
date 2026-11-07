"""Pruebas sin red ni navegador de la Cámara de compensación (PR 16).

Comprueban la forma de ``datos-ejemplo/pipeline.json`` frente a
``panel.pipeline_summary`` (tarea 19.1) y que la vista distingue avisos y
estado del índice de los errores (tarea 19.2). La 19.1 se completa al
verificar contra ``/api/pipeline`` real (PR 10).
"""

from __future__ import annotations

import json
import re
from dataclasses import fields
from pathlib import Path
from typing import Any

from banco_occidente_corpus.panel import Metric, Repetitions, Stage

RAIZ = Path(__file__).resolve().parents[1]
WEB = RAIZ / "app" / "web"
EJEMPLO = WEB / "datos-ejemplo" / "pipeline.json"
VISTA = WEB / "vistas" / "camara.js"

ETAPAS = ("discover", "fetch", "extract", "dedupe", "gold")


def leer_ejemplo() -> dict[str, Any]:
    """Lee ``app/web/datos-ejemplo/pipeline.json``."""
    return json.loads(EJEMPLO.read_text(encoding="utf-8"))


def leer_vista() -> str:
    """Lee el código de la vista Cámara."""
    return VISTA.read_text(encoding="utf-8")


def bloque_css() -> str:
    """Devuelve el bloque CSS de la Cámara, entre sus marcadores."""
    css = (WEB / "estilos.css").read_text(encoding="utf-8")
    inicio = css.index("/* --- camara (PR 16) --- */")
    fin = css.index("/* --- fin camara --- */", inicio)
    return css[inicio:fin]


def test_etapas_de_ejemplo_tienen_la_forma_de_stage() -> None:
    """Cada etapa trae los campos de ``panel.Stage`` y las métricas los de ``Metric``."""
    campos_etapa = {campo.name for campo in fields(Stage)}
    campos_metrica = {campo.name for campo in fields(Metric)}
    etapas = leer_ejemplo()["etapas"]
    assert tuple(etapa["key"] for etapa in etapas) == ETAPAS
    for etapa in etapas:
        assert set(etapa) == campos_etapa
        for metrica in etapa["metrics"]:
            assert set(metrica) == campos_metrica
            assert isinstance(metrica["value"], str)
            assert re.search(r"\d,\d{3}\b|\d\.\d\b", metrica["value"]) is None, metrica


def test_repeticiones_de_ejemplo_tienen_la_forma_de_repetitions() -> None:
    """El detalle de repeticiones usa los campos de ``panel.Repetitions``."""
    repeticiones = leer_ejemplo()["repeticiones"]
    assert set(repeticiones) == {campo.name for campo in fields(Repetitions)}
    for fila in repeticiones["thresholds"]:
        assert 0 <= fila["percentage"] <= 100


def test_indexacion_de_ejemplo() -> None:
    """La etapa nueva trae estado, fragmentos, modelo y alcance."""
    indexacion = leer_ejemplo()["indexacion"]
    assert set(indexacion) == {
        "indice_listo",
        "fragmentos_indexados",
        "modelo_embeddings",
        "alcance",
    }
    assert isinstance(indexacion["indice_listo"], bool)
    assert isinstance(indexacion["fragmentos_indexados"], int)


def test_fuentes_de_ejemplo_son_rutas_relativas() -> None:
    """Las rutas no revelan carpetas del equipo de quien generó el ejemplo."""
    for ruta in leer_ejemplo()["fuentes"]:
        assert ruta.startswith("data/"), ruta


def test_ejemplo_tiene_avisos_y_etapas_sin_aviso() -> None:
    """El ejemplo sirve para revisar los dos casos: etapas con aviso y sin aviso."""
    avisos = [bool(etapa["warning"]) for etapa in leer_ejemplo()["etapas"]]
    assert any(avisos)
    assert not all(avisos)


def test_vista_pide_el_pipeline_y_no_hace_peticiones_propias() -> None:
    """La vista usa el contrato y no lee archivos ni la red por su cuenta."""
    codigo = leer_vista()
    assert 'estado.pedir("pipeline")' in codigo
    for prohibido in ("fetch(", "innerHTML", "localStorage", "sessionStorage", '"preguntar"'):
        assert prohibido not in codigo, prohibido


def test_aviso_no_se_pinta_como_error() -> None:
    """Los avisos de etapa y el índice pendiente usan estilo de aviso, no de error."""
    codigo = leer_vista()
    assert '"camara__aviso"' in codigo
    assert "camara__aviso camara__aviso--pendiente" in codigo
    assert "Un aviso no es un error" in codigo
    assert codigo.count("aviso--error") == 1
    assert "crearError(error" in codigo


def test_indice_pendiente_se_explica() -> None:
    """Sin índice, la vista dice que es un paso pendiente y cómo crearlo."""
    codigo = leer_vista()
    assert 'listo ? ["Índice listo", "ok"] : ["Pendiente", "pendiente"]' in codigo
    assert "make indice" in codigo


def test_estilos_de_la_camara_usan_variables_y_su_prefijo() -> None:
    """El bloque de la Cámara usa solo variables de la base y clases ``.camara``."""
    bloque = bloque_css()
    sin_comentarios = re.sub(r"/\*.*?\*/", "", bloque, flags=re.DOTALL)
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b", sin_comentarios)
    assert not re.search(r"\b(rgba?|hsla?)\(", sin_comentarios)
    for selector in re.findall(r"([^{}]+)\{", sin_comentarios):
        for parte in selector.split(","):
            limpio = parte.strip()
            if limpio and not limpio.startswith("@"):
                assert limpio.startswith(".camara"), limpio
