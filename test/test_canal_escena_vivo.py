"""Pruebas de la escena en vivo del canal (sin red ni Meta).

Se comprueba el comando ``ESCENA``, la ranura única con TTL, la no publicación
de terceros, el orden invitado → Pana, el filtro de PII y el interruptor. El
publicador y el motor se sustituyen por dobles: nada sale del proceso.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from banco_occidente_corpus.canal.cola import ColaMensajes
from banco_occidente_corpus.canal.configuracion import ConfiguracionCanal
from banco_occidente_corpus.canal.consentimiento import MaquinaConsentimiento
from banco_occidente_corpus.canal.contratos import MensajeEntrante, RespuestaCanal
from banco_occidente_corpus.canal.despachador import Despachador
from banco_occidente_corpus.canal.entrevista import EntrevistaCanal
from banco_occidente_corpus.canal.escena_vivo import (
    TEXTO_ACTIVADA,
    TEXTO_APAGADA,
    EscenaVivo,
    codigo_del_comando,
    es_comando,
    sin_nombres,
)
from banco_occidente_corpus.canal.identidad import calcular_usuario_id
from banco_occidente_corpus.escena.contratos import TurnoEscena

SAL = "sal-de-prueba"
NUMERO = "57000000001"
OTRO_NUMERO = "57000000002"
AHORA = datetime(2026, 11, 26, 12, 0, tzinfo=UTC)
#: Código de la sesión que la tarjeta entrega solo al voluntario.
CODIGO = "1965"


@pytest.fixture(autouse=True)
def codigo_de_sesion(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fija el código de la sesión como lo hace la tarjeta del voluntario."""
    monkeypatch.setenv("ESCENA_CODIGO", CODIGO)


@dataclass
class PublicadorEspia:
    """Publicador de doble que guarda los turnos y su origen."""

    publicados: list[tuple[TurnoEscena, str]] = field(default_factory=list)

    def __call__(
        self,
        turnos: Iterable[TurnoEscena],
        *,
        origen: str,
        permitidos: object = (),
    ) -> tuple[int, ...]:
        """Registra cada turno y devuelve los ``seq`` ficticios."""
        for turno in turnos:
            self.publicados.append((turno, origen))
        return tuple(range(len(self.publicados)))


@dataclass
class Reloj:
    """Reloj inyectable para mover el vencimiento sin dormir."""

    momento: datetime = AHORA

    def __call__(self) -> datetime:
        """Devuelve el instante fijado."""
        return self.momento


@dataclass
class EnviadorEspia:
    """Enviador que guarda las respuestas en memoria."""

    enviadas: list[RespuestaCanal] = field(default_factory=list)

    def enviar(self, respuesta: RespuestaCanal) -> str:
        """Registra la respuesta y devuelve un id ficticio."""
        self.enviadas.append(respuesta)
        return "fake:espia"


def _mensaje(
    texto: str = "hola", *, numero: str = NUMERO, id_mensaje: str = "wamid.1"
) -> MensajeEntrante:
    """Construye un mensaje entrante válido."""
    return MensajeEntrante(
        id_mensaje=id_mensaje,
        remitente=numero,
        texto=texto,
        recibido_en=AHORA,
    )


def _escena(espia: PublicadorEspia, reloj: Reloj, *, ttl: int = 180) -> EscenaVivo:
    """Arma la ranura con publicador y reloj de doble."""
    return EscenaVivo(ttl_minutos=ttl, publicador=espia, ahora=reloj)


def test_sin_interruptor_no_publica_y_avisa(monkeypatch: pytest.MonkeyPatch) -> None:
    """Con la variable ausente, el comando avisa y no toca la lista."""
    monkeypatch.delenv("ESCENA_EN_VIVO", raising=False)
    espia, reloj = PublicadorEspia(), Reloj()
    escena = _escena(espia, reloj)
    usuario_id = calcular_usuario_id(NUMERO, SAL)

    respuesta = escena.decidir(_mensaje(f"ESCENA {CODIGO}"), usuario_id)

    assert respuesta is not None
    assert respuesta.texto == TEXTO_APAGADA
    assert espia.publicados == []
    assert escena.activo(usuario_id) is False


