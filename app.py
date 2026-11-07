"""Arranque de la Sucursal 1965: API y app web en un solo servidor local.

``uv run python app.py`` equivale a ``make app``: levanta uvicorn en
``http://127.0.0.1:8000`` y sirve los archivos de ``app/web/`` (OpenSpec
``sucursal-1965``, decisión 15). Escucha solo en ``127.0.0.1``: nunca abre un
host público.

La API (``/api/...``) se registra en :func:`crear_app` **antes** de montar los
estáticos, porque el montaje en ``/`` atiende todo lo que no haya reclamado una
ruta anterior. Expone estado, Tablero, Bóveda, pipeline, Arqueo, Vestíbulo y
``POST /api/preguntar``: el grafo y sus dependencias se construyen en la primera
pregunta, nunca al importar este módulo.

La app web vive en ``app/web/`` y consume la API; la lógica del asistente está en
``asistente/`` y el grafo de la sucursal en ``sucursal/``.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from banco_occidente_corpus.config import Config, load_config
from banco_occidente_corpus.sucursal.ajustes import (
    ConfiguracionSucursal,
    cargar_configuracion_sucursal,
)
from banco_occidente_corpus.sucursal.api import crear_router
from banco_occidente_corpus.sucursal.costo import CacheRespuestas, GastoDiario
from banco_occidente_corpus.sucursal.preguntar import PiezasGrafo

HOST = "127.0.0.1"
PUERTO = 8000
RAIZ = Path(__file__).resolve().parent
CARPETA_WEB = RAIZ / "app" / "web"


def crear_app(
    carpeta_web: Path = CARPETA_WEB,
    *,
    config: Config | None = None,
    ajustes: ConfiguracionSucursal | None = None,
    cache: CacheRespuestas | None = None,
    piezas: Callable[[], PiezasGrafo] | None = None,
) -> FastAPI:
    """Crea la app FastAPI de la sucursal y monta la app web en ``/``.

    ``carpeta_web`` se puede cambiar en las pruebas para servir otra carpeta;
    ``config``, ``ajustes``, ``cache`` y ``piezas`` permiten inyectar rutas, topes
    y un grafo simulado sin tocar la red.
    """
    configuracion = config or load_config()
    parametros = ajustes or cargar_configuracion_sucursal()
    gasto = GastoDiario(configuracion.paths.root / "data/asistente/gasto.sqlite")
    app = FastAPI(
        title="Sucursal 1965",
        description="Asistente de conocimiento sobre Banco de Occidente (proyecto TAAML, UAO).",
    )
    app.include_router(crear_router(configuracion, parametros, gasto, cache=cache, piezas=piezas))
    app.mount("/", StaticFiles(directory=carpeta_web, html=True), name="web")
    return app


app = crear_app()


def main() -> None:
    """Levanta uvicorn en ``127.0.0.1:8000`` con la app de la sucursal."""
    print(f"Sucursal 1965 abierta en http://{HOST}:{PUERTO}  (Ctrl + C para cerrar)")
    uvicorn.run(app, host=HOST, port=PUERTO)


if __name__ == "__main__":
    main()
