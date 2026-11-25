"""Pruebas del comité de crédito, sin red y con modelos de prueba.

El motor real se ejecuta contra una tabla Gold temporal con las tasas de la
vigencia 2026-11, igual que en `test_diagnostico_motor.py`. Los agentes son
dobles que devuelven posturas fijas y cuentan las llamadas; así se comprueban
la síntesis, el tope de llamadas, el estrés que cambia la postura y el auditor
determinístico bajo ataque.
"""

from __future__ import annotations

import inspect
import json
import re
import threading
from collections.abc import Iterator, Mapping, Sequence
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from langchain_core.exceptions import OutputParserException
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.runnables import RunnableLambda

from banco_occidente_corpus.asistente.metricas import leer_uso
from banco_occidente_corpus.asistente.prompts import cargar_prompt
from banco_occidente_corpus.asistente.validacion import cifras_duras, detectar_pii
from banco_occidente_corpus.canal.contratos import EntradaDiagnostico, ResultadoDiagnostico
from banco_occidente_corpus.config import PROJECT_ROOT
from banco_occidente_corpus.diagnostico import comite as comite_mod
from banco_occidente_corpus.diagnostico import motor
from banco_occidente_corpus.diagnostico.comite import (
    CODIGOS_ESCENARIO,
    MENSAJE_PII,
    EscenarioComite,
    PosturaAgente,
    RegistroComite,
    auditar,
    auditar_texto,
    cargar_limites,
    construir_escenarios,
    deliberar,
)
from banco_occidente_corpus.tablero.tasas import FilaTasa, escribir_tabla

#: Personas sintéticas del Taller.
RUTA_PERSONAS = PROJECT_ROOT / "data" / "evaluacion" / "personas_sinteticas.json"
#: Vigencia de la tabla de prueba.
VIGENCIA_DESDE = date(2026, 11, 1)
VIGENCIA_HASTA = date(2026, 11, 30)
#: Fecha de consulta fija, dentro de la vigencia.
FECHA_CONSULTA = date(2026, 11, 16)
#: Huella del PDF de tasas de la vigencia.
SHA_EJEMPLO = "989be43a0ed19eb33e2057cd01c1ae612b6f15544eaaf41af6348846a6ff1b7f"
#: URL de la fuente de las tasas.
FUENTE = "https://www.bancodeoccidente.com.co/documents/d/guest/tasas-personas-bdo"
#: Prefijos que identifican una respuesta de la entrevista.
PREFIJOS = frozenset(
    {"objetivo", "vinculacion", "ingresos", "gastos", "cuotas", "cuota_trasladar", "monto", "plazo"}
)
#: Tareas de los tres prompts del comité.
TAREAS_COMITE = ("comite_riesgo", "comite_comercial", "comite_auditor")
#: Identificador o código interno que no debe llegar al texto de la persona.
CODIGO_INTERNO = re.compile(r"\b[a-z0-9]+(?:_[a-z0-9]+)+\b")


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
    filas = [
        _fila("libre_inversion", "0.2056", "0.2817"),
        _fila("compra_cartera", "0.1746", "0.2817"),
        _fila("libranza", "0.1539", "0.2431", "Libre inversión"),
        _fila("libranza", "0.1471", "0.2343", "Compra de cartera"),
        _fila("vivienda", "0.1517", "0.1854", "Crédito hipotecario"),
        _fila("ahorro", "0.0001", "0.0001", "De 0 a $5.000.000"),
        _fila("cdt", "0.0005", "0.0005", "$500M- $99 MM", 30),
    ]
    escribir_tabla(tmp_path / "tasas-personas-2026-11.jsonl", filas)
    return tmp_path


def _personas() -> dict[str, dict[str, Any]]:
    """Carga las personas sintéticas indexadas por su id.

    Returns:
        El diccionario persona por id.
    """
    datos = json.loads(RUTA_PERSONAS.read_text(encoding="utf-8"))
    return {persona["id"]: persona for persona in datos["personas"]}


def _ids(persona: dict[str, Any]) -> list[str]:
    """Extrae de los turnos los ids canónicos de la entrevista.

    Args:
        persona: persona sintética con su lista de turnos.

    Returns:
        Los ids elegidos, en el orden de la entrevista.
    """
    return [
        str(turno["valor"])
        for turno in persona["turnos"]
        if turno.get("tipo") in {"lista", "boton"}
        and str(turno["valor"]).split(".", 1)[0] in PREFIJOS
    ]


def _diagnostico(ident: str, raiz: Path) -> tuple[EntradaDiagnostico, ResultadoDiagnostico]:
    """Corre el camino completo de una persona sintética.

    Args:
        ident: id de la persona en el JSON.
        raiz: tabla Gold de prueba.

    Returns:
        La entrada y el resultado del motor real para esa persona.
    """
    persona = _personas()[ident]
    entrada = motor.entrada_desde_respuestas(_ids(persona))
    resultado = motor.calcular(entrada, hoy=FECHA_CONSULTA, raiz=raiz)
    return entrada, resultado


def _entrada_estres() -> EntradaDiagnostico:
    """Insumos de un independiente amarillo que el estrés vuelve negativo.

    Returns:
        Un crédito de libre inversión con capacidad de pago ajustada.
    """
    return EntradaDiagnostico.model_validate(
        {
            "producto": "libre_inversion",
            "vinculacion": "independiente",
            "ingreso_mensual": Decimal(2_500_000),
            "gastos_mensuales": Decimal(1_200_000),
            "cuotas_deudas": Decimal(500_000),
            "monto_credito": Decimal(10_000_000),
            "plazo_meses": 48,
        }
    )


def _postura(
    agente: str,
    postura: str,
    argumentos: Sequence[str] = (),
    evidencia: Sequence[str] = (),
) -> dict[str, Any]:
    """Arma el payload de una postura para el modelo de prueba.

    Args:
        agente: rol del comité.
        postura: texto de la postura.
        argumentos: frases del agente.
        evidencia: campos que respaldan los argumentos.

    Returns:
        El diccionario que valida el esquema.
    """
    return {
        "agente": agente,
        "postura": postura,
        "argumentos": list(argumentos),
        "evidencia": list(evidencia),
    }


def _error_400() -> RuntimeError:
    """Reproduce el 400 de DeepSeek contra ``tool_choice`` en modo pensamiento.

    Returns:
        Una excepción con el texto y el ``request_id`` que devuelve el proveedor.
    """
    return RuntimeError(
        "Error code: 400 - Thinking mode does not support this tool_choice "
        "(request_id=20261119-987654321)"
    )


def _error_longitud() -> BaseException:
    """Reproduce ``LengthFinishReasonError`` con la completion truncada.

    Returns:
        Una excepción con nombre de OpenAI, `finish_reason` y uso del caso real.
    """
    from types import SimpleNamespace

    completion = SimpleNamespace(
        choices=[SimpleNamespace(finish_reason="length")],
        usage=SimpleNamespace(
            prompt_tokens=500,
            completion_tokens=1_200,
            total_tokens=1_700,
            prompt_cache_hit_tokens=0,
            completion_tokens_details=SimpleNamespace(reasoning_tokens=1_200),
        ),
    )
    clase = type("LengthFinishReasonError", (RuntimeError,), {})
    error = clase("se agotó max_tokens")
    error.completion = completion  # type: ignore[attr-defined]
    return error


def _rol(sistema: str) -> str:
    """Deduce el rol del comité a partir del prompt del sistema.

    Args:
        sistema: contenido del mensaje del sistema.

    Returns:
        `riesgo`, `comercial` o `auditor`.
    """
    minusculas = sistema.casefold()
    for rol in ("riesgo", "comercial", "auditor"):
        if f"agente de {rol}" in minusculas or f"agente {rol}" in minusculas:
            return rol
    raise AssertionError(f"prompt sin rol reconocible: {sistema[:80]}")


