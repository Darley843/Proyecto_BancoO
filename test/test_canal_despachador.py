"""Pruebas del despachador del canal (sin red).

El grafo y el enviador se sustituyen por dobles: se comprueba la identidad, la
autorización, el consentimiento, el `thread_id` y el envío, sin llamar a Meta ni
al modelo.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import pytest

from banco_occidente_corpus.canal.almacen import contar_mensajes
from banco_occidente_corpus.canal.cola import ColaMensajes
from banco_occidente_corpus.canal.configuracion import ConfiguracionCanal
from banco_occidente_corpus.canal.consentimiento import ID_ACEPTO, MaquinaConsentimiento
from banco_occidente_corpus.canal.contratos import MensajeEntrante, RespuestaCanal
from banco_occidente_corpus.canal.despachador import (
    AVISO_NO_AUTORIZADO,
    TEXTO_ERROR,
    Despachador,
)
from banco_occidente_corpus.canal.envio import Enviador, ErrorEnvio
from banco_occidente_corpus.canal.identidad import calcular_usuario_id
from banco_occidente_corpus.sucursal.perfil import huella_perfil

SAL = "sal-de-prueba"
NUMERO = "57000000001"
AHORA = datetime(2026, 11, 19, 12, 0, tzinfo=UTC)


@dataclass
class EnviadorEspia:
    """Enviador que guarda las respuestas en memoria."""

    enviadas: list[RespuestaCanal] = field(default_factory=list)

    def enviar(self, respuesta: RespuestaCanal) -> str:
        """Registra la respuesta y devuelve un id ficticio."""
        self.enviadas.append(respuesta)
        return "fake:espia"


@dataclass
class FakeOpenClaw:
    """Doble del motor OpenClaw: guarda el turno y devuelve un texto fijo."""

    respuesta: str | None = "respuesta de openclaw"
    llamadas: list[tuple[str, str]] = field(default_factory=list)

    def __call__(self, texto: str, usuario_id: str) -> str | None:
        """Registra el turno y devuelve la respuesta configurada."""
        self.llamadas.append((texto, usuario_id))
        return self.respuesta


@dataclass
class EnviadorBloqueado:
    """Imita el modo real: rechaza los destinos fuera de la lista."""

    def enviar(self, respuesta: RespuestaCanal) -> str:
        """Rechaza el envío como ``EnviadorMeta`` sin salir a la red."""
        raise ErrorEnvio("destino no autorizado para el modo real")


@dataclass
class BancoDePrueba:
    """Piezas construidas para un caso del despachador."""

    despachador: Despachador
    enviadas: list[RespuestaCanal]
    llamadas: list[tuple[str, str, str]]
    ruta: Path
    maquina: MaquinaConsentimiento
    usuario_id: str


def _mensaje(
    texto: str = "hola", *, boton: str | None = None, id_mensaje: str = "wamid.1"
) -> MensajeEntrante:
    """Construye un mensaje entrante válido."""
    return MensajeEntrante(
        id_mensaje=id_mensaje,
        remitente=NUMERO,
        texto=texto,
        id_boton=boton,
        recibido_en=AHORA,
    )


def _banco(
    tmp_path: Path,
    *,
    autorizado: bool = True,
    motor: Callable[[str, str], str | None] | None = None,
    enviador: Enviador | None = None,
) -> BancoDePrueba:
    """Arma el despachador con enviador, grafo y motor de doble."""
    ruta = tmp_path / "whatsapp.sqlite"
    usuario_id = calcular_usuario_id(NUMERO, SAL)
    enviadas: list[RespuestaCanal] = []
    llamadas: list[tuple[str, str, str]] = []
    espia = EnviadorEspia(enviadas)

    def responder(pregunta: str, thread_id: str, perfil: str) -> str:
        """Doble del grafo: guarda la llamada y devuelve un texto fijo."""
        llamadas.append((pregunta, thread_id, perfil))
        return "respuesta del grafo"

    despachador = Despachador(
        config=ConfiguracionCanal(huellas=(usuario_id,) if autorizado else ()),
        sal=SAL,
        ruta_almacen=ruta,
        maquina=MaquinaConsentimiento(ruta),
        cola=ColaMensajes(),
        crear_enviador=lambda _usuario, _destino: enviador or espia,
        responder=responder,
        motor=motor,
    )
    return BancoDePrueba(
        despachador=despachador,
        enviadas=enviadas,
        llamadas=llamadas,
        ruta=ruta,
        maquina=despachador.maquina,
        usuario_id=usuario_id,
    )


def test_numero_no_autorizado_recibe_aviso(tmp_path: Path) -> None:
    """Un número fuera de las huellas no entra al grafo ni crea consentimiento."""
    banco = _banco(tmp_path, autorizado=False)
    mensaje = _mensaje("¿cuota de manejo?")

    banco.despachador.recibir(mensaje)
    banco.despachador.procesar(mensaje)

    assert [respuesta.texto for respuesta in banco.enviadas] == [AVISO_NO_AUTORIZADO]
    assert banco.llamadas == []
    assert contar_mensajes(banco.ruta) == {"ignorado": 1}


def test_numero_no_autorizado_queda_ignorado_si_el_envio_real_lo_bloquea(
    tmp_path: Path,
) -> None:
    """El bloqueo del modo real no convierte el descarte en error."""
    banco = _banco(tmp_path, autorizado=False, enviador=EnviadorBloqueado())
    mensaje = _mensaje("¿cuota de manejo?")

    banco.despachador.recibir(mensaje)
    banco.despachador.procesar(mensaje)

    assert banco.enviadas == []
    assert banco.llamadas == []
    assert contar_mensajes(banco.ruta) == {"ignorado": 1}


def test_primer_contacto_pide_consentimiento(tmp_path: Path) -> None:
    """Sin consentimiento, la respuesta es el aviso con botones."""
    banco = _banco(tmp_path)
    mensaje = _mensaje("hola")

    banco.despachador.recibir(mensaje)
    banco.despachador.procesar(mensaje)

    assert banco.enviadas[0].tipo == "botones"
    assert "1581" in banco.enviadas[0].texto
    assert banco.llamadas == []
    assert contar_mensajes(banco.ruta) == {"respondido": 1}


def test_con_consentimiento_llama_al_grafo(tmp_path: Path) -> None:
    """Con consentimiento, la pregunta va al grafo con el hilo del usuario."""
    banco = _banco(tmp_path)
    banco.maquina.aceptar(banco.usuario_id, AHORA)
    mensaje = _mensaje("¿cuál es la cuota de manejo?")

    banco.despachador.recibir(mensaje)
    banco.despachador.procesar(mensaje)

    assert banco.llamadas == [
        (
            "¿cuál es la cuota de manejo?",
            f"wa:{banco.usuario_id}",
            huella_perfil(banco.usuario_id),
        )
    ]
    assert [respuesta.texto for respuesta in banco.enviadas] == ["respuesta del grafo"]


def test_boton_acepto_guarda_consentimiento(tmp_path: Path) -> None:
    """El botón de consentimiento se procesa antes del grafo."""
    banco = _banco(tmp_path)
    mensaje = _mensaje("Acepto", boton=ID_ACEPTO, id_mensaje="wamid.ACEPTO")

    banco.despachador.recibir(mensaje)
    banco.despachador.procesar(mensaje)

    assert "Gracias" in banco.enviadas[0].texto
    assert banco.llamadas == []

    siguiente = _mensaje("hola", id_mensaje="wamid.SIGUIENTE")
    banco.despachador.recibir(siguiente)
    banco.despachador.procesar(siguiente)

    assert len(banco.llamadas) == 1


def test_deduplica_por_id_de_mensaje(tmp_path: Path) -> None:
    """El mismo id de Meta se registra una sola vez."""
    banco = _banco(tmp_path)
    mensaje = _mensaje("hola")

    banco.despachador.recibir(mensaje)
    banco.despachador.recibir(mensaje)

    assert contar_mensajes(banco.ruta) == {"recibido": 1}


def test_error_del_grafo_envia_texto_de_respaldo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Si el grafo falla, el usuario recibe una respuesta fija y el estado es error."""
    banco = _banco(tmp_path)
    banco.maquina.aceptar(banco.usuario_id, AHORA)

    def falla(_pregunta: str, _thread: str, _perfil: str) -> str:
        """Doble que simula una caída del grafo."""
        raise RuntimeError("modelo caído")

    monkeypatch.setattr(banco.despachador, "responder", falla)
    mensaje = _mensaje("hola")

    banco.despachador.recibir(mensaje)
    banco.despachador.procesar(mensaje)

    assert banco.enviadas[-1].texto == TEXTO_ERROR
    assert contar_mensajes(banco.ruta) == {"error": 1}


