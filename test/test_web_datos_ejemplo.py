"""Pruebas sin red ni navegador de la app web de la sucursal (PR 12).

Comprueban la tarea 15.1 (armazón y seis vistas sin framework) y la forma de
los datos de ejemplo de la tarea 15.2 contra el contrato de ``design.md``.
Cuando el PR 10 publique los modelos Pydantic de la API, la comparación de
campos se hará contra esos modelos en lugar de las claves escritas aquí.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

from banco_occidente_corpus.sucursal.api import PreguntarRequest, PreguntarRespuesta

RAIZ = Path(__file__).resolve().parents[1]
WEB = RAIZ / "app" / "web"
DATOS = WEB / "datos-ejemplo"

VISTAS = ("vestibulo", "ventanilla", "boveda", "tablero", "camara", "arqueo")

# Claves de primer nivel de cada respuesta, copiadas del contrato "API JSON".
CONTRATO: dict[str, set[str]] = {
    "estado": {
        "modo_demo",
        "gasto_hoy_usd",
        "tope_usd",
        "indice_listo",
        "fragmentos_indexados",
        "modelo_embeddings",
    },
    "preguntar": {
        "turno",
        "turno_numero",
        "ruta",
        "motivo",
        "uso_modelo",
        "reformulada",
        "respuesta",
        "fuentes",
        "tokens_entrada",
        "tokens_salida",
        "tokens_cache",
        "costo_usd",
        "tiempo_s",
        "cache",
    },
    "tablero": {"filas", "total"},
    "mapa": {"puntos", "pregunta", "top"},
    "pipeline": {"etapas", "fuentes", "repeticiones", "indexacion"},
    "arqueo": {"disponible", "datos", "error"},
    "vestibulo": {"hitos"},
}

CAMPOS_FILA = {
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
}
CAMPOS_FRAGMENTO = {
    "id",
    "texto",
    "url",
    "titulo",
    "seccion",
    "encabezado",
    "tipo",
    "tokens",
    "puntaje",
}


def leer(nombre: str) -> Any:
    """Lee un archivo de ``datos-ejemplo/`` como JSON."""
    return json.loads((DATOS / f"{nombre}.json").read_text(encoding="utf-8"))


def leer_ventanilla() -> str:
    """Lee el código de la vista Ventanilla (PR 13)."""
    return (WEB / "vistas" / "ventanilla.js").read_text(encoding="utf-8")


def bloque_funcion_ventanilla(nombre: str) -> str:
    """Devuelve el bloque de una función de nivel superior de la Ventanilla."""
    codigo = leer_ventanilla()
    inicio = codigo.index(f"function {nombre}(")
    fin = codigo.index("\n}\n", inicio) + 3
    return codigo[inicio:fin]


def bloque_ventanilla() -> str:
    """Devuelve el bloque CSS de la Ventanilla, entre sus marcadores."""
    css = (WEB / "estilos.css").read_text(encoding="utf-8")
    inicio = css.index("/* --- ventanilla (PR 13) --- */")
    fin = css.index("/* --- fin ventanilla --- */", inicio)
    return css[inicio:fin]


@pytest.mark.parametrize("nombre", sorted(CONTRATO))
def test_datos_ejemplo_tienen_las_claves_del_contrato(nombre: str) -> None:
    """Cada archivo de ejemplo tiene exactamente las claves de su endpoint."""
    assert set(leer(nombre)) == CONTRATO[nombre]


def test_no_sobran_archivos_de_ejemplo() -> None:
    """Solo existen los siete archivos que pide la tarea 15.2."""
    assert {ruta.stem for ruta in DATOS.glob("*.json")} == set(CONTRATO)


def test_preguntar_usa_letras_y_rutas_validas() -> None:
    """El turno es B, T o X y la ruta es una de las tres del Digiturno."""
    datos = leer("preguntar")
    assert datos["turno"] in {"B", "T", "X"}
    assert datos["ruta"] in {"boveda", "tablero", "rechazo"}
    assert all(
        {"n", "titulo", "url", "seccion", "tipo", "similitud"} <= set(f) for f in datos["fuentes"]
    )


def test_tablero_tiene_filas_completas() -> None:
    """Cada fila trae todas las columnas del CSV y ``total`` coincide."""
    datos = leer("tablero")
    assert all(set(fila) == CAMPOS_FILA for fila in datos["filas"])
    assert datos["total"] == len(datos["filas"])


def test_mapa_tiene_coordenadas_entre_0_y_100() -> None:
    """Puntos y pregunta vienen normalizados de 0 a 100, como hace el servidor."""
    datos = leer("mapa")
    coordenadas = [*datos["puntos"], datos["pregunta"]]
    assert all(0 <= p["x"] <= 100 and 0 <= p["y"] <= 100 for p in coordenadas)
    assert all(set(f) == CAMPOS_FRAGMENTO for f in datos["top"])
    assert all(0 <= f["puntaje"] <= 1 for f in datos["top"])


def test_vistas_existen_y_exportan_render() -> None:
    """Hay un archivo por vista y cada uno exporta ``render``."""
    for vista in VISTAS:
        codigo = (WEB / "vistas" / f"{vista}.js").read_text(encoding="utf-8")
        assert "export async function render(contenedor, estado)" in codigo


def test_navegacion_lleva_a_las_seis_vistas() -> None:
    """``index.html`` tiene un enlace y un contenedor por cada vista."""
    html = (WEB / "index.html").read_text(encoding="utf-8")
    for vista in VISTAS:
        assert f'href="#{vista}"' in html
        assert f'id="vista-{vista}"' in html


def test_sin_librerias_externas_ni_html_inyectado() -> None:
    """No se carga nada desde internet y ningún archivo usa ``innerHTML``."""
    archivos = [WEB / "index.html", *WEB.rglob("*.js")]
    for archivo in archivos:
        texto = archivo.read_text(encoding="utf-8")
        assert not re.search(r"""(src|href)=["']https?://""", texto), archivo.name
        assert "innerHTML" not in texto, archivo.name


