"""Prueba manual del cliente del gateway de OpenClaw.

No corre en ``make check``: necesita el gateway encendido y el token en el
entorno. Uso en PowerShell, en la misma sesión donde se arranca la app::

    $env:OPENCLAW_ACTIVO = "1"
    $env:OPENCLAW_GATEWAY_TOKEN = "<token>"
    uv run python scripts/probar_openclaw.py --texto "¿Cuál es la tasa?"

El script no imprime el token ni envía datos personales: usa una huella de
prueba de 64 hexadecimales. Si el gateway no responde, sale con código 1 y el
mensaje de respaldo; así se distingue de un fallo de configuración (código 2).
"""

from __future__ import annotations

import argparse
import os
import sys

from banco_occidente_corpus.canal.openclaw import (
    VALORES_ACTIVO,
    VARIABLE_ACTIVO,
    VARIABLE_TOKEN,
    ClienteOpenClaw,
    cargar_configuracion_openclaw,
)
from banco_occidente_corpus.config import load_config

#: Huella HMAC ficticia: 64 hexadecimales, sin número en claro.
HUELLA_PRUEBA: str = "0" * 64

#: Pregunta de humo si no se pasa ``--texto``.
TEXTO_POR_DEFECTO: str = "¿Cuál es la tasa de libre inversión?"


def main(argv: list[str] | None = None) -> int:
    """Consulta el gateway y devuelve un código de salida para la consola.

    Args:
        argv: argumentos de línea de comandos; por defecto ``sys.argv[1:]``.

    Returns:
        ``0`` si el gateway respondió, ``1`` si devolvió un fallo y ``2`` si
        falta el interruptor, el token o el contacto académico.
    """
    parser = argparse.ArgumentParser(description="Prueba el cliente de OpenClaw del canal.")
    parser.add_argument("--texto", default=TEXTO_POR_DEFECTO, help="mensaje nuevo a enviar")
    parser.add_argument(
        "--huella",
        default=HUELLA_PRUEBA,
        help="huella HMAC de 64 hexadecimales; por defecto una de prueba",
    )
    args = parser.parse_args(argv)

    huella = args.huella.strip().casefold()
    if len(huella) != 64 or any(caracter not in "0123456789abcdef" for caracter in huella):
        parser.error("--huella debe ser HMAC-SHA256 en hexadecimal de 64 caracteres")

    if os.getenv(VARIABLE_ACTIVO, "").strip().casefold() not in VALORES_ACTIVO:
        print(
            f"OpenClaw está apagado: define {VARIABLE_ACTIVO}=1 en esta sesión.",
            file=sys.stderr,
        )
        return 2
    token = os.getenv(VARIABLE_TOKEN, "").strip()
    if not token:
        print(f"Falta {VARIABLE_TOKEN}: el canal usaría el grafo.", file=sys.stderr)
        return 2

    sitio = load_config()
    if not sitio.site.contact.strip():
        print("Falta site.contact en config/site.toml para el header From.", file=sys.stderr)
        return 2

    cliente = ClienteOpenClaw(
        cargar_configuracion_openclaw(),
        token,
        sitio.site.user_agent,
        sitio.site.contact,
    )
    try:
        respuesta = cliente.responder(args.texto, huella)
    finally:
        cliente.cerrar()

    if respuesta is None:
        print(
            "El gateway no dio una respuesta usable: el despachador usaría el grafo.",
            file=sys.stderr,
        )
        return 1
    print(respuesta)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
