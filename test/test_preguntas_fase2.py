"""Pruebas sin red del banco de preguntas de la fase 2."""

from __future__ import annotations

import json
import tomllib
from collections import Counter
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
ARCHIVO_PREGUNTAS = RAIZ / "config" / "evaluacion" / "preguntas_fase2.toml"
ARCHIVO_CORPUS = RAIZ / "data" / "gold" / "corpus.jsonl"
ARCHIVO_DOCUMENTOS = RAIZ / "data" / "gold" / "documents.jsonl"

TIPOS = {"alcance", "tabla", "seguimiento", "fuera"}
RUTAS = {"B", "T", "X"}
COBERTURAS = {"si", "parcial", "no"}
CAMPOS_OBLIGATORIOS = {
    "id",
    "pregunta",
    "cobertura",
    "tipo",
    "ruta_esperada",
    "terminos",
    "fuentes_esperadas",
}


@pytest.fixture(scope="module")
def preguntas() -> list[dict[str, object]]:
    """Lee las 44 preguntas del TOML de la fase 2."""
    datos = tomllib.loads(ARCHIVO_PREGUNTAS.read_text(encoding="utf-8"))
    return list(datos["pregunta"])


def _fuentes_de(archivo: Path) -> set[str]:
    """Reune las URLs registradas como fuente en un JSONL del Gold."""
    with archivo.open(encoding="utf-8") as datos:
        return {json.loads(linea)["fuente"] for linea in datos if linea.strip()}


@pytest.fixture(scope="module")
def fuentes_gold() -> set[str]:
    """Reune las URLs de paginas y documentos del Gold, sin normalizar."""
    return _fuentes_de(ARCHIVO_CORPUS) | _fuentes_de(ARCHIVO_DOCUMENTOS)


def test_ids_unicos_del_1_al_44(preguntas: list[dict[str, object]]) -> None:
    """Los ids son unicos y cubren exactamente del 1 al 44."""
    # Arrange
    ids = [int(pregunta["id"]) for pregunta in preguntas]

    # Act
    ids_ordenados = sorted(ids)

    # Assert
    assert len(ids) == 44
    assert len(set(ids)) == 44
    assert ids_ordenados == list(range(1, 45))


def test_conteos_por_tipo(preguntas: list[dict[str, object]]) -> None:
    """Los cuatro tipos incluyen las nuevas preguntas del tarifario."""
    # Act
    conteo = Counter(str(pregunta["tipo"]) for pregunta in preguntas)

    # Assert
    assert dict(conteo) == {
        "alcance": 20,
        "tabla": 12,
        "seguimiento": 6,
        "fuera": 6,
    }


def test_tipo_y_ruta_validos(preguntas: list[dict[str, object]]) -> None:
    """Cada tipo y ruta pertenece al vocabulario y respeta su correspondencia."""
    # Arrange
    esperado: dict[str, set[str]] = {
        "alcance": {"B"},
        "tabla": {"T"},
        "seguimiento": {"B", "T"},
        "fuera": {"X"},
    }
    invalidas: list[tuple[object, object, object]] = []

    # Act
    for pregunta in preguntas:
        tipo = pregunta["tipo"]
        ruta = pregunta["ruta_esperada"]
        if (
            not isinstance(tipo, str)
            or not isinstance(ruta, str)
            or tipo not in TIPOS
            or ruta not in RUTAS
            or ruta not in esperado[tipo]
        ):
            invalidas.append((pregunta["id"], tipo, ruta))

    # Assert
    assert not invalidas


def test_seguimiento_tiene_previa(preguntas: list[dict[str, object]]) -> None:
    """Solo los seguimientos tienen previa, y siempre es texto no vacio."""
    # Arrange
    errores: list[tuple[object, str]] = []

    # Act
    for pregunta in preguntas:
        es_seguimiento = pregunta["tipo"] == "seguimiento"
        previa = pregunta.get("previa")
        if es_seguimiento and (not isinstance(previa, str) or not previa.strip()):
            errores.append((pregunta["id"], "seguimiento sin previa"))
        if not es_seguimiento and "previa" in pregunta:
            errores.append((pregunta["id"], "previa fuera de seguimiento"))

    # Assert
    assert not errores


def test_fuera_sin_fuentes(preguntas: list[dict[str, object]]) -> None:
    """Las preguntas fuera de alcance no declaran fuentes esperadas."""
    # Arrange
    fuera = [pregunta for pregunta in preguntas if pregunta["tipo"] == "fuera"]

    # Act
    con_fuentes = [pregunta["id"] for pregunta in fuera if pregunta["fuentes_esperadas"] != []]

    # Assert
    assert fuera
    assert not con_fuentes


def test_fuentes_esperadas_existen_en_gold(
    preguntas: list[dict[str, object]], fuentes_gold: set[str]
) -> None:
    """Cada URL existe exactamente como fuente en corpus.jsonl o documents.jsonl."""
    # Arrange
    faltantes: list[tuple[object, object]] = []

    # Act
    for pregunta in preguntas:
        fuentes = pregunta["fuentes_esperadas"]
        if not isinstance(fuentes, list):
            faltantes.append((pregunta["id"], "fuentes_esperadas no es lista"))
            continue
        for url in fuentes:
            if not isinstance(url, str) or url not in fuentes_gold:
                faltantes.append((pregunta["id"], url))

    # Assert
    assert not faltantes


def test_campos_obligatorios_y_cobertura(preguntas: list[dict[str, object]]) -> None:
    """Todas las filas traen los campos base y una cobertura valida."""
    # Arrange
    errores: list[tuple[object, object]] = []

    # Act
    for pregunta in preguntas:
        faltan = CAMPOS_OBLIGATORIOS - pregunta.keys()
        if faltan:
            errores.append((pregunta.get("id"), f"faltan {sorted(faltan)}"))

        cobertura = pregunta.get("cobertura")
        if not isinstance(cobertura, str) or cobertura not in COBERTURAS:
            errores.append((pregunta.get("id"), f"cobertura invalida: {cobertura!r}"))

        terminos = pregunta.get("terminos")
        if not isinstance(terminos, list) or not all(isinstance(grupo, list) for grupo in terminos):
            errores.append((pregunta.get("id"), "terminos no es lista de listas"))

        texto = pregunta.get("pregunta")
        if not isinstance(texto, str) or not texto.strip():
            errores.append((pregunta.get("id"), "pregunta vacia"))

    # Assert
    assert not errores
