"""Pruebas sin red del grafo: rutas, memoria, reformulación y Tablero."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_core.messages.utils import count_tokens_approximately

from banco_occidente_corpus.asistente.contexto_prompt import CanalOficial
from banco_occidente_corpus.asistente.validacion import respuesta_sin_datos
from banco_occidente_corpus.boveda.tipos import Fragmento
from banco_occidente_corpus.sucursal.digiturno import ContadorTurnos
from banco_occidente_corpus.sucursal.grafo import (
    DependenciasGrafo,
    crear_grafo,
    es_seguimiento,
    recortar_historial,
    responder_turno,
)
from banco_occidente_corpus.tablero.tipos import Fila, leer_filas

URL = "https://www.bancodeoccidente.com.co/tarifas"
URL_CANAL = "https://www.bancodeoccidente.com.co/ayuda/linea-servicio-cliente"
ARCHIVO_TABLERO = Path(__file__).resolve().parents[1] / "data/estructurados/tablero.csv"


class RecuperadorFalso:
    """Recuperador en memoria que devuelve fragmentos fijos."""

    def __init__(self, fragmentos: list[Fragmento]) -> None:
        self._fragmentos = fragmentos
        self.consultas: list[str] = []

    def buscar(self, consulta: str, k: int = 5) -> list[Fragmento]:
        """Devuelve los fragmentos configurados."""
        self.consultas.append(consulta)
        return self._fragmentos[:k]


class ModeloEspia:
    """Modelo falso que registra los mensajes y devuelve respuestas en orden."""

    def __init__(self, respuestas: list[str]) -> None:
        self.respuestas = list(respuestas)
        self.llamadas: list[list[BaseMessage]] = []

    def invoke(self, mensajes: list[BaseMessage], **opciones: Any) -> AIMessage:
        """Registra la llamada y devuelve la siguiente respuesta."""
        self.llamadas.append(list(mensajes))
        return AIMessage(content=self.respuestas.pop(0))


class ModeloRoto:
    """Modelo que siempre falla."""

    def invoke(self, mensajes: list[BaseMessage], **opciones: Any) -> AIMessage:
        """Lanza un error de red simulado."""
        raise RuntimeError("sin red")


def fragmento(texto: str = "La cuota de manejo es de $16.700.") -> Fragmento:
    """Fragmento de prueba con la URL del tarifario."""
    return Fragmento(
        id="frag:1",
        texto=texto,
        url=URL,
        titulo="Tarifas",
        seccion="oferta",
        encabezado="Tarjetas",
        tipo="pagina",
        tokens=20,
    )


def fila(
    concepto: str,
    valor: str = "16.700",
    *,
    moneda: str = "COP",
    periodicidad: str = "mensual",
    fuente: str = URL,
    categoria: str = "tarifas",
) -> Fila:
    """Fila del Tablero para las pruebas."""
    return Fila(
        concepto=concepto,
        categoria=categoria,
        valor=valor,
        moneda=moneda,
        recargos="",
        periodicidad=periodicidad,
        vigente_desde="2025-11-20",
        origen="tarifario",
        pagina="data/gold/documents/tarifas.md",
        fuente=fuente,
    )


def canal() -> CanalOficial:
    """Canal oficial de prueba."""
    return CanalOficial(
        url=URL_CANAL,
        telefono="018000 514652",
        telefonos=("018000514652",),
    )


def deps(
    tmp_path: Path,
    *,
    modelo: Any,
    filas: list[Fila] | None = None,
    fragmentos: list[Fragmento] | None = None,
) -> tuple[Any, DependenciasGrafo]:
    """Crea el grafo y sus dependencias sobre una SQLite temporal."""
    dependencias = DependenciasGrafo(
        recuperador=RecuperadorFalso(fragmentos or []),
        filas=filas or [],
        modelo=modelo,
        canal=canal(),
        contador=ContadorTurnos(),
    )
    grafo = crear_grafo(dependencias, tmp_path / "memoria.sqlite")
    return grafo, dependencias


def respuesta_valida() -> str:
    """Respuesta del modelo que cita el fragmento y lista su fuente."""
    return f"La cuota de manejo es de $16.700 [1].\n\nFuentes:\n- {URL}"


def test_pregunta_autonoma_va_a_boveda(tmp_path: Path) -> None:
    """Sin historial ni seguimiento, la pregunta va a Bóveda y se redacta."""
    modelo = ModeloEspia([respuesta_valida()])
    grafo, dependencias = deps(tmp_path, modelo=modelo, fragmentos=[fragmento()])

    estado = responder_turno(grafo, dependencias, "¿Qué es la cuenta de ahorros?", "t1")

    assert estado["turno"]["letra"] == "B"
    assert estado["respuesta"].startswith("La cuota de manejo")
    assert estado["fuentes"] == [URL]
    assert estado["uso"]["uso_modelo"] is True
    assert len(modelo.llamadas) == 1


def test_tablero_con_una_a_tres_filas_no_usa_modelo(tmp_path: Path) -> None:
    """Una fila del Tablero se responde con plantilla y costo cero."""
    modelo = ModeloEspia([])
    grafo, dependencias = deps(
        tmp_path, modelo=modelo, filas=[fila("Cuota de manejo tarjeta débito")]
    )

    estado = responder_turno(grafo, dependencias, "cuota de manejo", "t1")

    assert estado["turno"]["letra"] == "T"
    assert "16.700" in estado["respuesta"]
    assert estado["uso"] == {"uso_modelo": False, "costo_usd": 0.0}
    assert modelo.llamadas == []
    assert estado["fuentes"] == [URL]


def test_tablero_sin_filas_pasa_a_boveda(tmp_path: Path) -> None:
    """Si el Tablero no encuentra filas, la ruta sigue en Bóveda."""
    modelo = ModeloEspia([respuesta_valida()])
    grafo, dependencias = deps(tmp_path, modelo=modelo, filas=[], fragmentos=[fragmento()])

    estado = responder_turno(grafo, dependencias, "cuota de manejo", "t1")

    assert estado["turno"]["letra"] == "B"
    assert estado["turno"]["motivo"] == "tablero_sin_filas"
    assert len(modelo.llamadas) == 1


def test_tablero_con_muchas_filas_pasa_a_boveda(tmp_path: Path) -> None:
    """Cuatro o más filas se consideran ambiguas y responden por Bóveda."""
    modelo = ModeloEspia([respuesta_valida()])
    filas = [fila(f"Cuota de manejo franquicia {indice}") for indice in range(4)]
    grafo, dependencias = deps(tmp_path, modelo=modelo, filas=filas)

    estado = responder_turno(grafo, dependencias, "cuota de manejo", "t1")

    assert estado["turno"]["letra"] == "B"
    assert estado["turno"]["motivo"] == "tablero_ambigua"


def test_tablero_con_cuatro_filas_del_mismo_concepto_no_usa_modelo(tmp_path: Path) -> None:
    """Varias filas del mismo producto se responden con una tabla, sin modelo."""
    modelo = ModeloEspia([])
    filas = [
        fila("Gastos médicos (Mastercard)", "2.000"),
        fila("Gastos médicos (Mastercard)", "2.500"),
        fila("Gastos médicos (Visa)", "2.000"),
        fila("Gastos médicos (Visa)", "2.500"),
    ]
    grafo, dependencias = deps(tmp_path, modelo=modelo, filas=filas)

    estado = responder_turno(grafo, dependencias, "cobertura de gastos médicos", "t1")

    assert estado["turno"]["letra"] == "T"
    assert "2.000" in estado["respuesta"]
    assert estado["uso"] == {"uso_modelo": False, "costo_usd": 0.0}
    assert modelo.llamadas == []


def test_tablero_limita_las_filas_del_mismo_concepto(tmp_path: Path) -> None:
    """Más de diez filas del mismo producto ya no se vuelcan en una tabla."""
    modelo = ModeloEspia([respuesta_valida()])
    filas = [fila("Gastos médicos (Visa)", str(1_000 + indice)) for indice in range(11)]
    grafo, dependencias = deps(tmp_path, modelo=modelo, filas=filas, fragmentos=[fragmento()])

    estado = responder_turno(grafo, dependencias, "cobertura de gastos médicos", "t1")

    assert estado["turno"]["letra"] == "B"
    assert estado["turno"]["motivo"] == "tablero_ambigua"


def test_cuota_generica_de_tarjetas_pasa_a_boveda(tmp_path: Path) -> None:
    """La cuota de «las tarjetas de crédito» no se responde con una sola tarjeta."""
    modelo = ModeloEspia([respuesta_valida()])
    filas = [
        fila("Tarjeta Crédito Joven", "19.700"),
        fila("Cuota de Manejo Tarjeta Débito", "16.700"),
    ]
    grafo, dependencias = deps(tmp_path, modelo=modelo, filas=filas, fragmentos=[fragmento()])

    estado = responder_turno(
        grafo,
        dependencias,
        "¿Cuál es la cuota de manejo de las tarjetas de crédito?",
        "t1",
    )

    assert estado["turno"]["letra"] == "B"
    assert estado["turno"]["motivo"] == "tablero_generico"


def test_tablero_responde_la_black_con_su_propia_fila(tmp_path: Path) -> None:
    """«Black» se responde con la fila que menciona Black, no con la genérica."""
    modelo = ModeloEspia([])
    filas = [
        fila("Credencial Black*", "52.500"),
        fila("Pago Tarjeta de Crédito Credencial Mastercard", "3,5"),
    ]
    grafo, dependencias = deps(tmp_path, modelo=modelo, filas=filas)

    estado = responder_turno(
        grafo,
        dependencias,
        "¿Cuál es la cuota de manejo de la tarjeta Credencial Mastercard Black?",
        "t1",
    )

    assert estado["turno"]["letra"] == "T"
    assert "52.500" in estado["respuesta"]
    assert "3,5" not in estado["respuesta"]


def test_tablero_black_sin_fila_black_pasa_a_boveda(tmp_path: Path) -> None:
    """Si ninguna fila menciona Black, el Tablero no inventa una respuesta."""
    modelo = ModeloEspia([respuesta_valida()])
    filas = [fila("Pago Tarjeta de Crédito Credencial Mastercard", "3,5")]
    grafo, dependencias = deps(tmp_path, modelo=modelo, filas=filas, fragmentos=[fragmento()])

    estado = responder_turno(
        grafo,
        dependencias,
        "¿Cuál es la cuota de manejo de la tarjeta Credencial Mastercard Black?",
        "t1",
    )

    assert estado["turno"]["letra"] == "B"
    assert estado["turno"]["motivo"] == "tablero_sin_filas"


def test_pregunta_21_responde_por_tablero(tmp_path: Path) -> None:
    """Los nueve topes de gastos médicos se listan en una sola tabla."""
    grafo, dependencias = deps(tmp_path, modelo=ModeloEspia([]), filas=leer_filas(ARCHIVO_TABLERO))

    estado = responder_turno(
        grafo,
        dependencias,
        "¿Cuánto cubre la asistencia en viajes nacionales por gastos médicos "
        "por accidente o enfermedad?",
        "t1",
    )

    assert estado["turno"]["letra"] == "T"
    assert "2.000" in estado["respuesta"]


def test_pregunta_23_responde_por_tablero(tmp_path: Path) -> None:
    """Schengen se responde con sus topes en EUR, no con la tabla nacional."""
    grafo, dependencias = deps(tmp_path, modelo=ModeloEspia([]), filas=leer_filas(ARCHIVO_TABLERO))

    estado = responder_turno(
        grafo,
        dependencias,
        "¿Cuánto cubre la tarjeta de crédito por gastos médicos en países Schengen?",
        "t1",
    )

    assert estado["turno"]["letra"] == "T"
    assert "20.000" in estado["respuesta"]
    assert "EUR" in estado["respuesta"]


def test_rechazo_por_regla_no_llama_al_modelo(tmp_path: Path) -> None:
    """El saldo propio se rechaza con la frase fija, sin modelo."""
    modelo = ModeloEspia([])
    grafo, dependencias = deps(tmp_path, modelo=modelo)

    estado = responder_turno(grafo, dependencias, "¿cuál es el saldo de mi cuenta?", "t1")

    assert estado["turno"]["letra"] == "X"
    assert estado["respuesta"] == respuesta_sin_datos(dependencias.canal)
    assert estado["uso"]["uso_modelo"] is False
    assert modelo.llamadas == []


def test_pii_se_rechaza_antes_de_la_memoria(tmp_path: Path) -> None:
    """La PII no entra al checkpointer ni llama al modelo."""
    modelo = ModeloEspia([])
    grafo, dependencias = deps(tmp_path, modelo=modelo)

    estado = responder_turno(grafo, dependencias, "mi cédula 1234567890", "t1")

    assert estado["turno"]["letra"] == "X"
    assert estado["avisos"] == ["pii_bloqueada"]
    assert modelo.llamadas == []
    assert grafo.get_state({"configurable": {"thread_id": "t1"}}).values == {}


def test_seguimiento_reformula_con_el_historial(tmp_path: Path) -> None:
    """Un «¿Y cuánto cuesta?» se reformula antes de buscar en la Bóveda."""
    modelo = ModeloEspia(
        [
            respuesta_valida(),
            "¿Cuánto cuesta la cuota de manejo?",
            respuesta_valida(),
        ]
    )
    grafo, dependencias = deps(tmp_path, modelo=modelo, fragmentos=[fragmento()])

    responder_turno(grafo, dependencias, "¿Qué es la cuenta de ahorros?", "t1")
    estado = responder_turno(grafo, dependencias, "¿Y cuánto cuesta?", "t1")

    assert estado["reformulada"] == "¿Cuánto cuesta la cuota de manejo?"
    assert len(modelo.llamadas) == 3
    # La reformulación lleva el historial recortado y la pregunta original.
    contenidos = [str(mensaje.content) for mensaje in modelo.llamadas[1]]
    assert any("¿Qué es la cuenta de ahorros?" in contenido for contenido in contenidos)


def test_seguimiento_32_reformula_y_confirma_tablero(tmp_path: Path) -> None:
    """«¿Cuánto … usarla …?» se reconoce como seguimiento y confirma T."""
    modelo = ModeloEspia(
        ["¿Cuánto debo esperar para usar la Cuota Protegida si quedo desempleado?"]
    )
    filas = [
        fila("Desempleo", "30", categoria="cuota protegida"),
        fila("Enfermedades Graves", "90", categoria="cuota protegida"),
    ]
    grafo, dependencias = deps(tmp_path, modelo=modelo, filas=filas, fragmentos=[fragmento()])

    responder_turno(grafo, dependencias, "¿Qué es Cuota Protegida?", "t1")
    estado = responder_turno(
        grafo,
        dependencias,
        "¿Cuánto debo esperar para usarla si quedo desempleado?",
        "t1",
    )

    assert estado["turno"]["letra"] == "T"
    assert estado["reformulada"] == (
        "¿Cuánto debo esperar para usar la Cuota Protegida si quedo desempleado?"
    )
    assert "30" in estado["respuesta"]


def test_primer_turno_no_reformula(tmp_path: Path) -> None:
    """Sin historial, una pregunta corta no dispara el modelo de reformulación."""
    modelo = ModeloEspia([respuesta_valida()])
    grafo, dependencias = deps(tmp_path, modelo=modelo, fragmentos=[fragmento()])

    estado = responder_turno(grafo, dependencias, "¿Y la cuenta?", "t1")

    assert estado["reformulada"] == "¿Y la cuenta?"
    assert len(modelo.llamadas) == 1


def test_aislamiento_por_thread_id(tmp_path: Path) -> None:
    """Dos conversaciones no comparten el historial."""
    modelo = ModeloEspia([respuesta_valida(), respuesta_valida()])
    grafo, dependencias = deps(tmp_path, modelo=modelo, fragmentos=[fragmento()])

    responder_turno(grafo, dependencias, "¿Qué es la cuenta de ahorros?", "t1")
    responder_turno(grafo, dependencias, "¿Qué es la cuenta de ahorros?", "t2")

    estado_t1 = grafo.get_state({"configurable": {"thread_id": "t1"}}).values
    estado_t2 = grafo.get_state({"configurable": {"thread_id": "t2"}}).values
    assert len(estado_t1["messages"]) == 2
    assert len(estado_t2["messages"]) == 2


def test_error_del_modelo_cae_en_frase_fija(tmp_path: Path) -> None:
    """Si el modelo falla en redactar, el turno no rompe la conversación."""
    grafo, dependencias = deps(tmp_path, modelo=ModeloRoto(), fragmentos=[fragmento()])

    estado = responder_turno(grafo, dependencias, "¿Qué es la cuenta de ahorros?", "t1")

    assert estado["respuesta"] == respuesta_sin_datos(dependencias.canal)
    assert estado["avisos"] == ["error_modelo"]
    assert estado["uso"]["uso_modelo"] is False


def test_sin_modelo_responde_frase_fija(tmp_path: Path) -> None:
    """En modo sin modelo, el grafo responde la frase fija."""
    grafo, dependencias = deps(tmp_path, modelo=None, fragmentos=[fragmento()])

    estado = responder_turno(grafo, dependencias, "¿Qué es la cuenta de ahorros?", "t1")

    assert estado["avisos"] == ["sin_modelo"]


def test_recortar_historial_respeta_el_presupuesto() -> None:
    """El recorte deja el historial dentro del tope de tokens."""
    mensajes = [
        HumanMessage(content="palabra " * 200),
        AIMessage(content="respuesta " * 200),
        HumanMessage(content="otra pregunta corta"),
    ]

    recortados = recortar_historial(mensajes, 80)

    assert count_tokens_approximately(recortados) <= 80
    assert recortados[-1].content == "otra pregunta corta"


@pytest.mark.parametrize(
    ("pregunta", "esperado"),
    [
        ("¿Y cuánto cuesta?", True),
        ("y la tasa?", True),
        ("¿cuánto vale?", True),
        ("¿qué necesito para abrir una cuenta de nómina?", False),
        ("¿Cuánto debo esperar para usarla si quedo desempleado?", True),
        ("¿Qué es un CDT?", False),
        ("¿Cuál es la tasa del CDT?", False),
        ("¿Cómo abro una cuenta?", False),
    ],
)
def test_es_seguimiento(pregunta: str, esperado: bool) -> None:
    """Los prefijos y la longitud deciden si es un seguimiento."""
    assert es_seguimiento(pregunta) is esperado
