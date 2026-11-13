"""Pruebas sin red del mapa PCA de la Bóveda (PR 11, tareas 14.1 y 14.2).

Ninguna prueba llama a Ollama: los vectores salen de `DeterministicFakeEmbedding`
y el almacén se instancia en `tmp_path`.
"""

from __future__ import annotations

import json
import math
from dataclasses import asdict
from pathlib import Path
from typing import Any

import pytest
from langchain_core.embeddings import DeterministicFakeEmbedding

from banco_occidente_corpus.boveda.almacen import crear_almacen
from banco_occidente_corpus.boveda.configuracion import ConfiguracionEmbeddings
from banco_occidente_corpus.boveda.fragmentos import ruta_fragmentos
from banco_occidente_corpus.boveda.indice import construir_indice
from banco_occidente_corpus.boveda.mapa import (
    ServicioMapa,
    construir_mapa,
    leer_mapa,
    leer_proyeccion,
    leer_vectores_indexados,
    ruta_mapa,
)
from banco_occidente_corpus.boveda.tipos import Fragmento
from banco_occidente_corpus.config import Config, Paths
from banco_occidente_corpus.utils import write_jsonl

URL = "https://www.bancodeoccidente.com.co/productos"
TEMAS = (
    "Cuota de manejo de la tarjeta débito",
    "Requisitos para abrir una cuenta de ahorros",
    "Crédito de vivienda con tasa fija",
    "Horarios de atención de las oficinas",
    "Historia del banco desde 1965",
    "Seguro de vida para deudores",
    "Transferencias por la app",
)


def make_config(tmp_path: Path) -> Config:
    """Crea una configuración aislada en tmp_path, sin tocar el corpus real."""
    return Config(
        paths=Paths(
            root=tmp_path,
            raw=tmp_path / "data/raw",
            processed=tmp_path / "data/processed",
            gold=tmp_path / "data/gold",
            knowledge=tmp_path / "data/knowledge",
        )
    )


def fragmentos_de_prueba() -> list[Fragmento]:
    """Siete fragmentos con textos distintos y dos secciones."""
    return [
        Fragmento(
            id=f"frag:{numero}",
            texto=texto,
            url=URL,
            titulo=f"Página {numero}",
            seccion="oferta" if numero % 2 else "identidad",
            encabezado="",
            tipo="pagina",
            tokens=8,
        )
        for numero, texto in enumerate(TEMAS)
    ]


def vectores_de(fragmentos: list[Fragmento], size: int = 16) -> list[list[float]]:
    """Vectoriza los textos con embeddings deterministas."""
    return DeterministicFakeEmbedding(size=size).embed_documents([f.texto for f in fragmentos])


class RecuperadorFalso:
    """Recuperador de pruebas que devuelve siempre los dos primeros fragmentos."""

    def __init__(self, fragmentos: list[Fragmento]) -> None:
        """Guarda los fragmentos que devolverá y registra las consultas."""
        self.fragmentos = fragmentos
        self.consultas: list[str] = []

    def buscar(self, consulta: str, k: int = 5) -> list[Fragmento]:
        """Registra la consulta y devuelve hasta dos fragmentos."""
        self.consultas.append(consulta)
        return self.fragmentos[: min(k, 2)]


def test_un_punto_por_fragmento_entre_0_y_100() -> None:
    """Cada fragmento tiene su punto, en orden, con coordenadas finitas de 0 a 100."""
    fragmentos = fragmentos_de_prueba()
    mapa = construir_mapa(fragmentos, vectores_de(fragmentos))

    puntos = mapa["puntos"]
    assert [p["id"] for p in puntos] == [f.id for f in fragmentos]
    assert [p["titulo"] for p in puntos] == [f.titulo for f in fragmentos]
    assert [p["seccion"] for p in puntos] == [f.seccion for f in fragmentos]
    for punto in puntos:
        for eje in ("x", "y"):
            assert math.isfinite(punto[eje])
            assert 0 <= punto[eje] <= 100
    for eje in ("x", "y"):
        valores = [p[eje] for p in puntos]
        assert min(valores) == 0
        assert max(valores) == 100


def test_mapa_es_determinista() -> None:
    """Dos ejecuciones con los mismos vectores dan exactamente el mismo mapa."""
    fragmentos = fragmentos_de_prueba()
    vectores = vectores_de(fragmentos)

    assert construir_mapa(fragmentos, vectores) == construir_mapa(fragmentos, vectores)


def test_proyeccion_ubica_un_fragmento_en_su_propio_punto() -> None:
    """La transformación guardada lleva el vector de un fragmento a su mismo punto."""
    fragmentos = fragmentos_de_prueba()
    vectores = vectores_de(fragmentos)
    mapa = construir_mapa(fragmentos, vectores)
    proyeccion = leer_proyeccion(mapa)
    assert proyeccion is not None

    for punto, vector in zip(mapa["puntos"], vectores, strict=True):
        ubicado = proyeccion.ubicar(vector)
        assert ubicado["x"] == pytest.approx(punto["x"], abs=0.011)
        assert ubicado["y"] == pytest.approx(punto["y"], abs=0.011)


def test_proyeccion_recorta_y_rechaza_otra_dimension() -> None:
    """Una pregunta lejana queda dentro de 0–100 y otra dimensión se rechaza."""
    fragmentos = fragmentos_de_prueba()
    mapa = construir_mapa(fragmentos, vectores_de(fragmentos))
    proyeccion = leer_proyeccion(mapa)
    assert proyeccion is not None

    lejana = DeterministicFakeEmbedding(size=16).embed_query("algo sin relación")
    ubicada = proyeccion.ubicar(lejana)
    assert 0 <= ubicada["x"] <= 100
    assert 0 <= ubicada["y"] <= 100
    with pytest.raises(ValueError, match="dimensión"):
        proyeccion.ubicar([1.0, 2.0])


