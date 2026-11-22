"""Negociación de la escena: mesa, recomendación por color y cierre en un asesor.

Antes de llamar al modelo, `construir_mesa` calcula con `diagnostico.motor` los
escenarios que los dos agentes pueden discutir: el crédito pedido, dos plazos
más largos, dos montos menores, la compra de cartera (solo si hay deudas) y la
prueba de estrés de ingreso. El estrés no es ofertable: es una prueba, no una
oferta.

La mesa es la única fuente de verdad de la negociación:

- `agente_joven` propone con «Quisiera … a … meses; la cuota sería …» y nunca
  afirma que puede pagar. `agente_banco` recomienda, contrapropone o dice que
  no cabe; nunca aprueba ni cierra un crédito. El cierre siempre incluye «la
  decisión final es de un asesor».
- En verde el banco recomienda la opción pedida como sostenible y la
  negociación termina en dos turnos. En amarillo el banco dice «cabe, pero
  ajustado» y contrapropone la alternativa en verde con el menor cambio (plazo
  antes que monto), con la cuota que baja y el total que sube. En rojo el
  joven prueba primero un plazo más largo (60 meses) y después el monto menor;
  si nada es aceptable, la negociación termina sin acuerdo.
- La plantilla de cada turno pone las cifras desde el `EscenarioEscena`; el
  modelo solo aporta un argumento corto, sin dígitos, sin colores del semáforo
  y sin lenguaje de aprobación.
- La aceptación la decide el código: solo se recomienda un escenario con
  semáforo verde o amarillo y margen mayor o igual que cero. Si el modelo
  propone algo distinto de la regla del color, el orquestador usa la política
  determinista y lo deja en el registro.
- La negociación dura como máximo cuatro turnos, con 15 segundos en total y 4
  segundos por llamada, sin reintentos. Cuando una llamada falla o se agota el
  tiempo, el turno y los siguientes usan la política determinista.
- Con `SUCURSAL_DEMO=1` o sin `DEEPSEEK_API_KEY` se usa la política
  determinista de principio a fin, con `origen="reglas"`.

Si ningún escenario es aceptable, la negociación termina sin acuerdo y el
registro lo declara: es un final válido. El módulo no implementa el auditor de
la escena (vive en `escena/auditor.py`): acepta un auditor inyectable y, si no
se pasa, deja un veredicto provisional con un hallazgo medio `auditor_pendiente`
que nunca da `conforme`.
"""

from __future__ import annotations

import json
import os
import re
import time
import tomllib
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any, Literal

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ..asistente.modelo import crear_modelo
from ..asistente.prompts import cargar_prompt
from ..canal.contratos import EntradaDiagnostico, ResultadoDiagnostico
from ..config import PROJECT_ROOT
from ..diagnostico import motor
from .contratos import (
    CifraEscena,
    EscenarioEscena,
    FuenteCifra,
    HallazgoEscena,
    NegociacionEscena,
    PerfilEscena,
    TurnoEscena,
    VeredictoAuditor,
)
from .gota import formatear_pesos

#: Archivo versionado con los límites de la negociación.
RUTA_CONFIG = PROJECT_ROOT / "config" / "escena.toml"

#: Códigos de la mesa, en orden estable. El último es la prueba de estrés.
CODIGOS_MESA: tuple[str, ...] = (
    "base",
    "plazo_mas_largo_48",
    "plazo_mas_largo_60",
    "monto_20_por_ciento_menos",
    "monto_40_por_ciento_menos",
    "compra_de_cartera",
    "estres_de_ingreso",
)
#: Códigos que un agente puede ofrecer; el estrés solo se cita como prueba.
CODIGOS_OFERTABLES: tuple[str, ...] = tuple(
    codigo for codigo in CODIGOS_MESA if codigo != "estres_de_ingreso"
)
#: Prioridad de la alternativa verde para un amarillo: plazo antes que monto.
PRIORIDAD_ALTERNATIVA_VERDE: tuple[str, ...] = (
    "plazo_mas_largo_48",
    "plazo_mas_largo_60",
    "monto_20_por_ciento_menos",
    "monto_40_por_ciento_menos",
    "compra_de_cartera",
)
#: Orden en que el rojo prueba los cambios: primero el plazo de 60 y después
#: los montos menores, del más pequeño al mayor.
FALLBACKS_ROJO: tuple[str, ...] = (
    "plazo_mas_largo_60",
    "monto_40_por_ciento_menos",
    "monto_20_por_ciento_menos",
    "compra_de_cartera",
)
#: Códigos de los escenarios que reducen el monto.
CODIGOS_MONTO: frozenset[str] = frozenset(
    {"monto_20_por_ciento_menos", "monto_40_por_ciento_menos"}
)

#: Decisiones que entiende la negociación. El banco recomienda; nunca acepta.
DecisionNegociacion = Literal["propongo", "contrapropongo", "recomiendo", "rechazo"]
#: Papeles de los dos agentes en la negociación.
AgenteNegociacion = Literal["agente_joven", "agente_banco"]
#: Origen efectivo de un turno: lo decidió el modelo o la política determinista.
OrigenDecision = Literal["llm", "reglas"]

#: Máximo de turnos de la negociación (el diseño lo congela).
MAX_TURNOS = 4
#: Presupuesto total de la negociación, en segundos.
TIEMPO_TOTAL_SEGUNDOS = 15.0
#: Presupuesto de cada llamada al modelo, en segundos.
TIEMPO_LLAMADA_SEGUNDOS = 4.0
#: Máximo de palabras de un turno, argumento incluido.
MAX_PALABRAS = 40
#: Temperatura 0 y sin razonamiento, como el comité.
TEMPERATURA = 0.0
#: Tope de tokens de cada respuesta (la propuesta es corta).
MAX_TOKENS = 400
#: Por defecto la negociación no razona: el comité fue más estable y barato así.
RAZONAMIENTO = False
#: Orden del primer turno de la negociación en la escena completa.
ORDEN_INICIAL = 11

#: Método de salida estructurada del proveedor; igual que el comité.
METODO_ESTRUCTURADO = "json_mode"

#: Frase obligatoria del cierre del banco.
FRASE_ASESOR = "La decisión final es de un asesor."

