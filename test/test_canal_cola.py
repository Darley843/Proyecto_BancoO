"""Pruebas de la cola de un trabajador del canal (sin red)."""

from __future__ import annotations

from datetime import UTC, datetime

from banco_occidente_corpus.canal.cola import ColaMensajes
from banco_occidente_corpus.canal.contratos import MensajeEntrante

AHORA = datetime(2026, 11, 19, 12, 0, tzinfo=UTC)


def _mensaje(indice: int) -> MensajeEntrante:
    """Construye un mensaje válido para la cola."""
    return MensajeEntrante(
        id_mensaje=f"wamid.{indice}",
        remitente="57000000001",
        texto=f"mensaje {indice}",
        recibido_en=AHORA,
    )


def test_procesa_en_orden() -> None:
    """Un solo trabajador conserva el orden de llegada."""
    cola = ColaMensajes()
    vistos: list[str] = []
    cola.iniciar(lambda mensaje: vistos.append(mensaje.id_mensaje))

    cola.encolar(_mensaje(1))
    cola.encolar(_mensaje(2))
    cola.encolar(_mensaje(3))
    cola.detener()

    assert vistos == ["wamid.1", "wamid.2", "wamid.3"]


def test_cola_llena_descarta_sin_bloquear() -> None:
    """Si no hay trabajador y la cola está llena, el mensaje se descarta."""
    cola = ColaMensajes(maximo=1)

    assert cola.encolar(_mensaje(1)) is True
    assert cola.encolar(_mensaje(2)) is False


def test_detener_sin_iniciar_no_falla() -> None:
    """Apagar una cola que nunca arrancó es inofensivo."""
    ColaMensajes().detener()
