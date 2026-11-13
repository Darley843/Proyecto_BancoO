"""Streaming de `POST /api/preguntar/stream`: avance por etapas con SSE.

La Ventanilla ve el turno avanzar mientras el grafo trabaja: un evento cuando
cada nodo empieza (`en_curso`) y otro cuando termina (`hecho`), y al final el
mismo cuerpo que devuelve `POST /api/preguntar`.

Cómo se logra sin tocar `grafo.py` ni `preguntar.py`:

1. `GrafoConAvance` envuelve el grafo compilado. Si nadie escucha, su
   `invoke` llama al `invoke` real, así que la ruta clásica sigue igual.
2. Cuando hay un oyente en `_OYENTE` (un `ContextVar`), `invoke` usa
   `grafo.stream(stream_mode=["tasks", "values"])`: los eventos `tasks` se
   traducen a etapas y el último `values` es el mismo estado final que
   devolvería `invoke`.
3. `TransmisionTurno` ejecuta el servicio en un hilo aparte y pasa las etapas
   por una cola para que FastAPI las envíe como eventos del servidor (SSE).

Los eventos nunca llevan la pregunta, la respuesta parcial ni el `thread_id`:
solo el nombre del nodo, un texto corto y datos del ruteo (letra, ruta, motivo
y conteos). La respuesta solo sale en el evento `final`, ya validada, para no
publicar texto que el blindaje del RAG todavía no revisó.
"""

from __future__ import annotations

import json
import logging
import queue
import threading
from collections.abc import Callable, Iterator, Mapping
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any, Literal

from .preguntar import ErrorSucursal, PiezasGrafo, ruta_de_letra

#: Logger del streaming; igual que el servicio, nunca recibe la pregunta.
LOGGER = logging.getLogger(__name__)

#: Modos del stream de LangGraph: inicio y fin de cada nodo, y el estado.
MODOS_STREAM: list[str] = ["tasks", "values"]

#: Nodo del grafo → (etapa pública, texto mientras el nodo trabaja).
ETAPAS: dict[str, tuple[str, str]] = {
    "reformular": ("reformulando", "Revisando si la pregunta depende del historial…"),
    "digiturno": ("router", "El Digiturno decide la ruta del turno…"),
    "boveda": ("buscando", "Buscando fragmentos en la Bóveda…"),
    "tablero": ("buscando", "Consultando el Tablero de tarifas…"),
    "rechazo": ("redactando", "Preparando la respuesta fija…"),
    "redactar": ("redactando", "Redactando y validando la respuesta con sus citas…"),
}

#: Nombres legibles de las rutas para los textos de las etapas.
NOMBRES_RUTA: dict[str, str] = {
    "boveda": "Bóveda",
    "tablero": "Tablero",
    "rechazo": "Rechazo",
}

#: Mensaje genérico para un fallo inesperado; el detalle queda solo en el log.
MENSAJE_ERROR_INTERNO = (
    "La Sucursal tuvo un error inesperado al atender el turno. Intenta de nuevo."
)

#: Tipos de mensaje que viajan por la cola entre el hilo de trabajo y la API.
TipoMensaje = Literal["etapa", "final", "error"]

#: Quién recibe las etapas del turno que corre en el hilo actual.
_OYENTE: ContextVar[Callable[[dict[str, Any]], None] | None] = ContextVar(
    "oyente_etapas", default=None
)


@dataclass(frozen=True, slots=True)
class MensajeTurno:
    """Un mensaje de la transmisión: una etapa, el turno final o un error.

    Attributes:
        tipo: `etapa`, `final` o `error`; es también el nombre del evento SSE.
        datos: cuerpo JSON del evento.
        estado_http: código HTTP del error; solo se usa cuando `tipo` es `error`.
    """

    tipo: TipoMensaje
    datos: dict[str, Any] = field(default_factory=dict)
    estado_http: int = 200

    def como_sse(self) -> str:
        """Devuelve el mensaje en formato de evento del servidor (SSE).

        Returns:
            Texto `event: <tipo>` + `data: <json>` terminado en línea en blanco.
        """
        cuerpo = json.dumps(self.datos, ensure_ascii=False, separators=(",", ":"))
        return f"event: {self.tipo}\ndata: {cuerpo}\n\n"


