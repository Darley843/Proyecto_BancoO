"""Pruebas de `buscar_en_documentos` y `consultar_tarifas` (herramientas 17 y 18).

No usan red, Ollama ni DeepSeek: la búsqueda de la Bóveda se reemplaza por un
doble y el Tablero se arma con filas de prueba. Una prueba usa el
`data/estructurados/tablero.csv` versionado para fijar el hallazgo de «Tasas» y
comprueba que la herramienta no lo modifica.
"""

from __future__ import annotations

import hashlib
from typing import Any

import pytest
from pydantic import ValidationError

from banco_occidente_corpus.config import PROJECT_ROOT
from banco_occidente_corpus.mcp_servidor.conocimiento import (
    BuscarEnDocumentosEntrada,
    BuscarEnDocumentosSalida,
    ConsultarTarifasEntrada,
    ConsultarTarifasSalida,
    SobreError,
    buscar_en_documentos,
    consultar_tarifas,
    opciones_de_tasa,
    pregunta_generica,
)
from banco_occidente_corpus.tablero.tipos import Fila, leer_filas

#: Tablero versionado del repositorio.
TABLERO = PROJECT_ROOT / "data" / "estructurados" / "tablero.csv"
#: Fuente de las tasas de prueba.
FUENTE_TASAS = "https://www.bancodeoccidente.com.co/documents/d/guest/tasas-personas-bdo"
#: Vigencia de las tasas de prueba, como la escribe el Tablero.
VIGENCIA = "E.A., vigencia del 1 al 30 de noviembre de 2026"


def _tasa(concepto: str, producto: str, valor: str) -> Fila:
    """Fila de tasa como las que el Tablero toma de la tabla Gold."""
    return Fila(
        concepto=concepto,
        categoria=f"tasa de interés · {producto}",
        valor=valor,
        moneda="%",
        recargos="",
        periodicidad=VIGENCIA,
        vigente_desde="2026-11-01",
        origen="tasa",
        pagina="data/gold/tasas/tasas-personas-2026-11.jsonl",
        fuente=FUENTE_TASAS,
    )


def _tarifa(concepto: str, categoria: str, valor: str) -> Fila:
    """Fila del tarifario en pesos."""
    return Fila(
        concepto=concepto,
        categoria=categoria,
        valor=valor,
        moneda="COP",
        recargos="",
        periodicidad="",
        vigente_desde="2025-11-20",
        origen="tarifario",
        pagina="data/gold/documents/ver-tarifas-2025.md",
        fuente="https://www.bancodeoccidente.com.co/documents/d/guest/tarifas-persona-1",
    )


#: Catálogo de prueba con la fila que causó el hallazgo de «Tasas».
CATALOGO: tuple[Fila, ...] = (
    _tarifa("x tasa de mora/", "Penalización cheques impagados en el exterior", "360"),
    _tarifa("Cuota de Manejo Tarjeta Débito", "Tarjeta débito", "16.700"),
    _tasa("Libre inversión", "libre inversión", "20,56–28,17"),
    _tasa("Vivienda · Crédito hipotecario", "vivienda", "15,17–18,54"),
    _tasa("Vivienda · Leasing habitacional", "vivienda", "14,52–18,19"),
    _tasa("Tarjeta de crédito · Pesos", "tarjeta de crédito", "28,19"),
    _tasa("Tarjeta de crédito · Dólares", "tarjeta de crédito", "23,74"),
    _tasa("CDT · De $500 mil a $99 millones · 360 días (12 meses)", "cdt · 360 días", "11,80"),
)


# --- consultar_tarifas ------------------------------------------------------------


@pytest.mark.parametrize(
    ("consulta", "esperado"),
    [
        ("Tasas", "tasa"),
        ("tasa", "tasa"),
        ("tasas de interés", "tasa"),
        ("¿Cuál es la tasa del banco?", "tasa"),
        ("tarifas", "tarifa"),
        ("¿Cuánto cuesta?", "tarifa"),
        ("tasa de libre inversión", None),
        ("tasa de mora", None),
        ("cuota de manejo", None),
        ("tasa cdt 360 días", None),
        ("cuánto paga un CDT", None),
    ],
)
def test_pregunta_generica_distingue_si_falta_el_producto(
    consulta: str, esperado: str | None
) -> None:
    """Solo «tasa», «interés», «tarifa» o «costo», sin producto, es una pregunta genérica."""
    assert pregunta_generica(consulta) == esperado


def test_tasas_sin_producto_pide_el_producto_y_no_devuelve_una_fila_suelta() -> None:
    """El hallazgo de «Tasas»: ya no responde con la penalización de cheques."""
    resultado = consultar_tarifas(ConsultarTarifasEntrada(consulta="Tasas"), filas=CATALOGO)

    assert isinstance(resultado, ConsultarTarifasSalida)
    assert resultado.requiere_producto
    assert resultado.filas == []
    assert resultado.total == 0
    assert "producto" in (resultado.mensaje or "")
    assert [opcion.clave for opcion in resultado.opciones] == [
        "libre_inversion",
        "cdt",
        "vivienda",
        "tarjeta_credito",
    ]


