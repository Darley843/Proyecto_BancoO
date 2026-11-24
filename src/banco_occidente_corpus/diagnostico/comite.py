"""Comité de crédito de una ronda y síntesis determinista.

El comité **no decide el semáforo**: el semáforo lo calcula el motor del
diagnóstico. El comité delibera qué recomendarle a la persona cuando su caso es
amarillo o rojo, con tres miradas que se controlan entre sí
(`docs/COMITE.md`):

- **Riesgo** evalúa la sostenibilidad de la cuota, el endeudamiento y la prueba
  de estrés de ingreso.
- **Comercial** propone hasta dos alternativas, solo de los escenarios que el
  motor precalculó antes de llamar al modelo.
- **Auditor** revisa cifras, promesas, complacencia, alternativas y aviso.

El auditor también existe en código (`auditar`): ninguna cifra inventada, frase
de aprobación, alternativa fuera de los escenarios ni recomendación más
favorable que la de riesgo pasa la deliberación. Las comprobaciones sobre un
texto suelto (cifras, promesas, códigos, productos, aviso y datos personales)
viven en `auditar_texto`, que también usa el auditor de la escena «Pana vs. el
gota a gota». La síntesis es determinística: el semáforo no cambia, gana la
postura más prudente y, si el auditor vuelve a objetar tras una única
corrección, se responde con el texto del diagnóstico. Si la corrección deja la
validación determinística en limpio, la línea de la persona dice que el
auditor está conforme aunque el agente haya objetado: su objeción original se
conserva en `DeliberacionComite.posturas` para la pantalla.

Límites: una sola ronda, máximo cuatro llamadas al modelo (tres agentes, una
corrección y los reintentos por JSON inválido comparten ese tope), tope de
tokens por agente y 30 s en total. El módulo no escribe en la Bóveda ni
modifica el diagnóstico, y solo recibe el `ResultadoDiagnostico` y los
escenarios calculados, nunca el nombre ni el número de la persona.
"""

from __future__ import annotations

import json
import re
import threading
import time
import tomllib
from collections.abc import Callable, Collection, Iterator, Mapping, Sequence
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Literal

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ..asistente.metricas import extraer_metricas
from ..asistente.modelo import crear_modelo
from ..asistente.prompts import cargar_prompt
from ..asistente.validacion import cifras_duras, detectar_pii, normalizar_cifra_numerica
from ..canal.contratos import EntradaDiagnostico, RangoDecimal, ResultadoDiagnostico
from ..config import PROJECT_ROOT
from ..tablero.tasas import NOMBRES_PRODUCTO
from . import motor
from .escenarios import formatear_pesos, formatear_rango

#: Archivo versionado con los límites del comité.
RUTA_CONFIG = PROJECT_ROOT / "config" / "diagnostico.toml"

#: Roles del comité, en el orden en que se sintetizan.
ROLES: tuple[str, ...] = ("riesgo", "comercial", "auditor")
#: Roles que deliberan en paralelo; el auditor revisa después sus posturas.
ROLES_INICIALES: tuple[str, ...] = ("riesgo", "comercial")

#: Códigos de los escenarios que el motor precalcula para el comité.
CODIGOS_ESCENARIO: tuple[str, ...] = (
    "plazo_mas_largo",
    "monto_20_por_ciento_menos",
    "compra_de_cartera",
    "estres_de_ingreso",
)

#: Códigos que el comercial puede ofrecer; el estrés es una prueba, no una oferta.
CODIGOS_ALTERNATIVA: tuple[str, ...] = tuple(
    codigo for codigo in CODIGOS_ESCENARIO if codigo != "estres_de_ingreso"
)

#: Posturas válidas por rol. `abstencion` cubre el fallo o la falta de evidencia.
POSTURAS_RIESGO: frozenset[str] = frozenset(
    {"favorable", "con_condiciones", "desfavorable", "abstencion"}
)
POSTURAS_AUDITOR: frozenset[str] = frozenset({"conforme", "objeta", "abstencion"})

#: Orden de prudencia: menor es más prudente y manda en la síntesis.
ORDEN_POSTURA: dict[str, int] = {
    "desfavorable": 0,
    "con_condiciones": 1,
    "favorable": 2,
}

#: Cómo se escribe cada postura en la recomendación que recibe la persona. La
#: deliberación interna sigue usando los valores del contrato (`posturas`).
POSTURA_LEGIBLE: dict[str, str] = {
    "favorable": "favorable",
    "con_condiciones": "con condiciones",
    "desfavorable": "desfavorable",
    "abstencion": "se abstuvo",
    "conforme": "conforme",
    "objeta": "objeta",
}

#: Valores por defecto si el TOML no trae la sección `[comite]`.
MAX_LLAMADAS = 4
MAX_TOKENS_AGENTE = 3_000
TIEMPO_MAXIMO_SEGUNDOS = 30.0
MAX_ALTERNATIVAS = 2
#: Por defecto el comité no razona: fue el modo más estable y barato en la demo.
RAZONAMIENTO = False
#: Temperatura 0 en los tres agentes, incluido el auditor: menos variación entre corridas.
TEMPERATURA = 0.0

#: Intentos por agente: el primero y un reintento si la salida no es JSON válido.
MAX_INTENTOS_AGENTE = 2

#: Excepciones de salida que justifican el reintento por JSON inválido o truncado.
_ERRORES_REINTENTABLES = frozenset(
    {
        "LengthFinishReasonError",
        "ContentFilterFinishReasonError",
        "OutputParserException",
    }
)

#: Frases que prometen una aprobación; el auditor las rechaza.
_PROMESAS = re.compile(
    r"\b("
    r"aprobad[oa]s?|aprobaci[oó]n|aprobamos|preaprobad[oa]|"
    r"garantizad[oa]s?|garantizamos|"
    r"te lo dan|te la dan|te lo aprueban|te la aprueban|"
    r"sin problema|seguro que|definitiv[oa]"
    r")\b",
    re.IGNORECASE,
)
#: Palabras que niegan una promesa cuando la preceden de forma inmediata.
_NEGACIONES = re.compile(
    r"\b(?:no|nunca|ni|sin|ninguna|ninguno|jamás|jamas)\b",
    re.IGNORECASE,
)
#: Expresiones que introducen o atenúan la frase; nunca niegan la promesa.
_NEGACIONES_EXCLUIDAS = re.compile(
    r"\bno(?:\s+dudes|\s+solo|\s+sólo|\s+te\s+preocupes)\b|\bsin\s+duda\b",
    re.IGNORECASE,
)
#: Signos que cierran la frase o la cláusula: una negación no puede cruzarlos.
_CORTES_FRASE = re.compile(r"[,.:;!?\r\n]")
#: Palabras de enlace que pueden quedar entre la negación y la promesa.
_ENLACES = frozenset(
    {
        # Artículos y preposiciones.
        "un",
        "una",
        "unos",
        "unas",
        "el",
        "la",
        "los",
        "las",
        "de",
        "del",
        "al",
        "a",
        # Pronombres y formas de «ser», «estar» y «quedar».
        "te",
        "lo",
        "le",
        "les",
        "se",
        "nos",
        "me",
        "está",
        "están",
        "es",
        "son",
        "será",
        "queda",
        "quedan",
        "fue",
        # Verbos típicos del descargo.
        "hay",
        "garantiza",
        "garantizan",
        "garantizar",
        "asegura",
        "aseguran",
        "implica",
        "significa",
        "constituye",
        "representa",
        "equivale",
        # Modales.
        "podemos",
        "puedo",
        "puede",
        "pueden",
        # Atenuante.
        "siquiera",
    }
)
#: Negaciones que admiten un sustantivo antes de los enlaces.
_NEGACIONES_CON_SUSTANTIVO = frozenset({"ninguna", "ninguno"})
#: Máximo de palabras entre la negación y la promesa.
_MAX_PALABRAS_ENTRE_NEGACION_Y_PROMESA = 3
_CODIGO = re.compile(r"\[([a-z0-9_]+)\]")
_FECHA_ISO = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")

#: Números estructurales que no son cifras del caso (conteos y porcentajes).
_CIFRAS_ESTRUCTURALES = frozenset({"0", "1", "2", "3", "10", "20", "30", "40", "100"})

#: Porcentajes de la prueba de estrés de ingreso (independiente y dependiente).
PORCENTAJES_ESTRES: tuple[int, ...] = (10, 20)

#: Frase con la que la recomendación ofrece hablar con un asesor.
_OFERTA_ASESOR = "habla con un asesor"

#: Hallazgo por datos personales cuando no se dice dónde aparecieron.
MENSAJE_PII = "Datos personales en el texto."