class GrafoConAvance:
    """Envoltura del grafo compilado que avisa el avance de cada nodo.

    Delegar todo lo demás (`get_state`, `update_state`…) mantiene intacto el
    comportamiento de la memoria y de la caché del servicio.
    """

    def __init__(self, grafo: Any) -> None:
        """Guarda el grafo real que se va a envolver.

        Args:
            grafo: aplicación compilada de LangGraph.
        """
        self._grafo = grafo

    @property
    def grafo_real(self) -> Any:
        """Devuelve el grafo compilado sin envoltura."""
        return self._grafo

    def __getattr__(self, nombre: str) -> Any:
        """Delega en el grafo real cualquier atributo que no se redefine aquí."""
        return getattr(self._grafo, nombre)

    def invoke(self, entrada: Any, config: Any = None, **opciones: Any) -> Any:
        """Ejecuta el grafo; si hay oyente, avisa cada etapa mientras avanza.

        Args:
            entrada: estado inicial del turno.
            config: configuración con el `thread_id`.
            **opciones: otras opciones de LangGraph, se pasan sin cambios.

        Returns:
            El estado final del turno, igual al que devolvería `invoke`.
        """
        oyente = _OYENTE.get()
        if oyente is None:
            return self._grafo.invoke(entrada, config=config, **opciones)
        final: Any = None
        for modo, dato in self._grafo.stream(
            entrada, config=config, stream_mode=MODOS_STREAM, **opciones
        ):
            if modo == "values":
                final = dato
            elif modo == "tasks" and isinstance(dato, Mapping):
                evento = evento_de_tarea(dato)
                if evento is not None:
                    oyente(evento)
        return final if final is not None else {}


def con_avance(piezas: PiezasGrafo) -> PiezasGrafo:
    """Devuelve las mismas piezas con el grafo envuelto en `GrafoConAvance`.

    Args:
        piezas: dependencias y grafo construidos por el servicio.

    Returns:
        Piezas nuevas que comparten dependencias y memoria con las originales.
    """
    if isinstance(piezas.grafo, GrafoConAvance):
        return piezas
    return PiezasGrafo(dependencias=piezas.dependencias, grafo=GrafoConAvance(piezas.grafo))


def evento_de_tarea(tarea: Mapping[str, Any]) -> dict[str, Any] | None:
    """Traduce un evento `tasks` de LangGraph a una etapa de la Ventanilla.

    Args:
        tarea: evento de inicio (`input`) o de fin (`result`) de un nodo.

    Returns:
        `{nodo, etapa, estado, texto, detalle}` o None si el nodo no es público
        o si terminó con error (el error se propaga por `invoke`).
    """
    nodo = str(tarea.get("name", ""))
    if nodo not in ETAPAS:
        return None
    etapa, texto_en_curso = ETAPAS[nodo]
    if "input" in tarea:
        return {
            "nodo": nodo,
            "etapa": etapa,
            "estado": "en_curso",
            "texto": texto_en_curso,
            "detalle": {},
        }
    if tarea.get("error") is not None:
        return None
    resultado = tarea.get("result")
    texto, detalle = resumir_resultado(nodo, resultado if isinstance(resultado, Mapping) else {})
    return {
        "nodo": nodo,
        "etapa": etapa,
        "estado": "hecho",
        "texto": texto,
        "detalle": detalle,
    }


def resumir_resultado(nodo: str, resultado: Mapping[str, Any]) -> tuple[str, dict[str, Any]]:
    """Resume en una frase lo que hizo un nodo, sin copiar texto del cliente.

    Args:
        nodo: nombre del nodo del grafo.
        resultado: actualización de estado que devolvió el nodo.

    Returns:
        El texto de la etapa terminada y un detalle con datos del ruteo.
    """
    if nodo == "reformular":
        if resultado.get("usos"):
            return "Pregunta de seguimiento: se reformuló con el historial.", {"reformulo": True}
        return "Pregunta autónoma: no hizo falta reformular.", {"reformulo": False}
    if nodo == "digiturno":
        return _resumen_digiturno(resultado)
    if nodo == "boveda":
        total = len(resultado.get("fragmentos") or [])
        if total == 0:
            return "La Bóveda no encontró fragmentos: no se inventa respuesta.", {"fragmentos": 0}
        texto = f"La Bóveda recuperó {_contar(total, 'fragmento', 'fragmentos')} con su fuente."
        return texto, {"fragmentos": total}
    if nodo == "tablero":
        total = len(resultado.get("filas") or [])
        if resultado.get("respuesta"):
            texto = f"El Tablero respondió con {_contar(total, 'fila', 'filas')}, sin modelo."
            return texto, {"filas": total, "plantilla": True}
        return "El Tablero no basta: el turno pasa a la Bóveda.", {
            "filas": total,
            "plantilla": False,
        }
    if nodo == "rechazo":
        return "Respuesta fija, sin modelo y sin búsqueda.", {}
    avisos = [str(aviso) for aviso in resultado.get("avisos") or []]
    return "Respuesta lista y validada.", {"avisos": avisos}