def test_las_opciones_juntan_el_rango_y_no_mezclan_dolares() -> None:
    """Vivienda une sus dos filas, la tarjeta usa solo pesos y el CDT va sin rango."""
    opciones = {opcion.clave: opcion for opcion in opciones_de_tasa(CATALOGO)}

    assert opciones["libre_inversion"].rango == "20,56–28,17 % E.A."
    assert opciones["vivienda"].rango == "14,52–18,54 % E.A."
    assert opciones["tarjeta_credito"].rango == "28,19 % E.A."
    assert opciones["cdt"].rango is None
    assert "plazo" in (opciones["cdt"].nota or "")
    assert opciones["libre_inversion"].vigencia == "vigencia del 1 al 30 de noviembre de 2026"
    assert all(opcion.fuente == FUENTE_TASAS for opcion in opciones.values())


def test_tarifa_sin_servicio_pide_cual_sin_opciones() -> None:
    """«¿Cuánto cuesta?» no inventa una tarifa: pregunta de qué producto o servicio."""
    resultado = consultar_tarifas(
        ConsultarTarifasEntrada(consulta="¿Cuánto cuesta?"), filas=CATALOGO
    )

    assert isinstance(resultado, ConsultarTarifasSalida)
    assert resultado.requiere_producto
    assert resultado.opciones == []
    assert resultado.filas == []


def test_una_pregunta_con_producto_devuelve_su_fila_con_fuente() -> None:
    """Con el producto nombrado, la herramienta busca con la lógica del Tablero."""
    resultado = consultar_tarifas(
        ConsultarTarifasEntrada(consulta="tasa de libre inversión"), filas=CATALOGO
    )

    assert isinstance(resultado, ConsultarTarifasSalida)
    assert not resultado.requiere_producto
    assert [fila.concepto for fila in resultado.filas] == ["Libre inversión"]
    assert resultado.filas[0].fuente == FUENTE_TASAS


def test_el_producto_como_argumento_evita_la_pregunta_generica() -> None:
    """«tasa» con el producto aparte ya no es genérica: responde la fila del producto."""
    resultado = consultar_tarifas(
        ConsultarTarifasEntrada(consulta="tasa", producto="libre inversión"), filas=CATALOGO
    )

    assert isinstance(resultado, ConsultarTarifasSalida)
    assert not resultado.requiere_producto
    assert [fila.concepto for fila in resultado.filas] == ["Libre inversión"]


def test_sin_coincidencias_no_inventa_una_cifra() -> None:
    """Un servicio que no está en el Tablero devuelve cero filas y lo dice."""
    resultado = consultar_tarifas(
        ConsultarTarifasEntrada(consulta="seguro de mascotas"), filas=CATALOGO
    )

    assert isinstance(resultado, ConsultarTarifasSalida)
    assert resultado.filas == []
    assert resultado.total == 0
    assert resultado.mensaje


def test_sin_tablero_devuelve_el_sobre_de_error() -> None:
    """Un catálogo vacío no es «sin resultados»: es un Tablero que falta."""
    resultado = consultar_tarifas(ConsultarTarifasEntrada(consulta="cuota de manejo"), filas=[])

    assert isinstance(resultado, SobreError)
    assert resultado.ok is False
    assert resultado.codigo == "tablero_ausente"


@pytest.mark.parametrize(
    "datos",
    [
        {"consulta": "ta"},
        {"consulta": "cuota de manejo", "limite": 21},
        {"consulta": "cuota de manejo", "sql": "DROP TABLE"},
    ],
)
def test_la_entrada_del_tablero_se_valida(datos: dict[str, Any]) -> None:
    """Consulta muy corta, límite fuera de rango o un campo extra se rechazan."""
    with pytest.raises(ValidationError):
        ConsultarTarifasEntrada(**datos)


@pytest.mark.skipif(not TABLERO.exists(), reason="el Tablero versionado no está")
def test_tasas_con_el_tablero_real_no_responde_la_penalizacion_y_no_lo_modifica() -> None:
    """Con el CSV real, «Tasas» lista productos con rango y el archivo queda igual."""
    antes = hashlib.sha256(TABLERO.read_bytes()).hexdigest()

    resultado = consultar_tarifas(
        ConsultarTarifasEntrada(consulta="Tasas"), filas=leer_filas(TABLERO)
    )

    assert isinstance(resultado, ConsultarTarifasSalida)
    assert resultado.requiere_producto
    assert resultado.filas == []
    claves = [opcion.clave for opcion in resultado.opciones]
    assert claves[0] == "libre_inversion"
    assert "mora" not in str(resultado.model_dump()).lower()
    assert hashlib.sha256(TABLERO.read_bytes()).hexdigest() == antes


