"""Don Gota: préstamo determinista, frases fijas y turnos con fuente.

El módulo no llama a un modelo ni a la red. Lee `config/escena.toml [gota]` y
aplica las fórmulas del diseño en `Decimal` con `ROUND_HALF_UP`:

- ``interes_mensual = monto * tasa_mensual``
- ``total_ciclo = monto + interes_mensual``
- ``cuota_diaria = total_ciclo / dias_ciclo``
- ``intereses_horizonte = interes_mensual * meses_horizonte``
- ``total_pagado_horizonte = monto + intereses_horizonte``
- ``tasa_ea = (1 + tasa_mensual) ** 12 - 1``

El interés del horizonte es simple porque el capital no baja: la escena declara
el supuesto «si renuevas cada mes durante tres años». La tasa E.A. es la
equivalente compuesta de la tasa mensual, no el total del horizonte. Don Gota
no dice en voz la E.A. ni los totales de 36 meses: vende el costo mensual y la
cuota diaria; Pana revela el costo real y el supuesto.

Cada turno de Don Gota es `origen="guion_fijo"` y cada cifra que dice lleva su
`FuenteCifra`: el valor sale del préstamo calculado aquí o de la configuración,
nunca de un modelo.
"""

from __future__ import annotations

import hashlib
import tomllib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Context, Decimal, InvalidOperation, localcontext
from pathlib import Path

from ..config import PROJECT_ROOT
from .contratos import CifraEscena, FuenteCifra, PrestamoGota, TurnoEscena, UnidadCifra

#: Archivo versionado con los parámetros y las frases de Don Gota.
RUTA_CONFIG = PROJECT_ROOT / "config" / "escena.toml"
#: Versión de las fórmulas, que se guarda en el resultado para reproducirlo.
VERSION_FORMULA = "gota-v1"
#: Supuesto que la escena declara en voz y que los turnos de Pana repiten.
SUPUESTO_RENOVACION = "si renuevas cada mes durante tres años"
#: Grupos de frases fijas del banco de Don Gota.
GRUPOS_FRASES: tuple[str, ...] = ("oferta", "presion_diaria", "renovacion", "cierre")
#: Precisión decimal de las fórmulas.
PRECISION = 28


@dataclass(frozen=True, slots=True)
class ConfigGota:
    """Parámetros y frases de Don Gota leídos de `config/escena.toml`."""

    tasa_mensual: Decimal
    dias_ciclo: int
    meses_horizonte: int
    frases: Mapping[str, tuple[str, ...]]


def cargar_config_gota(ruta: Path | None = None) -> ConfigGota:
    """Lee la sección `[gota]` y su banco de frases fijas.

    Las frases pueden faltar al cargar solo la aritmética (por ejemplo, en una
    prueba con una tasa alternativa); `turnos_don_gota` exige el grupo que usa.

    Args:
        ruta: archivo TOML alternativo; por defecto `config/escena.toml`.

    Returns:
        La tasa mensual, los días del ciclo, el horizonte y las frases por grupo.

    Raises:
        FileNotFoundError: si el archivo no existe.
        ValueError: si falta `[gota]`, un parámetro no es positivo o el banco de
            frases no tiene la forma esperada.
    """
    archivo = Path(ruta) if ruta is not None else RUTA_CONFIG
    with archivo.open("rb") as fh:
        datos = tomllib.load(fh)

    gota = datos.get("gota")
    if not isinstance(gota, dict):
        raise ValueError("config/escena.toml no declara la sección [gota]")

    tasa = _decimal(gota.get("tasa_mensual", 0))
    dias = _entero(gota.get("dias_ciclo", 0), "dias_ciclo")
    meses = _entero(gota.get("meses_horizonte", 0), "meses_horizonte")
    if tasa <= 0:
        raise ValueError(f"gota.tasa_mensual debe ser positiva: {tasa}")
    if dias <= 0:
        raise ValueError(f"gota.dias_ciclo debe ser positivo: {dias}")
    if meses <= 0:
        raise ValueError(f"gota.meses_horizonte debe ser positivo: {meses}")

    frases_datos = gota.get("frases", {})
    if not isinstance(frases_datos, dict):
        raise ValueError("gota.frases debe ser una tabla de listas de frases")
    frases: dict[str, tuple[str, ...]] = {}
    for clave in GRUPOS_FRASES:
        opciones = frases_datos.get(clave, [])
        if not isinstance(opciones, list):
            raise ValueError(f"gota.frases.{clave} debe ser una lista de frases")
        frases[clave] = tuple(str(opcion) for opcion in opciones)

    return ConfigGota(
        tasa_mensual=tasa,
        dias_ciclo=dias,
        meses_horizonte=meses,
        frases=frases,
    )


