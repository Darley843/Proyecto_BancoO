"""Grafo de la Sucursal: digiturno, Bóveda, Tablero y redacción con memoria.

El estado viaja entre nodos como datos serializables (diccionarios) para que el
checkpointer SQLite no dependa de tipos propios. La memoria se aísla por
`thread_id`, el historial se recorta antes de cada llamada al modelo y la
pregunta con datos personales se rechaza antes de entrar al grafo.
"""

from __future__ import annotations

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
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages

from ..asistente.contexto_prompt import CanalOficial
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
from ..tablero.consultas import buscar_filas
from ..tablero.tipos import Fila
from ..texto import normalizar
from .digiturno import (
    Clasificador,
    ConfiguracionDigiturno,
    ContadorTurnos,
    clasificar,
)

#: Tokens de historial que se conservan antes de llamar al modelo.
HISTORIAL_MAX_TOKENS = 1200
#: Instrucción para convertir un seguimiento en pregunta autónoma.
INSTRUCCION_REFORMULAR = (
    "Reescribe la última pregunta como una pregunta autónoma en español, usando "
    "el historial solo para resolver a qué se refiere. No respondas la pregunta, "
    "no añadas datos y devuelve únicamente la pregunta reformulada."
)
#: Prefijos que delatan un seguimiento conversacional.
PREFIJOS_SEGUIMIENTO = ("¿y ", "y ", "cuanto", "cual", "como")


