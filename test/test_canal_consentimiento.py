"""Pruebas de la máquina de consentimiento de la Ley 1581 (sin red)."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

from banco_occidente_corpus.canal.consentimiento import (
    AVISO,
    ESTADO_ACEPTADO,
    ESTADO_SIN_CONSENTIMIENTO,
    ID_ACEPTO,
    ID_RECHAZO,
    LARGO_MAXIMO_AVISO,
    MaquinaConsentimiento,
    es_revocacion,
    interpretar,
    texto_aviso,
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


def test_revocacion_borra_casos_y_conserva_la_prueba_del_consentimiento(
    tmp_path: Path,
) -> None:
    """«Olvida mis datos» borra los casos y deja el consentimiento revocado como prueba."""
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
    assert "revoqué tu autorización" in respuesta.texto
    assert maquina.estado(USUARIO) == ESTADO_SIN_CONSENTIMIENTO
    assert _contar(ruta, "consentimientos") == 1
    assert _contar(ruta, "casos") == 0
    assert _contar(ruta, "mensajes") == 1
    with sqlite3.connect(str(ruta)) as conexion:
        version, aceptado_en, revocado_en = conexion.execute(
            "SELECT version, aceptado_en, revocado_en FROM consentimientos WHERE usuario_id = ?",
            (USUARIO,),
        ).fetchone()
    assert (version, aceptado_en) == ("2026-11", AHORA.isoformat())
    assert revocado_en is not None


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


# --- Ley 1581: prueba de la autorización (Decreto 1377 de 2013, art. 8) ---


def _revocado_en(ruta: Path) -> str | None:
    """Lee la fecha de revocación guardada para el usuario de prueba."""
    with sqlite3.connect(str(ruta)) as conexion:
        return conexion.execute(
            "SELECT revocado_en FROM consentimientos WHERE usuario_id = ?", (USUARIO,)
        ).fetchone()[0]


def test_revocar_dos_veces_conserva_la_primera_fecha(tmp_path: Path) -> None:
    """La prueba registra cuándo se revocó por primera vez; repetir no la cambia."""
    ruta = tmp_path / "whatsapp.sqlite"
    maquina = _maquina(tmp_path)
    maquina.aceptar(USUARIO, AHORA)
    maquina.revocar(USUARIO, AHORA + timedelta(days=1))
    maquina.revocar(USUARIO, AHORA + timedelta(days=2))

    assert _revocado_en(ruta) == (AHORA + timedelta(days=1)).isoformat()


def test_aceptar_de_nuevo_tras_revocar_reactiva_el_consentimiento(tmp_path: Path) -> None:
    """Quien revocó puede volver a autorizar; la revocación se limpia."""
    ruta = tmp_path / "whatsapp.sqlite"
    maquina = _maquina(tmp_path)
    maquina.aceptar(USUARIO, AHORA)
    maquina.revocar(USUARIO, AHORA + timedelta(days=1))
    maquina.aceptar(USUARIO, AHORA + timedelta(days=2))

    assert maquina.estado(USUARIO) == ESTADO_ACEPTADO
    assert _revocado_en(ruta) is None


def test_revocar_sin_consentimiento_no_crea_filas(tmp_path: Path) -> None:
    """Revocar sin haber aceptado no inventa una autorización."""
    ruta = tmp_path / "whatsapp.sqlite"
    _maquina(tmp_path).revocar(USUARIO, AHORA)

    assert _contar(ruta, "consentimientos") == 0


# --- Ley 1581: deber de informar (art. 12) ---


def test_el_aviso_cumple_el_deber_de_informar() -> None:
    """El aviso nombra responsable, datos, finalidad, destinatario, plazo y derechos."""
    for fragmento in (
        "Responsable",
        "rangos de ingresos, gastos y deudas",
        "asesor",
        "No guardamos tu número",
        "30 días",
        "conocer, actualizar, rectificar o suprimir",
        "«olvida mis datos»",
        "¿Autorizas",
    ):
        assert fragmento in AVISO, fragmento


def test_el_aviso_cabe_en_un_mensaje_interactivo() -> None:
    """WhatsApp admite hasta 1.024 caracteres en el cuerpo con botones."""
    assert len(AVISO) <= LARGO_MAXIMO_AVISO


def test_el_aviso_usa_el_plazo_configurado(tmp_path: Path) -> None:
    """Si la configuración cambia la conservación, el aviso dice el plazo real."""
    maquina = MaquinaConsentimiento(tmp_path / "whatsapp.sqlite", retencion_dias=15)

    respuesta = maquina.aviso(USUARIO, "wamid.1")

    assert "15 días" in respuesta.texto
    assert respuesta.texto == texto_aviso(15)


def test_si_por_texto_acepta() -> None:
    """El aviso termina en una pregunta; «sí» es una respuesta inequívoca."""
    assert interpretar(_mensaje("Sí")) == "acepto"
    assert interpretar(_mensaje("si")) == "acepto"
    assert interpretar(_mensaje("no")) == "rechazo"


# --- Conservación: el plazo del aviso se cumple ---


def test_purgar_borra_solo_los_casos_vencidos(tmp_path: Path) -> None:
    """Los casos más viejos que el plazo se borran; los recientes y el consentimiento quedan."""
    ruta = tmp_path / "whatsapp.sqlite"
    maquina = _maquina(tmp_path)
    maquina.aceptar(USUARIO, AHORA)
    with sqlite3.connect(str(ruta)) as conexion:
        for id_caso, dias in (("viejo", 35), ("reciente", 5)):
            conexion.execute(
                "INSERT INTO casos (id_caso, usuario_id, motivo, semaforo, resultado_json, "
                "estado, creado_en) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    id_caso,
                    USUARIO,
                    "semaforo_rojo",
                    "rojo",
                    "{}",
                    "pendiente",
                    (AHORA - timedelta(days=dias)).isoformat(),
                ),
            )

    borrados = maquina.purgar_casos_vencidos(AHORA)

    assert borrados == 1
    assert _contar(ruta, "casos") == 1
    assert _contar(ruta, "consentimientos") == 1
