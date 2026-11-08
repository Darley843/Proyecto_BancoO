"""Grafo de la Sucursal: digiturno, Bóveda, Tablero y redacción con memoria.

El estado viaja entre nodos como datos serializables (diccionarios) para que el
checkpointer SQLite no dependa de tipos propios. La memoria se aísla por
`thread_id`, el historial se recorta antes de cada llamada al modelo y la
pregunta con datos personales se rechaza antes de entrar al grafo.
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
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages

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
from ..tablero.consultas import (
    concepto_sin_franquicia,
    filas_para_plantilla,
)
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
#: Filas que la plantilla del Tablero puede listar sin volverse una tabla enorme.
MAX_FILAS_TABLERO = 10
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
    respuesta: str
    fuentes: list[str]
    uso: dict[str, Any]
    usos: list[dict[str, Any]]
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
            "usos": [],
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
            "usos": [],
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
        usos = list(estado.get("usos") or [])
        try:
            salida = dependencias.modelo.invoke(mensajes, max_tokens=MAX_TOKENS_REFORMULAR)
            texto = texto_de_contenido(salida.content).strip()
        except Exception:
            return {"reformulada": pregunta}
        usos.append(extraer_metricas(salida))
        return {"reformulada": texto or pregunta, "usos": usos}

    return reformular


def _nodo_digiturno(dependencias: DependenciasGrafo) -> Callable[[EstadoSucursal], dict[str, Any]]:
    """Crea el nodo que asigna el turno con el digiturno."""

    def digiturno(estado: EstadoSucursal) -> dict[str, Any]:
        consulta = estado.get("reformulada") or estado.get("pregunta", "")
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
        filas = filas_para_plantilla(dependencias.filas, consulta)
        guardadas = [asdict(fila) for fila in filas]
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
    tope con las mismas reglas: filas específicas, una a tres o del mismo
    concepto, y que no sea una cuota genérica de «las tarjetas de crédito».
    """
    encontradas = filas_para_plantilla(filas, consulta)
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