# --- buscar_en_documentos ---------------------------------------------------------


def _fragmento(posicion: int, puntaje: float, clave: str = "similitud_coseno") -> dict[str, Any]:
    """Fragmento como lo devuelve `buscar_en_boveda`."""
    return {
        "posicion": posicion,
        "id": f"frag-{posicion}",
        "texto": f"Texto del fragmento {posicion}.",
        "titulo": f"Página {posicion}",
        "url": f"https://www.bancodeoccidente.com.co/pagina-{posicion}",
        "fuente": f"https://www.bancodeoccidente.com.co/pagina-{posicion}",
        "seccion": "oferta",
        "encabezado": "",
        "tipo": "pagina",
        "tipo_puntaje": "bm25" if clave == "puntaje_bm25" else "coseno",
        clave: puntaje,
    }


def test_buscar_en_documentos_cita_titulo_url_y_puntaje() -> None:
    """La búsqueda híbrida vuelve con cada fragmento citado y el aviso de datos."""
    llamadas: list[tuple[str, int]] = []

    def buscar(pregunta: str, k: int) -> dict[str, Any]:
        llamadas.append((pregunta, k))
        return {
            "fragmentos": [_fragmento(1, 0.82), _fragmento(2, 0.71)],
            "respaldo": "hibrido",
            "tipo_puntaje": "coseno",
        }

    resultado = buscar_en_documentos(
        BuscarEnDocumentosEntrada(pregunta="¿Qué es la cuenta de ahorros?", k=2), buscar=buscar
    )

    assert isinstance(resultado, BuscarEnDocumentosSalida)
    assert llamadas == [("¿Qué es la cuenta de ahorros?", 2)]
    assert resultado.total == 2
    primero = resultado.fragmentos[0]
    assert primero.posicion == 1
    assert primero.puntaje == pytest.approx(0.82)
    assert primero.cita == "Página 1 — https://www.bancodeoccidente.com.co/pagina-1"
    assert resultado.tipo_puntaje == "coseno"
    assert "datos" in resultado.aviso


def test_el_respaldo_bm25_no_devuelve_fragmentos_sin_coincidencias() -> None:
    """Sin términos en común, BM25 rellena con fragmentos al azar: la herramienta los quita."""

    def buscar(pregunta: str, k: int) -> dict[str, Any]:
        return {
            "fragmentos": [
                _fragmento(1, 0.0, "puntaje_bm25"),
                _fragmento(2, 0.0, "puntaje_bm25"),
            ],
            "respaldo": "bm25",
            "tipo_puntaje": "bm25",
        }

    resultado = buscar_en_documentos(BuscarEnDocumentosEntrada(pregunta="xyzzy"), buscar=buscar)

    assert isinstance(resultado, BuscarEnDocumentosSalida)
    assert resultado.fragmentos == []
    assert resultado.total == 0
    assert resultado.respaldo == "bm25"
    assert resultado.mensaje


def test_un_error_de_la_boveda_vuelve_como_sobre_comun() -> None:
    """Sin índice, el agente recibe `ok: false` con código y mensaje, sin trazas."""

    def buscar(pregunta: str, k: int) -> dict[str, Any]:
        return {"error": {"codigo": "indice_ausente", "mensaje": "Ejecuta `make indice`."}}

    resultado = buscar_en_documentos(
        BuscarEnDocumentosEntrada(pregunta="¿Qué es un CDT?"), buscar=buscar
    )

    assert isinstance(resultado, SobreError)
    assert resultado.model_dump() == {
        "ok": False,
        "codigo": "indice_ausente",
        "mensaje": "Ejecuta `make indice`.",
    }


@pytest.mark.parametrize(
    "datos",
    [
        {"pregunta": ""},
        {"pregunta": "x" * 501},
        {"pregunta": "¿Qué es un CDT?", "k": 0},
        {"pregunta": "¿Qué es un CDT?", "k": 6},
        {"pregunta": "¿Qué es un CDT?", "ruta": "C:/secreto.txt"},
    ],
)
def test_la_entrada_de_documentos_se_valida(datos: dict[str, Any]) -> None:
    """Pregunta vacía o larga, k fuera de 1 a 5 o un campo extra se rechazan."""
    with pytest.raises(ValidationError):
        BuscarEnDocumentosEntrada(**datos)


def test_los_esquemas_no_aceptan_campos_extra() -> None:
    """Las cuatro clases públicas de entrada y salida declaran `extra="forbid"`."""
    for modelo in (
        BuscarEnDocumentosEntrada,
        BuscarEnDocumentosSalida,
        ConsultarTarifasEntrada,
        ConsultarTarifasSalida,
        SobreError,
    ):
        assert modelo.model_config.get("extra") == "forbid"
        assert modelo.model_json_schema()["additionalProperties"] is False
