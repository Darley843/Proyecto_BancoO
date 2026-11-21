"""Pruebas de la sección ``dominio`` del Arqueo (tarea 7.5).

La sección mide el filtro de dominio del Digiturno real, solo con reglas, sobre
``data/evaluacion/filtro_dominio.jsonl``. Se verifica que las cifras coinciden
con ``evaluar_filtro``, que la corrida es determinista, que no se publica el
texto de los casos y que el Markdown sale del mismo bloque del JSON.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from banco_occidente_corpus.arqueo.filtro_digiturno import (
    RUTA_CONJUNTO,
    clasificador_digiturno,
    markdown_dominio,
    seccion_dominio,
)
from banco_occidente_corpus.arqueo.filtro_dominio import cargar_casos, evaluar_filtro

ID_CASO = re.compile(r"^(dentro|fuera|frontera)-\d{3}$")
"""Forma de los ids del conjunto."""


def test_la_seccion_cuenta_los_casos_del_conjunto() -> None:
    """Los conteos por categoría coinciden con el JSONL versionado."""
    casos = cargar_casos(RUTA_CONJUNTO)

    seccion = seccion_dominio()

    assert seccion["modo"] == "solo_reglas"
    assert seccion["conjunto"] == "data/evaluacion/filtro_dominio.jsonl"
    assert sum(seccion["casos"].values()) == len(casos)
    assert seccion["fuga"]["n"] == seccion["casos"]["fuera"]
    assert seccion["rechazo_indebido"]["n"] == seccion["casos"]["dentro"]
    assert seccion["acierto_frontera"]["n"] == seccion["casos"]["frontera"]
    assert sum(seccion["decidio"].values()) == len(casos)


def test_las_cifras_coinciden_con_evaluar_filtro() -> None:
    """Éxitos, totales e ids son los mismos que da la evaluación directa."""
    resultado = evaluar_filtro(cargar_casos(RUTA_CONJUNTO), clasificador_digiturno())

    seccion = seccion_dominio()

    for clave, intervalo, ids in (
        ("fuga", resultado.fuga, resultado.ids_fuga),
        ("rechazo_indebido", resultado.rechazo_indebido, resultado.ids_rechazo_indebido),
        ("acierto_frontera", resultado.acierto_frontera, resultado.ids_frontera_fallidos),
    ):
        assert intervalo is not None
        assert seccion[clave]["exitos"] == intervalo.exitos
        assert seccion[clave]["n"] == intervalo.n
        assert seccion[clave]["ids"] == list(ids)
        assert abs(seccion[clave]["proporcion"] - intervalo.proporcion) < 1e-6
        assert abs(seccion[clave]["inferior"] - intervalo.inferior) < 1e-6
        assert abs(seccion[clave]["superior"] - intervalo.superior) < 1e-6


def test_la_seccion_es_determinista() -> None:
    """Dos corridas seguidas producen exactamente el mismo JSON."""
    primera = json.dumps(seccion_dominio(), ensure_ascii=False, sort_keys=True)
    segunda = json.dumps(seccion_dominio(), ensure_ascii=False, sort_keys=True)

    assert primera == segunda


def test_no_se_publica_el_texto_de_los_casos() -> None:
    """El JSON y el Markdown solo llevan ids, nunca el texto de un caso."""
    casos = cargar_casos(RUTA_CONJUNTO)
    seccion = seccion_dominio()
    publicado = json.dumps(seccion, ensure_ascii=False) + "\n".join(markdown_dominio(seccion))

    assert not [caso.id for caso in casos if caso.texto in publicado]
    for clave in ("fuga", "rechazo_indebido", "acierto_frontera"):
        assert all(ID_CASO.match(ident) for ident in seccion[clave]["ids"])


def test_el_markdown_sale_del_mismo_bloque_del_json() -> None:
    """Cada fila de la tabla muestra el conteo y el intervalo del JSON."""
    seccion = seccion_dominio()

    texto = "\n".join(markdown_dominio(seccion))

    assert texto.startswith("## Filtro de dominio")
    for clave in ("fuga", "rechazo_indebido", "acierto_frontera"):
        datos = seccion[clave]
        inferior = f"{datos['inferior'] * 100:.1f}".replace(".", ",") + " %"
        assert f"| {datos['exitos']}/{datos['n']} |" in texto
        assert inferior in texto
    assert "cota superior" in texto
    assert "Dudas" in texto
    assert "Quién decidió" in texto


def test_las_dudas_se_cuentan_por_categoria() -> None:
    """Las dudas son los casos sin regla que decida y el Markdown las informa."""
    seccion = seccion_dominio()

    texto = "\n".join(markdown_dominio(seccion))

    assert set(seccion["dudas"]) == {"dentro", "fuera", "frontera"}
    assert sum(seccion["dudas"].values()) == seccion["decidio"].get("regla defecto", 0)
    assert f"fuera {seccion['dudas']['fuera']} de {seccion['casos']['fuera']}" in texto


def test_muchos_ids_no_saturan_la_tabla() -> None:
    """Con más de diez casos con error, la tabla remite al JSON en vez de listarlos."""
    seccion = seccion_dominio()
    seccion["fuga"] = {**seccion["fuga"], "ids": [f"fuera-{i:03d}" for i in range(1, 12)]}

    texto = "\n".join(markdown_dominio(seccion))

    assert "11 casos; la lista está en `arqueo.json`" in texto
    assert "fuera-011" not in texto


def test_sin_seccion_el_markdown_lo_dice() -> None:
    """Un Arqueo sin bloque ``dominio`` no inventa cifras."""
    lineas = markdown_dominio(None)

    assert lineas[0] == "## Filtro de dominio"
    assert "No se midió" in "\n".join(lineas)


def test_un_conjunto_pequeno_fuera_del_repositorio(tmp_path: Path) -> None:
    """Con otro conjunto la sección usa su nombre y sus propios conteos."""
    origen = cargar_casos(RUTA_CONJUNTO)
    elegidos = [
        next(caso for caso in origen if caso.categoria.value == categoria)
        for categoria in ("dentro", "fuera")
    ]
    ruta = tmp_path / "mini.jsonl"
    ruta.write_text("\n".join(caso.model_dump_json() for caso in elegidos) + "\n", encoding="utf-8")

    seccion = seccion_dominio(ruta)

    assert seccion["conjunto"] == "mini.jsonl"
    assert seccion["casos"] == {"dentro": 1, "fuera": 1, "frontera": 0}
    assert seccion["acierto_frontera"]["n"] == 0
    assert "| Acierto en frontera | 0 | — | — |" in "\n".join(markdown_dominio(seccion))