#: Línea corta del auditor cuando no objeta; el detalle va en `posturas`.
AUDITOR_CONFORME = "Auditor: revisó las cifras y está conforme"

#: Motivo genérico de una abstención por fallo; nunca expone el error crudo.
MOTIVO_FALLO = "El agente no pudo responder con los datos del caso."

#: Motivo cuando riesgo y comercial se abstienen y el auditor no se convoca.
MOTIVO_SIN_AUDITOR = "No se convocó: riesgo y comercial se abstuvieron."

#: Primera línea de la recomendación, en lenguaje de la persona y sin códigos.
APERTURA_RECOMENDACION: dict[str, str] = {
    "apto": "El comité de crédito considera viable la solicitud con los datos del caso.",
    "apto_con_condiciones": (
        "El comité de crédito considera viable la solicitud, con condiciones."
    ),
    "no_apto": ("El comité de crédito no recomienda este crédito con las condiciones actuales."),
    "requiere_asesor": (
        "El comité de crédito no logró una postura completa; conviene revisar el caso."
    ),
}

#: Identificadores snake_case (códigos de escenario y alertas del motor).
_IDENTIFICADOR = re.compile(r"\b[a-z0-9]+(?:_[a-z0-9]+)+\b")


class PosturaAgente(BaseModel):
    """Opinión estructurada de un rol del comité.

    La postura es texto porque cada rol tiene su propio vocabulario: riesgo y
    comercial usan `favorable`, `con_condiciones`, `desfavorable` o
    `abstencion`; el auditor usa `conforme`, `objeta` o `abstencion`.
    """

    model_config = ConfigDict(extra="forbid")

    agente: Literal["riesgo", "comercial", "auditor"]
    postura: str = Field(min_length=1)
    argumentos: list[str] = Field(default_factory=list, max_length=3)
    evidencia: list[str] = Field(default_factory=list)


#: DeepSeek Flash en modo pensamiento rechaza `tool_choice` con un 400; el
#: esquema viaja en el prompt y la respuesta se valida con Pydantic.
METODO_ESTRUCTURADO = "json_mode"

_ESQUEMA_JSON = json.dumps(PosturaAgente.model_json_schema(), ensure_ascii=False, indent=2)

#: Instrucción de `json_mode`: sin ella el proveedor no conoce la forma esperada.
INSTRUCCION_JSON = (
    "Responde solo con un objeto JSON válido, sin texto adicional, sin comentarios "
    "y sin cercas de código. Debe cumplir exactamente este esquema JSON Schema:\n"
    f"{_ESQUEMA_JSON}"
)


class DeliberacionComite(BaseModel):
    """Resultado de una ronda del comité y su síntesis determinista."""

    model_config = ConfigDict(extra="forbid")

    posturas: list[PosturaAgente] = Field(min_length=3, max_length=3)
    recomendacion: str = Field(min_length=1)
    alternativas: list[str] = Field(default_factory=list, max_length=MAX_ALTERNATIVAS)
    hallazgos_auditor: list[str] = Field(default_factory=list)
    ofrece_asesor: bool


class EscenarioComite(BaseModel):
    """Escenario que el motor precalculó antes de llamar al modelo."""

    model_config = ConfigDict(extra="forbid")

    codigo: Literal[
        "plazo_mas_largo",
        "monto_20_por_ciento_menos",
        "compra_de_cartera",
        "estres_de_ingreso",
    ]
    descripcion: str
    cuota_mensual: RangoDecimal | None = None
    semaforo: Literal["verde", "amarillo", "rojo"] | None = None
    razon_endeudamiento: Decimal | None = None
    margen_despues_cuota: Decimal | None = None


@dataclass(frozen=True, slots=True)
class LimitesComite:
    """Límites de la deliberación: llamadas, tokens, reloj y temperatura."""

    max_llamadas: int = MAX_LLAMADAS
    max_tokens_agente: int = MAX_TOKENS_AGENTE
    tiempo_maximo_segundos: float = TIEMPO_MAXIMO_SEGUNDOS
    max_alternativas: int = MAX_ALTERNATIVAS
    razonamiento: bool = RAZONAMIENTO
    temperatura: float = TEMPERATURA


@dataclass(slots=True)
class RegistroComite:
    """Uso de cada llamada al modelo, para mostrar tokens y costo en la demo."""

    llamadas: list[dict[str, Any]] = field(default_factory=list)

    @property
    def total_llamadas(self) -> int:
        """Número de llamadas al modelo registradas, incluidas las fallidas."""
        return len(self.llamadas)

    def anotar(
        self,
        agente: str,
        metricas: Mapping[str, Any] | None,
        segundos: float,
        error: str | None = None,
        *,
        clase_error: str | None = None,
    ) -> None:
        """Guarda el uso y el tiempo de una llamada al modelo.

        Args:
            agente: rol que hizo la llamada.
            metricas: uso devuelto por LangChain, en el formato de
                `asistente.metricas.extraer_metricas`.
            segundos: duración de la llamada.
            error: mensaje si la llamada falló; vacío o `None` si fue bien.
            clase_error: nombre de la clase de la excepción o del error de
                validación; solo lo muestra la demo, nunca la recomendación.
        """
        self.llamadas.append(
            {
                "agente": agente,
                "metricas": dict(metricas or {}),
                "segundos": segundos,
                "error": error or "",
                "clase_error": clase_error or "",
            }
        )


def cargar_limites(ruta: Path | None = None) -> LimitesComite:
    """Lee los límites del comité de `config/diagnostico.toml`.

    Args:
        ruta: archivo TOML alternativo; por defecto `config/diagnostico.toml`.

    Returns:
        Los límites con los valores por defecto completados.

    Raises:
        FileNotFoundError: si el archivo no existe.
    """
    archivo = Path(ruta) if ruta is not None else RUTA_CONFIG
    with archivo.open("rb") as fh:
        datos = tomllib.load(fh)
    seccion = dict(datos.get("comite", {}))
    return LimitesComite(
        max_llamadas=int(seccion.get("max_llamadas", MAX_LLAMADAS)),
        max_tokens_agente=int(seccion.get("max_tokens_agente", MAX_TOKENS_AGENTE)),
        tiempo_maximo_segundos=float(seccion.get("tiempo_maximo_segundos", TIEMPO_MAXIMO_SEGUNDOS)),
        max_alternativas=int(seccion.get("max_alternativas", MAX_ALTERNATIVAS)),
        razonamiento=bool(seccion.get("razonamiento", RAZONAMIENTO)),
        temperatura=float(seccion.get("temperatura", TEMPERATURA)),
    )


