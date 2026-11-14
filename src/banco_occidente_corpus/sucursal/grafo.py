"""Grafo de la Sucursal: digiturno, perfil, Bóveda, Tablero y redacción.

El estado viaja entre nodos como datos serializables (diccionarios) para que el
checkpointer SQLite no dependa de tipos propios. La memoria corta se aísla por
`thread_id`; la memoria de perfil usa el store de LangGraph con un namespace
propio y nunca pasa por la caché. El historial se recorta antes de cada llamada
al modelo y la pregunta con datos personales se rechaza antes de entrar al grafo.
"""

from __future__ import annotations

import re
import sqlite3
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Annotated, Any, TypedDict, cast

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    trim_messages,
)
from langchain_core.messages.utils import count_tokens_approximately
from langgraph.channels import UntrackedValue
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.runtime import Runtime
from langgraph.store.base import BaseStore
from pydantic import ValidationError

from ..asistente.contexto_prompt import CanalOficial
from ..asistente.metricas import extraer_metricas
from ..asistente.prompts import Prompt, cargar_prompt
from ..asistente.rag import ContextoRag
from ..asistente.validacion import (
    detectar_pii,
    mensaje_pii,
    respuesta_sin_datos,
    sanear_pregunta,
    texto_de_contenido,
)
from ..boveda.tipos import Fragmento, Recuperador
from ..tablero.consultas import concepto_sin_franquicia
from ..tablero.herramienta import crear_herramienta_tablero, filas_de_consulta
from ..tablero.tipos import Fila
from ..texto import normalizar
from .digiturno import (
    Clasificador,
    ConfiguracionDigiturno,
    ContadorTurnos,
    clasificar,
)
from .perfil import (
    MENSAJE_PERFIL_BORRADO,
    MENSAJE_PERFIL_INACTIVO,
    AlmacenPerfil,
    confirmacion_perfil,
    detectar_intencion,
    respuesta_perfil,
)

#: Tokens de historial que se conservan antes de llamar al modelo.
HISTORIAL_MAX_TOKENS = 1200
#: Filas que la plantilla del Tablero puede listar sin volverse una tabla enorme.
MAX_FILAS_TABLERO = 10
#: Filas que se piden a la herramienta. Una más que el tope de la plantilla
#: permite distinguir «justo el máximo» de «demasiadas y ambigua».
FILAS_PARA_DECIDIR = MAX_FILAS_TABLERO + 1
#: Tope de tokens de la reformulación. Una pregunta autónoma es corta y el
#: razonamiento de DeepSeek Flash cabe de sobra en 512, igual que en el
#: clasificador; el tope de `qa` (2000) es para una respuesta completa con citas.
MAX_TOKENS_REFORMULAR: int = 512
#: Instrucción para convertir un seguimiento en pregunta autónoma.
INSTRUCCION_REFORMULAR = (
    "Reescribe la última pregunta como una pregunta autónoma en español, usando "
    "el historial solo para resolver a qué se refiere. No respondas la pregunta, "
    "no añadas datos y devuelve únicamente la pregunta reformulada."
)
#: Signos que abren una pregunta y no deben romper la detección de seguimiento.
_PUNTUACION_INICIAL = re.compile(r"^[\s¿¡\"'«»]+")
#: Prefijos que delatan un seguimiento conversacional (texto ya normalizado).
PREFIJOS_SEGUIMIENTO = ("cuanto", "cuanta", "cuantos", "cuantas", "cual", "cuales")
#: Palabras que remiten a algo dicho antes en la conversación.
_ANAFORAS = frozenset(
    {
        "anterior",
        "dicha",
        "dicho",
        "esa",
        "ese",
        "eso",
        "esta",
        "estas",
        "este",
        "esto",
        "estos",
        "misma",
        "mismo",
        "su",
        "sus",
        "tambien",
        "usarla",
        "usarlo",
    }
)


class EstadoSucursal(TypedDict, total=False):
    """Estado que comparten los nodos del grafo."""

    messages: Annotated[list[BaseMessage], add_messages]
    pregunta: str
    reformulada: str
    turno: dict[str, Any]
    filas: list[dict[str, str]]
    fragmentos: list[dict[str, Any]]
    # La respuesta y la confirmación pueden repetir nombre o empresa: se
    # devuelven al servicio, pero no se escriben en el checkpoint.
    respuesta: Annotated[str, UntrackedValue]
    fuentes: list[str]
    uso: dict[str, Any]
    usos: list[dict[str, Any]]
    avisos: list[str]
    perfil: str
    perfil_tocado: bool
    perfil_modificado: bool
    confirmacion_perfil: Annotated[str, UntrackedValue]