#: Cifras con dígitos; un argumento que las traiga se descarta.
_DIGITO = re.compile(r"\d")
#: Nombres de color del semáforo; un argumento que los traiga se descarta.
_COLOR = re.compile(r"\b(verde|amarillo|rojo|[aá]mbar)\b", re.IGNORECASE)
#: Lenguaje de aprobación o de cierre que la escena prohíbe.
_PROHIBIDAS = re.compile(
    r"\b(acepto|aceptamos|cerramos|aprobad[oa]s?|aprobación|aprobamos)\b"
    r"|me quedo con el crédito",
    re.IGNORECASE,
)
#: Palabras vacías que no cuentan para medir si un argumento repite la plantilla.
_PALABRAS_VACIAS = frozenset(
    {
        "algo",
        "algun",
        "alguna",
        "algunas",
        "alguno",
        "algunos",
        "ante",
        "antes",
        "aqui",
        "asi",
        "cada",
        "como",
        "con",
        "contra",
        "cual",
        "cuando",
        "de",
        "del",
        "desde",
        "donde",
        "durante",
        "el",
        "ella",
        "ellas",
        "ellos",
        "en",
        "entre",
        "era",
        "eran",
        "es",
        "esa",
        "esas",
        "ese",
        "eso",
        "esos",
        "esta",
        "estas",
        "este",
        "esto",
        "estos",
        "fue",
        "fueron",
        "ha",
        "han",
        "hasta",
        "hay",
        "la",
        "las",
        "le",
        "les",
        "lo",
        "los",
        "mas",
        "más",
        "me",
        "mi",
        "mis",
        "mucho",
        "muy",
        "no",
        "nos",
        "o",
        "otra",
        "otro",
        "para",
        "pero",
        "poco",
        "por",
        "porque",
        "que",
        "se",
        "ser",
        "si",
        "sin",
        "sobre",
        "son",
        "su",
        "sus",
        "tambien",
        "también",
        "te",
        "tiene",
        "todo",
        "toda",
        "todos",
        "todas",
        "tu",
        "tus",
        "un",
        "una",
        "uno",
        "unos",
        "unas",
        "y",
        "ya",
    }
)
#: Coincidencia mínima de palabras significativas para considerar que un
#: argumento repite la plantilla del turno.
_UMBRAL_REPETICION = 0.6

#: Decisiones que puede tomar cada agente. El joven solo propone; el banco
#: recomienda, contrapropone o rechaza, y en el cierre no contrapropone.
_DECISIONES_JOVEN = frozenset({"propongo"})
_DECISIONES_BANCO = frozenset({"recomiendo", "contrapropongo", "rechazo"})
_DECISIONES_BANCO_CIERRE = frozenset({"recomiendo", "rechazo"})

#: Etiqueta de la regla que deja constancia de que el auditor aún no corrió.
AUDITOR_PENDIENTE = "auditor_pendiente"
#: Etiqueta de la observación media cuando la negociación no llega a acuerdo.
SIN_ACUERDO = "sin_acuerdo"
#: Alternativas formales que acompañan un cierre sin acuerdo.
ALTERNATIVAS_FORMALES: tuple[str, ...] = (
    "microcrédito",
    "cooperativas",
    "entidades vigiladas por la Superfinanciera",
)


class PropuestaNegociacion(BaseModel):
    """Propuesta estructurada de un agente de la negociación."""

    model_config = ConfigDict(extra="forbid")

    codigo: str = Field(min_length=1)
    decision: DecisionNegociacion
    argumento: str = Field(default="", max_length=280)


_ESQUEMA_JSON = json.dumps(PropuestaNegociacion.model_json_schema(), ensure_ascii=False, indent=2)
#: Instrucción de `json_mode`: sin ella el proveedor no conoce la forma esperada.
INSTRUCCION_JSON = (
    "Responde solo con un objeto JSON válido, sin texto adicional, sin comentarios "
    "y sin cercas de código. Debe cumplir exactamente este esquema JSON Schema:\n"
    f"{_ESQUEMA_JSON}"
)

#: Firma del auditor inyectable: turnos, mesa y acuerdo alcanzado.
AuditorNegociacion = Callable[
    [Sequence[TurnoEscena], Sequence[EscenarioEscena], EscenarioEscena | None],
    VeredictoAuditor,
]


@dataclass(frozen=True, slots=True)
class LimitesNegociacion:
    """Límites de la negociación: turnos, reloj, palabras y parámetros del modelo.

    Los valores no pueden superar los del diseño: `cargar_limites_negociacion`
    recorta los del TOML contra `MAX_TURNOS`, `TIEMPO_TOTAL_SEGUNDOS`,
    `TIEMPO_LLAMADA_SEGUNDOS` y `MAX_PALABRAS`.
    """

    max_turnos: int = MAX_TURNOS
    tiempo_total_segundos: float = TIEMPO_TOTAL_SEGUNDOS
    tiempo_llamada_segundos: float = TIEMPO_LLAMADA_SEGUNDOS
    max_palabras: int = MAX_PALABRAS
    temperatura: float = TEMPERATURA
    max_tokens: int = MAX_TOKENS
    razonamiento: bool = RAZONAMIENTO


@dataclass(frozen=True, slots=True)
class DecisionTurno:
    """Decisión efectiva de un turno, ya validada por el orquestador."""

    orden: int
    agente: AgenteNegociacion
    decision: DecisionNegociacion
    codigo: str
    origen: OrigenDecision


@dataclass(frozen=True, slots=True)
class ResultadoNegociacion:
    """Negociación completa, acuerdo alcanzado y decisiones de cada turno."""

    negociacion: NegociacionEscena
    acuerdo: EscenarioEscena | None
    decisiones: tuple[DecisionTurno, ...]


@dataclass(slots=True)
class _Estado:
    """Estado de la mesa: escenario vigente, alternativa, pruebas y acuerdo."""

    solicitado: Decimal
    base: EscenarioEscena
    vigente: EscenarioEscena | None = None
    alternativa: EscenarioEscena | None = None
    fallbacks: list[EscenarioEscena] = field(default_factory=list)
    evaluados: list[EscenarioEscena] = field(default_factory=list)
    acuerdo: EscenarioEscena | None = None
    terminado: bool = False


@dataclass(frozen=True, slots=True)
class _PropuestaValidada:
    """Propuesta que pasó las validaciones del orquestador."""

    codigo: str
    decision: DecisionNegociacion
    argumento: str


def cargar_limites_negociacion(ruta: Path | None = None) -> LimitesNegociacion:
    """Lee `[negociacion]` de `config/escena.toml` y recorta los topes del diseño.

    Args:
        ruta: archivo TOML alternativo; por defecto `config/escena.toml`.

    Returns:
        Los límites con los valores por defecto completados; nunca supera los
        máximos del diseño aunque el TOML traiga cifras mayores.

    Raises:
        FileNotFoundError: si el archivo no existe.
    """
    archivo = Path(ruta) if ruta is not None else RUTA_CONFIG
    with archivo.open("rb") as fh:
        datos = tomllib.load(fh)
    seccion = datos.get("negociacion", {})
    if not isinstance(seccion, dict):
        seccion = {}

    turnos = int(seccion.get("max_turnos", MAX_TURNOS))
    turnos = min(MAX_TURNOS, max(2, turnos))
    if turnos % 2:
        turnos -= 1
    return LimitesNegociacion(
        max_turnos=turnos,
        tiempo_total_segundos=min(
            TIEMPO_TOTAL_SEGUNDOS,
            float(seccion.get("tiempo_total_segundos", TIEMPO_TOTAL_SEGUNDOS)),
        ),
        tiempo_llamada_segundos=min(
            TIEMPO_LLAMADA_SEGUNDOS,
            float(seccion.get("tiempo_llamada_segundos", TIEMPO_LLAMADA_SEGUNDOS)),
        ),
        max_palabras=min(MAX_PALABRAS, int(seccion.get("max_palabras", MAX_PALABRAS))),
        temperatura=float(seccion.get("temperatura", TEMPERATURA)),
        max_tokens=int(seccion.get("max_tokens", MAX_TOKENS)),
        razonamiento=bool(seccion.get("razonamiento", RAZONAMIENTO)),
    )


