"""Motor del diagnóstico: contratos del canal sobre el cálculo determinista.

`diagnostico.calculo` hace la aritmética en `Decimal` y lee la tabla Gold de
tasas; este módulo lo conecta con los contratos Pydantic del canal y con
`config/diagnostico.toml`:

- `calcular` convierte una `EntradaDiagnostico` en un `ResultadoDiagnostico`,
  usando los umbrales del TOML y sin modelo ni red.
- `entrada_desde_respuestas` traduce los ids canónicos de la entrevista
  (`objetivo.*`, `vinculacion.*`, `ingresos.*`, `monto.*`, `plazo.*`, …) a una
  `EntradaDiagnostico`, tomando los valores de cálculo del TOML. Así el canal
  no conoce las cifras: solo transporta botones.

La tasa se consulta en `data/gold/tasas/` y nunca se inventa. Si el producto no
tiene ninguna tasa publicada, la excepción `TasaNoDisponible` sube tal cual para
que el canal responda `tasa_no_disponible`. Si la tabla no cubre la fecha de
hoy, se usa la más reciente y el resultado agrega la alerta
`vigencia_vencida`: la app sigue respondiendo después del vencimiento.
"""

from __future__ import annotations

import tomllib
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Literal, cast

from ..canal.contratos import (
    AlertaDiagnostico,
    EntradaDiagnostico,
    RangoDecimal,
    ResultadoDiagnostico,
    TasaCaptacion,
)
from ..canal.contratos import (
    TramoTasa as TramoTasaContrato,
)
from ..config import PROJECT_ROOT
from ..tablero.tasas import clave_producto
from .calculo import (
    PRODUCTOS_DIAGNOSTICO,
    UMBRAL_AMARILLO,
    UMBRAL_VERDE,
    UMBRAL_VIVIENDA,
    VINCULACIONES,
    EntradaCalculo,
    ResultadoCalculo,
    TasaProducto,
)
from .calculo import (
    calcular as calcular_calculo,
)

#: Archivo versionado con umbrales y valores de cálculo de la entrevista.
RUTA_CONFIG = PROJECT_ROOT / "config" / "diagnostico.toml"

#: Frontera por defecto del monto del crédito, en pesos, si el TOML no la trae.
MONTO_MINIMO = Decimal(500_000)
MONTO_MAXIMO = Decimal(2_000_000_000)

#: Bloques de la entrevista que no viven en el TOML porque son listas fijas.
BLOQUES_FIJOS = frozenset({"objetivo", "vinculacion"})


@dataclass(frozen=True, slots=True)
class BloqueRango:
    """Extremos de un bloque de la entrevista y los productos a los que aplica.

    El bloque agrupa las opciones de un paso (`monto`, `monto_vivienda`,
    `plazo`, …). `minimo` y `maximo` son el extremo inferior y el superior de
    todas sus opciones; una opción abierta («hasta $5 millones», «más de $50
    millones») aporta su `valor` de cálculo en el extremo que no declara.
    """

    clave: str
    minimo: Decimal
    maximo: Decimal
    productos: frozenset[str]


@dataclass(frozen=True, slots=True)
class LimitesCredito:
    """Rango de monto y plazo que la entrevista admite para un producto."""

    monto_minimo: Decimal
    monto_maximo: Decimal
    plazo_minimo: int
    plazo_maximo: int


@dataclass(frozen=True, slots=True)
class ConfigDiagnostico:
    """Umbrales y valores de cálculo leídos de `config/diagnostico.toml`."""

    verde_hasta: Decimal
    amarillo_hasta: Decimal
    umbral_vivienda: Decimal
    valores: Mapping[str, Decimal]
    claves: Mapping[str, str]
    aplica_a: Mapping[str, tuple[str, ...]]
    bloques: Mapping[str, BloqueRango] = field(default_factory=dict)
    monto_minimo: Decimal = MONTO_MINIMO
    monto_maximo: Decimal = MONTO_MAXIMO
    preguntas: Mapping[str, str] = field(default_factory=dict)
    textos: Mapping[str, str] = field(default_factory=dict)
    orden: tuple[str, ...] = ()


