"""Pruebas del servicio que consume la app (sin red).

Usan ``FakeListChatModel`` de ``langchain_core`` o un envoltorio minimo con la
misma interfaz: ninguna prueba construye un cliente real ni llama a DeepSeek.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langchain_core.runnables import RunnableLambda

from banco_occidente_corpus.asistente.contexto_prompt import ContextoPrompt, cargar_contexto
from banco_occidente_corpus.asistente.prompts import cargar_prompt
from banco_occidente_corpus.asistente.qa import responder
from banco_occidente_corpus.asistente.servicio import (
    PROMPT_SIN_MODELO,
    ResultadoFAQ,
    detectar_pii_pregunta,
    ejecutar_faq,
    ejecutar_pregunta,
    ejecutar_resumen,
    respuesta_pii,
)
from banco_occidente_corpus.asistente.validacion import FRASE_SIN_DATOS

URL_CANAL = "https://www.bancodeoccidente.com.co/ayuda/linea-servicio-cliente"
URL_CUENTA = "https://www.bancodeoccidente.com.co/personas/cuenta-ahorros"

CONTEXTO = """# Contexto del Banco de Occidente

Documento generado a partir de data/gold. No editar a mano: make contexto.

## Líneas de Servicio al Cliente Banco de Occidente
Fuente: https://www.bancodeoccidente.com.co/ayuda/linea-servicio-cliente
Sección: atencion

Línea Nacional: 018000 514652

## Cuenta de Ahorros
Fuente: https://www.bancodeoccidente.com.co/personas/cuenta-ahorros
Sección: oferta

