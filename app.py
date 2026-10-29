"""Lanzador de la app Streamlit desde la raíz del repositorio.

``uv run streamlit run app.py`` equivale a ``make app``
(``uv run streamlit run app/streamlit_app.py``). Streamlit agrega al
``sys.path`` la carpeta del script que ejecuta, y la interfaz vive en ``app/``:
el lanzador deja la raíz y ``app/`` en el camino de importación antes de
ejecutar la interfaz, para que ambos comandos compartan los mismos imports.
"""

from __future__ import annotations

import runpy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
APP_DIR = ROOT / "app"


def main() -> None:
    """Ejecuta ``app/streamlit_app.py`` como si fuera el script principal."""
    for path in (ROOT, APP_DIR):
        if str(path) not in sys.path:
            sys.path.insert(0, str(path))
    runpy.run_path(str(APP_DIR / "streamlit_app.py"), run_name="__main__")


if __name__ == "__main__":
    main()
