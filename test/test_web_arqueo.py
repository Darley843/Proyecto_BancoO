"""Pruebas sin red ni navegador de la vista Arqueo (PR 18).

Comprueban la forma del reporte de ejemplo, que la vista sea de solo lectura,
que muestre la lectura del McNemar sin recalcularla, los estados «sin arqueo»
y «pendiente», el formato es-CO, las tablas accesibles y el prefijo CSS. No
fijan cifras exactas del ejemplo: solo sus claves y tipos.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

RAIZ = Path(__file__).resolve().parents[1]
WEB = RAIZ / "app" / "web"
EJEMPLO = WEB / "datos-ejemplo" / "arqueo.json"
REAL = RAIZ / "data" / "evaluacion" / "arqueo.json"
VISTA = WEB / "vistas" / "arqueo.js"


def leer_ejemplo() -> dict[str, Any]:
    """Lee ``app/web/datos-ejemplo/arqueo.json``."""
    return json.loads(EJEMPLO.read_text(encoding="utf-8"))


def leer_real() -> dict[str, Any]:
    """Lee ``data/evaluacion/arqueo.json``."""
    return json.loads(REAL.read_text(encoding="utf-8"))


def leer_vista() -> str:
    """Lee el código de la vista Arqueo."""
    return VISTA.read_text(encoding="utf-8")


def bloque_funcion(nombre: str) -> str:
    """Devuelve el bloque de una función de nivel superior de la vista."""
    codigo = leer_vista()
    inicio = codigo.index(f"function {nombre}(")
    fin = codigo.index("\n}\n", inicio) + 3
    return codigo[inicio:fin]


def bloque_css() -> str:
    """Devuelve el bloque CSS del Arqueo, entre sus marcadores."""
    css = (WEB / "estilos.css").read_text(encoding="utf-8")
    inicio = css.index("/* --- arqueo (PR 18) --- */")
    fin = css.index("/* --- fin arqueo --- */", inicio)
    return css[inicio:fin]


def test_ejemplo_envuelve_el_reporte_real_sin_detalle() -> None:
    """El ejemplo es el reporte real con la forma de ``/api/arqueo`` y sin ``detalle``."""
    ejemplo = leer_ejemplo()
    reporte = leer_real()

    assert set(ejemplo) == {"disponible", "datos", "error"}
    assert ejemplo["disponible"] is True
    assert ejemplo["error"] is None
    assert "detalle" not in ejemplo["datos"]
    assert set(ejemplo["datos"]) == set(reporte) - {"detalle"}


def test_ejemplo_mantiene_las_claves_del_contrato_sin_fijar_cifras() -> None:
    """Comprueba la forma del reporte, no sus valores concretos."""
    datos = leer_ejemplo()["datos"]

    assert isinstance(datos["recuperacion"], list)
    for configuracion in datos["recuperacion"]:
        assert {"etiqueta", "hit_at_5", "mrr"} <= set(configuracion)
    assert {"v1", "v2"} <= set(datos["evaluacion"])
    assert {"b", "c", "n", "p", "p_minimo", "alfa", "excluidos"} <= set(datos["mcnemar"])
    assert {"v1_usd", "v2_usd", "preguntas"} <= set(datos["costo"])
    assert {"preguntas", "con_fuente", "evaluables_b", "evaluables_t"} <= set(datos["conteos"])
    assert set(datos["preguntas_por_tipo"]) == {"alcance", "tabla", "seguimiento", "fuera"}


def test_vista_usa_el_contrato_y_no_hace_peticiones_propias() -> None:
    """La vista pide ``arqueo`` al estado compartido y no toca la red ni el HTML."""
    codigo = leer_vista()

    assert 'estado.pedir("arqueo")' in codigo
    for prohibido in (
        "fetch(",
        "innerHTML",
        "localStorage",
        "sessionStorage",
        "XMLHttpRequest",
        '"preguntar"',
    ):
        assert prohibido not in codigo, prohibido
    assert not re.search(r"""https?://""", codigo)


def test_vista_muestra_recuperacion_y_evaluacion() -> None:
    """Están las métricas de recuperación y la evaluación de las dos versiones."""
    codigo = leer_vista()

    for clave in ("hit_at_5", "mrr", "intervalo95", "exactitud", "citas_correctas"):
        assert clave in codigo, clave
    assert "Recuperación por configuración" in codigo
    assert "Evaluación v1 y v2" in codigo
    assert "Bóveda frente a Tablero" in codigo