Para abrir una cuenta de ahorros necesitas la cédula y un depósito inicial.
"""


@pytest.fixture
def contexto(tmp_path: Path) -> ContextoPrompt:
    """Contexto minimo con canal oficial y una pagina de oferta."""
    ruta = tmp_path / "contexto_banco.md"
    ruta.write_text(CONTEXTO, encoding="utf-8", newline="\n")
    return cargar_contexto(archivo=ruta)


@pytest.fixture
def prompt_qa():
    """Prompt de Q&A versionado en el repositorio."""
    return cargar_prompt("qa")


class ModeloProhibido:
    """Falla si el asistente intenta llamar al modelo."""

    def invoke(self, *args: object, **kwargs: object) -> object:
        """No debe usarse cuando la pregunta trae datos personales."""
        raise AssertionError("el modelo no debe invocarse con datos personales")


class ModeloEstructurado(FakeListChatModel):
    """Modelo falso que devuelve payloads Pydantic en orden."""

    payloads: list[dict[str, Any]]

    def with_structured_output(self, schema: Any, **_kwargs: Any) -> RunnableLambda:
        """Devuelve un runnable que valida el siguiente payload contra el esquema."""
        cola = iter(self.payloads)
        return RunnableLambda(lambda _: schema.model_validate(next(cola)))


def _modelo(respuesta: str) -> FakeListChatModel:
    """Modelo falso de langchain_core con una respuesta de texto."""
    return FakeListChatModel(responses=[respuesta])


def _payload_faq(total: int = 10) -> dict[str, Any]:
    """Payload valido de la FAQ para el modelo falso."""
    return {
        "preguntas": [
            {
                "pregunta": f"¿Cómo abro una cuenta de ahorros? ({indice})",
                "respuesta": (
                    "Puedes abrir una cuenta de ahorros con la cédula y un depósito inicial."
                ),
                "fuente": {"url": URL_CUENTA},
            }
            for indice in range(1, total + 1)
        ]
    }


# ---------------------------------------------------------------- Q&A


def test_ejecutar_pregunta_valida_y_mide_tiempo(contexto: ContextoPrompt) -> None:
    """La respuesta validada vuelve con su fuente y un tiempo positivo."""
    texto = f"Necesitas la cédula y un depósito inicial.\nFuente: {URL_CUENTA}"

    resultado = ejecutar_pregunta(_modelo(texto), "v1", "¿Qué necesito?", contexto=contexto)

    assert resultado.respuesta.sin_datos is False
    assert resultado.respuesta.fuente == URL_CUENTA
    assert resultado.prompt == "qa_v1"
    assert resultado.segundos >= 0.0
    assert resultado.respuesta.texto_crudo == texto


def test_ejecutar_pregunta_v0_conserva_el_texto_crudo(contexto: ContextoPrompt) -> None:
    """Con la linea base v0 la validacion sigue activa y el crudo se conserva."""
    crudo = "Necesitas la cédula y un depósito inicial."

    resultado = ejecutar_pregunta(_modelo(crudo), "v0", "¿Qué necesito?", contexto=contexto)

    assert resultado.prompt == "qa_v0"
    assert resultado.respuesta.sin_datos is True
    assert "fuente_invalida" in resultado.respuesta.avisos
    assert resultado.respuesta.texto_crudo == crudo
    assert FRASE_SIN_DATOS in resultado.respuesta.texto


# ---------------------------------------------------------------- PII previa


def test_detectar_pii_pregunta_marca_un_documento(contexto: ContextoPrompt) -> None:
    """Una cedula en la pregunta se detecta antes de llamar al modelo."""
    deteccion = detectar_pii_pregunta("Mi cédula es 1.234.567.890", contexto=contexto)

    assert deteccion is not None
    assert deteccion.categoria == "documento de identidad"


def test_detectar_pii_pregunta_permite_el_canal_publico(contexto: ContextoPrompt) -> None:
    """El telefono publico del contexto no se trata como dato personal."""
    assert detectar_pii_pregunta("¿Cuál es la línea 018000 514652?", contexto=contexto) is None


def test_detectar_pii_pregunta_vacia_no_falla(contexto: ContextoPrompt) -> None:
    """Sin texto no hay nada que detectar ni que enviar."""
    assert detectar_pii_pregunta("   ", contexto=contexto) is None


def test_respuesta_pii_no_invoca_el_modelo(contexto: ContextoPrompt) -> None:
    """El mensaje de proteccion se arma sin modelo y sin tiempo de generacion."""
    deteccion = detectar_pii_pregunta("Mi cédula es 1.234.567.890", contexto=contexto)
    assert deteccion is not None

    resultado = respuesta_pii(contexto, deteccion)

    assert resultado.prompt == PROMPT_SIN_MODELO
    assert resultado.segundos == 0.0
    assert resultado.respuesta.avisos == ("pii_bloqueada",)
    assert "Ley 1581" in resultado.respuesta.texto
    assert "1.234.567.890" not in resultado.respuesta.texto
    assert resultado.respuesta.fuente == URL_CANAL


def test_respuesta_pii_coincide_con_responder(contexto: ContextoPrompt, prompt_qa: Any) -> None:
    """La ruta de la app y la de responder() dan el mismo mensaje de proteccion."""
    pregunta = "Mi cédula es 1.234.567.890"
    deteccion = detectar_pii_pregunta(pregunta, contexto=contexto)
    assert deteccion is not None

    protegida = respuesta_pii(contexto, deteccion)
    esperada = responder(ModeloProhibido(), prompt_qa, contexto, pregunta)  # type: ignore[arg-type]

    assert protegida.respuesta.texto == esperada.texto
    assert protegida.respuesta.avisos == esperada.avisos
    assert protegida.respuesta.fuente == esperada.fuente


# ---------------------------------------------------------------- FAQ


def test_ejecutar_faq_usa_el_prompt_v1(contexto: ContextoPrompt) -> None:
    """FAQ usa siempre v1, sin importar la version elegida para Q&A."""
    modelo = ModeloEstructurado(responses=[""], payloads=[_payload_faq()])

    resultado: ResultadoFAQ = ejecutar_faq(modelo, contexto=contexto)

    assert resultado.prompt == "faq_v1"
    assert resultado.faq is not None
    assert len(resultado.faq.preguntas) == 10
    assert resultado.errores == ()
    assert resultado.segundos >= 0.0


def test_ejecutar_faq_invalida_devuelve_errores(contexto: ContextoPrompt) -> None:
    """Si la FAQ no cumple, el servicio devuelve errores en lugar de fallar."""
    modelo = ModeloEstructurado(responses=[""], payloads=[_payload_faq(total=9)])

    resultado = ejecutar_faq(modelo, contexto=contexto)

    assert resultado.faq is None
    assert resultado.errores
    assert resultado.prompt == "faq_v1"


# ---------------------------------------------------------------- resumen


def test_ejecutar_resumen_valido_conserva_fuentes(contexto: ContextoPrompt) -> None:
    """El resumen vuelve con sus fuentes y el tiempo medido."""
    texto = f"El banco ofrece cuentas de ahorro.\n\nFuentes:\n- {URL_CUENTA}"

    resultado = ejecutar_resumen(_modelo(texto), contexto=contexto)

    assert resultado.resumen is not None
    assert resultado.resumen.fuentes == (URL_CUENTA,)
    assert resultado.errores == ()
    assert resultado.prompt == "resumen_v1"
    assert resultado.segundos >= 0.0


def test_ejecutar_resumen_sin_fuentes_devuelve_errores(contexto: ContextoPrompt) -> None:
    """Sin bloque Fuentes: el servicio devuelve errores en lugar de fallar."""
    modelo = FakeListChatModel(responses=["Resumen sin fuentes.", "Resumen sin fuentes."])

    resultado = ejecutar_resumen(modelo, contexto=contexto)

    assert resultado.resumen is None
    assert resultado.errores
    assert resultado.prompt == "resumen_v1"