def calcular_prestamo_gota(
    monto: Decimal | int | float | str,
    *,
    config: ConfigGota | None = None,
    ruta: Path | None = None,
) -> PrestamoGota:
    """Calcula el préstamo de Don Gota para un monto.

    Args:
        monto: capital prestado, en pesos. Debe ser positivo.
        config: configuración ya cargada; por defecto se lee el TOML.
        ruta: archivo TOML alternativo si no se pasa `config`.

    Returns:
        El préstamo con la aritmética redondeada al peso y la tasa E.A.
        equivalente, lista para citar en un turno.

    Raises:
        ValueError: si el monto no es un decimal finito positivo o si la
            configuración no tiene una tasa mensual positiva.
    """
    capital = _decimal(monto)
    if capital <= 0:
        raise ValueError(f"el monto del préstamo debe ser positivo: {capital}")
    ajustes = config if config is not None else cargar_config_gota(ruta)
    if ajustes.tasa_mensual <= 0:
        raise ValueError(f"la tasa mensual debe ser positiva: {ajustes.tasa_mensual}")

    with localcontext(_contexto()):
        interes = _peso(capital * ajustes.tasa_mensual)
        total_ciclo = _peso(capital + interes)
        cuota_diaria = _peso(total_ciclo / Decimal(ajustes.dias_ciclo))
        intereses_horizonte = _peso(interes * ajustes.meses_horizonte)
        total_horizonte = _peso(capital + intereses_horizonte)
        tasa_ea = _cuantizar((Decimal(1) + ajustes.tasa_mensual) ** 12 - Decimal(1), 4)

    return PrestamoGota(
        version_formula=VERSION_FORMULA,
        monto=capital,
        tasa_mensual=ajustes.tasa_mensual,
        dias_ciclo=ajustes.dias_ciclo,
        meses_horizonte=ajustes.meses_horizonte,
        interes_mensual=interes,
        total_ciclo=total_ciclo,
        cuota_diaria=cuota_diaria,
        intereses_horizonte=intereses_horizonte,
        total_pagado_horizonte=total_horizonte,
        tasa_ea=tasa_ea,
        supuesto=SUPUESTO_RENOVACION,
        fuente=FuenteCifra(
            tipo="calculo_gota",
            referencia="escena.gota#calcular_prestamo_gota",
        ),
    )


def seleccionar_frase(frases: Sequence[str], perfil: str | int) -> str:
    """Elige una frase por índice determinista a partir del perfil.

    Un entero se usa como índice directo (módulo la cantidad de frases); un
    texto se convierte con SHA-256, de modo que dos corridas del mismo perfil
    eligen la misma frase y el resultado no depende de `hash()` ni del proceso.

    Args:
        frases: opciones del grupo; no puede estar vacío.
        perfil: identificador del perfil o índice entero.

    Returns:
        La frase elegida, sin rellenar todavía.

    Raises:
        ValueError: si el grupo no tiene frases.
    """
    opciones = tuple(str(frase) for frase in frases)
    if not opciones:
        raise ValueError("el grupo de frases de Don Gota no puede estar vacío")
    return opciones[_indice(perfil, len(opciones))]


