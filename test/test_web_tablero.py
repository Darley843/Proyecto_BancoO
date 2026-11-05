"""Pruebas sin red ni navegador del Tablero de tasas de la sucursal (PR 15).

Comprueban las tareas 18.2 (estado vacío sin inventar valores) y 18.3 (la
vista muestra concepto, valor, moneda, periodicidad, vigencia, origen y fuente,
sin recalcular ni comparar filas). La 18.1 se completa al verificar contra
``/api/tablero?q=cuota`` cuando exista el CSV del PR 7 y la API del PR 10.
"""

from __future__ import annotations

import csv
import json
import re
from pathlib import Path
from typing import Any

import pytest

RAIZ = Path(__file__).resolve().parents[1]
WEB = RAIZ / "app" / "web"
EJEMPLO = WEB / "datos-ejemplo" / "tablero.json"
CSV = RAIZ / "data" / "estructurados" / "tablero.csv"
VISTA = WEB / "vistas" / "tablero.js"

COLUMNAS_CSV = (
    "concepto",
    "categoria",
    "valor",
    "moneda",
    "recargos",
    "periodicidad",
    "vigente_desde",
    "origen",
    "pagina",
    "fuente",
)


def leer_ejemplo() -> dict[str, Any]:
    """Lee ``app/web/datos-ejemplo/tablero.json``."""
    return json.loads(EJEMPLO.read_text(encoding="utf-8"))


def leer_csv() -> list[dict[str, str]]:
    """Lee las filas de ``data/estructurados/tablero.csv`` (el CSV del PR 7)."""
    with CSV.open(encoding="utf-8", newline="") as archivo:
        return list(csv.DictReader(archivo))


def lineas_de_gold(ruta: str) -> list[str]:
    """Devuelve las líneas de una página de Gold sin las negritas de Markdown."""
    texto = (RAIZ / ruta).read_text(encoding="utf-8")
    return [linea.replace("**", "") for linea in texto.splitlines()]


def leer_vista() -> str:
    """Lee el código de la vista Tablero."""
    return VISTA.read_text(encoding="utf-8")


def bloque_css() -> str:
    """Devuelve el bloque CSS del Tablero, entre sus marcadores."""
    css = (WEB / "estilos.css").read_text(encoding="utf-8")
    inicio = css.index("/* --- tablero (PR 15) --- */")
    fin = css.index("/* --- fin tablero --- */", inicio)
    return css[inicio:fin]


def test_filas_de_ejemplo_tienen_las_diez_columnas() -> None:
    """Cada fila trae exactamente las diez columnas del CSV, todas como texto."""
    datos = leer_ejemplo()
    assert datos["total"] == len(datos["filas"])
    assert len(datos["filas"]) >= 10
    for fila in datos["filas"]:
        assert tuple(fila) == COLUMNAS_CSV
        assert all(isinstance(valor, str) for valor in fila.values())
        assert fila["origen"] in {"tarifario", "tabla_web"}
        assert fila["moneda"] in {"COP", "USD", "EUR", "%"}
        assert fila["fuente"].startswith("https://")


def test_vigencia_de_ejemplo_es_fecha_iso_o_vacia() -> None:
    """La vigencia viene normalizada a ISO (``AAAA-MM-DD``) o vacía."""
    for fila in leer_ejemplo()["filas"]:
        assert fila["vigente_desde"] == "" or re.fullmatch(
            r"\d{4}-\d{2}-\d{2}", fila["vigente_desde"]
        )


@pytest.mark.parametrize("fila", leer_ejemplo()["filas"], ids=lambda fila: fila["concepto"])
def test_fila_de_ejemplo_es_identica_a_una_fila_del_csv(fila: dict[str, str]) -> None:
    """Cada fila de la maqueta es una copia exacta de una fila del CSV canónico.

    Así la maqueta muestra lo mismo que mostrará ``/api/tablero``: el mismo
    concepto, la misma categoría y la misma periodicidad (vacía si el CSV la deja
    vacía), sin textos «bonitos» ni datos que el corpus no sostiene.
    """
    assert fila in leer_csv()