@dataclass(frozen=True, slots=True)
class ContextoSucursal:
    """Contexto de ejecución que no forma parte del checkpoint.

    ``pregunta_original`` solo vive en memoria mientras corre el turno; permite
    que el nodo ``perfil`` extraiga nombre y empresa sin guardar el mensaje
    original en el estado persistido.
    """

    perfil: str = ""
    pregunta_original: str = ""


@dataclass(frozen=True, slots=True)
class DependenciasGrafo:
    """Piezas que el grafo recibe para no tocar red ni disco por su cuenta."""

    recuperador: Recuperador
    filas: Sequence[Fila] = ()
    modelo: BaseChatModel | None = None
    clasificador: Clasificador | None = None
    canal: CanalOficial | None = None
    prompt: Prompt = field(default_factory=lambda: cargar_prompt("qa", "v2"))
    configuracion_digiturno: ConfiguracionDigiturno | None = None
    contador: ContadorTurnos = field(default_factory=ContadorTurnos)
    k: int = 5
    historial_max_tokens: int = HISTORIAL_MAX_TOKENS

    @property
    def permitidos(self) -> tuple[str, ...]:
        """Teléfonos públicos del canal, exentos del filtro de PII."""
        return self.canal.telefonos if self.canal else ()


def es_seguimiento(pregunta: str) -> bool:
    """Decide si la pregunta depende del turno anterior.

    Limpia los signos de apertura para que «¿Cuánto…?» y «Cuánto…» se traten
    igual. Es seguimiento si empieza por «y », o por una palabra de pregunta
    cuando además es corta o contiene una anáfora («su», «usarla», «esa»).
    Una pregunta autónoma corta como «¿Qué es un CDT?» no lo es.

    Args:
        pregunta: texto del cliente.

    Returns:
        True si la pregunta necesita el historial para interpretarse.
    """
    normalizada = _PUNTUACION_INICIAL.sub("", normalizar(pregunta)).strip()
    palabras = normalizada.split()
    if normalizada.startswith("y "):
        return True
    if normalizada == "como" or normalizada.startswith("como "):
        return len(palabras) <= 3
    if re.match(rf"^({'|'.join(PREFIJOS_SEGUIMIENTO)})\b", normalizada):
        return len(palabras) <= 4 or any(palabra in _ANAFORAS for palabra in palabras)
    return False


def recortar_historial(mensajes: Sequence[BaseMessage], max_tokens: int) -> list[BaseMessage]:
    """Recorta el historial con `trim_messages` y el contador aproximado."""
    if not mensajes:
        return []
    return list(
        trim_messages(
            list(mensajes),
            max_tokens=max_tokens,
            strategy="last",
            token_counter=count_tokens_approximately,
        )
    )