class ModeloComite:
    """Modelo de prueba que devuelve posturas fijas y cuenta las llamadas."""

    def __init__(
        self,
        respuestas: Mapping[str, Sequence[Mapping[str, Any] | BaseException | None]],
    ) -> None:
        """Guarda la cola de respuestas por rol.

        Args:
            respuestas: payloads, excepciones o `None` por rol, en orden de uso.
                Un `None` simula un JSON inválido con `parsing_error`.
        """
        self._respuestas = {rol: list(valores) for rol, valores in respuestas.items()}
        self._candado = threading.Lock()
        self.llamadas: list[str] = []
        self.mensajes: list[str] = []
        self.mensajes_por_rol: dict[str, list[str]] = {}
        self.metodos: list[str] = []

    def with_structured_output(self, schema: Any, **kwargs: Any) -> RunnableLambda:
        """Devuelve un runnable que valida el siguiente payload del rol.

        Args:
            schema: esquema Pydantic de salida.
            **kwargs: argumentos de LangChain, incluido el método de salida.

        Returns:
            El runnable que responde como el agente.
        """
        self.metodos.append(str(kwargs.get("method", "")))

        def invocar(mensajes: Sequence[BaseMessage]) -> dict[str, Any]:
            """Selecciona la respuesta del rol y la valida contra el esquema."""
            sistema = str(mensajes[0].content)
            rol = _rol(sistema)
            with self._candado:
                self.llamadas.append(rol)
                self.mensajes.extend(str(mensaje.content) for mensaje in mensajes)
                self.mensajes_por_rol.setdefault(rol, []).append(str(mensajes[-1].content))
                cola = self._respuestas.get(rol, [])
                payload = cola.pop(0) if cola else _postura(rol, "abstencion")
            if isinstance(payload, BaseException):
                raise payload
            crudo = AIMessage(
                content="ok",
                usage_metadata={
                    "input_tokens": 100,
                    "output_tokens": 50,
                    "total_tokens": 150,
                },
            )
            if payload is None:
                return {
                    "raw": AIMessage(
                        content='{"agente": "riesgo", "postura"',
                        usage_metadata={
                            "input_tokens": 100,
                            "output_tokens": 3_000,
                            "total_tokens": 3_100,
                            "output_token_details": {"reasoning": 2_900},
                        },
                        response_metadata={"finish_reason": "length"},
                    ),
                    "parsed": None,
                    "parsing_error": OutputParserException("JSON truncado"),
                }
            return {
                "raw": crudo,
                "parsed": schema.model_validate(payload),
                "parsing_error": None,
            }

        return RunnableLambda(invocar)


def test_verde_y_rojo_sin_cuota_no_convocan(raiz_tasas: Path) -> None:
    """El comité solo se activa en amarillo o rojo con cuota simulada."""
    modelo = ModeloComite({})

    laura, verde = _diagnostico("empleada_verde", raiz_tasas)
    assert verde.semaforo == "verde"
    assert deliberar(laura, verde, modelo=modelo) is None

    entrada = EntradaDiagnostico.model_validate(
        {
            "producto": "libre_inversion",
            "vinculacion": "empleado",
            "ingreso_mensual": Decimal(1_000_000),
            "gastos_mensuales": Decimal(1_500_000),
            "cuotas_deudas": Decimal(0),
            "monto_credito": Decimal(10_000_000),
            "plazo_meses": 36,
        }
    )
    rojo_sin_cuota = motor.calcular(entrada, hoy=FECHA_CONSULTA, raiz=raiz_tasas)
    assert rojo_sin_cuota.semaforo == "rojo"
    assert rojo_sin_cuota.cuota_mensual is None
    assert deliberar(entrada, rojo_sin_cuota, modelo=modelo) is None

    assert modelo.llamadas == []


def test_escenarios_precalculados_con_el_motor(raiz_tasas: Path) -> None:
    """El siguiente plazo, el monto menor, la cartera y el estrés salen del motor."""
    entrada, resultado = _diagnostico("pensionado_amarillo", raiz_tasas)
    escenarios = construir_escenarios(entrada, resultado, hoy=FECHA_CONSULTA, raiz=raiz_tasas)

    assert [escenario.codigo for escenario in escenarios] == [
        "plazo_mas_largo",
        "monto_20_por_ciento_menos",
        "compra_de_cartera",
        "estres_de_ingreso",
    ]
    plazo, monto, cartera, estres = escenarios
    assert resultado.cuota_mensual is not None
    assert plazo.cuota_mensual is not None
    assert plazo.cuota_mensual.hasta < resultado.cuota_mensual.hasta
    assert monto.razon_endeudamiento is not None
    assert monto.razon_endeudamiento < Decimal("0.3306")
    assert cartera.semaforo is not None
    assert estres.cuota_mensual == resultado.cuota_mensual
    assert estres.margen_despues_cuota is not None


def test_amarillo_convoca_tres_posturas_y_una_ronda(raiz_tasas: Path) -> None:
    """Amarillo: tres opiniones, síntesis con condiciones y sin segunda ronda."""
    entrada, resultado = _diagnostico("pensionado_amarillo", raiz_tasas)
    modelo = ModeloComite(
        {
            "riesgo": [
                _postura(
                    "riesgo",
                    "con_condiciones",
                    ["La cuota deja poco margen.", "La razón está en el rango amarillo."],
                    ["margen_despues_cuota", "razon_endeudamiento"],
                )
            ],
            "comercial": [
                _postura(
                    "comercial",
                    "con_condiciones",
                    [
                        "[plazo_mas_largo] El siguiente plazo de la entrevista reduce la cuota.",
                        "[monto_20_por_ciento_menos] Un monto menor también ayuda.",
                    ],
                    ["escenarios[plazo_mas_largo]", "escenarios[monto_20_por_ciento_menos]"],
                )
            ],
            "auditor": [
                _postura(
                    "auditor",
                    "conforme",
                    ["Las cifras coinciden con el diagnóstico."],
                    ["diagnostico"],
                )
            ],
        }
    )

    deliberacion = deliberar(entrada, resultado, modelo=modelo)

    assert deliberacion is not None
    assert sorted(modelo.llamadas) == ["auditor", "comercial", "riesgo"]
    assert len(deliberacion.posturas) == 3
    assert {postura.agente for postura in deliberacion.posturas} == {
        "riesgo",
        "comercial",
        "auditor",
    }
    assert all(postura.postura != "abstencion" for postura in deliberacion.posturas)
    assert deliberacion.recomendacion.startswith(
        "El comité de crédito considera viable la solicitud, con condiciones."
    )
    assert "apto_con_condiciones:" not in deliberacion.recomendacion
    assert deliberacion.ofrece_asesor is False
    assert len(deliberacion.alternativas) == 2
    assert any(
        "Ampliar el plazo a 48 meses" in alternativa for alternativa in deliberacion.alternativas
    )
    assert any("20 % menos" in alternativa for alternativa in deliberacion.alternativas)
    assert "la decisión final corresponde a un asesor." in deliberacion.recomendacion
    assert "asesor humano del banco" not in deliberacion.recomendacion


def test_la_linea_del_auditor_se_resume_para_la_persona(raiz_tasas: Path) -> None:
    """La recomendación dice que el auditor está conforme; el detalle queda en posturas."""
    entrada, resultado = _diagnostico("pensionado_amarillo", raiz_tasas)
    argumento = "Revisé la cuota, la tasa y los escenarios: todo coincide."
    modelo = ModeloComite(
        {
            "riesgo": [_postura("riesgo", "con_condiciones", ["La cuota deja poco margen."])],
            "comercial": [
                _postura("comercial", "con_condiciones", ["[plazo_mas_largo] Revisa el plazo."])
            ],
            "auditor": [_postura("auditor", "conforme", [argumento])],
        }
    )

    deliberacion = deliberar(entrada, resultado, modelo=modelo)

    assert deliberacion is not None
    assert "Auditor: revisó las cifras y está conforme" in deliberacion.recomendacion
    assert argumento not in deliberacion.recomendacion
    auditor = next(postura for postura in deliberacion.posturas if postura.agente == "auditor")
    assert auditor.argumentos == [argumento]


def test_texto_para_la_persona_quita_codigos_internos() -> None:
    """Los corchetes de escenario y el snake_case se escriben en lenguaje natural."""
    texto = (
        "Comercial: con_condiciones — [plazo_mas_largo] Revisa el plazo y la razon_endeudamiento."
    )

    limpio = comite_mod.texto_para_la_persona(texto)

    assert limpio == ("Comercial: con condiciones — Revisa el plazo y la razon endeudamiento.")


def test_posturas_se_escriben_en_lenguaje_natural(raiz_tasas: Path) -> None:
    """La persona lee «con condiciones» y ningún código; la deliberación no cambia."""
    entrada, resultado = _diagnostico("pensionado_amarillo", raiz_tasas)
    modelo = ModeloComite(
        {
            "riesgo": [
                _postura(
                    "riesgo",
                    "con_condiciones",
                    ["La razón de endeudamiento supera el límite verde."],
                )
            ],
            "comercial": [
                _postura(
                    "comercial",
                    "con_condiciones",
                    ["[plazo_mas_largo] El siguiente plazo reduce la cuota."],
                )
            ],
            "auditor": [_postura("auditor", "conforme", ["Las cifras coinciden."])],
        }
    )

    deliberacion = deliberar(entrada, resultado, modelo=modelo)

    assert deliberacion is not None
    assert "Riesgo: con condiciones" in deliberacion.recomendacion
    assert "Comercial: con condiciones" in deliberacion.recomendacion
    assert "con_condiciones" not in deliberacion.recomendacion
    assert "[plazo_mas_largo]" not in deliberacion.recomendacion
    assert not CODIGO_INTERNO.search(deliberacion.recomendacion)
    # La deliberación interna conserva el vocabulario del contrato.
    assert {postura.postura for postura in deliberacion.posturas} == {
        "con_condiciones",
        "conforme",
    }


