"""Escenarios «¿Y si…?» del diagnóstico (OpenSpec corresponsal-whatsapp, 8.2 y 8.3).

Cuando un diagnóstico terminó, la persona puede preguntar «¿y si el plazo
fuera 48 meses?» o «¿y si pido 8 millones?». Este módulo:

1. interpreta el pedido sin modelo (`interpretar_pedido`);
2. valida el cambio contra los límites del diagnóstico (`aplicar_cambio`): si
   está fuera de rango, explica el límite y **no crea la rama**;
3. bifurca el diagnóstico (`bifurcar_escenario`): lee el estado terminado del
   hilo original con `get_state`, recalcula con el motor y escribe el
   resultado en un `thread_id` nuevo `diag:<usuario_id>:esc:<n>` con
   `update_state`. El hilo original nunca se escribe (design.md, decisión 11);
4. compara cuota, semáforo y razón de endeudamiento (`ComparacionEscenario`)
   y arma el mensaje para WhatsApp.

El cálculo no vive aquí: se inyecta la función del motor determinista
(`diagnostico.motor`), así este módulo no duplica fórmulas y se prueba con un
grafo simulado mientras el grafo real de diagnóstico se termina.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from decimal import Decimal, InvalidOperation
from typing import Any, Literal, Protocol

from langchain_core.runnables import RunnableConfig
from pydantic import BaseModel, ConfigDict, ValidationError

from ..canal.contratos import EntradaDiagnostico, RangoDecimal, ResultadoDiagnostico

CampoEscenario = Literal[
    "monto_credito",
    "plazo_meses",
    "ingreso_mensual",
    "gastos_mensuales",
    "cuotas_deudas",
]
Semaforo = Literal["verde", "amarillo", "rojo"]

#: Etapa en la que el diagnóstico original debe estar para bifurcarse.
ETAPA_TERMINADA = "terminado"
#: Nodo al que se atribuye la escritura del escenario (último nodo del grafo).
NODO_FINAL = "cerrar"
#: Escenarios por diagnóstico, para que una conversación no cree ramas sin fin.
MAXIMO_ESCENARIOS = 10

#: Plazo en meses para todos los productos menos vivienda (guion de la entrevista).
PLAZO_GENERAL = (6, 72)
#: Plazo en meses para vivienda.
PLAZO_VIVIENDA = (60, 240)
#: Monto del crédito en pesos.
MONTO = (Decimal(500_000), Decimal(2_000_000_000))
#: Ingreso, gastos y cuotas mensuales en pesos (0 solo para gastos y cuotas).
VALOR_MENSUAL_MAXIMO = Decimal(1_000_000_000)

#: Orden de los semáforos, para decir si el escenario mejora o empeora.
ORDEN_SEMAFORO: dict[str, int] = {"verde": 0, "amarillo": 1, "rojo": 2}


class GrafoConEstado(Protocol):
    """Lo mínimo que se usa del grafo compilado de LangGraph."""

    def get_state(self, config: RunnableConfig) -> Any:
        """Devuelve el `StateSnapshot` del hilo."""
        ...

    def update_state(
        self, config: RunnableConfig, values: dict[str, Any], as_node: str | None = None
    ) -> RunnableConfig:
        """Escribe valores en el hilo como si los produjera `as_node`."""
        ...


class CambioEscenario(BaseModel):
    """Un cambio pedido por la persona sobre uno de los insumos."""

    model_config = ConfigDict(extra="forbid")

    campo: CampoEscenario
    valor: Decimal


class FotoResultado(BaseModel):
    """Lo que se compara de un resultado: cuota, semáforo y endeudamiento."""

    model_config = ConfigDict(extra="forbid")

    cuota_mensual: RangoDecimal
    semaforo: Semaforo
    razon_endeudamiento: Decimal
    capacidad_pago: Decimal


class ComparacionEscenario(BaseModel):
    """Resultado de un «¿Y si…?»: original, escenario y lectura en una frase."""

    model_config = ConfigDict(extra="forbid")

    thread_original: str
    thread_escenario: str
    cambio: CambioEscenario
    original: FotoResultado
    escenario: FotoResultado
    tendencia: Literal["mejora", "igual", "empeora"]
    mensaje: str


class EscenarioFueraDeRango(ValueError):
    """El cambio pedido está fuera de los límites: no se crea la rama."""

    def __init__(self, mensaje: str) -> None:
        """Guarda el mensaje que se le muestra a la persona.

        Args:
            mensaje: explicación del límite, lista para enviar por WhatsApp.
        """
        super().__init__(mensaje)
        self.mensaje = mensaje


class DiagnosticoNoTerminado(LookupError):
    """El hilo original no existe o su diagnóstico aún no termina."""


def interpretar_pedido(texto: str) -> CambioEscenario | None:
    """Reconoce un «¿y si…?» con plazo, monto, ingreso, gastos o cuotas.

    Es determinista: reglas sobre el texto, sin modelo. Entiende meses o años
    («48 meses», «4 años») y montos con «millones», «mil», «M» o cifras
    («8 millones», «2.500.000», «800 mil»).

    Args:
        texto: mensaje de la persona.

    Returns:
        El cambio reconocido, o None si el texto no es un escenario.
    """
    limpio = texto.lower().strip()
    if not re.search(
        r"\by\s+si\b|\bqu[eé]\s+tal\s+si\b|\bsi\s+(?:fuera|pido|pidiera|gano|ganara)\b", limpio
    ):
        return None

    plazo = re.search(r"(\d{1,3})\s*(mes(?:es)?|a[nñ]os?)\b", limpio)
    if plazo:
        meses = int(plazo.group(1)) * (12 if plazo.group(2).startswith("a") else 1)
        return CambioEscenario(campo="plazo_meses", valor=Decimal(meses))

    cifra = _leer_cifra(limpio)
    if cifra is None:
        return None
    if re.search(r"\bgan(?:o|ara|ar[ií]a)\b|ingreso|sueldo|salario", limpio):
        return CambioEscenario(campo="ingreso_mensual", valor=cifra)
    if re.search(r"\bgast(?:o|os|ara|ar[ií]a)\b", limpio):
        return CambioEscenario(campo="gastos_mensuales", valor=cifra)
    if re.search(r"\bcuotas?\b|\bdeudas?\b", limpio):
        return CambioEscenario(campo="cuotas_deudas", valor=cifra)
    return CambioEscenario(campo="monto_credito", valor=cifra)


def aplicar_cambio(entrada: EntradaDiagnostico, cambio: CambioEscenario) -> EntradaDiagnostico:
    """Devuelve la entrada con el cambio, o explica por qué no se puede.

    Args:
        entrada: insumos del diagnóstico original.
        cambio: insumo y valor nuevos.

    Returns:
        Una entrada nueva; la original no se modifica.

    Raises:
        EscenarioFueraDeRango: si el valor está fuera de los límites, con un
            mensaje que dice el rango permitido.
    """
    valor = cambio.valor
    if cambio.campo == "plazo_meses":
        minimo, maximo = PLAZO_VIVIENDA if entrada.producto == "vivienda" else PLAZO_GENERAL
        if valor != valor.to_integral_value() or not minimo <= valor <= maximo:
            raise EscenarioFueraDeRango(
                f"Para este producto el plazo va de {minimo} a {maximo} meses. "
                "Prueba con un plazo dentro de ese rango."
            )
        nuevo: Any = int(valor)
    elif cambio.campo == "monto_credito":
        if not MONTO[0] <= valor <= MONTO[1]:
            raise EscenarioFueraDeRango(
                f"El monto debe estar entre {formatear_pesos(MONTO[0])} y {formatear_pesos(MONTO[1])}."
            )
        nuevo = valor
    else:
        minimo_mensual = Decimal(1) if cambio.campo == "ingreso_mensual" else Decimal(0)
        if not minimo_mensual <= valor <= VALOR_MENSUAL_MAXIMO:
            raise EscenarioFueraDeRango(
                f"Ese valor mensual no es válido: debe estar entre {formatear_pesos(minimo_mensual)} "
                f"y {formatear_pesos(VALOR_MENSUAL_MAXIMO)}."
            )
        nuevo = valor
    try:
        return EntradaDiagnostico.model_validate({**entrada.model_dump(), cambio.campo: nuevo})
    except ValidationError as error:
        raise EscenarioFueraDeRango("Ese cambio no cabe en el diagnóstico.") from error


def bifurcar_escenario(
    grafo: GrafoConEstado,
    usuario_id: str,
    thread_original: str,
    cambio: CambioEscenario,
    calcular: Callable[[EntradaDiagnostico], ResultadoDiagnostico],
) -> ComparacionEscenario:
    """Crea la rama «¿Y si…?» de un diagnóstico terminado y la compara.

    Solo lee el hilo original. Valida el cambio **antes** de escribir nada, así
    un valor fuera de rango no deja una rama a medias.

    Args:
        grafo: grafo de diagnóstico compilado con su checkpointer.
        usuario_id: huella HMAC de la persona (nunca el número).
        thread_original: `thread_id` del diagnóstico terminado.
        cambio: insumo y valor nuevos.
        calcular: motor determinista que convierte la entrada en resultado.

    Returns:
        La comparación entre el original y el escenario.

    Raises:
        DiagnosticoNoTerminado: si el hilo no existe o no está terminado.
        EscenarioFueraDeRango: si el cambio está fuera de los límites o se
            alcanzó el máximo de escenarios.
    """
    valores = dict(grafo.get_state(_config(thread_original)).values or {})
    if valores.get("etapa") != ETAPA_TERMINADA or not valores.get("resultado"):
        raise DiagnosticoNoTerminado(
            "Primero terminemos tu diagnóstico; después podemos probar escenarios."
        )
    original = ResultadoDiagnostico.model_validate(valores["resultado"])
    entrada = aplicar_cambio(original.entrada, cambio)

    numero = _siguiente_numero(grafo, usuario_id)
    thread_escenario = f"diag:{usuario_id}:esc:{numero}"
    resultado = calcular(entrada).model_copy(update={"escenario_de": thread_original})

    estado_rama = {
        clave: valor for clave, valor in valores.items() if clave not in {"messages", "caso"}
    }
    estado_rama.update(
        etapa=ETAPA_TERMINADA,
        entrada=entrada.model_dump(mode="json"),
        resultado=resultado.model_dump(mode="json"),
        escenario={
            "escenario_de": thread_original,
            "campo": cambio.campo,
            "valor": str(cambio.valor),
            "numero": numero,
        },
    )
    grafo.update_state(_config(thread_escenario), estado_rama, as_node=NODO_FINAL)

    foto_original = _foto(original)
    foto_escenario = _foto(resultado)
    tendencia = _tendencia(foto_original, foto_escenario)
    return ComparacionEscenario(
        thread_original=thread_original,
        thread_escenario=thread_escenario,
        cambio=cambio,
        original=foto_original,
        escenario=foto_escenario,
        tendencia=tendencia,
        mensaje=redactar_comparacion(cambio, foto_original, foto_escenario, tendencia),
    )


def redactar_comparacion(
    cambio: CambioEscenario,
    original: FotoResultado,
    escenario: FotoResultado,
    tendencia: Literal["mejora", "igual", "empeora"],
) -> str:
    """Arma el mensaje de WhatsApp que compara los dos resultados.

    Args:
        cambio: lo que se cambió.
        original: foto del diagnóstico original.
        escenario: foto del escenario.
        tendencia: si el semáforo o la razón de endeudamiento mejoran.

    Returns:
        Un texto corto, con la cuota en rango y el semáforo antes y después.
    """
    que = {
        "plazo_meses": f"un plazo de {int(cambio.valor)} meses",
        "monto_credito": f"un crédito de {formatear_pesos(cambio.valor)}",
        "ingreso_mensual": f"un ingreso de {formatear_pesos(cambio.valor)} al mes",
        "gastos_mensuales": f"gastos de {formatear_pesos(cambio.valor)} al mes",
        "cuotas_deudas": f"cuotas actuales de {formatear_pesos(cambio.valor)} al mes",
    }[cambio.campo]
    lectura = {
        "mejora": "Tu situación mejora.",
        "igual": "Tu situación queda parecida.",
        "empeora": "Ojo: tu situación se aprieta.",
    }[tendencia]
    return (
        f"Con {que}, tu cuota pasaría de {formatear_rango(original.cuota_mensual)} "
        f"a {formatear_rango(escenario.cuota_mensual)} y el semáforo de "
        f"{original.semaforo} a {escenario.semaforo}. {lectura} "
        "Es un cálculo orientativo: tu diagnóstico original no cambia."
    )


def formatear_pesos(valor: Decimal) -> str:
    """Formatea pesos colombianos sin decimales y con punto de miles.

    Args:
        valor: monto en pesos.

    Returns:
        Texto como `$1.250.000`.
    """
    entero = int(valor.quantize(Decimal(1)))
    return "$" + f"{entero:,}".replace(",", ".")


def formatear_rango(rango: RangoDecimal) -> str:
    """Formatea un rango de pesos; si los extremos coinciden, una sola cifra.

    Args:
        rango: rango de la cuota u otro valor.

    Returns:
        Texto como `$410.000–$455.000`.
    """
    desde, hasta = formatear_pesos(rango.desde), formatear_pesos(rango.hasta)
    return desde if desde == hasta else f"{desde}–{hasta}"


def _foto(resultado: ResultadoDiagnostico) -> FotoResultado:
    """Extrae del resultado lo que se compara.

    Args:
        resultado: diagnóstico completo.

    Returns:
        La foto con cuota, semáforo, razón y capacidad.
    """
    return FotoResultado(
        cuota_mensual=resultado.cuota_mensual,
        semaforo=resultado.semaforo,
        razon_endeudamiento=resultado.razon_endeudamiento,
        capacidad_pago=resultado.capacidad_pago,
    )


def _tendencia(
    original: FotoResultado, escenario: FotoResultado
) -> Literal["mejora", "igual", "empeora"]:
    """Decide si el escenario mejora: primero por semáforo, luego por endeudamiento.

    Args:
        original: foto del diagnóstico original.
        escenario: foto del escenario.

    Returns:
        `mejora`, `igual` o `empeora`.
    """
    antes, despues = ORDEN_SEMAFORO[original.semaforo], ORDEN_SEMAFORO[escenario.semaforo]
    if despues != antes:
        return "mejora" if despues < antes else "empeora"
    if escenario.razon_endeudamiento < original.razon_endeudamiento:
        return "mejora"
    if escenario.razon_endeudamiento > original.razon_endeudamiento:
        return "empeora"
    return "igual"


def _siguiente_numero(grafo: GrafoConEstado, usuario_id: str) -> int:
    """Busca el primer número de escenario libre para esta persona.

    Args:
        grafo: grafo con su checkpointer.
        usuario_id: huella HMAC de la persona.

    Returns:
        El número del escenario nuevo, desde 1.

    Raises:
        EscenarioFueraDeRango: si ya hay `MAXIMO_ESCENARIOS` escenarios.
    """
    for numero in range(1, MAXIMO_ESCENARIOS + 1):
        if not grafo.get_state(_config(f"diag:{usuario_id}:esc:{numero}")).values:
            return numero
    raise EscenarioFueraDeRango(
        f"Ya probaste {MAXIMO_ESCENARIOS} escenarios. Si quieres, te comunico con un asesor."
    )


def _config(thread_id: str) -> RunnableConfig:
    """Arma la configuración de LangGraph para un hilo.

    Args:
        thread_id: identificador del hilo.

    Returns:
        La configuración con `configurable.thread_id`.
    """
    return {"configurable": {"thread_id": thread_id}}


def _leer_cifra(texto: str) -> Decimal | None:
    """Lee la primera cifra en pesos de un texto en español.

    Con unidad («8 millones», «2,5 M», «800 mil») admite decimales; sin unidad
    («2.500.000») los puntos y comas son separadores de miles.

    Args:
        texto: texto en minúsculas.

    Returns:
        La cifra en pesos, o None si no hay.
    """
    coincidencia = re.search(r"(\d+(?:[.,]\d+)*)\s*(millones|mill[oó]n|m\b|mil\b)?", texto)
    if not coincidencia:
        return None
    numero, unidad = coincidencia.group(1), coincidencia.group(2) or ""
    separadores = numero.count(".") + numero.count(",")
    if unidad and separadores == 1:
        normal = numero.replace(",", ".")
    else:
        normal = numero.replace(".", "").replace(",", "")
    try:
        cifra = Decimal(normal)
    except InvalidOperation:
        return None
    if unidad == "mil":
        return cifra * 1_000
    if unidad:
        return cifra * 1_000_000
    return cifra
