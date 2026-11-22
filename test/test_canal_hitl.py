"""Pruebas del HITL con el asesor en el canal (tareas 4.1, 4.2 y 4.4, sin red).

El rojo suspende la entrevista con `interrupt()` y dos botones; contactar abre
el caso y descartar no lo crea. La reanudación llega por el despachador, usa el
hilo de la persona y no toca el de otra.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from banco_occidente_corpus.canal.almacen import listar_casos
from banco_occidente_corpus.canal.cola import ColaMensajes
from banco_occidente_corpus.canal.configuracion import ConfiguracionCanal
from banco_occidente_corpus.canal.consentimiento import MaquinaConsentimiento
from banco_occidente_corpus.canal.contratos import MensajeEntrante
from banco_occidente_corpus.canal.despachador import Despachador, RespuestaGrafo
from banco_occidente_corpus.canal.entrevista import (
    ID_CONTACTAR,
    ID_DESCARTAR,
    PREGUNTA_HITL,
    TEXTO_ASESOR,
    TEXTO_CONTACTADO,
    TEXTO_DESCARTADO,
    TEXTO_SIN_CASO,
    EntrevistaCanal,
)
from banco_occidente_corpus.canal.envio import EnviadorFalso
from banco_occidente_corpus.canal.hitl import HitlAsesor, limpiar_hilo
from banco_occidente_corpus.canal.identidad import calcular_usuario_id
from banco_occidente_corpus.tablero.tasas import FilaTasa, escribir_tabla

SAL = "sal-de-prueba"
NUMERO_A = "57000000001"
NUMERO_B = "57000000002"
AHORA = datetime(2026, 11, 16, 12, 0, tzinfo=UTC)
VIGENCIA_DESDE = date(2026, 11, 1)
VIGENCIA_HASTA = date(2026, 11, 30)
FUENTE = "https://www.bancodeoccidente.com.co/documents/d/guest/tasas-personas-bdo"

#: Entrevista completa que termina en rojo.
ROJO: dict[str, str] = {
    "objetivo": "objetivo.libre_inversion",
    "vinculacion": "vinculacion.independiente",
    "ingresos": "ingresos.DE_2M_A_3M",
    "gastos": "gastos.DE_1M_A_2M",
    "cuotas": "cuotas.DE_500K_A_1M",
    "monto": "monto.DE_20M_A_50M",
    "plazo": "plazo.36",
}


@pytest.fixture()
def raiz(tmp_path: Path) -> Path:
    """Tabla Gold temporal con la tasa de libre inversión."""
    escribir_tabla(
        tmp_path / "tasas-personas-2026-11.jsonl",
        [
            FilaTasa(
                producto="libre_inversion",
                segmento=None,
                tipo_tasa="fija",
                plazo_dias=None,
                tasa_ea_desde=Decimal("0.2056"),
                tasa_ea_hasta=Decimal("0.2817"),
                vigencia_desde=VIGENCIA_DESDE,
                vigencia_hasta=VIGENCIA_HASTA,
                fuente=FUENTE,
                sha256_pdf="0" * 64,
                fecha_extraccion=VIGENCIA_DESDE,
            )
        ],
    )
    return tmp_path


def _mensaje(texto: str, *, boton: str | None = None, indice: int = 1) -> MensajeEntrante:
    """Construye un mensaje entrante válido."""
    return MensajeEntrante(
        id_mensaje=f"wamid.HITL{indice}",
        remitente=NUMERO_A,
        texto=texto,
        tipo="interactivo" if boton else "texto",
        id_boton=boton,
        recibido_en=AHORA,
    )


def _entrevista(ruta: Path, raiz: Path) -> EntrevistaCanal:
    """Entrevista con la tabla de prueba y la fecha fija de la vigencia."""
    return EntrevistaCanal(ruta, hoy=AHORA, raiz=raiz)


def test_rojo_suspende_con_dos_botones(tmp_path: Path, raiz: Path) -> None:
    """El rojo no manda la tarjeta todavía: resumen y botones."""
    ruta = tmp_path / "whatsapp.sqlite"
    entrevista = _entrevista(ruta, raiz)
    usuario = "u" * 64

    respuesta = entrevista.completar(usuario, "wamid.1", ROJO)

    assert respuesta.tipo == "botones"
    assert PREGUNTA_HITL in respuesta.texto
    assert [boton.id for boton in respuesta.botones] == [ID_CONTACTAR, ID_DESCARTAR]
    assert entrevista._hitl.suspendido(usuario) is True
    assert listar_casos(ruta) == ()


def test_contactar_abre_el_caso_y_manda_la_tarjeta(tmp_path: Path, raiz: Path) -> None:
    """Contactar reanuda el hilo, crea el caso y entrega la tarjeta."""
    ruta = tmp_path / "whatsapp.sqlite"
    entrevista = _entrevista(ruta, raiz)
    usuario = "u" * 64
    entrevista.completar(usuario, "wamid.1", ROJO)

    respuesta = entrevista.reanudar(_mensaje("Contactar", boton=ID_CONTACTAR), usuario)

    assert respuesta is not None
    assert respuesta.tipo == "imagen"
    assert respuesta.imagen is not None
    assert respuesta.texto.startswith(TEXTO_CONTACTADO)
    casos = listar_casos(ruta)
    assert len(casos) == 1
    assert casos[0].usuario_id == usuario
    assert casos[0].motivo == "semaforo_rojo"
    assert casos[0].semaforo == "rojo"
    assert casos[0].estado == "pendiente"
    assert casos[0].resultado is None  # la tarjeta vive en resultados_diagnostico
    assert entrevista._hitl.suspendido(usuario) is False


def test_descartar_no_crea_caso(tmp_path: Path, raiz: Path) -> None:
    """Descartar cierra el turno y no deja caso pendiente."""
    ruta = tmp_path / "whatsapp.sqlite"
    entrevista = _entrevista(ruta, raiz)
    usuario = "u" * 64
    entrevista.completar(usuario, "wamid.1", ROJO)

    respuesta = entrevista.reanudar(_mensaje("Descartar", boton=ID_DESCARTAR), usuario)

    assert respuesta is not None
    assert respuesta.tipo == "imagen"
    assert respuesta.texto.startswith(TEXTO_DESCARTADO)
    assert listar_casos(ruta) == ()
    assert entrevista._hitl.suspendido(usuario) is False


def test_una_segunda_pulsacion_no_duplica(tmp_path: Path, raiz: Path) -> None:
    """Sin hilo suspendido, el botón responde el aviso y no crea otro caso."""
    ruta = tmp_path / "whatsapp.sqlite"
    entrevista = _entrevista(ruta, raiz)
    usuario = "u" * 64
    entrevista.completar(usuario, "wamid.1", ROJO)
    entrevista.reanudar(_mensaje("Contactar", boton=ID_CONTACTAR), usuario)

    respuesta = entrevista.reanudar(_mensaje("Contactar", boton=ID_CONTACTAR), usuario)

    assert respuesta is not None
    assert respuesta.texto == TEXTO_SIN_CASO
    assert len(listar_casos(ruta)) == 1


def test_mensaje_distinto_repite_los_botones(tmp_path: Path, raiz: Path) -> None:
    """Con un caso suspendido, otro texto recuerda las dos opciones."""
    ruta = tmp_path / "whatsapp.sqlite"
    entrevista = _entrevista(ruta, raiz)
    usuario = "u" * 64
    entrevista.completar(usuario, "wamid.1", ROJO)

    respuesta = entrevista.reanudar(_mensaje("hola"), usuario)

    assert respuesta is not None
    assert respuesta.tipo == "botones"
    assert [boton.id for boton in respuesta.botones] == [ID_CONTACTAR, ID_DESCARTAR]
    assert listar_casos(ruta) == ()


def test_asesor_directo_abre_caso_sin_diagnostico(tmp_path: Path, raiz: Path) -> None:
    """Pedir asesor a mitad de la entrevista abre el caso y la deja."""
    ruta = tmp_path / "whatsapp.sqlite"
    entrevista = _entrevista(ruta, raiz)
    usuario = "u" * 64
    entrevista.iniciar(usuario, "wamid.1")

    avance = entrevista.avanzar(_mensaje("prefiero un asesor"), usuario)

    assert avance.respuesta is not None
    assert avance.respuesta.texto == TEXTO_ASESOR
    assert entrevista.activa(usuario) is False
    casos = listar_casos(ruta)
    assert len(casos) == 1
    assert casos[0].motivo == "asesor_solicitado"
    assert casos[0].semaforo == "pendiente"


def test_el_despachador_reanuda_el_boton(tmp_path: Path, raiz: Path) -> None:
    """El botón que llega por el webhook lo resuelve la entrevista."""
    ruta = tmp_path / "whatsapp.sqlite"
    usuario = calcular_usuario_id(NUMERO_A, SAL)
    maquina = MaquinaConsentimiento(ruta)
    maquina.aceptar(usuario, AHORA)
    enviador = EnviadorFalso(ruta)
    entrevista = _entrevista(ruta, raiz)
    despachador = Despachador(
        config=ConfiguracionCanal(huellas=(usuario,)),
        sal=SAL,
        ruta_almacen=ruta,
        maquina=maquina,
        cola=ColaMensajes(),
        crear_enviador=lambda _usuario, _destino: enviador,
        responder=lambda _p, _t, _f: RespuestaGrafo("respuesta del grafo"),
        entrevista=entrevista,
    )
    entrevista.completar(usuario, "wamid.1", ROJO)
    mensaje = _mensaje("Contactar", boton=ID_CONTACTAR)

    despachador.recibir(mensaje)
    despachador.procesar(mensaje)

    assert [tipo for tipo, _ in enviador.registro[-2:]] == ["texto", "imagen"]
    assert len(listar_casos(ruta)) == 1


def test_un_hilo_ajeno_no_se_ve_afectado(tmp_path: Path, raiz: Path) -> None:
    """Suspender a una persona no toca la entrevista de la otra."""
    ruta = tmp_path / "whatsapp.sqlite"
    entrevista = _entrevista(ruta, raiz)
    usuario_a = "a" * 64
    usuario_b = "b" * 64
    entrevista.iniciar(usuario_b, "wamid.B1")
    entrevista.completar(usuario_a, "wamid.A1", ROJO)

    respuesta_b = entrevista.avanzar(
        _mensaje("objetivo.libre_inversion", boton="objetivo.libre_inversion"),
        usuario_b,
    )

    assert respuesta_b.respuesta is not None
    assert respuesta_b.respuesta.tipo == "botones"  # vinculación
    assert entrevista._hitl.suspendido(usuario_b) is False
    assert listar_casos(ruta) == ()
    assert entrevista._hitl.suspendido(usuario_a) is True


def test_sin_action_valida_la_reanudacion_falla(tmp_path: Path) -> None:
    """Una acción que no es contactar ni descartar no toca el caso."""
    ruta = tmp_path / "whatsapp.sqlite"
    hitl = HitlAsesor(ruta)
    hitl.suspender("u" * 64, motivo="semaforo_rojo", semaforo="rojo")

    assert hitl.reanudar("u" * 64, "otra") is None  # type: ignore[arg-type]
    assert hitl.suspendido("u" * 64) is True
    assert listar_casos(ruta) == ()


def test_revocar_limpia_el_hilo_suspendido(tmp_path: Path, raiz: Path) -> None:
    """«Olvida mis datos» no deja el HITL suspendido en la base."""
    ruta = tmp_path / "whatsapp.sqlite"
    hitl = HitlAsesor(ruta)
    usuario = "u" * 64
    hitl.suspender(usuario, motivo="semaforo_rojo", semaforo="rojo")
    maquina = MaquinaConsentimiento(ruta)
    maquina.aceptar(usuario, AHORA)

    respuesta = maquina.decidir(_mensaje("olvida mis datos"), usuario)

    assert respuesta is not None
    assert hitl.suspendido(usuario) is False
    assert listar_casos(ruta) == ()


def test_limpiar_hilo_sin_tablas_del_saver_no_falla(tmp_path: Path) -> None:
    """Una base sin checkpoint se deja como está, sin lanzar error."""
    ruta = tmp_path / "vacia.sqlite"
    ruta.touch()

    limpiar_hilo(ruta, "u" * 64)

    assert ruta.exists()