def test_auditor_revisa_las_posturas_de_riesgo_y_comercial(raiz_tasas: Path) -> None:
    """Riesgo y comercial van en paralelo; el auditor los revisa después."""
    entrada, resultado = _diagnostico("pensionado_amarillo", raiz_tasas)
    modelo = ModeloComite(
        {
            "riesgo": [
                _postura(
                    "riesgo",
                    "con_condiciones",
                    ["La cuota deja poco margen."],
                    ["margen_despues_cuota"],
                )
            ],
            "comercial": [
                _postura(
                    "comercial",
                    "con_condiciones",
                    ["[plazo_mas_largo] El siguiente plazo reduce la cuota."],
                    ["escenarios[plazo_mas_largo]"],
                )
            ],
            "auditor": [_postura("auditor", "conforme", ["Sin hallazgos."])],
        }
    )

    deliberar(entrada, resultado, modelo=modelo)

    assert sorted(modelo.llamadas[:2]) == ["comercial", "riesgo"]
    assert modelo.llamadas[2] == "auditor"
    mensaje = modelo.mensajes_por_rol["auditor"][0]
    assert "Posturas a revisar:" in mensaje
    assert "- riesgo: con_condiciones" in mensaje
    assert "La cuota deja poco margen." in mensaje
    assert "- comercial: con_condiciones" in mensaje
    assert "[plazo_mas_largo] El siguiente plazo reduce la cuota." in mensaje


def test_rojo_ofrece_asesor_y_no_apto(raiz_tasas: Path) -> None:
    """Rojo: la síntesis conserva el semáforo y ofrece un asesor."""
    entrada, resultado = _diagnostico("independiente_rojo", raiz_tasas)
    modelo = ModeloComite(
        {
            "riesgo": [
                _postura(
                    "riesgo",
                    "desfavorable",
                    ["El margen después de la cuota es negativo."],
                    ["margen_despues_cuota"],
                )
            ],
            "comercial": [
                _postura(
                    "comercial",
                    "desfavorable",
                    ["[compra_de_cartera] El traslado no alcanza para este monto."],
                    ["escenarios[compra_de_cartera]"],
                )
            ],
            "auditor": [_postura("auditor", "conforme", ["No hay hallazgos."])],
        }
    )

    deliberacion = deliberar(entrada, resultado, modelo=modelo)

    assert deliberacion is not None
    assert resultado.semaforo == "rojo"
    assert deliberacion.recomendacion.startswith(
        "El comité de crédito no recomienda este crédito con las condiciones actuales."
    )
    assert "no_apto:" not in deliberacion.recomendacion
    assert deliberacion.ofrece_asesor is True
    assert "asesor" in deliberacion.recomendacion
    assert len(modelo.llamadas) == 3


def test_rol_faltante_queda_en_abstencion_y_pide_asesor(raiz_tasas: Path) -> None:
    """Un esquema incompleto no inventa una decisión: el rol se abstiene."""
    entrada, resultado = _diagnostico("pensionado_amarillo", raiz_tasas)
    incompleta = {"agente": "riesgo", "argumentos": ["Sin postura."]}
    modelo = ModeloComite(
        {
            "riesgo": [incompleta],
            "comercial": [
                _postura("comercial", "con_condiciones", ["[plazo_mas_largo] Revisa el plazo."])
            ],
            "auditor": [_postura("auditor", "conforme", ["Sin hallazgos."])],
        }
    )

    deliberacion = deliberar(entrada, resultado, modelo=modelo)

    assert deliberacion is not None
    riesgo = next(postura for postura in deliberacion.posturas if postura.agente == "riesgo")
    assert riesgo.postura == "abstencion"
    assert "Riesgo: se abstuvo" in deliberacion.recomendacion
    assert "abstencion" not in deliberacion.recomendacion
    assert deliberacion.recomendacion.startswith(
        "El comité de crédito no logró una postura completa"
    )
    assert "requiere_asesor:" not in deliberacion.recomendacion
    assert deliberacion.ofrece_asesor is True
    # El esquema incompleto se reintenta una vez; el segundo intento también
    # queda en abstención (payload por defecto del modelo de prueba).
    assert modelo.llamadas.count("riesgo") == 2
    assert len(modelo.llamadas) == 4


def test_estres_de_ingreso_cambia_la_postura(raiz_tasas: Path) -> None:
    """Si el estrés deja el margen negativo, riesgo no puede ser favorable."""
    entrada = _entrada_estres()
    resultado = motor.calcular(entrada, hoy=FECHA_CONSULTA, raiz=raiz_tasas)
    assert resultado.semaforo == "amarillo"
    escenarios = construir_escenarios(entrada, resultado, hoy=FECHA_CONSULTA, raiz=raiz_tasas)
    estres = next(escenario for escenario in escenarios if escenario.codigo == "estres_de_ingreso")
    assert estres.semaforo == "rojo"
    assert estres.margen_despues_cuota is not None
    assert estres.margen_despues_cuota < 0

    modelo = ModeloComite(
        {
            "riesgo": [_postura("riesgo", "favorable", ["La cuota cabe con margen."])],
            "comercial": [
                _postura("comercial", "favorable", ["No hace falta cambiar nada."]),
                _postura(
                    "comercial",
                    "con_condiciones",
                    ["[plazo_mas_largo] El estrés de ingreso pide revisar el plazo."],
                ),
            ],
            "auditor": [_postura("auditor", "conforme", ["Sin hallazgos."])],
        }
    )

    deliberacion = deliberar(entrada, resultado, modelo=modelo)

    assert deliberacion is not None
    riesgo = next(postura for postura in deliberacion.posturas if postura.agente == "riesgo")
    assert riesgo.postura == "con_condiciones"
    assert riesgo.postura != "favorable"
    assert deliberacion.recomendacion.startswith(
        "El comité de crédito considera viable la solicitud, con condiciones."
    )
    assert len(modelo.llamadas) == 4


def test_auditor_atrapa_las_cuatro_trampas(raiz_tasas: Path) -> None:
    """Cifra inventada, promesa, alternativa no permitida y complacencia."""
    entrada, resultado = _diagnostico("independiente_rojo", raiz_tasas)
    escenarios = construir_escenarios(entrada, resultado, hoy=FECHA_CONSULTA, raiz=raiz_tasas)
    posturas = [
        _postura(
            "riesgo",
            "desfavorable",
            ["El margen después de la cuota es negativo."],
            ["margen_despues_cuota"],
        ),
        _postura(
            "comercial",
            "favorable",
            [
                "[vivienda_240] Te ofrecemos vivienda a 240 meses.",
                "Tu crédito está aprobado y garantizado.",
                "La cuota sería de $9.999.999.",
            ],
            ["margen_despues_cuota"],
        ),
        _postura("auditor", "conforme", ["No hay hallazgos."]),
    ]

    hallazgos = auditar(
        [PosturaAgente.model_validate(postura) for postura in posturas],
        resultado,
        escenarios,
    )

    assert any("Cifra no presente en la entrada: 9999999" in hallazgo for hallazgo in hallazgos)
    assert any("Promesa de aprobación" in hallazgo for hallazgo in hallazgos)
    assert any("Alternativa fuera de los escenarios: [vivienda_240]" in h for h in hallazgos)
    assert any("Producto fuera de los escenarios: vivienda" in hallazgo for hallazgo in hallazgos)
    assert any("más favorable que la de riesgo" in hallazgo for hallazgo in hallazgos)
    assert len(hallazgos) >= 4


def test_auditor_revisa_la_recomendacion_final(raiz_tasas: Path) -> None:
    """Una recomendación más favorable que riesgo y sin aviso se objeta."""
    entrada, resultado = _diagnostico("independiente_rojo", raiz_tasas)
    escenarios = construir_escenarios(entrada, resultado, hoy=FECHA_CONSULTA, raiz=raiz_tasas)
    posturas = [
        PosturaAgente.model_validate(_postura("riesgo", "desfavorable", ["No hay margen."])),
        PosturaAgente.model_validate(
            _postura("comercial", "desfavorable", ["[compra_de_cartera] No alcanza."])
        ),
        PosturaAgente.model_validate(_postura("auditor", "conforme", ["Sin hallazgos."])),
    ]

    hallazgos = auditar(
        posturas,
        resultado,
        escenarios,
        recomendacion="apto: el crédito cabe en el presupuesto.",
    )

    assert any("más favorable que la postura de riesgo" in hallazgo for hallazgo in hallazgos)
    assert any("Falta el aviso orientativo" in hallazgo for hallazgo in hallazgos)