def test_vista_muestra_mcnemar_v1_v2_con_sus_campos() -> None:
    """La tabla de McNemar incluye b, c, n, p, p mínimo, alfa y excluidos."""
    codigo = leer_vista()

    for campo in ("b", "c", "n", "p", "p_minimo", "alfa", "excluidos"):
        assert f"mcnemar.{campo}" in codigo, campo
    assert "McNemar v1 frente a v2" in codigo


def test_vista_lee_la_lectura_del_json_y_no_la_recalcula() -> None:
    """La lectura sale del JSON; si falta se muestra «—» y no se compara p con alfa."""
    codigo = leer_vista()

    assert "textoODefecto(mcnemar.lectura)" in codigo
    assert 'textoODefecto(valor, defecto = "—")' in codigo
    assert "_frase_mcnemar" not in codigo
    for prohibido in ("parseFloat", "parseInt", "toFixed", ".reduce(", "Math."):
        assert prohibido not in codigo, prohibido
    assert not re.search(
        r"\b(p|p_minimo|pMinimo)\b[^\n]*(?:[<>]=?|===?|!==?)[^\n]*\bal(?:fa|pha)\b",
        codigo,
    )
    assert not re.search(
        r"\bal(?:fa|pha)\b[^\n]*(?:[<>]=?|===?|!==?)[^\n]*\b(p|p_minimo|pMinimo)\b",
        codigo,
    )


def test_vista_tiene_el_estado_sin_arqueo() -> None:
    """Sin reporte se dice «sin arqueo» y no se presentan métricas vacías."""
    codigo = leer_vista()

    assert "Sin arqueo" in codigo
    assert "respuesta.disponible !== true" in codigo
    assert "no se muestran métricas vacías" in codigo


def test_vista_marca_pendiente_los_bloques_nulos() -> None:
    """Los bloques nulos del reporte se explican como pendientes."""
    codigo = leer_vista()

    assert "Pendiente: " in codigo
    assert "crearPendiente(" in codigo
    for bloque in ("evaluacion.v2", "sensibilidad", "uso.v2", "mcnemar_pesos"):
        assert bloque in codigo, bloque
    assert "valorOPendiente" in codigo


def test_vista_explica_que_el_costo_de_v2_es_una_cota_historica() -> None:
    """La nota de costo dice que las cifras de v2 se midieron antes del #93."""
    bloque = bloque_funcion("crearCosto")

    assert "antes del arreglo del #93" in bloque
    assert "cota inferior histórica" in bloque
    assert "tres llamadas del turno" in bloque


def test_vista_formatea_en_es_co_y_usa_tablas_accesibles() -> None:
    """Las cifras usan es-CO y cada tabla tiene caption y encabezados con scope."""
    codigo = leer_vista()

    assert 'toLocaleString("es-CO"' in codigo
    assert 'crearTexto("caption"' in codigo
    assert 'th.scope = "col"' in codigo
    assert 'th.scope = "row"' in codigo


def test_mcnemar_de_pesos_es_solo_tabla_y_explicacion_fija() -> None:
    """La comparación de pesos no calcula una frase: tabla y explicación fija."""
    bloque = bloque_funcion("crearComparacionPesos")

    assert "crearTabla(" in bloque
    assert "b cuenta los pares donde acierta la configuración por defecto" in bloque
    assert "Las demás configuraciones son exploratorias" in bloque
    assert "crearLectura(" not in bloque
    assert "lectura" not in bloque


def test_estilos_del_arqueo_usan_variables_prefijo_y_breakpoint() -> None:
    """El bloque CSS usa solo variables de la base, clases ``.arqueo`` y celular."""
    bloque = bloque_css()
    sin_comentarios = re.sub(r"/\*.*?\*/", "", bloque, flags=re.DOTALL)

    assert not re.search(r"#[0-9a-fA-F]{3,8}\b", sin_comentarios)
    assert not re.search(r"\b(rgba?|hsla?)\(", sin_comentarios)
    assert "@media (max-width: 600px)" in bloque
    for selector in re.findall(r"([^{}]+)\{", sin_comentarios):
        for parte in selector.split(","):
            limpio = parte.strip()
            if limpio and not limpio.startswith("@"):
                assert limpio.startswith(".arqueo"), limpio
