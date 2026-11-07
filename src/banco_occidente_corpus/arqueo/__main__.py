"""Punto de entrada del Arqueo: `python -m banco_occidente_corpus.arqueo`.

`make arqueo` ejecuta solo los experimentos y el reporte. No toca `all`, `gold`
ni `deliver` y no necesita `DEEPSEEK_API_KEY`: el unico costo del Arqueo es cero.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import cast

from ..boveda.fragmentos import ALCANCES, Alcance
from ..config import PROJECT_ROOT, load_config
from .informe import SALIDA_JSON, SALIDA_MD, ejecutar_arqueo


def _crear_parser() -> argparse.ArgumentParser:
    """Construye el parser de la linea de comandos del Arqueo."""
    parser = argparse.ArgumentParser(
        prog="python -m banco_occidente_corpus.arqueo",
        description="Mide recuperacion y evaluacion y escribe el reporte del Arqueo.",
    )
    parser.add_argument(
        "--alcance",
        choices=ALCANCES,
        default="base",
        help="alcance del indice que se mide: base (por defecto) o completo",
    )
    parser.add_argument(
        "--reconstruir-sin-prefijos",
        action="store_true",
        help="reconstruye el indice extra sin prefijos aunque exista uno compatible",
    )
    return parser


def commit_actual() -> str:
    """Devuelve el commit corto de Git o una cadena vacia si no hay repositorio."""
    resultado = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if resultado.returncode != 0:
        return ""
    return resultado.stdout.strip()


def main(argv: Sequence[str] | None = None) -> int:
    """Ejecuta el Arqueo y devuelve el codigo de salida."""
    args = _crear_parser().parse_args(argv)
    config = load_config()
    try:
        arqueo, _ = ejecutar_arqueo(
            config,
            alcance=_alcance(args.alcance),
            commit=commit_actual(),
            reconstruir_sin_prefijos=bool(args.reconstruir_sin_prefijos),
        )
    except (FileNotFoundError, ValueError, RuntimeError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1

    print("Arqueo escrito:")
    print(f"  {_ruta_visible(SALIDA_JSON)}")
    print(f"  {_ruta_visible(SALIDA_MD)}")
    print(f"Configuraciones medidas: {len(arqueo['recuperacion'])}")
    return 0


def _alcance(valor: str) -> Alcance:
    """Convierte el argumento de la CLI en un alcance tipado."""
    return cast(Alcance, valor)


def _ruta_visible(ruta: Path) -> str:
    """Muestra una ruta relativa al proyecto, sin rutas absolutas."""
    try:
        return ruta.relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return ruta.name


if __name__ == "__main__":
    raise SystemExit(main())