def modo_demo(entorno: Mapping[str, str] | None = None) -> bool:
    """Indica si la negociación debe usar solo la política determinista.

    La demo se activa con `SUCURSAL_DEMO=1` o cuando no hay
    `DEEPSEEK_API_KEY` en el entorno. No lee archivos `.env`.

    Args:
        entorno: variables de entorno; por defecto las del proceso.

    Returns:
        `True` si la negociación no debe llamar a un modelo.
    """
    valores = os.environ if entorno is None else entorno
    demo = valores.get("SUCURSAL_DEMO", "").strip() == "1"
    clave = bool(valores.get("DEEPSEEK_API_KEY", "").strip())
    return demo or not clave


def entrada_desde_perfil(
    perfil: PerfilEscena | EntradaDiagnostico,
) -> EntradaDiagnostico:
    """Normaliza el perfil de la escena en una entrada del motor.

    Un `PerfilEscena` aporta el monto de cálculo y las cuatro respuestas
    (`monto`, `ingresos`, `gastos`, `deudas`); la deuda se interpreta como la
    cuota mensual que la persona paga hoy. La compra de cartera se calcula
    aparte, con su propia cuota trasladada.

    Args:
        perfil: perfil de la escena o entrada del diagnóstico ya construida.

    Returns:
        La entrada validada del motor.

    Raises:
        ValueError: si el perfil no trae las cuatro respuestas o si el producto
            no es un crédito con monto y plazo.
    """
    if isinstance(perfil, EntradaDiagnostico):
        entrada = perfil
    else:
        valores = {respuesta.pregunta: respuesta.valor for respuesta in perfil.respuestas}
        faltan = [
            clave for clave in ("monto", "ingresos", "gastos", "deudas") if clave not in valores
        ]
        if faltan:
            raise ValueError("el perfil no trae las respuestas: " + ", ".join(faltan))
        entrada = EntradaDiagnostico(
            producto=perfil.producto,
            vinculacion=perfil.vinculacion,
            ingreso_mensual=valores["ingresos"],
            gastos_mensuales=valores["gastos"],
            cuotas_deudas=valores["deudas"],
            monto_credito=perfil.monto_calculo,
            plazo_meses=perfil.plazo_meses,
        )
    if entrada.monto_credito is None or entrada.plazo_meses is None:
        raise ValueError("la negociación exige un crédito con monto y plazo")
    return entrada


def construir_mesa(
    perfil: PerfilEscena | EntradaDiagnostico,
    *,
    hoy: date | None = None,
    raiz: Path | None = None,
    config: motor.ConfigDiagnostico | None = None,
) -> tuple[EscenarioEscena, ...]:
    """Precalcula con el motor los escenarios que pueden discutir los agentes.

    La mesa siempre trae `base`, los plazos de 48 y 60 meses y los montos 20 %
    y 40 % menores; añade `compra_de_cartera` solo si el perfil tiene deudas y
    cierra con `estres_de_ingreso`, que es una prueba y no una oferta. Los
    escenarios con monto por debajo de la frontera de `config/diagnostico.toml`
    no se construyen.

    Args:
        perfil: perfil de la escena o entrada del diagnóstico.
        hoy: fecha con la que el motor comprueba la vigencia de la tasa.
        raiz: carpeta de tablas Gold alternativa.
        config: configuración ya cargada de `config/diagnostico.toml`.

    Returns:
        Los escenarios en orden estable, cada uno con su semáforo, margen y la
        decisión de aceptación que calculó el código.

    Raises:
        ValueError: si el perfil no es un crédito con monto y plazo.
        TasaNoDisponible: si el motor no encuentra la tasa del producto.
    """
    entrada = entrada_desde_perfil(perfil)
    ajustes = config if config is not None else motor.cargar_config()
    monto = entrada.monto_credito
    plazo = entrada.plazo_meses
    assert monto is not None and plazo is not None

    escenarios: list[EscenarioEscena] = []
    base = motor.calcular(entrada, hoy=hoy, raiz=raiz, config=ajustes)
    escenarios.append(
        _armar(
            "base",
            f"El crédito que pediste a {plazo} meses",
            base,
            monto=monto,
            plazo=plazo,
            producto=entrada.producto,
            ofertable=True,
        )
    )

    for nuevo_plazo in (48, 60):
        if nuevo_plazo == plazo:
            continue
        otro = motor.calcular(
            entrada.model_copy(update={"plazo_meses": nuevo_plazo}),
            hoy=hoy,
            raiz=raiz,
            config=ajustes,
        )
        escenarios.append(
            _armar(
                f"plazo_mas_largo_{nuevo_plazo}",
                f"Ampliar el plazo a {nuevo_plazo} meses",
                otro,
                monto=monto,
                plazo=nuevo_plazo,
                producto=entrada.producto,
                ofertable=True,
            )
        )

    for codigo, factor, porcentaje in (
        ("monto_20_por_ciento_menos", Decimal("0.8"), 20),
        ("monto_40_por_ciento_menos", Decimal("0.6"), 40),
    ):
        menor = (monto * factor).quantize(Decimal(1), rounding=ROUND_HALF_UP)
        if menor < ajustes.monto_minimo:
            continue
        otro = motor.calcular(
            entrada.model_copy(update={"monto_credito": menor}),
            hoy=hoy,
            raiz=raiz,
            config=ajustes,
        )
        escenarios.append(
            _armar(
                codigo,
                f"Reducir el monto a {formatear_pesos(menor)} ({porcentaje} % menos)",
                otro,
                monto=menor,
                plazo=plazo,
                producto=entrada.producto,
                ofertable=True,
            )
        )

    if entrada.cuotas_deudas > 0:
        otro = motor.calcular(
            entrada.model_copy(
                update={
                    "producto": "compra_cartera",
                    "cuota_trasladar": entrada.cuotas_deudas,
                }
            ),
            hoy=hoy,
            raiz=raiz,
            config=ajustes,
        )
        escenarios.append(
            _armar(
                "compra_de_cartera",
                "Trasladar tus cuotas actuales a una compra de cartera",
                otro,
                monto=monto,
                plazo=plazo,
                producto="compra_cartera",
                ofertable=True,
            )
        )

    factor_estres = Decimal("0.9")
    ingreso_estres = (entrada.ingreso_mensual * factor_estres).quantize(
        Decimal(1), rounding=ROUND_HALF_UP
    )
    otro = motor.calcular(
        entrada.model_copy(update={"ingreso_mensual": ingreso_estres}),
        hoy=hoy,
        raiz=raiz,
        config=ajustes,
    )
    escenarios.append(
        _armar(
            "estres_de_ingreso",
            f"Prueba de estrés: ingreso 10 % menor ({formatear_pesos(ingreso_estres)}), "
            "misma cuota",
            otro,
            monto=monto,
            plazo=plazo,
            producto=entrada.producto,
            ofertable=False,
        )
    )
    return tuple(escenarios)


