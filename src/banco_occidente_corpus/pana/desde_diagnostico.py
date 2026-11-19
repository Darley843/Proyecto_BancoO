"""Convierte el resultado del motor del diagnóstico en datos de tarjeta.

Es el puente entre `diagnostico.motor` (que devuelve un `ResultadoDiagnostico`
con cifras en `Decimal` y tasas como fracción) y las tarjetas de Pana (que
piden textos cortos y porcentajes). Aquí no se calcula nada nuevo: solo se
eligen y se formatean los datos que el motor ya produjo.

Qué tarjeta corresponde a cada resultado:

- Crédito con cuota simulada → `DatosDiagnostico` (con `ahorro_mensual` en la
  compra de cartera cuando el traslado sí baja la cuota).
- Ahorro → `DatosAhorro` (sin semáforo).
- Libranza para independiente o capacidad negativa → `DatosNoAplica`.

`tarjeta_y_texto` hace todo el recorrido y devuelve el PNG y su texto
equivalente, que llevan los mismos datos. Nada de esto toca el disco.
"""

from __future__ import annotations

from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from ..canal.contratos import ResultadoDiagnostico
from ..canal.contratos import TasaCaptacion as TasaContrato
from ..diagnostico.escenarios import ComparacionEscenario
from ..tablero.tasas import nombre_producto
from .tarjetas import (
    DatosAhorro,
    DatosDiagnostico,
    DatosEscenario,
    DatosNoAplica,
    FotoEscenario,
    TasaCaptacion,
    pesos,
    tarjeta_ahorro,
    tarjeta_diagnostico,
    tarjeta_escenario,
    tarjeta_no_aplica,
    texto_ahorro,
    texto_diagnostico,
    texto_escenario,
    texto_no_aplica,
)

#: Datos que puede recibir una tarjeta de diagnóstico.
DatosTarjeta = DatosDiagnostico | DatosAhorro | DatosNoAplica

#: Nombre corto de la fuente que se muestra en la tarjeta. El detalle (archivo,
#: huella del PDF) queda en el `ResultadoDiagnostico` para el Arqueo.
FUENTE_TARJETA = "Tablero de tasas"

#: Abreviatura de cada mes, como se imprime en la tarjeta («nov. 2026»).
MESES_CORTOS: dict[int, str] = {
    1: "ene.",
    2: "feb.",
    3: "mar.",
    4: "abr.",
    5: "may.",
    6: "jun.",
    7: "jul.",
    8: "ago.",
    9: "sep.",
    10: "oct.",
    11: "nov.",
    12: "dic.",
}

#: Frase del semáforo según el color, con la parte del ingreso que se va en cuotas.
FRASE_SEMAFORO: dict[str, str] = {
    "verde": "Tus cuotas se llevarían {p} de tu ingreso: cabe con margen.",
    "amarillo": "Tus cuotas se llevarían {p} de tu ingreso: cabe, pero justo.",
    "rojo": "Tus cuotas se llevarían {p} de tu ingreso: aprieta demasiado.",
}
#: Frase cuando la cuota no cabe en lo que queda libre (margen negativo).
FRASE_SIN_MARGEN = "La cuota no cabe en lo que te queda libre cada mes."
#: Frase cuando la vivienda supera el tope de la primera cuota.
FRASE_VIVIENDA = "En vivienda la primera cuota no debe pasar del 30 % de tu ingreso."

#: Textos de la tarjeta «no aplica» según la alerta del motor.
NO_APLICA: dict[str, tuple[str, str]] = {
    "libranza_no_aplica": (
        "La libranza solo está disponible para empleados o pensionados con "
        "convenio de descuento.",
        "Puedes simular un préstamo de libre inversión o hablar con un asesor.",
    ),
    "capacidad_negativa": (
        "Hoy tus gastos y cuotas ya superan tu ingreso, así que no se simula un "
        "crédito nuevo.",
        "Ordena primero tus gastos y deudas, o habla con un asesor.",
    ),
}

#: Frase del ahorro según haya o no margen al mes.
FRASE_AHORRO_CON_MARGEN = "Es lo que te queda libre al mes después de gastos y cuotas."
FRASE_AHORRO_SIN_MARGEN = "Tus gastos y cuotas se llevan todo tu ingreso: primero libera margen."