def turnos_don_gota(
    prestamo: PrestamoGota,
    perfil: str | int = "seguro",
    *,
    config: ConfigGota | None = None,
    orden_inicial: int = 1,
) -> tuple[TurnoEscena, ...]:
    """Construye los cuatro turnos fijos de Don Gota, con sus cifras y fuentes.

    El turno de oferta presenta el monto, el 20 % mensual y el costo del ciclo;
    el de presión diaria reparte el total entre los días; el de renovación
    insiste en renovar cuando quieras, sin papeles; y el cierre pide la firma.
    Don Gota no revela la tasa E.A. ni los totales de 36 meses: esas cifras
    quedan para Pana.

    Args:
        prestamo: resultado de `calcular_prestamo_gota`.
        perfil: identificador o índice que elige la frase de cada grupo.
        config: configuración con el banco de frases; por defecto se lee el TOML.
        orden_inicial: orden del primer turno en la escena completa.

    Returns:
        Los cuatro turnos, en el orden oferta, presión, renovación y cierre.

    Raises:
        ValueError: si falta el grupo de frases o una plantilla usa una variable
            desconocida.
    """
    ajustes = config if config is not None else cargar_config_gota()
    valores = _valores(prestamo)
    turnos: list[TurnoEscena] = []
    for posicion, (clave, identificador) in enumerate(zip(GRUPOS_FRASES, _IDS_TURNOS, strict=True)):
        opciones = ajustes.frases.get(clave, ())
        if not opciones:
            raise ValueError(f"falta el grupo de frases gota.frases.{clave}")
        texto = _formatear(seleccionar_frase(opciones, perfil), valores)
        turnos.append(
            TurnoEscena(
                id=identificador,
                orden=orden_inicial + posicion,
                personaje="don_gota",
                texto=texto,
                cifras=_cifras_turno(clave, prestamo, ajustes),
                origen="guion_fijo",
            )
        )
    return tuple(turnos)


def formatear_pesos(valor: Decimal) -> str:
    """Escribe un monto en pesos con separador de miles y signo.

    Args:
        valor: monto en pesos.

    Returns:
        El texto, como ``$1.000.000``.
    """
    entero = int(Decimal(valor).quantize(Decimal(1), rounding=ROUND_HALF_UP))
    signo = "-" if entero < 0 else ""
    return f"{signo}${abs(entero):,}".replace(",", ".")


def formatear_porcentaje(valor: Decimal) -> str:
    """Escribe una fracción como porcentaje con dos decimales y coma.

    Args:
        valor: fracción, donde 0,20 es 20 %.

    Returns:
        El texto, como ``20 %`` o ``791,61 %``.
    """
    centenas = _cuantizar(Decimal(valor) * 100, 2)
    texto = f"{centenas:.2f}".replace(".", ",").removesuffix(",00")
    return f"{texto} %"


def formatear_tasa_ea(valor: Decimal) -> str:
    """Escribe una tasa E.A. con su unidad.

    Args:
        valor: tasa como fracción, donde 0,2834 es 28,34 % E.A.

    Returns:
        El texto, como ``28,34 % E.A.``.
    """
    return f"{formatear_porcentaje(valor)} E.A."


#: Ids de los turnos, en el mismo orden que `GRUPOS_FRASES`.
_IDS_TURNOS: tuple[str, ...] = (
    "gota.oferta.v1",
    "gota.presion.v1",
    "gota.renovacion.v1",
    "gota.cierre.v1",
)


def _valores(prestamo: PrestamoGota) -> dict[str, str]:
    """Arma las variables legibles que rellenan las plantillas de Don Gota.

    Args:
        prestamo: préstamo calculado.

    Returns:
        El diccionario de variables con montos y tasas ya formateados.
    """
    return {
        "monto": formatear_pesos(prestamo.monto),
        "tasa_mensual": formatear_porcentaje(prestamo.tasa_mensual),
        "interes_mensual": formatear_pesos(prestamo.interes_mensual),
        "total_ciclo": formatear_pesos(prestamo.total_ciclo),
        "cuota_diaria": formatear_pesos(prestamo.cuota_diaria),
        "dias_ciclo": str(prestamo.dias_ciclo),
    }


def _formatear(plantilla: str, valores: Mapping[str, str]) -> str:
    """Rellena una plantilla y explica si usa una variable desconocida.

    Args:
        plantilla: frase del TOML con variables entre llaves.
        valores: variables disponibles.

    Returns:
        La frase con las variables reemplazadas.

    Raises:
        ValueError: si la plantilla usa una variable que no existe.
    """
    try:
        return _terminar(plantilla.format_map(valores))
    except (KeyError, IndexError) as error:
        raise ValueError(f"la frase de Don Gota usa una variable desconocida: {error}") from error


def _terminar(texto: str) -> str:
    """Cierra una frase con punto sin duplicarlo tras una abreviatura.

    Args:
        texto: frase que puede terminar en punto.

    Returns:
        La frase con un solo punto final.
    """
    return texto if texto.endswith(".") else f"{texto}."