def negociar(
    perfil: PerfilEscena | EntradaDiagnostico,
    *,
    modelo: BaseChatModel | None = None,
    auditor: AuditorNegociacion | None = None,
    limites: LimitesNegociacion | None = None,
    hoy: date | None = None,
    raiz: Path | None = None,
    config: motor.ConfigDiagnostico | None = None,
    entorno: Mapping[str, str] | None = None,
    orden_inicial: int = ORDEN_INICIAL,
) -> ResultadoNegociacion:
    """Negocia sobre la mesa precalculada y devuelve turnos, acuerdo y registro.

    El joven abre con el crédito pedido. El banco recomienda la opción pedida
    si es sostenible —y la negociación termina—, contrapropone la alternativa
    verde con el menor cambio si la opción pedida está ajustada, o dice que no
    cabe. En rojo el joven prueba primero un plazo de 60 meses y luego el monto
    menor. El cierre siempre dice que la decisión final es de un asesor.

    Se hacen como máximo cuatro turnos. Cada llamada al modelo tiene su propio
    plazo y el total no pasa de 15 segundos; no hay reintentos. Una propuesta
    inválida, un fallo o un tiempo agotado activan la política determinista
    para ese turno y los siguientes.

    Con `SUCURSAL_DEMO=1` o sin `DEEPSEEK_API_KEY` se usa la política
    determinista de principio a fin, con `origen="reglas"`. Las pruebas
    inyectan el modelo y declaran una clave de prueba en `entorno` para recorrer
    el camino con modelo sin abrir la red.

    Args:
        perfil: perfil de la escena o entrada del diagnóstico.
        modelo: modelo de chat; por defecto se crea el DeepSeek de la
            negociación con temperatura 0 y sin razonamiento.
        auditor: auditor determinista que revisa los turnos; si falta, se deja
            un veredicto provisional que nunca da `conforme`.
        limites: límites de la negociación; por defecto el TOML recortado.
        hoy: fecha con la que el motor comprueba la vigencia de la tasa.
        raiz: carpeta de tablas Gold alternativa.
        config: configuración ya cargada de `config/diagnostico.toml`.
        entorno: variables de entorno; por defecto las del proceso.
        orden_inicial: orden del primer turno en la escena completa.

    Returns:
        La negociación con sus turnos, la mesa, el acuerdo —o `None` si no lo
        hubo—, las decisiones efectivas y el registro de validaciones.

    Raises:
        ValueError: si el perfil no es un crédito con monto y plazo.
        TasaNoDisponible: si el motor no encuentra la tasa del producto.
    """
    entrada = entrada_desde_perfil(perfil)
    ajustes = limites if limites is not None else cargar_limites_negociacion()
    mesa = construir_mesa(entrada, hoy=hoy, raiz=raiz, config=config)
    base = _buscar(mesa, "base")
    assert base is not None
    solicitado = entrada.monto_credito
    assert solicitado is not None
    estado = _Estado(
        solicitado=solicitado,
        base=base,
        fallbacks=list(_fallbacks_rojo(mesa)),
    )

    determinista = modo_demo(entorno)
    if not determinista and modelo is None:
        modelo = crear_modelo(
            temperatura=ajustes.temperatura,
            max_tokens=ajustes.max_tokens,
            timeout=ajustes.tiempo_llamada_segundos,
            max_retries=0,
            razonamiento=ajustes.razonamiento,
        )

    turnos: list[TurnoEscena] = []
    decisiones: list[DecisionTurno] = []
    registro: list[str] = []
    forzar_reglas = determinista
    if determinista:
        registro.append("modo demo: política determinista de principio a fin")

    inicio = time.monotonic()
    ejecutor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="negociacion")
    try:
        for indice in range(ajustes.max_turnos):
            agente: AgenteNegociacion = "agente_joven" if indice % 2 == 0 else "agente_banco"
            cierra = indice == ajustes.max_turnos - 1
            origen: OrigenDecision = "reglas"
            notas: list[str] = []
            decision: DecisionNegociacion | None = None
            escenario: EscenarioEscena | None = None
            argumento = ""

            if not forzar_reglas and modelo is not None:
                restante = ajustes.tiempo_total_segundos - (time.monotonic() - inicio)
                if restante <= 0:
                    forzar_reglas = True
                    notas.append("tiempo total agotado; se usa la política determinista")
                else:
                    futuro = ejecutor.submit(
                        _llamar_modelo,
                        modelo,
                        "joven" if agente == "agente_joven" else "banco",
                        _contexto(indice, agente, cierra, estado, mesa),
                    )
                    try:
                        propuesta = futuro.result(
                            timeout=min(ajustes.tiempo_llamada_segundos, restante)
                        )
                    except TimeoutError:
                        propuesta = None
                        forzar_reglas = True
                        notas.append(
                            "tiempo de la llamada agotado; se usa la política determinista"
                        )
                    except Exception as exc:  # noqa: BLE001 - el turno cae a la política
                        propuesta = None
                        forzar_reglas = True
                        notas.append(
                            f"fallo del modelo ({type(exc).__name__}); "
                            "se usa la política determinista"
                        )
                    if propuesta is None and not forzar_reglas:
                        forzar_reglas = True
                        notas.append("respuesta inválida; se usa la política determinista")
                    elif propuesta is not None:
                        validada, motivo = _validar_propuesta(
                            propuesta, indice, agente, cierra, mesa, estado
                        )
                        if validada is None:
                            forzar_reglas = True
                            notas.append(f"propuesta inválida: {motivo}")
                        elif agente == "agente_banco":
                            esperada, escenario_esperado = _accion_banco(estado, mesa, cierra)
                            if (
                                validada.decision == esperada
                                and validada.codigo == escenario_esperado.codigo
                            ):
                                decision = validada.decision
                                escenario = escenario_esperado
                                argumento = validada.argumento
                                origen = "llm"
                            else:
                                decision = esperada
                                escenario = escenario_esperado
                                notas.append(
                                    "la decisión del modelo no sigue la regla del escenario; "
                                    "se usa la política determinista"
                                )
                        else:
                            decision = validada.decision
                            escenario = _buscar(mesa, validada.codigo)
                            assert escenario is not None
                            argumento = validada.argumento
                            origen = "llm"

            if decision is None or escenario is None:
                if agente == "agente_joven":
                    decision, escenario = _accion_joven(estado)
                else:
                    decision, escenario = _accion_banco(estado, mesa, cierra)
                origen = "reglas"

            if agente == "agente_banco" and decision == "rechazo":
                if not cierra:
                    notas.append(
                        "pruebas en orden: "
                        + ", ".join(
                            escenario_fallback.codigo for escenario_fallback in estado.fallbacks
                        )
                    )
                else:
                    monto_menor = _monto_menor(estado)
                    if monto_menor is not None:
                        notas.append(f"prueba 2: {monto_menor.codigo} (tampoco alcanza)")
            if (
                agente == "agente_joven"
                and indice == 2
                and escenario.codigo in {fallback.codigo for fallback in estado.fallbacks}
            ):
                notas.append(f"prueba 1: {escenario.codigo}")

            texto, cifras = _componer_turno(
                agente,
                decision,
                escenario,
                cierra,
                alternativa=estado.alternativa,
                monto_menor=_monto_menor(estado) if decision == "rechazo" and cierra else None,
                anterior=estado.vigente,
            )
            if argumento:
                motivo = _motivo_argumento(argumento)
                if motivo:
                    notas.append(f"argumento descartado ({motivo})")
                    argumento = ""
                elif _repite_plantilla(texto, argumento):
                    notas.append("argumento descartado (repite la plantilla)")
                    argumento = ""
            if argumento:
                candidato = _con_argumento(texto, argumento)
                if len(candidato.split()) > ajustes.max_palabras:
                    notas.append("argumento descartado (supera el máximo de palabras)")
                else:
                    texto = candidato

            turnos.append(
                TurnoEscena(
                    id=f"negociacion.{agente}.{indice + 1}.v1",
                    orden=orden_inicial + indice,
                    personaje=agente,
                    texto=texto,
                    cifras=cifras,
                    escenario=escenario,
                    origen=origen,
                )
            )
            decisiones.append(
                DecisionTurno(
                    orden=orden_inicial + indice,
                    agente=agente,
                    decision=decision,
                    codigo=escenario.codigo,
                    origen=origen,
                )
            )
            registro.extend(f"turno {indice + 1} | {nota}" for nota in notas)
            _actualizar(estado, decision, escenario, cierra)
            if estado.terminado:
                break
    finally:
        ejecutor.shutdown(wait=False, cancel_futures=True)

    if estado.acuerdo is None:
        registro.append(f"cierre | {SIN_ACUERDO}")
    else:
        registro.append(f"cierre | recomendación en {estado.acuerdo.codigo}")

    veredicto = (
        auditor(tuple(turnos), mesa, estado.acuerdo)
        if auditor is not None
        else _veredicto_provisional(tuple(turnos), estado.acuerdo)
    )
    return ResultadoNegociacion(
        negociacion=NegociacionEscena(
            turnos=tuple(turnos),
            escenarios=mesa,
            veredicto=veredicto,
            registro=tuple(registro),
        ),
        acuerdo=estado.acuerdo,
        decisiones=tuple(decisiones),
    )


