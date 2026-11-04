"""Punto de entrada de la Bóveda: `python -m banco_occidente_corpus.boveda`."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from ..config import load_config
from .fragmentos import ALCANCES, escribir_fragmentos, formatear_resumen
from .indice import construir_indice, formatear_resumen_indice


def _crear_parser() -> argparse.ArgumentParser:
    """Construye el parser de la línea de comandos de la Bóveda."""
    parser = argparse.ArgumentParser(
        prog="python -m banco_occidente_corpus.boveda",
        description="Herramientas de la Bóveda del corpus.",
    )
    subcomandos = parser.add_subparsers(dest="comando", required=True)
    fragmentos = subcomandos.add_parser(
        "fragmentos",
        help="construye el JSONL de fragmentos desde chunks y hechos",
    )
    fragmentos.add_argument(
        "--alcance",
        choices=ALCANCES,
        default="base",
        help="alcance del índice: base (por defecto) o completo",
    )
    indice = subcomandos.add_parser(
        "indice",
        help="vectoriza los fragmentos con Ollama y reconstruye el índice Chroma",
    )
    indice.add_argument(
        "--alcance",
        choices=ALCANCES,
        default="base",
        help="alcance del índice: base (por defecto) o completo",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Ejecuta el subcomando pedido y devuelve el código de salida."""
    args = _crear_parser().parse_args(argv)
    try:
        config = load_config()
        if args.comando == "fragmentos":
            ruta, resumen = escribir_fragmentos(config, args.alcance)
            print(formatear_resumen(resumen, ruta))
            return 0
        if args.comando == "indice":
            resumen_indice = construir_indice(config, args.alcance)
            print(formatear_resumen_indice(resumen_indice))
            return 0
    except (FileNotFoundError, ValueError, RuntimeError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
