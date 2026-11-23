"""Pruebas del servicio de la escena: fase 1, fase 2 y núcleo (tarea 5.5)."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from banco_occidente_corpus.escena.contratos import (
    Escena,
    NegociacionEscena,
    PerfilEscena,
    RespuestaEscena,
)
from banco_occidente_corpus.escena.perfiles import perfil_seguro
from banco_occidente_corpus.escena.servicio import (
    construir_escena,
    construir_negociacion,
    construir_nucleo,
    construir_perfil,
    sellos,
)

DEMO = {"SUCURSAL_DEMO": "1"}


@pytest.fixture(scope="module")
def perfil() -> PerfilEscena:
    """Perfil seguro verde validado contra el motor."""
    return perfil_seguro("verde_computador")


@pytest.fixture(scope="module")
def fase1(perfil: PerfilEscena) -> Escena:
    """Escena de fase 1 del perfil verde."""
    return construir_escena(perfil)


@pytest.fixture(scope="module")
def negociacion(perfil: PerfilEscena) -> NegociacionEscena:
    """Fase 2 determinista del perfil verde."""
    return construir_negociacion(perfil, entorno=DEMO)


def test_fase_1_trae_diagnostico_gota_y_comparacion(fase1: Escena) -> None:
    """La fase 1 tiene las piezas que la pantalla necesita."""
    assert fase1.diagnostico.semaforo == "verde"
    assert fase1.gota.monto == Decimal(4_000_000)
    assert fase1.comparacion.monto == Decimal(4_000_000)
    assert fase1.comparacion.tasa_ea_gota > fase1.comparacion.tasa_ea_banco
    assert fase1.turnos[0].personaje == "pana"
    assert any(turno.personaje == "don_gota" for turno in fase1.turnos)


def test_dos_llamadas_dan_las_mismas_cifras(perfil: PerfilEscena, fase1: Escena) -> None:
    """El servicio es determinista para el mismo perfil."""
    otra = construir_escena(perfil)
    assert otra.gota == fase1.gota
    assert otra.comparacion == fase1.comparacion
    assert [turno.texto for turno in otra.turnos] == [turno.texto for turno in fase1.turnos]


def test_el_auditor_revisa_los_turnos_base(fase1: Escena) -> None:
    """El veredicto cubre los turnos de la fase 1 y no usa colores."""
    assert set(fase1.veredicto.turnos_revisados) == {turno.id for turno in fase1.turnos}
    assert fase1.veredicto.veredicto in {"conforme", "con_observaciones", "objeta"}


def test_la_fase_2_trae_agentes_auditor_y_cierre(negociacion: NegociacionEscena) -> None:
    """La negociación añade los agentes, el veredicto y el cierre de Pana."""
    personajes = [turno.personaje for turno in negociacion.turnos]
    assert "agente_joven" in personajes
    assert "agente_banco" in personajes
    assert negociacion.turnos[-2].personaje == "auditor"
    assert negociacion.turnos[-1].personaje == "pana"
    assert negociacion.veredicto.veredicto in {"conforme", "con_observaciones", "objeta"}
    assert negociacion.escenarios


def test_la_escena_completa_incluye_la_negociacion(perfil: PerfilEscena) -> None:
    """La escena completa suma la fase 1, la negociación, el auditor y el cierre."""
    completa = construir_escena(perfil, incluir_negociacion=True, entorno=DEMO)
    ids = [turno.id for turno in completa.turnos]
    assert "auditor.veredicto.v1" in ids
    assert "pana.cierre.v1" in ids
    ordenes = [turno.orden for turno in completa.turnos]
    assert ordenes == sorted(ordenes)
    assert len(set(ordenes)) == len(ordenes)


def test_el_nucleo_deja_don_gota_pana_y_auditor(perfil: PerfilEscena) -> None:
    """El núcleo no incluye a los agentes ni al voluntario."""
    nucleo = construir_nucleo(perfil)
    personajes = {turno.personaje for turno in nucleo.turnos}
    assert personajes == {"pana", "don_gota", "auditor"}
    assert nucleo.modo == "nucleo"


def test_no_crea_sqlite_ni_archivos(
    perfil: PerfilEscena, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """El servicio no crea SQLite ni carpetas de datos al construir la escena."""
    monkeypatch.chdir(tmp_path)
    construir_escena(perfil)
    assert not (tmp_path / "data").exists()
    assert not (tmp_path / "escena").exists()


def test_los_sellos_incluyen_las_configuraciones() -> None:
    """Los sellos cubren diagnóstico, tasas, escena y la tabla Gold."""
    resultado = sellos()
    assert {"config/diagnostico.toml", "config/tasas.toml", "config/escena.toml"} <= set(resultado)
    assert "gold_tasas" in resultado
    assert all(len(valor) == 64 for valor in resultado.values())


def test_el_perfil_exige_las_cuatro_respuestas() -> None:
    """Un perfil incompleto se rechaza antes de calcular."""
    respuesta = RespuestaEscena(
        pregunta="monto",
        letra="A",
        opcion_id="monto.HASTA_5M",
        texto="Hasta $5 millones",
        valor=Decimal(4_000_000),
    )
    with pytest.raises(ValueError, match="faltan respuestas"):
        construir_perfil([respuesta])
