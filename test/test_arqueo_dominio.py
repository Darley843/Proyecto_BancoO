"""Pruebas de la sección ``dominio`` del Arqueo (tarea 7.5).

La sección pone lado a lado las reglas solas del Digiturno, medidas en cada
Arqueo sobre ``data/evaluacion/filtro_dominio.jsonl``, y el sistema real con el
modelo, leído del último informe publicado. Se verifica que las cifras coinciden
con el Digiturno, que la corrida es determinista, que no se publica el texto de
los casos y que el Markdown sale del mismo bloque del JSON.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from banco_occidente_corpus.arqueo.filtro_digiturno import (
    MOTIVO_DUDA,
    RUTA_CONJUNTO,
    RUTA_INFORME_MODELO,
    clasificador_digiturno,
    leer_corridas_modelo,
    markdown_dominio,
    seccion_dominio,
)
from banco_occidente_corpus.arqueo.filtro_dominio import cargar_casos
from banco_occidente_corpus.sucursal.tipos import Turno

ID_CASO = re.compile(r"^(dentro|fuera|frontera)-\d{3}$")
"""Forma de los ids del conjunto."""

INFORME_DE_PRUEBA = """## Filtro de dominio del Digiturno: reglas + modelo (DeepSeek), 2 corridas

| Corrida | Fuga | Rechazo indebido | Acierto en frontera | Dudas sin respuesta |
|---:|---|---|---|---:|
| 1 | 0/50 | 3/50 | 14/14 | 2 |
| 2 | 1/50 | 1/50 | 13/14 | 0 |
| **Rango** | 0 a 1 de 50 (0,0 a 2,0 %) | 1 a 3 de 50 (2,0 a 6,0 %) | 13 a 14 de 14 | |
"""
"""Informe con modelo de ejemplo, con el formato de `medir_varias`."""


def _informe(tmp_path: Path) -> Path:
    """Escribe el informe de ejemplo y devuelve su ruta."""
    ruta = tmp_path / "informe_modelo.md"
    ruta.write_text(INFORME_DE_PRUEBA, encoding="utf-8")
    return ruta


def test_las_reglas_cuentan_cobertura_y_errores_como_el_digiturno() -> None:
    """Deciden, errores e ids coinciden con clasificar cada caso con el Digiturno."""
    casos = cargar_casos(RUTA_CONJUNTO)
    turnos: dict[str, Turno] = {}
    decidir = clasificador_digiturno(turnos=turnos)
    deciden: dict[str, int] = {}
    errores: dict[str, list[str]] = {}
    for caso in casos:
        obtenida = decidir(caso.texto)
        clave = caso.categoria.value
        deciden.setdefault(clave, 0)
        errores.setdefault(clave, [])
        if turnos[caso.texto].motivo.split(":")[0] == MOTIVO_DUDA:
            continue
        deciden[clave] += 1
        if obtenida is not caso.esperado:
            errores[clave].append(caso.id)

    grupos = seccion_dominio()["reglas"]["grupos"]

    for clave, total in deciden.items():
        assert grupos[clave]["deciden"] == total
        assert grupos[clave]["ids"] == errores[clave]
        if total:
            assert grupos[clave]["errores"]["exitos"] == len(errores[clave])
            assert grupos[clave]["errores"]["n"] == total


def test_la_cobertura_suma_los_grupos() -> None:
    """La cobertura total es la suma de lo que deciden las reglas en cada grupo."""
    seccion = seccion_dominio()
    reglas = seccion["reglas"]

    assert sum(seccion["casos"].values()) == len(cargar_casos(RUTA_CONJUNTO))
    assert reglas["cobertura"]["n"] == sum(seccion["casos"].values())
    assert reglas["cobertura"]["exitos"] == sum(g["deciden"] for g in reglas["grupos"].values())
    assert sum(reglas["decidio"].values()) == reglas["cobertura"]["n"]
    dudas = reglas["decidio"].get(f"regla {MOTIVO_DUDA}", 0)
    assert reglas["cobertura"]["exitos"] == reglas["cobertura"]["n"] - dudas


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
    for grupo in seccion["reglas"]["grupos"].values():
        assert all(ID_CASO.match(ident) for ident in grupo["ids"])


def test_lee_las_corridas_del_informe_con_modelo(tmp_path: Path) -> None:
    """Se leen las filas de corrida y se ignora la fila de rango."""
    corridas = leer_corridas_modelo(_informe(tmp_path))

    assert [c["corrida"] for c in corridas] == [1, 2]
    assert corridas[0] == {
        "corrida": 1,
        "fuga": 0,
        "n_fuera": 50,
        "rechazo_indebido": 3,
        "n_dentro": 50,
        "acierto_frontera": 14,
        "n_frontera": 14,
        "dudas_sin_respuesta": 2,
    }


def test_el_informe_publicado_del_proyecto_se_puede_leer() -> None:
    """El informe con modelo versionado tiene corridas con los totales del conjunto."""
    seccion = seccion_dominio()

    assert RUTA_INFORME_MODELO.exists()
    assert seccion["modelo"] is not None
    for corrida in seccion["modelo"]["corridas"]:
        assert corrida["n_fuera"] == seccion["casos"]["fuera"]
        assert corrida["n_dentro"] == seccion["casos"]["dentro"]
        assert corrida["n_frontera"] == seccion["casos"]["frontera"]


def test_el_markdown_pone_lado_a_lado_reglas_y_modelo(tmp_path: Path) -> None:
    """Las dos tablas salen del mismo bloque del JSON, con el rango del modelo."""
    seccion = seccion_dominio(informe_modelo=_informe(tmp_path))

    texto = "\n".join(markdown_dominio(seccion))

    assert "### Reglas solas (US$ 0, determinista)" in texto
    assert "### Sistema real: reglas + modelo (DeepSeek)" in texto
    cobertura = seccion["reglas"]["cobertura"]
    assert f"Las reglas deciden {cobertura['exitos']} de {cobertura['n']} casos" in texto
    fuera = seccion["reglas"]["grupos"]["fuera"]
    assert f"| Fuera de tema (fuga) | {fuera['n']} | {fuera['deciden']}/{fuera['n']} " in texto
    assert "| 2 | 1/50 | 1/50 | 13/14 | 0 |" in texto
    assert "| **Rango** | 0 a 1 de 50 (0,0 a 2,0 %) | 1 a 3 de 50 (2,0 a 6,0 %) |" in texto


def test_sin_informe_con_modelo_lo_dice(tmp_path: Path) -> None:
    """Sin corrida con modelo publicada, la sección no inventa cifras del sistema real."""
    seccion = seccion_dominio(informe_modelo=tmp_path / "no_existe.md")

    texto = "\n".join(markdown_dominio(seccion))

    assert seccion["modelo"] is None
    assert "Todavía no hay una corrida con modelo publicada" in texto


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
    assert seccion["reglas"]["grupos"]["frontera"]["cobertura"] is None
    assert "| Frontera (decisión distinta) | 0 | — | — | — |" in "\n".join(
        markdown_dominio(seccion)
    )
