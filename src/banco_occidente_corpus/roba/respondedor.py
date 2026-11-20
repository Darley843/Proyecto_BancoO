"""Asistente de Roba la Bóveda: la Sucursal en modo demo con el corpus sintético.

Usa el mismo grafo que la Ventanilla, pero siempre en **modo demo** (sin
modelo, sin gasto y sin caché) y con el fragmento de prueba de
``sucursal/demo_inyeccion.py``, que trae una orden escondida. Así el juego no
consume DeepSeek, la misma batería da el mismo resultado y el ataque se prueba
contra un corpus sintético, nunca contra el sitio del banco ni contra WhatsApp.
La memoria de los hilos ``roba:<sesion>`` va en su propia base para no mezclarse
con la conversación de la Ventanilla.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from ..config import Config
from ..sucursal.ajustes import ConfiguracionSucursal
from ..sucursal.costo import GastoDiario
from ..sucursal.preguntar import ErrorSucursal, PiezasGrafo, ServicioPreguntas, construir_piezas
from .api import AsistenteNoDisponible, RespuestaAsistente

#: Memoria propia de los hilos del juego.
RUTA_MEMORIA_ROBA = "data/asistente/roba_memoria.sqlite"
#: Carpeta de los prompts versionados.
RUTA_PROMPTS = "config/prompts"
#: Largo mínimo de una línea del prompt para usarla como marcador de fuga.
LARGO_MARCADOR = 40


def marcadores_de_prompts(carpeta: Path) -> tuple[str, ...]:
    """Toma las líneas largas de los prompts versionados como marcadores de fuga.

    Si una de estas líneas aparece en una respuesta, el prompt se filtró.

    Args:
        carpeta: carpeta con los prompts (``config/prompts``).

    Returns:
        Las líneas sin repetir, en orden estable; vacío si la carpeta falta.
    """
    if not carpeta.is_dir():
        return ()
    lineas: dict[str, None] = {}
    for archivo in sorted(carpeta.rglob("*")):
        if not archivo.is_file() or archivo.suffix.lower() not in {".md", ".txt", ".toml"}:
            continue
        try:
            contenido = archivo.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for linea in contenido.splitlines():
            limpia = linea.strip()
            if len(limpia) >= LARGO_MARCADOR:
                lineas.setdefault(limpia, None)
    return tuple(lineas)


class RespondedorSucursal:
    """Responde los intentos con el grafo de la Sucursal en modo demo."""

    def __init__(self, config: Config, ajustes: ConfiguracionSucursal, gasto: GastoDiario) -> None:
        """Prepara un servicio propio en modo demo; el grafo se arma en el primer intento.

        Args:
            config: configuración con las rutas del corpus.
            ajustes: configuración de la Sucursal; aquí se fuerza el modo demo.
            gasto: acumulado diario; en demo no se escribe.
        """
        demo = replace(ajustes, demo=True)
        raiz = config.paths.root

        def piezas() -> PiezasGrafo:
            """Construye el grafo demo con el fragmento de prueba y memoria propia."""
            return construir_piezas(
                config, demo, inyeccion=True, ruta_memoria=raiz / RUTA_MEMORIA_ROBA
            )

        self._servicio = ServicioPreguntas(config, demo, gasto, piezas=piezas, usar_cache=False)
        self._marcadores = marcadores_de_prompts(raiz / RUTA_PROMPTS)

    def permitidos(self) -> tuple[str, ...]:
        """Devuelve los datos públicos del banco (canal oficial) que no son PII.

        Construye el grafo si aún no existe; si no se puede (sin índice o sin
        Ollama), el error sube y la API sigue sin datos públicos.

        Returns:
            Los datos públicos que el Digiturno ya acepta.
        """
        dependencias = self._servicio.piezas().dependencias
        return tuple(str(valor) for valor in getattr(dependencias, "permitidos", ()))

    def responder(self, texto: str, hilo: str) -> RespuestaAsistente:
        """Responde el intento y adjunta los datos públicos y los marcadores del prompt.

        Args:
            texto: intento sin datos personales.
            hilo: hilo ``roba:<sesion>``.

        Returns:
            La respuesta, la letra y el motivo del turno.

        Raises:
            AsistenteNoDisponible: si la Sucursal no puede responder (sin índice,
                sin Ollama o con un error del contrato).
        """
        try:
            datos = self._servicio.preguntar(texto, hilo)
        except ErrorSucursal as error:
            raise AsistenteNoDisponible(error.codigo, error.mensaje, error.estado_http) from error
        return RespuestaAsistente(
            respuesta=str(datos.get("respuesta", "")),
            turno=str(datos.get("turno", "B")),
            motivo=str(datos.get("motivo", "")),
            permitidos=self.permitidos(),
            marcadores_prompt=self._marcadores,
        )