@pytest.mark.parametrize("fila", leer_ejemplo()["filas"], ids=lambda fila: fila["concepto"])
def test_concepto_y_valor_estan_en_la_misma_linea_de_gold(fila: dict[str, str]) -> None:
    """El concepto y su valor aparecen juntos en una misma línea de su página de Gold.

    El valor se busca como número completo (``2.800`` no vale dentro de
    ``112.800``). Al concepto se le quitan los asteriscos de nota y la franquicia
    entre paréntesis que agrega el CSV, porque la página la pone en la columna.
    """
    pagina = (RAIZ / fila["pagina"]).read_text(encoding="utf-8")
    fuente = re.search(r"^fuente: (.+)$", pagina, re.MULTILINE)
    assert fuente is not None
    assert fuente.group(1).strip() == fila["fuente"]
    concepto = re.sub(r"\s*\((Visa|Mastercard)\)$", "", fila["concepto"]).rstrip("*")
    valor = re.compile(rf"(?<![\d.,]){re.escape(fila['valor'])}(?![\d.,])")
    assert any(concepto in linea and valor.search(linea) for linea in lineas_de_gold(fila["pagina"]))


def test_maqueta_no_repite_concepto_con_valores_distintos() -> None:
    """Si el CSV trae un concepto con varios valores (por categoría de tarjeta), no va a la maqueta.

    Una sola fila daría a entender una cobertura igual para todas las tarjetas.
    """
    valores: dict[tuple[str, str], set[str]] = {}
    for fila in leer_csv():
        valores.setdefault((fila["concepto"], fila["categoria"]), set()).add(fila["valor"])
    for fila in leer_ejemplo()["filas"]:
        assert valores[(fila["concepto"], fila["categoria"])] == {fila["valor"]}


def test_vista_consulta_la_api_con_q() -> None:
    """La vista envía ``q`` a ``/api/tablero`` y no hace peticiones propias."""
    codigo = leer_vista()
    assert 'estado.pedir("tablero", { consulta: { q } })' in codigo
    for prohibido in ("fetch(", "innerHTML", "localStorage", "sessionStorage", '"preguntar"'):
        assert prohibido not in codigo, prohibido


def test_vista_muestra_las_columnas_pedidas() -> None:
    """Están las columnas de la tarea 18.3 y la moneda va junto al valor."""
    codigo = leer_vista()
    for clave in (
        "concepto",
        "valor",
        "recargos",
        "periodicidad",
        "vigente_desde",
        "origen",
        "fuente",
    ):
        assert f'["{clave}",' in codigo, clave
    assert "fila.moneda" in codigo


def test_vista_no_recalcula_ni_inventa() -> None:
    """La vista no hace cuentas con los valores y muestra «—» si falta un dato."""
    codigo = leer_vista()
    for prohibido in ("parseFloat", "parseInt", "Number(fila", "toFixed", ".reduce(", "Math."):
        assert prohibido not in codigo, prohibido
    assert 'defecto = "—"' in codigo
    assert "no inventa cifras" in codigo


def test_vista_tiene_estado_vacio_y_error() -> None:
    """Hay estado vacío con la consulta, error con reintento y resumen accesible."""
    codigo = leer_vista()
    assert "No hay filas para «${q}»." in codigo
    assert "Reintentar" in codigo
    assert 'setAttribute("role", "alert")' in codigo
    assert 'setAttribute("aria-live", "polite")' in codigo


def test_filtro_local_solo_en_la_maqueta() -> None:
    """El filtro del navegador solo corre en modo de ejemplo; con la API filtra el servidor."""
    codigo = leer_vista()
    assert codigo.count("filtrarEnMaqueta(") == 2
    llamada = codigo.index("filtrarEnMaqueta(filas, q)")
    assert 'if (estado.modo === "ejemplo") {' in codigo[llamada - 120 : llamada]


def test_enlaces_de_fuente_validados() -> None:
    """La fuente solo se enlaza si es http/https y abre en otra pestaña sin ``opener``."""
    codigo = leer_vista()
    assert "esUrlSegura(url)" in codigo
    assert 'enlace.target = "_blank"' in codigo
    assert 'enlace.rel = "noopener noreferrer"' in codigo


def test_estilos_del_tablero_usan_variables_y_su_prefijo() -> None:
    """El bloque del Tablero usa solo variables de la base y clases ``.tablero``."""
    bloque = bloque_css()
    sin_comentarios = re.sub(r"/\*.*?\*/", "", bloque, flags=re.DOTALL)
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b", sin_comentarios)
    assert not re.search(r"\b(rgba?|hsla?)\(", sin_comentarios)
    for selector in re.findall(r"([^{}]+)\{", sin_comentarios):
        for parte in selector.split(","):
            limpio = parte.strip()
            if limpio and not limpio.startswith("@"):
                assert limpio.startswith(".tablero"), limpio


def test_porcentaje_va_despues_del_valor() -> None:
    """El CSV del PR 7 usa ``%`` como moneda en descuentos: se muestra ``17 %``."""
    codigo = leer_vista()
    assert 'if (moneda === "%") {' in codigo
    assert "return `${valor} %`;" in codigo
