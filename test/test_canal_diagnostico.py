"""Pruebas del servicio de diagnóstico del canal (sin red).

Se recorre la entrevista completa con el motor real contra una tabla Gold
temporal, se comprueba que el resultado llega como texto más tarjeta de Pana y
que la sesión se borra al cerrar. También se cubren cancelar, asesor y las
respuestas fuera de lista.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from banco_occidente_corpus.canal.contratos import MensajeEntrante, RespuestaCanal
from banco_occidente_corpus.canal.diagnostico import (
    TEXTO_ASESOR,
    TEXTO_CANCELADO,
    TEXTO_INVITACION,
    ServicioDiagnostico,
    crear_servicio,
    pide_diagnostico,
)
from banco_occidente_corpus.diagnostico.entrevista import ID_CANCELAR, ID_EMPEZAR
from banco_occidente_corpus.diagnostico.sesiones import cargar as cargar_sesion
from banco_occidente_corpus.tablero.tasas import FilaTasa, escribir_tabla

USUARIO = "u" * 64
AHORA = datetime(2026, 11, 19, 12, 0, tzinfo=UTC)
HOY = date.today()
FUENTE = "https://www.bancodeoccidente.com.co/documents/d/guest/tasas-personas-bdo"


def _fila(producto: str, desde: str, hasta: str, segmento: str | None = None) -> FilaTasa:
    """Construye una fila de la tabla Gold de prueba vigente hoy."""
    return FilaTasa(
        producto=producto,
        segmento=segmento,
        tipo_tasa="fija",
        plazo_dias=None,
        tasa_ea_desde=Decimal(desde),
        tasa_ea_hasta=Decimal(hasta),
        vigencia_desde=HOY - timedelta(days=30),
        vigencia_hasta=HOY + timedelta(days=30),
        fuente=FUENTE,
        sha256_pdf="0" * 64,
        fecha_extraccion=HOY,
    )


@pytest.fixture()
def raiz(tmp_path: Path) -> Path:
    """Tabla Gold temporal con las tasas que usa la entrevista."""
    filas = [
        _fila("libre_inversion", "0.2056", "0.2817"),
        _fila("compra_cartera", "0.1746", "0.2817"),
        _fila("libranza", "0.1539", "0.2431", "Libre inversión"),
        _fila("vivienda", "0.1517", "0.1854", "Crédito hipotecario"),
        _fila("ahorro", "0.0001", "0.0001", "De 0 a $5.000.000"),
        _fila("cdt", "0.1100", "0.1100", "$500M- $99 MM"),
    ]
    escribir_tabla(tmp_path / "tasas-personas-prueba.jsonl", filas)
    return tmp_path


@pytest.fixture()
def servicio(tmp_path: Path, raiz: Path) -> ServicioDiagnostico:
    """Servicio con sesiones y casos en una carpeta temporal."""
    return crear_servicio(
        tmp_path / "diagnostico.sqlite",
        tmp_path / "whatsapp.sqlite",
        raiz=raiz,
        es_diagnostico=lambda texto: "diagnostico" in texto.lower(),
    )


def _mensaje(texto: str, *, boton: str | None = None, numero: int = 0) -> MensajeEntrante:
    """Construye un mensaje entrante válido."""
    return MensajeEntrante(
        id_mensaje=f"wamid.{numero}",
        remitente="57000000001",
        texto=texto,
        id_boton=boton,
        recibido_en=AHORA,
    )


def _elegir(
    servicio: ServicioDiagnostico,
    respuesta: RespuestaCanal,
    *,
    indice: int = 0,
    numero: int = 0,
) -> RespuestaCanal | None:
    """Responde el paso con la opción elegida, como haría WhatsApp."""
    opcion = respuesta.opciones[indice] if respuesta.tipo == "lista" else respuesta.botones[indice]
    return servicio.atender(
        _mensaje(opcion.titulo, boton=opcion.id, numero=numero),
        USUARIO,
    )


def _recorrer(
    servicio: ServicioDiagnostico,
    primera: RespuestaCanal,
    *,
    maximo: int = 10,
) -> RespuestaCanal:
    """Recorre la entrevista eligiendo siempre la primera opción."""
    respuesta = primera
    for numero in range(maximo):
        if respuesta.tipo == "imagen":
            return respuesta
        siguiente = _elegir(servicio, respuesta, numero=numero)
        assert siguiente is not None
        respuesta = siguiente
    raise AssertionError("la entrevista no terminó")


def test_pide_diagnostico_reconoce_la_ruta_d() -> None:
    """El detector reutiliza el Digiturno: la ruta D es el diagnóstico."""
    assert pide_diagnostico("hazme el diagnóstico") is True
    assert pide_diagnostico("¿cuál es la cuota de manejo?") is False


def test_la_invitacion_lleva_dos_botones(servicio: ServicioDiagnostico) -> None:
    """Sin sesión, un pedido de diagnóstico invita con Empezar y Ahora no."""
    respuesta = servicio.atender(_mensaje("quiero hacer el diagnostico"), USUARIO)

    assert respuesta is not None
    assert respuesta.tipo == "botones"
    assert respuesta.texto == TEXTO_INVITACION
    assert [boton.id for boton in respuesta.botones] == [ID_EMPEZAR, ID_CANCELAR]
    assert respuesta.metadatos["paso"] == "invitacion"


def test_empezar_envia_la_primera_lista(servicio: ServicioDiagnostico) -> None:
    """El botón Empezar arranca la entrevista con el objetivo como lista."""
    respuesta = servicio.atender(_mensaje("Empezar", boton=ID_EMPEZAR), USUARIO)

    assert respuesta is not None
    assert respuesta.tipo == "lista"
    assert respuesta.metadatos["paso"] == "objetivo"
    assert len(respuesta.opciones) == 7


def test_entrevista_completa_termina_en_tarjeta(servicio: ServicioDiagnostico) -> None:
    """Un crédito recorre siete pasos y cierra con texto más imagen."""
    inicio = servicio.atender(_mensaje("quiero hacer el diagnostico"), USUARIO)
    assert inicio is not None
    primera = _elegir(servicio, inicio)

    resultado = _recorrer(servicio, primera)

    assert resultado.tipo == "imagen"
    assert resultado.imagen is not None
    assert resultado.imagen.startswith(b"\x89PNG")
    assert "orientativo" in resultado.texto.lower()
    assert resultado.metadatos["paso"] == "resultado"
    assert resultado.metadatos["semaforo"] in {"verde", "amarillo", "rojo"}
    assert cargar_sesion(servicio.ruta_sesiones, USUARIO) == {}


def test_el_ahorro_cierra_sin_monto_ni_plazo(servicio: ServicioDiagnostico) -> None:
    """El ahorro no pregunta monto ni plazo y también entrega tarjeta."""
    inicio = servicio.atender(_mensaje("quiero hacer el diagnostico"), USUARIO)
    assert inicio is not None
    objetivo = _elegir(servicio, inicio)
    assert objetivo is not None
    respuesta = _elegir(servicio, objetivo, indice=6, numero=1)

    pasos: list[str] = []
    for numero in range(2, 10):
        assert respuesta is not None
        if respuesta.tipo == "imagen":
            break
        pasos.append(respuesta.metadatos["paso"])
        respuesta = _elegir(servicio, respuesta, numero=numero)

    assert pasos == ["vinculacion", "ingresos", "gastos", "cuotas"]
    assert respuesta is not None and respuesta.tipo == "imagen"


def test_respuesta_fuera_de_lista_repite_la_pregunta(servicio: ServicioDiagnostico) -> None:
    """Un texto que no es opción no avanza: se repite el paso con el aviso."""
    servicio.atender(_mensaje("Empezar", boton=ID_EMPEZAR), USUARIO)

    respuesta = servicio.atender(_mensaje("no sé"), USUARIO)

    assert respuesta is not None
    assert respuesta.metadatos["paso"] == "objetivo"
    assert "no es una de las opciones" in respuesta.texto
    assert cargar_sesion(servicio.ruta_sesiones, USUARIO) == {}


def test_cancelar_borra_la_sesion(servicio: ServicioDiagnostico) -> None:
    """Cancelar deja la entrevista sin estado y responde el texto fijo."""
    servicio.atender(_mensaje("Empezar", boton=ID_EMPEZAR), USUARIO)

    respuesta = servicio.atender(_mensaje("Cancelar", boton=ID_CANCELAR), USUARIO)

    assert respuesta is not None
    assert respuesta.texto == TEXTO_CANCELADO
    assert cargar_sesion(servicio.ruta_sesiones, USUARIO) == {}


def test_asesor_deja_un_caso_sin_datos_personales(servicio: ServicioDiagnostico) -> None:
    """Pedir un asesor crea el caso y cierra la entrevista."""
    servicio.atender(_mensaje("Empezar", boton=ID_EMPEZAR), USUARIO)

    respuesta = servicio.atender(_mensaje("prefiero un asesor"), USUARIO)

    assert respuesta is not None
    assert respuesta.texto == TEXTO_ASESOR
    assert cargar_sesion(servicio.ruta_sesiones, USUARIO) == {}
    with sqlite3.connect(str(servicio.ruta_almacen)) as conexion:
        filas = conexion.execute(
            "SELECT usuario_id, motivo, semaforo, estado FROM casos"
        ).fetchall()
    assert filas == [(USUARIO, "asesor_solicitado", "pendiente", "abierto")]


def test_mensaje_ajeno_no_lo_atiende(servicio: ServicioDiagnostico) -> None:
    """Una pregunta normal sigue su camino al grafo."""
    assert servicio.atender(_mensaje("¿cuál es la cuota de manejo?"), USUARIO) is None


def test_traslado_mayor_que_las_cuotas_no_avanza(servicio: ServicioDiagnostico) -> None:
    """La compra de cartera rechaza trasladar más de lo que paga hoy."""
    inicio = servicio.atender(_mensaje("Empezar", boton=ID_EMPEZAR), USUARIO)
    assert inicio is not None
    respuesta = _elegir(servicio, inicio, indice=1)
    for numero in range(4):
        assert respuesta is not None
        respuesta = _elegir(servicio, respuesta, numero=numero)

    assert respuesta is not None
    assert respuesta.metadatos["paso"] == "cuota_trasladar"
    rechazo = _elegir(servicio, respuesta, indice=4)

    assert rechazo is not None
    assert rechazo.metadatos["paso"] == "cuota_trasladar"
    assert "no puede ser mayor" in rechazo.texto