def deliberar(
    entrada: EntradaDiagnostico,
    resultado: ResultadoDiagnostico,
    *,
    modelo: BaseChatModel | None = None,
    calcular: Callable[[EntradaDiagnostico], ResultadoDiagnostico] | None = None,
    hoy: date | None = None,
    raiz: Path | None = None,
    limites: LimitesComite | None = None,
    registro: RegistroComite | None = None,
) -> DeliberacionComite | None:
    """Convoca el comité para un diagnóstico amarillo o rojo con cuota.

    En verde, en rojo por capacidad negativa (sin cuota) y en los productos que
    no simulan crédito devuelve `None` sin llamar al modelo.

    Args:
        entrada: insumos del diagnóstico, ya validados.
        resultado: resultado del motor; su semáforo no se modifica.
        modelo: modelo de chat; por defecto se crea el DeepSeek del comité con
            el modo de razonamiento que fija `[comite]` en el TOML.
        calcular: motor determinista para los escenarios; por defecto
            `diagnostico.motor.calcular`.
        hoy: fecha con la que se comprueba la vigencia de la tasa.
        raiz: carpeta de tablas Gold alternativa.
        limites: límites de llamadas, tokens y tiempo; por defecto el TOML.
        registro: colector opcional de tokens y tiempos de cada llamada.

    Returns:
        La deliberación con las tres posturas, la recomendación, las
        alternativas y los hallazgos del auditor; `None` si no hay comité.

    Raises:
        ValueError: si la entrada no coincide con la del resultado.
    """
    if resultado.semaforo not in {"amarillo", "rojo"}:
        return None
    if resultado.cuota_mensual is None:
        return None
    if entrada != resultado.entrada:
        raise ValueError("la entrada no coincide con la del resultado del diagnóstico")

    ajustes = limites if limites is not None else cargar_limites()
    escenarios = construir_escenarios(
        entrada,
        resultado,
        calcular=calcular,
        hoy=hoy,
        raiz=raiz,
    )
    if modelo is None:
        modelo = crear_modelo(
            temperatura=ajustes.temperatura,
            max_tokens=ajustes.max_tokens_agente,
            timeout=ajustes.tiempo_maximo_segundos,
            razonamiento=ajustes.razonamiento,
        )

    presupuesto = _Presupuesto(ajustes.max_llamadas, ajustes.tiempo_maximo_segundos)
    contexto = _contexto_del_caso(resultado, escenarios)
    posturas = _ronda_inicial(modelo, contexto, ajustes, presupuesto, registro)
    posturas["riesgo"] = _ajustar_riesgo_por_estres(posturas["riesgo"], escenarios)
    if _sin_posturas(posturas):
        # Sin posturas de riesgo ni comercial no hay nada que auditar: el
        # auditor no se convoca y se responde con el texto del diagnóstico.
        posturas["auditor"] = _abstencion("auditor", MOTIVO_SIN_AUDITOR)
        return _respuesta_sin_comite(
            posturas,
            resultado,
            auditar(list(posturas.values()), resultado, escenarios),
        )
    posturas["auditor"] = _revisar(modelo, contexto, posturas, presupuesto, registro)

    hallazgos = auditar(list(posturas.values()), resultado, escenarios)
    if posturas["auditor"].postura == "objeta" or hallazgos:
        # La objeción original se conserva en `posturas` para la pantalla; el
        # texto de la persona solo la muestra si la corrección no la resuelve.
        originales = _sin_repetir([*_hallazgos_del_auditor(posturas["auditor"]), *hallazgos])
        pendientes = _corregir(
            modelo,
            contexto,
            posturas,
            resultado,
            escenarios,
            ajustes,
            presupuesto,
            registro,
            originales,
        )
        if pendientes:
            return _respuesta_sin_comite(
                posturas, resultado, _sin_repetir([*originales, *pendientes])
            )
        # La validación determinística pasa: la línea del auditor para la
        # persona es «conforme», sin repetir una objeción ya corregida.
        hallazgos = []

    alternativas = _elegir_alternativas(posturas["comercial"], escenarios, ajustes.max_alternativas)
    return _sintetizar(posturas, resultado, alternativas, hallazgos, escenarios)


def construir_escenarios(
    entrada: EntradaDiagnostico,
    resultado: ResultadoDiagnostico,
    *,
    calcular: Callable[[EntradaDiagnostico], ResultadoDiagnostico] | None = None,
    hoy: date | None = None,
    raiz: Path | None = None,
    config: motor.ConfigDiagnostico | None = None,
) -> list[EscenarioComite]:
    """Precalcula con el motor los escenarios que verá el comité.

    Son el siguiente plazo de la entrevista, un monto 20 % menor, la compra de
    cartera si hay cuotas actuales y la prueba de estrés de ingreso (−10 % para
    empleado o pensionado y −20 % para independiente) con la misma cuota.

    Args:
        entrada: insumos del diagnóstico original.
        resultado: resultado del motor original.
        calcular: motor determinista; por defecto `diagnostico.motor.calcular`.
        hoy: fecha con la que se comprueba la vigencia de la tasa.
        raiz: carpeta de tablas Gold alternativa.
        config: configuración ya cargada de `config/diagnostico.toml`.

    Returns:
        Los escenarios que se pudieron calcular, en orden estable.

    Raises:
        ValueError: si el resultado no tiene una cuota simulada.
    """
    if resultado.cuota_mensual is None:
        raise ValueError("el comité solo se convoca con una cuota simulada")
    ajustes = config if config is not None else motor.cargar_config()
    motor_calculo = calcular if calcular is not None else _motor_por_defecto(hoy, raiz)
    escenarios: list[EscenarioComite] = []

    if entrada.monto_credito is not None and entrada.plazo_meses is not None:
        siguiente = _siguiente_plazo(entrada, ajustes)
        if siguiente is not None:
            otro = motor_calculo(entrada.model_copy(update={"plazo_meses": siguiente}))
            escenarios.append(
                _escenario(
                    "plazo_mas_largo",
                    f"Ampliar el plazo a {siguiente} meses",
                    otro,
                    resultado.cuota_mensual,
                )
            )

        menor = (entrada.monto_credito * Decimal("0.8")).quantize(
            Decimal(1), rounding=ROUND_HALF_UP
        )
        if menor >= ajustes.monto_minimo:
            otro = motor_calculo(entrada.model_copy(update={"monto_credito": menor}))
            escenarios.append(
                _escenario(
                    "monto_20_por_ciento_menos",
                    f"Reducir el monto a {formatear_pesos(menor)} (20 % menos)",
                    otro,
                    resultado.cuota_mensual,
                )
            )

    if entrada.cuotas_deudas > 0 and entrada.producto != "compra_cartera":
        trasladar = entrada.cuota_trasladar or entrada.cuotas_deudas
        otro = motor_calculo(
            entrada.model_copy(
                update={
                    "producto": "compra_cartera",
                    "cuota_trasladar": min(trasladar, entrada.cuotas_deudas),
                }
            )
        )
        escenarios.append(
            _escenario(
                "compra_de_cartera",
                "Trasladar las cuotas actuales a una compra de cartera",
                otro,
                resultado.cuota_mensual,
            )
        )

    factor = Decimal("0.8") if entrada.vinculacion == "independiente" else Decimal("0.9")
    ingreso_estres = (entrada.ingreso_mensual * factor).quantize(Decimal(1), rounding=ROUND_HALF_UP)
    otro = motor_calculo(entrada.model_copy(update={"ingreso_mensual": ingreso_estres}))
    porcentaje = 20 if entrada.vinculacion == "independiente" else 10
    escenarios.append(
        _escenario(
            "estres_de_ingreso",
            f"Prueba de estrés: ingreso {porcentaje} % menor "
            f"({formatear_pesos(ingreso_estres)}), misma cuota",
            otro,
            resultado.cuota_mensual,
        )
    )
    return escenarios


def auditar_texto(
    texto: str,
    *,
    cifras_permitidas: Collection[str] | None = None,
    revisar_promesas: bool = True,
    codigos_permitidos: Collection[str] | None = None,
    productos_permitidos: Collection[str] | None = None,
    aviso: str | None = None,
    mensaje_pii: str = MENSAJE_PII,
) -> list[str]:
    """Revisa un texto con las comprobaciones determinísticas del auditor.

    Es la parte del auditor que no depende del comité: `auditar` la aplica a
    cada postura y a la recomendación final, y el auditor de la escena «Pana
    vs. el gota a gota» la aplica a cada turno. Cada comprobación se activa
    solo si recibe su referencia, y los hallazgos salen siempre en el mismo
    orden: cifras, promesas, códigos, productos, aviso y datos personales.

    Args:
        texto: lo que se revisa.
        cifras_permitidas: cifras normalizadas (solo dígitos, como las devuelve
            `cifras_duras`) que el texto puede citar; con ``None`` no se
            revisan cifras.
        revisar_promesas: si busca frases que prometen una aprobación.
        codigos_permitidos: códigos que el texto puede citar entre corchetes,
            como ``[plazo_mas_largo]``; con ``None`` no se revisan.
        productos_permitidos: nombres de producto del Tablero, en minúsculas,
            que el texto puede mencionar; con ``None`` no se revisan.
        aviso: texto que debe aparecer completo; con ``None`` no se exige.
        mensaje_pii: hallazgo que se reporta si el texto trae datos personales.

    Returns:
        Los hallazgos en español, sin repetir; una lista vacía significa que el
        texto pasa.
    """
    hallazgos: list[str] = []
    if cifras_permitidas is not None:
        for cifra in sorted(cifras_duras(texto)):
            if cifra not in cifras_permitidas:
                hallazgos.append(f"Cifra no presente en la entrada: {cifra}")
    if revisar_promesas:
        for frase in _promesas(texto):
            hallazgos.append(f"Promesa de aprobación: «{frase}»")
    if codigos_permitidos is not None:
        for codigo in _CODIGO.findall(texto.casefold()):
            if codigo not in codigos_permitidos:
                hallazgos.append(f"Alternativa fuera de los escenarios: [{codigo}]")
    if productos_permitidos is not None:
        for producto in _productos_mencionados(_sin_identificadores(texto)):
            if producto not in productos_permitidos:
                hallazgos.append(f"Producto fuera de los escenarios: {producto}")
    if aviso is not None and aviso not in texto:
        hallazgos.append("Falta el aviso orientativo.")
    if detectar_pii(texto) is not None:
        hallazgos.append(mensaje_pii)
    return _sin_repetir(hallazgos)