def crear_grafo(
    dependencias: DependenciasGrafo,
    ruta_memoria: Path,
    *,
    store: BaseStore | None = None,
) -> Any:
    """Compila el grafo con memoria SQLite y el store de largo plazo.

    Args:
        dependencias: recuperador, modelo, filas del Tablero y canal.
        ruta_memoria: archivo SQLite del checkpointer.
        store: store de LangGraph para el perfil. Si falta se usa uno en memoria,
            que es lo que necesitan las pruebas que no inyectan `SqliteStore`.

    Returns:
        La aplicación compilada de LangGraph.
    """
    ruta_memoria.parent.mkdir(parents=True, exist_ok=True)
    conexion = sqlite3.connect(str(ruta_memoria), check_same_thread=False)
    checkpointer = SqliteSaver(conexion)
    if store is None:
        from langgraph.store.memory import InMemoryStore

        store = InMemoryStore()

    # `ty` no reconoce el TypedDict con `add_messages` como StateLike; el cast
    # mantiene el tipado en el resto del módulo sin relajar el estado en runtime.
    constructor = StateGraph(
        cast(Any, EstadoSucursal),
        context_schema=cast(Any, ContextoSucursal),
    )
    constructor.add_node("reformular", cast(Any, _nodo_reformular(dependencias)))
    constructor.add_node("digiturno", cast(Any, _nodo_digiturno(dependencias)))
    constructor.add_node("perfil", cast(Any, _nodo_perfil(dependencias)))
    constructor.add_node("boveda", cast(Any, _nodo_boveda(dependencias)))
    constructor.add_node("tablero", cast(Any, _nodo_tablero(dependencias)))
    constructor.add_node("mixto", cast(Any, _nodo_mixto(dependencias)))
    constructor.add_node("cortesia", cast(Any, _nodo_cortesia(dependencias)))
    constructor.add_node("rechazo", cast(Any, _nodo_rechazo(dependencias)))
    constructor.add_node("redactar", cast(Any, _nodo_redactar(dependencias)))

    constructor.add_edge(START, "reformular")
    constructor.add_edge("reformular", "digiturno")
    constructor.add_conditional_edges(
        "digiturno",
        _ruta_digiturno,
        {
            "X": "rechazo",
            "T": "tablero",
            "B": "boveda",
            "mixto": "mixto",
            "cortesia": "cortesia",
            "perfil": "perfil",
        },
    )
    constructor.add_conditional_edges(
        "perfil",
        _ruta_despues_de_perfil,
        {
            "fin": END,
            "boveda": "boveda",
            "tablero": "tablero",
            "mixto": "mixto",
            "cortesia": "cortesia",
            "rechazo": "rechazo",
        },
    )
    constructor.add_conditional_edges(
        "boveda",
        _ruta_boveda,
        {"redactar": "redactar", "rechazo": "rechazo"},
    )
    constructor.add_conditional_edges(
        "tablero",
        _ruta_tablero,
        {"redactar": "redactar", "boveda": "boveda"},
    )
    constructor.add_conditional_edges(
        "mixto",
        _ruta_boveda,
        {"redactar": "redactar", "rechazo": "rechazo"},
    )
    constructor.add_edge("cortesia", END)
    constructor.add_edge("rechazo", END)
    constructor.add_edge("redactar", END)

    return constructor.compile(checkpointer=checkpointer, store=store)


def responder_turno(
    grafo: Any,
    dependencias: DependenciasGrafo,
    pregunta: str,
    thread_id: str,
    perfil: str = "",
) -> dict[str, Any]:
    """Ejecuta un turno, rechazando la PII antes de entrar a la memoria.

    Args:
        grafo: aplicación compilada con `crear_grafo`.
        dependencias: mismas dependencias usadas al compilar.
        pregunta: texto del cliente.
        thread_id: identificador de la conversación.
        perfil: hash del identificador de perfil, o vacío si la memoria de
            perfil no está activa en esta conversación.

    Returns:
        El estado final del turno.
    """
    limpia = sanear_pregunta(pregunta)
    deteccion = detectar_pii(limpia, permitidos=dependencias.permitidos)
    if deteccion is not None:
        numero = dependencias.contador.siguiente()
        return {
            "turno": {"numero": numero, "letra": "X", "motivo": f"pii:{deteccion.categoria}"},
            "respuesta": mensaje_pii(deteccion.categoria, dependencias.canal),
            "fuentes": [dependencias.canal.url]
            if dependencias.canal and dependencias.canal.url
            else [],
            "uso": {"uso_modelo": False},
            "usos": [],
            "avisos": ["pii_bloqueada"],
            "messages": [],
        }

    # La memoria del hilo no conserva el mensaje original de un turno de
    # perfil. En el mixto solo entra el residual; en el perfil puro, nada. Así
    # una reformulación posterior nunca recibe el nombre ni la empresa.
    intencion = detectar_intencion(limpia)
    if intencion is not None:
        mensajes = [HumanMessage(content=intencion.resto)] if perfil and intencion.resto else []
    else:
        mensajes = [HumanMessage(content=limpia)]

    pregunta_estado = intencion.resto if intencion is not None else limpia
    return grafo.invoke(
        {
            "messages": mensajes,
            "pregunta": pregunta_estado,
            "reformulada": "",
            "turno": {},
            "filas": [],
            "fragmentos": [],
            "respuesta": "",
            "fuentes": [],
            "uso": {},
            "usos": [],
            "avisos": [],
            "perfil": perfil,
            "perfil_tocado": intencion is not None,
            "perfil_modificado": False,
            "confirmacion_perfil": "",
        },
        config={"configurable": {"thread_id": thread_id}},
        context=ContextoSucursal(perfil=perfil, pregunta_original=limpia),
    )