def test_dos_usuarios_no_comparten_hilo_ni_perfil(tmp_path: Path) -> None:
    """Cada número entra con su propio hilo y su propia huella de perfil."""
    ruta = tmp_path / "whatsapp.sqlite"
    numeros = ("57000000001", "57000000002")
    usuarios = tuple(calcular_usuario_id(numero, SAL) for numero in numeros)
    llamadas: list[tuple[str, str, str]] = []
    enviadas: list[RespuestaCanal] = []

    def responder(pregunta: str, thread_id: str, perfil: str) -> str:
        """Doble del grafo que guarda el hilo y la huella de cada turno."""
        llamadas.append((pregunta, thread_id, perfil))
        return "respuesta del grafo"

    despachador = Despachador(
        config=ConfiguracionCanal(huellas=usuarios),
        sal=SAL,
        ruta_almacen=ruta,
        maquina=MaquinaConsentimiento(ruta),
        cola=ColaMensajes(),
        crear_enviador=lambda _usuario, _destino: EnviadorEspia(enviadas),
        responder=responder,
    )
    for indice, (usuario_id, numero) in enumerate(zip(usuarios, numeros, strict=True)):
        despachador.maquina.aceptar(usuario_id, AHORA)
        mensaje = _mensaje("¿cuál es la cuota de manejo?", id_mensaje=f"wamid.USUARIO{indice}")
        mensaje = mensaje.model_copy(update={"remitente": numero})
        despachador.recibir(mensaje)
        despachador.procesar(mensaje)

    assert llamadas == [
        ("¿cuál es la cuota de manejo?", f"wa:{usuarios[0]}", huella_perfil(usuarios[0])),
        ("¿cuál es la cuota de manejo?", f"wa:{usuarios[1]}", huella_perfil(usuarios[1])),
    ]
    assert llamadas[0][1] != llamadas[1][1]
    assert llamadas[0][2] != llamadas[1][2]


