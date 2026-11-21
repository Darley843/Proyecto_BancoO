"""HITL con el asesor: suspensión, botones y reanudación.

La entrevista del diagnóstico es determinística y no vive en un grafo: la tarea
3.10 se cerró con la máquina de estados de `canal/entrevista.py`. El HITL sí
necesita un grafo mínimo, porque `interrupt()` y `Command(resume=...)` solo
existen dentro de un grafo con checkpointer. Este módulo compila dos nodos
—``ofrecer`` y ``decidir``— y guarda el estado en el mismo
``whatsapp.sqlite`` del canal, con un hilo por persona.

Flujo:

1. ``suspender`` interrumpe el turno con el caso y el hilo queda esperando. No
   se escribe nada en ``casos`` todavía.
2. ``reanudar`` con ``contactar`` abre el caso; con ``descartar`` no crea nada.
   Una segunda reanudación no cambia el estado ni duplica la fila.
3. ``contactar_directo`` abre el caso sin suspender, para quien pide asesor.

El checkpoint no guarda el resultado del diagnóstico: solo el motivo y el
semáforo. La tarjeta se reconstruye desde ``resultados_diagnostico``, que vence
a las 24 horas, y el hilo se borra en cuanto se reanuda. Las pruebas viven en
``test/test_canal_hitl.py``.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, TypedDict, cast

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from .almacen import abrir_caso, inicializar_almacen

#: Motivo del caso cuando el semáforo sale rojo.
MOTIVO_ROJO: str = "semaforo_rojo"
#: Motivo del caso cuando la persona pide un asesor.
MOTIVO_ASESOR: str = "asesor_solicitado"
#: Acciones que acepta la reanudación.
ACCIONES_HITL: frozenset[str] = frozenset({"contactar", "descartar"})
#: Sufijo del hilo del HITL; el prefijo `wa:` lo comparte con la Sucursal.
PREFIJO_HILO: str = "wa:"
SUFIJO_HILO: str = ":hitl"

AccionHitl = Literal["contactar", "descartar"]


class EstadoHitl(TypedDict, total=False):
    """Estado serializable del HITL.

    Attributes:
        usuario_id: huella HMAC del número, nunca el número.
        motivo: causa del caso (`semaforo_rojo` o `asesor_solicitado`).
        semaforo: color del diagnóstico, o `pendiente` si no hay cálculo.
        accion: `contactar` o `descartar` después de la reanudación.
        caso_id: caso abierto, o vacío si se descartó.
    """

    usuario_id: str
    motivo: str
    semaforo: str
    accion: str
    caso_id: str


@dataclass(frozen=True, slots=True)
class Decision:
    """Lo que decidió la persona al reanudar el HITL.

    Attributes:
        accion: `contactar` o `descartar`.
        caso_id: id del caso abierto; vacío al descartar.
    """

    accion: AccionHitl
    caso_id: str = ""


def config_hilo(usuario_id: str) -> dict[str, Any]:
    """Devuelve la configuración del checkpointer para una persona.

    Args:
        usuario_id: huella HMAC del número.

    Returns:
        El diccionario que LangGraph espera en ``config``.
    """
    return {"configurable": {"thread_id": f"{PREFIJO_HILO}{usuario_id}{SUFIJO_HILO}"}}


@dataclass
class HitlAsesor:
    """Suspende el turno y crea o descarta el caso de asesor.

    Attributes:
        ruta: base `whatsapp.sqlite` del canal, que también guarda los casos.
    """

    ruta: Path
    _grafo: Any = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        """Crea las tablas del canal y compila el grafo con su checkpointer."""
        inicializar_almacen(self.ruta)
        self.ruta.parent.mkdir(parents=True, exist_ok=True)
        conexion = sqlite3.connect(str(self.ruta), check_same_thread=False)
        checkpointer = SqliteSaver(conexion)

        constructor = StateGraph(cast(Any, EstadoHitl))
        constructor.add_node("ofrecer", cast(Any, self._ofrecer))
        constructor.add_node("decidir", cast(Any, self._decidir))
        constructor.add_edge(START, "ofrecer")
        constructor.add_edge("ofrecer", "decidir")
        constructor.add_edge("decidir", END)
        self._grafo = constructor.compile(checkpointer=checkpointer)

    def suspender(self, usuario_id: str, *, motivo: str, semaforo: str) -> None:
        """Interrumpe el turno con el caso y deja el hilo esperando.

        Args:
            usuario_id: huella HMAC del número.
            motivo: causa del caso.
            semaforo: color del diagnóstico, o `pendiente`.
        """
        self._grafo.invoke(
            {
                "usuario_id": usuario_id,
                "motivo": motivo,
                "semaforo": semaforo,
                "accion": "",
                "caso_id": "",
            },
            config=config_hilo(usuario_id),
        )

    def suspendido(self, usuario_id: str) -> bool:
        """Dice si el hilo está esperando la decisión de la persona.

        Args:
            usuario_id: huella HMAC del número.

        Returns:
            ``True`` si hay una interrupción abierta.
        """
        estado = self._grafo.get_state(config_hilo(usuario_id))
        tareas = getattr(estado, "tasks", ()) or ()
        return any(getattr(tarea, "interrupts", ()) for tarea in tareas)

    def reanudar(self, usuario_id: str, accion: AccionHitl) -> Decision | None:
        """Reanuda el hilo con la decisión y borra el checkpoint.

        Args:
            usuario_id: huella HMAC del número.
            accion: `contactar` o `descartar`.

        Returns:
            La decisión aplicada, o ``None`` si el hilo no estaba suspendido.
        """
        if accion not in ACCIONES_HITL or not self.suspendido(usuario_id):
            return None
        estado = self._grafo.invoke(
            Command(resume={"accion": accion}),
            config=config_hilo(usuario_id),
        )
        self.limpiar(usuario_id)
        return Decision(accion=accion, caso_id=str(estado.get("caso_id", "")))

    def contactar_directo(self, usuario_id: str, *, motivo: str = MOTIVO_ASESOR) -> str:
        """Abre el caso sin suspender, para quien ya pidió un asesor.

        Args:
            usuario_id: huella HMAC del número.
            motivo: causa del caso.

        Returns:
            El id del caso abierto.
        """
        return abrir_caso(self.ruta, usuario_id, motivo, semaforo="pendiente")

    def limpiar(self, usuario_id: str) -> None:
        """Borra el checkpoint de la persona, si el saver lo permite.

        Args:
            usuario_id: huella HMAC del número.
        """
        borrar = getattr(self._grafo.checkpointer, "delete_thread", None)
        if borrar is not None:
            borrar(config_hilo(usuario_id)["configurable"]["thread_id"])

    def _ofrecer(self, estado: EstadoHitl) -> dict[str, Any]:
        """Suspende el turno y devuelve la acción elegida al reanudar."""
        decision = interrupt(
            {
                "tipo": "asesor",
                "caso": {
                    "motivo": estado.get("motivo", ""),
                    "semaforo": estado.get("semaforo", "pendiente"),
                },
            }
        )
        return {"accion": _accion(decision)}

    def _decidir(self, estado: EstadoHitl) -> dict[str, Any]:
        """Crea o cierra el caso según la acción elegida."""
        if estado.get("accion") == "descartar":
            return {"caso_id": ""}
        id_caso = abrir_caso(
            self.ruta,
            str(estado.get("usuario_id", "")),
            str(estado.get("motivo", MOTIVO_ROJO)),
            semaforo=str(estado.get("semaforo", "pendiente")),
        )
        return {"caso_id": id_caso}


def _accion(decision: Any) -> str:
    """Normaliza la reanudación a ``contactar`` o ``descartar``.

    Args:
        decision: valor que devolvió `interrupt()` al reanudar.

    Returns:
        La acción pedida.

    Raises:
        ValueError: si la reanudación no trae una acción válida.
    """
    crudo = decision.get("accion", "") if isinstance(decision, dict) else decision
    accion = str(crudo or "").strip().lower()
    if accion not in ACCIONES_HITL:
        raise ValueError("la reanudación del HITL debe ser «contactar» o «descartar»")
    return accion
