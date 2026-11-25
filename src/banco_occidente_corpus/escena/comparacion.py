"""Pana: comparación de Don Gota con el banco, la usura y el artículo 305.

El banco se calcula con `diagnostico.motor.calcular` usando el mismo monto, el
producto `libre_inversion`, un plazo de 36 meses y la vinculación `empleado`.
De los rangos del motor se toma el extremo **máximo**, igual que el semáforo
(`base_semaforo="tasa_maxima"`): la frase comparativa no usa el extremo
favorable.

La usura sale de `config/tasas.toml [usura]`. Si no está certificada, la
comparación deja vacíos `usura_ea`, `usura_vigencia`, `veces_usura` y
`fuente_usura`, y `alertas_comparacion` devuelve `usura_sin_certificar`: no se
calcula un ratio contra una cifra que no existe. Si el Tablero no publica la
tasa del producto, `diagnostico.motor.calcular` sube `TasaNoDisponible` con el
código `tasa_no_disponible`; la escena no inventa una tasa.

El turno de Pana se parte en tres plantillas fijas y cortas: el golpe (el
supuesto de 36 renovaciones, el total de Don Gota frente al banco y cuántas
veces el total del banco), la tasa (la E.A. de Don Gota, las veces la usura y
la tasa máxima del banco) y la ley (artículo 305 y usura vigente con su
período). Ninguno lo genera un modelo. Cada cifra del texto lleva su
`CifraEscena` y su `FuenteCifra`.

El monto del voluntario se pasa al motor tal cual. Si queda fuera de
`monto_minimo`/`monto_maximo` de `config/diagnostico.toml`, `motor.calcular`
**no** valida ese rango —la validación vive en `diagnostico.escenarios`—: la
comparación se calcula igual y ese caso queda para el 5.5 del plan. Lo que sí
se propaga es `ValueError` si el monto no es positivo o el motor no puede
simular el crédito, `pydantic.ValidationError` si la entrada no cumple el
contrato y `TasaNoDisponible` si el Tablero no publica la tasa.
"""

from __future__ import annotations

from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from ..canal.contratos import EntradaDiagnostico, ResultadoDiagnostico
from ..cifras_legibles import formatear_pesos, formatear_tasa_ea
from ..diagnostico import motor
from ..tablero.tasas import ConfiguracionTasas, cargar_config_tasas, vigencia_legible
from .contratos import (
    CifraEscena,
    ComparacionGota,
    EscenarioEscena,
    FuenteCifra,
    TurnoEscena,
    UnidadCifra,
)
from .gota import (
    SUPUESTO_RENOVACION,
    PrestamoGota,
)

#: Referencia legal que cita Pana; es informativa y no acusa a una persona real.
ARTICULO_305 = "Código Penal, artículo 305"
#: Código de alerta cuando el Tablero no publica la tasa del producto.
ESTADO_TASA_NO_DISPONIBLE = "tasa_no_disponible"
#: Código de alerta cuando la usura no está certificada.
ESTADO_USURA_SIN_CERTIFICAR = "usura_sin_certificar"