def auditar(
    posturas: Sequence[PosturaAgente],
    resultado: ResultadoDiagnostico,
    escenarios: Sequence[EscenarioComite],
    *,
    recomendacion: str | None = None,
) -> list[str]:
    """Aplica la lista de chequeo del auditor de forma determinística.

    Revisa cifras, promesas de aprobación, alternativas fuera de los escenarios
    (solo en la postura del comercial), complacencia frente a la postura de
    riesgo, datos personales y, cuando se pasa la recomendación final, el aviso
    orientativo que la síntesis agrega de forma determinística. Ese aviso no se
    exige a las posturas de riesgo ni de comercial.

    Args:
        posturas: opiniones de los tres agentes.
        resultado: resultado del motor que sostiene las cifras.
        escenarios: escenarios precalculados.
        recomendacion: texto final, si ya se sintetizó.

    Returns:
        Los hallazgos en español; una lista vacía significa que el auditor no
        objeta.
    """
    hallazgos: list[str] = []
    permitidas = _cifras_permitidas(resultado, escenarios)
    productos = _productos_permitidos(resultado, escenarios)

    for postura in posturas:
        if postura.agente == "auditor" or postura.postura == "abstencion":
            continue
        hallazgos.extend(
            auditar_texto(
                _texto_de(postura),
                cifras_permitidas=permitidas,
                codigos_permitidos=CODIGOS_ESCENARIO,
                # Solo las alternativas del comercial se contrastan con el
                # catálogo: una alerta como `vivienda_primera_cuota` en la
                # postura de riesgo no es un producto fuera de los escenarios.
                productos_permitidos=productos if postura.agente == "comercial" else None,
                mensaje_pii=f"Datos personales en la postura de {postura.agente}",
            )
        )

    riesgo = _buscar_postura(posturas, "riesgo")
    comercial = _buscar_postura(posturas, "comercial")
    if (
        riesgo is not None
        and comercial is not None
        and "abstencion" not in {riesgo.postura, comercial.postura}
        and riesgo.postura in ORDEN_POSTURA
        and comercial.postura in ORDEN_POSTURA
        and _orden(comercial.postura) > _orden(riesgo.postura)
    ):
        hallazgos.append("La postura del comercial es más favorable que la de riesgo.")

    if recomendacion is not None:
        etiqueta = _etiqueta_recomendacion(recomendacion)
        if (
            riesgo is not None
            and etiqueta in {"apto", "apto_con_condiciones"}
            and _orden(riesgo.postura) < ORDEN_POSTURA["favorable"]
        ):
            hallazgos.append("La recomendación es más favorable que la postura de riesgo.")
        hallazgos.extend(
            auditar_texto(
                recomendacion,
                revisar_promesas=False,
                aviso=resultado.aviso,
                mensaje_pii="Datos personales en la recomendación.",
            )
        )

    return _sin_repetir(hallazgos)


def _siguiente_plazo(entrada: EntradaDiagnostico, config: motor.ConfigDiagnostico) -> int | None:
    """Busca el siguiente plazo de la entrevista para el producto.

    Args:
        entrada: insumos con el plazo actual.
        config: configuración con los valores de cada opción.

    Returns:
        El plazo inmediatamente mayor, o `None` si ya está en el máximo.
    """
    if entrada.plazo_meses is None:
        return None
    opciones = [
        int(valor)
        for ident, valor in config.valores.items()
        if ident.startswith("plazo.")
        and entrada.producto in config.aplica_a.get(ident, ())
        and valor > entrada.plazo_meses
    ]
    return min(opciones) if opciones else None


def _motor_por_defecto(
    hoy: date | None, raiz: Path | None
) -> Callable[[EntradaDiagnostico], ResultadoDiagnostico]:
    """Envuelve el motor real con la fecha y la raíz pedidas.

    Args:
        hoy: fecha de contraste de la vigencia.
        raiz: carpeta de tablas Gold alternativa.

    Returns:
        Una función que calcula un diagnóstico completo.
    """

    def calcular(entrada: EntradaDiagnostico) -> ResultadoDiagnostico:
        """Calcula el diagnóstico con el motor real y la fecha fijada."""
        return motor.calcular(entrada, hoy=hoy, raiz=raiz)

    return calcular


def _escenario(
    codigo: Literal[
        "plazo_mas_largo",
        "monto_20_por_ciento_menos",
        "compra_de_cartera",
        "estres_de_ingreso",
    ],
    descripcion: str,
    otro: ResultadoDiagnostico,
    cuota_original: RangoDecimal,
) -> EscenarioComite:
    """Arma un escenario con la cuota, el semáforo y el margen recalculados.

    Cuando el motor no simula (por ejemplo, si el estrés deja la capacidad
    negativa), se conserva la cuota original y se calcula el margen con ella:
    así la prueba sigue mostrando el impacto del ingreso estresado.

    Args:
        codigo: código del escenario.
        descripcion: texto determinístico con los datos del escenario.
        otro: resultado del motor para el escenario.
        cuota_original: cuota del diagnóstico original.

    Returns:
        El escenario listo para el modelo y para el auditor.
    """
    cuota = otro.cuota_mensual or cuota_original
    margen = otro.margen_despues_cuota
    if margen is None:
        margen = (otro.capacidad_pago - cuota.hasta).quantize(Decimal(1), rounding=ROUND_HALF_UP)
    razon = otro.razon_endeudamiento or _razon_de(otro, cuota)
    detalle = f"cuota de {formatear_rango(cuota)}"
    if otro.semaforo is not None:
        detalle += f" y semáforo {otro.semaforo}"
    return EscenarioComite(
        codigo=codigo,
        descripcion=f"{descripcion}: {detalle}.",
        cuota_mensual=cuota,
        semaforo=otro.semaforo,
        razon_endeudamiento=razon,
        margen_despues_cuota=margen,
    )


def _razon_de(otro: ResultadoDiagnostico, cuota: RangoDecimal) -> Decimal | None:
    """Calcula la razón de endeudamiento cuando el motor no la pudo dar.

    Args:
        otro: resultado del escenario.
        cuota: cuota usada para la comparación.

    Returns:
        La razón redondeada a cuatro decimales, o `None` si el ingreso es cero.
    """
    ingreso = otro.entrada.ingreso_mensual
    if ingreso <= 0:
        return None
    numerador = otro.entrada.cuotas_deudas + cuota.hasta - (otro.entrada.cuota_trasladar or 0)
    if numerador < 0:
        return None
    return (numerador / ingreso).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def _contexto_del_caso(
    resultado: ResultadoDiagnostico, escenarios: Sequence[EscenarioComite]
) -> dict[str, Any]:
    """Arma el JSON que reciben los agentes, sin nombre ni número.

    Args:
        resultado: diagnóstico completo del motor.
        escenarios: escenarios precalculados.

    Returns:
        El caso con el diagnóstico y los escenarios en formato JSON.
    """
    return {
        "diagnostico": resultado.model_dump(mode="json"),
        "escenarios": [escenario.model_dump(mode="json") for escenario in escenarios],
    }


@dataclass(slots=True)
class _Presupuesto:
    """Controla las llamadas y el reloj total de la deliberación."""

    maximo: int
    tiempo_maximo: float
    inicio: float = field(default_factory=time.monotonic)
    usadas: int = 0
    _candado: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def restante(self) -> float:
        """Segundos que quedan del reloj total."""
        return max(0.0, self.tiempo_maximo - (time.monotonic() - self.inicio))

    def consumir(self) -> bool:
        """Reserva una llamada si quedan presupuesto y tiempo."""
        with self._candado:
            if self.usadas >= self.maximo or self.restante() <= 0:
                return False
            self.usadas += 1
            return True


def _ronda_inicial(
    modelo: BaseChatModel,
    contexto: Mapping[str, Any],
    limites: LimitesComite,
    presupuesto: _Presupuesto,
    registro: RegistroComite | None,
) -> dict[str, PosturaAgente]:
    """Hace las llamadas de riesgo y comercial, en paralelo.

    El auditor no corre aquí: necesita las dos posturas para revisarlas y se
    convoca después (`_revisar`). Un rol que falla, agota su tiempo o devuelve
    un esquema inválido queda como `abstencion`; `_consultar` hace un único
    reintento dentro del mismo presupuesto y no se abre una segunda ronda.

    Args:
        modelo: modelo de chat con salida estructurada.
        contexto: diagnóstico y escenarios del caso.
        limites: límites de la deliberación.
        presupuesto: control de llamadas y tiempo.
        registro: colector opcional de uso.

    Returns:
        La postura de riesgo y la de comercial.
    """
    posturas: dict[str, PosturaAgente] = {}
    ejecutor = ThreadPoolExecutor(max_workers=len(ROLES_INICIALES), thread_name_prefix="comite")
    futuros: dict[Future[PosturaAgente], str] = {
        ejecutor.submit(
            _consultar,
            modelo,
            rol,
            contexto,
            presupuesto=presupuesto,
            registro=registro,
        ): rol
        for rol in ROLES_INICIALES
    }
    try:
        for futuro in as_completed(futuros, timeout=limites.tiempo_maximo_segundos):
            rol = futuros[futuro]
            try:
                posturas[rol] = futuro.result()
            except Exception:  # noqa: BLE001 - el rol queda en abstención
                posturas[rol] = _abstencion(rol, MOTIVO_FALLO)
    except TimeoutError:
        pass
    finally:
        ejecutor.shutdown(wait=False, cancel_futures=True)
    for rol in ROLES_INICIALES:
        posturas.setdefault(rol, _abstencion(rol, "El comité agotó el tiempo."))
    return posturas