def cargar_config(ruta: Path | None = None) -> ConfigDiagnostico:
    """Lee los umbrales y los valores de cálculo de la entrevista.

    Args:
        ruta: archivo TOML alternativo; por defecto `config/diagnostico.toml`.

    Returns:
        La configuración con el umbral verde, el amarillo, el de vivienda, el
        valor de cálculo por id y la clave del bloque al que pertenece cada id.

    Raises:
        FileNotFoundError: si el archivo no existe.
        KeyError: si un rango u opción no declara su clave o su valor.
    """
    archivo = Path(ruta) if ruta is not None else RUTA_CONFIG
    with archivo.open("rb") as fh:
        datos = tomllib.load(fh)

    umbrales = dict(datos.get("umbrales", {}))
    limites = dict(datos.get("limites", {}))
    valores: dict[str, Decimal] = {}
    claves: dict[str, str] = {}
    aplica_a: dict[str, tuple[str, ...]] = {}
    bloques: dict[str, BloqueRango] = {}
    preguntas: dict[str, str] = {}
    textos: dict[str, str] = {}
    orden: list[str] = []
    for rango in datos.get("rango", []):
        clave = str(rango["clave"])
        productos = tuple(str(producto) for producto in rango.get("aplica_a", []))
        minimo: Decimal | None = None
        maximo: Decimal | None = None
        orden.append(clave)
        preguntas[clave] = str(rango.get("pregunta", ""))
        for opcion in rango.get("opcion", []):
            ident = str(opcion["id"])
            valor = Decimal(str(opcion["valor"]))
            inferior = Decimal(str(opcion.get("desde", valor)))
            superior = Decimal(str(opcion.get("hasta", valor)))
            valores[ident] = valor
            claves[ident] = clave
            aplica_a[ident] = productos
            textos[ident] = str(opcion.get("texto", ident))
            minimo = inferior if minimo is None else min(minimo, inferior)
            maximo = superior if maximo is None else max(maximo, superior)
        if minimo is not None and maximo is not None:
            bloques[clave] = BloqueRango(
                clave=clave,
                minimo=minimo,
                maximo=maximo,
                productos=frozenset(productos),
            )
    return ConfigDiagnostico(
        verde_hasta=Decimal(str(umbrales.get("verde_hasta", UMBRAL_VERDE))),
        amarillo_hasta=Decimal(str(umbrales.get("amarillo_hasta", UMBRAL_AMARILLO))),
        umbral_vivienda=Decimal(str(umbrales.get("vivienda_hasta", UMBRAL_VIVIENDA))),
        valores=valores,
        claves=claves,
        aplica_a=aplica_a,
        bloques=bloques,
        monto_minimo=Decimal(str(limites.get("monto_minimo", MONTO_MINIMO))),
        monto_maximo=Decimal(str(limites.get("monto_maximo", MONTO_MAXIMO))),
        preguntas=preguntas,
        textos=textos,
        orden=tuple(orden),
    )


def limites_credito(
    producto: str,
    *,
    config: ConfigDiagnostico | None = None,
) -> LimitesCredito:
    """Devuelve los límites de monto y plazo que acepta la simulación.

    El monto usa la frontera de `[limites]` de `config/diagnostico.toml` —la
    misma que aplican el diagnóstico y los escenarios «¿Y si…?»—, no los valores
    de cálculo de los rangos, que son representativos. El plazo sale de los
    bloques `plazo*` que declaran el producto en `aplica_a`.

    Args:
        producto: clave canónica del producto (`libre_inversion`, `vivienda`,
            …). No se acepta ahorro, que no simula cuota de crédito.
        config: configuración ya cargada; por defecto se lee el TOML.

    Returns:
        La frontera de monto, en pesos, y los extremos de plazo, en meses.

    Raises:
        ValueError: si el producto no tiene bloque de plazo, es decir, si no es
            un producto de crédito con cuota fija.
    """
    clave = clave_producto(producto)
    ajustes = config if config is not None else cargar_config()
    plazos = [
        bloque
        for bloque in ajustes.bloques.values()
        if (bloque.clave == "plazo" or bloque.clave.startswith("plazo_"))
        and clave in bloque.productos
    ]
    if not plazos:
        raise ValueError(f"«{producto}» no es un producto de crédito con cuota fija")
    return LimitesCredito(
        monto_minimo=ajustes.monto_minimo,
        monto_maximo=ajustes.monto_maximo,
        plazo_minimo=int(min(bloque.minimo for bloque in plazos)),
        plazo_maximo=int(max(bloque.maximo for bloque in plazos)),
    )


