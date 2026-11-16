"""Pruebas sin red ni navegador de la vista Operación (entrega final, 8.8).

Comprueban la forma de ``datos-ejemplo/operacion.json`` frente al contrato de
``GET /api/operacion`` (design.md, decisión 16) y las reglas de la spec
``sucursal-frontend``: solo lectura, sin datos personales, estados vacíos
claros y latencia con la caché aparte.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

RAIZ = Path(__file__).resolve().parents[1]
WEB = RAIZ / "app" / "web"
EJEMPLO = WEB / "datos-ejemplo" / "operacion.json"
VISTA = WEB / "vistas" / "operacion.js"

FLUJOS = {"webhook", "diagnostico", "hitl", "mcp"}
CAMPOS_LATENCIA = {"p50_ms", "p95_ms", "n", "suficiente"}
CAMPOS_CASO = {"id", "motivo", "semaforo", "estado", "creado"}


def leer_ejemplo() -> dict[str, Any]:
    """Lee ``app/web/datos-ejemplo/operacion.json``."""
    return json.loads(EJEMPLO.read_text(encoding="utf-8"))


def leer_vista() -> str:
    """Lee el código de la vista Operación."""
    return VISTA.read_text(encoding="utf-8")


def bloque_css() -> str:
    """Devuelve el bloque CSS de Operación, entre sus marcadores."""
    css = (WEB / "estilos.css").read_text(encoding="utf-8")
    inicio = css.index("/* --- operacion (entrega final, 8.8) --- */")
    fin = css.index("/* --- fin operacion --- */", inicio)
    return css[inicio:fin]


def test_bloques_de_ejemplo_tienen_sus_campos() -> None:
    """Cada bloque trae los campos del contrato con tipos enteros."""
    datos = leer_ejemplo()
    assert set(datos["canal"]) == {"configurado", "modo", "numeros_autorizados"}
    assert datos["canal"]["modo"] in {"real", "falso", "deshabilitado"}
    assert isinstance(datos["canal"]["configurado"], bool)
    assert set(datos["mensajes"]) == {
        "recibidos",
        "respondidos",
        "errores",
        "pendientes",
        "duplicados",
    }
    assert set(datos["consentimientos"]) == {"aceptados", "pendientes", "revocados"}
    assert set(datos["casos"]) == {"pendientes", "contactados", "descartados", "lista"}
    assert set(datos["roba"]) == {"intentos", "exitos", "puntos", "por_categoria"}
    for bloque in ("mensajes", "consentimientos", "roba"):
        for clave, valor in datos[bloque].items():
            if clave != "por_categoria":
                assert isinstance(valor, int) and valor >= 0, (bloque, clave)


def test_mensajes_de_ejemplo_cuadran() -> None:
    """Respondidos, errores y cola suman los recibidos."""
    mensajes = leer_ejemplo()["mensajes"]
    total = mensajes["respondidos"] + mensajes["errores"] + mensajes["pendientes"]
    assert total == mensajes["recibidos"]


def test_casos_de_ejemplo_sin_datos_personales() -> None:
    """Un caso solo trae id, motivo, semáforo, estado y fecha."""
    casos = leer_ejemplo()["casos"]
    assert casos["lista"], "el ejemplo debe tener casos para revisar la tabla"
    for caso in casos["lista"]:
        assert set(caso) == CAMPOS_CASO
        assert caso["semaforo"] in {"verde", "amarillo", "rojo"}
        assert caso["motivo"] in {"semaforo_rojo", "solicitud_usuario"}
    pendientes = [c for c in casos["lista"] if c["estado"] == "pendiente"]
    assert len(pendientes) == casos["pendientes"]


def test_latencia_de_ejemplo_por_flujo_y_cache_aparte() -> None:
    """Los flujos son los del diseño, p50 <= p95 y la caché va en su bloque."""
    datos = leer_ejemplo()
    for bloque in ("latencia", "latencia_cache"):
        assert set(datos[bloque]) <= FLUJOS
        for medida in datos[bloque].values():
            assert set(medida) == CAMPOS_LATENCIA
            assert medida["p50_ms"] <= medida["p95_ms"]
            assert medida["suficiente"] == (medida["n"] >= 30)
    assert any(not m["suficiente"] for m in datos["latencia"].values())


def test_ejemplo_no_trae_telefonos_ni_textos() -> None:
    """El resumen no tiene números de teléfono ni campos de texto libre."""
    crudo = EJEMPLO.read_text(encoding="utf-8")
    assert not re.search(r"\+?57\s?3\d{9}|\b3\d{9}\b", crudo)
    for prohibido in ('"nombre"', '"numero"', '"telefono"', '"texto"', '"mensaje"'):
        assert prohibido not in crudo, prohibido


def test_vista_pide_solo_operacion() -> None:
    """La vista usa el contrato y no hace peticiones ni escrituras propias."""
    codigo = leer_vista()
    assert 'estado.pedir("operacion")' in codigo
    assert codigo.count("estado.pedir(") == 1
    for prohibido in ("fetch(", "innerHTML", "localStorage", "sessionStorage", "cuerpo:"):
        assert prohibido not in codigo, prohibido


def test_vista_explica_estados_vacios_y_muestra_insuficiente() -> None:
    """Sin canal, sin casos o sin medidas lo dice; con n < 30 no es concluyente."""
    codigo = leer_vista()
    assert "El canal todavía no está configurado" in codigo
    assert "No hay casos esperando a un asesor." in codigo
    assert "Aún no hay mediciones" in codigo
    assert "Muestra insuficiente" in codigo
    assert "const MINIMO_CORRIDAS = 30;" in codigo
    assert '"Con caché (aparte)"' in codigo


def test_cifra_ausente_no_se_muestra_como_cero() -> None:
    """Un valor que falta se pinta como «—», no como 0."""
    codigo = leer_vista()
    assert 'Number.isFinite(valor) ? formatearEntero(valor) : "—"' in codigo


def test_estilos_de_operacion_usan_variables_y_su_prefijo() -> None:
    """El bloque usa solo variables de la base y clases ``.operacion``."""
    sin_comentarios = re.sub(r"/\*.*?\*/", "", bloque_css(), flags=re.DOTALL)
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b", sin_comentarios)
    assert not re.search(r"\b(rgba?|hsla?)\(", sin_comentarios)
    for selector in re.findall(r"([^{}]+)\{", sin_comentarios):
        for parte in selector.split(","):
            limpio = parte.strip()
            if limpio and not limpio.startswith("@"):
                assert limpio.startswith(".operacion"), limpio