class EstadoSucursal(TypedDict, total=False):
    """Estado que comparten los nodos del grafo."""

    messages: Annotated[list[BaseMessage], add_messages]
    pregunta: str
    reformulada: str
    turno: dict[str, Any]
    filas: list[dict[str, str]]
    fragmentos: list[dict[str, Any]]
    respuesta: str
    fuentes: list[str]
    uso: dict[str, Any]
    avisos: list[str]


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

    Args:
        pregunta: texto del cliente.

    Returns:
        True si empieza con un prefijo de seguimiento o tiene menos de seis palabras.
    """
    normalizada = normalizar(pregunta).strip()
    if normalizada.startswith(PREFIJOS_SEGUIMIENTO):
        return True
    return len(normalizada.split()) < 6


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
) -> Any:
    """Compila el grafo con memoria SQLite en `ruta_memoria`.

    Args:
        dependencias: recuperador, modelo, filas del Tablero y canal.
        ruta_memoria: archivo SQLite del checkpointer.

    Returns:
        La aplicación compilada de LangGraph.
    """
    ruta_memoria.parent.mkdir(parents=True, exist_ok=True)
    conexion = sqlite3.connect(str(ruta_memoria), check_same_thread=False)
    checkpointer = SqliteSaver(conexion)

    # `ty` no reconoce el TypedDict con `add_messages` como StateLike; el cast
    # mantiene el tipado en el resto del módulo sin relajar el estado en runtime.
    constructor = StateGraph(cast(Any, EstadoSucursal))
    constructor.add_node("reformular", cast(Any, _nodo_reformular(dependencias)))
    constructor.add_node("digiturno", cast(Any, _nodo_digiturno(dependencias)))
    constructor.add_node("boveda", cast(Any, _nodo_boveda(dependencias)))
    constructor.add_node("tablero", cast(Any, _nodo_tablero(dependencias)))
    constructor.add_node("rechazo", cast(Any, _nodo_rechazo(dependencias)))
    constructor.add_node("redactar", cast(Any, _nodo_redactar(dependencias)))

    constructor.add_edge(START, "reformular")
    constructor.add_edge("reformular", "digiturno")
    constructor.add_conditional_edges(
        "digiturno",
        _ruta_digiturno,
        {"X": "rechazo", "T": "tablero", "B": "boveda"},
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
    constructor.add_edge("rechazo", END)
    constructor.add_edge("redactar", END)

    return constructor.compile(checkpointer=checkpointer)


def responder_turno(
    grafo: Any,
    dependencias: DependenciasGrafo,
    pregunta: str,
    thread_id: str,
) -> dict[str, Any]:
    """Ejecuta un turno, rechazando la PII antes de entrar a la memoria.

    Args:
        grafo: aplicación compilada con `crear_grafo`.
        dependencias: mismas dependencias usadas al compilar.
        pregunta: texto del cliente.
        thread_id: identificador de la conversación.

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
            "avisos": ["pii_bloqueada"],
            "messages": [],
        }

    return grafo.invoke(
        {
            "messages": [HumanMessage(content=limpia)],
            "pregunta": limpia,
            "reformulada": "",
            "turno": {},
            "filas": [],
            "fragmentos": [],
            "respuesta": "",
            "fuentes": [],
            "uso": {},
            "avisos": [],
        },
        config={"configurable": {"thread_id": thread_id}},
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
        historial = list(estado.get("messages", []))[:-1]
        if not historial or not es_seguimiento(pregunta) or dependencias.modelo is None:
            return {"reformulada": pregunta}

        previos = recortar_historial(historial, dependencias.historial_max_tokens)
        mensajes = (
            [SystemMessage(content=INSTRUCCION_REFORMULAR)]
            + previos
            + [HumanMessage(content=pregunta)]
        )
        try:
            salida = dependencias.modelo.invoke(mensajes)
            texto = texto_de_contenido(salida.content).strip()
        except Exception:
            return {"reformulada": pregunta}
        return {"reformulada": texto or pregunta}

    return reformular


def _nodo_digiturno(dependencias: DependenciasGrafo) -> Callable[[EstadoSucursal], dict[str, Any]]:
    """Crea el nodo que asigna el turno con el digiturno."""

    def digiturno(estado: EstadoSucursal) -> dict[str, Any]:
        consulta = estado.get("reformulada") or estado.get("pregunta", "")
        turno = clasificar(
            consulta,
            configuracion=dependencias.configuracion_digiturno,
            permitidos=dependencias.permitidos,
            clasificador=dependencias.clasificador,
            contador=dependencias.contador,
        )
        return {"turno": asdict(turno)}

    return digiturno


def _nodo_boveda(dependencias: DependenciasGrafo) -> Callable[[EstadoSucursal], dict[str, Any]]:
    """Crea el nodo que recupera fragmentos de la Bóveda."""

    def boveda(estado: EstadoSucursal) -> dict[str, Any]:
        consulta = estado.get("reformulada") or estado.get("pregunta", "")
        fragmentos = dependencias.recuperador.buscar(consulta, k=dependencias.k)
        return {"fragmentos": [asdict(fragmento) for fragmento in fragmentos]}

    return boveda


def _nodo_tablero(dependencias: DependenciasGrafo) -> Callable[[EstadoSucursal], dict[str, Any]]:
    """Crea el nodo que responde con filas del Tablero o devuelve la ruta a B."""

    def tablero(estado: EstadoSucursal) -> dict[str, Any]:
        consulta = estado.get("reformulada") or estado.get("pregunta", "")
        filas = buscar_filas(dependencias.filas, consulta)
        guardadas = [asdict(fila) for fila in filas]
        if 1 <= len(filas) <= 3:
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
        return {
            "respuesta": respuesta.texto,
            "fuentes": list(respuesta.fuentes),
            "uso": uso,
            "avisos": list(respuesta.avisos),
            "messages": [AIMessage(content=respuesta.texto)],
        }

    return redactar


def _ruta_digiturno(estado: EstadoSucursal) -> str:
    """Devuelve la letra del turno como ruta del grafo."""
    turno = estado.get("turno", {})
    letra = str(turno.get("letra", "B"))
    return letra if letra in {"B", "T", "X"} else "B"


def _ruta_boveda(estado: EstadoSucursal) -> str:
    """Decide entre redactar o rechazar según los fragmentos."""
    return "redactar" if estado.get("fragmentos") else "rechazo"


def _ruta_tablero(estado: EstadoSucursal) -> str:
    """Decide entre la plantilla del Tablero o seguir a la Bóveda."""
    return "redactar" if estado.get("respuesta") else "boveda"


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