def registrar_turno(grafo: Any, pregunta: str, respuesta: str, thread_id: str) -> None:
    """Añade a la memoria del hilo un turno que no pasó por el grafo.

    Lo usa la API cuando la respuesta viene de la caché: el turno no ejecuta
    nodos, pero la siguiente pregunta de seguimiento necesita el par
    pregunta/respuesta en el `checkpointer` para reformularse.

    Args:
        grafo: aplicación compilada con `crear_grafo`.
        pregunta: pregunta saneada que envió el cliente.
        respuesta: texto que se devolvió al cliente.
        thread_id: identificador de la conversación.

    Raises:
        Exception: cualquier fallo del `checkpointer` se propaga al llamador, que
            decide si puede seguir sin historial.
    """
    grafo.update_state(
        {"configurable": {"thread_id": thread_id}},
        {"messages": [HumanMessage(content=pregunta), AIMessage(content=respuesta)]},
        as_node="redactar",
    )


def _nodo_reformular(dependencias: DependenciasGrafo) -> Callable[[EstadoSucursal], dict[str, Any]]:
    """Crea el nodo que reformula un seguimiento cuando hace falta."""

    def reformular(estado: EstadoSucursal) -> dict[str, Any]:
        pregunta = estado.get("pregunta", "")
        # Un turno de perfil no se reformula: el mensaje original contiene
        # nombre o empresa y no debe llegar al modelo por el historial.
        if estado.get("perfil_tocado"):
            return {"reformulada": pregunta}
        historial = list(estado.get("messages", []))[:-1]
        if not historial or not es_seguimiento(pregunta) or dependencias.modelo is None:
            return {"reformulada": pregunta}

        previos = recortar_historial(historial, dependencias.historial_max_tokens)
        mensajes = (
            [SystemMessage(content=INSTRUCCION_REFORMULAR)]
            + previos
            + [HumanMessage(content=pregunta)]
        )
        usos = list(estado.get("usos") or [])
        try:
            salida = dependencias.modelo.invoke(mensajes, max_tokens=MAX_TOKENS_REFORMULAR)
            texto = texto_de_contenido(salida.content).strip()
        except Exception:
            return {"reformulada": pregunta}
        usos.append(extraer_metricas(salida))
        return {"reformulada": texto or pregunta, "usos": usos}

    return reformular


def _nodo_digiturno(dependencias: DependenciasGrafo) -> Callable[..., dict[str, Any]]:
    """Crea el nodo que asigna el turno con el digiturno."""

    def digiturno(
        estado: EstadoSucursal,
        *,
        runtime: Runtime[ContextoSucursal],
    ) -> dict[str, Any]:
        consulta = estado.get("reformulada") or estado.get("pregunta", "")
        if estado.get("perfil_tocado"):
            # El estado guarda solo el residual; el mensaje original viaja en
            # el contexto de ejecución para que el digiturno lo clasifique.
            consulta = runtime.context.pregunta_original or consulta
        usos = list(estado.get("usos") or [])
        turno = clasificar(
            consulta,
            configuracion=dependencias.configuracion_digiturno,
            permitidos=dependencias.permitidos,
            clasificador=dependencias.clasificador,
            registrar_uso=usos.append,
            contador=dependencias.contador,
        )
        return {"turno": asdict(turno), "usos": usos}

    return digiturno