def _revisar(
    modelo: BaseChatModel,
    contexto: Mapping[str, Any],
    posturas: Mapping[str, PosturaAgente],
    presupuesto: _Presupuesto,
    registro: RegistroComite | None,
) -> PosturaAgente:
    """Llama al auditor después de riesgo y comercial, con sus dos posturas.

    Args:
        modelo: modelo de chat.
        contexto: diagnóstico y escenarios.
        posturas: posturas de riesgo y comercial.
        presupuesto: control de llamadas y tiempo.
        registro: colector opcional de uso.

    Returns:
        La postura del auditor; una abstención si no hubo llamada o falló.
    """
    return _consultar(
        modelo,
        "auditor",
        contexto,
        revision=[posturas["riesgo"], posturas["comercial"]],
        presupuesto=presupuesto,
        registro=registro,
    )


def _corregir(
    modelo: BaseChatModel,
    contexto: Mapping[str, Any],
    posturas: dict[str, PosturaAgente],
    resultado: ResultadoDiagnostico,
    escenarios: Sequence[EscenarioComite],
    limites: LimitesComite,
    presupuesto: _Presupuesto,
    registro: RegistroComite | None,
    hallazgos: Sequence[str],
) -> list[str]:
    """Hace la única corrección del comercial con los hallazgos del auditor.

    Args:
        modelo: modelo de chat.
        contexto: diagnóstico y escenarios.
        posturas: posturas de la ronda; se reemplaza la del comercial.
        resultado: resultado del motor.
        escenarios: escenarios precalculados.
        limites: límites de la deliberación.
        presupuesto: control de llamadas y tiempo.
        registro: colector opcional de uso.
        hallazgos: hallazgos que motivan la corrección.

    Returns:
        Los hallazgos que quedan después de la corrección.
    """
    correccion = _consultar(
        modelo,
        "comercial",
        contexto,
        hallazgos=list(hallazgos),
        presupuesto=presupuesto,
        registro=registro,
    )
    posturas["comercial"] = correccion
    return auditar(list(posturas.values()), resultado, escenarios)


def _reintentable(exc: BaseException) -> bool:
    """Indica si el fallo es una salida inválida o truncada.

    Un 400, un timeout o un error de red no se reintentan: el reintento es solo
    para el JSON que no llegó a formarse.

    Args:
        exc: excepción lanzada por el modelo o el parser.

    Returns:
        `True` si el fallo corresponde a la salida del modelo.
    """
    return isinstance(exc, ValidationError) or type(exc).__name__ in _ERRORES_REINTENTABLES


def _consultar(
    modelo: BaseChatModel,
    rol: str,
    contexto: Mapping[str, Any],
    *,
    hallazgos: Sequence[str] | None = None,
    revision: Sequence[PosturaAgente] | None = None,
    presupuesto: _Presupuesto,
    registro: RegistroComite | None,
) -> PosturaAgente:
    """Llama a un agente con salida estructurada y normaliza su postura.

    Si la salida no es JSON válido, hace un solo reintento dentro del mismo
    presupuesto de llamadas y del reloj total. La clase del error queda en el
    registro, para que la demo explique la abstención sin filtrarla al texto
    que recibe la persona.

    Args:
        modelo: modelo de chat.
        rol: `riesgo`, `comercial` o `auditor`.
        contexto: diagnóstico y escenarios.
        hallazgos: hallazgos del auditor para la corrección, si hay.
        revision: posturas que el auditor debe revisar, si las hay.
        presupuesto: control de llamadas y tiempo.
        registro: colector opcional de uso.

    Returns:
        La postura validada, o una abstención si no hubo llamada o falló.
    """
    if not presupuesto.consumir():
        return _abstencion(rol, "El comité agotó las llamadas o el tiempo.")

    prompt = cargar_prompt(f"comite_{rol}")
    sistema = prompt.sistema
    if prompt.recordatorio:
        sistema = f"{sistema}\n\n{prompt.recordatorio}"
    humano = f"{_mensaje_humano(contexto, hallazgos, revision)}\n\n{INSTRUCCION_JSON}"
    mensajes = [SystemMessage(content=sistema), HumanMessage(content=humano)]

    inicio = time.monotonic()
    metricas: Mapping[str, Any] | None = None
    try:
        runnable = modelo.with_structured_output(
            PosturaAgente,
            method=METODO_ESTRUCTURADO,
            include_raw=True,
        )
    except Exception as exc:  # noqa: BLE001 - el rol queda en abstención
        segundos = time.monotonic() - inicio
        if registro is not None:
            registro.anotar(rol, metricas, segundos, MOTIVO_FALLO, clase_error=type(exc).__name__)
        return _abstencion(rol, MOTIVO_FALLO)

    for intento in range(MAX_INTENTOS_AGENTE):
        mensajes_intento = mensajes
        if intento:
            mensajes_intento = [
                *mensajes,
                HumanMessage(
                    content=(
                        "La respuesta anterior no fue JSON válido. Responde solo "
                        "con el objeto JSON del esquema."
                    )
                ),
            ]
        inicio = time.monotonic()
        metricas = None
        try:
            salida = runnable.invoke(mensajes_intento)
        except Exception as exc:  # noqa: BLE001 - el rol queda en abstención
            segundos = time.monotonic() - inicio
            if registro is not None:
                registro.anotar(
                    rol,
                    _metricas_de_error(exc),
                    segundos,
                    MOTIVO_FALLO,
                    clase_error=type(exc).__name__,
                )
            if _reintentable(exc) and intento + 1 < MAX_INTENTOS_AGENTE and presupuesto.consumir():
                continue
            return _abstencion(rol, MOTIVO_FALLO)

        segundos = time.monotonic() - inicio
        postura, metricas, error, clase_error = _leer_salida(salida)
        if postura is not None:
            normalizada = _normalizar(postura, rol)
            fallo = normalizada.postura == "abstencion"
            if registro is not None:
                registro.anotar(
                    rol,
                    metricas,
                    segundos,
                    MOTIVO_FALLO if fallo else None,
                    clase_error="postura_invalida" if fallo else None,
                )
            return normalizada

        if registro is not None:
            registro.anotar(
                rol,
                metricas,
                segundos,
                MOTIVO_FALLO,
                clase_error=clase_error or "salida_invalida",
            )
        # Un solo reintento, y solo si el presupuesto de llamadas y el reloj
        # todavía alcanzan: el tope total de costo no cambia.
        if intento + 1 >= MAX_INTENTOS_AGENTE or not presupuesto.consumir():
            return _abstencion(rol, MOTIVO_FALLO)

    return _abstencion(rol, MOTIVO_FALLO)


def _leer_salida(
    salida: Any,
) -> tuple[PosturaAgente | None, Mapping[str, Any] | None, str | None, str | None]:
    """Extrae la postura y las métricas de la salida estructurada.

    Args:
        salida: resultado del runnable, con o sin `include_raw`.

    Returns:
        La postura, las métricas del mensaje crudo, el error de validación y la
        clase de ese error; los dos últimos son `None` si no hubo fallo.
    """
    metricas: Mapping[str, Any] | None = None
    error: str | None = None
    clase_error: str | None = None
    if isinstance(salida, dict) and "parsed" in salida:
        crudo = salida.get("raw")
        if isinstance(crudo, BaseMessage):
            metricas = extraer_metricas(crudo)
        fallo = salida.get("parsing_error")
        if fallo is not None:
            error = str(fallo)
            clase_error = type(fallo).__name__ if not isinstance(fallo, str) else None
        salida = salida.get("parsed")
    if salida is None:
        return None, metricas, error, clase_error or "salida_invalida"
    try:
        postura = (
            salida if isinstance(salida, PosturaAgente) else PosturaAgente.model_validate(salida)
        )
    except ValidationError as exc:
        return None, metricas, str(exc), type(exc).__name__
    return postura, metricas, error, clase_error