@pytest.mark.parametrize(
    ("cantidad", "mensaje"),
    [(1, "al menos dos"), (0, "al menos dos")],
)
def test_mapa_necesita_dos_fragmentos(cantidad: int, mensaje: str) -> None:
    """PCA de dos componentes necesita al menos dos fragmentos."""
    fragmentos = fragmentos_de_prueba()[:cantidad]
    with pytest.raises(ValueError, match=mensaje):
        construir_mapa(fragmentos, vectores_de(fragmentos) if fragmentos else [])


def test_mapa_rechaza_listas_de_distinto_tamano() -> None:
    """Fragmentos y vectores deben venir en pares."""
    fragmentos = fragmentos_de_prueba()
    with pytest.raises(ValueError, match="deben coincidir"):
        construir_mapa(fragmentos, vectores_de(fragmentos)[:-1])


def test_mapa_rechaza_vectores_nulos() -> None:
    """Un vector de ceros no tiene dirección y no se puede ubicar."""
    fragmentos = fragmentos_de_prueba()[:3]
    vectores = vectores_de(fragmentos)
    vectores[1] = [0.0] * len(vectores[1])
    with pytest.raises(ValueError, match="nulos"):
        construir_mapa(fragmentos, vectores)


def preparar_indice(tmp_path: Path) -> tuple[Config, list[Fragmento]]:
    """Escribe fragmentos y construye un índice real en tmp_path."""
    config = make_config(tmp_path)
    fragmentos = fragmentos_de_prueba()
    write_jsonl(ruta_fragmentos(config, "base"), [asdict(f) for f in fragmentos])
    construir_indice(
        config,
        "base",
        configuracion=ConfiguracionEmbeddings(prefijos=True),
        embeddings=DeterministicFakeEmbedding(size=16),
        almacen=crear_almacen(config),
    )
    return config, fragmentos


def test_make_indice_regenera_el_mapa(tmp_path: Path) -> None:
    """Construir el índice escribe mapa.json con un punto por fragmento y su proyección."""
    config, fragmentos = preparar_indice(tmp_path)

    mapa = leer_mapa(config)
    assert mapa is not None
    assert mapa["alcance"] == "base"
    assert [p["id"] for p in mapa["puntos"]] == [f.id for f in fragmentos]
    assert leer_proyeccion(mapa) is not None


def test_mapa_ausente_se_calcula_una_vez_desde_el_indice(tmp_path: Path) -> None:
    """Si falta mapa.json, el servicio lo recalcula con los vectores de Chroma y lo escribe."""
    config, fragmentos = preparar_indice(tmp_path)
    original = leer_mapa(config)
    ruta_mapa(config).unlink()

    leidos, vectores = leer_vectores_indexados(config)
    recalculado = ServicioMapa(config).mapa()

    assert [f.id for f in leidos] == [f.id for f in fragmentos]
    assert len(vectores) == len(fragmentos)
    assert recalculado is not None
    assert ruta_mapa(config).exists()
    assert original is not None
    for nuevo, viejo in zip(recalculado["puntos"], original["puntos"], strict=True):
        assert nuevo["id"] == viejo["id"]
        assert nuevo["x"] == pytest.approx(viejo["x"], abs=0.011)
        assert nuevo["y"] == pytest.approx(viejo["y"], abs=0.011)


def test_sin_indice_no_hay_mapa(tmp_path: Path) -> None:
    """Sin índice ni mapa.json el servicio responde None, sin inventar puntos."""
    assert ServicioMapa(make_config(tmp_path)).mapa() is None


def test_servicio_ubica_la_pregunta_y_da_el_top(tmp_path: Path) -> None:
    """La pregunta se proyecta con la transformación guardada y el top viene del recuperador."""
    config = make_config(tmp_path)
    fragmentos = fragmentos_de_prueba()
    vectores = vectores_de(fragmentos)
    recuperador = RecuperadorFalso(fragmentos)
    servicio = ServicioMapa(
        config,
        embeddings=lambda: DeterministicFakeEmbedding(size=16),
        recuperador=lambda: recuperador,
        vectores=lambda: (fragmentos, vectores),
    )

    mapa = servicio.mapa()
    assert mapa is not None
    ubicada = servicio.ubicar(mapa, "¿Cuánto cuesta la cuota de manejo?")
    top: list[dict[str, Any]] = servicio.top("¿Cuánto cuesta la cuota de manejo?")

    assert 0 <= ubicada["x"] <= 100
    assert 0 <= ubicada["y"] <= 100
    assert [item["id"] for item in top] == ["frag:0", "frag:1"]
    assert set(top[0]) == {
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
    assert recuperador.consultas == ["¿Cuánto cuesta la cuota de manejo?"]


def test_mapa_sin_proyeccion_pide_reindexar(tmp_path: Path) -> None:
    """Un mapa viejo sin transformación no permite ubicar la pregunta."""
    config = make_config(tmp_path)
    ruta_mapa(config).parent.mkdir(parents=True)
    ruta_mapa(config).write_text(json.dumps({"puntos": []}), encoding="utf-8")
    servicio = ServicioMapa(config, embeddings=lambda: DeterministicFakeEmbedding(size=16))

    mapa = servicio.mapa()
    assert mapa is not None
    with pytest.raises(ValueError, match="make indice"):
        servicio.ubicar(mapa, "pregunta")