def _armar(
    codigo: str,
    descripcion: str,
    resultado: ResultadoDiagnostico,
    *,
    monto: Decimal,
    plazo: int,
    producto: str,
    ofertable: bool,
) -> EscenarioEscena:
    """Convierte un resultado del motor en un escenario de la mesa.

    La aceptación es código: un escenario es aceptable solo si es ofertable,
    tiene cuota simulada, su semáforo es verde o amarillo y deja margen mayor o
    igual que cero.

    Args:
        codigo: código estable del escenario.
        descripcion: texto determinista del escenario.
        resultado: `ResultadoDiagnostico` del motor.
        monto: monto del escenario.
        plazo: plazo del escenario, en meses.
        producto: clave del producto simulado.
        ofertable: si un agente puede ofrecerlo.

    Returns:
        El escenario listo para la mesa y para los turnos.
    """
    cuota = resultado.cuota_mensual.hasta if resultado.cuota_mensual is not None else None
    total = resultado.total_pagado.hasta if resultado.total_pagado is not None else None
    intereses = resultado.total_intereses.hasta if resultado.total_intereses is not None else None
    margen = resultado.margen_despues_cuota
    aceptable = (
        ofertable
        and cuota is not None
        and resultado.semaforo in {"verde", "amarillo"}
        and margen is not None
        and margen >= 0
    )
    return EscenarioEscena(
        codigo=codigo,
        descripcion=descripcion,
        producto=producto,
        monto=monto,
        plazo_meses=plazo,
        cuota_mensual=cuota,
        total_pagado=total,
        total_intereses=intereses,
        semaforo=resultado.semaforo,
        razon_endeudamiento=resultado.razon_endeudamiento,
        margen_despues_cuota=margen,
        aceptable=aceptable,
        ofertable=ofertable,
    )


def _accion_joven(estado: _Estado) -> tuple[DecisionNegociacion, EscenarioEscena]:
    """Decide el turno del joven con la política determinista.

    El primer turno siempre propone el crédito pedido. En el tercer turno
    propone la alternativa verde que contrapropuso el banco o, si el banco
    rechazó, la primera prueba del rojo: el plazo de 60 meses.

    Args:
        estado: estado vigente de la mesa.

    Returns:
        La decisión y el escenario que la sostiene.
    """
    if estado.vigente is None:
        return "propongo", estado.base
    if estado.alternativa is not None and estado.alternativa.aceptable:
        return "propongo", estado.alternativa
    evaluados = {escenario.codigo for escenario in estado.evaluados}
    siguiente = next(
        (escenario for escenario in estado.fallbacks if escenario.codigo not in evaluados),
        None,
    )
    if siguiente is not None:
        return "propongo", siguiente
    return "propongo", estado.vigente


def _accion_banco(
    estado: _Estado,
    mesa: Sequence[EscenarioEscena],
    cierra: bool,
) -> tuple[DecisionNegociacion, EscenarioEscena]:
    """Decide el turno del banco según el color del escenario vigente.

    - Verde: recomienda la opción como sostenible.
    - Amarillo: dice que cabe, pero ajustado, y contrapropone la alternativa
      verde con el menor cambio; en el cierre recomienda la opción sostenible.
    - Rojo: dice que no cabe; en el cierre revisa las pruebas del joven y, si
      alguna es aceptable, la recomienda.

    Args:
        estado: estado vigente de la mesa.
        mesa: escenarios precalculados.
        cierra: si es el último turno de la negociación.

    Returns:
        La decisión y el escenario que la sostiene.
    """
    actual = estado.vigente or estado.base
    if actual.aceptable:
        if (
            cierra
            and estado.alternativa is not None
            and estado.alternativa.aceptable
            and estado.alternativa.semaforo == "verde"
        ):
            return "recomiendo", estado.alternativa
        if not cierra and actual.semaforo == "amarillo":
            alternativa = _alternativa_verde(mesa, actual)
            if alternativa is not None:
                return "contrapropongo", alternativa
        return "recomiendo", actual
    if not cierra:
        return "rechazo", actual
    for fallback in estado.fallbacks:
        if fallback.codigo != actual.codigo and fallback.aceptable:
            return "recomiendo", fallback
    return "rechazo", actual


def _alternativa_verde(
    mesa: Sequence[EscenarioEscena],
    actual: EscenarioEscena,
) -> EscenarioEscena | None:
    """Busca la alternativa verde con el menor cambio para un amarillo.

    Primero el plazo más corto que mejore el semáforo y después el monto menor,
    igual que el comité.

    Args:
        mesa: escenarios precalculados.
        actual: escenario vigente que está ajustado.

    Returns:
        La alternativa verde, o `None` si no hay ninguna.
    """
    for codigo in PRIORIDAD_ALTERNATIVA_VERDE:
        escenario = _buscar(mesa, codigo)
        if (
            escenario is not None
            and escenario.ofertable
            and escenario.aceptable
            and escenario.semaforo == "verde"
            and escenario.codigo != actual.codigo
        ):
            return escenario
    return None


