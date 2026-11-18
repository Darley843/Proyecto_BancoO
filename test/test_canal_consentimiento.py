"""Pruebas de la máquina de consentimiento de la Ley 1581 (sin red)."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from banco_occidente_corpus.canal.consentimiento import (
    AVISO,
    ESTADO_ACEPTADO,
    ESTADO_SIN_CONSENTIMIENTO,
    ID_ACEPTO,
    ID_RECHAZO,
    MaquinaConsentimiento,
    es_revocacion,
    interpretar,
)
from banco_occidente_corpus.canal.contratos import MensajeEntrante

AHORA = datetime(2026, 11, 17, 12, 0, tzinfo=UTC)
"""Instante fijo de las pruebas."""

USUARIO = "u" * 64
"""Huella ficticia del número."""


def _mensaje(
    texto: str = "hola", *, boton: str | None = None, id_mensaje: str = "wamid.1"
) -> MensajeEntrante:
    """Construye un mensaje entrante válido."""
    return MensajeEntrante(
        id_mensaje=id_mensaje,
        remitente="57000000001",
        texto=texto,
        id_boton=boton,
        recibido_en=AHORA,
    )


def _maquina(tmp_path: Path, version: str = "2026-11") -> MaquinaConsentimiento:
    """Máquina de consentimiento sobre una base temporal."""
    return MaquinaConsentimiento(tmp_path / "whatsapp.sqlite", version=version)


def _contar(ruta: Path, tabla: str) -> int:
    """Cuenta filas de una tabla del almacén."""
    with sqlite3.connect(str(ruta)) as conexion:
        return conexion.execute(f"SELECT COUNT(*) FROM {tabla}").fetchone()[0]


def test_primer_contacto_devuelve_el_aviso_con_dos_botones(tmp_path: Path) -> None:
    """Sin fila previa, el canal pide consentimiento explícito."""
    maquina = _maquina(tmp_path)

    respuesta = maquina.decidir(_mensaje("hola"), USUARIO)

    assert respuesta is not None
    assert respuesta.tipo == "botones"
    assert respuesta.texto == AVISO
    assert [boton.id for boton in respuesta.botones] == [ID_ACEPTO, ID_RECHAZO]
    assert "1581" in respuesta.texto
    assert maquina.estado(USUARIO) == ESTADO_SIN_CONSENTIMIENTO


def test_aceptar_con_el_boton_registra_version_y_fecha(tmp_path: Path) -> None:
    """«Acepto» guarda la versión del aviso y el instante."""
    maquina = _maquina(tmp_path, version="2026-12")

    respuesta = maquina.decidir(_mensaje("Acepto", boton=ID_ACEPTO), USUARIO)

    assert respuesta is not None
    assert maquina.estado(USUARIO) == ESTADO_ACEPTADO
    with sqlite3.connect(str(tmp_path / "whatsapp.sqlite")) as conexion:
        fila = conexion.execute(
            "SELECT version, aceptado_en, revocado_en FROM consentimientos WHERE usuario_id = ?",
            (USUARIO,),
        ).fetchone()
    assert fila is not None
    assert fila[0] == "2026-12"
    assert datetime.fromisoformat(fila[1]).tzinfo is not None
    assert fila[2] is None


def test_version_nueva_vuelve_a_pedir_consentimiento(tmp_path: Path) -> None:
    """Aceptar una versión anterior no vale para el aviso nuevo."""
    _maquina(tmp_path).aceptar(USUARIO, AHORA)

    assert _maquina(tmp_path, version="2026-12").estado(USUARIO) == ESTADO_SIN_CONSENTIMIENTO


def test_aceptar_por_texto_normaliza_tildes_y_mayusculas(tmp_path: Path) -> None:
    """«  ACEPTO! » cuenta como aceptación inequívoca."""
    maquina = _maquina(tmp_path)

    maquina.decidir(_mensaje("  ACEPTO! "), USUARIO)

    assert maquina.estado(USUARIO) == ESTADO_ACEPTADO


def test_rechazo_no_guarda_consentimiento(tmp_path: Path) -> None:
    """«Ahora no» responde sin crear fila ni perfil."""
    maquina = _maquina(tmp_path)

    respuesta = maquina.decidir(_mensaje("ahora no"), USUARIO)

    assert respuesta is not None
    assert "no guardaré tus datos" in respuesta.texto
    assert maquina.estado(USUARIO) == ESTADO_SIN_CONSENTIMIENTO
    assert _contar(tmp_path / "whatsapp.sqlite", "consentimientos") == 0


def test_silencio_repite_el_aviso(tmp_path: Path) -> None:
    """Un mensaje que no decide vuelve a pedir el consentimiento."""
    maquina = _maquina(tmp_path)

    respuesta = maquina.decidir(_mensaje("¿qué es la inflación?"), USUARIO)

    assert respuesta is not None
    assert respuesta.texto == AVISO


def test_con_consentimiento_el_turno_sigue_al_grafo(tmp_path: Path) -> None:
    """Aceptado el aviso, la máquina devuelve None y el despachador continúa."""
    maquina = _maquina(tmp_path)
    maquina.aceptar(USUARIO, AHORA)

    assert maquina.decidir(_mensaje("¿cuál es la cuota de manejo?"), USUARIO) is None


def test_revocacion_borra_consentimiento_y_casos_pero_no_la_deduplicacion(
    tmp_path: Path,
) -> None:
    """«Olvida mis datos» borra PII y conserva el id de deduplicación."""
    ruta = tmp_path / "whatsapp.sqlite"
    maquina = _maquina(tmp_path)
    maquina.aceptar(USUARIO, AHORA)
    with sqlite3.connect(str(ruta)) as conexion:
        conexion.execute(
            "INSERT INTO casos (id_caso, usuario_id, motivo, semaforo, resultado_json, "
            "estado, creado_en) VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("caso-1", USUARIO, "solicitud_directa", "amarillo", "{}", "pendiente", "2026-11-17"),
        )
        conexion.execute(
            "INSERT INTO mensajes (id_mensaje, usuario_id, estado, recibido_en) "
            "VALUES (?, ?, ?, ?)",
            ("wamid.1", USUARIO, "respondido", "2026-11-17T12:00:00+00:00"),
        )

    respuesta = maquina.decidir(_mensaje("Olvida mis datos"), USUARIO)

    assert respuesta is not None
    assert "borré tus datos" in respuesta.texto
    assert maquina.estado(USUARIO) == ESTADO_SIN_CONSENTIMIENTO
    assert _contar(ruta, "consentimientos") == 0
    assert _contar(ruta, "casos") == 0
    assert _contar(ruta, "mensajes") == 1


def test_revocacion_solo_con_la_frase_exacta(tmp_path: Path) -> None:
    """«Olvida mi perfil» es otra ruta y no dispara el borrado del canal."""
    assert es_revocacion(_mensaje("olvida mi perfil")) is False
    assert es_revocacion(_mensaje("OLVIDA MIS DATOS")) is True


def test_interpretar_botones_y_textos() -> None:
    """Los identificadores de Meta y los textos libres se clasifican igual."""
    assert interpretar(_mensaje("x", boton=ID_ACEPTO)) == "acepto"
    assert interpretar(_mensaje("x", boton=ID_RECHAZO)) == "rechazo"
    assert interpretar(_mensaje("autorizo")) == "acepto"
    assert interpretar(_mensaje("otra cosa")) == "silencio"
