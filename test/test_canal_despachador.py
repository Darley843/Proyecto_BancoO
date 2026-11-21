"""Pruebas del despachador del canal (sin red).

El grafo y el enviador se sustituyen por dobles: se comprueba la identidad, la
autorización, el consentimiento, el `thread_id` y el envío, sin llamar a Meta ni
al modelo.
"""

from __future__ import annotations

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


def _banco(tmp_path: Path, *, autorizado: bool = True) -> BancoDePrueba:
    """Arma el despachador con enviador y grafo de doble."""
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
        crear_enviador=lambda _usuario, _destino: espia,
        responder=responder,
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