def test_auditor_bajo_ataque_frena_la_respuesta(raiz_tasas: Path) -> None:
    """Si la corrección repite las trampas, el comité responde sin comité."""
    entrada, resultado = _diagnostico("independiente_rojo", raiz_tasas)
    ataque = _postura(
        "comercial",
        "favorable",
        [
            "[vivienda_240] Te ofrecemos vivienda.",
            "Tu crédito está aprobado y garantizado.",
        ],
    )
    modelo = ModeloComite(
        {
            "riesgo": [_postura("riesgo", "desfavorable", ["El margen es negativo."])],
            "comercial": [ataque, ataque],
            "auditor": [
                _postura("auditor", "objeta", ["Hay una promesa y una alternativa inválida."])
            ],
        }
    )
    registro = RegistroComite()

    deliberacion = deliberar(entrada, resultado, modelo=modelo, registro=registro)

    assert deliberacion is not None
    assert len(modelo.llamadas) == 4
    assert modelo.llamadas.count("comercial") == 2
    assert registro.total_llamadas == 4
    assert deliberacion.recomendacion.startswith("El comité no logró")
    assert deliberacion.alternativas == []
    assert deliberacion.hallazgos_auditor
    assert deliberacion.ofrece_asesor is True


def test_error_400_deepseek_devuelve_respuesta_deterministica(raiz_tasas: Path) -> None:
    """Si los tres agentes fallan con el 400, responde el diagnóstico sin ruido."""
    entrada, resultado = _diagnostico("independiente_rojo", raiz_tasas)
    assert resultado.semaforo == "rojo"
    modelo = ModeloComite(
        {
            "riesgo": [_error_400()],
            "comercial": [_error_400()],
            "auditor": [_error_400()],
        }
    )

    deliberacion = deliberar(entrada, resultado, modelo=modelo)

    assert deliberacion is not None
    assert set(modelo.metodos) == {"json_mode"}
    # Sin posturas de riesgo ni comercial no se convoca al auditor.
    assert sorted(modelo.llamadas) == ["comercial", "riesgo"]
    assert deliberacion.recomendacion.startswith("El comité no logró")
    assert deliberacion.alternativas == []
    assert deliberacion.hallazgos_auditor == []
    assert not any("Cifra no presente" in hallazgo for hallazgo in deliberacion.hallazgos_auditor)
    assert "request_id" not in deliberacion.recomendacion
    assert "tool_choice" not in deliberacion.recomendacion
    assert "987654321" not in deliberacion.recomendacion
    assert deliberacion.recomendacion.count("Habla con un asesor") == 1
    assert all(postura.postura == "abstencion" for postura in deliberacion.posturas)


def test_demo_andres_no_cae_al_texto_de_respaldo(raiz_tasas: Path) -> None:
    """Regresión de la demo real: los umbrales 0.30 y 0.40 no son cifras inventadas.

    Las posturas reproducen el caso y los formatos que citó Riesgo en la demo
    con Andrés. Riesgo cita los umbrales en forma decimal y porcentual, la tasa
    máxima y su vigencia; el auditor queda conforme. Antes del arreglo, el
    auditor determinístico reportaba «030» y «040» y la recomendación caía al
    texto del diagnóstico.
    """
    entrada, resultado = _diagnostico("independiente_rojo", raiz_tasas)
    assert resultado.semaforo == "rojo"
    escenarios = construir_escenarios(entrada, resultado, hoy=FECHA_CONSULTA, raiz=raiz_tasas)
    posturas = [
        _postura(
            "riesgo",
            "desfavorable",
            [
                "La razón de endeudamiento es 0.8572, equivalente a 85,72 %, y "
                "supera el umbral amarillo de 0.40 (40 %).",
                "El umbral verde es 0.30 (30 %) y la cuota máxima de $1.393.023 "
                "supera la capacidad de $250.000.",
                "La tasa máxima es 28,17 % E.A., vigente del 1 al 30 de noviembre de 2026.",
            ],
            ["razon_endeudamiento", "margen_despues_cuota", "tasa_ea.hasta"],
        ),
        _postura(
            "comercial",
            "desfavorable",
            [
                "[plazo_mas_largo] Ampliar el plazo a 48 meses deja la cuota en "
                "$1.043.628–$1.162.006 y el semáforo sigue en rojo.",
                "[compra_de_cartera] Trasladar las cuotas actuales deja el margen "
                "negativo y el semáforo sigue en rojo.",
            ],
            ["escenarios[plazo_mas_largo]", "escenarios[compra_de_cartera]"],
        ),
        _postura(
            "auditor",
            "conforme",
            [
                "Revisé las cifras: 0.8572 y 85,72 % coinciden con la razón de "
                "endeudamiento; 0.30 (30 %) y 0.40 (40 %) son política del proyecto.",
                "La tasa máxima de 28,17 % E.A. y la vigencia del 1 al 30 de "
                "noviembre de 2026 están citadas.",
            ],
            ["diagnostico", "umbrales"],
        ),
    ]

    hallazgos = auditar(
        [PosturaAgente.model_validate(postura) for postura in posturas],
        resultado,
        escenarios,
    )
    assert hallazgos == []

    modelo = ModeloComite(
        {
            "riesgo": [posturas[0]],
            "comercial": [posturas[1]],
            "auditor": [posturas[2]],
        }
    )
    deliberacion = deliberar(
        entrada,
        resultado,
        modelo=modelo,
        hoy=FECHA_CONSULTA,
        raiz=raiz_tasas,
    )

    assert deliberacion is not None
    assert sorted(modelo.llamadas) == ["auditor", "comercial", "riesgo"]
    assert deliberacion.hallazgos_auditor == []
    assert deliberacion.recomendacion.startswith(
        "El comité de crédito no recomienda este crédito con las condiciones actuales."
    )
    assert "El comité no logró" not in deliberacion.recomendacion
    assert "no_apto:" not in deliberacion.recomendacion
    assert deliberacion.ofrece_asesor is True


def test_correccion_unica_y_sin_segunda_ronda(raiz_tasas: Path) -> None:
    """Una objeción del auditor se corrige una vez y no se repite la ronda."""
    entrada, resultado = _diagnostico("pensionado_amarillo", raiz_tasas)
    modelo = ModeloComite(
        {
            "riesgo": [_postura("riesgo", "con_condiciones", ["La cuota deja poco margen."])],
            "comercial": [
                _postura(
                    "comercial",
                    "favorable",
                    ["[plazo_mas_largo] Te lo aprueban con el plazo más largo."],
                ),
                _postura(
                    "comercial",
                    "con_condiciones",
                    ["[plazo_mas_largo] Revisa el plazo antes de decidir."],
                ),
            ],
            "auditor": [_postura("auditor", "objeta", ["Hay una promesa de aprobación."])],
        }
    )

    deliberacion = deliberar(entrada, resultado, modelo=modelo)

    assert deliberacion is not None
    assert len(modelo.llamadas) == 4
    assert modelo.llamadas.count("comercial") == 2
    assert deliberacion.recomendacion.startswith(
        "El comité de crédito considera viable la solicitud, con condiciones."
    )
    # La corrección deja la validación determinística en limpio: la persona ve
    # que el auditor está conforme y nunca la objeción ya corregida.
    assert "Auditor: revisó las cifras y está conforme" in deliberacion.recomendacion
    assert "Hay una promesa de aprobación." not in deliberacion.recomendacion
    assert deliberacion.hallazgos_auditor == []
    # La objeción original se conserva en `posturas` para la pantalla.
    auditor = next(postura for postura in deliberacion.posturas if postura.agente == "auditor")
    assert auditor.postura == "objeta"
    assert auditor.argumentos == ["Hay una promesa de aprobación."]