#: Nota de la tarjeta «¿Y si…?» según la tendencia del escenario.
NOTA_TENDENCIA: dict[str, str] = {
    "mejora": "Tu situación mejora.",
    "igual": "Tu situación queda parecida.",
    "empeora": "Ojo: tu situación se aprieta.",
}
#: Frase común a todas las notas del escenario.
NOTA_ORIGINAL = "Tu diagnóstico original no cambió."


class SinTarjeta(ValueError):
    """El resultado no tiene datos suficientes para ninguna tarjeta."""


def _pct(fraccion: Decimal) -> Decimal:
    """Pasa una fracción (0,0185) a porcentaje con dos decimales (1,85).

    Args:
        fraccion: valor entre 0 y 1.

    Returns:
        El porcentaje redondeado a dos decimales.
    """
    return (fraccion * 100).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _pct_texto(fraccion: Decimal) -> str:
    """Escribe una fracción como porcentaje entero, al estilo «35 %».

    Args:
        fraccion: valor entre 0 y 1 (puede pasar de 1 si las cuotas superan el
            ingreso).

    Returns:
        El porcentaje redondeado sin decimales.
    """
    entero = int((fraccion * 100).quantize(Decimal(1), rounding=ROUND_HALF_UP))
    return f"{entero} %"


def vigencia_corta(hasta: date | None, *, vencida: bool = False) -> str:
    """Escribe la vigencia de la tasa como «nov. 2026».

    Args:
        hasta: último día de la vigencia publicada, o None si no se conoce.
        vencida: si el motor marcó `vigencia_vencida`.

    Returns:
        El mes y el año, con «, vencida» cuando ya no cubre la fecha de hoy, o
        «sin vigencia» si no hay fecha.
    """
    if hasta is None:
        return "sin vigencia"
    texto = f"{MESES_CORTOS[hasta.month]} {hasta.year}"
    return f"{texto}, vencida" if vencida else texto


def _razon_credito(resultado: ResultadoDiagnostico) -> str:
    """Elige la frase corta que explica el color del semáforo.

    Args:
        resultado: diagnóstico de un crédito con cuota.

    Returns:
        Una frase de menos de 110 caracteres, sin números largos.
    """
    if "vivienda_30" in resultado.alertas:
        return FRASE_VIVIENDA
    if resultado.margen_despues_cuota is not None and resultado.margen_despues_cuota < 0:
        return FRASE_SIN_MARGEN
    color = resultado.semaforo or "rojo"
    razon = resultado.razon_endeudamiento or Decimal(0)
    return FRASE_SEMAFORO[color].format(p=_pct_texto(razon))


def _etiqueta_captacion(tasa: TasaContrato) -> str:
    """Nombre corto de una tasa de ahorro o CDT para la tarjeta.

    Args:
        tasa: tasa de captación del contrato.

    Returns:
        «Cuenta de ahorros» o «CDT» con el primer plazo si lo hay (máx. 30
        caracteres).
    """
    if tasa.producto == "ahorro":
        return "Cuenta de ahorros"
    if tasa.tramos:
        primero, ultimo = tasa.tramos[0].etiqueta, tasa.tramos[-1].etiqueta
        detalle = primero if primero == ultimo else f"{primero} a {ultimo}"
        etiqueta = f"CDT {detalle}"
        if len(etiqueta) <= 30:
            return etiqueta
    return "CDT"


