"""Motor de cálculo determinista del diagnóstico financiero.

El módulo no importa LangGraph ni el modelo: solo aritmética en `Decimal` y
consulta offline de la tabla Gold de tasas. Sigue `docs/DIAGNOSTICO.md`:

- Tasa mensual: ``i = (1 + E.A.) ** (1/12) - 1`` sin redondear.
- Cuota francesa: ``cuota = monto * i / (1 - (1 + i) ** -n)``; con ``i = 0``
  la cuota es ``monto / n``. Solo la cuota final se redondea al peso.
- Capacidad de pago: ``ingreso - gastos - cuotas`` actuales, antes de la cuota
  nueva; en compra de cartera se restan las cuotas que se trasladan.
- Margen después de la cuota: ``capacidad - cuota_nueva``. Si es negativo, el
  semáforo es rojo.
- Razón de endeudamiento: ``(cuotas + cuota_nueva) / ingreso``; en compra de
  cartera se descuenta la cuota trasladada.
- La cuota se publica como rango entre la tasa mínima y la máxima, pero el
  semáforo, la razón y la capacidad se calculan con la tasa **máxima**.

Las reglas especiales (vivienda, libranza, compra de cartera, ahorro y
capacidad negativa) devuelven motivos explicables y nunca simulan un crédito
que no corresponde. La tasa se lee de `tablero.tasas` y nunca de un spread.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from datetime import date
from decimal import ROUND_HALF_UP, Context, Decimal, localcontext
from pathlib import Path
from typing import Literal

from ..tablero.tasas import (
    ALERTA_VIGENCIA_VENCIDA,
    BANDAS_MONTO,
    BandaMonto,
    FilaTasa,
    TasaFueraDeRango,
    TasaNoDisponible,
    banda_de_concepto,
    clave_producto,
    esta_vigente,
    fecha_legible,
    nombre_producto,
    plazo_legible,
    tasas_producto,
    vigencia_legible,
)

#: Resultado posible del semáforo de crédito. `None` significa «no aplica».
Semaforo = Literal["verde", "amarillo", "rojo"]

#: Versión de las fórmulas, que se guarda en el resultado para reproducirlo.
VERSION_FORMULA = "v1"
#: El semáforo se calcula siempre con la tasa máxima del rango publicado.
BASE_SEMAFORO: Literal["tasa_maxima"] = "tasa_maxima"
#: Umbral por defecto entre verde y amarillo.
UMBRAL_VERDE = Decimal("0.30")
#: Umbral por defecto entre amarillo y rojo.
UMBRAL_AMARILLO = Decimal("0.40")
#: En vivienda, la primera cuota no debe superar este porcentaje del ingreso.
UMBRAL_VIVIENDA = Decimal("0.30")
#: Precisión decimal de las fórmulas.
PRECISION = 28
#: Doce meses de un año para la equivalencia de tasas.
MESES_ANIO = Decimal(12)
#: Productos que el diagnóstico puede simular.
PRODUCTOS_DIAGNOSTICO: frozenset[str] = frozenset(
    {
        "libre_inversion",
        "compra_cartera",
        "vivienda",
        "libranza",
        "vehiculo_nuevo",
        "vehiculo_usado",
        "ahorro",
    }
)
#: Productos con cuota francesa; el ahorro no simula crédito.
PRODUCTOS_CREDITO: frozenset[str] = PRODUCTOS_DIAGNOSTICO - {"ahorro"}
#: Productos cuyas tasas puede leer el motor, incluido el CDT de captación.
PRODUCTOS_TASAS: frozenset[str] = PRODUCTOS_DIAGNOSTICO | {"cdt"}
#: Segmento del Tablero que corresponde a cada producto con varios segmentos.
SEGMENTOS: dict[str, str] = {
    "vivienda": "credito_hipotecario",
    "libranza": "libre_inversion",
}
#: Formas válidas de recibir ingresos para el diagnóstico.
VINCULACIONES: frozenset[str] = frozenset({"empleado", "independiente", "pensionado"})
#: Recomendaciones deterministas por color.
RECOMENDACIONES: dict[str, tuple[str, ...]] = {
    "verde": (
        "La cuota cabe con margen en tu presupuesto.",
        "Compara plazos: el más corto paga menos intereses.",
        "Revisa los requisitos del producto en la Bóveda.",
    ),
    "amarillo": (
        "La cuota cabe, pero con poco margen.",
        "Considera un plazo más largo o un monto menor.",
        "Simula de nuevo con «¿y si…?» para comparar.",
    ),
    "rojo": (
        "Con estos datos la cuota compromete demasiado tu ingreso.",
        "Considera un monto menor o un plazo mayor.",
        "Si tienes deudas caras, evalúa una compra de cartera.",
        "Habla con un asesor para revisar tu caso.",
    ),
}


@dataclass(frozen=True, slots=True)
class TramoCaptacion:
    """Plazo o tramo de saldo de una tasa de captación, con su tasa E.A."""

    etiqueta: str
    ea_desde: Decimal
    ea_hasta: Decimal


@dataclass(frozen=True, slots=True)
class TasaProducto:
    """Rango de tasa E.A. de un producto, con su vigencia y su fuente.

    En ahorro y CDT, `ea_desde`–`ea_hasta` es el rango de referencia (el tramo
    de saldo más bajo o el monto mínimo por plazo), `tramo` nombra ese tramo,
    `rango_completo_*` conserva la envolvente del producto y `tramos` desagrega
    el CDT por plazo.
    """

    producto: str
    segmento: str | None
    ea_desde: Decimal
    ea_hasta: Decimal
    vigencia_desde: date
    vigencia_hasta: date
    fuente: str
    sha256_pdf: str
    tramo: str | None = None
    rango_completo_desde: Decimal | None = None
    rango_completo_hasta: Decimal | None = None
    tramos: tuple[TramoCaptacion, ...] = ()


@dataclass(frozen=True, slots=True)
class EntradaCalculo:
    """Insumos normalizados de un diagnóstico, independientes del canal.

    `producto` acepta la clave canónica del Tablero (`libre_inversion`,
    `compra_cartera`, `vivienda`, `libranza`, `vehiculo_nuevo`,
    `vehiculo_usado` o `ahorro`). `monto_credito` y `plazo_meses` son
    obligatorios para los productos de crédito y se ignoran en ahorro.
    """

    producto: str
    ingreso_mensual: Decimal
    gastos_mensuales: Decimal
    cuotas_deudas: Decimal = Decimal(0)
    monto_credito: Decimal | None = None
    plazo_meses: int | None = None
    vinculacion: str = "empleado"
    cuota_trasladar: Decimal | None = None


@dataclass(frozen=True, slots=True)
class ResultadoCalculo:
    """Resultado determinista del cálculo, con sus motivos y recomendaciones."""

    producto: str
    version_formula: str
    base_semaforo: Literal["tasa_maxima"]
    tasa: TasaProducto | None
    tasa_mensual_min: Decimal | None
    tasa_mensual_max: Decimal | None
    cuota_min: Decimal | None
    cuota_max: Decimal | None
    total_intereses_min: Decimal | None
    total_intereses_max: Decimal | None
    total_pagado_min: Decimal | None
    total_pagado_max: Decimal | None
    razon_endeudamiento: Decimal | None
    capacidad_pago: Decimal
    margen_despues_cuota: Decimal | None
    capacidad_ahorro: Decimal | None
    ahorro_mensual: Decimal | None
    semaforo: Semaforo | None
    alertas: tuple[str, ...]
    motivos: tuple[str, ...]
    recomendaciones: tuple[str, ...]
    tasas_captacion: tuple[TasaProducto, ...]
    aviso: str


def tasa_mensual(valor_ea: Decimal) -> Decimal:
    """Convierte una tasa efectiva anual en su equivalente mensual.

    Args:
        valor_ea: tasa efectiva anual como decimal entre 0 y 1.

    Returns:
        La tasa mensual con la precisión completa del contexto (28 dígitos),
        sin redondear.

    Raises:
        ValueError: si la tasa no está entre 0 y 1.
    """
    ea = Decimal(valor_ea)
    if not Decimal(0) <= ea <= Decimal(1):
        raise ValueError(f"la tasa E.A. debe estar entre 0 y 1: {ea}")
    if ea == 0:
        return Decimal(0)
    with localcontext(_contexto()):
        return (Decimal(1) + ea) ** (Decimal(1) / MESES_ANIO) - Decimal(1)


def cuota_francesa(monto: Decimal, tasa: Decimal, plazo_meses: int) -> Decimal:
    """Calcula la cuota fija de un crédito con amortización francesa.

    Args:
        monto: capital prestado, en pesos.
        tasa: tasa mensual como decimal (por ejemplo, 0,0209).
        plazo_meses: número de cuotas mensuales.

    Returns:
        La cuota mensual, redondeada al peso.

    Raises:
        ValueError: si el monto o la tasa son negativos o el plazo no es positivo.
    """
    capital = Decimal(monto)
    interes = Decimal(tasa)
    cuotas = int(plazo_meses)
    if capital < 0:
        raise ValueError(f"el monto no puede ser negativo: {capital}")
    if interes < 0:
        raise ValueError(f"la tasa mensual no puede ser negativa: {interes}")
    if cuotas <= 0:
        raise ValueError(f"el plazo debe ser positivo: {cuotas}")
    if interes == 0:
        return _peso(capital / cuotas)
    with localcontext(_contexto()):
        cuota = capital * interes / (Decimal(1) - (Decimal(1) + interes) ** (-cuotas))
    return _peso(cuota)


def capacidad_pago(
    ingreso_mensual: Decimal,
    gastos_mensuales: Decimal,
    cuotas_deudas: Decimal,
    cuota_trasladar: Decimal = Decimal(0),
) -> Decimal:
    """Calcula la capacidad de pago antes de la cuota nueva.

    En compra de cartera las cuotas trasladadas desaparecen de las deudas
    actuales, así que la capacidad comparable resta solo
    ``cuotas - cuota_trasladar``.

    Args:
        ingreso_mensual: ingreso mensual, en pesos.
        gastos_mensuales: gastos fijos mensuales, en pesos.
        cuotas_deudas: cuotas actuales de créditos y tarjetas, en pesos.
        cuota_trasladar: cuota actual que se deja de pagar, en pesos.

    Returns:
        `ingreso - gastos - (cuotas - trasladar)`, redondeada al peso. Puede
        ser negativa, y en ese caso el diagnóstico no simula el crédito.
    """
    return _peso(
        Decimal(ingreso_mensual)
        - Decimal(gastos_mensuales)
        - (Decimal(cuotas_deudas) - Decimal(cuota_trasladar))
    )


def margen_despues_cuota(capacidad: Decimal, cuota_nueva: Decimal) -> Decimal:
    """Calcula el margen que queda después de pagar la cuota nueva.

    Args:
        capacidad: capacidad de pago antes de la cuota nueva, en pesos.
        cuota_nueva: cuota del crédito simulado, en pesos.

    Returns:
        `capacidad - cuota_nueva`, redondeado al peso. Un margen negativo
        obliga a un semáforo rojo.
    """
    return _peso(Decimal(capacidad) - Decimal(cuota_nueva))


def razon_endeudamiento(
    cuotas_deudas: Decimal,
    cuota_nueva: Decimal,
    ingreso_mensual: Decimal,
    cuota_trasladar: Decimal = Decimal(0),
) -> Decimal:
    """Calcula la razón entre las cuotas y el ingreso mensual.

    En compra de cartera se descuenta del numerador la cuota que se traslada,
    porque deja de pagarse en las deudas actuales.

    Args:
        cuotas_deudas: cuotas actuales de créditos y tarjetas, en pesos.
        cuota_nueva: cuota del crédito simulado, en pesos.
        ingreso_mensual: ingreso mensual, en pesos.
        cuota_trasladar: cuota actual que se traslada, en pesos.

    Returns:
        La razón como decimal entre 0 y 1, redondeada a cuatro decimales.

    Raises:
        ValueError: si el ingreso no es positivo o la cuota trasladada supera
            las cuotas actuales más la cuota nueva.
    """
    ingreso = Decimal(ingreso_mensual)
    if ingreso <= 0:
        raise ValueError(f"el ingreso mensual debe ser positivo: {ingreso}")
    numerador = Decimal(cuotas_deudas) + Decimal(cuota_nueva) - Decimal(cuota_trasladar)
    if numerador < 0:
        raise ValueError("la cuota trasladada no puede superar las cuotas más la cuota nueva")
    with localcontext(_contexto()):
        razon = numerador / ingreso
    return _cuantizar(razon, 4)


def semaforo(
    razon: Decimal,
    cuota: Decimal,
    capacidad: Decimal,
    verde_hasta: Decimal = UMBRAL_VERDE,
    amarillo_hasta: Decimal = UMBRAL_AMARILLO,
) -> Semaforo:
    """Clasifica el resultado en verde, amarillo o rojo.

    El margen después de la cuota es ``capacidad - cuota``: si es negativo, el
    semáforo es rojo; después se aplican los umbrales de la razón.

    Args:
        razon: razón de endeudamiento como decimal.
        cuota: cuota nueva calculada con la tasa máxima, en pesos.
        capacidad: capacidad de pago antes de la cuota nueva, en pesos.
        verde_hasta: umbral máximo de la razón para verde.
        amarillo_hasta: umbral máximo de la razón para amarillo.

    Returns:
        `verde` si la razón no supera `verde_hasta` y el margen no es negativo;
        `amarillo` si no supera `amarillo_hasta`; `rojo` en el resto.

    Raises:
        ValueError: si los umbrales no están entre 0 y 1 o están invertidos.
    """
    verde = Decimal(verde_hasta)
    amarillo = Decimal(amarillo_hasta)
    if not Decimal(0) <= verde <= amarillo <= Decimal(1):
        raise ValueError(f"umbrales inválidos: verde={verde}, amarillo={amarillo}")
    if margen_despues_cuota(capacidad, cuota) < 0:
        return "rojo"
    if razon > amarillo:
        return "rojo"
    if razon > verde:
        return "amarillo"
    return "verde"


def tasa_de_tablero(
    producto: str,
    fecha: date | None = None,
    *,
    raiz: Path | None = None,
) -> TasaProducto:
    """Lee del Tablero el rango de tasa de un producto, sin spreads.

    Vivienda usa el segmento «Crédito hipotecario» y libranza el segmento
    «Libre inversión»; el resto de productos usa la envolvente de sus filas
    fijas. El ahorro devuelve como referencia el tramo de saldo más bajo y el
    CDT el rango por plazo del monto mínimo, con la envolvente en
    `rango_completo_*`. La consulta es offline y conserva vigencia, fuente y
    `sha256`. Si la fecha quedó fuera de todas las vigencias, usa la más
    reciente: el cálculo agrega la alerta `vigencia_vencida` en `evaluar`.

    Args:
        producto: clave o nombre del producto.
        fecha: fecha consultada; por defecto, la vigencia más reciente.
        raiz: carpeta de tablas Gold alternativa; por defecto la del Tablero.

    Returns:
        El rango E.A. del producto con su segmento y su trazabilidad.

    Raises:
        TasaNoDisponible: si el producto o el segmento no tienen tasa.
        TasaFueraDeRango: si la envolvente no es un decimal válido.
    """
    clave = clave_producto(producto)
    if clave not in PRODUCTOS_TASAS:
        raise TasaNoDisponible(f"«{producto}» no es un producto del diagnóstico")
    if clave == "ahorro":
        return _tasa_ahorro(fecha, raiz)
    if clave == "cdt":
        return _tasa_cdt(fecha, raiz)

    filas = tasas_producto(clave, fecha, raiz=raiz)
    segmento = SEGMENTOS.get(clave)
    if segmento is not None:
        filas = [fila for fila in filas if clave_producto(fila.segmento or "") == segmento]
        if not filas:
            raise TasaNoDisponible(f"no hay tasa de «{producto}» en el segmento «{segmento}»")
    desde = min(fila.tasa_ea_desde for fila in filas)
    hasta = max(fila.tasa_ea_hasta for fila in filas)
    if not Decimal(0) <= desde <= hasta <= Decimal(1):
        raise TasaFueraDeRango(f"{clave}: la envolvente E.A. queda en {desde}–{hasta}")
    segmentos = {fila.segmento for fila in filas}
    return TasaProducto(
        producto=clave,
        segmento=segmentos.pop() if len(segmentos) == 1 else None,
        ea_desde=desde,
        ea_hasta=hasta,
        vigencia_desde=min(fila.vigencia_desde for fila in filas),
        vigencia_hasta=max(fila.vigencia_hasta for fila in filas),
        fuente=filas[0].fuente,
        sha256_pdf=filas[0].sha256_pdf,
    )


def _tasa_ahorro(fecha: date | None, raiz: Path | None) -> TasaProducto:
    """Toma el tramo de saldo más bajo como referencia y conserva la envolvente.

    Args:
        fecha: fecha de la vigencia consultada.
        raiz: carpeta de tablas Gold alternativa.

    Returns:
        La tasa del tramo más bajo, con la etiqueta del tramo y el rango
        completo por saldo.

    Raises:
        TasaNoDisponible: si no hay tasa de ahorro publicada.
        TasaFueraDeRango: si alguna tasa no es un decimal válido.
    """
    filas = tasas_producto("ahorro", fecha, raiz=raiz)
    completa_desde, completa_hasta = _envolvente("ahorro", filas)
    referencia = min(filas, key=lambda fila: (_inicio_tramo(fila.segmento), fila.segmento or ""))
    desde, hasta = _rango_valido("ahorro", referencia.tasa_ea_desde, referencia.tasa_ea_hasta)
    return TasaProducto(
        producto="ahorro",
        segmento=referencia.segmento,
        ea_desde=desde,
        ea_hasta=hasta,
        vigencia_desde=min(fila.vigencia_desde for fila in filas),
        vigencia_hasta=max(fila.vigencia_hasta for fila in filas),
        fuente=referencia.fuente,
        sha256_pdf=referencia.sha256_pdf,
        tramo=referencia.segmento,
        rango_completo_desde=completa_desde,
        rango_completo_hasta=completa_hasta,
    )


def _tasa_cdt(fecha: date | None, raiz: Path | None) -> TasaProducto:
    """Toma el monto mínimo del CDT y devuelve su rango por plazo.

    Así la referencia no es el máximo de la envolvente (12,15 % E.A.), sino lo
    que paga el CDT de menor monto según el plazo; el rango completo del
    producto queda en `rango_completo_*` como dato adicional.

    Args:
        fecha: fecha de la vigencia consultada.
        raiz: carpeta de tablas Gold alternativa.

    Returns:
        El rango por plazo del monto mínimo, con el detalle de cada plazo.

    Raises:
        TasaNoDisponible: si no hay tasa de CDT publicada.
        TasaFueraDeRango: si alguna tasa no es un decimal válido.
    """
    filas = tasas_producto("cdt", fecha, raiz=raiz)
    completa_desde, completa_hasta = _envolvente("cdt", filas)
    banda, referidas = _banda_minima(filas)
    tramos = _tramos_por_plazo(referidas)
    if tramos:
        desde = min(tramo.ea_desde for tramo in tramos)
        hasta = max(tramo.ea_hasta for tramo in tramos)
    else:
        desde = min(fila.tasa_ea_desde for fila in referidas)
        hasta = max(fila.tasa_ea_hasta for fila in referidas)
    desde, hasta = _rango_valido("cdt", desde, hasta)
    return TasaProducto(
        producto="cdt",
        segmento=banda.etiqueta if banda is not None else None,
        ea_desde=desde,
        ea_hasta=hasta,
        vigencia_desde=min(fila.vigencia_desde for fila in filas),
        vigencia_hasta=max(fila.vigencia_hasta for fila in filas),
        fuente=referidas[0].fuente,
        sha256_pdf=referidas[0].sha256_pdf,
        tramo=banda.etiqueta if banda is not None else None,
        rango_completo_desde=completa_desde,
        rango_completo_hasta=completa_hasta,
        tramos=tramos,
    )


def _banda_minima(filas: list[FilaTasa]) -> tuple[BandaMonto | None, list[FilaTasa]]:
    """Busca la banda de monto más baja del CDT y sus filas.

    Args:
        filas: tasas fijas del CDT en la vigencia elegida.

    Returns:
        La banda de monto más baja con sus filas, o `(None, filas)` si ninguna
        fila nombra una banda conocida.
    """
    for banda in BANDAS_MONTO:
        coinciden = [fila for fila in filas if banda_de_concepto(fila.segmento or "") is banda]
        if coinciden:
            return banda, coinciden
    return None, filas


def _tramos_por_plazo(filas: list[FilaTasa]) -> tuple[TramoCaptacion, ...]:
    """Agrupa las filas del CDT por plazo y arma su rango de tasa.

    Args:
        filas: filas del CDT de la banda de monto elegida.

    Returns:
        Un tramo por plazo, de menor a mayor, con su etiqueta legible.
    """
    por_plazo: dict[int, list[FilaTasa]] = {}
    for fila in filas:
        if fila.plazo_dias is not None:
            por_plazo.setdefault(fila.plazo_dias, []).append(fila)
    return tuple(
        TramoCaptacion(
            etiqueta=plazo_legible(plazo),
            ea_desde=min(fila.tasa_ea_desde for fila in por_plazo[plazo]),
            ea_hasta=max(fila.tasa_ea_hasta for fila in por_plazo[plazo]),
        )
        for plazo in sorted(por_plazo)
    )


def _envolvente(producto: str, filas: list[FilaTasa]) -> tuple[Decimal, Decimal]:
    """Devuelve y valida la envolvente E.A. de las filas de un producto.

    Args:
        producto: clave del producto, para el mensaje de error.
        filas: filas de tasa del producto.

    Returns:
        El `desde` más bajo y el `hasta` más alto.

    Raises:
        TasaFueraDeRango: si la envolvente no es un decimal entre 0 y 1.
    """
    desde = min(fila.tasa_ea_desde for fila in filas)
    hasta = max(fila.tasa_ea_hasta for fila in filas)
    return _rango_valido(producto, desde, hasta)


def _rango_valido(producto: str, desde: Decimal, hasta: Decimal) -> tuple[Decimal, Decimal]:
    """Comprueba que un rango E.A. sea un decimal válido entre 0 y 1.

    Args:
        producto: clave del producto, para el mensaje de error.
        desde: extremo inferior del rango.
        hasta: extremo superior del rango.

    Returns:
        El mismo rango, ya validado.

    Raises:
        TasaFueraDeRango: si el rango se sale de 0–1 o está invertido.
    """
    if not Decimal(0) <= desde <= hasta <= Decimal(1):
        raise TasaFueraDeRango(f"{producto}: el rango E.A. queda en {desde}–{hasta}")
    return desde, hasta


#: Primera cifra de un tramo de saldo, como «De 0» o «De $5.000.001».
_RE_CIFRA = re.compile(r"\d[\d.]*")


def _inicio_tramo(segmento: str | None) -> Decimal:
    """Lee el extremo inferior de un tramo de saldo para ordenarlo.

    Args:
        segmento: texto publicado del tramo, como «De $5.000.001 a $20.000.000».

    Returns:
        El monto inicial en pesos; 0 si el texto no trae cifras.
    """
    encontrado = _RE_CIFRA.search(segmento or "")
    if encontrado is None:
        return Decimal(0)
    return Decimal(encontrado.group(0).replace(".", ""))


def calcular(
    entrada: EntradaCalculo,
    *,
    tasa: TasaProducto | None = None,
    fecha: date | None = None,
    hoy: date | None = None,
    raiz: Path | None = None,
    verde_hasta: Decimal = UMBRAL_VERDE,
    amarillo_hasta: Decimal = UMBRAL_AMARILLO,
    umbral_vivienda: Decimal = UMBRAL_VIVIENDA,
) -> ResultadoCalculo:
    """Calcula el diagnóstico y, si hace falta, lee la tasa del Tablero.

    No simula cuando la capacidad es negativa ni cuando la libranza no aplica;
    en esos casos no consulta la tasa. Para el ahorro solo informa la capacidad
    de ahorro y las tasas de captación vigentes. Si no hay tabla vigente para
    la fecha consultada, usa la más reciente y agrega `vigencia_vencida`; nunca
    se detiene por una vigencia expirada.

    Args:
        entrada: insumos normalizados del diagnóstico.
        tasa: rango ya resuelto; si falta, se lee del Tablero.
        fecha: fecha de la vigencia consultada.
        hoy: fecha con la que se comprueba la vigencia de la tasa; por defecto
            la de hoy.
        raiz: carpeta de tablas Gold alternativa.
        verde_hasta: umbral verde de la razón de endeudamiento.
        amarillo_hasta: umbral amarillo de la razón de endeudamiento.
        umbral_vivienda: porcentaje máximo de la cuota sobre el ingreso.

    Returns:
        El resultado con cuota en rango, semáforo y motivos explicables.

    Raises:
        ValueError: si la entrada no cumple el contrato.
        TasaNoDisponible: si el producto no tiene ninguna tasa publicada.
    """
    _validar(entrada)
    _validar_umbrales(verde_hasta, amarillo_hasta, umbral_vivienda)
    clave = clave_producto(entrada.producto)
    if clave == "ahorro":
        captacion = _tasas_captacion(fecha, raiz)
        return evaluar(
            entrada,
            tasas_captacion=captacion,
            hoy=hoy,
            verde_hasta=verde_hasta,
            amarillo_hasta=amarillo_hasta,
            umbral_vivienda=umbral_vivienda,
        )
    capacidad = capacidad_pago(
        entrada.ingreso_mensual,
        entrada.gastos_mensuales,
        entrada.cuotas_deudas,
        entrada.cuota_trasladar or Decimal(0),
    )
    if capacidad < 0 or (clave == "libranza" and entrada.vinculacion == "independiente"):
        return evaluar(
            entrada,
            tasa,
            hoy=hoy,
            verde_hasta=verde_hasta,
            amarillo_hasta=amarillo_hasta,
            umbral_vivienda=umbral_vivienda,
        )
    rango = tasa if tasa is not None else tasa_de_tablero(clave, fecha, raiz=raiz)
    return evaluar(
        entrada,
        rango,
        hoy=hoy,
        verde_hasta=verde_hasta,
        amarillo_hasta=amarillo_hasta,
        umbral_vivienda=umbral_vivienda,
    )


def evaluar(
    entrada: EntradaCalculo,
    tasa: TasaProducto | None = None,
    *,
    tasas_captacion: tuple[TasaProducto, ...] = (),
    hoy: date | None = None,
    verde_hasta: Decimal = UMBRAL_VERDE,
    amarillo_hasta: Decimal = UMBRAL_AMARILLO,
    umbral_vivienda: Decimal = UMBRAL_VIVIENDA,
) -> ResultadoCalculo:
    """Evalúa una entrada con una tasa ya resuelta, sin leer archivos.

    Args:
        entrada: insumos normalizados del diagnóstico.
        tasa: rango de tasa del producto; obligatorio si hay que simular.
        tasas_captacion: tasas de ahorro y CDT para el producto `ahorro`.
        hoy: fecha con la que se comprueba la vigencia de la tasa; por defecto
            la de hoy.
        verde_hasta: umbral verde de la razón de endeudamiento.
        amarillo_hasta: umbral amarillo de la razón de endeudamiento.
        umbral_vivienda: porcentaje máximo de la cuota sobre el ingreso.

    Returns:
        El resultado determinista del diagnóstico, con la alerta
        `vigencia_vencida` si la tasa consultada ya no cubre la fecha de hoy.

    Raises:
        ValueError: si la entrada no cumple el contrato o falta la tasa.
    """
    _validar(entrada)
    _validar_umbrales(verde_hasta, amarillo_hasta, umbral_vivienda)
    clave = clave_producto(entrada.producto)
    capacidad = capacidad_pago(
        entrada.ingreso_mensual,
        entrada.gastos_mensuales,
        entrada.cuotas_deudas,
        entrada.cuota_trasladar or Decimal(0),
    )
    if clave == "ahorro":
        resultado = _resultado_ahorro(entrada, capacidad, tasas_captacion)
    elif capacidad < 0:
        resultado = _resultado_capacidad_negativa(entrada, capacidad, tasa)
    elif clave == "libranza" and entrada.vinculacion == "independiente":
        resultado = _resultado_libranza_no_disponible(entrada, capacidad, tasa)
    else:
        if tasa is None:
            raise ValueError("falta la tasa del Tablero para simular el crédito")
        resultado = _resultado_credito(
            entrada,
            tasa,
            capacidad,
            verde_hasta=verde_hasta,
            amarillo_hasta=amarillo_hasta,
            umbral_vivienda=umbral_vivienda,
        )
    return _con_vigencia(resultado, hoy)


def _con_vigencia(resultado: ResultadoCalculo, hoy: date | None) -> ResultadoCalculo:
    """Añade la alerta y el motivo cuando la tasa no cubre la fecha de hoy.

    La consulta no se detiene cuando no hay tabla vigente: el cálculo usa la
    más reciente y este paso deja la alerta `vigencia_vencida` con un motivo
    que cita la vigencia publicada.

    Args:
        resultado: resultado del cálculo con sus tasas.
        hoy: fecha de contraste; por defecto la de hoy.

    Returns:
        El mismo resultado, con `vigencia_vencida` en las alertas y un motivo
        por cada tasa cuya vigencia no incluye la fecha.
    """
    fecha = hoy if hoy is not None else date.today()
    tasas = resultado.tasas_captacion if resultado.producto == "ahorro" else (resultado.tasa,)
    vencidas = [
        tasa
        for tasa in tasas
        if tasa is not None and not esta_vigente(tasa.vigencia_desde, tasa.vigencia_hasta, fecha)
    ]
    if not vencidas:
        return resultado
    alertas = (*resultado.alertas, ALERTA_VIGENCIA_VENCIDA)
    motivos = (*resultado.motivos, *(_motivo_vigencia(tasa, fecha) for tasa in vencidas))
    return replace(resultado, alertas=alertas, motivos=motivos)


def _motivo_vigencia(tasa: TasaProducto, hoy: date) -> str:
    """Explica en texto que la vigencia de una tasa no incluye la fecha de hoy.

    Args:
        tasa: tasa cuya vigencia se comprobó.
        hoy: fecha de contraste.

    Returns:
        El motivo, con la vigencia publicada y la fecha consultada.
    """
    nombre = "CDT" if tasa.producto == "cdt" else nombre_producto(tasa.producto).casefold()
    vigencia = vigencia_legible(tasa.vigencia_desde, tasa.vigencia_hasta)
    return (
        f"La vigencia de la tasa de {nombre} ({vigencia}) no incluye la fecha de "
        f"hoy ({fecha_legible(hoy)}): confírmala antes de usarla."
    )


def _resultado_credito(
    entrada: EntradaCalculo,
    tasa: TasaProducto,
    capacidad: Decimal,
    *,
    verde_hasta: Decimal,
    amarillo_hasta: Decimal,
    umbral_vivienda: Decimal,
) -> ResultadoCalculo:
    """Simula el crédito en los dos extremos del rango y aplica el semáforo."""
    clave = clave_producto(entrada.producto)
    monto = Decimal(entrada.monto_credito or 0)
    plazo = int(entrada.plazo_meses or 0)
    trasladar = Decimal(entrada.cuota_trasladar or 0)
    interes_min = tasa_mensual(tasa.ea_desde)
    interes_max = tasa_mensual(tasa.ea_hasta)
    cuota_min = cuota_francesa(monto, interes_min, plazo)
    cuota_max = cuota_francesa(monto, interes_max, plazo)
    margen = margen_despues_cuota(capacidad, cuota_max)
    razon = razon_endeudamiento(
        entrada.cuotas_deudas, cuota_max, entrada.ingreso_mensual, trasladar
    )
    color = semaforo(razon, cuota_max, capacidad, verde_hasta, amarillo_hasta)
    motivos: list[str] = []
    if margen < 0:
        motivos.append(
            f"El margen después de la cuota es negativo: {_pesos(capacidad)} de "
            f"capacidad menos {_pesos(cuota_max)} de cuota deja {_pesos(margen)}."
        )
    elif razon > amarillo_hasta:
        motivos.append(
            f"La razón de endeudamiento de {_porcentaje(razon)} supera el "
            f"límite rojo de {_porcentaje(amarillo_hasta)}."
        )
    elif razon > verde_hasta:
        motivos.append(
            f"La razón de endeudamiento de {_porcentaje(razon)} supera el "
            f"límite verde de {_porcentaje(verde_hasta)}."
        )
    else:
        motivos.append(
            f"La cuota de {_pesos(cuota_max)} deja un margen de {_pesos(margen)} "
            f"y la razón de endeudamiento es {_porcentaje(razon)}."
        )

    alertas: list[str] = []
    if clave == "vivienda":
        limite = _peso(Decimal(entrada.ingreso_mensual) * Decimal(umbral_vivienda))
        if cuota_max > limite:
            color = "rojo"
            alertas.append("vivienda_30")
            motivos.append(
                f"En vivienda la primera cuota no debe superar el "
                f"{_porcentaje(umbral_vivienda)} del ingreso: {_pesos(cuota_max)} > "
                f"{_pesos(limite)}."
            )

    ahorro_mensual: Decimal | None = None
    if clave == "compra_cartera":
        ahorro_mensual = _peso(trasladar - cuota_max)
        if ahorro_mensual > 0:
            motivos.append(f"El traslado reduce la cuota en {_pesos(ahorro_mensual)} al mes.")
        else:
            motivos.append(
                "Con este plazo el traslado no reduce la cuota: la cuota nueva "
                f"es de {_pesos(cuota_max)} y la actual de {_pesos(trasladar)}."
            )

    recomendaciones = list(RECOMENDACIONES[color])
    if clave == "vivienda" and color == "rojo":
        recomendaciones.append(
            "Revisa el monto o amplía el plazo para que la primera cuota no "
            "supere el 30 % del ingreso."
        )
    return ResultadoCalculo(
        producto=clave,
        version_formula=VERSION_FORMULA,
        base_semaforo=BASE_SEMAFORO,
        tasa=tasa,
        tasa_mensual_min=interes_min,
        tasa_mensual_max=interes_max,
        cuota_min=cuota_min,
        cuota_max=cuota_max,
        total_intereses_min=_peso(cuota_min * plazo - monto),
        total_intereses_max=_peso(cuota_max * plazo - monto),
        total_pagado_min=_peso(cuota_min * plazo),
        total_pagado_max=_peso(cuota_max * plazo),
        razon_endeudamiento=razon,
        capacidad_pago=capacidad,
        margen_despues_cuota=margen,
        capacidad_ahorro=None,
        ahorro_mensual=ahorro_mensual,
        semaforo=color,
        alertas=tuple(alertas),
        motivos=tuple(motivos),
        recomendaciones=tuple(recomendaciones),
        tasas_captacion=(),
        aviso=_aviso(tasa),
    )


def _resultado_ahorro(
    entrada: EntradaCalculo,
    capacidad: Decimal,
    tasas_captacion: tuple[TasaProducto, ...],
) -> ResultadoCalculo:
    """Informa la capacidad de ahorro y las tasas de captación, sin semáforo.

    Con capacidad de ahorro nula o negativa la recomendación es revisar los
    gastos fijos antes de ahorrar, y no automatizar un ahorro que no cabe en el
    presupuesto.
    """
    motivos = ["El ahorro no tiene semáforo de crédito: se informa la capacidad mensual."]
    if capacidad < 0:
        motivos.append("Los gastos y las cuotas superan el ingreso: no hay capacidad de ahorro.")
        recomendaciones = [
            "Revisa tus gastos fijos: primero hay que liberar margen en el presupuesto.",
            "Reduce o renegocia las cuotas que más pesan en tus gastos mensuales.",
            "Cuando el presupuesto deje margen, define una meta de ahorro.",
        ]
    elif capacidad == 0:
        motivos.append(
            "Los gastos y las cuotas consumen todo el ingreso: no queda margen para ahorrar."
        )
        recomendaciones = [
            "Revisa tus gastos fijos: es el primer paso antes de empezar a ahorrar.",
            "Identifica los gastos que puedes reducir o renegociar este mes.",
            "Cuando liberes margen, vuelve a revisar las tasas de ahorro y CDT.",
        ]
    else:
        recomendaciones = [
            "Con tu capacidad de ahorro puedes revisar las tasas de ahorro y CDT del Tablero.",
            "Define una meta y automatiza el ahorro apenas recibas tus ingresos.",
        ]
    if not tasas_captacion:
        motivos.append("No hay tasas de ahorro o CDT disponibles en el Tablero.")
    motivos.extend(
        motivo for tasa in tasas_captacion if (motivo := _motivo_captacion(tasa)) is not None
    )
    primera = tasas_captacion[0] if tasas_captacion else None
    return ResultadoCalculo(
        producto="ahorro",
        version_formula=VERSION_FORMULA,
        base_semaforo=BASE_SEMAFORO,
        tasa=primera,
        tasa_mensual_min=None,
        tasa_mensual_max=None,
        cuota_min=None,
        cuota_max=None,
        total_intereses_min=None,
        total_intereses_max=None,
        total_pagado_min=None,
        total_pagado_max=None,
        razon_endeudamiento=None,
        capacidad_pago=capacidad,
        margen_despues_cuota=None,
        capacidad_ahorro=capacidad,
        ahorro_mensual=None,
        semaforo=None,
        alertas=(),
        motivos=tuple(motivos),
        recomendaciones=tuple(recomendaciones),
        tasas_captacion=tasas_captacion,
        aviso=_aviso(primera),
    )


def _motivo_captacion(tasa: TasaProducto) -> str | None:
    """Explica en texto la referencia y el rango completo de una tasa de captación.

    Args:
        tasa: tasa de ahorro o CDT leída del Tablero.

    Returns:
        El motivo con el tramo de referencia y el rango completo, o None si la
        tasa no trae ese detalle.
    """
    completa = _rango_texto(tasa.rango_completo_desde, tasa.rango_completo_hasta)
    if tasa.producto == "ahorro":
        if tasa.tramo is None or completa is None:
            return None
        return (
            f"La tasa de ahorro de referencia es la del tramo «{tasa.tramo}»: "
            f"{_rango_texto(tasa.ea_desde, tasa.ea_hasta)} E.A. El rango completo "
            f"por saldo va de {completa} E.A."
        )
    if not tasa.tramos:
        return None
    primero, ultimo = tasa.tramos[0], tasa.tramos[-1]
    tramo = f"«{tasa.tramo}»" if tasa.tramo is not None else "de menor monto"
    return (
        f"El CDT depende del plazo y del monto: para el tramo {tramo} la tasa va "
        f"de {_rango_texto(tasa.ea_desde, tasa.ea_hasta)} E.A. entre "
        f"{primero.etiqueta} y {ultimo.etiqueta}. El rango completo del producto "
        f"es {completa} E.A. según el monto."
    )


def _rango_texto(desde: Decimal | None, hasta: Decimal | None) -> str | None:
    """Escribe un rango de tasas como «0,05 % a 12,05 %».

    Args:
        desde: extremo inferior de la tasa.
        hasta: extremo superior de la tasa.

    Returns:
        El rango en texto, la cifra sola si los extremos coinciden, o None si
        falta alguno de los extremos.
    """
    if desde is None or hasta is None:
        return None
    if desde == hasta:
        return _porcentaje(desde)
    return f"{_porcentaje(desde)} a {_porcentaje(hasta)}"


def _resultado_capacidad_negativa(
    entrada: EntradaCalculo,
    capacidad: Decimal,
    tasa: TasaProducto | None,
) -> ResultadoCalculo:
    """Devuelve rojo sin simular cuando gastos y cuotas superan el ingreso."""
    return ResultadoCalculo(
        producto=clave_producto(entrada.producto),
        version_formula=VERSION_FORMULA,
        base_semaforo=BASE_SEMAFORO,
        tasa=tasa,
        tasa_mensual_min=None,
        tasa_mensual_max=None,
        cuota_min=None,
        cuota_max=None,
        total_intereses_min=None,
        total_intereses_max=None,
        total_pagado_min=None,
        total_pagado_max=None,
        razon_endeudamiento=None,
        capacidad_pago=capacidad,
        margen_despues_cuota=None,
        capacidad_ahorro=None,
        ahorro_mensual=None,
        semaforo="rojo",
        alertas=("capacidad_negativa",),
        motivos=(
            "Los gastos y las cuotas superan el ingreso: no hay capacidad para "
            "una cuota nueva y no se simula el crédito.",
            f"La capacidad de pago es de {_pesos(capacidad)}.",
        ),
        recomendaciones=(
            "Ordena primero tus gastos y deudas.",
            "Habla con un asesor para revisar tu caso.",
        ),
        tasas_captacion=(),
        aviso=_aviso(tasa),
    )


def _resultado_libranza_no_disponible(
    entrada: EntradaCalculo,
    capacidad: Decimal,
    tasa: TasaProducto | None,
) -> ResultadoCalculo:
    """Explica que la libranza exige convenio y ofrece simular libre inversión."""
    return ResultadoCalculo(
        producto="libranza",
        version_formula=VERSION_FORMULA,
        base_semaforo=BASE_SEMAFORO,
        tasa=tasa,
        tasa_mensual_min=None,
        tasa_mensual_max=None,
        cuota_min=None,
        cuota_max=None,
        total_intereses_min=None,
        total_intereses_max=None,
        total_pagado_min=None,
        total_pagado_max=None,
        razon_endeudamiento=None,
        capacidad_pago=capacidad,
        margen_despues_cuota=None,
        capacidad_ahorro=None,
        ahorro_mensual=None,
        semaforo=None,
        alertas=("libranza_no_aplica",),
        motivos=(
            "La libranza solo está disponible para empleados o pensionados con "
            "convenio de descuento.",
            "Con vinculación independiente no se puede simular libranza.",
        ),
        recomendaciones=(
            "Puedes simular un préstamo de libre inversión.",
            "Habla con un asesor para revisar alternativas de crédito.",
        ),
        tasas_captacion=(),
        aviso=_aviso(tasa),
    )


def _tasas_captacion(
    fecha: date | None,
    raiz: Path | None,
) -> tuple[TasaProducto, ...]:
    """Lee las tasas de ahorro y CDT sin fallar si una no está publicada."""
    tasas: list[TasaProducto] = []
    for producto in ("ahorro", "cdt"):
        try:
            tasas.append(tasa_de_tablero(producto, fecha, raiz=raiz))
        except TasaNoDisponible:
            continue
    return tuple(tasas)


def _validar(entrada: EntradaCalculo) -> None:
    """Comprueba que la entrada tenga los insumos que exige el producto.

    Raises:
        ValueError: si falta un insumo, un valor es negativo o la compra de
            cartera traslada más cuota de la que existe.
    """
    clave = clave_producto(entrada.producto)
    if clave not in PRODUCTOS_DIAGNOSTICO:
        raise ValueError(f"«{entrada.producto}» no es un producto del diagnóstico")
    if Decimal(entrada.ingreso_mensual) <= 0:
        raise ValueError("el ingreso mensual debe ser positivo")
    if Decimal(entrada.gastos_mensuales) < 0:
        raise ValueError("los gastos mensuales no pueden ser negativos")
    if Decimal(entrada.cuotas_deudas) < 0:
        raise ValueError("las cuotas de deudas no pueden ser negativas")
    if entrada.vinculacion not in VINCULACIONES:
        raise ValueError(f"vinculación inválida: {entrada.vinculacion}")
    if clave in PRODUCTOS_CREDITO:
        if entrada.monto_credito is None or Decimal(entrada.monto_credito) <= 0:
            raise ValueError("el monto del crédito debe ser positivo")
        if entrada.plazo_meses is None or int(entrada.plazo_meses) <= 0:
            raise ValueError("el plazo del crédito debe ser positivo")
    if clave == "compra_cartera":
        if entrada.cuota_trasladar is None:
            raise ValueError("la compra de cartera exige la cuota que se traslada")
        if Decimal(entrada.cuota_trasladar) < 0:
            raise ValueError("la cuota trasladada no puede ser negativa")
        if Decimal(entrada.cuota_trasladar) > Decimal(entrada.cuotas_deudas):
            raise ValueError("la cuota trasladada no puede superar las cuotas actuales")


def _validar_umbrales(
    verde_hasta: Decimal,
    amarillo_hasta: Decimal,
    umbral_vivienda: Decimal,
) -> None:
    """Comprueba que los umbrales del semáforo y de vivienda sean válidos.

    Raises:
        ValueError: si un umbral se sale de 0–1 o el par verde/amarillo está
            invertido.
    """
    verde = Decimal(verde_hasta)
    amarillo = Decimal(amarillo_hasta)
    vivienda = Decimal(umbral_vivienda)
    if not Decimal(0) <= verde <= amarillo <= Decimal(1):
        raise ValueError(f"umbrales inválidos: verde={verde}, amarillo={amarillo}")
    if not Decimal(0) <= vivienda <= Decimal(1):
        raise ValueError(f"umbral de vivienda inválido: {vivienda}")


def _contexto() -> Context:
    """Devuelve el contexto decimal del motor: 28 dígitos, mitad hacia arriba."""
    return Context(prec=PRECISION, rounding=ROUND_HALF_UP)


def _cuantizar(valor: Decimal, decimales: int) -> Decimal:
    """Redondea un decimal con la precisión indicada y ROUND_HALF_UP."""
    return valor.quantize(Decimal(1).scaleb(-decimales), rounding=ROUND_HALF_UP)


def _peso(valor: Decimal) -> Decimal:
    """Redondea un monto en pesos al peso, con ROUND_HALF_UP."""
    return _cuantizar(valor, 0)


def _pesos(valor: Decimal) -> str:
    """Formatea un monto en pesos con separador de miles y signo."""
    entero = int(valor.quantize(Decimal(1), rounding=ROUND_HALF_UP))
    signo = "-" if entero < 0 else ""
    return f"{signo}${abs(entero):,}".replace(",", ".")


def _porcentaje(valor: Decimal) -> str:
    """Formatea una fracción como porcentaje con dos decimales y coma."""
    return f"{valor * 100:.2f}".replace(".", ",") + " %"


def _aviso(tasa: TasaProducto | None) -> str:
    """Arma el aviso orientativo obligatorio citando la vigencia de la tasa."""
    if tasa is None:
        vigencia = "la vigencia publicada"
    else:
        vigencia = vigencia_legible(tasa.vigencia_desde, tasa.vigencia_hasta)
    return (
        "Este resultado es orientativo y se basa en rangos aproximados y en las "
        f"tasas publicadas por el Banco de Occidente para {vigencia}. No es una "
        "aprobación ni una oferta de crédito; la tasa final depende del monto, el "
        "plazo y tu perfil. Proyecto académico de la UAO, no es un canal oficial "
        "del banco."
    )
