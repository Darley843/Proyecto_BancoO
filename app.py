"""Arranque de la Sucursal 1965: API y app web en un solo servidor local.

``uv run python app.py`` equivale a ``make app``: levanta uvicorn en
``http://127.0.0.1:8000`` y sirve los archivos de ``app/web/`` (OpenSpec
``sucursal-1965``, decisión 15). Escucha solo en ``127.0.0.1``: nunca abre un
host público.

La API (``/api/...``) se registra en :func:`crear_app` **antes** de montar los
estáticos, porque el montaje en ``/`` atiende todo lo que no haya reclamado una
ruta anterior. Expone estado, Tablero, Bóveda, pipeline, Arqueo, Vestíbulo,
``POST /api/preguntar`` y ``GET /health``: el grafo y sus dependencias se
construyen en la primera pregunta, nunca al importar este módulo.

La app web vive en ``app/web/`` y consume la API; la lógica del asistente está en
``asistente/`` y el grafo de la sucursal en ``sucursal/``.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Response
from fastapi.staticfiles import StaticFiles

from banco_occidente_corpus.boveda.mapa import ServicioMapa
from banco_occidente_corpus.config import Config, load_config
from banco_occidente_corpus.sucursal.ajustes import (
    ConfiguracionSucursal,
    cargar_configuracion_sucursal,
)
from banco_occidente_corpus.sucursal.api import (
    SaludRespuesta,
    crear_router,
    salud_operativa,
)
from banco_occidente_corpus.sucursal.costo import CacheRespuestas, GastoDiario
from banco_occidente_corpus.sucursal.preguntar import PiezasGrafo
from banco_occidente_corpus.sucursal.transmision import cerrar_transmisiones

HOST = "127.0.0.1"
PUERTO = 8000
#: Segundos que uvicorn espera a las conexiones abiertas al recibir Ctrl + C.
ESPERA_APAGADO_SEGUNDOS = 5
RAIZ = Path(__file__).resolve().parent
CARPETA_WEB = RAIZ / "app" / "web"


@asynccontextmanager
async def _ciclo_de_vida(_: FastAPI) -> AsyncIterator[None]:
    """Suelta las transmisiones abiertas cuando la app se apaga.

    uvicorn espera a las conexiones abiertas antes de llegar aquí, así que el
    corte de un stream vivo lo acota ``timeout_graceful_shutdown``; este cierre
    cubre el apagado en proceso (pruebas, uso embebido) y no deja colas con
    consumidores pendientes.

    Args:
        _: la app que arranca o se apaga; no se usa.

    Yields:
        El control durante toda la vida del servidor.
    """
    yield
    cerrar_transmisiones()


def crear_app(
    carpeta_web: Path = CARPETA_WEB,
    *,
    config: Config | None = None,
    ajustes: ConfiguracionSucursal | None = None,
    cache: CacheRespuestas | None = None,
    piezas: Callable[[], PiezasGrafo] | None = None,
    mapa_boveda: ServicioMapa | None = None,
) -> FastAPI:
    """Crea la app FastAPI de la sucursal y monta la app web en ``/``.

    ``carpeta_web`` se puede cambiar en las pruebas para servir otra carpeta;
    ``config``, ``ajustes``, ``cache``, ``piezas`` y ``mapa_boveda`` permiten
    inyectar rutas, topes, un grafo simulado y un mapa sin tocar la red.
    """
    configuracion = config or load_config()
    parametros = ajustes or cargar_configuracion_sucursal()
    gasto = GastoDiario(configuracion.paths.root / "data/asistente/gasto.sqlite")
    app = FastAPI(
        title="Sucursal 1965",
        description="Asistente de conocimiento sobre Banco de Occidente (proyecto TAAML, UAO).",
        lifespan=_ciclo_de_vida,
    )
    app.include_router(
        crear_router(
            configuracion,
            parametros,
            gasto,
            cache=cache,
            piezas=piezas,
            mapa_boveda=mapa_boveda,
        )
    )

    @app.get("/health", response_model=SaludRespuesta, tags=["salud"])
    def salud(response: Response) -> SaludRespuesta:
        """Responde el chequeo de salud en la raíz, como esperan los monitores.

        Va en ``/`` y no en ``/api`` a propósito: es la ruta que prueban los
        monitores y la que se consulta al arrancar. Devuelve 200 cuando hay
        índice o se está en demo, y 503 cuando la Sucursal no puede responder.

        Args:
            response: respuesta de FastAPI, para fijar el estado HTTP.

        Returns:
            El estado operativo mínimo, sin red, sin claves ni datos de clientes.
        """
        estado = salud_operativa(configuracion, parametros)
        response.status_code = 200 if estado.estado == "ok" else 503
        return estado

    app.mount("/", StaticFiles(directory=carpeta_web, html=True), name="web")
    return app


app = crear_app()


def main() -> None:
    """Levanta uvicorn en ``127.0.0.1:8000`` con la app de la sucursal.

    Fija ``timeout_graceful_shutdown`` para que Ctrl + C cierre aunque quede una
    ventana con el streaming SSE abierto: las transmisiones se cortan en el
    apagado y, si alguna no responde, uvicorn sale igual tras la espera.
    """
    print(f"Sucursal 1965 abierta en http://{HOST}:{PUERTO}  (Ctrl + C para cerrar)")
    uvicorn.run(
        app,
        host=HOST,
        port=PUERTO,
        timeout_graceful_shutdown=ESPERA_APAGADO_SEGUNDOS,
    )


if __name__ == "__main__":
    main()
