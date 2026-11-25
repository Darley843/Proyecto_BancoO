"""Punto de entrada del servidor MCP del agente `pana`.

`python -m banco_occidente_corpus.mcp_servidor.agente` arranca el servidor HTTP
con las veinte herramientas del catálogo, en `127.0.0.1:8765` por defecto. El
servidor de solo lectura `boveda-occidente` conserva su propio comando stdio.
"""

from __future__ import annotations

from ..herramientas.servidor import ConfiguracionMCP, cargar_configuracion_mcp, crear_servidor, main

__all__ = ["ConfiguracionMCP", "cargar_configuracion_mcp", "crear_servidor", "main"]

if __name__ == "__main__":
    raise SystemExit(main())
