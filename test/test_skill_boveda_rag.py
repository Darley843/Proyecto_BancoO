"""Controles de calidad de la skill `boveda-rag`, sin Ollama y sin red."""

from __future__ import annotations

import importlib.util
import sys
import tomllib
from collections import Counter
from pathlib import Path
from types import ModuleType

import pytest

from banco_occidente_corpus.boveda.fragmentos import (
    TOKENS_MAXIMOS,
    construir_fragmentos,
)
from banco_occidente_corpus.boveda.tipos import Fragmento
from banco_occidente_corpus.config import load_config

RAIZ = Path(__file__).resolve().parents[1]
PREGUNTAS = RAIZ / "config" / "evaluacion" / "preguntas_fase2.toml"
SCRIPTS = RAIZ / ".opencode" / "skills" / "boveda-rag" / "scripts"
MENU = ("- Canales digitales", "- Segmentos", "- Mesa de dinero")


@pytest.fixture(scope="module")
def fragmentos() -> list[Fragmento]:
    """Construye una vez los fragmentos base del corpus real."""
    return list(construir_fragmentos(load_config(), "base").fragmentos)


@pytest.fixture(scope="module")
def fuentes_esperadas() -> dict[str, list[int]]:
    """Reúne las URL de páginas web esperadas por preguntas de alcance o tabla."""
    datos = tomllib.loads(PREGUNTAS.read_text(encoding="utf-8"))
    fuentes: dict[str, list[int]] = {}
    for pregunta in datos["pregunta"]:
        if pregunta["tipo"] not in {"alcance", "tabla"}:
            continue
        for url in pregunta.get("fuentes_esperadas", []):
            if "/documents/" in url:
                continue
            fuentes.setdefault(url, []).append(int(pregunta["id"]))
    return fuentes


@pytest.fixture(scope="module")
def medir() -> ModuleType:
    """Carga el script de medición por ruta, porque la carpeta lleva guion."""
    return _cargar_script("medir_recuperacion")


def _cargar_script(nombre: str) -> ModuleType:
    """Carga un script de la skill con `importlib` y lo registra en `sys.modules`."""
    ruta = SCRIPTS / f"{nombre}.py"
    especificacion = importlib.util.spec_from_file_location(f"skill_boveda_rag_{nombre}", ruta)
    if especificacion is None or especificacion.loader is None:
        raise RuntimeError(f"No se pudo cargar el script {ruta}")
    modulo = importlib.util.module_from_spec(especificacion)
    sys.modules[especificacion.name] = modulo
    especificacion.loader.exec_module(modulo)
    return modulo


def test_fuentes_esperadas_tienen_fragmento(
    fragmentos: list[Fragmento],
    fuentes_esperadas: dict[str, list[int]],
) -> None:
    """Cada URL esperada de una página web tiene al menos un fragmento."""
    urls = {fragmento.url for fragmento in fragmentos if fragmento.tipo == "pagina"}
    faltantes = [(url, ids) for url, ids in sorted(fuentes_esperadas.items()) if url not in urls]

    assert not faltantes, f"Fuentes sin fragmento: {faltantes}"


def test_ningun_fragmento_supera_400_tokens(fragmentos: list[Fragmento]) -> None:
    """Ningún fragmento supera el límite de tokens del contrato."""
    largos = [
        (fragmento.id, fragmento.tokens)
        for fragmento in fragmentos
        if fragmento.tokens > TOKENS_MAXIMOS
    ]

    assert not largos, f"Fragmentos por encima de {TOKENS_MAXIMOS} tokens: {largos}"


def test_fragmentos_sin_menu_de_navegacion(fragmentos: list[Fragmento]) -> None:
    """Ningún fragmento conserva las líneas del menú de navegación repetido."""
    con_menu = [
        (fragmento.id, linea)
        for fragmento in fragmentos
        for linea in MENU
        if linea in fragmento.texto
    ]

    assert not con_menu, f"Fragmentos con menú de navegación: {con_menu}"


