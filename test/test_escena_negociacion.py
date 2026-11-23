"""Pruebas de la negociación de la escena: mesa, recomendación y cierre.

La mesa se calcula contra una tabla Gold temporal con la tasa de libre
inversión, así que las pruebas no dependen de la fecha ni de la red. Los
modelos son dobles que devuelven las propuestas de cada turno; ningún caso crea
un cliente real de DeepSeek.
"""

from __future__ import annotations

import re
import time
from collections.abc import Mapping, Sequence
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.runnables import RunnableLambda

from banco_occidente_corpus.asistente.prompts import (
    TAREAS,
    PromptNoEncontrado,
    cargar_prompt,
)
from banco_occidente_corpus.canal.contratos import EntradaDiagnostico
from banco_occidente_corpus.escena.contratos import (
    PerfilEscena,
    RespuestaEscena,
    VeredictoAuditor,
)
from banco_occidente_corpus.escena.negociacion import (
    CODIGOS_MESA,
    CODIGOS_OFERTABLES,
    FRASE_ASESOR,
    MAX_TURNOS,
    LimitesNegociacion,
    ResultadoNegociacion,
    cargar_limites_negociacion,
    construir_mesa,
    modo_demo,
    negociar,
)
from banco_occidente_corpus.sucursal.ajustes import leer_modo_demo
from banco_occidente_corpus.tablero.tasas import FilaTasa, escribir_tabla

#: Vigencia de la tabla Gold de prueba.
VIGENCIA_DESDE = date(2026, 11, 1)
VIGENCIA_HASTA = date(2026, 11, 30)
#: Fecha fija de consulta, dentro de la vigencia.
FECHA_CONSULTA = date(2026, 11, 16)
#: Huella del PDF de tasas de la vigencia.
SHA_EJEMPLO = "989be43a0ed19eb33e2057cd01c1ae612b6f15544eaaf41af6348846a6ff1b7f"
#: URL de la fuente de las tasas.
FUENTE = "https://www.bancodeoccidente.com.co/documents/d/guest/tasas-personas-bdo"
#: Entorno con clave de prueba: permite usar el doble del modelo sin red.
ENTORNO_PRUEBA: dict[str, str] = {"DEEPSEEK_API_KEY": "clave-de-prueba"}
#: Frases que la escena prohíbe en cualquier turno.
LENGUAJE_PROHIBIDO = re.compile(
    r"\b(acepto|aceptamos|cerramos|aprobad[oa]s?|aprobación|aprobamos)\b"
    r"|me quedo con el crédito",
    re.IGNORECASE,
)