def _contar(total: int, singular: str, plural: str) -> str:
    """Escribe una cantidad con su sustantivo en singular o plural."""
    return f"{total} {singular if total == 1 else plural}"


def _resumen_digiturno(resultado: Mapping[str, Any]) -> tuple[str, dict[str, Any]]:
    """Resume la decisión del Digiturno: letra, número, ruta y motivo."""
    turno = resultado.get("turno")
    datos = turno if isinstance(turno, Mapping) else {}
    letra = str(datos.get("letra", "B"))
    numero = datos.get("numero", "")
    motivo = str(datos.get("motivo", ""))
    ruta = ruta_de_letra(letra)
    nombre = NOMBRES_RUTA.get(ruta, ruta)
    texto = f"Turno {letra}-{numero}: ruta {nombre}"
    if motivo:
        texto += f" (motivo: {motivo})"
    return f"{texto}.", {"letra": letra, "ruta": ruta, "motivo": motivo}


class TransmisionTurno:
    """Ejecuta un turno en un hilo aparte y entrega sus mensajes en orden."""

    def __init__(self, atender: Callable[[], dict[str, Any]]) -> None:
        """Prepara la cola y el hilo; no arranca hasta llamar `iniciar`.

        Args:
            atender: función que atiende el turno y devuelve el cuerpo final del
                contrato; las etapas se avisan mientras corre.
        """
        self._atender = atender
        self._cola: queue.Queue[MensajeTurno | None] = queue.Queue()
        self._hilo = threading.Thread(target=self._trabajar, name="turno-stream", daemon=True)

    def iniciar(self) -> TransmisionTurno:
        """Arranca el hilo de trabajo y devuelve la misma transmisión."""
        self._hilo.start()
        return self

    def siguiente(self) -> MensajeTurno | None:
        """Espera el siguiente mensaje; None significa que la transmisión terminó."""
        return self._cola.get()

    def eventos_sse(self, primero: MensajeTurno | None = None) -> Iterator[str]:
        """Genera los eventos SSE hasta el mensaje final o el error.

        Args:
            primero: mensaje que ya se leyó para decidir el estado HTTP; se
                envía antes que los demás.

        Yields:
            Cada mensaje en formato SSE.
        """
        mensaje = primero if primero is not None else self.siguiente()
        while mensaje is not None:
            yield mensaje.como_sse()
            if mensaje.tipo != "etapa":
                return
            mensaje = self.siguiente()

    def _avisar(self, etapa: dict[str, Any]) -> None:
        """Pone una etapa en la cola; lo llama `GrafoConAvance` en este hilo."""
        self._cola.put(MensajeTurno("etapa", etapa))

    def _trabajar(self) -> None:
        """Atiende el turno con el oyente activo y deja el resultado en la cola."""
        token = _OYENTE.set(self._avisar)
        try:
            final = self._atender()
            self._cola.put(MensajeTurno("final", final))
        except ErrorSucursal as error:
            self._cola.put(error_como_mensaje(error))
        except Exception as error:
            LOGGER.error("evento=stream_fallido codigo=%s", type(error).__name__)
            self._cola.put(
                MensajeTurno(
                    "error",
                    {"error": {"codigo": "error_interno", "mensaje": MENSAJE_ERROR_INTERNO}},
                    estado_http=500,
                )
            )
        finally:
            _OYENTE.reset(token)
            self._cola.put(None)


def error_como_mensaje(error: ErrorSucursal) -> MensajeTurno:
    """Convierte un `ErrorSucursal` en el mensaje de error del contrato.

    Args:
        error: error con estado HTTP, código y mensaje.

    Returns:
        Un mensaje `error` con `{"error": {"codigo", "mensaje"}}`.
    """
    return MensajeTurno(
        "error",
        {"error": {"codigo": error.codigo, "mensaje": error.mensaje}},
        estado_http=error.estado_http,
    )
