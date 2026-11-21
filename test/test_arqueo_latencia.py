"""Pruebas de la latencia real (OpenSpec corresponsal-whatsapp, tareas 8.4 a 8.6).

`medir` escribe cada flujo en una base temporal y separa la caché; los
percentiles nearest-rank exigen 30 corridas; la sección del Arqueo y su
Markdown marcan una muestra insuficiente. Ninguna prueba escribe en
``data/asistente`` del proyecto.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from banco_occidente_corpus.arqueo.latencia import (
    FLUJOS,
    con_latencia,
    markdown_latencia,
    medir,
    registrar,
    seccion_latencia,
)


def _filas(ruta: Path) -> list[tuple[str, int]]:
    """Lee flujo y caché de la tabla, en orden de llegada."""
    with sqlite3.connect(ruta) as conexion:
        return conexion.execute("SELECT flujo, cache FROM latencias ORDER BY rowid").fetchall()


def test_medir_escribe_cada_flujo_y_separa_la_cache(tmp_path: Path) -> None:
    """Los cuatro flujos del diseño quedan escritos y la caché va con cache=1."""
    ruta = tmp_path / "latencias.sqlite"
    for flujo in ("webhook", "diagnostico", "hitl", "mcp"):
        with medir(flujo, ruta=ruta):
            pass
    with medir("ventanilla", ruta=ruta) as corrida:
        corrida.cache = True

    assert _filas(ruta) == [
        ("webhook", 0),
        ("diagnostico", 0),
        ("hitl", 0),
        ("mcp", 0),
        ("ventanilla", 1),
    ]


def test_sin_ruta_mide_pero_no_escribe(tmp_path: Path) -> None:
    """Sin base explícita no se crea ningún archivo."""
    with medir("webhook") as corrida:
        pass

    assert corrida.ms is not None and corrida.ms >= 0
    assert list(tmp_path.iterdir()) == []


def test_una_peticion_rechazada_no_cuenta(tmp_path: Path) -> None:
    """Con guardar en False la corrida no se guarda."""
    ruta = tmp_path / "latencias.sqlite"
    with medir("ventanilla", ruta=ruta) as corrida:
        corrida.guardar = False

    assert not ruta.exists()


def test_un_bloque_que_falla_igual_se_mide(tmp_path: Path) -> None:
    """La corrida se guarda aunque el bloque lance una excepción."""
    ruta = tmp_path / "latencias.sqlite"
    with pytest.raises(RuntimeError), medir("webhook", ruta=ruta):
        raise RuntimeError("falla simulada")

    assert _filas(ruta) == [("webhook", 0)]


def test_flujo_desconocido_se_rechaza(tmp_path: Path) -> None:
    """Un flujo fuera de la lista no se mide."""
    with pytest.raises(ValueError, match="flujo desconocido"), medir("otro", ruta=tmp_path / "x"):
        pass
    with pytest.raises(ValueError, match="negativa"):
        registrar("webhook", -1, ruta=tmp_path / "x")


def test_una_base_que_no_se_puede_escribir_no_corta_la_respuesta(tmp_path: Path) -> None:
    """Si la base no se puede abrir, registrar devuelve False sin lanzar."""
    carpeta = tmp_path / "es-una-carpeta"
    carpeta.mkdir()

    assert registrar("webhook", 5, ruta=carpeta) is False


def test_con_latencia_envuelve_y_devuelve_el_resultado(tmp_path: Path) -> None:
    """El envoltorio mide cada llamada y conserva el valor devuelto."""
    ruta = tmp_path / "latencias.sqlite"

    def duplicar(valor: int) -> int:
        """Devuelve el doble."""
        return valor * 2

    medida = con_latencia("webhook", duplicar, ruta=ruta)

    assert medida(4) == 8
    assert medida.__name__ == "duplicar"
    assert _filas(ruta) == [("webhook", 0)]


def _llenar(ruta: Path, flujo: str, valores: list[float], *, cache: bool = False) -> None:
    """Escribe una corrida por valor."""
    for valor in valores:
        registrar(flujo, valor, cache=cache, ruta=ruta)


def test_muestra_de_30_es_suficiente_y_da_nearest_rank(tmp_path: Path) -> None:
    """Con 30 corridas de 1 a 30 ms: p50 = 15 y p95 = 29 (rango ⌈0,95·30⌉ = 29)."""
    ruta = tmp_path / "latencias.sqlite"
    _llenar(ruta, "webhook", [float(valor) for valor in range(30, 0, -1)])

    seccion = seccion_latencia(ruta)

    assert seccion["sin_cache"]["webhook"] == {
        "p50_ms": 15.0,
        "p95_ms": 29.0,
        "n": 30,
        "suficiente": True,
    }


def test_muestra_de_29_no_es_concluyente(tmp_path: Path) -> None:
    """Con 29 corridas el flujo se marca y el Markdown no da percentiles."""
    ruta = tmp_path / "latencias.sqlite"
    _llenar(ruta, "diagnostico", [10.0] * 29)

    seccion = seccion_latencia(ruta)
    texto = "\n".join(markdown_latencia(seccion))

    assert seccion["sin_cache"]["diagnostico"]["suficiente"] is False
    assert "| diagnostico | 29 | no concluyente | no concluyente |" in texto


def test_la_cache_se_reporta_aparte(tmp_path: Path) -> None:
    """Las corridas de caché no se mezclan con las normales."""
    ruta = tmp_path / "latencias.sqlite"
    _llenar(ruta, "ventanilla", [1000.0] * 30)
    _llenar(ruta, "ventanilla", [5.0] * 30, cache=True)

    seccion = seccion_latencia(ruta)
    texto = "\n".join(markdown_latencia(seccion))

    assert seccion["sin_cache"]["ventanilla"]["p95_ms"] == 1000.0
    assert seccion["con_cache"]["ventanilla"]["p95_ms"] == 5.0
    assert "### Sin caché" in texto and "### Con caché" in texto
    assert "| ventanilla | 30 | 1000.0 | 1000.0 |" in texto


def test_sin_base_la_seccion_queda_vacia(tmp_path: Path) -> None:
    """Sin corridas el Arqueo lo dice y no inventa cifras."""
    seccion = seccion_latencia(tmp_path / "no-existe.sqlite")

    assert seccion == {"minimo_corridas": 30, "sin_cache": {}, "con_cache": {}}
    assert "Todavía no hay corridas" in "\n".join(markdown_latencia(seccion))


def test_los_flujos_coinciden_con_la_vista_de_operacion() -> None:
    """Cada flujo que se mide tiene nombre visible en operacion.js."""
    vista = (Path(__file__).resolve().parents[1] / "app/web/vistas/operacion.js").read_text(
        encoding="utf-8"
    )
    for flujo in FLUJOS:
        assert f"  {flujo}: " in vista
