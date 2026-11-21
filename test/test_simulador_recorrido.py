"""Pruebas del recorrido de punta a punta del simulador (tarea 7.2, sin red).

El recorrido firma las conversaciones de las personas sintéticas, las entrega al
webhook real dentro del proceso y verifica lo que registra el enviador falso.
La tabla Gold se crea en un directorio temporal con las tasas de la vigencia
2026-11 y el comité usa un modelo que falla, así que la corrida no depende de
la red, de DeepSeek ni de la fecha del sistema.
"""

from __future__ import annotations

import os
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from langchain_core.messages import BaseMessage
from langchain_core.runnables import RunnableLambda

from banco_occidente_corpus.simulador.personas import (
    Esperado,
    Persona,
    SemaforoEsperado,
    cargar_personas,
)
from banco_occidente_corpus.simulador.recorrido import (
    RUTA_PERSONAS,
    ResultadoPersona,
    grafo_ruta_d,
    informe,
    main,
    recorrer,
)
from banco_occidente_corpus.tablero.tasas import FilaTasa, escribir_tabla

VIGENCIA_DESDE = date(2026, 11, 1)
VIGENCIA_HASTA = date(2026, 11, 30)
FECHA_CONSULTA = datetime(2026, 11, 16, 12, 0, tzinfo=UTC)
"""Fecha fija, dentro de la vigencia de la tabla de prueba."""

SHA_EJEMPLO = "989be43a0ed19eb33e2057cd01c1ae612b6f15544eaaf41af6348846a6ff1b7f"
FUENTE = "https://www.bancodeoccidente.com.co/documents/d/guest/tasas-personas-bdo"


def _fila(
    producto: str,
    desde: str,
    hasta: str,
    segmento: str | None = None,
    plazo_dias: int | None = None,
) -> FilaTasa:
    """Construye una fila de la tabla Gold de prueba.

    Args:
        producto: clave canónica del producto.
        desde: tasa E.A. mínima publicada.
        hasta: tasa E.A. máxima publicada.
        segmento: segmento del Tablero, si el producto tiene varios.
        plazo_dias: plazo del CDT en días, si el producto lo publica.

    Returns:
        La fila lista para escribir la tabla.
    """
    return FilaTasa(
        producto=producto,
        segmento=segmento,
        tipo_tasa="fija",
        plazo_dias=plazo_dias,
        tasa_ea_desde=Decimal(desde),
        tasa_ea_hasta=Decimal(hasta),
        vigencia_desde=VIGENCIA_DESDE,
        vigencia_hasta=VIGENCIA_HASTA,
        fuente=FUENTE,
        sha256_pdf=SHA_EJEMPLO,
        fecha_extraccion=VIGENCIA_DESDE,
    )


@pytest.fixture()
def raiz_tasas(tmp_path: Path) -> Path:
    """Crea una tabla Gold temporal con las tasas de la vigencia 2026-11."""
    carpeta = tmp_path / "gold"
    carpeta.mkdir()
    filas = [
        _fila("libre_inversion", "0.2056", "0.2817"),
        _fila("compra_cartera", "0.1746", "0.2817"),
        _fila("libranza", "0.1539", "0.2431", "Libre inversión"),
        _fila("libranza", "0.1471", "0.2343", "Compra de cartera"),
        _fila("vivienda", "0.1517", "0.1854", "Crédito hipotecario"),
        _fila("ahorro", "0.0001", "0.0001", "De 0 a $5.000.000"),
        _fila("ahorro", "0.0010", "0.0010", "De $100.000.001 a $3.000.000.000"),
        _fila("cdt", "0.0005", "0.0005", "$500M- $99 MM", 30),
        _fila("cdt", "0.1100", "0.1100", "$500M- $99 MM", 90),
        _fila("cdt", "0.1205", "0.1205", "$500M- $99 MM", 1080),
        _fila("cdt", "0.1215", "0.1215", "$500 MM - 10.000 MM", 1080),
    ]
    escribir_tabla(carpeta / "tasas-personas-2026-11.jsonl", filas)
    return carpeta


class ModeloQueFalla:
    """Modelo de prueba que siempre falla: el comité no se convoca."""

    def with_structured_output(self, schema: Any, **kwargs: Any) -> RunnableLambda:
        """Devuelve un runnable que falla al invocarse.

        Args:
            schema: esquema Pydantic de salida; no se usa.
            **kwargs: argumentos de LangChain; no se usan.

        Returns:
            El runnable que lanza el error del proveedor.
        """

        def invocar(_mensajes: list[BaseMessage]) -> dict[str, Any]:
            """Simula la caída del modelo del comité."""
            raise RuntimeError("proveedor caído")

        return RunnableLambda(invocar)