def test_comercial_con_escenario_verde_no_es_complacencia(raiz_tasas: Path) -> None:
    """Citar compra de cartera en verde no es complacencia si ambas posturas coinciden.

    Regresión de la demo real con Jaime: el auditor objetó porque Comercial citó
    un escenario precalculado con semáforo verde. Esa cita es su función; la
    complacencia solo existe si la postura es más favorable que la de Riesgo. Si
    la corrección pasa la validación determinística, el texto a la persona no
    muestra la objeción.
    """
    entrada, resultado = _diagnostico("pensionado_amarillo", raiz_tasas)
    escenarios = construir_escenarios(entrada, resultado, hoy=FECHA_CONSULTA, raiz=raiz_tasas)
    compra = next(escenario for escenario in escenarios if escenario.codigo == "compra_de_cartera")
    assert compra.semaforo == "verde"

    riesgo = _postura(
        "riesgo",
        "con_condiciones",
        ["La cuota deja un margen ajustado y la razón está en amarillo."],
        ["margen_despues_cuota", "razon_endeudamiento"],
    )
    comercial = _postura(
        "comercial",
        "con_condiciones",
        [
            "[compra_de_cartera] Trasladar las cuotas actuales deja el semáforo "
            "en verde; la recomendación sigue con condiciones."
        ],
        ["escenarios[compra_de_cartera]"],
    )
    objecion = _postura(
        "auditor",
        "objeta",
        ["La postura del comercial es más favorable que la de riesgo."],
    )

    assert (
        auditar(
            [PosturaAgente.model_validate(postura) for postura in (riesgo, comercial, objecion)],
            resultado,
            escenarios,
        )
        == []
    )

    modelo = ModeloComite(
        {
            "riesgo": [riesgo],
            "comercial": [comercial, comercial],
            "auditor": [objecion],
        }
    )
    deliberacion = deliberar(entrada, resultado, modelo=modelo, hoy=FECHA_CONSULTA, raiz=raiz_tasas)

    assert deliberacion is not None
    assert modelo.llamadas.count("comercial") == 2
    assert "Auditor: revisó las cifras y está conforme" in deliberacion.recomendacion
    assert "más favorable" not in deliberacion.recomendacion
    assert "objeta" not in deliberacion.recomendacion
    assert deliberacion.hallazgos_auditor == []
    auditor = next(postura for postura in deliberacion.posturas if postura.agente == "auditor")
    assert auditor.postura == "objeta"


def test_prompts_del_comite_cargan_sin_datos_personales() -> None:
    """Los tres prompts cargan con `cargar_prompt` y no traen PII."""
    for tarea in TAREAS_COMITE:
        prompt = cargar_prompt(tarea)
        assert prompt.sistema
        assert "invent" in prompt.sistema.casefold()
        assert detectar_pii(prompt.sistema) is None


def test_prompt_del_auditor_no_confunde_semaforo_verde_con_complacencia() -> None:
    """El auditor no exige el aviso a los agentes ni llama complacencia a un escenario verde."""
    prompt = cargar_prompt("comite_auditor")
    texto = f"{prompt.sistema}\n{prompt.recordatorio}".casefold()

    assert "aunque sea verde" in texto
    assert "**no** es complacencia" in texto
    assert "determin" in texto
    assert "no se exige" in texto


def test_el_comite_no_recibe_nombre_ni_numero(raiz_tasas: Path) -> None:
    """El contexto de los agentes solo trae el diagnóstico y los escenarios."""
    entrada, resultado = _diagnostico("pensionado_amarillo", raiz_tasas)
    modelo = ModeloComite(
        {
            "riesgo": [_postura("riesgo", "con_condiciones", ["La cuota deja poco margen."])],
            "comercial": [_postura("comercial", "con_condiciones", ["[plazo_mas_largo] Revisa."])],
            "auditor": [_postura("auditor", "conforme", ["Sin hallazgos."])],
        }
    )

    deliberar(entrada, resultado, modelo=modelo)

    contexto = "\n".join(modelo.mensajes)
    assert "Andrés" not in contexto
    assert "Jaime" not in contexto
    assert "3001234567" not in contexto
    assert "@" not in contexto


def test_la_convocatoria_no_escribe_ni_cambia_el_diagnostico(raiz_tasas: Path) -> None:
    """El comité es de solo lectura: no toca la Bóveda ni el resultado."""
    entrada, resultado = _diagnostico("pensionado_amarillo", raiz_tasas)
    tabla = raiz_tasas / "tasas-personas-2026-11.jsonl"
    antes_tabla = tabla.read_text(encoding="utf-8")
    antes_resultado = resultado.model_dump(mode="json")
    modelo = ModeloComite(
        {
            "riesgo": [_postura("riesgo", "con_condiciones", ["La cuota deja poco margen."])],
            "comercial": [_postura("comercial", "con_condiciones", ["[plazo_mas_largo] Revisa."])],
            "auditor": [_postura("auditor", "conforme", ["Sin hallazgos."])],
        }
    )

    deliberar(entrada, resultado, modelo=modelo)

    assert resultado.model_dump(mode="json") == antes_resultado
    assert tabla.read_text(encoding="utf-8") == antes_tabla
    assert "boveda" not in inspect.getsource(comite_mod).casefold()


def test_el_estres_cambia_el_resultado_con_el_mismo_escenario(
    raiz_tasas: Path,
) -> None:
    """El escenario de estrés conserva la cuota y mide el margen con menos ingreso."""
    entrada, resultado = _diagnostico("pensionado_amarillo", raiz_tasas)
    escenarios: list[EscenarioComite] = construir_escenarios(
        entrada, resultado, hoy=FECHA_CONSULTA, raiz=raiz_tasas
    )
    estres = next(escenario for escenario in escenarios if escenario.codigo == "estres_de_ingreso")

    assert estres.cuota_mensual == resultado.cuota_mensual
    assert estres.razon_endeudamiento is not None
    assert resultado.razon_endeudamiento is not None
    assert estres.razon_endeudamiento > resultado.razon_endeudamiento


def test_auditor_no_confunde_alertas_con_productos(raiz_tasas: Path) -> None:
    """`vivienda_primera_cuota` en Riesgo es una alerta, no un producto ofrecido."""
    entrada, resultado = _diagnostico("independiente_rojo", raiz_tasas)
    escenarios = construir_escenarios(entrada, resultado, hoy=FECHA_CONSULTA, raiz=raiz_tasas)
    posturas = [
        PosturaAgente.model_validate(
            _postura(
                "riesgo",
                "desfavorable",
                [
                    "La alerta vivienda_primera_cuota está presente y el margen es negativo.",
                    "La razón de endeudamiento supera el umbral amarillo.",
                ],
                ["alertas[vivienda_primera_cuota]", "razon_endeudamiento"],
            )
        ),
        PosturaAgente.model_validate(
            _postura(
                "comercial",
                "desfavorable",
                ["[compra_de_cartera] El traslado no alcanza para este monto."],
                ["escenarios[compra_de_cartera]"],
            )
        ),
        PosturaAgente.model_validate(_postura("auditor", "conforme", ["Sin hallazgos."])),
    ]

    hallazgos = auditar(posturas, resultado, escenarios)

    assert not any("Producto fuera de los escenarios" in hallazgo for hallazgo in hallazgos)


def test_sin_riesgo_ni_comercial_no_convoca_al_auditor(raiz_tasas: Path) -> None:
    """Si ambos roles iniciales se abstienen, responde el diagnóstico directo."""
    entrada, resultado = _diagnostico("independiente_rojo", raiz_tasas)
    modelo = ModeloComite(
        {
            "riesgo": [_postura("riesgo", "abstencion", ["No pude verificar el caso."])],
            "comercial": [_postura("comercial", "abstencion", ["No pude verificar el caso."])],
            "auditor": [_postura("auditor", "conforme", ["No debía llamarse."])],
        }
    )
    registro = RegistroComite()

    deliberacion = deliberar(entrada, resultado, modelo=modelo, registro=registro)

    assert deliberacion is not None
    assert sorted(modelo.llamadas) == ["comercial", "riesgo"]
    assert "auditor" not in modelo.llamadas
    assert registro.total_llamadas == 2
    assert deliberacion.recomendacion.startswith("El comité no logró")
    auditor = next(postura for postura in deliberacion.posturas if postura.agente == "auditor")
    assert auditor.postura == "abstencion"
    assert "No se convocó" in auditor.argumentos[0]


def test_recomendacion_no_empieza_con_codigo_interno(raiz_tasas: Path) -> None:
    """La recomendación deliberada abre en lenguaje de la persona, no con `no_apto:`."""
    entrada, resultado = _diagnostico("independiente_rojo", raiz_tasas)
    modelo = ModeloComite(
        {
            "riesgo": [
                _postura("riesgo", "desfavorable", ["El margen después de la cuota es negativo."])
            ],
            "comercial": [
                _postura("comercial", "desfavorable", ["[compra_de_cartera] No alcanza."])
            ],
            "auditor": [_postura("auditor", "conforme", ["Sin hallazgos."])],
        }
    )

    deliberacion = deliberar(entrada, resultado, modelo=modelo)

    assert deliberacion is not None
    primera = deliberacion.recomendacion.splitlines()[0]
    assert not primera.casefold().startswith(
        ("no_apto", "apto", "apto_con_condiciones", "requiere_asesor")
    )
    assert "no_apto:" not in deliberacion.recomendacion
    assert primera.startswith("El comité de crédito")


