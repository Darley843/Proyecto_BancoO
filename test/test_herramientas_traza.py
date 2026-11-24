"""Pruebas de la traza local de herramientas, sin datos personales."""

from __future__ import annotations

import inspect
import json
from dataclasses import asdict
from pathlib import Path

import pytest

from banco_occidente_corpus.herramientas import lectura, traza


@pytest.fixture
def carpeta(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Aísla la traza en una carpeta temporal."""
    monkeypatch.setenv(traza.VARIABLE_CARPETA, str(tmp_path))
    return tmp_path


def test_con_traza_registra_y_no_guarda_texto_libre(carpeta: Path) -> None:
    """La traza guarda nombre, latencia y un resumen; el texto solo su largo."""
    envuelta = traza.con_traza("auditar_respuesta", lectura.auditar_respuesta)
    salida = envuelta(texto="mi celular es 3001234567", cifras_permitidas=[])
    assert salida.traza_id

    registros = traza.ultimas(1)
    assert len(registros) == 1
    registro = registros[0]
    assert registro.id == salida.traza_id
    assert registro.herramienta == "auditar_respuesta"
    assert registro.latencia_ms >= 0
    assert "caracteres" in str(registro.argumentos["texto"])

    archivo = carpeta / traza.ARCHIVO_TRAZA
    contenido = archivo.read_text(encoding="utf-8")
    assert "3001234567" not in contenido
    json.loads(contenido.splitlines()[0])


def test_con_traza_convierte_la_validacion_en_error_estable(carpeta: Path) -> None:
    """Una entrada inválida no rompe el turno y deja su código en la traza."""
    envuelta = traza.con_traza("auditar_respuesta", lectura.auditar_respuesta)
    salida = envuelta(texto="")
    assert not salida.ok
    assert salida.error is not None
    assert salida.error.codigo == "entrada_invalida"
    assert traza.ultimas(1)[0].codigo == "entrada_invalida"


def test_la_firma_de_la_herramienta_se_conserva(carpeta: Path) -> None:
    """El envoltorio conserva la firma para que el MCP genere el esquema."""
    envuelta = traza.con_traza("auditar_respuesta", lectura.auditar_respuesta)
    parametros = inspect.signature(envuelta).parameters
    assert "texto" in parametros
    assert "cifras_permitidas" in parametros


def test_ultimas_lee_ordenado_y_admite_vacio(carpeta: Path) -> None:
    """La consola devuelve las últimas llamadas y no falla sin archivo."""
    assert traza.ultimas(5) == []
    envuelta = traza.con_traza("verificar_usura", lectura.verificar_usura)
    primera = envuelta(tasa_ea=0.35)
    segunda = envuelta(tasa_ea=0.20)
    registros = traza.ultimas(5)
    assert [registro.id for registro in registros] == [primera.traza_id, segunda.traza_id]
    assert json.loads(json.dumps(asdict(registros[0]), ensure_ascii=False))["ok"] is True