def test_escena_activa_publica_la_confirmacion(monkeypatch: pytest.MonkeyPatch) -> None:
    """Con el interruptor encendido y el código correcto, confirma y publica."""
    monkeypatch.setenv("ESCENA_EN_VIVO", "1")
    espia, reloj = PublicadorEspia(), Reloj()
    escena = _escena(espia, reloj)
    usuario_id = calcular_usuario_id(NUMERO, SAL)

    respuesta = escena.decidir(_mensaje(f"  escena   {CODIGO} "), usuario_id)

    assert respuesta is not None
    assert respuesta.texto == TEXTO_ACTIVADA
    assert escena.activo(usuario_id) is True
    assert len(espia.publicados) == 1
    turno, origen = espia.publicados[0]
    assert origen == "canal"
    assert turno.personaje == "pana"
    assert turno.id == "canal.pana.escena.v1"
    assert turno.texto == TEXTO_ACTIVADA


def test_sin_codigo_no_activa_ni_publica(monkeypatch: pytest.MonkeyPatch) -> None:
    """``ESCENA`` sin código sigue su curso privado y no activa ni publica."""
    monkeypatch.setenv("ESCENA_EN_VIVO", "1")
    espia, reloj = PublicadorEspia(), Reloj()
    escena = _escena(espia, reloj)
    usuario_id = calcular_usuario_id(NUMERO, SAL)

    respuesta = escena.decidir(_mensaje("ESCENA"), usuario_id)

    assert respuesta is None
    assert escena.activo(usuario_id) is False
    assert espia.publicados == []


def test_otro_codigo_no_activa_ni_publica(monkeypatch: pytest.MonkeyPatch) -> None:
    """Un código distinto al de la sesión tampoco activa la escena."""
    monkeypatch.setenv("ESCENA_EN_VIVO", "1")
    espia, reloj = PublicadorEspia(), Reloj()
    escena = _escena(espia, reloj)
    usuario_id = calcular_usuario_id(NUMERO, SAL)

    respuesta = escena.decidir(_mensaje("ESCENA 0000"), usuario_id)

    assert respuesta is None
    assert escena.activo(usuario_id) is False
    assert espia.publicados == []


def test_sin_codigo_en_la_sesion_no_activa(monkeypatch: pytest.MonkeyPatch) -> None:
    """Si la sesión no define ``ESCENA_CODIGO``, ningún código vale."""
    monkeypatch.setenv("ESCENA_EN_VIVO", "1")
    monkeypatch.delenv("ESCENA_CODIGO", raising=False)
    espia, reloj = PublicadorEspia(), Reloj()
    escena = _escena(espia, reloj)
    usuario_id = calcular_usuario_id(NUMERO, SAL)

    respuesta = escena.decidir(_mensaje(f"ESCENA {CODIGO}"), usuario_id)

    assert respuesta is None
    assert escena.activo(usuario_id) is False
    assert espia.publicados == []


@pytest.mark.parametrize("codigo", ["", "196", "19a5", "١٩٦٥"])
def test_un_codigo_de_sesion_invalido_no_activa(
    monkeypatch: pytest.MonkeyPatch, codigo: str
) -> None:
    """El código de la sesión debe ser de cuatro dígitos ASCII; si no, no activa."""
    monkeypatch.setenv("ESCENA_EN_VIVO", "1")
    monkeypatch.setenv("ESCENA_CODIGO", codigo)
    espia, reloj = PublicadorEspia(), Reloj()
    escena = _escena(espia, reloj)
    usuario_id = calcular_usuario_id(NUMERO, SAL)

    respuesta = escena.decidir(_mensaje(f"ESCENA {CODIGO}"), usuario_id)

    assert respuesta is None
    assert escena.activo(usuario_id) is False
    assert espia.publicados == []


def test_el_ttl_vence_y_se_renueva(monkeypatch: pytest.MonkeyPatch) -> None:
    """La ranura dura el TTL y cada mensaje del voluntario lo renueva."""
    monkeypatch.setenv("ESCENA_EN_VIVO", "1")
    espia, reloj = PublicadorEspia(), Reloj()
    escena = _escena(espia, reloj, ttl=10)
    usuario_id = calcular_usuario_id(NUMERO, SAL)

    escena.activar(usuario_id)
    reloj.momento = AHORA + timedelta(minutes=6)
    assert escena.activo(usuario_id) is True

    reloj.momento = AHORA + timedelta(minutes=8)
    assert escena.publicar_invitado(_mensaje("hola"), usuario_id) is True
    reloj.momento = AHORA + timedelta(minutes=14)
    assert escena.activo(usuario_id) is True

    reloj.momento = AHORA + timedelta(minutes=25)
    assert escena.activo(usuario_id) is False


