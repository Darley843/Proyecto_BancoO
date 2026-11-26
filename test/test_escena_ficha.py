"""La ficha de respuestas fijas de Pana en `config/escena.toml` (tarea 6.14).

Cada entrada sale de la «Voz» de una pregunta de `docs/PRESENTADOR.md` y se
revisa aquí con las mismas reglas que aplica `escena/pregunta.py` antes de
usarla: fuente que existe, máximo tres frases y 40 palabras, toda cifra dura
declarada y sin datos personales. Además, cada variante elige su propia entrada
y una pregunta parecida que no llega al umbral no se responde como fija.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest

from banco_occidente_corpus.asistente.validacion import cifras_duras, contar_palabras, detectar_pii
from banco_occidente_corpus.config import PROJECT_ROOT
from banco_occidente_corpus.escena import pregunta
from banco_occidente_corpus.escena.pregunta import (
    EntradaFija,
    cargar_ficha,
    cargar_limites_pregunta,
)

RUTA_TOML = PROJECT_ROOT / "config" / "escena.toml"
RUTA_FICHA = PROJECT_ROOT / "docs" / "PRESENTADOR.md"
FICHA = cargar_ficha()
LIMITES = cargar_limites_pregunta()


def _crudas() -> list[dict[str, object]]:
    with RUTA_TOML.open("rb") as archivo:
        return list(tomllib.load(archivo)["preguntas"]["fijas"])


def _ids(entradas: tuple[EntradaFija, ...]) -> list[str]:
    return [entrada.id for entrada in entradas]


def test_se_cargan_las_22_y_ninguna_se_descarta() -> None:
    """Las 22 preguntas de la ficha cargan: ninguna pierde su fuente al leerse."""
    assert len(_crudas()) == 22
    assert _ids(FICHA.entradas) == [str(dato["id"]) for dato in _crudas()]
    assert len(set(_ids(FICHA.entradas))) == 22


@pytest.mark.parametrize("entrada", FICHA.entradas, ids=_ids(FICHA.entradas))
def test_cada_fuente_es_un_ancla_de_la_ficha_que_existe(entrada: EntradaFija) -> None:
    """La fuente apunta a `docs/PRESENTADOR.md#pN` y esa ancla está en el archivo."""
    coincidencia = re.fullmatch(r"docs/PRESENTADOR\.md#(p\d{1,2})", entrada.fuente)
    assert coincidencia is not None
    assert f'<a id="{coincidencia.group(1)}"></a>' in RUTA_FICHA.read_text(encoding="utf-8")


@pytest.mark.parametrize("entrada", FICHA.entradas, ids=_ids(FICHA.entradas))
def test_cada_respuesta_cumple_el_contrato_de_la_voz(entrada: EntradaFija) -> None:
    """Máximo tres frases y 40 palabras, cifras declaradas y sin datos personales."""
    assert pregunta._entrada_valida(entrada, LIMITES)
    assert contar_palabras(entrada.respuesta) <= LIMITES.max_palabras
    assert pregunta._contar_frases(entrada.respuesta) <= 3
    declaradas = {pregunta._canonica(cifra.valor) for cifra in entrada.cifras}
    assert cifras_duras(entrada.respuesta) <= declaradas
    for texto in (entrada.respuesta, *entrada.variantes):
        assert not detectar_pii(texto)


@pytest.mark.parametrize("entrada", FICHA.entradas, ids=_ids(FICHA.entradas))
def test_cada_variante_elige_su_propia_entrada(entrada: EntradaFija) -> None:
    """Dos variantes de la misma pregunta devuelven la misma entrada."""
    for variante in entrada.variantes:
        elegida = pregunta._buscar_fija(variante, FICHA, LIMITES)
        assert elegida is not None
        assert elegida.id == entrada.id


@pytest.mark.parametrize(
    ("texto", "esperado"),
    [
        ("¿Cómo está dividido el proyecto?", "codigo"),
        ("¿Muéstrame los PR?", "repositorio"),
        ("¿Qué es un token?", "git_tokens"),
        ("¿Tienen diagramas?", "diagrama"),
        ("¿Cómo prueban?", "pruebas"),
        ("Cuéntame del proyecto", "proyecto"),
        ("Cuéntanos del proyecto", "proyecto"),
        ("Háblame del proyecto", "proyecto"),
        ("Dame un resumen del proyecto", "proyecto"),
        ("¿En qué consiste el proyecto?", "proyecto"),
        ("Cuéntame de la Sucursal 1965", "proyecto"),
    ],
)
def test_las_preguntas_del_profesor_llegan_a_su_entrada(texto: str, esperado: str) -> None:
    """Las formas cortas que usa el profesor no caen al rechazo."""
    elegida = pregunta._buscar_fija(texto, FICHA, LIMITES)
    assert elegida is not None
    assert elegida.id == esperado


@pytest.mark.parametrize(
    "parecida",
    ["¿Qué es Qdrant?", "¿Quién es Karol G?", "¿Cuánto cuesta un CDT?", "¿Qué es el comité?"],
)
def test_una_pregunta_parecida_bajo_el_umbral_no_es_fija(parecida: str) -> None:
    """Una pregunta que no llega a `umbral_fijo` sigue al paso siguiente."""
    assert pregunta._buscar_fija(parecida, FICHA, LIMITES) is None


def test_la_ficha_no_tiene_telefonos_correos_ni_documentos() -> None:
    """El bloque de la ficha en el TOML no trae datos personales."""
    texto = RUTA_TOML.read_text(encoding="utf-8")
    inicio = texto.index("[[preguntas.fijas]]")
    assert not detectar_pii(texto[inicio:])


def test_un_toml_con_otra_raiz_sin_la_ficha_no_carga_entradas(tmp_path: Path) -> None:
    """Si `docs/PRESENTADOR.md` no existe en la raíz, ninguna entrada se usa."""
    assert cargar_ficha(RUTA_TOML, raiz=tmp_path).entradas == ()
