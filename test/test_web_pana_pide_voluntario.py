"""Pana pide un voluntario: no elige a alguien de la fila.

En la sustentación no se sabe cómo se sentará el público, así que Pana
pregunta quién se anima en vez de nombrar una fila y una silla, y recuerda
que se escribe con datos inventados.
"""

from __future__ import annotations

import json
from pathlib import Path

ESCENA = Path(__file__).resolve().parents[1] / "app" / "web" / "escena"


def test_la_presentacion_pide_un_voluntario_con_datos_inventados() -> None:
    """El cierre de la presentación invita a ofrecerse, sin elegir a nadie."""
    codigo = (ESCENA / "anfitrion.js").read_text(encoding="utf-8")
    assert "¿Hay alguien que se anime a ser mi voluntario?" in codigo
    assert "con datos inventados: nada de su información real" in codigo
    assert "elegiré a un voluntario" not in codigo


def test_la_escena_de_ejemplo_no_nombra_fila_ni_silla() -> None:
    """Ningún turno de Pana en el guion de ejemplo nombra una fila o una silla."""
    datos = json.loads((ESCENA / "turnos-ejemplo.json").read_text(encoding="utf-8"))
    textos = [turno["texto"].lower() for turno in datos["turnos"] if turno["personaje"] == "pana"]
    assert textos[0].startswith("¿quién se anima a ser mi voluntario?")
    assert not any("silla" in texto or "fila tres" in texto for texto in textos)