def test_reintento_unico_ante_json_invalido(raiz_tasas: Path) -> None:
    """Un JSON truncado tiene un solo reintento y el registro guarda la causa."""
    entrada, resultado = _diagnostico("pensionado_amarillo", raiz_tasas)
    modelo = ModeloComite(
        {
            "riesgo": [
                None,
                _postura("riesgo", "con_condiciones", ["La cuota deja poco margen."]),
            ],
            "comercial": [
                _postura("comercial", "con_condiciones", ["[plazo_mas_largo] Revisa el plazo."])
            ],
            "auditor": [_postura("auditor", "conforme", ["Sin hallazgos."])],
        }
    )
    registro = RegistroComite()

    deliberacion = deliberar(entrada, resultado, modelo=modelo, registro=registro)

    assert deliberacion is not None
    assert modelo.llamadas.count("riesgo") == 2
    riesgo = next(postura for postura in deliberacion.posturas if postura.agente == "riesgo")
    assert riesgo.postura == "con_condiciones"
    fallo = next(llamada for llamada in registro.llamadas if llamada["clase_error"])
    assert fallo["clase_error"] == "OutputParserException"
    uso = leer_uso(fallo["metricas"])
    assert uso.finish_reason == "length"
    assert uso.salida == 3_000
    assert uso.razonamiento == 2_900
    assert "no fue JSON válido" in modelo.mensajes_por_rol["riesgo"][1]


def test_reintento_tras_error_de_longitud(raiz_tasas: Path) -> None:
    """Un `LengthFinishReasonError` se reintenta y deja la causa en el registro."""
    entrada, resultado = _diagnostico("pensionado_amarillo", raiz_tasas)
    modelo = ModeloComite(
        {
            "riesgo": [
                _error_longitud(),
                _postura("riesgo", "con_condiciones", ["La cuota deja poco margen."]),
            ],
            "comercial": [
                _postura("comercial", "con_condiciones", ["[plazo_mas_largo] Revisa el plazo."])
            ],
            "auditor": [_postura("auditor", "conforme", ["Sin hallazgos."])],
        }
    )
    registro = RegistroComite()

    deliberacion = deliberar(entrada, resultado, modelo=modelo, registro=registro)

    assert deliberacion is not None
    assert modelo.llamadas.count("riesgo") == 2
    riesgo = next(postura for postura in deliberacion.posturas if postura.agente == "riesgo")
    assert riesgo.postura == "con_condiciones"
    fallo = next(
        llamada
        for llamada in registro.llamadas
        if llamada["clase_error"] == "LengthFinishReasonError"
    )
    uso = leer_uso(fallo["metricas"])
    assert uso.finish_reason == "length"
    assert uso.salida == 1_200
    assert uso.razonamiento == 1_200


def test_un_solo_reintento_por_agente(raiz_tasas: Path) -> None:
    """Si el reintento también falla, el rol se abstiene sin abrir otra ronda."""
    entrada, resultado = _diagnostico("pensionado_amarillo", raiz_tasas)
    modelo = ModeloComite(
        {
            "riesgo": [None, None],
            "comercial": [
                _postura("comercial", "con_condiciones", ["[plazo_mas_largo] Revisa el plazo."])
            ],
            "auditor": [_postura("auditor", "conforme", ["Sin hallazgos."])],
        }
    )

    deliberacion = deliberar(entrada, resultado, modelo=modelo)

    assert deliberacion is not None
    assert modelo.llamadas.count("riesgo") == 2
    assert len(modelo.llamadas) == 4
    riesgo = next(postura for postura in deliberacion.posturas if postura.agente == "riesgo")
    assert riesgo.postura == "abstencion"


def test_limites_del_comite_cubren_el_razonamiento() -> None:
    """El tope por agente deja espacio al razonamiento y conserva costo y reloj."""
    limites = cargar_limites()

    assert limites.max_tokens_agente == 3_000
    assert limites.max_llamadas == 4
    assert limites.tiempo_maximo_segundos == 30.0
    assert limites.temperatura == 0.0


