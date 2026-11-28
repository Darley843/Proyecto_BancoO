"""Prueba de PII de la escena en vivo (6.4; docs/ESCENA_EN_VIVO.md §13 y §14).

Completa lo que ya prueba ``test_escena_publicador.py`` (correo y teléfono en
``texto``): el documento, la PII escondida en el subtítulo, la ruta
``GET /api/escena/en-vivo`` con la lista real, la salida por consola y el script
de limpieza. Los nombres los enmascara el canal y los prueba
``test_canal_escena_vivo.py::test_los_nombres_se_enmascaran``.

Todos los datos son sintéticos. Las pruebas usan ``tmp_path`` y nunca tocan
``data/escena/``.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from banco_occidente_corpus.asistente.validacion import detectar_pii
from banco_occidente_corpus.config import PROJECT_ROOT
from banco_occidente_corpus.escena import publicador
from banco_occidente_corpus.escena.api_en_vivo import crear_router_en_vivo
from banco_occidente_corpus.escena.contratos import TurnoEscena

TELEFONO = "3009999999"
CORREO = "invitado.prueba@example.com"
DOCUMENTO = "1234567890"

#: Un mensaje del invitado por cada tipo de dato personal.
MENSAJES_CON_PII: dict[str, str] = {
    "telefono": f"Escríbeme al {TELEFONO} para lo del préstamo",
    "correo": f"Mi correo es {CORREO}, mándame la ficha",
    "documento": f"Mi cédula es {DOCUMENTO}, ¿me alcanza?",
}

#: Lo que nunca debe aparecer en la lista, la ruta, los logs ni la consola.
VALORES_PROHIBIDOS: tuple[str, ...] = (TELEFONO, CORREO, DOCUMENTO)

MENSAJE_LIMPIO = "Quiero un préstamo de dos millones para mi negocio"

Registros = tuple[tuple[Mapping[str, Any], ...], int]


def _turno_invitado(texto: str, *, subtitulo: str | None = None) -> TurnoEscena:
    """Turno del voluntario tal como lo publica el canal (§9.3)."""
    return TurnoEscena(
        id="canal.invitado.v1",
        orden=0,
        personaje="invitado",
        texto=texto,
        subtitulo=subtitulo,
        origen="canal",
    )


def _lote_mixto() -> list[TurnoEscena]:
    """Un turno limpio y, después, uno por cada dato personal."""
    return [
        _turno_invitado(MENSAJE_LIMPIO),
        *(_turno_invitado(mensaje) for mensaje in MENSAJES_CON_PII.values()),
    ]


def _contenido(ruta: Path) -> str:
    """Texto crudo de la lista, o vacío si no se creó."""
    return ruta.read_text(encoding="utf-8") if ruta.exists() else ""


def _sin_prohibidos(texto: str) -> None:
    """Falla si aparece cualquiera de los datos sintéticos."""
    for valor in VALORES_PROHIBIDOS:
        assert valor not in texto, f"apareció un dato sintético: {valor!r}"


def _lector_de(lista: Path) -> Callable[..., Registros]:
    """Lector para la ruta que lee la lista temporal con el publicador real."""

    def leer(desde: int, *, limite: int = 200) -> Registros:
        return publicador.leer_turnos(desde, limite=limite, ruta=lista)

    return leer


@pytest.fixture
def lista(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Interruptor encendido y lista en ``tmp_path``."""
    monkeypatch.setenv("ESCENA_EN_VIVO", "1")
    return tmp_path / "en_vivo.jsonl"


# --- Control de los datos sintéticos ---------------------------------------


@pytest.mark.parametrize("mensaje", MENSAJES_CON_PII.values(), ids=MENSAJES_CON_PII.keys())
def test_los_datos_sinteticos_son_pii_para_el_detector(mensaje: str) -> None:
    """Si el detector no los marcara, el resto de la prueba no demostraría nada."""
    assert detectar_pii(mensaje) is not None