def _cifras_turno(
    clave: str,
    prestamo: PrestamoGota,
    config: ConfigGota,
) -> tuple[CifraEscena, ...]:
    """Devuelve las cifras que dice un turno, cada una con su fuente.

    Args:
        clave: grupo de frases del turno.
        prestamo: préstamo calculado.
        config: configuración con los días del ciclo.

    Returns:
        Las cifras del turno, en el orden en que aparecen en su texto.
    """
    monto = _cifra(
        "monto prestado",
        prestamo.monto,
        formatear_pesos(prestamo.monto),
        "pesos",
        _fuente_gota("monto"),
    )
    tasa_mensual = _cifra(
        "tasa mensual",
        prestamo.tasa_mensual,
        formatear_porcentaje(prestamo.tasa_mensual),
        "porcentaje",
        _fuente_config("tasa_mensual"),
    )
    total = _cifra(
        "total del ciclo",
        prestamo.total_ciclo,
        formatear_pesos(prestamo.total_ciclo),
        "pesos",
        _fuente_gota("total_ciclo"),
    )
    cuota = _cifra(
        "cuota diaria",
        prestamo.cuota_diaria,
        formatear_pesos(prestamo.cuota_diaria),
        "pesos",
        _fuente_gota("cuota_diaria"),
    )
    dias = _cifra(
        "días del ciclo",
        Decimal(config.dias_ciclo),
        str(config.dias_ciclo),
        "dias",
        _fuente_config("dias_ciclo"),
    )
    por_grupo: dict[str, tuple[CifraEscena, ...]] = {
        "oferta": (monto, tasa_mensual, total, dias),
        "presion_diaria": (total, dias, cuota),
        "renovacion": (tasa_mensual, cuota),
        "cierre": (monto, cuota),
    }
    return por_grupo[clave]


def _cifra(
    etiqueta: str,
    valor: Decimal,
    legible: str,
    unidad: UnidadCifra,
    fuente: FuenteCifra,
) -> CifraEscena:
    """Arma una cifra de la escena con su fuente.

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


def _indice(perfil: str | int, cantidad: int) -> int:
    """Convierte un perfil en un índice estable entre 0 y `cantidad - 1`.

    Args:
        perfil: identificador textual o índice entero.
        cantidad: número de opciones.

    Returns:
        El índice determinista.
    """
    if isinstance(perfil, int):
        return perfil % cantidad
    digest = hashlib.sha256(str(perfil).encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") % cantidad


def _entero(valor: object, nombre: str) -> int:
    """Convierte un parámetro del TOML en entero positivo o explica el error.

    Args:
        valor: valor leído del TOML.
        nombre: nombre del parámetro, para el mensaje.

    Returns:
        El entero.

    Raises:
        ValueError: si el valor no es un entero.
    """
    try:
        return int(str(valor))
    except ValueError as error:
        raise ValueError(f"gota.{nombre} debe ser un entero: {valor!r}") from error


def _decimal(valor: object) -> Decimal:
    """Convierte un valor en decimal finito o explica el error.

    Args:
        valor: número, texto o `Decimal`.

    Returns:
        El decimal validado.

    Raises:
        ValueError: si el valor no es un decimal finito.
    """
    try:
        numero = Decimal(str(valor))
    except InvalidOperation as error:
        raise ValueError(f"el valor no es un decimal válido: {valor!r}") from error
    if not numero.is_finite():
        raise ValueError(f"el valor debe ser un decimal finito: {valor!r}")
    return numero


def _contexto() -> Context:
    """Devuelve el contexto decimal de la escena: 28 dígitos, mitad hacia arriba."""
    return Context(prec=PRECISION, rounding=ROUND_HALF_UP)


def _cuantizar(valor: Decimal, decimales: int) -> Decimal:
    """Redondea un decimal con la precisión indicada y `ROUND_HALF_UP`.

    Args:
        valor: decimal que se redondea.
        decimales: cifras decimales que se conservan.

    Returns:
        El decimal redondeado.
    """
    return valor.quantize(Decimal(1).scaleb(-decimales), rounding=ROUND_HALF_UP)


def _peso(valor: Decimal) -> Decimal:
    """Redondea un monto en pesos al peso, con `ROUND_HALF_UP`.

    Args:
        valor: monto que se redondea.

    Returns:
        El monto sin decimales.
    """
    return _cuantizar(valor, 0)
