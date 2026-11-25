"""API de solo lectura con las últimas llamadas a las herramientas del agente.

La pantalla de la escena muestra en vivo qué herramienta usó Pana, si salió bien
y cuánto tardó. La fuente es la traza local que escribe el servidor MCP
(``herramientas/traza.py``); esta ruta solo la lee.

Para el público se entregan únicamente el nombre de la herramienta, la hora,
el resultado y la latencia. Los argumentos **no** salen de aquí, ni siquiera el
resumen de la traza: el prefijo de la huella y los largos de texto se quedan en
el computador (``make traza`` los sigue mostrando a quien facilita).

Las pruebas viven en ``test/test_herramientas_api.py``.
"""

from __future__ import annotations

from fastapi import APIRouter, Query
from pydantic import BaseModel, ConfigDict, Field

from .traza import RegistroTraza, ultimas

#: Cuántas llamadas pide la pantalla si no dice otra cosa.
CANTIDAD_POR_DEFECTO: int = 8
#: Tope de llamadas por petición: la pantalla no necesita más.
CANTIDAD_MAXIMA: int = 50


class LlamadaPublica(BaseModel):
    """Una llamada a una herramienta, sin argumentos ni datos del invitado."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(description="Identificador corto de la llamada en la traza.")
    momento: str = Field(description="Hora UTC de la llamada, en ISO 8601.")
    herramienta: str = Field(description="Nombre de la herramienta en el catálogo.")
    ok: bool = Field(description="True si la herramienta respondió sin error.")
    codigo: str | None = Field(description="Código de error, o null si salió bien.")
    latencia_ms: float = Field(description="Duración de la llamada en milisegundos.")


class TrazaPublica(BaseModel):
    """Respuesta de ``GET /api/herramientas/traza``."""

    model_config = ConfigDict(extra="forbid")

    llamadas: list[LlamadaPublica] = Field(
        description="Últimas llamadas, de la más nueva a la más vieja."
    )


def a_publica(registro: RegistroTraza) -> LlamadaPublica:
    """Quita los argumentos de un registro de la traza.

    Args:
        registro: línea leída de la traza local.

    Returns:
        La misma llamada sin el resumen de argumentos.
    """
    return LlamadaPublica(
        id=registro.id,
        momento=registro.momento,
        herramienta=registro.herramienta,
        ok=registro.ok,
        codigo=registro.codigo,
        latencia_ms=registro.latencia_ms,
    )


def crear_router_herramientas() -> APIRouter:
    """Crea el router de la traza pública de herramientas.

    Returns:
        Router con ``GET /api/herramientas/traza``.
    """
    router = APIRouter(prefix="/api/herramientas", tags=["herramientas"])

    @router.get("/traza", response_model=TrazaPublica)
    def traza(
        n: int = Query(CANTIDAD_POR_DEFECTO, ge=1, le=CANTIDAD_MAXIMA),
    ) -> TrazaPublica:
        """Devuelve las últimas llamadas, la más nueva primero.

        Args:
            n: cuántas llamadas devolver (1 a 50).

        Returns:
            Las llamadas sin argumentos; lista vacía si aún no hay traza.
        """
        registros = ultimas(n)
        return TrazaPublica(llamadas=[a_publica(r) for r in reversed(registros)])

    return router
