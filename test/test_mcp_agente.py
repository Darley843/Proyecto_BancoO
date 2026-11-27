"""Pruebas del catálogo y el servidor MCP del agente `pana`."""

from __future__ import annotations

import asyncio
import json
import tomllib
from collections import Counter
from pathlib import Path

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from banco_occidente_corpus.herramientas.catalogo import CATALOGO, nombres
from banco_occidente_corpus.herramientas.servidor import (
    ConfiguracionMCP,
    cargar_configuracion_mcp,
    crear_servidor,
)

NOMBRES_ESPERADOS = (
    "consultar_tasa",
    "simular_cuota",
    "verificar_usura",
    "diagnosticar_capacidad",
    "comparar_escenario",
    "convocar_comite",
    "calcular_prestamo_gota",
    "comparar_gota_banco",
    "negociar_opcion",
    "generar_ficha_opcion",
    "responder_sobre_proyecto",
    "registrar_consentimiento",
    "olvidar_mis_datos",
    "solicitar_asesor",
    "consultar_caso",
    "generar_tarjeta_pana",
    "buscar_en_documentos",
    "consultar_tarifas",
    "clasificar_pregunta",
    "auditar_respuesta",
)


def test_catalogo_tiene_veinte_y_el_reparto_acordado() -> None:
    """El catálogo es exactamente el del OpenSpec, con sus dueñas."""
    assert len(CATALOGO) == 20
    assert nombres() == NOMBRES_ESPERADOS
    assert Counter(herramienta.duena for herramienta in CATALOGO) == {
        "Nayla": 11,
        "Darley": 5,
        "Anny": 4,
    }


def test_cada_entrada_es_un_esquema_pydantic_cerrado() -> None:
    """Cada entrada declara su JSON Schema y rechaza campos extra."""
    for herramienta in CATALOGO:
        esquema = herramienta.entrada.model_json_schema()
        assert esquema["type"] == "object"
        assert esquema["additionalProperties"] is False
        assert esquema["properties"]
        assert herramienta.entrada.model_config.get("extra") == "forbid"


def test_servidor_lista_veinte_con_entrada_y_salida() -> None:
    """El servidor expone las veinte herramientas con esquema de entrada y salida."""

    async def caso() -> None:
        servidor = crear_servidor()
        herramientas = await servidor.list_tools()
        assert [herramienta.name for herramienta in herramientas] == list(NOMBRES_ESPERADOS)
        for herramienta in herramientas:
            assert herramienta.input_schema["type"] == "object"
            assert herramienta.input_schema["properties"]
            assert herramienta.input_schema["required"]
            assert herramienta.output_schema is not None

    asyncio.run(caso())


def test_herramienta_fuera_del_catalogo_se_rechaza() -> None:
    """Una herramienta no declarada no se ejecuta."""

    async def caso() -> None:
        servidor = crear_servidor()
        with pytest.raises(ToolError):
            await servidor.call_tool("ejecutar_shell", {})

    asyncio.run(caso())


def test_configuracion_solo_acepta_loopback(tmp_path: Path) -> None:
    """El host del MCP no puede ser público y el puerto por defecto es 8765."""
    assert cargar_configuracion_mcp().host == ConfiguracionMCP().host == "127.0.0.1"
    assert cargar_configuracion_mcp().puerto == 8765
    archivo = tmp_path / "openclaw.toml"
    archivo.write_text('[mcp]\nhost = "0.0.0.0"\npuerto = 8765\n', encoding="utf-8")
    with pytest.raises(ValueError, match="loopback"):
        cargar_configuracion_mcp(archivo)


def test_entrada_del_agente_reexporta_el_servidor() -> None:
    """El módulo que arranca el MCP es la misma fábrica que usan las pruebas."""
    from banco_occidente_corpus.mcp_servidor import agente

    assert agente.crear_servidor is crear_servidor
    assert agente.cargar_configuracion_mcp is cargar_configuracion_mcp


def test_openclaw_json_declara_las_veinte_y_solo_loopback() -> None:
    """La copia versionada apunta al MCP, enumera el catálogo y cierra comandos."""
    datos = json.loads(Path("openclaw/openclaw.json").read_text(encoding="utf-8"))
    servidor = datos["mcp"]["servers"]["sucursal"]
    assert servidor["url"] == "http://127.0.0.1:8765/mcp"
    assert servidor["transport"] == "streamable-http"
    assert servidor["toolFilter"]["include"] == list(NOMBRES_ESPERADOS)
    assert datos["agents"]["entries"]["pana"]["tools"]["alsoAllow"] == ["bundle-mcp"]
    comandos = datos["commands"]
    for nombre in ("text", "restart", "config", "mcp", "plugins", "debug", "bash"):
        assert comandos[nombre] is False, f"commands.{nombre} debe quedar en false"


def test_config_del_gateway_es_local_y_tiene_timeout() -> None:
    """El TOML del gateway no publica nada y declara un timeout explícito."""
    datos = tomllib.loads(Path("config/openclaw.toml").read_text(encoding="utf-8"))
    assert datos["gateway"]["base_url"] == "http://127.0.0.1:18789"
    assert datos["gateway"]["timeout_segundos"] == 90.0
    assert datos["gateway"]["reintentos"] == 0
    assert datos["mcp"]["host"] == "127.0.0.1"