def _fallbacks_rojo(mesa: Sequence[EscenarioEscena]) -> tuple[EscenarioEscena, ...]:
    """Ordena las pruebas del rojo: plazo de 60 y después los montos menores.

    Args:
        mesa: escenarios precalculados.

    Returns:
        Los escenarios ofertables, en el orden en que el joven los prueba.
    """
    return tuple(
        escenario
        for codigo in FALLBACKS_ROJO
        if (escenario := _buscar(mesa, codigo)) is not None and escenario.ofertable
    )


def _monto_menor(estado: _Estado) -> EscenarioEscena | None:
    """Devuelve el primer escenario de monto menor de la mesa.

    Args:
        estado: estado vigente de la mesa.

    Returns:
        El escenario de monto menor, o `None` si la mesa no tiene ninguno.
    """
    return next(
        (escenario for escenario in estado.fallbacks if escenario.codigo in CODIGOS_MONTO),
        None,
    )


def _actualizar(
    estado: _Estado,
    decision: DecisionNegociacion,
    escenario: EscenarioEscena,
    cierra: bool,
) -> None:
    """Actualiza el estado de la mesa con la decisión del turno.

    Args:
        estado: estado vigente; se modifica en el sitio.
        decision: decisión efectiva del turno.
        escenario: escenario que sostiene la decisión.
        cierra: si es el último turno de la negociación.
    """
    if decision == "propongo":
        estado.vigente = escenario
        if escenario.codigo in {
            fallback.codigo for fallback in estado.fallbacks
        } and escenario.codigo not in {evaluado.codigo for evaluado in estado.evaluados}:
            estado.evaluados.append(escenario)
        return
    if decision == "contrapropongo":
        estado.vigente = escenario
        estado.alternativa = escenario
        return
    if decision == "recomiendo":
        estado.vigente = escenario
        estado.acuerdo = escenario
        estado.terminado = True
        return
    if decision == "rechazo":
        estado.acuerdo = None
        if cierra:
            estado.terminado = True


def _contexto(
    indice: int,
    agente: AgenteNegociacion,
    cierra: bool,
    estado: _Estado,
    mesa: Sequence[EscenarioEscena],
) -> dict[str, Any]:
    """Arma el JSON que recibe el agente, sin umbrales ni datos personales.

    Args:
        indice: posición del turno, desde cero.
        agente: papel del agente en el turno.
        cierra: si es el último turno de la negociación.
        estado: estado vigente de la mesa.
        mesa: escenarios precalculados.

    Returns:
        El contexto con el turno, el escenario vigente y la mesa completa.
    """
    return {
        "turno": indice + 1,
        "agente": agente,
        "cierra": cierra,
        "escenario_vigente": (
            estado.vigente.model_dump(mode="json") if estado.vigente is not None else None
        ),
        "alternativa_contrapropuesta": (
            estado.alternativa.model_dump(mode="json") if estado.alternativa is not None else None
        ),
        "escenarios": [escenario.model_dump(mode="json") for escenario in mesa],
    }


def _mensaje_humano(contexto: Mapping[str, Any]) -> str:
    """Arma el mensaje con la mesa y las reglas de la respuesta.

    Args:
        contexto: turno, escenario vigente y mesa.

    Returns:
        El texto que recibe el agente.
    """
    return "\n".join(
        (
            "Datos de la mesa (solo cifras calculadas; no hay datos personales):",
            json.dumps(contexto, ensure_ascii=False, indent=2, default=str),
            "Responde solo con el esquema PropuestaNegociacion y usa únicamente "
            "los códigos de la mesa. No escribas cifras, colores del semáforo ni "
            "lenguaje de aprobación.",
        )
    )


def _llamar_modelo(
    modelo: BaseChatModel,
    rol: Literal["joven", "banco"],
    contexto: Mapping[str, Any],
) -> PropuestaNegociacion | None:
    """Llama a un agente con salida estructurada y devuelve su propuesta.

    No hace reintentos: la primera respuesta inválida o el primer fallo dejan
    el turno en manos de la política determinista.

    Args:
        modelo: modelo de chat.
        rol: `joven` o `banco`, para cargar el prompt versionado.
        contexto: turno, escenario vigente y mesa.

    Returns:
        La propuesta validada, o `None` si la salida no tiene la forma esperada.
    """
    prompt = cargar_prompt(f"negociacion_{rol}")
    sistema = prompt.sistema
    if prompt.recordatorio:
        sistema = f"{sistema}\n\n{prompt.recordatorio}"
    mensajes = [
        SystemMessage(content=sistema),
        HumanMessage(content=f"{_mensaje_humano(contexto)}\n\n{INSTRUCCION_JSON}"),
    ]
    runnable = modelo.with_structured_output(
        PropuestaNegociacion,
        method=METODO_ESTRUCTURADO,
        include_raw=True,
    )
    return _leer_salida(runnable.invoke(mensajes))


def _leer_salida(salida: Any) -> PropuestaNegociacion | None:
    """Extrae la propuesta de la salida estructurada del modelo.

    Args:
        salida: resultado del runnable, con o sin `include_raw`.

    Returns:
        La propuesta validada, o `None` si no se pudo leer.
    """
    if isinstance(salida, dict) and "parsed" in salida:
        salida = salida.get("parsed")
    if salida is None:
        return None
    if isinstance(salida, PropuestaNegociacion):
        return salida
    try:
        return PropuestaNegociacion.model_validate(salida)
    except ValidationError:
        return None


def _validar_propuesta(
    propuesta: PropuestaNegociacion,
    indice: int,
    agente: AgenteNegociacion,
    cierra: bool,
    mesa: Sequence[EscenarioEscena],
    estado: _Estado,
) -> tuple[_PropuestaValidada | None, str]:
    """Valida el código, la decisión y la coherencia de una propuesta.

    Args:
        propuesta: salida del modelo.
        indice: posición del turno, desde cero.
        agente: papel del agente en el turno.
        cierra: si es el último turno de la negociación.
        mesa: escenarios precalculados.
        estado: estado vigente de la mesa.

    Returns:
        La propuesta validada y una cadena vacía, o `None` y el motivo por el
        que se descarta.
    """
    codigo = propuesta.codigo.strip()
    escenario = _buscar(mesa, codigo)
    if escenario is None:
        return None, f"el código «{codigo}» no existe en la mesa"
    if not escenario.ofertable:
        return None, f"el escenario «{codigo}» no es ofertable"
    permitidas = _decisiones_permitidas(indice, agente, cierra)
    if propuesta.decision not in permitidas:
        return None, f"la decisión «{propuesta.decision}» no cabe en este turno"
    vigente = estado.vigente
    if agente == "agente_joven":
        if indice == 0 and codigo != "base":
            return None, "el primer turno debe proponer el escenario base"
        if indice == 2 and estado.alternativa is not None:
            permitidos = {estado.alternativa.codigo, estado.base.codigo}
            if codigo not in permitidos:
                return None, (
                    "el turno de decisión solo admite el escenario pedido "
                    "o la alternativa contrapropuesta"
                )
        if indice == 2 and estado.alternativa is None and estado.fallbacks:
            primero = estado.fallbacks[0]
            if codigo != primero.codigo:
                return None, f"el primer cambio del rojo es {primero.codigo}"
    if propuesta.decision == "rechazo" and (vigente is None or codigo != vigente.codigo):
        return None, "el rechazo no corresponde al escenario vigente"
    if propuesta.decision == "contrapropongo" and vigente is not None and codigo == vigente.codigo:
        return None, "la contrapropuesta repite el escenario vigente"
    return _PropuestaValidada(codigo, propuesta.decision, propuesta.argumento.strip()), ""


