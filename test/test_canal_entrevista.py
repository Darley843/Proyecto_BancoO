"""Pruebas de la entrevista guiada del diagnóstico por el canal (sin red).

Se cubren dos niveles: la máquina de estados de ``canal.entrevista`` (una
pregunta por turno, texto libre que repite, ``nuevo`` y vencimiento) y el camino
completo desde los payloads del simulador de WhatsApp hasta el enviador falso,
con las cinco personas de ``data/evaluacion/personas_sinteticas.json`` y un
modelo de prueba para el comité.

La tabla Gold se crea en un directorio temporal con las tasas de la vigencia
2026-11: la corrida no depende de la red ni de la fecha del sistema.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.runnables import RunnableLambda

from banco_occidente_corpus.canal.cola import ColaMensajes
from banco_occidente_corpus.canal.configuracion import ConfiguracionCanal
from banco_occidente_corpus.canal.consentimiento import MaquinaConsentimiento
from banco_occidente_corpus.canal.contratos import MensajeEntrante
from banco_occidente_corpus.canal.despachador import Despachador, RespuestaGrafo
from banco_occidente_corpus.canal.entrada import extraer_mensajes
from banco_occidente_corpus.canal.entrevista import TEXTO_SIN_TASA, EntrevistaCanal
from banco_occidente_corpus.canal.envio import EnviadorFalso
from banco_occidente_corpus.canal.identidad import calcular_usuario_id
from banco_occidente_corpus.config import PROJECT_ROOT
from banco_occidente_corpus.simulador.payloads import Payload, numero_ficticio
from banco_occidente_corpus.simulador.personas import (
    Persona,
    SemaforoEsperado,
    Turno,
    cargar_personas,
    conversacion,
)
from banco_occidente_corpus.tablero.tasas import FilaTasa, escribir_tabla

SAL = "sal-de-prueba"
"""Sal HMAC ficticia de las pruebas."""

RUTA_PERSONAS = PROJECT_ROOT / "data" / "evaluacion" / "personas_sinteticas.json"
"""Personas sintéticas del Taller."""

VIGENCIA_DESDE = date(2026, 11, 1)
VIGENCIA_HASTA = date(2026, 11, 30)
FECHA_CONSULTA = datetime(2026, 11, 16, 12, 0, tzinfo=UTC)
"""Fecha fija, dentro de la vigencia de la tabla de prueba."""

SHA_EJEMPLO = "989be43a0ed19eb33e2057cd01c1ae612b6f15544eaaf41af6348846a6ff1b7f"
FUENTE = "https://www.bancodeoccidente.com.co/documents/d/guest/tasas-personas-bdo"

CONSENTIMIENTO = Turno(tipo="boton", valor="consentimiento.acepto", titulo="Acepto")
"""Primer turno del canal: la aceptación de la Ley 1581."""

PERSONAS_DEL_TALLER = (
    "empleada_verde",
    "independiente_rojo",
    "pensionado_amarillo",
    "joven_ahorro",
    "compra_cartera",
)
"""Las cinco personas con semáforo esperado (la sexta es de inyección)."""

TITULO_ESPERADO = {
    SemaforoEsperado.VERDE: "Verde: va bien",
    SemaforoEsperado.AMARILLO: "Amarillo: se puede, con cuidado",
    SemaforoEsperado.ROJO: "Rojo: calma, hay plan",
}


def _fila(
    producto: str,
    desde: str,
    hasta: str,
    segmento: str | None = None,
    plazo_dias: int | None = None,
) -> FilaTasa:
    """Construye una fila de la tabla Gold de prueba.

    Args:
        producto: clave canónica del producto.
        desde: tasa E.A. mínima publicada.
        hasta: tasa E.A. máxima publicada.
        segmento: segmento del Tablero, si el producto tiene varios.
        plazo_dias: plazo del CDT en días, si el producto lo publica.

    Returns:
        La fila lista para escribir la tabla.
    """
    return FilaTasa(
        producto=producto,
        segmento=segmento,
        tipo_tasa="fija",
        plazo_dias=plazo_dias,
        tasa_ea_desde=Decimal(desde),
        tasa_ea_hasta=Decimal(hasta),
        vigencia_desde=VIGENCIA_DESDE,
        vigencia_hasta=VIGENCIA_HASTA,
        fuente=FUENTE,
        sha256_pdf=SHA_EJEMPLO,
        fecha_extraccion=VIGENCIA_DESDE,
    )


@pytest.fixture()
def raiz_tasas(tmp_path: Path) -> Path:
    """Crea una tabla Gold temporal con las tasas de la vigencia 2026-11."""
    filas = [
        _fila("libre_inversion", "0.2056", "0.2817"),
        _fila("compra_cartera", "0.1746", "0.2817"),
        _fila("libranza", "0.1539", "0.2431", "Libre inversión"),
        _fila("libranza", "0.1471", "0.2343", "Compra de cartera"),
        _fila("vivienda", "0.1517", "0.1854", "Crédito hipotecario"),
        _fila("ahorro", "0.0001", "0.0001", "De 0 a $5.000.000"),
        _fila("ahorro", "0.0010", "0.0010", "De $100.000.001 a $3.000.000.000"),
        _fila("cdt", "0.0005", "0.0005", "$500M- $99 MM", 30),
        _fila("cdt", "0.1100", "0.1100", "$500M- $99 MM", 90),
        _fila("cdt", "0.1205", "0.1205", "$500M- $99 MM", 1080),
        _fila("cdt", "0.1215", "0.1215", "$500 MM - 10.000 MM", 1080),
    ]
    escribir_tabla(tmp_path / "tasas-personas-2026-11.jsonl", filas)
    return tmp_path


def _mensaje(texto: str, *, boton: str | None = None, indice: int = 1) -> MensajeEntrante:
    """Construye un mensaje entrante válido para la máquina de la entrevista."""
    return MensajeEntrante(
        id_mensaje=f"wamid.PRUEBA{indice}",
        remitente=numero_ficticio(1),
        texto=texto,
        tipo="interactivo" if boton else "texto",
        id_boton=boton,
        recibido_en=FECHA_CONSULTA,
    )


def _persona(ident: str) -> Persona:
    """Carga una persona sintética por su id.

    Args:
        ident: id de la persona en el JSON.

    Returns:
        La persona validada.
    """
    return next(persona for persona in cargar_personas(RUTA_PERSONAS) if persona.id == ident)


def _paso_guardado(despachador: Despachador, usuario_id: str) -> str | None:
    """Devuelve el paso guardado del usuario, o ``None`` si no hay entrevista.

    Args:
        despachador: despachador con la entrevista configurada.
        usuario_id: huella del número.

    Returns:
        El paso actual, o ``None`` al terminar.
    """
    assert despachador.entrevista is not None
    estado = despachador.entrevista.leer(usuario_id)
    return estado.paso if estado is not None else None


def _rol(sistema: str) -> str:
    """Deduce el rol del comité a partir del prompt del sistema.

    Args:
        sistema: contenido del mensaje del sistema.

    Returns:
        ``riesgo``, ``comercial`` o ``auditor``.
    """
    minusculas = sistema.casefold()
    for rol in ("riesgo", "comercial", "auditor"):
        if f"agente de {rol}" in minusculas or f"agente {rol}" in minusculas:
            return rol
    raise AssertionError("prompt del comité sin rol reconocible")


class ModeloComite:
    """Modelo de prueba que devuelve posturas fijas y cuenta las llamadas."""

    def __init__(self) -> None:
        """Inicializa el registro de llamadas."""
        self.llamadas: list[str] = []

    def with_structured_output(self, schema: Any, **kwargs: Any) -> RunnableLambda:
        """Devuelve un runnable que responde como el rol del prompt.

        Args:
            schema: esquema Pydantic de salida.
            **kwargs: argumentos de LangChain; se ignoran.

        Returns:
            El runnable que valida la postura contra el esquema.
        """

        def invocar(mensajes: list[BaseMessage]) -> dict[str, Any]:
            """Selecciona la postura del rol y la valida contra el esquema."""
            rol = _rol(str(mensajes[0].content))
            self.llamadas.append(rol)
            caso = str(mensajes[-1].content).casefold()
            rojo = '"semaforo": "rojo"' in caso
            posturas = {
                "riesgo": (
                    ("desfavorable", "La cuota no cabe en lo que queda libre cada mes.")
                    if rojo
                    else ("con_condiciones", "La cuota deja poco margen frente al ingreso.")
                ),
                "comercial": (
                    (
                        "desfavorable",
                        "Con estas condiciones no conviene ofrecer el crédito.",
                    )
                    if rojo
                    else (
                        "con_condiciones",
                        "Conviene revisar el plazo y el monto antes de decidir.",
                    )
                ),
                "auditor": ("conforme", "Revisé las cifras del caso."),
            }
            postura, argumento = posturas[rol]
            return {
                "raw": AIMessage(content="ok"),
                "parsed": schema.model_validate(
                    {
                        "agente": rol,
                        "postura": postura,
                        "argumentos": [argumento],
                        "evidencia": [],
                    }
                ),
                "parsing_error": None,
            }

        return RunnableLambda(invocar)


class ModeloQueFalla:
    """Modelo de prueba que siempre lanza un error, como un proveedor caído."""

    def with_structured_output(self, schema: Any, **kwargs: Any) -> RunnableLambda:
        """Devuelve un runnable que falla al invocarse.

        Args:
            schema: esquema Pydantic de salida; no se usa.
            **kwargs: argumentos de LangChain; no se usan.

        Returns:
            El runnable que lanza el error del proveedor.
        """

        def invocar(_mensajes: list[BaseMessage]) -> dict[str, Any]:
            """Simula la caída del modelo del comité."""
            raise RuntimeError("proveedor caído")

        return RunnableLambda(invocar)


def _enviar(payload: Payload, despachador: Despachador) -> None:
    """Extrae los mensajes de un payload y los procesa en el despachador.

    Args:
        payload: payload del webhook construido por el simulador.
        despachador: despachador del canal.
    """
    for mensaje in extraer_mensajes(payload):
        despachador.recibir(mensaje)
        despachador.procesar(mensaje)


def _sin_numero_en_la_base(ruta: Path, numero: str) -> bool:
    """Comprueba que el número en claro no quedó en ninguna tabla.

    Args:
        ruta: archivo SQLite del canal.
        numero: número ficticio de la persona.

    Returns:
        ``True`` si los bytes del número no aparecen en la base.
    """
    return numero.encode("utf-8") not in ruta.read_bytes()


def test_la_primera_pregunta_es_una_lista_con_los_siete_objetivos(tmp_path: Path) -> None:
    """La entrevista arranca con una lista y no con la invitación del grafo."""
    entrevista = EntrevistaCanal(tmp_path / "whatsapp.sqlite")

    respuesta = entrevista.iniciar("u" * 64, "wamid.1")

    assert respuesta.tipo == "lista"
    assert respuesta.texto.endswith("¿Qué te gustaría revisar?")
    assert "orientativo" in respuesta.texto
    assert len(respuesta.opciones) == 7
    assert respuesta.opciones[0].id == "objetivo.libre_inversion"
    assert respuesta.opciones[-1].id == "objetivo.ahorro"


def test_vinculacion_usa_botones_porque_tiene_tres_opciones(tmp_path: Path) -> None:
    """Con tres opciones y títulos cortos, la pregunta va en botones."""
    entrevista = EntrevistaCanal(tmp_path / "whatsapp.sqlite")
    entrevista.iniciar("u" * 64, "wamid.1")

    avance = entrevista.avanzar(
        _mensaje("Libre inversión", boton="objetivo.libre_inversion"), "u" * 64
    )

    assert avance.respuesta is not None
    assert avance.respuesta.tipo == "botones"
    assert [boton.id for boton in avance.respuesta.botones] == [
        "vinculacion.empleado",
        "vinculacion.independiente",
        "vinculacion.pensionado",
    ]


def test_texto_libre_repite_la_pregunta_sin_avanzar(tmp_path: Path) -> None:
    """Un texto que no es una opción repite la pregunta y conserva el paso."""
    ruta = tmp_path / "whatsapp.sqlite"
    entrevista = EntrevistaCanal(ruta)
    entrevista.iniciar("u" * 64, "wamid.1")

    avance = entrevista.avanzar(_mensaje("Quiero un préstamo"), "u" * 64)

    assert avance.respuesta is not None
    assert avance.respuesta.tipo == "lista"
    assert "No alcancé a entender" in avance.respuesta.texto
    estado = entrevista.leer("u" * 64)
    assert estado is not None
    assert estado.paso == "objetivo"
    assert estado.respuestas == {}


def test_nuevo_reinicia_la_entrevista(tmp_path: Path) -> None:
    """El comando «nuevo» borra el avance y vuelve al objetivo."""
    entrevista = EntrevistaCanal(tmp_path / "whatsapp.sqlite")
    entrevista.iniciar("u" * 64, "wamid.1")
    entrevista.avanzar(_mensaje("x", boton="objetivo.libre_inversion"), "u" * 64)

    avance = entrevista.avanzar(_mensaje("nuevo"), "u" * 64)

    assert avance.respuesta is not None
    assert avance.respuesta.texto.endswith("¿Qué te gustaría revisar?")
    estado = entrevista.leer("u" * 64)
    assert estado is not None
    assert estado.paso == "objetivo"
    assert estado.respuestas == {}


def test_cancelar_y_asesor_detienen_la_entrevista(tmp_path: Path) -> None:
    """«Cancelar» y «prefiero un asesor» cierran la entrevista sin inventar datos."""
    for texto in ("cancelar", "prefiero un asesor"):
        entrevista = EntrevistaCanal(tmp_path / f"{texto[:5]}.sqlite")
        entrevista.iniciar("u" * 64, "wamid.1")

        avance = entrevista.avanzar(_mensaje(texto), "u" * 64)

        assert avance.respuesta is not None
        assert avance.respuestas is None
        assert entrevista.leer("u" * 64) is None


def test_la_entrevista_vence_sin_actividad(tmp_path: Path) -> None:
    """Pasado el TTL, el avance se descarta y el turno vuelve al grafo."""
    ahora = [FECHA_CONSULTA]
    entrevista = EntrevistaCanal(
        tmp_path / "whatsapp.sqlite",
        ttl_minutos=10,
        reloj=lambda: ahora[0],
    )
    entrevista.iniciar("u" * 64, "wamid.1")
    assert entrevista.activa("u" * 64)

    ahora[0] = ahora[0] + timedelta(minutes=11)

    assert not entrevista.activa("u" * 64)
    with sqlite3.connect(str(tmp_path / "whatsapp.sqlite")) as conexion:
        total = conexion.execute("SELECT COUNT(*) FROM entrevistas").fetchone()[0]
    assert total == 0


def test_ahorro_no_pregunta_monto_ni_plazo(tmp_path: Path) -> None:
    """Al elegir ahorro, la entrevista termina en las cuotas."""
    entrevista = EntrevistaCanal(tmp_path / "whatsapp.sqlite")
    entrevista.iniciar("u" * 64, "wamid.1")
    respuestas = [
        "objetivo.ahorro",
        "vinculacion.empleado",
        "ingresos.MENOS_2M",
        "gastos.DE_1M_A_2M",
        "cuotas.NINGUNA",
    ]

    avance = None
    for indice, ident in enumerate(respuestas, start=2):
        avance = entrevista.avanzar(_mensaje(ident, boton=ident, indice=indice), "u" * 64)

    assert avance is not None
    assert avance.respuesta is None
    assert avance.respuestas is not None
    assert "monto" not in avance.respuestas
    assert "plazo" not in avance.respuestas
    assert "cuota_trasladar" not in avance.respuestas


def test_compra_de_cartera_pregunta_cuota_trasladar(tmp_path: Path) -> None:
    """Solo la compra de cartera incluye la cuota que se quiere trasladar."""
    entrevista = EntrevistaCanal(tmp_path / "whatsapp.sqlite")
    entrevista.iniciar("u" * 64, "wamid.1")
    for indice, ident in enumerate(
        [
            "objetivo.compra_cartera",
            "vinculacion.empleado",
            "ingresos.DE_3M_A_5M",
            "gastos.DE_1M_A_2M",
            "cuotas.DE_1M_A_2M",
        ],
        start=2,
    ):
        avance = entrevista.avanzar(_mensaje(ident, boton=ident, indice=indice), "u" * 64)

    assert avance.respuesta is not None
    assert avance.respuesta.texto.startswith("¿Cuánto pagas hoy de cuota")
    assert {opcion.id.split(".", 1)[0] for opcion in avance.respuesta.opciones} == {
        "cuota_trasladar"
    }


def test_sin_tasa_publicada_responde_un_texto_explicable(tmp_path: Path) -> None:
    """Si el producto no tiene tasa, no se inventa y se explica al usuario."""
    entrevista = EntrevistaCanal(tmp_path / "whatsapp.sqlite", raiz=tmp_path)
    respuestas = {
        "objetivo": "objetivo.libre_inversion",
        "vinculacion": "vinculacion.empleado",
        "ingresos": "ingresos.DE_5M_A_8M",
        "gastos": "gastos.DE_2M_A_3M",
        "cuotas": "cuotas.NINGUNA",
        "monto": "monto.DE_10M_A_20M",
        "plazo": "plazo.48",
    }

    respuesta = entrevista.completar("u" * 64, "wamid.1", respuestas)

    assert respuesta.tipo == "texto"
    assert respuesta.texto == TEXTO_SIN_TASA


@pytest.mark.parametrize("ident", PERSONAS_DEL_TALLER)
def test_persona_completa_la_entrevista_y_recibe_su_semaforo(
    ident: str, tmp_path: Path, raiz_tasas: Path
) -> None:
    """Cada persona recibe su tarjeta y su semáforo, con texto antes que imagen."""
    persona = _persona(ident)
    ruta = tmp_path / "whatsapp.sqlite"
    usuario_id = calcular_usuario_id(persona.numero, SAL)
    modelo = ModeloComite()
    enviador = EnviadorFalso(ruta)
    llamadas: list[str] = []

    def responder(pregunta: str, _thread_id: str, _perfil: str) -> RespuestaGrafo:
        """Doble del grafo: devuelve la ruta D y anota la pregunta."""
        llamadas.append(pregunta)
        return RespuestaGrafo(texto="Invitación de la ruta D", avisos=("diagnostico",))

    despachador = Despachador(
        config=ConfiguracionCanal(huellas=(usuario_id,)),
        sal=SAL,
        ruta_almacen=ruta,
        maquina=MaquinaConsentimiento(ruta),
        cola=ColaMensajes(),
        crear_enviador=lambda _usuario, _destino: enviador,
        responder=responder,
        entrevista=EntrevistaCanal(
            ruta,
            modelo=modelo,
            hoy=FECHA_CONSULTA,
            raiz=raiz_tasas,
        ),
    )

    for payload in conversacion(persona, preambulo=(CONSENTIMIENTO,)):
        _enviar(payload, despachador)

    assert llamadas == ["Hola, quiero hacer el diagnóstico"]
    assert [tipo for tipo, _ in enviador.registro[-2:]] == ["texto", "imagen"]
    texto_final = enviador.registro[-2][1]
    esperado = persona.esperado.semaforo
    if esperado is None:
        assert "Cuenta de ahorros" in texto_final or "CDT" in texto_final
    else:
        assert TITULO_ESPERADO[esperado] in texto_final
    if persona.esperado.semaforo is SemaforoEsperado.ROJO:
        assert "asesor" in texto_final.casefold()
    if persona.esperado.semaforo is SemaforoEsperado.AMARILLO:
        assert "comité" in texto_final.casefold()
        assert len(modelo.llamadas) == 3
    if persona.esperado.semaforo in {SemaforoEsperado.VERDE, None}:
        assert modelo.llamadas == []
    assert _paso_guardado(despachador, usuario_id) is None
    assert _sin_numero_en_la_base(ruta, persona.numero)


def test_si_el_comite_falla_se_responde_con_el_diagnostico(
    tmp_path: Path, raiz_tasas: Path
) -> None:
    """Un proveedor caído no deja a la persona sin diagnóstico ni oferta de asesor."""
    persona = _persona("independiente_rojo")
    ruta = tmp_path / "whatsapp.sqlite"
    enviador = EnviadorFalso(ruta)
    usuario_id = calcular_usuario_id(persona.numero, SAL)
    despachador = Despachador(
        config=ConfiguracionCanal(huellas=(usuario_id,)),
        sal=SAL,
        ruta_almacen=ruta,
        maquina=MaquinaConsentimiento(ruta),
        cola=ColaMensajes(),
        crear_enviador=lambda _usuario, _destino: enviador,
        responder=lambda _p, _t, _f: RespuestaGrafo("hola", ("diagnostico",)),
        entrevista=EntrevistaCanal(
            ruta,
            modelo=ModeloQueFalla(),
            hoy=FECHA_CONSULTA,
            raiz=raiz_tasas,
        ),
    )

    for payload in conversacion(persona, preambulo=(CONSENTIMIENTO,)):
        _enviar(payload, despachador)

    assert [tipo for tipo, _ in enviador.registro[-2:]] == ["texto", "imagen"]
    texto_final = enviador.registro[-2][1]
    assert TITULO_ESPERADO[SemaforoEsperado.ROJO] in texto_final
    assert "comité" not in texto_final.casefold()
    assert "asesor" in texto_final.casefold()


def test_al_completar_se_guarda_la_tarjeta_y_no_el_numero(tmp_path: Path, raiz_tasas: Path) -> None:
    """La respuesta final lleva tarjeta y el número no queda en SQLite."""
    persona = _persona("empleada_verde")
    ruta = tmp_path / "whatsapp.sqlite"
    enviador = EnviadorFalso(ruta)
    usuario_id = calcular_usuario_id(persona.numero, SAL)
    despachador = Despachador(
        config=ConfiguracionCanal(huellas=(usuario_id,)),
        sal=SAL,
        ruta_almacen=ruta,
        maquina=MaquinaConsentimiento(ruta),
        cola=ColaMensajes(),
        crear_enviador=lambda _usuario, _destino: enviador,
        responder=lambda _p, _t, _f: RespuestaGrafo("hola", ("diagnostico",)),
        entrevista=EntrevistaCanal(ruta, hoy=FECHA_CONSULTA, raiz=raiz_tasas),
    )

    for payload in conversacion(persona, preambulo=(CONSENTIMIENTO,)):
        _enviar(payload, despachador)

    assert _sin_numero_en_la_base(ruta, persona.numero)
    with sqlite3.connect(str(ruta)) as conexion:
        respuestas = conexion.execute("SELECT respuestas_json FROM entrevistas").fetchall()
    assert respuestas == []