def test_un_segundo_escena_no_reemplaza_al_primero(monkeypatch: pytest.MonkeyPatch) -> None:
    """Solo hay un voluntario: el comando de otra huella se ignora."""
    monkeypatch.setenv("ESCENA_EN_VIVO", "1")
    espia, reloj = PublicadorEspia(), Reloj()
    escena = _escena(espia, reloj)
    primero = calcular_usuario_id(NUMERO, SAL)
    segundo = calcular_usuario_id(OTRO_NUMERO, SAL)

    assert escena.activar(primero) is True
    assert escena.activar(segundo) is False

    assert escena.activo(primero) is True
    assert escena.activo(segundo) is False


def test_el_voluntario_activo_renueva_su_codigo(monkeypatch: pytest.MonkeyPatch) -> None:
    """El mismo voluntario puede repetir ``ESCENA <código>`` y renueva el TTL."""
    monkeypatch.setenv("ESCENA_EN_VIVO", "1")
    espia, reloj = PublicadorEspia(), Reloj()
    escena = _escena(espia, reloj, ttl=10)
    usuario_id = calcular_usuario_id(NUMERO, SAL)

    assert escena.decidir(_mensaje(f"ESCENA {CODIGO}"), usuario_id) is not None
    reloj.momento = AHORA + timedelta(minutes=8)
    assert escena.decidir(_mensaje(f"ESCENA {CODIGO}"), usuario_id) is not None

    reloj.momento = AHORA + timedelta(minutes=14)
    assert escena.activo(usuario_id) is True


def test_tras_el_vencimiento_otro_puede_activar(monkeypatch: pytest.MonkeyPatch) -> None:
    """Cuando vence el primero, otra huella sí puede tomar la ranura."""
    monkeypatch.setenv("ESCENA_EN_VIVO", "1")
    espia, reloj = PublicadorEspia(), Reloj()
    escena = _escena(espia, reloj, ttl=10)
    primero = calcular_usuario_id(NUMERO, SAL)
    segundo = calcular_usuario_id(OTRO_NUMERO, SAL)

    escena.activar(primero)
    reloj.momento = AHORA + timedelta(minutes=11)

    assert escena.activar(segundo) is True
    assert escena.activo(segundo) is True


def test_otro_invitado_no_publica(monkeypatch: pytest.MonkeyPatch) -> None:
    """Un invitado distinto del voluntario no aparece en la lista."""
    monkeypatch.setenv("ESCENA_EN_VIVO", "1")
    espia, reloj = PublicadorEspia(), Reloj()
    escena = _escena(espia, reloj)
    voluntario = calcular_usuario_id(NUMERO, SAL)
    otro = calcular_usuario_id(OTRO_NUMERO, SAL)
    escena.activar(voluntario)

    assert escena.publicar_invitado(_mensaje("hola"), otro) is False
    assert escena.publicar_pana(otro, "respuesta de Pana") is False
    assert espia.publicados == []


def test_pii_no_se_publica_y_si_la_respuesta_fija(monkeypatch: pytest.MonkeyPatch) -> None:
    """Un teléfono en el mensaje no entra; la frase fija de Pana sí."""
    monkeypatch.setenv("ESCENA_EN_VIVO", "1")
    espia, reloj = PublicadorEspia(), Reloj()
    escena = _escena(espia, reloj)
    usuario_id = calcular_usuario_id(NUMERO, SAL)
    escena.activar(usuario_id)

    assert escena.publicar_invitado(_mensaje("mi celular es 3001234567"), usuario_id) is False
    assert escena.publicar_pana(usuario_id, "No puedo atender datos personales.") is True
    assert [turno.personaje for turno, _ in espia.publicados] == ["pana"]


def test_los_nombres_se_enmascaran(monkeypatch: pytest.MonkeyPatch) -> None:
    """Las formas de presentarse pierden el nombre propio y no la frase."""
    monkeypatch.setenv("ESCENA_EN_VIVO", "1")
    espia, reloj = PublicadorEspia(), Reloj()
    escena = _escena(espia, reloj)
    usuario_id = calcular_usuario_id(NUMERO, SAL)
    escena.activar(usuario_id)

    assert sin_nombres("me llamo Darley Prieto") == "me llamo [nombre]"
    assert sin_nombres("soy independiente") == "soy independiente"
    assert escena.publicar_invitado(_mensaje("soy Laura"), usuario_id) is True
    assert espia.publicados[0][0].texto == "soy [nombre]"


