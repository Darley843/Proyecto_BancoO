"""Pruebas del modo evento del canal (sin red).

Cubren la ventana del evento, la cuota por persona, el tope global, el alcance
completo de los desconocidos (misma entrevista que la lista) y la autorización
del envío por ventana de servicio. Todo corre con dobles: no hay Meta, ni
modelo, ni túnel.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from banco_occidente_corpus.canal.almacen import (
    contar_mensajes_desde,
    contar_mensajes_usuario,
    hay_mensaje_desde,
    inicializar_almacen,
    registrar_mensaje,
)
from banco_occidente_corpus.canal.cola import ColaMensajes
from banco_occidente_corpus.canal.configuracion import (
    ConfiguracionCanal,
    cargar_configuracion_canal,
)
from banco_occidente_corpus.canal.consentimiento import MaquinaConsentimiento
from banco_occidente_corpus.canal.contratos import MensajeEntrante, RespuestaCanal
from banco_occidente_corpus.canal.despachador import (
    AVISO_NO_AUTORIZADO,
    TEXTO_CUOTA_USUARIO,
    TEXTO_EVENTO_CERRADO,
    Despachador,
    RespuestaGrafo,
)
from banco_occidente_corpus.canal.envio import EnviadorMeta, ErrorEnvio
from banco_occidente_corpus.canal.evento import Evento, leer_evento
from banco_occidente_corpus.canal.identidad import calcular_usuario_id

SAL = "sal-de-prueba"
NUMERO = "57000000009"
AHORA = datetime(2026, 11, 24, 19, 0, tzinfo=UTC)


def _evento(**cambios: object) -> Evento:
    """Evento vigente alrededor de ``AHORA`` con cuotas amplias."""
    datos: dict[str, object] = {
        "activo": True,
        "desde": AHORA - timedelta(hours=1),
        "hasta": AHORA + timedelta(hours=3),
        "max_por_hora": 30,
        "max_por_usuario": 40,
        "max_total": 300,
    }
    datos.update(cambios)
    return Evento(**datos)  # type: ignore[arg-type]


@dataclass
class EnviadorEspia:
    """Enviador que guarda las respuestas en memoria."""

    enviadas: list[RespuestaCanal] = field(default_factory=list)

    def enviar(self, respuesta: RespuestaCanal) -> str:
        """Registra la respuesta y devuelve un id ficticio."""
        self.enviadas.append(respuesta)
        return "fake:espia"


class EntrevistaFalsa:
    """Entrevista que registra cada llamada para comprobar el alcance."""

    def __init__(self) -> None:
        """Arranca sin llamadas registradas."""
        self.llamadas: list[str] = []

    def reanudar(self, *_args: object) -> None:
        """No hay entrevista previa."""
        self.llamadas.append("reanudar")

    def activa(self, *_args: object) -> bool:
        """No hay entrevista activa."""
        self.llamadas.append("activa")
        return False

    def avanzar(self, *_args: object) -> object:
        """Devuelve un avance sin respuestas ni texto."""
        self.llamadas.append("avanzar")
        return AvanceFalso()

    def completar(self, *_args: object) -> None:
        """No se completa nada en estas pruebas."""
        self.llamadas.append("completar")

    def escenario(self, *_args: object) -> None:
        """No hay «¿Y si…?» en estas pruebas."""
        self.llamadas.append("escenario")

    def iniciar(self, usuario_id: str, id_mensaje: str) -> RespuestaCanal:
        """Registra el arranque y devuelve una respuesta reconocible."""
        self.llamadas.append("iniciar")
        return RespuestaCanal(
            usuario_id=usuario_id,
            id_mensaje_origen=id_mensaje,
            texto="pregunta de la entrevista",
        )


@dataclass
class AvanceFalso:
    """Avance de entrevista vacío."""

    respuestas: object | None = None
    respuesta: RespuestaCanal | None = None


@dataclass
class BancoEvento:
    """Piezas construidas para un caso del modo evento."""

    despachador: Despachador
    enviadas: list[RespuestaCanal]
    llamadas: list[tuple[str, str, str]]
    ruta: Path
    usuario_id: str


def _mensaje(id_mensaje: str = "wamid.evento.1") -> MensajeEntrante:
    """Construye un mensaje entrante válido de un número desconocido."""
    return MensajeEntrante(
        id_mensaje=id_mensaje,
        remitente=NUMERO,
        texto="¿qué tasa hay para libre inversión?",
        recibido_en=AHORA,
    )


def _banco(
    tmp_path: Path,
    *,
    evento: Evento,
    autorizado: bool = False,
    avisos: tuple[str, ...] = (),
    entrevista: EntrevistaFalsa | None = None,
) -> BancoEvento:
    """Arma el despachador con enviador y grafo de doble."""
    ruta = tmp_path / "whatsapp.sqlite"
    usuario_id = calcular_usuario_id(NUMERO, SAL)
    enviadas: list[RespuestaCanal] = []
    llamadas: list[tuple[str, str, str]] = []
    espia = EnviadorEspia(enviadas)

    def responder(pregunta: str, thread_id: str, perfil: str) -> RespuestaGrafo:
        """Doble del grafo: guarda la llamada y devuelve una respuesta fija."""
        llamadas.append((pregunta, thread_id, perfil))
        return RespuestaGrafo(texto="respuesta del grafo", avisos=avisos)

    despachador = Despachador(
        config=ConfiguracionCanal(
            huellas=(usuario_id,) if autorizado else (),
            evento=evento,
        ),
        sal=SAL,
        ruta_almacen=ruta,
        maquina=MaquinaConsentimiento(ruta),
        cola=ColaMensajes(),
        crear_enviador=lambda _usuario, _destino: espia,
        responder=responder,
        entrevista=entrevista,  # type: ignore[arg-type]
    )
    return BancoEvento(
        despachador=despachador,
        enviadas=enviadas,
        llamadas=llamadas,
        ruta=ruta,
        usuario_id=usuario_id,
    )


def test_evento_apagado_no_abre_la_puerta(tmp_path: Path) -> None:
    """Sin evento, un desconocido sigue recibiendo el aviso de no autorizado."""
    banco = _banco(tmp_path, evento=Evento(activo=False))
    mensaje = _mensaje()

    banco.despachador.recibir(mensaje)
    banco.despachador.procesar(mensaje, AHORA)

    assert [respuesta.texto for respuesta in banco.enviadas] == [AVISO_NO_AUTORIZADO]
    assert banco.llamadas == []


def test_evento_fuera_de_ventana_no_abre_la_puerta(tmp_path: Path) -> None:
    """Un evento activo pero vencido no atiende a desconocidos."""
    vencido = _evento(hasta=AHORA - timedelta(minutes=1))
    banco = _banco(tmp_path, evento=vencido)
    mensaje = _mensaje()

    banco.despachador.recibir(mensaje)
    banco.despachador.procesar(mensaje, AHORA)

    assert [respuesta.texto for respuesta in banco.enviadas] == [AVISO_NO_AUTORIZADO]


def test_desconocido_en_evento_recibe_el_aviso_de_consentimiento(tmp_path: Path) -> None:
    """En evento, el desconocido llega al aviso de la Ley 1581, no al bloqueo."""
    banco = _banco(tmp_path, evento=_evento())
    mensaje = _mensaje()

    banco.despachador.recibir(mensaje)
    banco.despachador.procesar(mensaje, AHORA)

    assert len(banco.enviadas) == 1
    assert "Ley 1581" in banco.enviadas[0].texto
    assert AVISO_NO_AUTORIZADO not in banco.enviadas[0].texto
    assert banco.llamadas == []


def test_cuota_por_hora_corta_al_segundo_mensaje(tmp_path: Path) -> None:
    """Con una cuota de un mensaje por hora, el segundo recibe el aviso de cuota."""
    banco = _banco(tmp_path, evento=_evento(max_por_hora=1))

    primero = _mensaje("wamid.evento.1")
    banco.despachador.recibir(primero)
    banco.despachador.procesar(primero, AHORA)

    segundo = _mensaje("wamid.evento.2")
    banco.despachador.recibir(segundo)
    banco.despachador.procesar(segundo, AHORA)

    assert banco.enviadas[-1].texto == TEXTO_CUOTA_USUARIO


def test_tope_global_cierra_el_evento(tmp_path: Path) -> None:
    """El tope global corta aunque la persona tenga cuota disponible."""
    banco = _banco(tmp_path, evento=_evento(max_total=1))

    primero = _mensaje("wamid.evento.1")
    banco.despachador.recibir(primero)
    banco.despachador.procesar(primero, AHORA)

    segundo = _mensaje("wamid.evento.2")
    banco.despachador.recibir(segundo)
    banco.despachador.procesar(segundo, AHORA)

    assert banco.enviadas[-1].texto == TEXTO_EVENTO_CERRADO


def test_desconocido_en_evento_entra_a_la_entrevista_del_diagnostico(tmp_path: Path) -> None:
    """La ruta D de un desconocido del evento abre la entrevista igual que la lista."""
    entrevista = EntrevistaFalsa()
    banco = _banco(
        tmp_path,
        evento=_evento(),
        avisos=("diagnostico",),
        entrevista=entrevista,
    )
    banco.despachador.maquina.aceptar(banco.usuario_id, AHORA)
    mensaje = _mensaje()

    banco.despachador.recibir(mensaje)
    banco.despachador.procesar(mensaje, AHORA)

    assert "iniciar" in entrevista.llamadas
    assert banco.enviadas[-1].texto == "pregunta de la entrevista"


def test_desconocido_en_evento_sin_consentimiento_no_abre_la_entrevista(tmp_path: Path) -> None:
    """El alcance completo del evento no se salta la Ley 1581."""
    entrevista = EntrevistaFalsa()
    banco = _banco(
        tmp_path,
        evento=_evento(),
        avisos=("diagnostico",),
        entrevista=entrevista,
    )
    mensaje = _mensaje()

    banco.despachador.recibir(mensaje)
    banco.despachador.procesar(mensaje, AHORA)

    assert "Ley 1581" in banco.enviadas[-1].texto
    assert entrevista.llamadas == []
    assert banco.llamadas == []


class EntrevistaEnCurso(EntrevistaFalsa):
    """Entrevista ya abierta que devuelve la siguiente pregunta."""

    def activa(self, *_args: object) -> bool:
        """Sí hay entrevista activa para esa huella."""
        self.llamadas.append("activa")
        return True

    def avanzar(self, *_args: object) -> AvanceFalso:
        """Devuelve la siguiente respuesta de la entrevista."""
        self.llamadas.append("avanzar")
        return AvanceFalso(
            respuesta=RespuestaCanal(
                usuario_id="huella",
                id_mensaje_origen="wamid.evento.1",
                texto="siguiente pregunta",
            )
        )


def test_desconocido_en_evento_con_entrevista_activa_la_continua(tmp_path: Path) -> None:
    """Quien ya empezó la entrevista sigue en ella dentro de la ventana."""
    entrevista = EntrevistaEnCurso()
    banco = _banco(tmp_path, evento=_evento(), entrevista=entrevista)
    banco.despachador.maquina.aceptar(banco.usuario_id, AHORA)
    mensaje = _mensaje()

    banco.despachador.recibir(mensaje)
    banco.despachador.procesar(mensaje, AHORA)

    assert "avanzar" in entrevista.llamadas
    assert banco.enviadas[-1].texto == "siguiente pregunta"


def test_autorizado_conserva_la_entrevista(tmp_path: Path) -> None:
    """Un número de la lista mantiene el diagnóstico completo."""
    entrevista = EntrevistaFalsa()
    banco = _banco(
        tmp_path,
        evento=_evento(),
        autorizado=True,
        avisos=("diagnostico",),
        entrevista=entrevista,
    )
    banco.despachador.maquina.aceptar(banco.usuario_id, AHORA)
    mensaje = _mensaje()

    banco.despachador.recibir(mensaje)
    banco.despachador.procesar(mensaje, AHORA)

    assert "iniciar" in entrevista.llamadas
    assert banco.enviadas[-1].texto == "pregunta de la entrevista"


def test_evento_vigente_permite_solo_dentro_de_la_ventana() -> None:
    """La ventana respeta ``desde`` y ``hasta`` en UTC."""
    evento = Evento(
        activo=True,
        desde=AHORA - timedelta(hours=1),
        hasta=AHORA + timedelta(hours=1),
    )

    assert evento.vigente(AHORA)
    assert not evento.vigente(AHORA - timedelta(hours=2))
    assert not evento.vigente(AHORA + timedelta(hours=2))


def test_leer_evento_respeta_la_sobrescritura_del_entorno() -> None:
    """``WHATSAPP_EVENTO`` manda sobre el valor del TOML."""
    datos = {"activo": False, "max_por_hora": 3}

    assert leer_evento(datos, activo_entorno=True).activo
    assert not leer_evento({"activo": True}, activo_entorno=False).activo
    assert leer_evento(datos).max_por_hora == 3


@pytest.mark.parametrize("valor", [0, -3, "ocho", True])
def test_cuota_invalida_falla(valor: object) -> None:
    """Una cuota que no es un entero positivo rompe la carga del TOML."""
    with pytest.raises(ValueError):
        leer_evento({"max_total": valor})


def test_cargar_configuracion_lee_la_seccion_evento(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """El evento se lee del TOML y el entorno puede encenderlo."""
    archivo = tmp_path / "whatsapp.toml"
    archivo.write_text(
        """