def comparar_gota_banco(
    prestamo: PrestamoGota,
    entrada: EntradaDiagnostico,
    *,
    raiz: Path | None = None,
    ruta_tasas: Path | None = None,
    config_tasas: ConfiguracionTasas | None = None,
    hoy: date | None = None,
) -> ComparacionGota:
    """Compara el préstamo de Don Gota con el banco y con la usura.

    La entrada del diagnóstico aporta ingresos, gastos y deudas; el producto,
    el monto, el plazo y la vinculación se normalizan a `libre_inversion`, el
    monto del préstamo, 36 meses y `empleado`, para que la comparación use
    exactamente el mismo escenario.

    El monto de `prestamo` se usa tal cual. `motor.calcular` no aplica los
    límites `monto_minimo`/`monto_maximo` del diagnóstico: un monto fuera de
    rango no lanza ninguna excepción aquí, la simulación se hace igual y el
    caso queda para el 5.5 (Darley). Solo se propagan `ValidationError`/
    `ValueError` si el monto no es positivo o el motor no puede simular el
    crédito, y `TasaNoDisponible` si falta la tasa del producto.

    Args:
        prestamo: préstamo de Don Gota ya calculado con el mismo monto.
        entrada: insumos del diagnóstico del perfil.
        raiz: carpeta de tablas Gold alternativa; por defecto la del Tablero.
        ruta_tasas: `config/tasas.toml` alternativo, útil en pruebas.
        config_tasas: configuración de tasas ya cargada; tiene prioridad sobre
            `ruta_tasas`.
        hoy: fecha con la que se comprueba la vigencia de la tasa y de la usura.

    Returns:
        La comparación con las cifras del banco en su extremo máximo, la usura
        vigente y los supuestos declarados.

    Raises:
        TasaNoDisponible: si el Tablero no publica la tasa de libre inversión.
        ValueError: si el motor no pudo simular el crédito del banco o si la
            usura certificada no trae una tasa E.A. positiva.
    """
    datos = entrada.model_dump()
    datos.update(
        {
            "producto": "libre_inversion",
            "vinculacion": "empleado",
            "monto_credito": prestamo.monto,
            "plazo_meses": prestamo.meses_horizonte,
            "cuota_trasladar": None,
        }
    )
    entrada_banco = EntradaDiagnostico.model_validate(datos)
    # El rango de monto del motor no se valida en `motor.calcular` (vive en
    # `diagnostico.escenarios`): un monto fuera de límites sigue de largo y el
    # caso queda para el 5.5; aquí solo se propagan ValidationError/ValueError
    # por un monto no positivo y TasaNoDisponible si falta la tasa.
    resultado = motor.calcular(entrada_banco, hoy=hoy, raiz=raiz)
    banco = _datos_banco(resultado)
    ajustes = config_tasas if config_tasas is not None else cargar_config_tasas(ruta_tasas)
    usura = ajustes.usura
    certificada = usura.certificada

    usura_ea: Decimal | None = None
    usura_vigencia: str | None = None
    fuente_usura: FuenteCifra | None = None
    veces_usura: Decimal | None = None
    if certificada:
        tasa_usura = Decimal(usura.tasa_ea)
        if tasa_usura <= 0:
            raise ValueError("la usura certificada debe traer una tasa E.A. positiva")
        usura_ea = tasa_usura
        usura_vigencia = f"{usura.vigencia_desde.isoformat()}/{usura.vigencia_hasta.isoformat()}"
        fuente_usura = FuenteCifra(
            tipo="usura",
            referencia="config/tasas.toml#usura.tasa_ea",
            vigencia=usura_vigencia,
        )
        veces_usura = _cuantizar(prestamo.tasa_ea / tasa_usura, 2)

    total_gota = prestamo.total_pagado_horizonte
    total_banco = banco["total_pagado"]
    supuestos = (
        "mismo monto",
        f"mismo horizonte de {prestamo.meses_horizonte} meses",
        "tasa máxima del banco",
        "renovación mensual sin capitalizar",
    )
    if certificada and usura_ea is not None:
        supuestos += (f"usura vigente {formatear_tasa_ea(usura_ea)}",)
    else:
        supuestos += (ESTADO_USURA_SIN_CERTIFICAR,)

    return ComparacionGota(
        monto=prestamo.monto,
        plazo_meses=prestamo.meses_horizonte,
        tasa_ea_banco=banco["tasa_ea"],
        tasa_ea_gota=prestamo.tasa_ea,
        usura_ea=usura_ea,
        usura_vigencia=usura_vigencia,
        total_banco=total_banco,
        total_gota=total_gota,
        diferencia=total_gota - total_banco,
        veces_total=_cuantizar(total_gota / total_banco, 2),
        veces_usura=veces_usura,
        articulo_305=ARTICULO_305,
        supuestos=supuestos,
        fuente_usura=fuente_usura,
    )


def alertas_comparacion(comparacion: ComparacionGota) -> tuple[str, ...]:
    """Devuelve los códigos de alerta que la comparación deja visibles.

    La ausencia de usura certificada no detiene la escena, pero el auditor no
    puede dar `conforme` y la pantalla debe mostrarlo.

    Args:
        comparacion: comparación de Pana ya construida.

    Returns:
        Los códigos de alerta, vacío si la usura está certificada.
    """
    alertas: list[str] = []
    if comparacion.usura_ea is None or comparacion.fuente_usura is None:
        alertas.append(ESTADO_USURA_SIN_CERTIFICAR)
    return tuple(alertas)