def _recorrer(personas: tuple[Persona, ...], tmp_path: Path, raiz: Path) -> list[ResultadoPersona]:
    """Corre el recorrido en una carpeta nueva con la tabla y la fecha de prueba."""
    carpeta = tmp_path / "canal"
    carpeta.mkdir()
    return recorrer(
        personas,
        carpeta,
        modelo=ModeloQueFalla(),
        hoy=FECHA_CONSULTA,
        raiz=raiz,
    )


def test_todas_las_personas_pasan_el_recorrido(tmp_path: Path, raiz_tasas: Path) -> None:
    """Las seis personas reciben su resultado, una respuesta por turno y sin número."""
    personas = cargar_personas(RUTA_PERSONAS)

    resultados = _recorrer(personas, tmp_path, raiz_tasas)

    assert [resultado.persona for resultado in resultados] == [p.id for p in personas]
    assert all(resultado.ok for resultado in resultados), [
        (resultado.persona, resultado.fallas) for resultado in resultados if not resultado.ok
    ]
    obtenidos = {resultado.persona: resultado.obtenido for resultado in resultados}
    assert obtenidos["empleada_verde"] == "verde"
    assert obtenidos["pensionado_amarillo"] == "amarillo"
    assert obtenidos["independiente_rojo"] == "rojo"
    assert obtenidos["joven_ahorro"] == "ahorro"
    assert not any(resultado.comite for resultado in resultados)


def test_el_y_si_de_un_credito_trae_la_tarjeta(tmp_path: Path, raiz_tasas: Path) -> None:
    """Después del diagnóstico, el «¿Y si…?» de un crédito responde con tarjeta."""
    persona = next(p for p in cargar_personas(RUTA_PERSONAS) if p.id == "empleada_verde")

    (resultado,) = _recorrer((persona,), tmp_path, raiz_tasas)

    assert resultado.escenario == "tarjeta"


def test_un_semaforo_distinto_se_reporta_como_falla(tmp_path: Path, raiz_tasas: Path) -> None:
    """Si el guion espera otro color, el recorrido lo detecta y no pasa."""
    persona = next(p for p in cargar_personas(RUTA_PERSONAS) if p.id == "empleada_verde")
    alterada = persona.model_copy(
        update={
            "esperado": Esperado(
                semaforo=SemaforoEsperado.ROJO,
                deriva_asesor=False,
                nota="Esperado alterado para la prueba.",
            )
        }
    )

    (resultado,) = _recorrer((alterada,), tmp_path, raiz_tasas)

    assert not resultado.ok
    assert resultado.obtenido == "verde"
    assert any("se esperaba «rojo»" in falla for falla in resultado.fallas)


def test_el_recorrido_no_deja_el_secreto_en_el_entorno(
    tmp_path: Path, raiz_tasas: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """El App Secret ficticio solo vive durante el recorrido."""
    monkeypatch.delenv("WHATSAPP_APP_SECRET", raising=False)
    persona = next(p for p in cargar_personas(RUTA_PERSONAS) if p.id == "empleada_verde")

    _recorrer((persona,), tmp_path, raiz_tasas)

    assert "WHATSAPP_APP_SECRET" not in os.environ


def test_el_grafo_simulado_solo_abre_la_ruta_d_para_el_diagnostico() -> None:
    """La ruta D sale para «diagnóstico» o «me alcanza»; lo demás es texto fijo."""
    assert grafo_ruta_d("Hola, quiero hacer el diagnóstico", "wa:x", "p").es_diagnostico
    assert grafo_ruta_d("¿Me alcanza para un crédito?", "wa:x", "p").es_diagnostico
    assert not grafo_ruta_d("¿Cuál es la cuota de manejo?", "wa:x", "p").es_diagnostico


def test_el_informe_resume_y_lista_las_fallas() -> None:
    """El informe muestra una fila por persona y el detalle de las fallas."""
    resultados = [
        ResultadoPersona("empleada_verde", "verde", "verde", False, "tarjeta"),
        ResultadoPersona("independiente_rojo", "rojo", "amarillo", False, "tarjeta", ["x"]),
    ]

    texto = informe(resultados, con_clave=False)

    assert "sin DEEPSEEK_API_KEY" in texto
    assert "empleada_verde" in texto and "OK" in texto
    assert "independiente_rojo:" in texto and "  - x" in texto
    assert "Con fallas: 1 de 2 personas pasaron." in texto


def test_una_persona_desconocida_termina_con_codigo_2(capsys: pytest.CaptureFixture[str]) -> None:
    """``--solo`` con un id inexistente no corre nada y explica las opciones."""
    codigo = main(["--solo", "no_existe"])

    salida = capsys.readouterr().out
    assert codigo == 2
    assert "Personas desconocidas: no_existe" in salida
    assert "empleada_verde" in salida
