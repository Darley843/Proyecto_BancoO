"""Punto de entrada de la Bóveda: `python -m banco_occidente_corpus.boveda`."""

from __future__ import annotations

import argparse
import sys
import time
from collections.abc import Sequence

from ..config import load_config
from .fragmentos import ALCANCES, escribir_fragmentos, formatear_resumen
from .indice import (
    AvisoLote,
    TiempoAgotadoEmbeddings,
    construir_indice,
    formatear_duracion,
    formatear_resumen_indice,
)


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


def _mensaje_tiempo_agotado(error: TiempoAgotadoEmbeddings) -> str:
    """Redacta el mensaje de un lote que agotó el tiempo de espera."""
    return "\n".join(
        [
            f"Error: se agotó el tiempo de espera ({error.timeout_segundos:g} s) al vectorizar "
            f"el lote {error.lote} de {error.lotes}.",
            "El índice anterior queda intacto: no se reinició la colección.",
            "Sube timeout_segundos en config/sucursal.toml o comprueba que Ollama responde "
            "con `ollama ps`.",
        ]
    )


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
            inicio = time.monotonic()

            def avisar(aviso: AvisoLote) -> None:
                """Imprime el avance de un lote vectorizado."""
                print(
                    f"lote {aviso.lote}/{aviso.lotes} · "
                    f"{aviso.procesados}/{aviso.total} fragmentos · "
                    f"{formatear_duracion(time.monotonic() - inicio)}",
                    flush=True,
                )

            resumen_indice = construir_indice(config, args.alcance, progreso=avisar)
            print(formatear_resumen_indice(resumen_indice))
            print(f"Tiempo total: {formatear_duracion(time.monotonic() - inicio)}")
            return 0
    except TiempoAgotadoEmbeddings as error:
        print(_mensaje_tiempo_agotado(error), file=sys.stderr)
        return 1
    except (FileNotFoundError, ValueError, RuntimeError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