def test_fragmentos_sin_textos_repetidos(fragmentos: list[Fragmento]) -> None:
    """Ningún texto de fragmento se repite tras normalizar los espacios."""
    normalizados = [" ".join(fragmento.texto.split()) for fragmento in fragmentos]
    repetidos = sorted(texto for texto, copias in Counter(normalizados).items() if copias > 1)

    assert not repetidos, f"Textos repetidos: {repetidos[:5]}"


def test_intervalo_wilson_22_de_32(medir: ModuleType) -> None:
    """El intervalo de Wilson de 22 aciertos de 32 va de 0,51 a 0,82."""
    inferior, superior = medir.intervalo_wilson(22, 32)

    assert inferior == pytest.approx(0.51, abs=0.01)
    assert superior == pytest.approx(0.82, abs=0.01)


def test_urls_distintas_conserva_orden_y_limite(medir: ModuleType) -> None:
    """La variante de URL distintas deduplica y conserva el orden de llegada."""
    resultado = medir.urls_distintas(["a", "b", "a", "c", "d", "e", "f"], 5)

    assert resultado == ("a", "b", "c", "d", "e")


def test_consulta_de_une_previa_y_pregunta(medir: ModuleType) -> None:
    """Una pregunta de seguimiento se consulta junto con su previa."""
    seguimiento = medir.Pregunta(
        id=29,
        tipo="seguimiento",
        pregunta="¿Y cuál es su cuota de manejo?",
        previa="¿Qué tarjetas de crédito ofrece?",
        fuentes_esperadas=("https://www.bancodeoccidente.com.co/tarjetas-credito",),
    )
    autonoma = medir.Pregunta(
        id=3,
        tipo="alcance",
        pregunta="¿Cuál es la línea de atención telefónica?",
        previa="",
        fuentes_esperadas=("https://www.bancodeoccidente.com.co/ayuda",),
    )

    assert (
        medir.consulta_de(seguimiento)
        == "¿Qué tarjetas de crédito ofrece? ¿Y cuál es su cuota de manejo?"
    )
    assert medir.consulta_de(autonoma) == autonoma.pregunta


@pytest.mark.parametrize(
    ("consulta", "esperado"),
    [
        ("¿En qué año se fundó el Banco de Occidente?", "¿En qué año se fundó?"),
        ("¿Cuándo y dónde se fundó el banco?", "¿Cuándo y dónde se fundó el banco?"),
        ("¿Qué productos ofrece Banco Occidente?", "¿Qué productos ofrece?"),
        ("¿Banco de Occidente?", "¿Banco de Occidente?"),
    ],
    ids=["marca-completa", "banco-generico", "marca-sin-de", "solo-marca"],
)
def test_limpiar_marca_retira_la_marca(
    medir: ModuleType,
    consulta: str,
    esperado: str,
) -> None:
    """La limpieza quita la marca, cierra los huecos y conserva la original si vacía."""
    assert medir.limpiar_marca(consulta) == esperado


@pytest.mark.parametrize(
    ("consulta", "esperado"),
    [
        (
            "¿Cuándo y dónde se fundó el banco?",
            "¿Cuándo y dónde se fundó el Banco de Occidente?",
        ),
        ("El banco abre los sábados.", "El Banco de Occidente abre los sábados."),
        (
            "¿Cuál es la línea de atención telefónica?",
            "¿Cuál es la línea de atención telefónica del Banco de Occidente?",
        ),
    ],
    ids=["reemplaza-el-banco", "conserva-mayuscula", "agrega-antes-del-cierre"],
)
def test_poner_marca_menciona_el_banco(
    medir: ModuleType,
    consulta: str,
    esperado: str,
) -> None:
    """La inyección reemplaza «el banco» o añade la marca antes del cierre."""
    assert medir.poner_marca(consulta) == esperado
