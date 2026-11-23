"""Pruebas de la proyección t-SNE de la Bóveda.

Usan vectores sintéticos con grupos conocidos: no leen el índice ni llaman a
Ollama. Comprueban la pureza, la semilla fija, los fallos, la figura y la
escritura de las salidas.
"""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pytest

from banco_occidente_corpus.arqueo.experimentos import PreguntaFase2
from banco_occidente_corpus.arqueo.proyeccion import (
    OTRAS,
    agrupar,
    ajustar_tsne,
    construir_proyeccion,
    dibujar_svg,
    ejecutar,
    perplejidad_efectiva,
    pureza_vecindario,
    resumen,
    unitarios,
)

#: Dimensión de los vectores sintéticos.
DIMENSION = 16
#: Fragmentos por sección sintética.
POR_SECCION = 20
#: Secciones sintéticas y la URL de cada una.
SECCIONES = {
    "personas": "https://banco.test/personas",
    "empresas": "https://banco.test/empresas",
    "nuestro-banco": "https://banco.test/nuestro-banco",
}


@dataclass(frozen=True, slots=True)
class FragmentoFalso:
    """Lo mínimo de un fragmento que usa la proyección."""

    id: str
    url: str
    seccion: str


def _centros() -> dict[str, np.ndarray]:
    """Un eje distinto para cada sección, así los grupos quedan separados."""
    return {seccion: np.eye(DIMENSION)[indice] * 5 for indice, seccion in enumerate(SECCIONES)}


def _indice(semilla: int = 7) -> tuple[list[FragmentoFalso], np.ndarray]:
    """Fragmentos sintéticos con ruido pequeño alrededor de su centro."""
    azar = np.random.default_rng(semilla)
    fragmentos: list[FragmentoFalso] = []
    vectores: list[np.ndarray] = []
    for seccion, centro in _centros().items():
        for numero in range(POR_SECCION):
            fragmentos.append(
                FragmentoFalso(
                    id=f"{seccion}-{numero}",
                    url=SECCIONES[seccion],
                    seccion=seccion,
                )
            )
            vectores.append(centro + azar.normal(0, 0.3, DIMENSION))
    return fragmentos, np.asarray(vectores)


def _pregunta(identificador: int, url: str) -> PreguntaFase2:
    """Pregunta evaluable con una fuente esperada."""
    return PreguntaFase2(
        id=identificador,
        pregunta=f"Pregunta {identificador}",
        cobertura="",
        tipo="alcance",
        ruta_esperada="B",
        fuentes_esperadas=(url,),
        previa="",
        terminos=(),
    )


def _preguntas() -> tuple[list[PreguntaFase2], np.ndarray, dict[int, int | None]]:
    """Dos preguntas: una cae en su sección y otra cae en una sección ajena."""
    centros = _centros()
    preguntas = [
        _pregunta(1, SECCIONES["personas"]),
        _pregunta(2, SECCIONES["empresas"]),
    ]
    vectores = np.asarray([centros["personas"], centros["nuestro-banco"]])
    posiciones: dict[int, int | None] = {1: 1, 2: None}
    return preguntas, vectores, posiciones


def test_unitarios_normaliza_y_rechaza_vectores_nulos() -> None:
    """Cada fila queda con norma 1; un vector nulo no se puede proyectar."""
    matriz = unitarios([[3.0, 4.0], [0.0, 2.0]])

    assert np.allclose(np.linalg.norm(matriz, axis=1), 1.0)
    with pytest.raises(ValueError, match="nulos"):
        unitarios([[0.0, 0.0], [1.0, 0.0]])
    with pytest.raises(ValueError, match="no finitos"):
        unitarios([[float("nan"), 1.0]])


def test_agrupar_deja_las_secciones_grandes_y_junta_el_resto() -> None:
    """Las secciones principales conservan su nombre y las demás van a «otras»."""
    secciones = ["a"] * 5 + ["b"] * 4 + ["c"] * 3 + ["d"] + [""]

    grupos = agrupar(secciones, maximo=2)

    assert grupos[:9] == ["a"] * 5 + ["b"] * 4
    assert set(grupos[9:]) == {OTRAS}


def test_la_perplejidad_se_recorta_con_pocos_puntos() -> None:
    """t-SNE exige perplejidad menor que el número de puntos."""
    assert perplejidad_efectiva(1000) == 30.0
    assert perplejidad_efectiva(10) == 3.0
    assert perplejidad_efectiva(2) == 1.0


def test_la_pureza_distingue_grupos_separados_de_etiquetas_al_azar() -> None:
    """Con grupos reales la pureza es casi 1; con etiquetas barajadas, cerca del azar."""
    fragmentos, vectores = _indice()
    matriz = unitarios(vectores)
    reales = [fragmento.seccion for fragmento in fragmentos]
    barajadas = list(np.random.default_rng(3).permutation(reales))

    por_grupo, global_real = pureza_vecindario(matriz, reales)
    _, global_azar = pureza_vecindario(matriz, barajadas)

    assert global_real > 0.95
    assert all(valor > 0.95 for valor in por_grupo.values())
    assert global_azar < 0.6


def test_el_tsne_es_reproducible_con_la_misma_semilla() -> None:
    """La misma semilla da las mismas coordenadas; el plano no tiene valores raros."""
    _, vectores = _indice()
    matriz = unitarios(vectores)

    primera, usada = ajustar_tsne(matriz, perplejidad=10)
    segunda, _ = ajustar_tsne(matriz, perplejidad=10)

    assert primera.shape == (len(matriz), 2)
    assert np.all(np.isfinite(primera))
    assert np.allclose(primera, segunda)
    assert usada == 10