def test_deliberar_crea_el_modelo_sin_razonamiento(
    raiz_tasas: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Fuera de la demo, `deliberar` lee `razonamiento = false` del TOML."""
    entrada, resultado = _diagnostico("pensionado_amarillo", raiz_tasas)
    modelo = ModeloComite(
        {
            "riesgo": [_postura("riesgo", "con_condiciones", ["La cuota deja poco margen."])],
            "comercial": [
                _postura("comercial", "con_condiciones", ["[plazo_mas_largo] Revisa el plazo."])
            ],
            "auditor": [_postura("auditor", "conforme", ["Sin hallazgos."])],
        }
    )
    capturado: dict[str, Any] = {}

    def crear_modelo_de_prueba(**kwargs: Any) -> ModeloComite:
        """Registra los argumentos con los que `deliberar` crea el modelo."""
        capturado.update(kwargs)
        return modelo

    monkeypatch.setattr(comite_mod, "crear_modelo", crear_modelo_de_prueba)

    deliberacion = deliberar(entrada, resultado, hoy=FECHA_CONSULTA, raiz=raiz_tasas)

    limites = cargar_limites()
    assert deliberacion is not None
    assert limites.razonamiento is False
    assert capturado["razonamiento"] is False
    assert capturado["temperatura"] == 0.0
    assert capturado["max_tokens"] == limites.max_tokens_agente
    assert capturado["timeout"] == limites.tiempo_maximo_segundos


def test_metricas_de_longitud_salen_de_la_excepcion() -> None:
    """El diagnóstico de la demo lee `finish_reason` y tokens del error de longitud."""
    from types import SimpleNamespace

    completion = SimpleNamespace(
        choices=[SimpleNamespace(finish_reason="length")],
        usage=SimpleNamespace(
            prompt_tokens=1_000,
            completion_tokens=1_200,
            total_tokens=2_200,
            prompt_cache_hit_tokens=0,
            completion_tokens_details=SimpleNamespace(reasoning_tokens=1_150),
        ),
    )
    error = type("LengthFinishReasonError", (RuntimeError,), {"completion": completion})()

    metricas = comite_mod._metricas_de_error(error)
    uso = leer_uso(metricas)

    assert uso.finish_reason == "length"
    assert uso.salida == 1_200
    assert uso.razonamiento == 1_150


# --- Tarea 4.1: `auditar_texto` sale de `auditar` sin cambiar su comportamiento ---

#: Texto con un dato personal ficticio para las pruebas de PII.
TEXTO_CON_PII = "Escríbeme a ana.prueba@ejemplo.com o al 300 123 4567."

#: Combinaciones de posturas para comparar `auditar` con su versión anterior.
VARIANTES_POSTURAS: tuple[tuple[dict[str, Any], ...], ...] = (
    (
        _postura("riesgo", "desfavorable", ["El margen después de la cuota es negativo."]),
        _postura("comercial", "desfavorable", ["[compra_de_cartera] No alcanza."]),
        _postura("auditor", "conforme", ["Sin hallazgos."]),
    ),
    (
        _postura("riesgo", "desfavorable", ["El margen es negativo."], ["margen_despues_cuota"]),
        _postura(
            "comercial",
            "favorable",
            [
                "[vivienda_240] Te ofrecemos vivienda a 240 meses.",
                "Tu crédito está aprobado y garantizado.",
                "La cuota sería de $9.999.999.",
            ],
        ),
        _postura("auditor", "conforme", ["No hay hallazgos."]),
    ),
    (
        _postura(
            "riesgo",
            "desfavorable",
            ["La alerta vivienda_primera_cuota está presente.", TEXTO_CON_PII],
            ["alertas[vivienda_primera_cuota]"],
        ),
        _postura(
            "comercial",
            "con_condiciones",
            ["No está aprobado: depende del plazo.", "Aprobado, aprobado y aprobado."],
        ),
        _postura("auditor", "objeta", ["Tu crédito está aprobado.", "[vivienda_240]"]),
    ),
    (
        _postura("riesgo", "abstencion", ["Tu crédito está aprobado por $1.234.567."]),
        _postura("comercial", "favorable", ["Libranza y vivienda en [plazo_mas_largo]."]),
        _postura("auditor", "conforme", []),
    ),
    (
        _postura(
            "riesgo",
            "desfavorable",
            [
                "Este resultado no es una aprobación del crédito",
                "El diagnóstico no constituye una aprobación",
                "No hay aprobación todavía",
            ],
        ),
        _postura(
            "comercial",
            "desfavorable",
            [
                "Esto no implica aprobación",
                "Ninguna opción está garantizada",
                "No garantiza la aprobación",
            ],
        ),
        _postura("auditor", "conforme", []),
    ),
    (
        _postura(
            "riesgo",
            "desfavorable",
            [
                "No hay aprobación garantizada",
                "no podemos garantizar la aprobación",
                "ni siquiera está garantizado",
            ],
        ),
        _postura(
            "comercial",
            "desfavorable",
            [
                "no es una aprobación garantizada",
                "Es una opinión del comité de crédito y no una aprobación",
                "No garantiza la aprobación",
            ],
        ),
        _postura("auditor", "conforme", []),
    ),
)

#: Recomendaciones finales; `{aviso}` se reemplaza por el aviso del resultado.
VARIANTES_RECOMENDACION: tuple[str | None, ...] = (
    None,
    "apto: el crédito cabe en el presupuesto.",
    "no_apto: con estos datos la cuota no cabe.\n{aviso}",
    "apto_con_condiciones: te lo aprueban seguro.\n{aviso}",
    "no_apto: no conviene.\n" + TEXTO_CON_PII,
)

#: Negaciones que sí anulan la promesa: inmediatamente antes, con enlaces.
NEGACIONES_QUE_ANULAN: tuple[str, ...] = (
    "no te lo aprueban",
    "no está garantizado",
    "nunca garantizamos la aprobación",
    "Este resultado no es una aprobación del crédito",
    "No garantiza la aprobación",
    "El diagnóstico no constituye una aprobación",
    "Esto no implica aprobación",
    "No hay aprobación todavía",
    "Ninguna opción está garantizada",
    "No hay aprobación garantizada",
    "no podemos garantizar la aprobación",
    "no es una aprobación garantizada",
    "ni siquiera está garantizado",
    "Es una opinión del comité de crédito y no una aprobación",
)

#: Negaciones que no anulan la promesa: en otra frase, tras coma o a distancia.
NEGACIONES_QUE_NO_ANULAN: tuple[str, ...] = (
    "No te preocupes: te lo aprueban",
    "Sin papeles. Queda garantizado",
    "No hay problema; está aprobado",
    "No dudes que te lo aprueban",
    "No solo te lo aprueban, sino que te lo desembolsan hoy",
    "No, te lo aprueban",
    "No, está aprobado",
    "Sin duda está aprobado",
    "No hay problema, te lo aprueban",
)

#: Subconjunto que la versión original de #179 sí anulaba y ahora ya no.
#: «No, te lo aprueban» queda fuera: el token antiguo era «no » y no cruzaba la coma.
NEGACIONES_QUE_ANTES_ANULABAN: tuple[str, ...] = (
    "No te preocupes: te lo aprueban",
    "Sin papeles. Queda garantizado",
    "No hay problema; está aprobado",
    "No dudes que te lo aprueban",
    "No solo te lo aprueban, sino que te lo desembolsan hoy",
    "Sin duda está aprobado",
    "No hay problema, te lo aprueban",
)

#: Tokens de negación de `_promesas` antes de los arreglos: no miraban la frase.
_NEGACIONES_VERSION_ANTERIOR = ("no ", "nunca ", "ni ", "sin ", "ninguna ", "jamás ", "jamas ")


def _promesas_version_anterior(texto: str) -> Iterator[str]:
    """Copia de `_promesas` anterior a los arreglos de negación.

    La versión anterior anulaba la promesa si cualquier negación aparecía en
    los 25 caracteres previos, aunque estuviera en otra frase, tras una coma o
    sin preceder de inmediato a la promesa. Se conserva como referencia de la
    prueba de equivalencia de la tarea 4.1.

    Args:
        texto: argumentos y evidencias de un agente.

    Yields:
        Cada frase de promesa que la versión anterior consideraba sin negar.
    """
    for coincidencia in comite_mod._PROMESAS.finditer(texto):
        previo = texto[max(0, coincidencia.start() - 25) : coincidencia.start()].casefold()
        if any(negacion in previo for negacion in _NEGACIONES_VERSION_ANTERIOR):
            continue
        yield coincidencia.group(0)


def _auditar_original(
    posturas: Sequence[PosturaAgente],
    resultado: ResultadoDiagnostico,
    escenarios: Sequence[EscenarioComite],
    *,
    recomendacion: str | None = None,
) -> list[str]:
    """Copia de `auditar` tal como estaba antes de extraer `auditar_texto`.

    Es la referencia de la prueba de equivalencia de la tarea 4.1, con la
    negación de `_promesas_version_anterior`: la del #179, que cruzaba de frase.
    Si algún día se cambia el comportamiento de `auditar` a propósito, esta
    copia y su prueba se actualizan en el mismo PR.

    Args:
        posturas: opiniones de los tres agentes.
        resultado: resultado del motor.
        escenarios: escenarios precalculados.
        recomendacion: texto final, si ya se sintetizó.

    Returns:
        Los hallazgos que devolvía la versión anterior.
    """
    hallazgos: list[str] = []
    permitidas = comite_mod._cifras_permitidas(resultado, escenarios)
    productos = comite_mod._productos_permitidos(resultado, escenarios)

    for postura in posturas:
        if postura.agente == "auditor" or postura.postura == "abstencion":
            continue
        texto = comite_mod._texto_de(postura)
        for cifra in sorted(cifras_duras(texto)):
            if cifra not in permitidas:
                hallazgos.append(f"Cifra no presente en la entrada: {cifra}")
        for frase in _promesas_version_anterior(texto):
            hallazgos.append(f"Promesa de aprobación: «{frase}»")
        for codigo in comite_mod._CODIGO.findall(texto.casefold()):
            if codigo not in CODIGOS_ESCENARIO:
                hallazgos.append(f"Alternativa fuera de los escenarios: [{codigo}]")
        if postura.agente == "comercial":
            sin_ids = comite_mod._sin_identificadores(texto)
            for producto in comite_mod._productos_mencionados(sin_ids):
                if producto not in productos:
                    hallazgos.append(f"Producto fuera de los escenarios: {producto}")
        if detectar_pii(texto) is not None:
            hallazgos.append(f"Datos personales en la postura de {postura.agente}")

    riesgo = comite_mod._buscar_postura(posturas, "riesgo")
    comercial = comite_mod._buscar_postura(posturas, "comercial")
    orden = comite_mod.ORDEN_POSTURA
    if (
        riesgo is not None
        and comercial is not None
        and "abstencion" not in {riesgo.postura, comercial.postura}
        and riesgo.postura in orden
        and comercial.postura in orden
        and comite_mod._orden(comercial.postura) > comite_mod._orden(riesgo.postura)
    ):
        hallazgos.append("La postura del comercial es más favorable que la de riesgo.")

    if recomendacion is not None:
        etiqueta = comite_mod._etiqueta_recomendacion(recomendacion)
        if (
            riesgo is not None
            and etiqueta in {"apto", "apto_con_condiciones"}
            and comite_mod._orden(riesgo.postura) < orden["favorable"]
        ):
            hallazgos.append("La recomendación es más favorable que la postura de riesgo.")
        if resultado.aviso not in recomendacion:
            hallazgos.append("Falta el aviso orientativo.")
        if detectar_pii(recomendacion) is not None:
            hallazgos.append("Datos personales en la recomendación.")

    return comite_mod._sin_repetir(hallazgos)


@pytest.mark.parametrize("ident", ["independiente_rojo", "pensionado_amarillo"])
@pytest.mark.parametrize("variante", range(len(VARIANTES_POSTURAS)))
@pytest.mark.parametrize("recomendacion", VARIANTES_RECOMENDACION)
def test_auditar_da_los_mismos_hallazgos_que_antes(
    ident: str, variante: int, recomendacion: str | None, raiz_tasas: Path
) -> None:
    """Extraer `auditar_texto` no cambia los hallazgos salvo la regla de negación (4.1).

    Los cambios intencionales frente a la versión anterior son las negaciones
    que no preceden de inmediato a la promesa: en otra frase, tras una coma, a
    más de tres palabras o con «no dudes», «no solo» o «no te preocupes» (ver
    `test_auditar_difiere_de_la_version_anterior_solo_en_negaciones_que_no_la_preceden`).
    Estas variantes no traen esos casos, así que la equivalencia es exacta.
    """
    entrada, resultado = _diagnostico(ident, raiz_tasas)
    escenarios = construir_escenarios(entrada, resultado, hoy=FECHA_CONSULTA, raiz=raiz_tasas)
    posturas = [PosturaAgente.model_validate(p) for p in VARIANTES_POSTURAS[variante]]
    final = None if recomendacion is None else recomendacion.format(aviso=resultado.aviso)

    nuevo = auditar(posturas, resultado, escenarios, recomendacion=final)
    anterior = _auditar_original(posturas, resultado, escenarios, recomendacion=final)

    assert nuevo == anterior


@pytest.mark.parametrize("texto", NEGACIONES_QUE_ANTES_ANULABAN)
def test_auditar_difiere_de_la_version_anterior_solo_en_negaciones_que_no_la_preceden(
    texto: str, raiz_tasas: Path
) -> None:
    """El cambio es intencional: antes la promesa se perdía por un «no» no inmediato."""
    entrada, resultado = _diagnostico("independiente_rojo", raiz_tasas)
    escenarios = construir_escenarios(entrada, resultado, hoy=FECHA_CONSULTA, raiz=raiz_tasas)
    posturas = [
        PosturaAgente.model_validate(_postura("riesgo", "desfavorable", [texto])),
        PosturaAgente.model_validate(_postura("comercial", "desfavorable", ["No alcanza."])),
        PosturaAgente.model_validate(_postura("auditor", "conforme", ["Sin hallazgos."])),
    ]

    nuevo = auditar(posturas, resultado, escenarios)
    anterior = _auditar_original(posturas, resultado, escenarios)

    assert not any("Promesa de aprobación" in hallazgo for hallazgo in anterior)
    assert any("Promesa de aprobación" in hallazgo for hallazgo in nuevo)


def test_la_negacion_tras_coma_ya_se_marcaba_en_la_version_original(raiz_tasas: Path) -> None:
    """«No, te lo aprueban» ya era promesa en #179: «no » no cruzaba la coma."""
    entrada, resultado = _diagnostico("independiente_rojo", raiz_tasas)
    escenarios = construir_escenarios(entrada, resultado, hoy=FECHA_CONSULTA, raiz=raiz_tasas)
    posturas = [
        PosturaAgente.model_validate(_postura("riesgo", "desfavorable", ["No, te lo aprueban"])),
        PosturaAgente.model_validate(_postura("comercial", "desfavorable", ["No alcanza."])),
        PosturaAgente.model_validate(_postura("auditor", "conforme", ["Sin hallazgos."])),
    ]

    nuevo = auditar(posturas, resultado, escenarios)
    anterior = _auditar_original(posturas, resultado, escenarios)

    assert any("Promesa de aprobación" in hallazgo for hallazgo in anterior)
    assert any("Promesa de aprobación" in hallazgo for hallazgo in nuevo)


def test_las_variantes_de_equivalencia_ejercitan_cada_comprobacion(raiz_tasas: Path) -> None:
    """La prueba de equivalencia no pasa en vacío: cada tipo de hallazgo aparece."""
    entrada, resultado = _diagnostico("independiente_rojo", raiz_tasas)
    escenarios = construir_escenarios(entrada, resultado, hoy=FECHA_CONSULTA, raiz=raiz_tasas)
    todos: list[str] = []
    for variante in VARIANTES_POSTURAS:
        posturas = [PosturaAgente.model_validate(p) for p in variante]
        for recomendacion in VARIANTES_RECOMENDACION:
            final = None if recomendacion is None else recomendacion.format(aviso=resultado.aviso)
            todos.extend(auditar(posturas, resultado, escenarios, recomendacion=final))

    for inicio in (
        "Cifra no presente en la entrada",
        "Promesa de aprobación",
        "Alternativa fuera de los escenarios",
        "Producto fuera de los escenarios",
        "Datos personales en la postura de riesgo",
        "La postura del comercial es más favorable",
        "La recomendación es más favorable",
        "Falta el aviso orientativo",
        "Datos personales en la recomendación",
    ):
        assert any(hallazgo.startswith(inicio) for hallazgo in todos), inicio


def test_auditar_texto_sin_referencias_solo_revisa_promesas_y_pii() -> None:
    """Sin cifras, códigos, productos ni aviso, solo quedan promesas y PII."""
    assert detectar_pii(TEXTO_CON_PII) is not None

    hallazgos = auditar_texto(
        "Te presto $9.999.999 para [vivienda_240] y está aprobado. " + TEXTO_CON_PII
    )

    assert hallazgos == ["Promesa de aprobación: «aprobado»", MENSAJE_PII]


def test_auditar_texto_no_marca_una_promesa_negada() -> None:
    """«No está aprobado» no es una promesa."""
    assert auditar_texto("Todavía no está aprobado: lo decide el banco.") == []


@pytest.mark.parametrize("texto", NEGACIONES_QUE_ANULAN)
def test_auditar_texto_no_marca_una_negacion_inmediata_en_la_misma_frase(texto: str) -> None:
    """La negación inmediata, con enlaces permitidos, sigue anulando la promesa."""
    assert auditar_texto(texto) == []


@pytest.mark.parametrize("texto", NEGACIONES_QUE_NO_ANULAN)
def test_auditar_texto_marca_una_promesa_si_la_negacion_no_la_precede(texto: str) -> None:
    """En otra frase, tras coma o con «no dudes»/«no solo», la promesa sí se marca."""
    hallazgos = auditar_texto(texto)

    assert hallazgos
    assert all(hallazgo.startswith("Promesa de aprobación") for hallazgo in hallazgos)


def test_auditar_texto_limita_las_palabras_entre_la_negacion_y_la_promesa() -> None:
    """Con tres enlaces la negación aún anula; con cuatro ya no es inmediata."""
    assert auditar_texto("no está queda fue aprobado") == []
    assert auditar_texto("no está queda fue es aprobado") == ["Promesa de aprobación: «aprobado»"]


def test_auditar_texto_admite_un_sustantivo_tras_ninguna_o_ninguno() -> None:
    """«Ninguna opción está garantizada» niega; dos sustantivos ya no son inmediatos."""
    assert auditar_texto("Ninguna opción está garantizada") == []
    assert auditar_texto("Ninguno está garantizado") == []
    assert auditar_texto("Ninguna opción de crédito está garantizada") == [
        "Promesa de aprobación: «garantizada»"
    ]


def test_auditar_texto_ningun_niega_igual_que_ninguno() -> None:
    """«Ningún crédito está aprobado» y su forma sin tildes no son promesas."""
    assert auditar_texto("Ningún crédito está aprobado") == []
    assert auditar_texto("ningun credito esta aprobado") == []


def test_auditar_texto_ningun_no_niega_la_promesa_de_otra_frase() -> None:
    """«Ningún problema» es una expresión de ánimo, no una negación de la promesa."""
    assert auditar_texto("No dudes, ningún problema: te lo aprueban") == [
        "Promesa de aprobación: «te lo aprueban»"
    ]


def test_auditar_texto_revisa_cifras_contra_las_permitidas() -> None:
    """Solo marca las cifras que no están en la lista permitida."""
    texto = "Por $1.000.000 pagas $40.000 cada día."
    permitidas = set(cifras_duras("$1.000.000"))

    hallazgos = auditar_texto(texto, cifras_permitidas=permitidas)

    assert len(hallazgos) == len(cifras_duras(texto) - permitidas) >= 1
    assert all(hallazgo.startswith("Cifra no presente en la entrada") for hallazgo in hallazgos)
    assert all(cifra not in hallazgo for cifra in permitidas for hallazgo in hallazgos)


def test_auditar_texto_exige_el_aviso_completo() -> None:
    """Con `aviso`, falta el hallazgo solo si el texto no lo trae completo."""
    aviso = "Este resultado es orientativo."

    assert auditar_texto("La cuota no cabe.", aviso=aviso) == ["Falta el aviso orientativo."]
    assert auditar_texto(f"La cuota no cabe. {aviso}", aviso=aviso) == []


def test_auditar_texto_ordena_los_hallazgos_y_no_repite() -> None:
    """Orden fijo: cifras, promesas, códigos, productos, aviso y PII; sin repetidos."""
    texto = (
        "Tu crédito está aprobado, aprobado. [vivienda_240] Vivienda por $9.999.999. "
        + TEXTO_CON_PII
    )

    hallazgos = auditar_texto(
        texto,
        cifras_permitidas=set(),
        codigos_permitidos=CODIGOS_ESCENARIO,
        productos_permitidos=frozenset(),
        aviso="Este resultado es orientativo.",
        mensaje_pii="Datos personales en el turno.",
    )

    categorias = [
        "Cifra no presente en la entrada",
        "Promesa de aprobación",
        "Alternativa fuera de los escenarios",
        "Producto fuera de los escenarios",
        "Falta el aviso orientativo",
        "Datos personales en el turno.",
    ]
    posiciones = [
        next(i for i, hallazgo in enumerate(hallazgos) if hallazgo.startswith(categoria))
        for categoria in categorias
    ]
    assert posiciones == sorted(posiciones)
    assert len(hallazgos) == len(set(hallazgos))
    assert hallazgos.count("Promesa de aprobación: «aprobado»") == 1
