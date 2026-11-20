"""Cola de un solo trabajador para los mensajes del canal.

Meta exige respuesta 200 en segundos; el turno se procesa después. Un único
trabajador conserva el orden por usuario y evita que dos turnos del mismo hilo
compitan por el ``checkpointer``. Si la cola está llena, el mensaje se descarta y
se registra el evento, pero el webhook sigue respondiendo 200 para que Meta no
reintente en bucle. Las pruebas viven en ``test/test_canal_cola.py``.
"""

from __future__ import annotations

import logging
import queue
import threading
from collections.abc import Callable
from dataclasses import dataclass, field

from .contratos import MensajeEntrante

logger = logging.getLogger(__name__)

#: Elemento que marca el final del trabajador.
_PARADA = object()


@dataclass
class ColaMensajes:
    """Cola acotada con un hilo trabajador."""

    maximo: int = 100
    _cola: queue.Queue[object] = field(init=False, repr=False)
    _hilo: threading.Thread | None = field(init=False, default=None, repr=False)

    def __post_init__(self) -> None:
        """Crea la cola con el tamaño máximo indicado."""
        self._cola = queue.Queue(maxsize=self.maximo)

    def iniciar(self, procesar: Callable[[MensajeEntrante], None]) -> None:
        """Arranca el trabajador si no estaba corriendo.

        Args:
            procesar: función que atiende cada mensaje.
        """
        if self._hilo is not None:
            return
        self._hilo = threading.Thread(
            target=self._trabajar,
            args=(procesar,),
            name="canal-whatsapp",
            daemon=True,
        )
        self._hilo.start()

    def encolar(self, mensaje: MensajeEntrante) -> bool:
        """Encola un mensaje sin bloquear.

        Args:
            mensaje: mensaje ya registrado y deduplicado.

        Returns:
            ``True`` si entró; ``False`` si la cola estaba llena.
        """
        try:
            self._cola.put_nowait(mensaje)
            return True
        except queue.Full:
            logger.warning("cola del canal llena; mensaje descartado")
            return False

    def detener(self, timeout: float = 5.0) -> None:
        """Pide al trabajador que termine y espera su cierre.

        Args:
            timeout: segundos máximos de espera.
        """
        if self._hilo is None:
            return
        try:
            self._cola.put(_PARADA, timeout=timeout)
        except queue.Full:
            logger.warning("no se pudo encolar la parada de la cola del canal")
        self._hilo.join(timeout)
        self._hilo = None

    def _trabajar(self, procesar: Callable[[MensajeEntrante], None]) -> None:
        """Atiende la cola en orden hasta recibir la señal de parada."""
        while True:
            elemento = self._cola.get()
            try:
                if elemento is _PARADA:
                    return
                if isinstance(elemento, MensajeEntrante):
                    procesar(elemento)
            except Exception:
                logger.exception("fallo al procesar un mensaje del canal")
            finally:
                self._cola.task_done()