def _motor_de(ruta: Path, id_mensaje: str) -> str | None:
    """Lee el motor que quedó registrado para un mensaje."""
    with sqlite3.connect(str(ruta)) as conexion:
        fila = conexion.execute(
            "SELECT motor FROM mensajes WHERE id_mensaje = ?", (id_mensaje,)
        ).fetchone()
    return None if fila is None else str(fila[0])


def test_openclaw_responde_una_sola_vez_y_no_llama_al_grafo(tmp_path: Path) -> None:
    """Un texto válido del gateway se envía una vez y el grafo no participa."""
    motor = FakeOpenClaw()

    banco = _banco(tmp_path, motor=motor)
    banco.maquina.aceptar(banco.usuario_id, AHORA)
    mensaje = _mensaje("¿cuál es la cuota de manejo?")

    banco.despachador.recibir(mensaje)
    banco.despachador.procesar(mensaje)

    assert motor.llamadas == [("¿cuál es la cuota de manejo?", banco.usuario_id)]
    assert banco.llamadas == []
    assert [respuesta.texto for respuesta in banco.enviadas] == ["respuesta de openclaw"]
    assert _motor_de(banco.ruta, mensaje.id_mensaje) == "openclaw"


def test_si_openclaw_no_responde_responde_el_grafo(tmp_path: Path) -> None:
    """Un ``None`` del gateway cae al grafo y deja el motor en la traza."""
    banco = _banco(tmp_path, motor=lambda _texto, _huella: None)
    banco.maquina.aceptar(banco.usuario_id, AHORA)
    mensaje = _mensaje("¿cuál es la cuota de manejo?")

    banco.despachador.recibir(mensaje)
    banco.despachador.procesar(mensaje)

    assert len(banco.llamadas) == 1
    assert [respuesta.texto for respuesta in banco.enviadas] == ["respuesta del grafo"]
    assert _motor_de(banco.ruta, mensaje.id_mensaje) == "grafo"