def _campo(objeto: Any, nombre: str) -> Any:
    """Lee un atributo o una clave de ``model_extra`` sin depender del SDK.

    Args:
        objeto: respuesta del proveedor.
        nombre: atributo buscado.

    Returns:
        El valor encontrado o `None`.
    """
    valor = getattr(objeto, nombre, None)
    if valor is not None:
        return valor
    extra = getattr(objeto, "model_extra", None)
    return extra.get(nombre) if isinstance(extra, Mapping) else None


def _metricas_de_error(exc: BaseException) -> Mapping[str, Any] | None:
    """Recupera el uso de una excepción que trae la respuesta del modelo.

    `LengthFinishReasonError` de OpenAI adjunta la ``completion`` que no se pudo
    parsear porque se agotó ``max_tokens``. De ahí salen `finish_reason` y los
    tokens de salida y razonamiento que la demo muestra al diagnosticar.
    Para el resto de excepciones devuelve `None`.

    Args:
        exc: excepción lanzada por el cliente del modelo.

    Returns:
        Métricas en el formato de `leer_uso`, o `None` si no trae respuesta.
    """
    completion = getattr(exc, "completion", None)
    if completion is None:
        return None
    elecciones = _campo(completion, "choices") or []
    finish = _campo(elecciones[0], "finish_reason") if elecciones else None
    uso = _campo(completion, "usage")
    if uso is None:
        return {"respuesta": {"finish_reason": finish}} if finish else None
    detalles = _campo(uso, "completion_tokens_details")
    valores: dict[str, Any] = {
        "input_tokens": _campo(uso, "prompt_tokens"),
        "output_tokens": _campo(uso, "completion_tokens"),
        "total_tokens": _campo(uso, "total_tokens"),
    }
    razonamiento = _campo(detalles, "reasoning_tokens") if detalles is not None else None
    if razonamiento is not None:
        valores["output_token_details"] = {"reasoning": razonamiento}
    cache = _campo(uso, "prompt_cache_hit_tokens")
    if cache is not None:
        valores["input_token_details"] = {"cache_read": cache}
    return {
        "uso": {clave: valor for clave, valor in valores.items() if valor is not None},
        "respuesta": {"finish_reason": finish},
    }


def _mensaje_humano(
    contexto: Mapping[str, Any],
    hallazgos: Sequence[str] | None,
    revision: Sequence[PosturaAgente] | None = None,
) -> str:
    """Arma el mensaje con el caso, las posturas a revisar y los hallazgos.

    Args:
        contexto: diagnóstico y escenarios.
        hallazgos: hallazgos del auditor.
        revision: posturas de riesgo y comercial que revisa el auditor.

    Returns:
        El texto que recibe el agente.
    """
    partes = [
        "Datos del caso (solo cifras calculadas; no hay datos personales):",
        json.dumps(contexto, ensure_ascii=False, indent=2, default=str),
    ]
    if revision:
        partes.append("\nPosturas a revisar:")
        for postura in revision:
            partes.append(f"- {postura.agente}: {postura.postura}")
            partes.extend(f"  - {argumento}" for argumento in postura.argumentos)
            if postura.evidencia:
                partes.append(f"  - Evidencia: {', '.join(postura.evidencia)}")
    if hallazgos:
        partes.append(
            "\nEl auditor objetó con estos hallazgos; corrige tu postura y no repitas el error:"
        )
        partes.extend(f"- {hallazgo}" for hallazgo in hallazgos)
    partes.append(
        "\nResponde solo con el esquema PosturaAgente y usa únicamente las "
        "cifras y los escenarios anteriores."
    )
    return "\n".join(partes)


def _abstencion(rol: str, motivo: str) -> PosturaAgente:
    """Construye una postura de abstención para un rol que no respondió.

    Args:
        rol: rol del comité.
        motivo: explicación breve.

    Returns:
        La postura con `abstencion` y el motivo como argumento.
    """
    agente: Literal["riesgo", "comercial", "auditor"] = "riesgo"
    if rol == "comercial":
        agente = "comercial"
    elif rol == "auditor":
        agente = "auditor"
    return PosturaAgente(
        agente=agente,
        postura="abstencion",
        argumentos=[motivo[:300]],
        evidencia=[],
    )


def _sin_posturas(posturas: Mapping[str, PosturaAgente]) -> bool:
    """Indica si riesgo y comercial quedaron sin una postura válida.

    Args:
        posturas: posturas de los tres roles.

    Returns:
        `True` si ambos roles iniciales se abstuvieron; la deliberación no
        puede sostener una recomendación propia.
    """
    return all(posturas[rol].postura == "abstencion" for rol in ROLES_INICIALES)


def _agregar_oferta_asesor(lineas: list[str]) -> None:
    """Añade la oferta de asesor solo si la recomendación aún no la trae.

    Args:
        lineas: líneas de la recomendación; se modifican en el sitio.
    """
    if not any(_OFERTA_ASESOR in linea.casefold() for linea in lineas):
        lineas.append("Puedes hablar con un asesor para revisar tu caso.")


def _normalizar(postura: PosturaAgente, rol: str) -> PosturaAgente:
    """Valida que la postura pertenezca al rol y la deja en abstención si no.

    Args:
        postura: salida del modelo.
        rol: rol esperado.

    Returns:
        La postura validada o una abstención.
    """
    if postura.agente != rol:
        return _abstencion(rol, f"El agente respondió como «{postura.agente}».")
    validas = POSTURAS_AUDITOR if rol == "auditor" else POSTURAS_RIESGO
    if postura.postura not in validas:
        return _abstencion(rol, f"Postura no reconocida: «{postura.postura}».")
    return postura


def _ajustar_riesgo_por_estres(
    postura: PosturaAgente, escenarios: Sequence[EscenarioComite]
) -> PosturaAgente:
    """Impide una postura de riesgo favorable si el estrés aprieta el margen.

    Si con el ingreso estresado el margen se vuelve negativo o el semáforo pasa
    a rojo, riesgo no puede quedar en `favorable`: se baja a `con_condiciones`.

    Args:
        postura: postura del agente de riesgo.
        escenarios: escenarios precalculados.

    Returns:
        La misma postura, ajustada si el estrés lo exige.
    """
    if postura.postura != "favorable":
        return postura
    estres = next(
        (escenario for escenario in escenarios if escenario.codigo == "estres_de_ingreso"),
        None,
    )
    if estres is None:
        return postura
    if estres.semaforo != "rojo" and (estres.margen_despues_cuota or 0) >= 0:
        return postura
    argumentos = list(postura.argumentos)
    detalle = "La prueba de estrés de ingreso no deja margen suficiente."
    if len(argumentos) < 3:
        argumentos.append(detalle)
    return postura.model_copy(update={"postura": "con_condiciones", "argumentos": argumentos})


def _elegir_alternativas(
    comercial: PosturaAgente, escenarios: Sequence[EscenarioComite], maximo: int
) -> list[str]:
    """Elige hasta dos alternativas, solo de los escenarios precalculados.

    Primero respeta los códigos que propuso el comercial; si faltan, completa
    con los escenarios que mejoran el semáforo y la razón de endeudamiento.

    Args:
        comercial: postura del agente comercial.
        escenarios: escenarios precalculados.
        maximo: número máximo de alternativas.

    Returns:
        Las descripciones de las alternativas elegidas.
    """
    disponibles: dict[str, EscenarioComite] = {
        escenario.codigo: escenario
        for escenario in escenarios
        if escenario.codigo in CODIGOS_ALTERNATIVA
    }
    elegidos: list[str] = []
    for codigo in _CODIGO.findall(_texto_de(comercial).casefold()):
        if codigo in disponibles and codigo not in elegidos:
            elegidos.append(codigo)
        if len(elegidos) >= maximo:
            break

    orden = {codigo: posicion for posicion, codigo in enumerate(CODIGOS_ALTERNATIVA)}
    resto = sorted(
        (codigo for codigo in disponibles if codigo not in elegidos),
        key=lambda codigo: (
            _orden_semaforo(disponibles[codigo].semaforo),
            disponibles[codigo].razon_endeudamiento
            if disponibles[codigo].razon_endeudamiento is not None
            else Decimal(99),
            orden[codigo],
        ),
    )
    elegidos.extend(resto[: max(0, maximo - len(elegidos))])
    return [disponibles[codigo].descripcion for codigo in elegidos]