def _nodo_perfil(
    dependencias: DependenciasGrafo,
) -> Callable[..., dict[str, Any]]:
    """Crea el nodo que guarda, consulta o borra la memoria de perfil.

    El nodo recibe el `Runtime` con el `store` que LangGraph inyecta desde
    `compile(checkpointer=..., store=...)` y el mensaje original en el contexto
    de ejecución; no abre archivos ni lee el original del estado persistido. Si
    la conversación no trae `perfil_id`, responde el mensaje de memoria inactiva
    sin guardar nada. Si el mensaje trae PII, tampoco guarda.
    """

    def perfil(
        estado: EstadoSucursal,
        *,
        runtime: Runtime[ContextoSucursal],
    ) -> dict[str, Any]:
        pregunta = runtime.context.pregunta_original
        intencion = detectar_intencion(pregunta)
        turno = dict(estado.get("turno", {}))
        if intencion is None:
            return {"perfil_tocado": True}

        deteccion = detectar_pii(pregunta, permitidos=dependencias.permitidos)
        if deteccion is not None:
            texto = mensaje_pii(deteccion.categoria, dependencias.canal)
            turno["letra"] = "X"
            turno["motivo"] = f"pii:{deteccion.categoria}"
            return {
                "turno": turno,
                "respuesta": texto,
                "fuentes": [dependencias.canal.url]
                if dependencias.canal and dependencias.canal.url
                else [],
                "uso": {"uso_modelo": False, "costo_usd": 0.0},
                "avisos": ["pii_bloqueada"],
                "messages": [AIMessage(content=texto)],
                "perfil_tocado": True,
                "perfil_modificado": False,
            }

        identificador = runtime.context.perfil
        if not identificador or runtime.store is None:
            return _respuesta_perfil_inactiva(turno)

        almacen = AlmacenPerfil(runtime.store)
        datos = almacen.leer(identificador)
        guardados = [dato.campo for dato in intencion.guardar]
        if intencion.borrar:
            almacen.borrar(identificador)
            datos = {}
            guardados = []
        elif guardados:
            datos = almacen.guardar(
                identificador,
                {dato.campo: dato.valor for dato in intencion.guardar},
            )
        modificado = intencion.borrar or bool(guardados)

        prefijo = ""
        if intencion.borrar:
            prefijo = MENSAJE_PERFIL_BORRADO
        else:
            partes: list[str] = []
            if guardados:
                partes.append(confirmacion_perfil(datos, guardados))
            if intencion.consultar:
                partes.append(respuesta_perfil(datos, intencion.consultar))
            prefijo = " ".join(parte for parte in partes if parte)

        if intencion.resto:
            motivo_residual = str(turno.get("motivo_residual") or "defecto")
            turno["motivo"] = f"perfil:{motivo_residual}"
            return {
                "turno": turno,
                "confirmacion_perfil": prefijo,
                "reformulada": intencion.resto,
                "perfil_tocado": True,
                "perfil_modificado": modificado,
                "avisos": ["perfil"],
            }

        texto = prefijo or respuesta_perfil(datos, intencion.consultar)
        turno["motivo"] = "perfil"
        # Sin AIMessage: la respuesta puede repetir nombre o empresa y no debe
        # quedar en el historial que luego recibe una reformulación.
        return {
            "turno": turno,
            "respuesta": texto,
            "fuentes": [],
            "uso": {"uso_modelo": False, "costo_usd": 0.0},
            "avisos": ["perfil"],
            "perfil_tocado": True,
            "perfil_modificado": modificado,
        }

    return perfil


def _respuesta_perfil_inactiva(turno: dict[str, Any]) -> dict[str, Any]:
    """Arma la respuesta corta de una conversación sin `perfil_id`."""
    turno["letra"] = "B"
    turno["motivo"] = "perfil"
    return {
        "turno": turno,
        "respuesta": MENSAJE_PERFIL_INACTIVO,
        "fuentes": [],
        "uso": {"uso_modelo": False, "costo_usd": 0.0},
        "avisos": ["perfil_inactivo"],
        "perfil_tocado": True,
        "perfil_modificado": False,
    }


def _nodo_boveda(dependencias: DependenciasGrafo) -> Callable[[EstadoSucursal], dict[str, Any]]:
    """Crea el nodo que recupera fragmentos de la Bóveda."""

    def boveda(estado: EstadoSucursal) -> dict[str, Any]:
        consulta = estado.get("reformulada") or estado.get("pregunta", "")
        fragmentos = dependencias.recuperador.buscar(consulta, k=dependencias.k)
        return {"fragmentos": [asdict(fragmento) for fragmento in fragmentos]}

    return boveda