def test_un_motor_que_falla_no_rompe_el_turno(tmp_path: Path) -> None:
    """Una excepción del gateway se trata como fallo y responde el grafo."""

    def motor(_texto: str, _usuario_id: str) -> str:
        """Doble que simula una caída del cliente."""
        raise RuntimeError("gateway caído")

    banco = _banco(tmp_path, motor=motor)
    banco.maquina.aceptar(banco.usuario_id, AHORA)
    mensaje = _mensaje("hola")

    banco.despachador.recibir(mensaje)
    banco.despachador.procesar(mensaje)

    assert len(banco.llamadas) == 1
    assert [respuesta.texto for respuesta in banco.enviadas] == ["respuesta del grafo"]
    assert _motor_de(banco.ruta, mensaje.id_mensaje) == "grafo"


def test_comando_con_barra_no_va_al_gateway(tmp_path: Path) -> None:
    """Un texto que empieza por ``/`` no dispara los comandos de OpenClaw."""
    llamadas_motor: list[str] = []

    def motor(texto: str, _usuario_id: str) -> str:
        """Doble que no debería recibir el comando."""
        llamadas_motor.append(texto)
        return "respuesta de openclaw"

    banco = _banco(tmp_path, motor=motor)
    banco.maquina.aceptar(banco.usuario_id, AHORA)
    mensaje = _mensaje("/reset")

    banco.despachador.recibir(mensaje)
    banco.despachador.procesar(mensaje)

    assert llamadas_motor == []
    assert len(banco.llamadas) == 1
    assert _motor_de(banco.ruta, mensaje.id_mensaje) == "grafo"


def test_pii_no_va_al_gateway(tmp_path: Path) -> None:
    """Un teléfono dictado se queda en el grafo, que aplica la política de PII."""
    llamadas_motor: list[str] = []

    def motor(texto: str, _usuario_id: str) -> str:
        """Doble que no debería recibir PII."""
        llamadas_motor.append(texto)
        return "respuesta de openclaw"

    banco = _banco(tmp_path, motor=motor)
    banco.maquina.aceptar(banco.usuario_id, AHORA)
    mensaje = _mensaje("mi teléfono es 3001234567")

    banco.despachador.recibir(mensaje)
    banco.despachador.procesar(mensaje)

    assert llamadas_motor == []
    assert len(banco.llamadas) == 1
    assert _motor_de(banco.ruta, mensaje.id_mensaje) == "grafo"


def test_sin_consentimiento_no_llama_al_motor(tmp_path: Path) -> None:
    """El aviso de la Ley 1581 sale antes de cualquier motor."""
    llamadas_motor: list[str] = []

    def motor(texto: str, _usuario_id: str) -> str:
        """Doble que no debería recibir el primer mensaje."""
        llamadas_motor.append(texto)
        return "respuesta de openclaw"

    banco = _banco(tmp_path, motor=motor)
    mensaje = _mensaje("hola")

    banco.despachador.recibir(mensaje)
    banco.despachador.procesar(mensaje)

    assert llamadas_motor == []
    assert banco.enviadas[0].tipo == "botones"
    assert _motor_de(banco.ruta, mensaje.id_mensaje) == "canal"


def test_un_motor_con_texto_vacio_cae_al_grafo(tmp_path: Path) -> None:
    """Un texto en blanco se trata como fallo, no como respuesta vacía."""
    banco = _banco(tmp_path, motor=lambda _texto, _huella: "   ")
    banco.maquina.aceptar(banco.usuario_id, AHORA)
    mensaje = _mensaje("hola")

    banco.despachador.recibir(mensaje)
    banco.despachador.procesar(mensaje)

    assert [respuesta.texto for respuesta in banco.enviadas] == ["respuesta del grafo"]
    assert _motor_de(banco.ruta, mensaje.id_mensaje) == "grafo"