def test_el_mensaje_limpio_no_es_pii() -> None:
    """El turno de control debe poder publicarse."""
    assert detectar_pii(MENSAJE_LIMPIO) is None


# --- La lista ---------------------------------------------------------------


def test_un_documento_no_llega_a_la_lista(lista: Path) -> None:
    """La cédula también la frena el publicador, no solo el correo y el teléfono."""
    turno = _turno_invitado(MENSAJES_CON_PII["documento"])
    assert publicador.publicar_turnos([turno], origen="canal", ruta=lista) == ()
    _sin_prohibidos(_contenido(lista))


@pytest.mark.parametrize("mensaje", MENSAJES_CON_PII.values(), ids=MENSAJES_CON_PII.keys())
def test_la_pii_en_el_subtitulo_no_llega_a_la_lista(lista: Path, mensaje: str) -> None:
    """El detector revisa ``subtitulo`` además de ``texto`` (§13.2)."""
    turno = _turno_invitado(MENSAJE_LIMPIO, subtitulo=mensaje)
    assert publicador.publicar_turnos([turno], origen="canal", ruta=lista) == ()
    _sin_prohibidos(_contenido(lista))


def test_del_lote_mixto_solo_sale_el_turno_limpio(lista: Path) -> None:
    """Se descartan los tres turnos con PII y el limpio del mismo lote sí sale."""
    seqs = publicador.publicar_turnos(_lote_mixto(), origen="canal", ruta=lista)

    assert len(seqs) == 1
    registros, _ = publicador.leer_turnos(0, ruta=lista)
    assert [registro["turno"]["texto"] for registro in registros] == [MENSAJE_LIMPIO]
    _sin_prohibidos(_contenido(lista))


# --- Logs y consola ---------------------------------------------------------


def test_ni_los_logs_ni_la_consola_llevan_texto(
    lista: Path,
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Solo códigos y conteos, nunca el texto, tampoco el limpio (§7.1 y §13.2)."""
    with caplog.at_level(logging.DEBUG):
        publicador.publicar_turnos(_lote_mixto(), origen="canal", ruta=lista)
        turno = _turno_invitado(MENSAJE_LIMPIO, subtitulo=MENSAJES_CON_PII["documento"])
        publicador.publicar_turnos([turno], origen="canal", ruta=lista)
    salida = capsys.readouterr()

    for texto in (caplog.text, salida.out, salida.err):
        _sin_prohibidos(texto)
        assert MENSAJE_LIMPIO not in texto


# --- La ruta ----------------------------------------------------------------


def test_la_ruta_no_devuelve_pii_ni_rutas_internas(lista: Path) -> None:
    """``GET /api/escena/en-vivo`` sobre la lista real devuelve solo el turno limpio (§10)."""
    publicador.publicar_turnos(_lote_mixto(), origen="canal", ruta=lista)
    app = FastAPI()
    app.include_router(crear_router_en_vivo(lector=_lector_de(lista)))

    respuesta = TestClient(app).get("/api/escena/en-vivo", params={"desde": 0})

    assert respuesta.status_code == 200
    textos = [registro["turno"]["texto"] for registro in respuesta.json()["turnos"]]
    assert textos == [MENSAJE_LIMPIO]
    _sin_prohibidos(respuesta.text)
    for interno in ("en_vivo.jsonl", "en_vivo.lock", str(lista.parent)):
        assert interno not in respuesta.text


# --- El borrado -------------------------------------------------------------


def test_el_script_de_limpieza_nombra_la_lista_y_el_bloqueo() -> None:
    """``limpiar_evento.ps1`` borra la escena en vivo y la ficha pendiente (§12)."""
    script = (PROJECT_ROOT / "scripts" / "limpiar_evento.ps1").read_text(
        encoding="utf-8-sig", errors="replace"
    )
    assert "en_vivo.jsonl" in script
    assert "en_vivo.lock" in script
    assert "ficha_entrega.json" in script