def test_apagar_el_interruptor_detiene_la_escritura(monkeypatch: pytest.MonkeyPatch) -> None:
    """El interruptor se consulta en cada publicación, no al importar."""
    monkeypatch.setenv("ESCENA_EN_VIVO", "1")
    espia, reloj = PublicadorEspia(), Reloj()
    escena = _escena(espia, reloj)
    usuario_id = calcular_usuario_id(NUMERO, SAL)
    escena.activar(usuario_id)
    assert escena.publicar_invitado(_mensaje("antes"), usuario_id) is True

    monkeypatch.setenv("ESCENA_EN_VIVO", "0")
    assert escena.publicar_invitado(_mensaje("después"), usuario_id) is False
    assert len(espia.publicados) == 1


def test_el_comando_acepta_la_palabra_y_el_codigo() -> None:
    """``ESCENA`` se reconoce sola o con un código de cuatro dígitos."""
    assert es_comando(" ESCENA ") is True
    assert es_comando("escena") is True
    assert es_comando(f"Escena {CODIGO}") is True
    assert es_comando(f"  ESCENA   {CODIGO}  ") is True
    assert codigo_del_comando(f"ESCENA {CODIGO}") == CODIGO
    assert codigo_del_comando("ESCENA") is None


@pytest.mark.parametrize(
    "texto",
    ["ESCENA 196", "ESCENA 19655", "ESCENA 19a5", "escena en vivo", "mi escena", "ESCENA1965"],
)
def test_el_comando_no_acepta_otras_formas(texto: str) -> None:
    """No se confunde con frases que solo contienen la palabra o un código corto."""
    assert es_comando(texto) is False


def test_un_reinicio_pierde_la_memoria(monkeypatch: pytest.MonkeyPatch) -> None:
    """La ranura vive en memoria: una instancia nueva no recuerda al voluntario."""
    monkeypatch.setenv("ESCENA_EN_VIVO", "1")
    espia, reloj = PublicadorEspia(), Reloj()
    usuario_id = calcular_usuario_id(NUMERO, SAL)
    _escena(espia, reloj).activar(usuario_id)

    assert _escena(espia, reloj).activo(usuario_id) is False


@dataclass
class BancoCanal:
    """Piezas del despachador con dobles para la escena en vivo."""

    despachador: Despachador
    enviadas: list[RespuestaCanal]
    publicados: list[tuple[TurnoEscena, str]]
    llamadas: list[str]
    usuario_id: str


def _banco(
    tmp_path: Path,
    *,
    escena: EscenaVivo,
    entrevista: EntrevistaCanal | None = None,
    huellas_extra: tuple[str, ...] = (),
) -> BancoCanal:
    """Arma el despachador con enviador, grafo y motor de doble."""
    ruta = tmp_path / "whatsapp.sqlite"
    usuario_id = calcular_usuario_id(NUMERO, SAL)
    enviadas: list[RespuestaCanal] = []
    llamadas: list[str] = []
    espia = EnviadorEspia(enviadas)

    def responder(_pregunta: str, _thread_id: str, _perfil: str) -> str:
        """Doble del grafo."""
        return "respuesta del grafo"

    def motor(texto: str, _usuario_id: str) -> str:
        """Doble del motor de OpenClaw: registra el turno y responde."""
        llamadas.append(texto)
        return "respuesta de Pana"

    despachador = Despachador(
        config=ConfiguracionCanal(huellas=(usuario_id, *huellas_extra)),
        sal=SAL,
        ruta_almacen=ruta,
        maquina=MaquinaConsentimiento(ruta),
        cola=ColaMensajes(),
        crear_enviador=lambda _usuario, _destino: espia,
        responder=responder,
        motor=motor,
        entrevista=entrevista,
        escena=escena,
    )
    return BancoCanal(
        despachador=despachador,
        enviadas=enviadas,
        publicados=escena.publicador.publicados
        if isinstance(escena.publicador, PublicadorEspia)
        else [],
        llamadas=llamadas,
        usuario_id=usuario_id,
    )


def _atender(banco: BancoCanal, mensaje: MensajeEntrante) -> None:
    """Acepta el consentimiento y procesa un mensaje como el trabajador de la cola."""
    banco.despachador.maquina.aceptar(banco.usuario_id, AHORA)
    banco.despachador.recibir(mensaje)
    banco.despachador.procesar(mensaje, AHORA)