def _fila(producto: str, desde: str, hasta: str) -> FilaTasa:
    """Construye una fila de la tabla Gold de prueba.

    Args:
        producto: clave canónica del producto.
        desde: tasa E.A. mínima publicada.
        hasta: tasa E.A. máxima publicada.

    Returns:
        La fila lista para escribir la tabla.
    """
    return FilaTasa(
        producto=producto,
        tipo_tasa="fija",
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
    """Crea una tabla Gold temporal con la tasa de libre inversión."""
    escribir_tabla(
        tmp_path / "tasas-personas-2026-11.jsonl",
        [
            _fila("libre_inversion", "0.2056", "0.2817"),
            _fila("compra_cartera", "0.1746", "0.2817"),
        ],
    )
    return tmp_path


def _perfil(
    ingreso: int,
    gastos: int,
    deudas: int,
    monto: int,
) -> EntradaDiagnostico:
    """Arma la entrada del motor para un perfil de la escena.

    Args:
        ingreso: ingreso mensual, en pesos.
        gastos: gastos fijos mensuales, en pesos.
        deudas: cuotas actuales de deudas, en pesos.
        monto: monto del crédito, en pesos.

    Returns:
        La entrada validada del diagnóstico.
    """
    return EntradaDiagnostico(
        producto="libre_inversion",
        vinculacion="empleado",
        ingreso_mensual=Decimal(ingreso),
        gastos_mensuales=Decimal(gastos),
        cuotas_deudas=Decimal(deudas),
        monto_credito=Decimal(monto),
        plazo_meses=36,
    )


def _verde() -> EntradaDiagnostico:
    """Perfil que cierra en verde con el escenario base."""
    return _perfil(5_000_000, 2_000_000, 0, 10_000_000)


def _amarillo() -> EntradaDiagnostico:
    """Perfil que cierra en amarillo con el escenario base."""
    return _perfil(3_000_000, 1_200_000, 0, 25_000_000)


def _rojo() -> EntradaDiagnostico:
    """Perfil rojo en todos los escenarios de la mesa."""
    return _perfil(2_000_000, 1_500_000, 0, 30_000_000)


class ModeloNegociacion:
    """Modelo de prueba que devuelve las propuestas encoladas por turno."""

    def __init__(
        self,
        respuestas: Sequence[Mapping[str, Any] | BaseException | None],
    ) -> None:
        """Guarda la cola de respuestas.

        Args:
            respuestas: payloads, excepciones o `None` (JSON inválido), en el
                orden en que los consume la negociación.
        """
        self._respuestas = list(respuestas)
        self.llamadas = 0
        self.metodos: list[str] = []
        self.sistemas: list[str] = []
        self.humanos: list[str] = []

    def with_structured_output(self, schema: Any, **kwargs: Any) -> RunnableLambda:
        """Devuelve un runnable que valida la siguiente respuesta.

        Args:
            schema: esquema Pydantic de la propuesta.
            **kwargs: argumentos de LangChain, incluido el método de salida.

        Returns:
            El runnable que responde como el agente.
        """
        self.metodos.append(str(kwargs.get("method", "")))

        def invocar(mensajes: Sequence[BaseMessage]) -> dict[str, Any]:
            """Consume la siguiente respuesta y la valida contra el esquema."""
            self.llamadas += 1
            self.sistemas.append(str(mensajes[0].content))
            self.humanos.append(str(mensajes[-1].content))
            payload = self._respuestas.pop(0) if self._respuestas else None
            if isinstance(payload, BaseException):
                raise payload
            if payload is None:
                return {
                    "raw": AIMessage(content='{"codigo": "base"'),
                    "parsed": None,
                    "parsing_error": "JSON truncado",
                }
            return {
                "raw": AIMessage(content="ok"),
                "parsed": schema.model_validate(payload),
                "parsing_error": None,
            }

        return RunnableLambda(invocar)


class ModeloLento(ModeloNegociacion):
    """Modelo que tarda más que el plazo de la llamada."""

    def with_structured_output(self, schema: Any, **kwargs: Any) -> RunnableLambda:
        """Devuelve un runnable que duerme antes de responder.

        Args:
            schema: esquema Pydantic de la propuesta.
            **kwargs: argumentos de LangChain.

        Returns:
            El runnable que se demora a propósito para probar el plazo.
        """

        def invocar(mensajes: Sequence[BaseMessage]) -> dict[str, Any]:
            """Duerme más que el plazo configurado y responde una propuesta."""
            self.llamadas += 1
            time.sleep(0.3)
            return {
                "raw": AIMessage(content="ok"),
                "parsed": {"codigo": "base", "decision": "propongo", "argumento": ""},
                "parsing_error": None,
            }

        return RunnableLambda(invocar)


def _negociar_demo(perfil: EntradaDiagnostico, raiz: Path) -> ResultadoNegociacion:
    """Negocia en modo demo contra la tabla Gold de prueba.

    Args:
        perfil: entrada del diagnóstico.
        raiz: carpeta de la tabla Gold temporal.

    Returns:
        El resultado determinista de la negociación.
    """
    return negociar(
        perfil,
        entorno={"SUCURSAL_DEMO": "1"},
        hoy=FECHA_CONSULTA,
        raiz=raiz,
    )


def _negociar_modelo(
    perfil: EntradaDiagnostico,
    modelo: ModeloNegociacion,
    raiz: Path,
    *,
    limites: LimitesNegociacion | None = None,
) -> ResultadoNegociacion:
    """Negocia con un doble del modelo y la tabla Gold de prueba.

    Args:
        perfil: entrada del diagnóstico.
        modelo: doble del modelo con sus respuestas.
        raiz: carpeta de la tabla Gold temporal.
        limites: límites alternativos, útiles para el reloj.

    Returns:
        El resultado de la negociación.
    """
    return negociar(
        perfil,
        modelo=modelo,
        entorno=ENTORNO_PRUEBA,
        limites=limites,
        hoy=FECHA_CONSULTA,
        raiz=raiz,
    )


def _respuestas_verde() -> list[dict[str, str]]:
    """Propuestas de los dos turnos del verde."""
    return [
        {"codigo": "base", "decision": "propongo", "argumento": "Quisiera el monto pedido."},
        {"codigo": "base", "decision": "recomiendo", "argumento": "La cuota deja holgura."},
    ]


def _respuestas_amarillo() -> list[dict[str, str]]:
    """Propuestas de los cuatro turnos del amarillo."""
    return [
        {"codigo": "base", "decision": "propongo", "argumento": "Quisiera el monto pedido."},
        {
            "codigo": "plazo_mas_largo_48",
            "decision": "contrapropongo",
            "argumento": "La cuota baja y el total sube.",
        },
        {
            "codigo": "plazo_mas_largo_48",
            "decision": "propongo",
            "argumento": "Prefiero la cuota más baja.",
        },
        {
            "codigo": "plazo_mas_largo_48",
            "decision": "recomiendo",
            "argumento": "Es la opción sostenible.",
        },
    ]


def _respuestas_rojo() -> list[dict[str, str]]:
    """Propuestas de los cuatro turnos del rojo."""
    return [
        {"codigo": "base", "decision": "propongo", "argumento": "Quisiera el monto pedido."},
        {"codigo": "base", "decision": "rechazo", "argumento": "No cabe en el presupuesto."},
        {
            "codigo": "plazo_mas_largo_60",
            "decision": "propongo",
            "argumento": "Probemos un plazo más largo.",
        },
        {
            "codigo": "plazo_mas_largo_60",
            "decision": "rechazo",
            "argumento": "Tampoco alcanza.",
        },
    ]


def test_mesa_precalculada_con_el_motor(raiz_tasas: Path) -> None:
    """La mesa trae los escenarios del diseño y deja el estrés fuera de oferta."""
    mesa = construir_mesa(_verde(), hoy=FECHA_CONSULTA, raiz=raiz_tasas)

    assert [escenario.codigo for escenario in mesa] == [
        "base",
        "plazo_mas_largo_48",
        "plazo_mas_largo_60",
        "monto_20_por_ciento_menos",
        "monto_40_por_ciento_menos",
        "estres_de_ingreso",
    ]
    assert all(escenario.codigo in CODIGOS_MESA for escenario in mesa)
    estres = mesa[-1]
    assert estres.codigo == "estres_de_ingreso"
    assert estres.ofertable is False
    assert estres.aceptable is False
    assert "estres_de_ingreso" not in CODIGOS_OFERTABLES
    assert all(escenario.cuota_mensual is not None for escenario in mesa)
    assert all(escenario.monto > 0 for escenario in mesa)


def test_compra_de_cartera_solo_si_hay_deudas(raiz_tasas: Path) -> None:
    """Sin deudas la mesa no ofrece compra de cartera; con deudas sí."""
    sin_deudas = construir_mesa(_verde(), hoy=FECHA_CONSULTA, raiz=raiz_tasas)
    con_deudas = construir_mesa(
        _perfil(5_000_000, 2_000_000, 500_000, 10_000_000),
        hoy=FECHA_CONSULTA,
        raiz=raiz_tasas,
    )

    assert "compra_de_cartera" not in {escenario.codigo for escenario in sin_deudas}
    assert "compra_de_cartera" in {escenario.codigo for escenario in con_deudas}


def test_el_verde_termina_en_dos_o_tres_turnos_y_recomienda(raiz_tasas: Path) -> None:
    """En verde el banco recomienda la opción pedida y la escena no sigue."""
    resultado = _negociar_demo(_verde(), raiz_tasas)

    turnos = resultado.negociacion.turnos
    assert 2 <= len(turnos) <= 3
    assert all(turno.origen == "reglas" for turno in turnos)
    assert [decision.decision for decision in resultado.decisiones] == [
        "propongo",
        "recomiendo",
    ]
    assert "Quisiera" in turnos[0].texto
    assert "la cuota sería" in turnos[0].texto
    assert "sostenible" in turnos[1].texto
    assert "cabe con holgura" in turnos[1].texto
    assert FRASE_ASESOR in turnos[1].texto
    assert resultado.acuerdo is not None
    assert resultado.acuerdo.codigo == "base"
    assert resultado.acuerdo.semaforo == "verde"
    assert resultado.negociacion.registro[-1] == "cierre | recomendación en base"
    for turno in turnos:
        assert turno.escenario is not None
        assert turno.cifras
        assert len(turno.texto.split()) <= 40
        for cifra in turno.cifras:
            assert cifra.fuente.referencia
            assert cifra.valor_legible in turno.texto


def test_el_amarillo_pasa_a_una_alternativa_en_verde(raiz_tasas: Path) -> None:
    """El amarillo compara cuota y total, y pasa al plazo verde más corto."""
    resultado = _negociar_demo(_amarillo(), raiz_tasas)

    turnos = resultado.negociacion.turnos
    assert [decision.decision for decision in resultado.decisiones] == [
        "propongo",
        "contrapropongo",
        "propongo",
        "recomiendo",
    ]
    base = resultado.negociacion.escenarios[0]
    contrapropuesta = turnos[1]
    assert contrapropuesta.escenario is not None
    assert contrapropuesta.escenario.codigo == "plazo_mas_largo_48"
    assert contrapropuesta.escenario.semaforo == "verde"
    assert "Cabe, pero ajustado" in contrapropuesta.texto
    assert "la cuota baja de $995.016 a $830.005" in contrapropuesta.texto
    assert "el total sube de $35.820.576 a $39.840.240" in contrapropuesta.texto
    assert "$4.019.664 más" in contrapropuesta.texto
    assert base.total_pagado is not None
    assert contrapropuesta.escenario.total_pagado is not None
    total_base = next(
        cifra for cifra in contrapropuesta.cifras if cifra.etiqueta == "total del escenario pedido"
    )
    assert total_base.valor == base.total_pagado
    assert total_base.valor_legible in contrapropuesta.texto
    total_alternativa = next(
        cifra for cifra in contrapropuesta.cifras if cifra.etiqueta == "total de la contrapropuesta"
    )
    assert total_alternativa.valor == contrapropuesta.escenario.total_pagado
    diferencia = next(
        cifra for cifra in contrapropuesta.cifras if cifra.etiqueta == "diferencia de total"
    )
    assert diferencia.valor == contrapropuesta.escenario.total_pagado - base.total_pagado
    assert diferencia.valor_legible in contrapropuesta.texto
    assert all(cifra.valor_legible in contrapropuesta.texto for cifra in contrapropuesta.cifras)
    assert "cuota más baja" in turnos[2].texto
    assert "sostenible" in turnos[3].texto
    assert FRASE_ASESOR in turnos[3].texto
    assert resultado.acuerdo is not None
    assert resultado.acuerdo.codigo == "plazo_mas_largo_48"
    assert resultado.acuerdo.semaforo == "verde"


def test_el_rojo_prueba_el_plazo_antes_que_el_monto(raiz_tasas: Path) -> None:
    """El rojo prueba 60 meses y después el monto menor, y cierra sin acuerdo."""
    resultado = _negociar_demo(_rojo(), raiz_tasas)

    turnos = resultado.negociacion.turnos
    assert [decision.decision for decision in resultado.decisiones] == [
        "propongo",
        "rechazo",
        "propongo",
        "rechazo",
    ]
    assert resultado.decisiones[2].codigo == "plazo_mas_largo_60"
    assert "No cabe en tu capacidad" in turnos[1].texto
    assert "monto menor" in turnos[3].texto
    assert FRASE_ASESOR in turnos[3].texto
    registro = resultado.negociacion.registro
    linea_orden = next(linea for linea in registro if "pruebas en orden" in linea)
    assert linea_orden.index("plazo_mas_largo_60") < linea_orden.index("monto_40_por_ciento_menos")
    assert any("prueba 1: plazo_mas_largo_60" in linea for linea in registro)
    assert any("prueba 2: monto_40_por_ciento_menos" in linea for linea in registro)
    assert resultado.acuerdo is None
    assert registro[-1] == "cierre | sin_acuerdo"
    assert any(
        hallazgo.codigo == "sin_acuerdo" for hallazgo in resultado.negociacion.veredicto.hallazgos
    )
    assert resultado.negociacion.veredicto.alternativas


def test_ningun_turno_usa_lenguaje_de_aprobacion(raiz_tasas: Path) -> None:
    """Ningún perfil usa «acepto», «cerramos», «aprobado» ni el cierre viejo."""
    for perfil in (_verde(), _amarillo(), _rojo()):
        resultado = _negociar_demo(perfil, raiz_tasas)
        for turno in resultado.negociacion.turnos:
            assert LENGUAJE_PROHIBIDO.search(turno.texto) is None
        ultimo = resultado.negociacion.turnos[-1]
        assert FRASE_ASESOR in ultimo.texto


def test_modelo_con_un_codigo_fuera_de_la_mesa_cae_a_reglas(raiz_tasas: Path) -> None:
    """Un código inventado se reemplaza por la política determinista."""
    modelo = ModeloNegociacion(
        [{"codigo": "credito_express", "decision": "propongo", "argumento": "Te conviene."}]
    )

    resultado = _negociar_modelo(_verde(), modelo, raiz_tasas)

    assert modelo.llamadas == 1
    assert all(turno.origen == "reglas" for turno in resultado.negociacion.turnos)
    assert len(resultado.negociacion.turnos) == 2
    assert any("no existe en la mesa" in linea for linea in resultado.negociacion.registro)
    assert resultado.acuerdo is not None
    assert resultado.acuerdo.semaforo == "verde"


@pytest.mark.parametrize(
    ("argumento", "marca"),
    [
        ("Te presto 987654321 sin problema", "987654321"),
        ("El escenario queda en verde para ti", "verde"),
    ],
)
def test_argumentos_con_digitos_o_colores_se_descartan(
    raiz_tasas: Path,
    argumento: str,
    marca: str,
) -> None:
    """El argumento inválido no llega al turno; la decisión válida se conserva."""
    modelo = ModeloNegociacion(
        [
            {"codigo": "base", "decision": "propongo", "argumento": argumento},
            {"codigo": "base", "decision": "recomiendo", "argumento": "Cabe con holgura."},
        ]
    )

    resultado = _negociar_modelo(_verde(), modelo, raiz_tasas)

    primer = resultado.negociacion.turnos[0]
    assert marca not in primer.texto
    assert primer.origen == "llm"
    assert any("argumento descartado" in linea for linea in resultado.negociacion.registro)
    assert resultado.acuerdo is not None


def test_un_argumento_con_lenguaje_de_aprobacion_se_descarta(raiz_tasas: Path) -> None:
    """«Acepto», «cerramos» o «aprobado» en el argumento no llegan al turno."""
    modelo = ModeloNegociacion(
        [
            {
                "codigo": "base",
                "decision": "propongo",
                "argumento": "Acepto, cerramos y queda aprobado.",
            },
            {"codigo": "base", "decision": "recomiendo", "argumento": "Cabe con holgura."},
        ]
    )

    resultado = _negociar_modelo(_verde(), modelo, raiz_tasas)

    primer = resultado.negociacion.turnos[0]
    assert LENGUAJE_PROHIBIDO.search(primer.texto) is None
    assert primer.origen == "llm"
    assert any(
        "argumento descartado (usa lenguaje de aprobación)" in linea
        for linea in resultado.negociacion.registro
    )
    assert resultado.acuerdo is not None


@pytest.mark.parametrize(
    ("argumento", "marca"),
    [
        ("Queda garantizado por el banco", "garantizado"),
        ("Tranquilo: te lo aprueban hoy", "aprueban"),
        ("Es como el gota a gota, pero formal", "gota"),
        ("Don Gota te lo presta sin papeles", "Gota"),
    ],
)
def test_un_argumento_con_promesas_o_gota_a_gota_se_descarta(
    raiz_tasas: Path,
    argumento: str,
    marca: str,
) -> None:
    """Las promesas del comité y el gota a gota no llegan al turno."""
    modelo = ModeloNegociacion(
        [
            {"codigo": "base", "decision": "propongo", "argumento": argumento},
            {"codigo": "base", "decision": "recomiendo", "argumento": "Cabe con holgura."},
        ]
    )

    resultado = _negociar_modelo(_verde(), modelo, raiz_tasas)

    primer = resultado.negociacion.turnos[0]
    assert marca not in primer.texto
    assert primer.origen == "llm"
    assert any("argumento descartado" in linea for linea in resultado.negociacion.registro)
    assert resultado.acuerdo is not None


def test_un_argumento_que_repite_la_plantilla_se_descarta(raiz_tasas: Path) -> None:
    """Si el argumento repite las palabras del turno, se usa solo la plantilla."""
    modelo = ModeloNegociacion(
        [
            {
                "codigo": "base",
                "decision": "propongo",
                "argumento": "Quisiera el crédito; la cuota sería la del crédito.",
            },
            {
                "codigo": "base",
                "decision": "recomiendo",
                "argumento": "El presupuesto queda protegido.",
            },
        ]
    )

    resultado = _negociar_modelo(_verde(), modelo, raiz_tasas)

    primer = resultado.negociacion.turnos[0]
    assert "Quisiera el crédito" not in primer.texto
    assert primer.texto.startswith("Quisiera $10.000.000 a 36 meses")
    assert primer.origen == "llm"
    assert any(
        "argumento descartado (repite la plantilla)" in linea
        for linea in resultado.negociacion.registro
    )
    assert resultado.acuerdo is not None


def test_recomendar_un_rojo_se_convierte_en_rechazo(raiz_tasas: Path) -> None:
    """El banco no puede recomendar un rojo aunque el modelo lo intente."""
    modelo = ModeloNegociacion(
        [
            {"codigo": "base", "decision": "propongo", "argumento": "Quisiera el monto."},
            {"codigo": "base", "decision": "recomiendo", "argumento": "Cabe en tu capacidad."},
            {
                "codigo": "plazo_mas_largo_60",
                "decision": "propongo",
                "argumento": "Probemos más plazo.",
            },
            {
                "codigo": "plazo_mas_largo_60",
                "decision": "recomiendo",
                "argumento": "Es sostenible.",
            },
        ]
    )

    resultado = _negociar_modelo(_rojo(), modelo, raiz_tasas)

    assert [decision.decision for decision in resultado.decisiones] == [
        "propongo",
        "rechazo",
        "propongo",
        "rechazo",
    ]
    assert resultado.acuerdo is None
    assert any(
        "la decisión del modelo no sigue la regla del escenario" in linea
        for linea in resultado.negociacion.registro
    )
    assert resultado.negociacion.registro[-1] == "cierre | sin_acuerdo"


def test_tiempo_de_la_llamada_agotado_usa_la_politica_determinista(raiz_tasas: Path) -> None:
    """Si una llamada no responde a tiempo, ese turno y los siguientes son reglas."""
    modelo = ModeloLento([])

    resultado = _negociar_modelo(
        _verde(),
        modelo,
        raiz_tasas,
        limites=LimitesNegociacion(tiempo_llamada_segundos=0.05, tiempo_total_segundos=2.0),
    )

    assert modelo.llamadas == 1
    assert len(resultado.negociacion.turnos) == 2
    assert all(turno.origen == "reglas" for turno in resultado.negociacion.turnos)
    assert any("tiempo de la llamada agotado" in linea for linea in resultado.negociacion.registro)
    assert resultado.acuerdo is not None
    assert resultado.acuerdo.semaforo == "verde"


def test_tiempo_total_agotado_no_llama_al_modelo(raiz_tasas: Path) -> None:
    """Sin tiempo total la negociación se resuelve con la política determinista."""
    modelo = ModeloNegociacion([])

    resultado = _negociar_modelo(
        _verde(),
        modelo,
        raiz_tasas,
        limites=LimitesNegociacion(tiempo_total_segundos=0.0),
    )

    assert modelo.llamadas == 0
    assert len(resultado.negociacion.turnos) == 2
    assert all(turno.origen == "reglas" for turno in resultado.negociacion.turnos)


def test_modo_demo_no_construye_el_modelo(
    monkeypatch: pytest.MonkeyPatch,
    raiz_tasas: Path,
) -> None:
    """Con SUCURSAL_DEMO=1 o sin clave, la política determinista no crea modelo."""
    import banco_occidente_corpus.escena.negociacion as negociacion

    def prohibido(*args: Any, **kwargs: Any) -> Any:
        """Falla si la negociación intenta crear un cliente real."""
        raise AssertionError("el modo demo no debe crear un modelo")

    monkeypatch.setattr(negociacion, "crear_modelo", prohibido)

    con_bandera = negociar(
        _verde(),
        entorno={"SUCURSAL_DEMO": "1"},
        hoy=FECHA_CONSULTA,
        raiz=raiz_tasas,
    )
    sin_clave = negociar(_verde(), entorno={}, hoy=FECHA_CONSULTA, raiz=raiz_tasas)

    assert all(turno.origen == "reglas" for turno in con_bandera.negociacion.turnos)
    assert all(turno.origen == "reglas" for turno in sin_clave.negociacion.turnos)


def test_modo_demo_lee_la_bandera_y_la_clave() -> None:
    """La bandera manda y la falta de clave activa el modo determinista."""
    assert modo_demo({"SUCURSAL_DEMO": "1"}) is True
    assert modo_demo({}) is True
    assert modo_demo({"DEEPSEEK_API_KEY": "prueba"}) is False
    assert modo_demo({"DEEPSEEK_API_KEY": "prueba", "SUCURSAL_DEMO": "1"}) is True


def test_modo_demo_acepta_los_mismos_valores_que_la_sucursal() -> None:
    """La escena y la Sucursal leen SUCURSAL_DEMO con la misma función."""
    for bandera in ("1", "true", "TRUE", "si", "sí", " Sí ", "0", "no", ""):
        entorno = {"DEEPSEEK_API_KEY": "clave-de-prueba", "SUCURSAL_DEMO": bandera}
        assert modo_demo(entorno) is leer_modo_demo(entorno)


def test_nunca_hay_mas_de_cuatro_turnos(raiz_tasas: Path) -> None:
    """Aunque el modelo tenga más propuestas, la negociación corta en cuatro."""
    respuestas = _respuestas_amarillo() + _respuestas_amarillo()
    modelo = ModeloNegociacion(respuestas)

    resultado = _negociar_modelo(_amarillo(), modelo, raiz_tasas)

    assert len(resultado.negociacion.turnos) == MAX_TURNOS
    assert len(resultado.decisiones) == MAX_TURNOS
    assert modelo.llamadas == MAX_TURNOS


def test_el_estres_no_se_ofrece(raiz_tasas: Path) -> None:
    """Un agente que propone el estrés cae a la política y ningún turno lo vende."""
    modelo = ModeloNegociacion(
        [{"codigo": "estres_de_ingreso", "decision": "propongo", "argumento": "Aguantas."}]
    )

    resultado = _negociar_modelo(_verde(), modelo, raiz_tasas)

    assert all(
        turno.escenario is not None and turno.escenario.codigo != "estres_de_ingreso"
        for turno in resultado.negociacion.turnos
    )
    assert any("no es ofertable" in linea for linea in resultado.negociacion.registro)


def test_los_prompts_versionados_se_cargan() -> None:
    """Los dos prompts están en TAREAS y declaran su tarea y su versión."""
    assert "negociacion_joven" in TAREAS
    assert "negociacion_banco" in TAREAS

    joven = cargar_prompt("negociacion_joven")
    banco = cargar_prompt("negociacion_banco")

    assert joven.version == "v1"
    assert banco.version == "v1"
    assert "PropuestaNegociacion" in joven.sistema
    assert "PropuestaNegociacion" in banco.sistema
    assert "propongo" in joven.sistema
    assert "sostenible" in banco.sistema
    assert "cabe, pero ajustado" in banco.sistema
    assert "decisión final es de un asesor" in banco.sistema
    with pytest.raises(PromptNoEncontrado):
        cargar_prompt("negociacion_joven", "v9")


def test_el_modelo_no_recibe_umbrales_ni_datos_personales(raiz_tasas: Path) -> None:
    """El contexto lleva la mesa y el escenario, no los umbrales del motor."""
    modelo = ModeloNegociacion(_respuestas_verde())

    resultado = _negociar_modelo(_verde(), modelo, raiz_tasas)

    assert modelo.metodos == ["json_mode"] * 2
    assert all("umbrales" not in humano for humano in modelo.humanos)
    assert all("PropuestaNegociacion" in humano for humano in modelo.humanos)
    assert "aceptable" in modelo.humanos[0]
    assert resultado.acuerdo is not None


def test_un_perfil_de_la_escena_se_convierte_en_entrada(raiz_tasas: Path) -> None:
    """`PerfilEscena` aporta monto y respuestas y la negociación funciona igual."""
    perfil = PerfilEscena(
        personaje="Camila",
        proposito="Perfil amarillo de prueba",
        monto_declarado=Decimal(25_000_000),
        monto_calculo=Decimal(25_000_000),
        respuestas=(
            RespuestaEscena(
                pregunta="monto",
                letra="D",
                opcion_id="monto.DE_20M_A_50M",
                texto="$20 a $50 millones",
                valor=Decimal(25_000_000),
            ),
            RespuestaEscena(
                pregunta="ingresos",
                letra="B",
                opcion_id="ingresos.DE_2M_A_3M",
                texto="$2 a $3 millones",
                valor=Decimal(3_000_000),
            ),
            RespuestaEscena(
                pregunta="gastos",
                letra="B",
                opcion_id="gastos.DE_1M_A_2M",
                texto="$1 a $2 millones",
                valor=Decimal(1_200_000),
            ),
            RespuestaEscena(
                pregunta="deudas",
                letra="A",
                opcion_id="cuotas.NINGUNA",
                texto="No tengo cuotas",
                valor=Decimal(0),
            ),
        ),
        confirmado=True,
    )

    resultado = _negociar_demo(perfil, raiz_tasas)

    assert resultado.acuerdo is not None
    assert resultado.acuerdo.semaforo == "verde"
    assert resultado.acuerdo.codigo == "plazo_mas_largo_48"


def test_el_auditor_inyectado_reemplaza_el_veredicto_provisional(raiz_tasas: Path) -> None:
    """El orquestador acepta el auditor de la escena sin acoplarse a su módulo."""
    turnos_vistos: list[str] = []

    def auditor(
        turnos: Sequence[Any],
        escenarios: Sequence[Any],
        acuerdo: Any,
    ) -> VeredictoAuditor:
        """Devuelve un veredicto conforme y deja constancia de los turnos."""
        turnos_vistos.extend(turno.id for turno in turnos)
        return VeredictoAuditor(
            veredicto="conforme",
            hallazgos=(),
            turnos_revisados=tuple(turno.id for turno in turnos),
            reglas=("guion",),
        )

    resultado = negociar(
        _verde(),
        auditor=auditor,
        entorno={"SUCURSAL_DEMO": "1"},
        hoy=FECHA_CONSULTA,
        raiz=raiz_tasas,
    )

    assert resultado.negociacion.veredicto.veredicto == "conforme"
    assert turnos_vistos == [turno.id for turno in resultado.negociacion.turnos]


def test_los_limites_del_toml_no_superan_los_del_diseno(tmp_path: Path) -> None:
    """Aunque el TOML pida más, el código recorta turnos, reloj y palabras."""
    ruta = tmp_path / "escena.toml"
    ruta.write_text(
        "\n".join(
            (
                "[negociacion]",
                "max_turnos = 9",
                "tiempo_total_segundos = 40",
                "tiempo_llamada_segundos = 10",
                "max_palabras = 120",
                "",
            )
        ),
        encoding="utf-8",
    )

    limites = cargar_limites_negociacion(ruta)

    assert limites.max_turnos == MAX_TURNOS == 4
    assert limites.tiempo_total_segundos == 15.0
    assert limites.tiempo_llamada_segundos == 4.0
    assert limites.max_palabras == 40