def _nodo_tablero(dependencias: DependenciasGrafo) -> Callable[[EstadoSucursal], dict[str, Any]]:
    """Crea el nodo que responde con filas del Tablero o devuelve la ruta a B.

    La búsqueda se hace con la herramienta `consultar_tablero`, la misma que la
    rúbrica pide como `@tool` con esquema Pydantic. Si la herramienta rechaza la
    entrada (una consulta de menos de tres letras, por ejemplo), el nodo no
    rompe el turno: pasa a la Bóveda como si no hubiera filas.
    """
    herramienta = crear_herramienta_tablero(dependencias.filas)

    def tablero(estado: EstadoSucursal) -> dict[str, Any]:
        consulta = estado.get("reformulada") or estado.get("pregunta", "")
        filas = _invocar_herramienta(herramienta, consulta)
        guardadas = [fila.como_dict() for fila in filas]
        if filas and _es_consulta_generica(consulta):
            turno = dict(estado.get("turno", {}))
            turno["letra"] = "B"
            turno["motivo"] = "tablero_generico"
            return {"filas": guardadas, "turno": turno}
        if _puede_responder_tabla(filas):
            respuesta, fuentes = _plantilla_tablero(filas)
            return {
                "filas": guardadas,
                "respuesta": respuesta,
                "fuentes": list(fuentes),
                "uso": {"uso_modelo": False, "costo_usd": 0.0},
                "avisos": [],
            }

        turno = dict(estado.get("turno", {}))
        turno["letra"] = "B"
        turno["motivo"] = "tablero_sin_filas" if not filas else "tablero_ambigua"
        return {"filas": guardadas, "turno": turno}

    return tablero


def _nodo_mixto(dependencias: DependenciasGrafo) -> Callable[[EstadoSucursal], dict[str, Any]]:
    """Crea el nodo que combina el Tablero y la Bóveda en un solo turno.

    Las filas del Tablero se convierten en fragmentos citables con la URL del
    tarifario, delante de los fragmentos de la Bóveda. La redacción no distingue
    unos de otros: recibe un solo bloque `<fragmentos>` y valida las citas de
    las dos fuentes con las reglas de siempre.
    """
    herramienta = crear_herramienta_tablero(dependencias.filas)

    def mixto(estado: EstadoSucursal) -> dict[str, Any]:
        consulta = estado.get("reformulada") or estado.get("pregunta", "")
        filas = _invocar_herramienta(herramienta, consulta)
        recuperados = list(dependencias.recuperador.buscar(consulta, k=dependencias.k))
        fragmentos = [fragmento_de_tablero(fila) for fila in filas] + recuperados
        return {
            "filas": [fila.como_dict() for fila in filas],
            "fragmentos": [asdict(fragmento) for fragmento in fragmentos],
        }

    return mixto


def _nodo_cortesia(dependencias: DependenciasGrafo) -> Callable[[EstadoSucursal], dict[str, Any]]:
    """Crea el nodo que saluda sin buscar en la Bóveda ni en el Tablero."""

    def cortesia(estado: EstadoSucursal) -> dict[str, Any]:
        texto = texto_de_cortesia(dependencias.canal)
        return {
            "respuesta": texto,
            "fuentes": [],
            "uso": {"uso_modelo": False, "costo_usd": 0.0},
            "avisos": ["cortesia"],
            "messages": [AIMessage(content=texto)],
        }

    return cortesia


def texto_de_cortesia(canal: CanalOficial | None) -> str:
    """Arma el saludo con las capacidades del asistente y el canal oficial.

    Args:
        canal: canal oficial del contexto, si la capa Contexto está disponible.

    Returns:
        Un texto breve que no cita fuentes ni cifras: no hubo búsqueda.
    """
    lineas = [
        "¡Hola! Soy el asistente informativo del Banco de Occidente.",
        "Puedo ayudarte con información pública del banco: productos, requisitos, "
        "canales, tarifas, coberturas y trámites.",
    ]
    if canal and canal.telefono:
        lineas.append(
            f"Para tu caso particular, la Línea de Servicio al Cliente es {canal.telefono}."
        )
    elif canal and canal.url:
        lineas.append(f"Para tu caso particular, consulta los canales oficiales en {canal.url}.")
    lineas.append("¿Qué te gustaría consultar?")
    return "\n".join(lineas)


