"""Identidad del canal: número en E.164 y huella HMAC.

El número de WhatsApp nunca se guarda: se normaliza a E.164 y se convierte en
``usuario_id = HMAC-SHA256(número, WHATSAPP_ID_SALT)``. La sal vive en el
entorno; el número en claro solo existe en memoria durante la petición.

El comando auxiliar sirve para autorizar un número sin escribirlo en el
repositorio::

    python -m banco_occidente_corpus.canal.identidad --huella "+57 300 123 4567"

Imprime la huella; no imprime la sal ni el número. Las pruebas viven en
``test/test_canal_identidad.py``.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import os
import sys
from collections.abc import Sequence

#: Largo mínimo de un número E.164, sin contar el ``+``.
LARGO_MINIMO: int = 8

#: Largo máximo de un número E.164, sin contar el ``+``.
LARGO_MAXIMO: int = 15

#: País por defecto cuando el número llega sin prefijo.
PAIS_POR_DEFECTO: str = "57"


def normalizar_numero(numero: str, pais: str = PAIS_POR_DEFECTO) -> str:
    """Convierte un número a E.164 con el ``+`` y el prefijo de país.

    Acepta espacios, guiones, paréntesis, ``+57`` o ``0057``. Un número de diez
    dígitos se interpreta como nacional y se prefija con ``pais``; si ya trae el
    país debe llegar completo, con once dígitos o más. No se adivina por el
    prefijo: dos números de diez dígitos nunca se confunden.

    Args:
        numero: número tal como lo escribe la persona o lo envía Meta.
        pais: prefijo de país para números nacionales; por defecto ``57``.

    Returns:
        El número en formato E.164, por ejemplo ``+573001234567``.

    Raises:
        ValueError: si no quedan entre 8 y 15 dígitos.
    """
    digitos = "".join(caracter for caracter in numero if caracter.isdigit())
    if digitos.startswith("00"):
        digitos = digitos[2:]
    if len(digitos) == 10:
        digitos = f"{pais}{digitos}"
    if not LARGO_MINIMO <= len(digitos) <= LARGO_MAXIMO:
        raise ValueError("el número no tiene un largo E.164 válido")
    return f"+{digitos}"


def calcular_usuario_id(numero: str, sal: str, pais: str = PAIS_POR_DEFECTO) -> str:
    """Calcula ``usuario_id`` como HMAC-SHA256 del número normalizado.

    Args:
        numero: número en cualquier formato; se normaliza antes de la huella.
        sal: ``WHATSAPP_ID_SALT``; una sal distinta produce otra identidad.
        pais: prefijo de país para números nacionales.

    Returns:
        Huella hexadecimal de 64 caracteres.

    Raises:
        ValueError: si la sal está vacía o el número no es válido.
    """
    if not sal:
        raise ValueError("WHATSAPP_ID_SALT no puede estar vacía")
    normalizado = normalizar_numero(numero, pais)
    return hmac.new(sal.encode("utf-8"), normalizado.encode("utf-8"), hashlib.sha256).hexdigest()


def main(argv: Sequence[str] | None = None) -> int:
    """Imprime la huella de un número para autorizarlo en la configuración.

    Args:
        argv: argumentos de línea de comandos; por defecto ``sys.argv[1:]``.

    Returns:
        0 si imprime la huella, 2 si falta la sal o el número no es válido.
    """
    analizador = argparse.ArgumentParser(
        prog="python -m banco_occidente_corpus.canal.identidad",
        description="Calcula la huella HMAC de un número de WhatsApp.",
    )
    analizador.add_argument("--huella", metavar="NUMERO", required=True)
    analizador.add_argument("--pais", default=PAIS_POR_DEFECTO)
    argumentos = analizador.parse_args(argv)

    sal = os.getenv("WHATSAPP_ID_SALT", "").strip()
    if not sal:
        print("Falta WHATSAPP_ID_SALT en el entorno.", file=sys.stderr)
        return 2

    try:
        print(calcular_usuario_id(argumentos.huella, sal, argumentos.pais))
    except ValueError as error:
        print(f"Número inválido: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