def entrada_desde_respuestas(
    respuestas: Mapping[str, str] | Iterable[str] | str,
    *,
    config: ConfigDiagnostico | None = None,
) -> EntradaDiagnostico:
    """Convierte los ids de la entrevista en una entrada de diagnóstico.

    Acepta el diccionario de respuestas del grafo (clave del paso → id) o
    cualquier iterable de ids canónicos. El id manda; las claves del
    diccionario solo se conservan en `rango_usado`. Las respuestas repetidas
    del mismo bloque toman la última.

    Args:
        respuestas: ids elegidos en la entrevista.
        config: configuración ya cargada; por defecto se lee el TOML.

    Returns:
        La entrada validada, con el punto medio de cada rango y los ids usados.

    Raises:
        ValueError: si falta una respuesta obligatoria, un id no existe o el
            conjunto de respuestas no corresponde al producto elegido.
    """
    ajustes = config if config is not None else cargar_config()
    elegidos = _ids(respuestas)

    producto: str | None = None
    vinculacion: str | None = None
    valores: dict[str, Decimal] = {}
    usados: dict[str, str] = {}
    por_prefijo: dict[str, str] = {}

    for ident in elegidos:
        prefijo = ident.split(".", 1)[0]
        sufijo = ident.split(".", 1)[1] if "." in ident else ""
        if prefijo == "objetivo":
            if sufijo not in PRODUCTOS_DIAGNOSTICO:
                raise ValueError(f"«{ident}» no es un objetivo del diagnóstico")
            producto = sufijo
            usados["objetivo"] = ident
        elif prefijo == "vinculacion":
            if sufijo not in VINCULACIONES:
                raise ValueError(f"«{ident}» no es una forma de vinculación válida")
            vinculacion = sufijo
            usados["vinculacion"] = ident
        else:
            if ident not in ajustes.valores:
                raise ValueError(f"«{ident}» no es una opción de la entrevista")
            valores[prefijo] = ajustes.valores[ident]
            por_prefijo[prefijo] = ident
            usados[ajustes.claves[ident]] = ident

    if producto is None:
        raise ValueError("falta la respuesta del objetivo del diagnóstico")
    if vinculacion is None:
        raise ValueError("faltan las respuestas de la vinculación")
    if producto == "ahorro" and ("monto" in valores or "plazo" in valores):
        raise ValueError("el ahorro no lleva monto ni plazo de crédito")
    for prefijo in ("monto", "plazo"):
        ident = por_prefijo.get(prefijo)
        aplicables = ajustes.aplica_a.get(ident or "")
        if ident is not None and aplicables and producto not in aplicables:
            raise ValueError(f"«{ident}» no aplica al producto «{producto}»")
    faltan = [nombre for nombre in ("ingresos", "gastos", "cuotas") if nombre not in valores]
    if faltan:
        raise ValueError("faltan respuestas de la entrevista: " + ", ".join(faltan))

    datos: dict[str, object] = {
        "producto": producto,
        "vinculacion": vinculacion,
        "ingreso_mensual": valores["ingresos"],
        "gastos_mensuales": valores["gastos"],
        "cuotas_deudas": valores["cuotas"],
        "cuota_trasladar": valores.get("cuota_trasladar"),
        "rango_usado": usados,
    }
    if producto != "ahorro":
        if "monto" not in valores:
            raise ValueError("falta la respuesta del monto del crédito")
        if "plazo" not in valores:
            raise ValueError("falta la respuesta del plazo del crédito")
        datos["monto_credito"] = valores["monto"]
        datos["plazo_meses"] = int(valores["plazo"])
    return EntradaDiagnostico.model_validate(datos)


def calcular(
    entrada: EntradaDiagnostico,
    *,
    fecha: date | None = None,
    hoy: date | None = None,
    raiz: Path | None = None,
    config: ConfigDiagnostico | None = None,
) -> ResultadoDiagnostico:
    """Calcula el diagnóstico completo a partir de los contratos del canal.

    Args:
        entrada: insumos ya validados por `EntradaDiagnostico`.
        fecha: vigencia de la tasa consultada; por defecto la más reciente.
        hoy: fecha con la que se comprueba la vigencia de la tasa; por defecto
            la de hoy. Si la vigencia no la incluye, la alerta es
            `vigencia_vencida` y la tasa informada es la de la tabla más
            reciente.
        raiz: carpeta de tablas Gold alternativa; por defecto la del Tablero.
        config: umbrales ya cargados; por defecto se leen del TOML.

    Returns:
        El resultado determinista, con cuota en rango, semáforo, alertas,
        trazabilidad de la tasa y el aviso orientativo.

    Raises:
        ValueError: si la entrada no cumple el contrato del cálculo.
        TasaNoDisponible: si el Tablero no publica ninguna tasa del producto.
        TasaFueraDeRango: si la tasa publicada está fuera de rango.
    """
    ajustes = config if config is not None else cargar_config()
    interno = calcular_calculo(
        EntradaCalculo(
            producto=entrada.producto,
            ingreso_mensual=entrada.ingreso_mensual,
            gastos_mensuales=entrada.gastos_mensuales,
            cuotas_deudas=entrada.cuotas_deudas,
            monto_credito=entrada.monto_credito,
            plazo_meses=entrada.plazo_meses,
            vinculacion=entrada.vinculacion,
            cuota_trasladar=entrada.cuota_trasladar,
        ),
        fecha=fecha,
        hoy=hoy,
        raiz=raiz,
        verde_hasta=ajustes.verde_hasta,
        amarillo_hasta=ajustes.amarillo_hasta,
        umbral_vivienda=ajustes.umbral_vivienda,
    )
    return _resultado(entrada, interno, ajustes)