def _sintetizar(
    posturas: Mapping[str, PosturaAgente],
    resultado: ResultadoDiagnostico,
    alternativas: Sequence[str],
    hallazgos: Sequence[str],
    escenarios: Sequence[EscenarioComite],
) -> DeliberacionComite:
    """Aplica las reglas determinísticas de síntesis de `docs/COMITE.md`.

    Args:
        posturas: posturas de los tres roles.
        resultado: resultado del motor; su semáforo no cambia.
        alternativas: descripciones elegidas de los escenarios.
        hallazgos: hallazgos finales del auditor.
        escenarios: escenarios precalculados, para citar el estrés.

    Returns:
        La deliberación con la recomendación y la oferta de asesor.
    """
    riesgo = posturas["riesgo"]
    comercial = posturas["comercial"]
    auditor = posturas["auditor"]
    etiqueta = _etiqueta(riesgo, comercial)
    ofrece = resultado.semaforo == "rojo" or etiqueta == "requiere_asesor"

    lineas = [
        f"{APERTURA_RECOMENDACION[etiqueta]} Es una opinión del comité de crédito "
        "y no una aprobación; la decisión final corresponde a un asesor.",
        f"Semáforo del motor: {resultado.semaforo} (no cambia).",
        _linea_postura(riesgo),
        _linea_postura(comercial),
        _linea_auditor(auditor, hallazgos),
    ]
    if alternativas:
        lineas.append("Alternativas: " + " | ".join(alternativas))
    estres = next(
        (escenario for escenario in escenarios if escenario.codigo == "estres_de_ingreso"),
        None,
    )
    if estres is not None and estres.margen_despues_cuota is not None:
        lineas.append(
            f"Estrés de ingreso: margen de {formatear_pesos(estres.margen_despues_cuota)}."
        )
    if ofrece:
        _agregar_oferta_asesor(lineas)
    lineas.append(resultado.aviso)

    return DeliberacionComite(
        posturas=[riesgo, comercial, auditor],
        recomendacion="\n".join(texto_para_la_persona(linea) for linea in lineas),
        alternativas=list(alternativas)[:MAX_ALTERNATIVAS],
        hallazgos_auditor=list(hallazgos),
        ofrece_asesor=ofrece,
    )


def _etiqueta(riesgo: PosturaAgente, comercial: PosturaAgente) -> str:
    """Elige la recomendación con la postura más prudente.

    Args:
        riesgo: postura del agente de riesgo.
        comercial: postura del agente comercial.

    Returns:
        `requiere_asesor`, `no_apto`, `apto_con_condiciones` o `apto`.
    """
    if "abstencion" in {riesgo.postura, comercial.postura}:
        return "requiere_asesor"
    if "desfavorable" in {riesgo.postura, comercial.postura}:
        return "no_apto"
    if "con_condiciones" in {riesgo.postura, comercial.postura}:
        return "apto_con_condiciones"
    return "apto"


def texto_para_la_persona(texto: str) -> str:
    """Escribe una línea de la recomendación sin códigos internos.

    Las posturas y los códigos de escenario son el vocabulario interno de la
    deliberación; la persona recibe el mismo contenido en lenguaje natural. Los
    corchetes de código se eliminan y cualquier identificador snake_case que
    quede en un argumento del modelo se escribe con espacios.

    Args:
        texto: línea o párrafo de la recomendación.

    Returns:
        El texto sin códigos entre corchetes, sin guiones bajos y con los
        espacios repetidos colapsados.
    """
    sin_codigos = _CODIGO.sub("", texto)
    sin_guiones = _IDENTIFICADOR.sub(
        lambda coincidencia: coincidencia.group(0).replace("_", " "), sin_codigos
    )
    return re.sub(r"[ \t]{2,}", " ", sin_guiones).strip()


def _linea_postura(postura: PosturaAgente) -> str:
    """Escribe la postura de un agente en una línea, en lenguaje natural.

    Args:
        postura: opinión del agente.

    Returns:
        Texto con el rol, la postura legible y su primer argumento.
    """
    legible = POSTURA_LEGIBLE.get(postura.postura, postura.postura.replace("_", " "))
    detalle = f" — {postura.argumentos[0]}" if postura.argumentos else ""
    return f"{postura.agente.capitalize()}: {legible}{detalle}"


def _linea_auditor(postura: PosturaAgente, hallazgos: Sequence[str]) -> str:
    """Resume la auditoría en una línea corta para la persona.

    El detalle completo de la revisión no se pierde: sigue en
    `DeliberacionComite.posturas`, que la app muestra en pantalla.

    Args:
        postura: postura del auditor.
        hallazgos: hallazgos que quedan después de la corrección.

    Returns:
        `Auditor: revisó las cifras y está conforme`, el hallazgo principal si
        sigue objetando, o la línea completa si se abstuvo.
    """
    if postura.postura == "conforme":
        return AUDITOR_CONFORME
    if postura.postura == "objeta":
        if not hallazgos:
            # Objetó antes de la corrección, pero la validación determinística
            # pasó: el texto de la persona no puede contradecir la recomendación.
            return AUDITOR_CONFORME
        principal = hallazgos[0]
        return f"Auditor: {principal}"
    return _linea_postura(postura)


def _respuesta_sin_comite(
    posturas: Mapping[str, PosturaAgente],
    resultado: ResultadoDiagnostico,
    hallazgos: Sequence[str],
) -> DeliberacionComite:
    """Responde con el texto determinístico del diagnóstico, sin comité.

    Es la salida cuando riesgo y comercial se abstienen (no se convoca al
    auditor) o cuando el auditor vuelve a objetar después de la única
    corrección permitida.

    Args:
        posturas: posturas de los tres roles.
        resultado: resultado del motor.
        hallazgos: hallazgos que impiden confiar en la deliberación.

    Returns:
        La deliberación con la recomendación directa del diagnóstico.
    """
    lineas = [
        "El comité no logró una deliberación conforme; te damos el resultado "
        "directo del diagnóstico.",
        f"Semáforo: {resultado.semaforo}.",
        *resultado.motivos,
        *resultado.recomendaciones,
    ]
    if resultado.semaforo == "rojo":
        _agregar_oferta_asesor(lineas)
    lineas.append(resultado.aviso)
    return DeliberacionComite(
        posturas=[posturas[rol] for rol in ROLES],
        recomendacion="\n".join(texto_para_la_persona(linea) for linea in lineas),
        alternativas=[],
        hallazgos_auditor=list(hallazgos),
        ofrece_asesor=resultado.semaforo == "rojo",
    )


def _cifras_permitidas(
    resultado: ResultadoDiagnostico, escenarios: Sequence[EscenarioComite]
) -> set[str]:
    """Construye el conjunto de cifras que el caso autoriza citar.

    Args:
        resultado: resultado del motor.
        escenarios: escenarios precalculados.

    Returns:
        Cifras normalizadas (solo dígitos) que aparecen en la entrada.
    """
    textos = [resultado.model_dump_json()]
    textos.extend(escenario.model_dump_json() for escenario in escenarios)
    permitidas = cifras_duras("\n".join(textos))
    permitidas.update(_CIFRAS_ESTRUCTURALES)
    for fecha in _FECHA_ISO.findall("\n".join(textos)):
        permitidas.update({str(int(parte)) for parte in fecha})
    for valor in _decimales(resultado.model_dump(mode="json")):
        _agregar_equivalente(permitidas, valor)
    for escenario in escenarios:
        for valor in _decimales(escenario.model_dump(mode="json")):
            _agregar_equivalente(permitidas, valor)
    for valor in _umbrales_de_politica():
        _agregar_equivalente(permitidas, valor)
    for porcentaje in PORCENTAJES_ESTRES:
        _agregar_equivalente(permitidas, Decimal(porcentaje) / Decimal(100))
    return {cifra for cifra in permitidas if cifra}


def _agregar_equivalente(destino: set[str], valor: Decimal) -> None:
    """Añade una cifra y su forma porcentual al conjunto de permitidas.

    Args:
        destino: conjunto de cifras que se amplía en el sitio.
        valor: número que el caso autoriza citar.
    """
    texto = _formatear_decimal(valor)
    destino.add(normalizar_cifra_numerica(texto))
    destino.add(normalizar_cifra_numerica(f"{texto} %"))


def _umbrales_de_politica() -> tuple[Decimal, ...]:
    """Lee de `config/diagnostico.toml` los umbrales que el comité puede citar.

    Returns:
        Los límites verde, amarillo y de vivienda de la política del proyecto.
    """
    ajustes = motor.cargar_config()
    return (
        ajustes.verde_hasta,
        ajustes.amarillo_hasta,
        ajustes.umbral_vivienda_primera_cuota,
    )