def _decisiones_permitidas(
    indice: int,
    agente: AgenteNegociacion,
    cierra: bool,
) -> frozenset[str]:
    """Devuelve las decisiones que caben en un turno.

    Args:
        indice: posición del turno, desde cero.
        agente: papel del agente en el turno.
        cierra: si es el último turno de la negociación.

    Returns:
        El conjunto de decisiones válidas para ese turno.
    """
    if indice == 0:
        return _DECISIONES_JOVEN
    if agente == "agente_banco":
        return _DECISIONES_BANCO_CIERRE if cierra else _DECISIONES_BANCO
    return _DECISIONES_JOVEN


def _componer_turno(
    agente: AgenteNegociacion,
    decision: DecisionNegociacion,
    escenario: EscenarioEscena,
    cierra: bool,
    *,
    alternativa: EscenarioEscena | None,
    monto_menor: EscenarioEscena | None,
    anterior: EscenarioEscena | None = None,
) -> tuple[str, tuple[CifraEscena, ...]]:
    """Compone el texto y las cifras de un turno desde el escenario.

    La plantilla —nunca el modelo— pone el monto, el plazo, la cuota y el
    total, y cada cifra conserva su `FuenteCifra`. El joven nunca afirma que
    puede pagar y el banco nunca aprueba ni cierra un crédito: recomienda o
    dice que no cabe, y el cierre remite a un asesor. En la contrapropuesta del
    amarillo el banco compara la cuota y el total del escenario pedido con los
    de la alternativa, incluida la diferencia de total.

    Args:
        agente: papel del agente en el turno.
        decision: decisión efectiva del turno.
        escenario: escenario que sostiene la decisión.
        cierra: si es el último turno de la negociación.
        alternativa: alternativa verde que contrapropuso el banco, si la hay.
        monto_menor: escenario de monto menor que se revisa en el cierre rojo.
        anterior: escenario vigente antes de la contrapropuesta, para comparar.

    Returns:
        El texto del turno y las cifras que menciona, en el orden en que
        aparecen.
    """
    monto = formatear_pesos(escenario.monto)
    plazo = str(escenario.plazo_meses or 0)
    cuota = (
        formatear_pesos(escenario.cuota_mensual) if escenario.cuota_mensual is not None else None
    )
    total = formatear_pesos(escenario.total_pagado) if escenario.total_pagado is not None else None
    cuota_base: str | None = None
    total_base: str | None = None
    cuota_base_valor: Decimal | None = None
    total_base_valor: Decimal | None = None
    diferencia: str | None = None
    diferencia_valor: Decimal | None = None

    if agente == "agente_joven":
        texto = ""
        if alternativa is not None and escenario.codigo == alternativa.codigo:
            texto = "Entre pagar menos al mes y pagar menos en total, prefiero la cuota más baja. "
        texto += f"Quisiera {monto} a {plazo} meses"
        texto += f"; la cuota sería {cuota}." if cuota is not None else "."
    elif decision == "recomiendo":
        if escenario.semaforo == "verde":
            texto = (
                f"Esta opción es sostenible: la cuota de {cuota} para {monto} a {plazo} meses "
                "cabe con holgura"
            )
        else:
            texto = (
                f"Cabe, pero ajustado: la cuota de {cuota} para {monto} a {plazo} meses "
                "deja poco margen"
            )
        texto += f" y el total es {total}." if total is not None else "."
        texto += f" {FRASE_ASESOR}"
    elif decision == "contrapropongo":
        if anterior is not None and anterior.cuota_mensual is not None:
            cuota_base_valor = anterior.cuota_mensual
            cuota_base = formatear_pesos(cuota_base_valor)
        if anterior is not None and anterior.total_pagado is not None:
            total_base_valor = anterior.total_pagado
            total_base = formatear_pesos(total_base_valor)
        if (
            anterior is not None
            and anterior.total_pagado is not None
            and escenario.total_pagado is not None
        ):
            diferencia_valor = escenario.total_pagado - anterior.total_pagado
            diferencia = formatear_pesos(diferencia_valor)
        if (
            cuota_base is not None
            and cuota is not None
            and total_base is not None
            and total is not None
        ):
            texto = (
                f"Cabe, pero ajustado: con {plazo} meses la cuota baja de {cuota_base} "
                f"a {cuota}, pero el total sube de {total_base} a {total}"
            )
            if diferencia is not None:
                texto += f": {diferencia} más"
            texto += "."
        else:
            texto = f"Cabe, pero ajustado: con {plazo} meses la cuota baja a {cuota} para {monto}"
            texto += f", aunque el total sube a {total}." if total is not None else "."
    elif not cierra:
        if cuota is None:
            texto = (
                f"No cabe en tu capacidad: con {monto} a {plazo} meses no hay una cuota "
                "que quepa en tu presupuesto."
            )
        else:
            texto = (
                f"No cabe en tu capacidad: con {monto} a {plazo} meses la cuota de {cuota} "
                "supera el margen de tu presupuesto."
            )
    else:
        if cuota is None:
            texto = f"Con {monto} a {plazo} meses no hay una cuota que quepa en tu capacidad."
        else:
            texto = (
                f"Con {monto} a {plazo} meses la cuota de {cuota} sigue por encima de tu capacidad."
            )
        if monto_menor is not None and monto_menor.cuota_mensual is not None:
            cuota_menor = formatear_pesos(monto_menor.cuota_mensual)
            texto += (
                f" Con el monto menor la cuota sería {cuota_menor} y tampoco alcanza: "
                "no hay acuerdo hoy."
            )
        else:
            texto += " No hay acuerdo hoy."
        texto += f" {FRASE_ASESOR}"

    plazo_cifra = _cifra(
        "plazo del escenario",
        Decimal(escenario.plazo_meses or 0),
        plazo,
        "meses",
        FuenteCifra(
            tipo="config",
            referencia=f"config/diagnostico.toml#plazo.{plazo}",
        ),
    )
    if (
        decision == "contrapropongo"
        and cuota_base_valor is not None
        and total_base_valor is not None
        and cuota is not None
        and total is not None
    ):
        cifras = [
            plazo_cifra,
            _cifra(
                "cuota del escenario pedido",
                cuota_base_valor,
                cuota_base or "",
                "pesos",
                FuenteCifra(tipo="motor", referencia="diagnostico.motor#cuota_mensual.hasta"),
            ),
            _cifra(
                "cuota de la contrapropuesta",
                escenario.cuota_mensual or Decimal(0),
                cuota,
                "pesos",
                FuenteCifra(tipo="motor", referencia="diagnostico.motor#cuota_mensual.hasta"),
            ),
            _cifra(
                "total del escenario pedido",
                total_base_valor,
                total_base or "",
                "pesos",
                FuenteCifra(tipo="motor", referencia="diagnostico.motor#total_pagado.hasta"),
            ),
            _cifra(
                "total de la contrapropuesta",
                escenario.total_pagado or Decimal(0),
                total,
                "pesos",
                FuenteCifra(tipo="motor", referencia="diagnostico.motor#total_pagado.hasta"),
            ),
        ]
        if diferencia is not None and diferencia_valor is not None:
            cifras.append(
                _cifra(
                    "diferencia de total",
                    diferencia_valor,
                    diferencia,
                    "pesos",
                    FuenteCifra(
                        tipo="motor",
                        referencia="escena.negociacion#diferencia_total_pagado",
                    ),
                )
            )
    else:
        cifras = [
            _cifra(
                "monto ofrecido",
                escenario.monto,
                monto,
                "pesos",
                FuenteCifra(tipo="motor", referencia="diagnostico.motor#monto_credito"),
            ),
            plazo_cifra,
        ]
        if cuota is not None and escenario.cuota_mensual is not None:
            cifras.append(
                _cifra(
                    "cuota mensual",
                    escenario.cuota_mensual,
                    cuota,
                    "pesos",
                    FuenteCifra(tipo="motor", referencia="diagnostico.motor#cuota_mensual.hasta"),
                )
            )
        if total is not None and escenario.total_pagado is not None and total in texto:
            cifras.append(
                _cifra(
                    "total pagado en el horizonte",
                    escenario.total_pagado,
                    total,
                    "pesos",
                    FuenteCifra(tipo="motor", referencia="diagnostico.motor#total_pagado.hasta"),
                )
            )
        if (
            monto_menor is not None
            and monto_menor.cuota_mensual is not None
            and "monto menor" in texto
        ):
            cuota_menor_texto = formatear_pesos(monto_menor.cuota_mensual)
            cifras.append(
                _cifra(
                    "cuota con el monto menor",
                    monto_menor.cuota_mensual,
                    cuota_menor_texto,
                    "pesos",
                    FuenteCifra(tipo="motor", referencia="diagnostico.motor#cuota_mensual.hasta"),
                )
            )
    return texto, tuple(cifras)


