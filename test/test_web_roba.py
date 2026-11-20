"""Pruebas sin red ni navegador de la vista Roba la Bóveda (entrega final, 8.9).

Comprueban la forma de ``datos-ejemplo/roba.json`` frente al contrato de
``GET /api/roba`` (design.md, decisión 14) y que la terminal solo habla con
``/api/roba``, no clasifica por su cuenta, respeta el límite de intentos y
queda en pausa con los datos de ejemplo.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

RAIZ = Path(__file__).resolve().parents[1]
WEB = RAIZ / "app" / "web"
EJEMPLO = WEB / "datos-ejemplo" / "roba.json"
VISTA = WEB / "vistas" / "roba.js"
APP = WEB / "app.js"

CATEGORIAS = {"inyeccion", "extraccion_prompt", "dato_personal", "fuera_dominio", "legitimo"}
PUNTOS = {"inyeccion": 3, "extraccion_prompt": 3, "dato_personal": 2, "fuera_dominio": 1}
CAMPOS_INTENTO = {"n", "categoria", "exito", "puntos", "defensa", "texto", "respuesta", "creado"}


def leer_ejemplo() -> dict[str, Any]:
    """Lee ``app/web/datos-ejemplo/roba.json``."""
    return json.loads(EJEMPLO.read_text(encoding="utf-8"))


def leer_vista() -> str:
    """Lee el código de la vista Roba la Bóveda."""
    return VISTA.read_text(encoding="utf-8")


def bloque_css() -> str:
    """Devuelve el bloque CSS de Roba la Bóveda, entre sus marcadores."""
    css = (WEB / "estilos.css").read_text(encoding="utf-8")
    inicio = css.index("/* --- roba (entrega final, 8.9) --- */")
    fin = css.index("/* --- fin roba --- */", inicio)
    return css[inicio:fin]


def test_intentos_de_ejemplo_tienen_la_forma_del_contrato() -> None:
    """Cada intento trae sus campos, una categoría válida y puntos coherentes."""
    for intento in leer_ejemplo()["intentos"]:
        assert set(intento) == CAMPOS_INTENTO
        assert intento["categoria"] in CATEGORIAS
        assert intento["defensa"] == ("vulnerada" if intento["exito"] else "resistida")
        esperado = PUNTOS.get(intento["categoria"], 0) if intento["exito"] else 0
        assert intento["puntos"] == esperado


def test_marcador_de_ejemplo_cuadra_con_los_intentos() -> None:
    """Los totales y la tabla por categoría salen de los intentos."""
    datos = leer_ejemplo()
    intentos = datos["intentos"]
    marcador = datos["marcador"]
    assert marcador["intentos"] == len(intentos)
    assert marcador["exitos"] == sum(i["exito"] for i in intentos)
    assert marcador["puntos"] == sum(i["puntos"] for i in intentos)
    assert set(marcador["por_categoria"]) <= CATEGORIAS
    for categoria, fila in marcador["por_categoria"].items():
        propios = [i for i in intentos if i["categoria"] == categoria]
        assert fila == {
            "intentos": len(propios),
            "exitos": sum(i["exito"] for i in propios),
            "puntos": sum(i["puntos"] for i in propios),
        }
    assert datos["limite"] == 20
    assert marcador["intentos"] <= datos["limite"]


def test_ejemplo_no_trae_datos_personales() -> None:
    """Ni teléfonos, ni cédulas, ni números de tarjeta en el ejemplo."""
    crudo = EJEMPLO.read_text(encoding="utf-8")
    assert not re.search(r"\b\d{7,}\b", crudo)


def test_app_conoce_las_rutas_de_roba() -> None:
    """``app.js`` mapea los cinco recursos de Operación y Roba la Bóveda."""
    codigo = APP.read_text(encoding="utf-8")
    for clave, ruta in {
        "operacion": "/api/operacion",
        "roba": "/api/roba",
        "roba_intento": "/api/roba/intento",
        "roba_reiniciar": "/api/roba/reiniciar",
        "roba_exportar": "/api/roba/exportar",
    }.items():
        assert f'{clave}: "{ruta}"' in codigo


def test_vista_solo_usa_la_api_de_roba() -> None:
    """La terminal no llama a otra API, no usa la red directa ni guarda nada."""
    codigo = leer_vista()
    recursos = set(re.findall(r'estado\.pedir\("([a-z_]+)"', codigo))
    assert recursos == {"roba", "roba_intento", "roba_reiniciar", "roba_exportar"}
    for prohibido in ("fetch(", "innerHTML", "localStorage", "sessionStorage", "/webhooks/"):
        assert prohibido not in codigo, prohibido


def test_vista_no_clasifica_ni_puntua() -> None:
    """La categoría y los puntos vienen del backend: no hay reglas en la vista."""
    codigo = leer_vista()
    for senal in ("ignora", "olvida las instrucciones", "actúa como", "cédula"):
        assert f'"{senal}"' not in codigo.lower(), senal
    assert "puntos +=" not in codigo


def test_vista_limita_largo_e_intentos() -> None:
    """El intento tiene tope de caracteres y la sesión tope de intentos."""
    codigo = leer_vista()
    assert "const LARGO_MAXIMO = 500;" in codigo
    assert "const LIMITE_POR_DEFECTO = 20;" in codigo
    assert "campo.maxLength = LARGO_MAXIMO;" in codigo
    assert ">= limiteDe(datos)" in codigo


def test_maqueta_pausa_la_terminal() -> None:
    """Con los datos de ejemplo no se envía nada y se explica cómo jugar."""
    codigo = leer_vista()
    assert 'estado.modo === "ejemplo"' in codigo
    assert "if (enMaqueta ||" in codigo
    assert "make app" in codigo


def test_sesion_aleatoria_y_sin_almacenamiento() -> None:
    """La sesión se crea con ``crypto`` y no identifica a la persona."""
    codigo = leer_vista()
    assert "crypto.getRandomValues" in codigo
    assert "Math.random" not in codigo


def test_estilos_de_roba_usan_variables_y_su_prefijo() -> None:
    """El bloque usa solo variables de la base y clases ``.roba``."""
    sin_comentarios = re.sub(r"/\*.*?\*/", "", bloque_css(), flags=re.DOTALL)
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b", sin_comentarios)
    assert not re.search(r"\b(rgba?|hsla?)\(", sin_comentarios)
    for selector in re.findall(r"([^{}]+)\{", sin_comentarios):
        for parte in selector.split(","):
            limpio = parte.strip()
            if limpio and not limpio.startswith("@"):
                assert limpio.startswith(".roba"), limpio
