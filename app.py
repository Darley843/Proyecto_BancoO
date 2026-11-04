"""Arranque de la Sucursal 1965: API y app web en un solo servidor local.

``uv run python app.py`` equivale a ``make app``: levanta uvicorn en
``http://127.0.0.1:8000`` y sirve los archivos de ``app/web/`` (OpenSpec
``sucursal-1965``, decisión 15). Escucha solo en ``127.0.0.1``: nunca abre un
host público.

La API (``/api/...``) llega con el PR 10. Sus rutas se registran en
:func:`crear_app` **antes** de montar los estáticos, porque el montaje en ``/``
atiende todo lo que no haya reclamado una ruta anterior. Mientras la API no
exista, ``/api/estado`` responde 404 y la app web pasa sola a
``app/web/datos-ejemplo/``.

La app Streamlit de la fase 1 sigue disponible con ``make app-streamlit`` hasta
el PR de retiro (tarea 23.1).
"""

from __future__ import annotations

from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

HOST = "127.0.0.1"
PUERTO = 8000
RAIZ = Path(__file__).resolve().parent
CARPETA_WEB = RAIZ / "app" / "web"


def crear_app(carpeta_web: Path = CARPETA_WEB) -> FastAPI:
    """Crea la app FastAPI de la sucursal y monta la app web en ``/``.

    ``carpeta_web`` se puede cambiar en las pruebas para servir otra carpeta.
    """
    app = FastAPI(
        title="Sucursal 1965",
        description="Asistente de conocimiento sobre Banco de Occidente (proyecto TAAML, UAO).",
    )
    # PR 10: registrar aquí las rutas de la API, antes del montaje de estáticos.
    # app.include_router(api.router)
    app.mount("/", StaticFiles(directory=carpeta_web, html=True), name="web")
    return app


app = crear_app()


def main() -> None:
    """Levanta uvicorn en ``127.0.0.1:8000`` con la app de la sucursal."""
    print(f"Sucursal 1965 abierta en http://{HOST}:{PUERTO}  (Ctrl + C para cerrar)")
    uvicorn.run(app, host=HOST, port=PUERTO)


if __name__ == "__main__":
    main()
