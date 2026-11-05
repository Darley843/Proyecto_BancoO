"""Punto de entrada del Tablero: `python -m banco_occidente_corpus.tablero`."""

from __future__ import annotations

import sys

from ..config import load_config
from .construir import escribir_tablero, formatear_resumen


def main() -> int:
    """Construye el Tablero, lo reporta y devuelve 1 si falta una pregunta."""
    try:
        config = load_config()
        resumen = escribir_tablero(config)
    except (FileNotFoundError, ValueError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    print(formatear_resumen(resumen))
    return 1 if resumen.fallas else 0


if __name__ == "__main__":
    raise SystemExit(main())