def turnos_pana_comparacion(
    comparacion: ComparacionGota,
    *,
    orden_inicial: int = 8,
) -> tuple[TurnoEscena, ...]:
    """Arma los tres turnos fijos de Pana: golpe, tasa y ley.

    Args:
        comparacion: comparación de Pana ya calculada.
        orden_inicial: orden del primer turno en la escena completa.

    Returns:
        Los turnos `pana.golpe.v1`, `pana.tasa.v1` y `pana.ley.v1`, cada uno con
        sus cifras y fuentes; el primero lleva el escenario de comparación para
        el panel de trazabilidad.

    Raises:
        ValueError: si la comparación no trae el ratio de veces del total.
    """
    veces_total = comparacion.veces_total
    if veces_total is None:
        raise ValueError("la comparación necesita veces_total para el turno de Pana")
    monto = formatear_pesos(comparacion.monto)
    plazo = str(comparacion.plazo_meses)
    total_gota = formatear_pesos(comparacion.total_gota)
    total_banco = formatear_pesos(comparacion.total_banco)
    tasa_gota = formatear_tasa_ea(comparacion.tasa_ea_gota)
    tasa_banco = formatear_tasa_ea(comparacion.tasa_ea_banco)
    veces_total_texto, veces_total_frase = _texto_veces_total(veces_total)
    supuesto_texto = SUPUESTO_RENOVACION[0].upper() + SUPUESTO_RENOVACION[1:]

    texto_golpe = (
        f"{supuesto_texto}, con Don Gota pagarías "
        f"{total_gota} por {monto}; con el banco, a {plazo} meses, {total_banco}. "
        f"Es {veces_total_frase} veces lo que pagarías con el banco."
    )
    cifras_golpe = (
        _cifra(
            "total de Don Gota en el horizonte",
            comparacion.total_gota,
            total_gota,
            "pesos",
            _fuente_gota("total_pagado_horizonte"),
        ),
        _cifra("monto", comparacion.monto, monto, "pesos", _fuente_gota("monto")),
        _cifra(
            "plazo del horizonte",
            Decimal(comparacion.plazo_meses),
            plazo,
            "meses",
            _fuente_config("meses_horizonte"),
        ),
        _cifra(
            "total del banco en el horizonte",
            comparacion.total_banco,
            total_banco,
            "pesos",
            FuenteCifra(tipo="motor", referencia="diagnostico.motor#total_pagado.hasta"),
        ),
        _cifra(
            "veces el total del banco",
            veces_total,
            veces_total_texto,
            "veces",
            FuenteCifra(tipo="calculo_gota", referencia="escena.comparacion#veces_total"),
        ),
    )

    cifras_tasa: list[CifraEscena] = [
        _cifra(
            "tasa E.A. de Don Gota",
            comparacion.tasa_ea_gota,
            tasa_gota,
            "porcentaje_ea",
            _fuente_gota("tasa_ea"),
        )
    ]
    if comparacion.veces_usura is None:
        texto_tasa = f"Don Gota cobra {tasa_gota}. El banco, a su tasa máxima, cobra {tasa_banco}"
    else:
        veces_usura_texto = _formatear_veces(comparacion.veces_usura)
        texto_tasa = (
            f"Don Gota cobra {tasa_gota}: {veces_usura_texto} la usura. "
            f"El banco, a su tasa máxima, cobra {tasa_banco}"
        )
        cifras_tasa.append(
            _cifra(
                "veces la usura",
                comparacion.veces_usura,
                veces_usura_texto,
                "veces",
                FuenteCifra(tipo="calculo_gota", referencia="escena.comparacion#veces_usura"),
            )
        )
    cifras_tasa.append(
        _cifra(
            "tasa E.A. máxima del banco",
            comparacion.tasa_ea_banco,
            tasa_banco,
            "porcentaje_ea",
            FuenteCifra(tipo="motor", referencia="diagnostico.motor#tasa_ea.hasta"),
        )
    )

    cifras_ley: list[CifraEscena] = []
    if comparacion.usura_ea is not None:
        usura_texto = formatear_tasa_ea(comparacion.usura_ea)
        texto_ley = (
            "Si te cobran por encima de la usura, es delito "
            f"({comparacion.articulo_305}). Usura vigente: {usura_texto}, "
            f"{_vigencia_texto(comparacion.usura_vigencia)}."
        )
        cifras_ley.append(
            _cifra(
                "usura vigente",
                comparacion.usura_ea,
                usura_texto,
                "porcentaje_ea",
                comparacion.fuente_usura
                or FuenteCifra(tipo="usura", referencia="config/tasas.toml#usura.tasa_ea"),
            )
        )
    else:
        texto_ley = (
            "Si te cobran por encima de la usura, es delito "
            f"({comparacion.articulo_305}). Hoy no hay usura certificada vigente."
        )

    escenario = EscenarioEscena(
        codigo="comparacion",
        descripcion=f"Mismo monto y mismo horizonte de {comparacion.plazo_meses} meses",
        producto="libre_inversion",
        monto=comparacion.monto,
        plazo_meses=comparacion.plazo_meses,
        cuota_mensual=None,
        total_pagado=comparacion.total_gota,
        total_intereses=comparacion.total_gota - comparacion.monto,
        semaforo=None,
        razon_endeudamiento=None,
        margen_despues_cuota=None,
        aceptable=False,
        ofertable=False,
    )
    return (
        TurnoEscena(
            id="pana.golpe.v1",
            orden=orden_inicial,
            personaje="pana",
            texto=texto_golpe,
            cifras=cifras_golpe,
            escenario=escenario,
            origen="motor",
        ),
        TurnoEscena(
            id="pana.tasa.v1",
            orden=orden_inicial + 1,
            personaje="pana",
            texto=texto_tasa,
            cifras=tuple(cifras_tasa),
            origen="motor",
        ),
        TurnoEscena(
            id="pana.ley.v1",
            orden=orden_inicial + 2,
            personaje="pana",
            texto=texto_ley,
            cifras=tuple(cifras_ley),
            origen="motor",
        ),
    )