def test_ajustar_tsne_rechaza_menos_de_cuatro_puntos() -> None:
    """Con tres puntos no hay vecindario que proyectar."""
    with pytest.raises(ValueError, match="cuatro"):
        ajustar_tsne(unitarios(np.eye(3)))


def test_construir_proyeccion_explica_el_fallo_por_la_seccion_vecina() -> None:
    """La pregunta que falla cae junto a otra sección y su fuente queda lejos."""
    fragmentos, vectores = _indice()
    preguntas, vectores_preguntas, posiciones = _preguntas()

    proyeccion = construir_proyeccion(
        fragmentos,
        vectores,
        preguntas,
        vectores_preguntas,
        posiciones,
        {1: "B", 2: "B"},
        perplejidad=10,
    )

    acierto, fallo = proyeccion.preguntas
    assert acierto.acierto
    assert acierto.grupo_vecino == "personas"
    assert acierto.puesto_esperado == 1
    assert not fallo.acierto
    assert fallo.grupo_vecino == "nuestro-banco"
    assert fallo.grupo_esperado == "empresas"
    assert fallo.puesto_esperado is not None
    assert fallo.puesto_esperado > POR_SECCION
    assert proyeccion.confiabilidad > 0.9
    assert proyeccion.coordenadas.shape == (len(fragmentos), 2)
    assert proyeccion.coordenadas_preguntas.shape == (2, 2)


def test_el_resumen_cuenta_los_fallos_en_otra_seccion() -> None:
    """El JSON trae parámetros, grupos ordenados y el conteo de fallos."""
    fragmentos, vectores = _indice()
    preguntas, vectores_preguntas, posiciones = _preguntas()
    proyeccion = construir_proyeccion(
        fragmentos, vectores, preguntas, vectores_preguntas, posiciones, {}, perplejidad=10
    )

    datos = resumen(proyeccion)

    assert datos["parametros"]["semilla"] == 1965
    assert datos["parametros"]["metrica"] == "coseno"
    assert datos["fragmentos"] == len(fragmentos)
    assert [grupo["fragmentos"] for grupo in datos["grupos"]] == [POR_SECCION] * 3
    assert datos["fallos"] == 1
    assert datos["fallos_en_otra_seccion"] == 1
    json.dumps(datos)


def test_las_listas_deben_coincidir() -> None:
    """Fragmentos y vectores, o preguntas y vectores, de distinto tamaño fallan."""
    fragmentos, vectores = _indice()
    preguntas, vectores_preguntas, posiciones = _preguntas()

    with pytest.raises(ValueError, match="fragmentos"):
        construir_proyeccion(fragmentos[:-1], vectores, [], [], {}, {})
    with pytest.raises(ValueError, match="preguntas"):
        construir_proyeccion(
            fragmentos, vectores, preguntas, vectores_preguntas[:1], posiciones, {}
        )


def test_la_figura_es_un_svg_valido_con_un_punto_por_fragmento() -> None:
    """El SVG se puede leer, tiene un círculo por fragmento y marca aciertos y fallos."""
    fragmentos, vectores = _indice()
    preguntas, vectores_preguntas, posiciones = _preguntas()
    proyeccion = construir_proyeccion(
        fragmentos, vectores, preguntas, vectores_preguntas, posiciones, {}, perplejidad=10
    )

    svg = dibujar_svg(proyeccion)
    raiz = ET.fromstring(svg)
    espacio = "{http://www.w3.org/2000/svg}"
    circulos = raiz.findall(f"{espacio}circle")

    assert len(circulos) == len(fragmentos) + len(SECCIONES)
    assert "Fuente fuera del top 5" in svg
    assert "#C0392B" in svg


def test_ejecutar_escribe_el_json_y_la_figura(tmp_path: Path) -> None:
    """Con índice y vectorizador inyectados, `ejecutar` escribe las dos salidas.

    La pregunta 3 no es evaluable y queda fuera de la proyección.
    """
    fragmentos, vectores = _indice()
    preguntas, vectores_preguntas, _ = _preguntas()
    arqueo = tmp_path / "arqueo.json"
    arqueo.write_text(
        json.dumps(
            {
                "detalle": {
                    "preguntas": [
                        {
                            "id": 1,
                            "evaluable": True,
                            "fuente_indexada": True,
                            "ruta_esperada": "B",
                            "posiciones": {"0.6/0.4": 2},
                        },
                        {
                            "id": 2,
                            "evaluable": True,
                            "fuente_indexada": True,
                            "ruta_esperada": "B",
                            "posiciones": {"0.6/0.4": None},
                        },
                        {
                            "id": 3,
                            "evaluable": False,
                            "fuente_indexada": None,
                            "ruta_esperada": "F",
                            "posiciones": {"0.6/0.4": None},
                        },
                    ]
                }
            }
        ),
        encoding="utf-8",
    )
    por_texto = {
        pregunta.pregunta: vector
        for pregunta, vector in zip(preguntas, vectores_preguntas, strict=True)
    }

    proyeccion = ejecutar(
        leer_indice=lambda: (fragmentos, vectores),
        vectorizar=lambda textos: [list(por_texto[texto]) for texto in textos],
        arqueo=arqueo,
        preguntas=[*preguntas, _pregunta(3, SECCIONES["personas"])],
        json_destino=tmp_path / "proyeccion.json",
        svg_destino=tmp_path / "img" / "proyeccion.svg",
    )

    datos = json.loads((tmp_path / "proyeccion.json").read_text(encoding="utf-8"))
    assert [pregunta.id for pregunta in proyeccion.preguntas] == [1, 2]
    assert datos["fallos"] == 1
    assert (tmp_path / "img" / "proyeccion.svg").read_text(encoding="utf-8").startswith("<svg")