def test_funciones_javascript_documentadas() -> None:
    """Toda función de JavaScript va precedida de un comentario JSDoc."""
    patron = re.compile(r"^(export )?(async )?function \w+", re.MULTILINE)
    for archivo in WEB.rglob("*.js"):
        texto = archivo.read_text(encoding="utf-8")
        for coincidencia in patron.finditer(texto):
            previo = texto[: coincidencia.start()].rstrip()
            assert previo.endswith("*/"), f"{archivo.name}: {coincidencia.group(0)}"


def test_ventanilla_usa_el_contrato_y_el_hilo() -> None:
    """La Ventanilla envía pregunta y thread_id, y solo persiste el hilo."""
    codigo = leer_ventanilla()
    assert 'pedir("preguntar"' in codigo
    assert "pregunta" in codigo
    assert "thread_id" in codigo
    assert "sessionStorage" in codigo
    assert "crypto.randomUUID" in codigo
    assert 'CLAVE_HILO = "sucursal-ventanilla-hilo"' in codigo
    assert codigo.count("setItem(") == 1
    assert "localStorage" not in codigo
    assert "fetch(" not in codigo
    assert "innerHTML" not in codigo


def test_ventanilla_refresca_el_saldo_despues_de_responder() -> None:
    """Todo turno respondido refresca el saldo una sola vez, en `pedirTurno`."""
    codigo = leer_ventanilla()
    pedir = bloque_funcion_ventanilla("pedirTurno")
    enviar = bloque_funcion_ventanilla("enviarSecuencia")

    assert "await refrescarSaldo(app);" in pedir
    assert "await pedirTurno(" in enviar
    assert "refrescarSaldo" not in enviar
    assert codigo.count("await refrescarSaldo(") == 1
    for origen in (
        "void enviarSecuencia(preguntas);",
        "void enviarSecuencia([pregunta]);",
        "void enviarSecuencia([vista.preguntaParaReintentar]);",
    ):
        assert origen in codigo

    app = (WEB / "app.js").read_text(encoding="utf-8")
    assert "refrescarEstado," in app
    assert 'pedir("estado")' in app
    assert 'cache: "no-store"' in app