def _datos_banco(resultado: ResultadoDiagnostico) -> dict[str, Decimal]:
    """Extrae del motor el extremo máximo de tasa, total e intereses.

    Args:
        resultado: diagnóstico calculado para el mismo monto y horizonte.

    Returns:
        La tasa E.A. máxima, el total pagado máximo y el total de intereses
        máximo del rango del banco.

    Raises:
        ValueError: si el motor no produjo tasa o totales de crédito.
    """
    if (
        resultado.tasa_ea is None
        or resultado.total_pagado is None
        or resultado.total_intereses is None
    ):
        raise ValueError("el motor no pudo simular el crédito del banco para la comparación")
    return {
        "tasa_ea": resultado.tasa_ea.hasta,
        "total_pagado": resultado.total_pagado.hasta,
        "total_intereses": resultado.total_intereses.hasta,
    }


def _cifra(
    etiqueta: str,
    valor: Decimal,
    legible: str,
    unidad: UnidadCifra,
    fuente: FuenteCifra,
) -> CifraEscena:
    """Arma una cifra del turno de Pana con su fuente.

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


def _fuente_gota(campo: str) -> FuenteCifra:
    """Fuente de un valor calculado por `escena.gota`.

    Args:
        campo: nombre del campo del préstamo.

    Returns:
        La fuente con la referencia estable al cálculo.
    """
    return FuenteCifra(tipo="calculo_gota", referencia=f"escena.gota#{campo}")


def _fuente_config(campo: str) -> FuenteCifra:
    """Fuente de un parámetro leído de `config/escena.toml`.

    Args:
        campo: nombre del parámetro dentro de `[gota]`.

    Returns:
        La fuente con la ruta y la clave del TOML.
    """
    return FuenteCifra(tipo="config", referencia=f"config/escena.toml#gota.{campo}")


def _texto_veces_total(valor: Decimal) -> tuple[str, str]:
    """Escribe el ratio del total como «6», «casi 6» o «más de 6».

    Redondea al entero más cercano: si redondea hacia arriba dice «casi» y si
    redondea hacia abajo dice «más de», para no presentar un 6,3 como «casi 6»
    ni un 5,7 como «más de 6». El número que se cita es el del valor legible de
    la cifra y aparece en el texto del turno.

    Args:
        valor: veces que el total de Don Gota supera el del banco.

    Returns:
        El número que cita la cifra y la frase que acompaña a «veces».
    """
    cercano = int(_cuantizar(valor, 0))
    if valor == Decimal(cercano):
        return str(cercano), str(cercano)
    if valor < Decimal(cercano):
        return str(cercano), f"casi {cercano}"
    return str(cercano), f"más de {cercano}"


def _formatear_veces(valor: Decimal) -> str:
    """Escribe un ratio como «5,7 veces», con un decimal.

    Args:
        valor: número de veces.

    Returns:
        El texto legible con coma decimal y la unidad «veces».
    """
    cuantizado = _cuantizar(valor, 1)
    return f"{cuantizado:.1f}".replace(".", ",") + " veces"


def _vigencia_texto(vigencia: str | None) -> str:
    """Convierte la vigencia ISO de la usura en texto legible.

    Args:
        vigencia: rango ``AAAA-MM-DD/AAAA-MM-DD``, o None.

    Returns:
        La vigencia en español, como «del 1 al 30 de noviembre de 2026»; si el
        valor no es un rango ISO, lo devuelve con la etiqueta «con vigencia».
    """
    if not vigencia:
        return "con la vigencia publicada"
    try:
        desde, hasta = vigencia.split("/", 1)
        return vigencia_legible(date.fromisoformat(desde), date.fromisoformat(hasta))
    except ValueError:
        return f"con vigencia {vigencia}"


def _cuantizar(valor: Decimal, decimales: int) -> Decimal:
    """Redondea un decimal con la precisión indicada y `ROUND_HALF_UP`.

    Args:
        valor: decimal que se redondea.
        decimales: cifras decimales que se conservan.

    Returns:
        El decimal redondeado.
    """
    return valor.quantize(Decimal(1).scaleb(-decimales), rounding=ROUND_HALF_UP)
