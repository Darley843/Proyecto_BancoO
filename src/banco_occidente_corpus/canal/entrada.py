"""Extracción de mensajes del payload de WhatsApp Cloud API.

Meta envuelve cada evento en ``entry[].changes[].value``. Aquí se normaliza a
:class:`MensajeEntrante` lo que el canal sabe atender (texto, botón y lista) y se
ignoran estados de entrega, imágenes, audios y demás tipos no soportados.

El texto del mensaje se trata como dato: no se interpreta como instrucción ni se
registra en logs. Las pruebas viven en ``test/test_canal_entrada.py``.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, Literal

from .contratos import MensajeEntrante

#: Tipos de mensaje de Meta que el canal procesa.
TIPOS_SOPORTADOS: frozenset[str] = frozenset({"text", "interactive", "button"})

#: Tipo normalizado que entiende el contrato.
TipoMensaje = Literal["texto", "boton", "interactivo"]


def extraer_mensajes(datos: Mapping[str, Any]) -> list[MensajeEntrante]:
    """Convierte un payload del webhook en mensajes normalizados.

    Args:
        datos: JSON ya validado que envió Meta.

    Returns:
        Los mensajes soportados en orden; vacío si solo trae estados o tipos no
        soportados.
    """
    mensajes: list[MensajeEntrante] = []
    entradas = datos.get("entry")
    if not isinstance(entradas, list):
        return mensajes
    for entrada in entradas:
        if not isinstance(entrada, Mapping):
            continue
        cambios = entrada.get("changes")
        if not isinstance(cambios, list):
            continue
        for cambio in cambios:
            if not isinstance(cambio, Mapping) or cambio.get("field") != "messages":
                continue
            valor = cambio.get("value")
            if not isinstance(valor, Mapping):
                continue
            crudos = valor.get("messages")
            if not isinstance(crudos, list):
                continue
            for crudo in crudos:
                normalizado = _normalizar(crudo)
                if normalizado is not None:
                    mensajes.append(normalizado)
    return mensajes


def _normalizar(crudo: Any) -> MensajeEntrante | None:
    """Normaliza un mensaje crudo o devuelve ``None`` si no se atiende."""
    if not isinstance(crudo, Mapping):
        return None
    tipo_meta = crudo.get("type")
    if tipo_meta not in TIPOS_SOPORTADOS:
        return None

    id_mensaje = str(crudo.get("id", "")).strip()
    remitente = str(crudo.get("from", "")).strip()
    if not id_mensaje or not remitente:
        return None

    texto, tipo, id_boton = _contenido(crudo, str(tipo_meta))
    if not texto:
        return None

    return MensajeEntrante(
        id_mensaje=id_mensaje[:128],
        remitente=remitente,
        texto=texto[:4096],
        tipo=tipo,
        id_boton=id_boton,
        recibido_en=_instante(crudo.get("timestamp")),
    )


def _contenido(crudo: Mapping[str, Any], tipo_meta: str) -> tuple[str, TipoMensaje, str | None]:
    """Devuelve ``(texto, tipo, id_boton)`` según el tipo de Meta."""
    if tipo_meta == "text":
        bloque = crudo.get("text")
        cuerpo = bloque.get("body") if isinstance(bloque, Mapping) else None
        return (str(cuerpo).strip() if cuerpo else "", "texto", None)

    if tipo_meta == "interactive":
        bloque = crudo.get("interactive")
        if not isinstance(bloque, Mapping):
            return ("", "texto", None)
        for clave, tipo in (("button_reply", "boton"), ("list_reply", "interactivo")):
            respuesta = bloque.get(clave)
            if isinstance(respuesta, Mapping):
                identificador = str(respuesta.get("id", "")).strip()
                titulo = str(respuesta.get("title", "")).strip()
                return (titulo or identificador, tipo, identificador or None)
        return ("", "texto", None)

    bloque = crudo.get("button")
    if isinstance(bloque, Mapping):
        titulo = str(bloque.get("text", "")).strip()
        carga = str(bloque.get("payload", "")).strip()
        return (titulo or carga, "boton", carga or None)
    return ("", "texto", None)


def _instante(marca: Any) -> datetime:
    """Convierte el ``timestamp`` de Meta o usa ahora en UTC."""
    try:
        return datetime.fromtimestamp(int(str(marca)), UTC)
    except (TypeError, ValueError, OSError):
        return datetime.now(UTC)