[canal]
modo = "falso"

[evento]
activo = false
desde = "2026-11-28T08:00:00-05:00"
hasta = "2026-11-28T20:00:00-05:00"
max_por_hora = 4
max_total = 50
""",
        encoding="utf-8",
    )
    monkeypatch.delenv("WHATSAPP_EVENTO", raising=False)

    config = cargar_configuracion_canal(archivo)

    assert not config.evento.activo
    assert config.evento.max_por_hora == 4
    assert config.evento.desde == datetime(2026, 11, 28, 13, 0, tzinfo=UTC)

    monkeypatch.setenv("WHATSAPP_EVENTO", "1")
    assert cargar_configuracion_canal(archivo).evento.activo


def test_permite_distingue_lista_de_evento() -> None:
    """La lista autoriza siempre; el evento solo dentro de la ventana."""
    config = ConfiguracionCanal(
        huellas=("huella-autorizada",),
        evento=Evento(
            activo=True,
            desde=AHORA - timedelta(hours=1),
            hasta=AHORA + timedelta(hours=1),
        ),
    )

    assert config.permite("huella-autorizada", AHORA)
    assert config.permite("huella-desconocida", AHORA)
    assert not config.permite("huella-desconocida", AHORA + timedelta(days=2))
    assert not config.es_evento("huella-autorizada", AHORA)
    assert config.es_evento("huella-desconocida", AHORA)


def test_enviador_meta_exige_autorizacion() -> None:
    """Sin huella ni ventana de servicio, el envío real se bloquea."""
    respuesta = RespuestaCanal(
        usuario_id="huella",
        id_mensaje_origen="wamid.1",
        texto="hola",
    )
    enviador = EnviadorMeta(
        usuario_id="huella",
        destino="+573000000000",
        phone_number_id="123",
        token="token",
        user_agent="ua",
        remitente="from@example.com",
    )

    with pytest.raises(ErrorEnvio):
        enviador.enviar(respuesta)

    con_ventana = EnviadorMeta(
        usuario_id="huella",
        destino="+573000000000",
        phone_number_id="123",
        token="token",
        user_agent="ua",
        remitente="from@example.com",
        puede_responder=lambda _huella: True,
    )
    assert con_ventana._autorizado()


def test_contadores_de_ventana(tmp_path: Path) -> None:
    """Los contadores respetan el corte y distinguen por huella."""
    ruta = tmp_path / "whatsapp.sqlite"
    inicializar_almacen(ruta)
    registrar_mensaje(ruta, "wamid.1", "huella-a", "recibido", AHORA)
    registrar_mensaje(ruta, "wamid.2", "huella-a", "recibido", AHORA + timedelta(hours=2))
    registrar_mensaje(ruta, "wamid.3", "huella-b", "recibido", AHORA + timedelta(hours=3))

    corte = AHORA + timedelta(hours=1)

    assert hay_mensaje_desde(ruta, "huella-a", corte)
    assert hay_mensaje_desde(ruta, "huella-b", corte)
    assert not hay_mensaje_desde(ruta, "huella-b", AHORA + timedelta(hours=4))
    assert contar_mensajes_usuario(ruta, "huella-a", corte) == 1
    assert contar_mensajes_desde(ruta, corte) == 2


def test_entorno_vacio_no_enciende_el_evento(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Una variable de entorno vacía no cambia el valor del TOML."""
    monkeypatch.setenv("WHATSAPP_EVENTO", "")
    archivo = tmp_path / "whatsapp.toml"
    archivo.write_text("[evento]\nactivo = true\n", encoding="utf-8")

    assert cargar_configuracion_canal(archivo).evento.activo
    assert os.environ["WHATSAPP_EVENTO"] == ""
