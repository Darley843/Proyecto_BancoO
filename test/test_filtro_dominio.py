"""Pruebas del conjunto y de las métricas del filtro de dominio."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import pytest

from banco_occidente_corpus.arqueo.filtro_dominio import (
    CasoDominio,
    Categoria,
    Decision,
    cargar_casos,
    evaluar_filtro,
    intervalo,
    reporte_markdown,
)

RAIZ = Path(__file__).resolve().parents[1]
CONJUNTO = RAIZ / "data" / "evaluacion" / "filtro_dominio.jsonl"


# --- Intervalo (usa arqueo.metricas.intervalo_wilson; referencia: scipy.stats.binomtest, method="wilson") ---


@pytest.mark.parametrize(
    ("exitos", "n", "inferior", "superior"),
    [
        (0, 50, 0.0, 0.071348),
        (5, 50, 0.043476, 0.213602),
        (50, 50, 0.928652, 1.0),
        (2, 14, 0.040094, 0.399414),
    ],
)
def test_wilson_coincide_con_referencia(
    exitos: int, n: int, inferior: float, superior: float
) -> None:
    resultado = intervalo(exitos, n)
    assert resultado is not None
    assert resultado.inferior == pytest.approx(inferior, abs=1e-6)
    assert resultado.superior == pytest.approx(superior, abs=1e-6)


def test_wilson_con_cero_errores_no_da_ancho_cero() -> None:
    resultado = intervalo(0, 50)
    assert resultado is not None
    assert resultado.proporcion == 0
    assert resultado.superior > 0.05


def test_wilson_mas_confianza_es_mas_ancho() -> None:
    a95 = intervalo(5, 50, 0.95)
    a99 = intervalo(5, 50, 0.99)
    assert a95 is not None and a99 is not None
    assert a99.superior - a99.inferior > a95.superior - a95.inferior


def test_sin_casos_no_hay_intervalo() -> None:
    assert intervalo(0, 0) is None


@pytest.mark.parametrize(("exitos", "n", "confianza"), [(6, 5, 0.95), (-1, 5, 0.95), (1, 5, 1.0)])
def test_wilson_rechaza_entradas_invalidas(exitos: int, n: int, confianza: float) -> None:
    with pytest.raises(ValueError):
        intervalo(exitos, n, confianza)


def test_como_texto_usa_coma_decimal() -> None:
    resultado = intervalo(0, 50)
    assert resultado is not None
    assert resultado.como_texto() == "0,0 % [0,0 %; 7,1 %]"


# --- Conjunto versionado ---


def test_conjunto_tiene_tamano_minimo_por_grupo() -> None:
    conteo = Counter(c.categoria for c in cargar_casos(CONJUNTO))
    assert conteo[Categoria.DENTRO] >= 50
    assert conteo[Categoria.FUERA] >= 50
    assert conteo[Categoria.FRONTERA] >= 10


def test_conjunto_cubre_las_subcategorias_fuera_de_tema() -> None:
    subcategorias = {
        c.subcategoria for c in cargar_casos(CONJUNTO) if c.categoria is Categoria.FUERA
    }
    assert {"cultura_general", "codigo", "salud", "otros_bancos", "jailbreak"} <= subcategorias


def test_conjunto_sin_textos_repetidos() -> None:
    textos = [c.texto.casefold().strip() for c in cargar_casos(CONJUNTO)]
    assert len(textos) == len(set(textos))


def test_conjunto_frontera_tiene_ambas_decisiones() -> None:
    decisiones = {c.esperado for c in cargar_casos(CONJUNTO) if c.categoria is Categoria.FRONTERA}
    assert decisiones == {Decision.ACEPTAR, Decision.RECHAZAR}


# --- Validación de casos y carga ---


def test_caso_dentro_que_espera_rechazo_es_invalido() -> None:
    with pytest.raises(ValueError):
        CasoDominio(
            id="dentro-001",
            texto="hola",
            esperado=Decision.RECHAZAR,
            categoria=Categoria.DENTRO,
            subcategoria="x",
        )


def test_caso_con_id_de_otra_categoria_es_invalido() -> None:
    with pytest.raises(ValueError):
        CasoDominio(
            id="fuera-001",
            texto="hola",
            esperado=Decision.ACEPTAR,
            categoria=Categoria.DENTRO,
            subcategoria="x",
        )


def test_caso_frontera_exige_nota() -> None:
    with pytest.raises(ValueError):
        CasoDominio(
            id="frontera-001",
            texto="x",
            esperado=Decision.ACEPTAR,
            categoria=Categoria.FRONTERA,
            subcategoria="frontera",
        )


def test_carga_reporta_numero_de_linea(tmp_path: Path) -> None:
    ruta = tmp_path / "malo.jsonl"
    buena = {
        "id": "dentro-001",
        "texto": "a",
        "esperado": "aceptar",
        "categoria": "dentro",
        "subcategoria": "x",
    }
    ruta.write_text(json.dumps(buena) + "\n{no es json}\n", encoding="utf-8")
    with pytest.raises(ValueError, match=r":2:"):
        cargar_casos(ruta)


def test_carga_rechaza_ids_repetidos(tmp_path: Path) -> None:
    ruta = tmp_path / "repetido.jsonl"
    fila = json.dumps(
        {
            "id": "dentro-001",
            "texto": "a",
            "esperado": "aceptar",
            "categoria": "dentro",
            "subcategoria": "x",
        }
    )
    ruta.write_text(f"{fila}\n{fila}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="repetido"):
        cargar_casos(ruta)


# --- Métricas con clasificadores de juguete ---


def _acepta_todo(_: str) -> Decision:
    return Decision.ACEPTAR


def _rechaza_todo(_: str) -> Decision:
    return Decision.RECHAZAR


def test_aceptar_todo_fuga_completa_sin_rechazo_indebido() -> None:
    resultado = evaluar_filtro(cargar_casos(CONJUNTO), _acepta_todo)
    assert resultado.fuga is not None and resultado.fuga.proporcion == 1
    assert resultado.rechazo_indebido is not None and resultado.rechazo_indebido.proporcion == 0


def test_rechazar_todo_sin_fuga_y_rechazo_indebido_completo() -> None:
    resultado = evaluar_filtro(cargar_casos(CONJUNTO), _rechaza_todo)
    assert resultado.fuga is not None and resultado.fuga.proporcion == 0
    assert resultado.rechazo_indebido is not None and resultado.rechazo_indebido.proporcion == 1


def test_oraculo_perfecto_no_tiene_errores() -> None:
    casos = cargar_casos(CONJUNTO)
    esperado = {c.texto: c.esperado for c in casos}
    resultado = evaluar_filtro(casos, lambda texto: esperado[texto])
    assert resultado.ids_fuga == ()
    assert resultado.ids_rechazo_indebido == ()
    assert resultado.ids_frontera_fallidos == ()
    assert resultado.acierto_frontera is not None and resultado.acierto_frontera.proporcion == 1


def test_reporte_lista_los_ids_con_error() -> None:
    casos = (
        CasoDominio(
            id="fuera-001",
            texto="chiste",
            esperado=Decision.RECHAZAR,
            categoria=Categoria.FUERA,
            subcategoria="x",
        ),
        CasoDominio(
            id="dentro-001",
            texto="tasa",
            esperado=Decision.ACEPTAR,
            categoria=Categoria.DENTRO,
            subcategoria="x",
        ),
    )
    tabla = reporte_markdown(evaluar_filtro(casos, _acepta_todo))
    assert "fuera-001" in tabla
    assert "| Acierto en frontera | 0 | — | — |" in tabla