def datos_diagnostico(resultado: ResultadoDiagnostico) -> DatosDiagnostico:
    """Convierte un crédito con cuota simulada en datos de tarjeta.

    Usa la tasa mensual máxima, la misma con la que el motor calcula el
    semáforo, para no mostrar una tasa más amable que el color.

    Args:
        resultado: diagnóstico de un producto de crédito.

    Returns:
        Los datos validados de la tarjeta del diagnóstico.

    Raises:
        SinTarjeta: si el resultado no trae cuota, semáforo o tasa.
    """
    entrada = resultado.entrada
    if (
        resultado.cuota_mensual is None
        or resultado.semaforo is None
        or resultado.tasa_mensual is None
        or entrada.monto_credito is None
        or entrada.plazo_meses is None
    ):
        raise SinTarjeta("el resultado no tiene una cuota de crédito simulada")
    ahorro = resultado.ahorro_mensual_estimado
    return DatosDiagnostico(
        producto=nombre_producto(entrada.producto),
        monto=entrada.monto_credito,
        plazo_meses=entrada.plazo_meses,
        semaforo=resultado.semaforo,
        cuota_min=resultado.cuota_mensual.desde,
        cuota_max=resultado.cuota_mensual.hasta,
        razon=_razon_credito(resultado),
        tasa_mensual_pct=_pct(resultado.tasa_mensual.hasta),
        tasa_vigencia=vigencia_corta(
            resultado.vigencia_tasa_hasta, vencida="vigencia_vencida" in resultado.alertas
        ),
        tasa_fuente=FUENTE_TARJETA,
        ahorro_mensual=ahorro if ahorro is not None and ahorro > 0 else None,
    )


def datos_ahorro(resultado: ResultadoDiagnostico) -> DatosAhorro:
    """Convierte un resultado de ahorro en datos de tarjeta.

    Args:
        resultado: diagnóstico con producto `ahorro`.

    Returns:
        Los datos validados de la tarjeta de ahorro, con hasta tres tasas.
    """
    capacidad = resultado.capacidad_pago
    tasas = [
        TasaCaptacion(
            etiqueta=_etiqueta_captacion(tasa),
            ea_min_pct=_pct(tasa.tasa_ea.desde),
            ea_max_pct=_pct(tasa.tasa_ea.hasta),
        )
        for tasa in resultado.tasas_captacion[:3]
    ]
    hasta = resultado.tasas_captacion[0].vigencia_hasta if resultado.tasas_captacion else None
    return DatosAhorro(
        capacidad_ahorro=capacidad,
        razon=FRASE_AHORRO_CON_MARGEN if capacidad > 0 else FRASE_AHORRO_SIN_MARGEN,
        tasas=tasas,
        tasa_vigencia=vigencia_corta(hasta, vencida="vigencia_vencida" in resultado.alertas),
        tasa_fuente=FUENTE_TARJETA,
    )


def datos_no_aplica(resultado: ResultadoDiagnostico) -> DatosNoAplica:
    """Convierte una libranza que no aplica o una capacidad negativa en datos.

    Args:
        resultado: diagnóstico con la alerta `libranza_no_aplica` o
            `capacidad_negativa`.

    Returns:
        Los datos validados de la tarjeta «no aplica».

    Raises:
        SinTarjeta: si el resultado no trae ninguna de esas dos alertas.
    """
    for alerta, (razon, alternativa) in NO_APLICA.items():
        if alerta in resultado.alertas:
            return DatosNoAplica(
                producto=nombre_producto(resultado.entrada.producto),
                razon=razon,
                alternativa=alternativa,
            )
    raise SinTarjeta("el resultado no es un caso de «no aplica»")


def datos_tarjeta(resultado: ResultadoDiagnostico) -> DatosTarjeta:
    """Elige la tarjeta que corresponde al resultado y arma sus datos.

    Args:
        resultado: diagnóstico del motor.

    Returns:
        `DatosAhorro`, `DatosNoAplica` o `DatosDiagnostico`, según el caso.

    Raises:
        SinTarjeta: si el resultado no encaja en ninguna tarjeta.
    """
    if resultado.entrada.producto == "ahorro":
        return datos_ahorro(resultado)
    if {"libranza_no_aplica", "capacidad_negativa"} & set(resultado.alertas):
        return datos_no_aplica(resultado)
    return datos_diagnostico(resultado)


