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
import threading
from collections.abc import Mapping, Sequence
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.runnables import RunnableLambda

from banco_occidente_corpus.asistente.prompts import cargar_prompt
from banco_occidente_corpus.asistente.validacion import detectar_pii
from banco_occidente_corpus.canal.contratos import EntradaDiagnostico, ResultadoDiagnostico
from banco_occidente_corpus.config import PROJECT_ROOT
from banco_occidente_corpus.diagnostico import comite as comite_mod
from banco_occidente_corpus.diagnostico import motor
from banco_occidente_corpus.diagnostico.comite import (
    EscenarioComite,
    PosturaAgente,
    RegistroComite,
    auditar,
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
        respuestas: Mapping[str, Sequence[Mapping[str, Any] | BaseException]],
    ) -> None:
        """Guarda la cola de respuestas por rol.

        Args:
            respuestas: payloads o excepciones por rol, en orden de uso.
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
            return {
                "raw": AIMessage(
                    content="ok",
                    usage_metadata={
                        "input_tokens": 100,
                        "output_tokens": 50,
                        "total_tokens": 150,
                    },
                ),
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
    assert deliberacion.recomendacion.startswith("apto_con_condiciones:")
    assert deliberacion.ofrece_asesor is False
    assert len(deliberacion.alternativas) == 2
    assert any(
        "Ampliar el plazo a 48 meses" in alternativa for alternativa in deliberacion.alternativas
    )
    assert any("20 % menos" in alternativa for alternativa in deliberacion.alternativas)


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
    assert deliberacion.recomendacion.startswith("no_apto:")
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
    assert deliberacion.recomendacion.startswith("requiere_asesor:")
    assert deliberacion.ofrece_asesor is True
    assert len(modelo.llamadas) == 3


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
    assert deliberacion.recomendacion.startswith("apto_con_condiciones:")
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
    assert len(modelo.llamadas) == 3
    assert deliberacion.recomendacion.startswith("El comité no logró")
    assert deliberacion.alternativas == []
    assert deliberacion.hallazgos_auditor == []
    assert not any("Cifra no presente" in hallazgo for hallazgo in deliberacion.hallazgos_auditor)
    assert "request_id" not in deliberacion.recomendacion
    assert "tool_choice" not in deliberacion.recomendacion
    assert "987654321" not in deliberacion.recomendacion
    assert deliberacion.recomendacion.count("Habla con un asesor") == 1
    assert all(postura.postura == "abstencion" for postura in deliberacion.posturas)


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
    assert deliberacion.recomendacion.startswith("apto_con_condiciones:")
    assert deliberacion.hallazgos_auditor
    assert any("promesa" in hallazgo.casefold() for hallazgo in deliberacion.hallazgos_auditor)


def test_prompts_del_comite_cargan_sin_datos_personales() -> None:
    """Los tres prompts cargan con `cargar_prompt` y no traen PII."""
    for tarea in TAREAS_COMITE:
        prompt = cargar_prompt(tarea)
        assert prompt.sistema
        assert "invent" in prompt.sistema.casefold()
        assert detectar_pii(prompt.sistema) is None


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