def _cifra(
    etiqueta: str,
    valor: Decimal,
    legible: str,
    unidad: Literal["pesos", "meses"],
    fuente: FuenteCifra,
) -> CifraEscena:
    """Arma una cifra del turno con su fuente verificable.

    Args:
        etiqueta: nombre legible de la cifra.
        valor: valor de máquina.
        legible: texto que se muestra y que aparece en el turno.
        unidad: unidad de la cifra.
        fuente: origen verificable.

    Returns:
        La cifra lista para el contrato.
    """
    return CifraEscena(
        etiqueta=etiqueta,
        valor=valor,
        valor_legible=legible,
        unidad=unidad,
        fuente=fuente,
    )


def _con_argumento(texto: str, argumento: str) -> str:
    """Añade el argumento del modelo al texto del turno con puntuación.

    Args:
        texto: plantilla ya compuesta con las cifras.
        argumento: frase corta del modelo.

    Returns:
        El texto con el argumento al final y un solo punto de cierre.
    """
    cierre = argumento.rstrip()
    if not cierre.endswith((".", "!", "?")):
        cierre = f"{cierre}."
    return f"{texto} {cierre}"


def _motivo_argumento(argumento: str) -> str:
    """Devuelve por qué se descarta un argumento, o vacío si es válido.

    Args:
        argumento: frase del modelo.

    Returns:
        El motivo —dígitos, un color del semáforo o lenguaje de aprobación— o
        una cadena vacía.
    """
    if _DIGITO.search(argumento):
        return "contiene dígitos"
    if _COLOR.search(argumento):
        return "nombra un color del semáforo"
    if _PROHIBIDAS.search(argumento):
        return "usa lenguaje de aprobación"
    return ""


def _palabras_significativas(texto: str) -> set[str]:
    """Extrae las palabras que cuentan para comparar un argumento con la plantilla.

    Args:
        texto: frase del modelo o texto del turno.

    Returns:
        Las palabras en minúsculas, sin signos, con más de tres letras y sin
        las palabras vacías del español.
    """
    palabras = re.findall(r"[a-záéíóúüñ]+", texto.casefold())
    return {palabra for palabra in palabras if len(palabra) > 3 and palabra not in _PALABRAS_VACIAS}


def _repite_plantilla(texto: str, argumento: str) -> bool:
    """Indica si el argumento repite buena parte de la plantilla del turno.

    Cuenta la fracción de palabras significativas del argumento que ya
    aparecen en el texto del turno. Si supera `_UMBRAL_REPETICION`, el
    argumento no aporta una razón distinta y se descarta.

    Args:
        texto: texto del turno ya compuesto con la plantilla.
        argumento: frase del modelo.

    Returns:
        `True` si el argumento repite la plantilla.
    """
    palabras_argumento = _palabras_significativas(argumento)
    if not palabras_argumento:
        return False
    palabras_texto = _palabras_significativas(texto)
    if not palabras_texto:
        return False
    coincidencia = len(palabras_argumento & palabras_texto) / len(palabras_argumento)
    return coincidencia >= _UMBRAL_REPETICION


def _buscar(mesa: Sequence[EscenarioEscena], codigo: str) -> EscenarioEscena | None:
    """Busca un escenario por código en la mesa.

    Args:
        mesa: escenarios precalculados.
        codigo: código buscado.

    Returns:
        El escenario, o `None` si no está en la mesa.
    """
    return next((escenario for escenario in mesa if escenario.codigo == codigo), None)


def _veredicto_provisional(
    turnos: Sequence[TurnoEscena],
    acuerdo: EscenarioEscena | None,
) -> VeredictoAuditor:
    """Deja un veredicto provisional mientras el auditor de la escena no corre.

    Nunca da `conforme`: deja un hallazgo medio `auditor_pendiente` y, si no
    hubo acuerdo, añade `sin_acuerdo` y las alternativas formales de Pana.

    Args:
        turnos: turnos de la negociación.
        acuerdo: escenario del acuerdo, o `None`.

    Returns:
        El veredicto con los hallazgos medios y los turnos revisados.
    """
    hallazgos = [
        HallazgoEscena(
            codigo=AUDITOR_PENDIENTE,
            detalle="El auditor de la escena revisa estos turnos en su módulo.",
            gravedad="media",
        )
    ]
    reglas = [AUDITOR_PENDIENTE]
    alternativas: tuple[str, ...] = ()
    if acuerdo is None:
        hallazgos.append(
            HallazgoEscena(
                codigo=SIN_ACUERDO,
                detalle="La negociación cerró sin un escenario aceptable.",
                gravedad="media",
            )
        )
        reglas.append(SIN_ACUERDO)
        alternativas = ALTERNATIVAS_FORMALES
    return VeredictoAuditor(
        veredicto="con_observaciones",
        hallazgos=tuple(hallazgos),
        turnos_revisados=tuple(turno.id for turno in turnos),
        reglas=tuple(reglas),
        alternativas=alternativas,
    )
