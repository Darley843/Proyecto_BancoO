"""Punto de entrada: `python -m banco_occidente_corpus.herramientas`."""

from __future__ import annotations

import sys

from .catalogo import main

if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