def _decimales(valor: Any) -> Iterator[Decimal]:
    """Recorre un JSON y devuelve los números como `Decimal`.

    Args:
        valor: dato del `model_dump`.

    Yields:
        Cada número encontrado; los textos se ignoran.
    """
    if isinstance(valor, Mapping):
        for item in valor.values():
            yield from _decimales(item)
    elif isinstance(valor, (list, tuple)):
        for item in valor:
            yield from _decimales(item)
    elif isinstance(valor, bool) or valor is None:
        return
    elif isinstance(valor, (int, float, Decimal)):
        yield Decimal(str(valor))


def _productos_permitidos(
    resultado: ResultadoDiagnostico, escenarios: Sequence[EscenarioComite]
) -> frozenset[str]:
    """Nombres de producto que el caso autoriza mencionar.

    Args:
        resultado: resultado del motor.
        escenarios: escenarios precalculados.

    Returns:
        Nombres en minúsculas del producto actual y de la compra de cartera si
        es un escenario.
    """
    claves = {resultado.entrada.producto}
    if any(escenario.codigo == "compra_de_cartera" for escenario in escenarios):
        claves.add("compra_cartera")
    return frozenset(NOMBRES_PRODUCTO.get(clave, clave).casefold() for clave in claves)


def _productos_mencionados(texto: str) -> Iterator[str]:
    """Busca nombres de producto del Tablero dentro de un texto.

    Args:
        texto: argumentos y evidencias de un agente.

    Yields:
        Cada nombre de producto encontrado, en minúsculas y sin repetir.
    """
    minusculas = texto.casefold()
    for nombre in NOMBRES_PRODUCTO.values():
        if nombre.casefold() in minusculas:
            yield nombre.casefold()


def _sin_identificadores(texto: str) -> str:
    """Quita del texto los identificadores snake_case antes de buscar productos.

    Las alertas del motor (`vivienda_primera_cuota`) y los códigos de escenario
    (`plazo_mas_largo`) contienen nombres de producto como subcadena; no son
    menciones del producto.

    Args:
        texto: argumentos y evidencias de una postura.

    Returns:
        El texto en minúsculas y sin identificadores.
    """
    return _IDENTIFICADOR.sub(" ", texto.casefold())


def _negacion_inmediata(previo: str) -> bool:
    """Indica si una negación precede de inmediato a la promesa.

    Solo cuenta la última negación de la cláusula, y solo si entre ella y la
    promesa hay como máximo `_MAX_PALABRAS_ENTRE_NEGACION_Y_PROMESA` palabras de
    enlace: artículos, preposiciones, pronombres, formas de «ser» o «estar»,
    verbos del descargo («hay», «garantiza», «implica»), modales o «siquiera»;
    también cuenta una palabra que sea promesa, como «garantizamos» en «nunca
    garantizamos la aprobación». Tras «ninguna» o «ninguno» se admite un
    sustantivo antes de los enlaces («ninguna opción está garantizada»). «No
    dudes», «no solo», «no te preocupes» y «sin duda» nunca niegan.

    Args:
        previo: texto de la cláusula anterior a la promesa, ya cortado por el
            último signo de cierre o coma.

    Returns:
        `True` si la promesa queda negada por una negación inmediata.
    """
    negaciones = list(_NEGACIONES.finditer(previo))
    if not negaciones:
        return False
    ultima = negaciones[-1]
    if _NEGACIONES_EXCLUIDAS.match(previo, ultima.start()):
        return False
    palabras = previo[ultima.end() :].split()
    if ultima.group(0).casefold() in _NEGACIONES_CON_SUSTANTIVO and palabras:
        # «ninguna opción está garantizada»: el sustantivo va antes de los enlaces.
        palabras = palabras[1:]
    if len(palabras) > _MAX_PALABRAS_ENTRE_NEGACION_Y_PROMESA:
        return False
    return all(
        palabra.casefold() in _ENLACES or _PROMESAS.fullmatch(palabra) is not None
        for palabra in palabras
    )


def _promesas(texto: str) -> Iterator[str]:
    """Encuentra frases de promesa que no estén negadas de forma inmediata.

    Una negación solo anula la promesa si está justo antes, en la misma
    cláusula, con un máximo de tres palabras de enlace entre ambas. Un «no» en
    otra frase, tras una coma o a más distancia no convierte una promesa en
    negación: «No te preocupes: te lo aprueban» y «No dudes que te lo aprueban»
    siguen siendo promesas, y «sin duda» tampoco niega.

    Args:
        texto: argumentos y evidencias de un agente.

    Yields:
        Cada frase de promesa encontrada.
    """
    for coincidencia in _PROMESAS.finditer(texto):
        if negada_antes(texto, coincidencia.start()):
            continue
        yield coincidencia.group(0)


def negada_antes(texto: str, inicio: int) -> bool:
    """Indica si la frase que empieza en `inicio` queda negada de forma inmediata.

    Es la misma regla de las promesas de `auditar_texto`: solo cuenta la
    negación posterior al último cierre de frase o coma, con como máximo tres
    palabras de enlace antes de la frase, y «no dudes», «no solo», «no te
    preocupes» y «sin duda» nunca niegan. El auditor de la escena la usa para
    sus frases propias («te lo apruebo», recomendar el gota a gota), así las
    dos reglas niegan igual.

    Args:
        texto: texto completo.
        inicio: posición donde empieza la frase.

    Returns:
        `True` si la frase queda negada.
    """
    return _negacion_inmediata(_CORTES_FRASE.split(texto[:inicio])[-1])


def _buscar_postura(posturas: Sequence[PosturaAgente], rol: str) -> PosturaAgente | None:
    """Busca la postura de un rol concreto.

    Args:
        posturas: opiniones del comité.
        rol: rol buscado.

    Returns:
        La postura o `None` si no está.
    """
    return next((postura for postura in posturas if postura.agente == rol), None)


def _hallazgos_del_auditor(auditor: PosturaAgente) -> list[str]:
    """Recoge los hallazgos que dejó el agente auditor en su postura.

    Args:
        auditor: postura del agente auditor.

    Returns:
        Sus argumentos si objeta; una lista vacía en cualquier otro caso.
    """
    if auditor.postura != "objeta":
        return []
    return [argumento for argumento in auditor.argumentos if argumento.strip()]


def _orden(postura: str) -> int:
    """Traduce una postura a su orden de prudencia.

    Args:
        postura: texto de la postura.

    Returns:
        `0` para desfavorable, `1` para con condiciones, `2` para favorable y
        `-1` para abstención o valores desconocidos.
    """
    return ORDEN_POSTURA.get(postura, -1)


def _orden_semaforo(semaforo: str | None) -> int:
    """Ordena los semáforos de mejor a peor.

    Args:
        semaforo: color del escenario.

    Returns:
        `0` para verde, `1` para amarillo, `2` para rojo y `3` para sin dato.
    """
    return {"verde": 0, "amarillo": 1, "rojo": 2}.get(semaforo or "", 3)


def _texto_de(postura: PosturaAgente) -> str:
    """Junta argumentos y evidencias de una postura.

    Args:
        postura: opinión del agente.

    Returns:
        El texto revisado por el auditor.
    """
    return "\n".join([*postura.argumentos, *postura.evidencia])


def _etiqueta_recomendacion(recomendacion: str) -> str:
    """Lee la etiqueta interna de una recomendación ya sintetizada.

    Acepta tanto la apertura en lenguaje de la persona como el formato antiguo
    `etiqueta: ...`, que usan las pruebas del auditor.

    Args:
        recomendacion: texto de la síntesis.

    Returns:
        `apto`, `apto_con_condiciones`, `no_apto`, `requiere_asesor` o el texto
        antes de los dos puntos si no coincide con una apertura conocida.
    """
    primera = recomendacion.split("\n", 1)[0].strip()
    for etiqueta, apertura in APERTURA_RECOMENDACION.items():
        if primera.startswith(apertura):
            return etiqueta
    return primera.split(":", 1)[0].strip().casefold()


def _sin_repetir(hallazgos: Sequence[str]) -> list[str]:
    """Quita hallazgos repetidos conservando el orden.

    Args:
        hallazgos: lista original.

    Returns:
        La lista sin repetidos.
    """
    vistos: set[str] = set()
    unicos: list[str] = []
    for hallazgo in hallazgos:
        if hallazgo not in vistos:
            vistos.add(hallazgo)
            unicos.append(hallazgo)
    return unicos


def _formatear_decimal(valor: Decimal) -> str:
    """Formatea un decimal sin notación científica para los mensajes.

    Args:
        valor: número decimal.

    Returns:
        El texto del número.
    """
    try:
        return f"{valor.normalize():f}"
    except InvalidOperation:
        return str(valor)
