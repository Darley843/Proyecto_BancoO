"""Pruebas del CLI de la escena (tarea 7.2), sin red ni puertos."""

from __future__ import annotations

from pathlib import Path

import pytest

from banco_occidente_corpus.escena import __main__ as modulo
from banco_occidente_corpus.escena.contratos import Escena
from banco_occidente_corpus.tablero.tasas import TasaNoDisponible


def test_proyectado_escribe_el_json(tmp_path: Path) -> None:
    """--proyectado escribe una escena completa que valida el contrato."""
    codigo = modulo.main(
        ["--proyectado", "--salida", str(tmp_path), "--perfil", "verde_computador"]
    )
    assert codigo == 0
    ruta = tmp_path / "proyectado.json"
    assert ruta.is_file()
    escena = Escena.model_validate_json(ruta.read_text(encoding="utf-8"))
    assert escena.modo == "proyectado"
    assert any(turno.personaje == "auditor" for turno in escena.turnos)
    assert any(turno.personaje == "agente_banco" for turno in escena.turnos)


def test_dos_corridas_dan_el_mismo_json(tmp_path: Path) -> None:
    """La escena de respaldo es determinista byte a byte."""
    primera = tmp_path / "uno"
    segunda = tmp_path / "dos"
    argumentos = ["--proyectado", "--perfil", "verde_computador", "--salida"]
    assert modulo.main([*argumentos, str(primera)]) == 0
    assert modulo.main([*argumentos, str(segunda)]) == 0
    assert (primera / "proyectado.json").read_bytes() == (segunda / "proyectado.json").read_bytes()


def test_nucleo_deja_solo_a_don_gota_pana_y_auditor(tmp_path: Path) -> None:
    """--nucleo escribe el respaldo corto con los tres personajes."""
    codigo = modulo.main(["--nucleo", "--salida", str(tmp_path), "--perfil", "verde_computador"])
    assert codigo == 0
    escena = Escena.model_validate_json((tmp_path / "nucleo.json").read_text(encoding="utf-8"))
    assert escena.modo == "nucleo"
    assert {turno.personaje for turno in escena.turnos} == {"pana", "don_gota", "auditor"}


def test_sin_argumentos_falla(tmp_path: Path) -> None:
    """El CLI exige --proyectado o --nucleo."""
    with pytest.raises(SystemExit) as error:
        modulo.main([])
    assert error.value.code == 2


def test_perfil_inexistente_devuelve_dos(tmp_path: Path) -> None:
    """Un perfil que no existe no escribe nada y sale con 2."""
    assert modulo.main(["--nucleo", "--salida", str(tmp_path), "--perfil", "no_existe"]) == 2


def test_sin_datos_devuelve_tres(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Si falta la tasa, el CLI avisa y sale con 3."""

    def sin_tasa(*_args: object, **_kwargs: object) -> None:
        """Simula un Tablero sin la tasa del producto."""
        raise TasaNoDisponible("no hay tasa de libre inversión")

    monkeypatch.setattr(modulo, "construir_escena", sin_tasa)
    assert modulo.main(["--proyectado", "--salida", str(tmp_path)]) == 3
    assert not (tmp_path / "proyectado.json").exists()
