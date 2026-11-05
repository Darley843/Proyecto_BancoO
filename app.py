"""Arranque de la Sucursal 1965: API y app web en un solo servidor local.

``uv run python app.py`` equivale a ``make app``: levanta uvicorn en
``http://127.0.0.1:8000`` y sirve los archivos de ``app/web/`` (OpenSpec
``sucursal-1965``, decisión 15). Escucha solo en ``127.0.0.1``: nunca abre un
host público.

La API (``/api/...``) se registra en :func:`crear_app` **antes** de montar los
estáticos, porque el montaje en ``/`` atiende todo lo que no haya reclamado una
ruta anterior. Expone estado, Tablero, Bóveda, pipeline, Arqueo y Vestíbulo; el
endpoint de preguntas llega en el PR 10b.

La app Streamlit de la fase 1 sigue disponible con ``make app-streamlit`` hasta
el PR de retiro (tarea 23.1).
"""

from __future__ import annotations

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
from banco_occidente_corpus.sucursal.costo import GastoDiario

HOST = "127.0.0.1"
PUERTO = 8000
RAIZ = Path(__file__).resolve().parent
CARPETA_WEB = RAIZ / "app" / "web"


def crear_app(
    carpeta_web: Path = CARPETA_WEB,
    *,
    config: Config | None = None,
    ajustes: ConfiguracionSucursal | None = None,
) -> FastAPI:
    """Crea la app FastAPI de la sucursal y monta la app web en ``/``.

    ``carpeta_web`` se puede cambiar en las pruebas para servir otra carpeta;
    ``config`` y ``ajustes`` permiten inyectar rutas y topes temporales.
    """
    configuracion = config or load_config()
    parametros = ajustes or cargar_configuracion_sucursal()
    gasto = GastoDiario(configuracion.paths.root / "data/asistente/gasto.sqlite")
    app = FastAPI(
        title="Sucursal 1965",
        description="Asistente de conocimiento sobre Banco de Occidente (proyecto TAAML, UAO).",
    )
    app.include_router(crear_router(configuracion, parametros, gasto))
    app.mount("/", StaticFiles(directory=carpeta_web, html=True), name="web")
    return app


app = crear_app()


def main() -> None:
    """Levanta uvicorn en ``127.0.0.1:8000`` con la app de la sucursal."""
    print(f"Sucursal 1965 abierta en http://{HOST}:{PUERTO}  (Ctrl + C para cerrar)")
    uvicorn.run(app, host=HOST, port=PUERTO)


if __name__ == "__main__":
    main()
