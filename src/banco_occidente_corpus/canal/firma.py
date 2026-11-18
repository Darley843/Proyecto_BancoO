"""Firma ``X-Hub-Signature-256`` del webhook de WhatsApp.

Meta firma el **cuerpo crudo** con HMAC-SHA256 y el App Secret. La comparación
se hace en tiempo constante y una cabecera ausente o con otro esquema cuenta
como firma inválida: el mensaje no se procesa.
"""

from __future__ import annotations

import hashlib
import hmac

#: Prefijo que Meta pone delante del hexadecimal.
PREFIJO_FIRMA: str = "sha256="


def calcular_firma(cuerpo: bytes, secreto: str) -> str:
    """Calcula la firma de un cuerpo con el App Secret.

    Args:
        cuerpo: bytes exactos recibidos en la petición, sin reserializar.
        secreto: App Secret de la app de Meta.

    Returns:
        La cabecera completa, con el prefijo ``sha256=``.
    """
    digerido = hmac.new(secreto.encode("utf-8"), cuerpo, hashlib.sha256).hexdigest()
    return f"{PREFIJO_FIRMA}{digerido}"


def firma_valida(cuerpo: bytes, cabecera: str | None, secreto: str) -> bool:
    """Indica si la cabecera corresponde al cuerpo y al secreto.

    Args:
        cuerpo: bytes exactos recibidos en la petición.
        cabecera: valor de ``X-Hub-Signature-256``; puede faltar.
        secreto: App Secret de la app de Meta.

    Returns:
        ``True`` solo si la cabecera tiene el prefijo correcto y coincide en
        tiempo constante; ``False`` en cualquier otro caso, incluido un secreto
        vacío.
    """
    if not secreto or not cabecera or not cabecera.startswith(PREFIJO_FIRMA):
        return False
    return hmac.compare_digest(calcular_firma(cuerpo, secreto), cabecera)