def tarjeta_y_texto(resultado: ResultadoDiagnostico) -> tuple[bytes, str]:
    """Genera la tarjeta PNG y su texto equivalente a partir del resultado.

    El texto lleva los mismos datos que la imagen: el canal lo envía primero y
    la imagen después, de modo que una falla de la imagen no deja a la persona
    sin respuesta.

    Args:
        resultado: diagnóstico del motor.

    Returns:
        Los bytes del PNG (en memoria) y el texto para WhatsApp.

    Raises:
        SinTarjeta: si el resultado no encaja en ninguna tarjeta.
    """
    datos = datos_tarjeta(resultado)
    if isinstance(datos, DatosAhorro):
        return tarjeta_ahorro(datos), texto_ahorro(datos)
    if isinstance(datos, DatosNoAplica):
        return tarjeta_no_aplica(datos), texto_no_aplica(datos)
    return tarjeta_diagnostico(datos), texto_diagnostico(datos)


def _pregunta(comparacion: ComparacionEscenario) -> str:
    """Escribe la pregunta del escenario como la vería la persona.

    Args:
        comparacion: resultado del «¿Y si…?».

    Returns:
        Por ejemplo «¿Y si lo pagas en 36 meses?» (máx. 60 caracteres).
    """
    valor = comparacion.cambio.valor
    return {
        "plazo_meses": f"¿Y si lo pagas en {int(valor)} meses?",
        "monto_credito": f"¿Y si pides {pesos(valor)}?",
        "ingreso_mensual": f"¿Y si ganas {pesos(valor)} al mes?",
        "gastos_mensuales": f"¿Y si gastas {pesos(valor)} al mes?",
        "cuotas_deudas": f"¿Y si tus cuotas son {pesos(valor)}?",
    }[comparacion.cambio.campo]


def _nota(comparacion: ComparacionEscenario) -> str:
    """Resume en una frase lo que cambia con el escenario.

    Args:
        comparacion: resultado del «¿Y si…?».

    Returns:
        La lectura de la tendencia y el recordatorio de que el original no
        cambió (máx. 120 caracteres).
    """
    lectura = NOTA_TENDENCIA[comparacion.tendencia]
    if comparacion.cambio.campo == "plazo_meses":
        antes = comparacion.original.cuota_mensual.hasta
        despues = comparacion.escenario.cuota_mensual.hasta
        if despues < antes:
            lectura = "Pagas menos al mes, pero más intereses en total."
        elif despues > antes:
            lectura = "Pagas más al mes, pero menos intereses en total."
    return f"{lectura} {NOTA_ORIGINAL}"


def datos_escenario(comparacion: ComparacionEscenario, plazo_meses: int) -> DatosEscenario:
    """Convierte un «¿Y si…?» del motor en datos de tarjeta.

    `ComparacionEscenario` no guarda el plazo de cada lado, así que se recibe
    el del diagnóstico original. Si lo que cambió fue el plazo, el escenario
    toma el valor nuevo; si no, conserva el mismo.

    Args:
        comparacion: resultado de `bifurcar_escenario`.
        plazo_meses: plazo del diagnóstico original.

    Returns:
        Los datos validados de la tarjeta «¿Y si…?».
    """
    cambio = comparacion.cambio
    plazo_nuevo = int(cambio.valor) if cambio.campo == "plazo_meses" else plazo_meses
    original, escenario = comparacion.original, comparacion.escenario
    return DatosEscenario(
        pregunta=_pregunta(comparacion),
        antes=FotoEscenario(
            plazo_meses=plazo_meses,
            semaforo=original.semaforo,
            cuota_min=original.cuota_mensual.desde,
            cuota_max=original.cuota_mensual.hasta,
        ),
        despues=FotoEscenario(
            plazo_meses=plazo_nuevo,
            semaforo=escenario.semaforo,
            cuota_min=escenario.cuota_mensual.desde,
            cuota_max=escenario.cuota_mensual.hasta,
        ),
        nota=_nota(comparacion),
    )


def escenario_y_texto(comparacion: ComparacionEscenario, plazo_meses: int) -> tuple[bytes, str]:
    """Genera la tarjeta «¿Y si…?» y su texto equivalente.

    Args:
        comparacion: resultado de `bifurcar_escenario`.
        plazo_meses: plazo del diagnóstico original.

    Returns:
        Los bytes del PNG (en memoria) y el texto para WhatsApp.
    """
    datos = datos_escenario(comparacion, plazo_meses)
    return tarjeta_escenario(datos), texto_escenario(datos)