def test_el_invitado_va_antes_que_pana(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """El turno del invitado se publica antes de la respuesta del motor."""
    monkeypatch.setenv("ESCENA_EN_VIVO", "1")
    espia, reloj = PublicadorEspia(), Reloj()
    escena = _escena(espia, reloj)
    banco = _banco(tmp_path, escena=escena)
    espia.publicados.clear()

    banco.despachador.maquina.aceptar(banco.usuario_id, AHORA)
    comando = _mensaje(f"ESCENA {CODIGO}", id_mensaje="wamid.escena")
    banco.despachador.recibir(comando)
    banco.despachador.procesar(comando, AHORA)
    espia.publicados.clear()

    pregunta = _mensaje("¿cuál es la tasa de libre inversión?", id_mensaje="wamid.2")
    banco.despachador.recibir(pregunta)
    banco.despachador.procesar(pregunta, AHORA)

    assert [turno.personaje for turno, _ in espia.publicados] == ["invitado", "pana"]
    assert espia.publicados[0][0].texto == "¿cuál es la tasa de libre inversión?"
    assert espia.publicados[1][0].texto == "respuesta de Pana"
    assert banco.llamadas == ["¿cuál es la tasa de libre inversión?"]


def test_el_comando_no_se_reenvia_al_motor(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """``ESCENA`` no se publica como invitado ni llega al motor."""
    monkeypatch.setenv("ESCENA_EN_VIVO", "1")
    espia, reloj = PublicadorEspia(), Reloj()
    banco = _banco(tmp_path, escena=_escena(espia, reloj))

    _atender(banco, _mensaje(f"ESCENA {CODIGO}"))

    assert banco.enviadas[-1].texto == TEXTO_ACTIVADA
    assert banco.llamadas == []
    assert [turno.personaje for turno, _ in espia.publicados] == ["pana"]


def test_un_codigo_equivocado_no_publica_nada(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """El comando con otro código recibe respuesta privada y no entra en la lista."""
    monkeypatch.setenv("ESCENA_EN_VIVO", "1")
    espia, reloj = PublicadorEspia(), Reloj()
    banco = _banco(tmp_path, escena=_escena(espia, reloj))

    _atender(banco, _mensaje("ESCENA 0000"))

    assert banco.enviadas[-1].texto == "respuesta de Pana"
    assert banco.llamadas == ["ESCENA 0000"]
    assert espia.publicados == []


def test_otro_voluntario_no_reemplaza_al_activo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Un segundo ``ESCENA`` desde otra huella no cambia de voluntario ni publica."""
    monkeypatch.setenv("ESCENA_EN_VIVO", "1")
    espia, reloj = PublicadorEspia(), Reloj()
    escena = _escena(espia, reloj)
    segundo = calcular_usuario_id(OTRO_NUMERO, SAL)
    banco = _banco(tmp_path, escena=escena, huellas_extra=(segundo,))
    primero = banco.usuario_id
    _atender(banco, _mensaje(f"ESCENA {CODIGO}", id_mensaje="wamid.escena"))
    espia.publicados.clear()

    otro = _mensaje(f"ESCENA {CODIGO}", numero=OTRO_NUMERO, id_mensaje="wamid.otro")
    banco.despachador.maquina.aceptar(segundo, AHORA)
    banco.despachador.recibir(otro)
    banco.despachador.procesar(otro, AHORA)

    assert escena.activo(primero) is True
    assert escena.activo(segundo) is False
    assert espia.publicados == []


def test_escena_cancela_la_entrevista_a_medias(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Si el invitado estaba en la entrevista, ``ESCENA`` la descarta."""
    monkeypatch.setenv("ESCENA_EN_VIVO", "1")
    ruta = tmp_path / "whatsapp.sqlite"
    entrevista = EntrevistaCanal(ruta, ttl_minutos=30)
    espia, reloj = PublicadorEspia(), Reloj()
    banco = _banco(tmp_path, escena=_escena(espia, reloj), entrevista=entrevista)
    entrevista.iniciar(banco.usuario_id, "wamid.previo")
    assert entrevista.activa(banco.usuario_id) is True

    _atender(banco, _mensaje(f"ESCENA {CODIGO}", id_mensaje="wamid.escena"))

    assert entrevista.activa(banco.usuario_id) is False


def test_otro_invitado_no_publica_en_el_despachador(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """La conversación privada de otro invitado no entra en la lista."""
    monkeypatch.setenv("ESCENA_EN_VIVO", "1")
    espia, reloj = PublicadorEspia(), Reloj()
    escena = _escena(espia, reloj)
    banco = _banco(tmp_path, escena=escena)
    escena.activar(banco.usuario_id)
    espia.publicados.clear()

    otro = _mensaje("hola", numero=OTRO_NUMERO, id_mensaje="wamid.otro")
    banco.despachador.recibir(otro)
    banco.despachador.procesar(otro, AHORA)

    assert espia.publicados == []