def _ids(respuestas: Mapping[str, str] | Iterable[str] | str) -> list[str]:
    """Normaliza las respuestas a una lista de ids canónicos.

    Args:
        respuestas: diccionario de respuestas, texto suelto o iterable de ids.

    Returns:
        Los ids en el orden en que llegaron.
    """
    if isinstance(respuestas, str):
        return [respuestas]
    if isinstance(respuestas, Mapping):
        return [str(valor) for valor in respuestas.values()]
    return [str(valor) for valor in respuestas]


def _resultado(
    entrada: EntradaDiagnostico,
    interno: ResultadoCalculo,
    config: ConfigDiagnostico,
) -> ResultadoDiagnostico:
    """Traduce el resultado del cálculo al contrato del canal.

    En el ahorro no hay tasa de crédito ni cuota: los campos de crédito quedan
    vacíos y `fuente_tasa`/`vigencia_tasa_*` describen la primera tasa de
    captación informada. En la capacidad negativa el semáforo es rojo pero no
    hay cuota; en la libranza que no aplica no hay semáforo.

    Args:
        entrada: insumos del diagnóstico.
        interno: salida del motor de cálculo.
        config: umbrales usados.

    Returns:
        El `ResultadoDiagnostico` listo para guardar y citar.
    """
    tasa = interno.tasa
    cuota = _rango(interno.cuota_min, interno.cuota_max)
    creditos = entrada.producto != "ahorro"
    return ResultadoDiagnostico(
        version_formula=interno.version_formula,
        entrada=entrada,
        base_semaforo=interno.base_semaforo,
        tasa_ea=_rango(tasa.ea_desde, tasa.ea_hasta) if creditos and tasa else None,
        tasa_mensual=_rango(interno.tasa_mensual_min, interno.tasa_mensual_max),
        cuota_mensual=cuota,
        total_intereses=_rango(interno.total_intereses_min, interno.total_intereses_max),
        total_pagado=_rango(interno.total_pagado_min, interno.total_pagado_max),
        razon_endeudamiento=interno.razon_endeudamiento,
        capacidad_pago=interno.capacidad_pago,
        margen_despues_cuota=interno.margen_despues_cuota,
        ahorro_mensual_estimado=interno.ahorro_mensual,
        semaforo=interno.semaforo,
        alertas=cast(list[AlertaDiagnostico], list(interno.alertas)),
        motivos=list(interno.motivos),
        recomendaciones=list(interno.recomendaciones),
        fuente_tasa=tasa.fuente if tasa is not None else None,
        vigencia_tasa_desde=tasa.vigencia_desde if tasa is not None else None,
        vigencia_tasa_hasta=tasa.vigencia_hasta if tasa is not None else None,
        sha256_pdf=tasa.sha256_pdf if tasa is not None else None,
        umbrales={
            "verde_hasta": config.verde_hasta,
            "amarillo_hasta": config.amarillo_hasta,
            "vivienda_hasta": config.umbral_vivienda,
        },
        tasas_captacion=[_captacion(tasa) for tasa in interno.tasas_captacion],
        aviso=interno.aviso,
    )


def _captacion(tasa: TasaProducto) -> TasaCaptacion:
    """Convierte una tasa interna de ahorro o CDT en el contrato del canal.

    Args:
        tasa: tasa de captación del motor de cálculo.

    Returns:
        La tasa de captación con su tramo de referencia, el rango completo, el
        detalle por plazo, su vigencia y su fuente.
    """
    producto = cast(Literal["ahorro", "cdt"], tasa.producto)
    rango = _rango(tasa.ea_desde, tasa.ea_hasta)
    assert rango is not None
    tramos: list[TramoTasaContrato] = []
    for tramo in tasa.tramos:
        rango_tramo = _rango(tramo.ea_desde, tramo.ea_hasta)
        if rango_tramo is not None:
            tramos.append(TramoTasaContrato(etiqueta=tramo.etiqueta, tasa_ea=rango_tramo))
    return TasaCaptacion(
        producto=producto,
        tasa_ea=rango,
        referencia=tasa.tramo,
        rango_completo=_rango(tasa.rango_completo_desde, tasa.rango_completo_hasta),
        tramos=tramos,
        vigencia_desde=tasa.vigencia_desde,
        vigencia_hasta=tasa.vigencia_hasta,
        fuente=tasa.fuente,
    )


def _rango(desde: Decimal | None, hasta: Decimal | None) -> RangoDecimal | None:
    """Arma un `RangoDecimal` solo cuando los dos extremos existen.

    Args:
        desde: extremo inferior, o None.
        hasta: extremo superior, o None.

    Returns:
        El rango, o None si el cálculo no produjo ese valor.
    """
    if desde is None or hasta is None:
        return None
    return RangoDecimal(desde=desde, hasta=hasta)