def fragmento_de_tablero(fila: Fila) -> Fragmento:
    """Convierte una fila del Tablero en un fragmento citable de la Bóveda.

    La ruta mixta le entrega al modelo la cifra exacta con el mismo formato que
    un fragmento: título, sección, línea ``Fuente:`` y texto. Así la respuesta
    puede citarla con ``[n]``, `validar_citas` comprueba la URL y
    `cifras_inventadas` acepta el valor del tarifario como cifra permitida.

    Args:
        fila: fila del Tablero con su valor y su trazabilidad.

    Returns:
        El fragmento sintético listo para `formatear_fragmentos`.
    """
    concepto = fila.concepto.strip()
    texto = [f"Tarifa del Tablero: {concepto}"]
    if fila.categoria:
        texto.append(f"Categoría: {fila.categoria}")
    valor = f"Valor: {fila.valor}"
    if fila.moneda:
        valor += f" {fila.moneda}"
    if fila.periodicidad:
        valor += f" ({fila.periodicidad})"
    if fila.recargos:
        valor += f". Recargos: {fila.recargos}"
    texto.append(valor)
    if fila.vigente_desde:
        texto.append(f"Vigente desde: {fila.vigente_desde}")
    cuerpo = "\n".join(texto)
    return Fragmento(
        id=f"tablero:{fila.pagina}:{concepto}",
        texto=cuerpo,
        url=fila.fuente,
        titulo=concepto,
        seccion="tablero",
        encabezado="Tablero de tarifas",
        tipo="pdf" if fila.origen == "tarifario" else "pagina",
        tokens=max(1, len(cuerpo) // 4),
    )


def _invocar_herramienta(herramienta: Any, consulta: str) -> list[Fila]:
    """Invoca `consultar_tablero` y devuelve las filas; una entrada inválida es vacío."""
    try:
        datos = herramienta.invoke({"consulta": consulta, "limite": FILAS_PARA_DECIDIR})
    except (ValidationError, ValueError, TypeError):
        return []
    return [Fila(**fila) for fila in datos]


def _nodo_rechazo(dependencias: DependenciasGrafo) -> Callable[[EstadoSucursal], dict[str, Any]]:
    """Crea el nodo que responde con la frase fija, sin modelo."""

    def rechazo(estado: EstadoSucursal) -> dict[str, Any]:
        texto = respuesta_sin_datos(dependencias.canal)
        fuentes = [dependencias.canal.url] if dependencias.canal and dependencias.canal.url else []
        return {
            "respuesta": texto,
            "fuentes": fuentes,
            "uso": {"uso_modelo": False, "costo_usd": 0.0},
            "avisos": ["rechazo"],
            "messages": [AIMessage(content=texto)],
        }

    return rechazo


def _nodo_redactar(dependencias: DependenciasGrafo) -> Callable[[EstadoSucursal], dict[str, Any]]:
    """Crea el nodo que redacta con plantilla o con el RAG validado."""

    def redactar(estado: EstadoSucursal) -> dict[str, Any]:
        if estado.get("respuesta"):
            return {"messages": [AIMessage(content=estado["respuesta"])]}

        if dependencias.modelo is None:
            texto = respuesta_sin_datos(dependencias.canal)
            return {
                "respuesta": texto,
                "fuentes": [],
                "uso": {"uso_modelo": False, "costo_usd": 0.0},
                "avisos": ["sin_modelo"],
                "messages": [AIMessage(content=texto)],
            }

        fragmentos = tuple(Fragmento(**datos) for datos in estado.get("fragmentos", []))
        contexto = ContextoRag(fragmentos, dependencias.canal)
        pregunta = estado.get("reformulada") or estado.get("pregunta", "")
        try:
            respuesta = contexto.responder(dependencias.modelo, dependencias.prompt, pregunta)
        except Exception:
            texto = respuesta_sin_datos(dependencias.canal)
            return {
                "respuesta": texto,
                "fuentes": [],
                "uso": {"uso_modelo": False, "costo_usd": 0.0},
                "avisos": ["error_modelo"],
                "messages": [AIMessage(content=texto)],
            }

        uso = dict(respuesta.metricas)
        uso["uso_modelo"] = not respuesta.sin_datos
        usos = list(estado.get("usos") or [])
        if respuesta.metricas:
            usos.append(respuesta.metricas)
        return {
            "respuesta": respuesta.texto,
            "fuentes": list(respuesta.fuentes),
            "uso": uso,
            "usos": usos,
            "avisos": list(respuesta.avisos),
            "messages": [AIMessage(content=respuesta.texto)],
        }

    return redactar


def _ruta_digiturno(estado: EstadoSucursal) -> str:
    """Devuelve el destino del grafo: letra del turno o motivo especial.

    La cortesía y la pregunta mixta no cambian la letra del contrato (siguen
    siendo `B` y `T`): se reconocen por el motivo y toman un nodo propio.
    """
    turno = estado.get("turno", {})
    motivo = str(turno.get("motivo", ""))
    if motivo == "perfil" or motivo.startswith("perfil:"):
        return "perfil"
    if motivo.startswith("cortesia"):
        return "cortesia"
    if motivo.startswith("mixta"):
        return "mixto"
    letra = str(turno.get("letra", "B"))
    return letra if letra in {"B", "T", "X"} else "B"


def _ruta_despues_de_perfil(estado: EstadoSucursal) -> str:
    """Decide si el perfil ya respondió o si sigue la pregunta residual."""
    if estado.get("respuesta"):
        return "fin"
    turno = estado.get("turno", {})
    motivo = str(turno.get("motivo_residual", ""))
    if motivo.startswith("cortesia"):
        return "cortesia"
    if motivo.startswith("mixta"):
        return "mixto"
    letra = str(turno.get("letra", "B"))
    return {"X": "rechazo", "T": "tablero", "B": "boveda"}.get(letra, "boveda")


def _ruta_boveda(estado: EstadoSucursal) -> str:
    """Decide entre redactar o rechazar según los fragmentos."""
    return "redactar" if estado.get("fragmentos") else "rechazo"


def _ruta_tablero(estado: EstadoSucursal) -> str:
    """Decide entre la plantilla del Tablero o seguir a la Bóveda."""
    return "redactar" if estado.get("respuesta") else "boveda"


#: Productos de tarjeta que hacen específica una pregunta de cuota.
_PRODUCTOS_TARJETA = (
    "credencial",
    "gold",
    "black",
    "clasica",
    "joven",
    "business",
    "viajera",
)


def tablero_responde_sin_modelo(filas: Sequence[Fila], consulta: str) -> bool:
    """Indica si el Tablero puede responder la consulta con plantilla.

    Replica la decisión del nodo `tablero` para que la API estime el gasto y el
    tope con las mismas reglas: usa la misma herramienta, con el mismo límite de
    filas, y exige filas específicas, una a tres o del mismo concepto, y que no
    sea una cuota genérica de «las tarjetas de crédito».
    """
    encontradas = filas_de_consulta(filas, consulta, limite=FILAS_PARA_DECIDIR)
    if not encontradas or _es_consulta_generica(consulta):
        return False
    return _puede_responder_tabla(encontradas)


def _es_consulta_generica(consulta: str) -> bool:
    """Detecta una cuota pedida para «las tarjetas de crédito» en general.

    Si el cliente pregunta por la cuota de manejo de la categoría completa, no
    hay una fila única que responder: el Tablero debe pasar a la Bóveda para que
    pregunte por la tarjeta concreta. Una cobertura de viaje sí puede listar las
    dos franquicias, por eso la regla solo aplica a cuota, costo o manejo.
    """
    texto = normalizar(consulta)
    if re.search(r"\btarjetas\s+de\s+credito\b", texto) is None:
        return False
    if any(producto in texto for producto in _PRODUCTOS_TARJETA):
        return False
    return any(palabra in texto for palabra in ("cuota", "manejo", "cuesta", "vale"))


def _puede_responder_tabla(filas: Sequence[Fila]) -> bool:
    """Decide si las filas se pueden responder con la plantilla del Tablero.

    Una a tres filas siempre se responden. Con más, solo si todas comparten el
    mismo concepto base (por ejemplo, los topes de la misma asistencia para Visa
    y Mastercard) y no superan ``MAX_FILAS_TABLERO``; si hay conceptos distintos,
    la consulta es ambigua y debe responder la Bóveda.
    """
    if not filas:
        return False
    if len(filas) <= 3:
        return True
    if len(filas) > MAX_FILAS_TABLERO:
        return False
    bases = {concepto_sin_franquicia(fila.concepto) for fila in filas}
    return len(bases) == 1


def _plantilla_tablero(filas: Sequence[Fila]) -> tuple[str, tuple[str, ...]]:
    """Responde con las filas del Tablero sin llamar al modelo."""
    lineas = ["Según el Tablero de tarifas:"]
    for fila in filas:
        partes = [f"- {fila.concepto}: {fila.valor}"]
        if fila.moneda:
            partes[-1] += f" {fila.moneda}"
        if fila.periodicidad:
            partes[-1] += f" ({fila.periodicidad})"
        if fila.vigente_desde:
            partes[-1] += f", vigente desde {fila.vigente_desde}"
        lineas.append(partes[-1])
    fuentes = tuple(dict.fromkeys(fila.fuente for fila in filas))
    lineas.append("")
    lineas.append("Fuentes:")
    lineas.extend(f"- {fuente}" for fuente in fuentes)
    return "\n".join(lineas), fuentes