def test_ventanilla_tiene_los_ejemplos_y_los_estados() -> None:
    """Están los cuatro ejemplos, el seguimiento y los textos de estado."""
    codigo = leer_ventanilla()
    for pregunta in (
        "¿En qué año se fundó el Banco de Occidente?",
        "¿Cuánto cuesta la cuota de manejo de la tarjeta débito?",
        "¿Qué tarjetas Credencial Mastercard ofrece?",
        "¿Y cuánto cuesta la Black?",
        "¿En qué acciones me recomiendas invertir?",
    ):
        assert pregunta in codigo
    assert "Tomar turno" in codigo
    assert "Nueva conversación" in codigo
    assert "Atendiendo…" in codigo
    assert "Memoria: reformulada como" in codigo
    assert "formatearUsd" in codigo
    assert "crearTexto" in codigo
    assert "aria-live" in codigo
    assert 'setAttribute("role", "log")' in codigo
    assert 'setAttribute("role", "alert")' in codigo


def test_ventanilla_detecta_voz_y_microfono() -> None:
    """La voz y el dictado se ofrecen solo si el navegador los expone."""
    codigo = leer_ventanilla()
    assert "speechSynthesis" in codigo
    assert "SpeechSynthesisUtterance" in codigo
    assert "webkitSpeechRecognition" in codigo
    assert "window.SpeechRecognition" in codigo
    assert "return null" in codigo


def test_ventanilla_estilos_usan_variables() -> None:
    """El bloque de la Ventanilla usa variables y prefija sus selectores."""
    bloque = bloque_ventanilla()
    sin_comentarios = re.sub(r"/\*.*?\*/", "", bloque, flags=re.DOTALL)
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b", sin_comentarios)
    assert not re.search(r"\brgba?\(", sin_comentarios)
    assert not re.search(r"\bhsla?\(", sin_comentarios)
    for clase in (
        ".ventanilla__ticket--b",
        ".ventanilla__ticket--t",
        ".ventanilla__ticket--x",
        ".ventanilla__comprobante",
        ".ventanilla__similitud",
    ):
        assert clase in bloque
    assert "max-width: 900px" in bloque

    for selector in re.findall(r"([^{}]+)\{", sin_comentarios):
        for parte in selector.split(","):
            limpio = parte.strip()
            if limpio and not limpio.startswith("@"):
                assert ".ventanilla" in limpio, limpio


def test_preguntar_similitud_entre_0_y_1() -> None:
    """La similitud de cada fuente de ejemplo está en el rango del contrato."""
    for fuente in leer("preguntar")["fuentes"]:
        if fuente.get("similitud") is not None:
            assert 0 <= fuente["similitud"] <= 1


def test_preguntar_coincide_con_el_modelo_pydantic() -> None:
    """El ejemplo de la Ventanilla tiene los campos y tipos del modelo de la API."""
    datos = leer("preguntar")

    assert set(datos) == set(PreguntarRespuesta.model_fields)
    assert PreguntarRespuesta.model_validate(datos).model_dump() == datos


def test_preguntar_ejemplo_usa_los_valores_de_la_api() -> None:
    """El motivo es el del digiturno y el Tablero no aporta similitud."""
    datos = leer("preguntar")

    assert datos["motivo"] == "tarifas"
    assert all(fuente["similitud"] is None for fuente in datos["fuentes"])


def seccion_readme(titulo: str) -> str:
    """Devuelve el Markdown de una sección de nivel tres del README."""
    texto = (RAIZ / "README.md").read_text(encoding="utf-8")
    inicio = texto.index(f"### {titulo}")
    resto = texto[inicio + len(titulo) + 4 :]
    siguiente = resto.find("\n### ")
    return resto if siguiente == -1 else resto[:siguiente]


def bloques_json(seccion: str) -> list[Any]:
    """Extrae y parsea los bloques ```json de una sección del README."""
    return [json.loads(bloque) for bloque in re.findall(r"```json\n(.*?)\n```", seccion, re.DOTALL)]


def test_readme_documenta_preguntar_con_el_contrato() -> None:
    """El request y el response del README validan contra los modelos Pydantic."""
    bloques = bloques_json(seccion_readme("Preguntar"))

    assert len(bloques) == 2
    peticion, respuesta = bloques
    assert set(peticion) == set(PreguntarRequest.model_fields)
    PreguntarRequest.model_validate(peticion)
    assert set(respuesta) == set(PreguntarRespuesta.model_fields)
    assert set(respuesta) == set(leer("preguntar"))
    PreguntarRespuesta.model_validate(respuesta)
