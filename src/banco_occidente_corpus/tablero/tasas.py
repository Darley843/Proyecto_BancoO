"""Tasas de personas del PDF 2026: extracción, tabla Gold y usura.

El PDF vigente (`tasas-personas-bdo`, 1–30 de noviembre de 2026) publica las
tasas de colocación y captación en tablas «desde/hasta». Este módulo lee el PDF
de Bronze con `pypdfium2`, reconoce solo las tablas de los diez productos del
alcance y escribe una tabla Gold versionada por vigencia.

Las tasas se guardan como decimales entre 0 y 1. La tasa de mora, las
comisiones, los descuentos y las tablas variables quedan fuera de la tabla de
colocación. La tarjeta de crédito no publica M.V. sino «n.v.», así que su
`tasa_mv_*` se deja vacía en lugar de inventarla.

El CDT se desagrega por plazo y por rango de monto, con el plazo en días como
campo propio. Su tabla de largo plazo publica dos componentes variables por
plazo —IPC (% E.A.) e IBR (% sobre IBR a 30 días)— que se guardan tal como se
imprimen, con `tipo_tasa` en `spread_ipc` o `spread_ibr`. Un spread no es una
tasa: no se valida contra la usura ni contra la equivalencia M.V./E.A., no
entra en las consultas que devuelven «la tasa» del producto y se presenta
siempre como «IPC + X puntos» o «IBR + X puntos».

Antes de publicar, `validar_usura` recorre todas las filas de crédito y rechaza
la que supere la usura certificada en `config/tasas.toml`. Vivienda no se valida
contra esa usura (tiene modalidad y certificación propias) y ahorro y CDT no son
crédito: se exceptúan y sirven de control de cordura. `validar_coherencia_tasas`
comprueba además que cada M.V. publicada corresponda a su E.A. dentro de 0,01
puntos porcentuales.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import re
import tomllib
import unicodedata
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ..config import PROJECT_ROOT
from ..texto import normalizar
from .tipos import Fila

log = logging.getLogger(__name__)

#: Ruta de la configuración de tasas y usura.
RUTA_CONFIG_TASAS: Path = PROJECT_ROOT / "config" / "tasas.toml"
#: Productos que no se validan contra la usura de consumo y ordinario.
PRODUCTOS_EXCEPTUADOS: frozenset[str] = frozenset({"vivienda", "ahorro", "cdt"})
#: Cien, para convertir porcentajes a decimales.
_CIEN = Decimal(100)
#: Meses en español tal como los imprime el PDF.
_MESES: dict[str, int] = {
    "enero": 1,
    "febrero": 2,
    "marzo": 3,
    "abril": 4,
    "mayo": 5,
    "junio": 6,
    "julio": 7,
    "agosto": 8,
    "septiembre": 9,
    "octubre": 10,
    "noviembre": 11,
    "diciembre": 12,
}
#: Nota de vigencia impresa en el PDF, incluida la que omite «de» antes del año.
_RE_VIGENCIA = re.compile(
    r"Vigencia del\s+(\d{1,2})\s+al\s+(\d{1,2})\s+de\s+([A-Za-zÁÉÍÓÚÜáéíóúüñ]+)"
    r"\s+(?:de\s+)?(\d{4})",
    re.IGNORECASE,
)
#: Porcentajes de una línea, como `1,57%` o `0.01 %`.
_RE_PORCENTAJE = re.compile(r"(\d+(?:[.,]\d+)?)\s*%")
#: Renglón «Nuevo/Usado» de Occiauto con su M.V. y su E.A. publicadas.
_RE_VEHICULO = re.compile(
    r"(Nuevo|Usado)\*?\s+TASA\s+m\.?\s*v\.?\s+([\d.,]+)\s*%\s+"
    r"TASA\s+E\.?\s*A\.?\s+([\d.,]+)\s*%",
    re.IGNORECASE,
)
#: Renglón «Tasa Compra y Avances» de la tarjeta: E.A. y n.v. en pesos y dólares.
_RE_TARJETA = re.compile(
    r"Tasa\s+Compra\s+y\s+Avances\s+([\d.,]+)\s*%\s+([\d.,]+)\s*%"
    r"(?:\s+([\d.,]+)\s*%\s+([\d.,]+)\s*%)?",
    re.IGNORECASE,
)
#: Rangos de monto del encabezado de la tabla de CDT.
_RE_BANDA_CDT = re.compile(r"\$[\d.]+\s?M\w*\s*-\s*\$?[\d.]+\s?M\w*")
#: Renglón de CDT corto con sus tres tasas fijas (una por rango de monto).
_RE_FILA_CDT = re.compile(r"^(?P<plazo>\d+\s*D[ií]as.*?)\s+(?P<valores>(?:[\d,.]+\s*%\s*){3})$")
#: Renglón de CDT largo con sus componentes IPC e IBR.
_RE_FILA_CDT_LARGO = re.compile(
    r"^(?P<plazo>\d+\s*(?:D[ií]as|Meses|Años))\s+"
    r"(?P<ipc>[\d,.]+\s*%)\s+(?P<ibr>[\d,.]+\s*%)$"
)
#: Plazo publicado, para convertirlo a días (mes de 30 y año de 360).
_RE_PLAZO = re.compile(r"(\d+)\s*(d[ií]as|meses|años)", re.IGNORECASE)
#: Tramo de saldo de la cuenta de ahorros con su tasa.
_RE_TRAMO_AHORRO = re.compile(r"(De \$?[\d.]+(?:\s*[’']\s*[\d.]+)*\s+a \$?[\d.]+)\s+([\d,.]+)\s*%")
#: Tolerancia de la coherencia M.V./E.A.: 0,01 puntos porcentuales.
TOLERANCIA_MV = Decimal("0.0001")
#: Nombre visible de cada producto del alcance, para el Tablero y las consultas.
NOMBRES_PRODUCTO: dict[str, str] = {
    "libre_inversion": "Libre inversión",
    "compra_cartera": "Compra de cartera",
    "credito_rotativo": "Crédito rotativo",
    "libranza": "Libranza",
    "vehiculo_nuevo": "Vehículo nuevo",
    "vehiculo_usado": "Vehículo usado",
    "vivienda": "Vivienda",
    "tarjeta_credito": "Tarjeta de crédito",
    "ahorro": "Ahorro",
    "cdt": "CDT",
}
#: Nombre de cada mes en español, indexado por su número.
_NOMBRES_MES: dict[int, str] = {numero: nombre for nombre, numero in _MESES.items()}
#: Cifra con moneda (`$5.000.000`) o con unidad de monto (`200 millones`).
_RE_MONTO = re.compile(
    r"\$\s*(?P<pesos>\d[\d.,]*)"
    r"|(?P<numero>\d[\d.,]*)\s*(?P<unidad>millones|millon|mil)(?![a-z])",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class BandaMonto:
    """Banda de monto del CDT: texto publicado, etiqueta visible y extremos.

    Gold conserva el texto del PDF (`$500M- $99 MM`); el Tablero muestra la
    etiqueta legible (`De $500 mil a $99 millones`) y usa los extremos en pesos
    para responder por el monto de la pregunta.
    """

    publicado: str
    etiqueta: str
    desde: int
    hasta: int


#: Bandas de monto del CDT, de la más baja a la más alta, en pesos.
BANDAS_MONTO: tuple[BandaMonto, ...] = (
    BandaMonto("$500M- $99 MM", "De $500 mil a $99 millones", 500_000, 99_000_000),
    BandaMonto("$100 MM - 499 MM", "De $100 a $499 millones", 100_000_000, 499_000_000),
    BandaMonto(
        "$500 MM - 10.000 MM",
        "De $500 millones a $10.000 millones",
        500_000_000,
        10_000_000_000,
    ),
)


class ErrorTasas(ValueError):
    """Error de extracción o validación con un código estable para la API."""

    codigo = "error_tasas"

    def __init__(self, detalle: str) -> None:
        """Guarda el detalle y arma el mensaje con el código."""
        super().__init__(f"{self.codigo}: {detalle}")
        self.detalle = detalle


class TablaIncompleta(ErrorTasas):
    """El PDF cambió de maquetación y una tabla reconocida no se puede leer."""

    codigo = "tabla_incompleta"


class TasaFueraDeRango(ErrorTasas):
    """Una tasa no es un decimal entre 0 y 1 o el rango está invertido."""

    codigo = "tasa_fuera_de_rango"


class TasaSobreUsura(ErrorTasas):
    """Una tasa de crédito supera la usura certificada del período."""

    codigo = "tasa_sobre_usura"


class UsuraSinCertificar(ErrorTasas):
    """La usura conserva el centinela 0,0 y no se puede publicar la tabla."""

    codigo = "usura_sin_certificar"


class TasaIncoherente(ErrorTasas):
    """La M.V. publicada no corresponde a la E.A. del mismo renglón."""

    codigo = "tasa_incoherente"


class TasaNoDisponible(ErrorTasas):
    """No hay fila publicada para el producto y la fecha consultados."""

    codigo = "tasa_no_disponible"


class FilaTasa(BaseModel):
    """Una tasa publicada para un producto, su segmento y su vigencia."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    producto: str
    segmento: str | None = None
    #: Naturaleza de la cifra: tasa fija o spread sobre IPC o sobre IBR. Solo
    #: `fija` es una tasa y solo ella entra en usura, coherencia y consultas.
    tipo_tasa: Literal["fija", "spread_ipc", "spread_ibr"] = "fija"
    #: Plazo del CDT en días (30 por mes y 360 por año); el resto de productos
    #: no publica plazo y lo deja vacío.
    plazo_dias: int | None = Field(default=None, ge=1)
    tasa_ea_desde: Decimal
    tasa_ea_hasta: Decimal
    tasa_mv_desde: Decimal | None = None
    tasa_mv_hasta: Decimal | None = None
    vigencia_desde: date
    vigencia_hasta: date
    fuente: str
    sha256_pdf: str = Field(min_length=64, max_length=64)
    fecha_extraccion: date

    def como_dict(self) -> dict[str, object]:
        """Devuelve la fila como diccionario serializable a JSON."""
        return {
            "producto": self.producto,
            "segmento": self.segmento,
            "tipo_tasa": self.tipo_tasa,
            "plazo_dias": self.plazo_dias,
            "tasa_ea_desde": float(self.tasa_ea_desde),
            "tasa_ea_hasta": float(self.tasa_ea_hasta),
            "tasa_mv_desde": None if self.tasa_mv_desde is None else float(self.tasa_mv_desde),
            "tasa_mv_hasta": None if self.tasa_mv_hasta is None else float(self.tasa_mv_hasta),
            "vigencia_desde": self.vigencia_desde.isoformat(),
            "vigencia_hasta": self.vigencia_hasta.isoformat(),
            "fuente": self.fuente,
            "sha256_pdf": self.sha256_pdf,
            "fecha_extraccion": self.fecha_extraccion.isoformat(),
        }


class TasaVigente(BaseModel):
    """Tasa publicada para un producto, con su rango y su vigencia.

    Es la envolvente del producto en la vigencia elegida: el `desde` más bajo y
    el `hasta` más alto entre sus segmentos, sin promedio. Las filas por
    segmento se conservan en la tabla Gold y las devuelve `tasas_producto`.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    producto: str
    segmento: str | None = None
    tasa_ea_desde: Decimal
    tasa_ea_hasta: Decimal
    tasa_mv_desde: Decimal | None = None
    tasa_mv_hasta: Decimal | None = None
    vigencia_desde: date
    vigencia_hasta: date
    fuente: str
    sha256_pdf: str = Field(min_length=64, max_length=64)
    fecha_extraccion: date


@dataclass(frozen=True, slots=True)
class Usura:
    """Tasa de usura certificada para el período y sus productos exceptuados."""

    tasa_ea: Decimal
    vigencia_desde: date
    vigencia_hasta: date
    fuente: str
    resolucion: str
    exceptuados: frozenset[str]

    @property
    def certificada(self) -> bool:
        """Indica si hay una tasa certificada y no el centinela 0,0."""
        return self.tasa_ea > 0


@dataclass(frozen=True, slots=True)
class ConfiguracionTasas:
    """Fuente, archivos y usura que gobiernan la extracción de tasas."""

    fuente: str
    pagina: str
    vigencia_desde: date
    vigencia_hasta: date
    pdf: Path
    sha256: str
    tabla: Path
    usura: Usura


@dataclass(frozen=True, slots=True)
class _Metadatos:
    """Trazabilidad común a todas las filas de una extracción."""

    fuente: str
    sha256_pdf: str
    fecha_extraccion: date
    vigencia_desde: date
    vigencia_hasta: date


@dataclass(frozen=True, slots=True)
class _Columna:
    """Producto y segmento que representa una columna publicada."""

    producto: str
    segmento: str | None = None


@dataclass(frozen=True, slots=True)
class _Seccion:
    """Bloque del PDF con una tabla de tasas «desde/hasta»."""

    inicio: str
    fin: str
    ancla: str | None
    palabras: tuple[str, ...]
    columnas: tuple[_Columna, ...]


#: Tablas «desde/hasta» del PDF, con el producto y el segmento de cada columna.
#: Las tablas de la página 3 y las de la página 14 publican lo mismo: el
#: duplicado se colapsa al deduplicar las filas.
_SECCIONES: tuple[_Seccion, ...] = (
    _Seccion(
        inicio="Cupo línea Préstamo Personal",
        fin="Cupo línea Crédito Rotativo",
        ancla=None,
        palabras=("LIBREINVERSION", "COMPRADECARTERA"),
        columnas=(
            _Columna("libre_inversion"),
            _Columna("compra_cartera"),
        ),
    ),
    _Seccion(
        inicio="Cupo línea Crédito Rotativo",
        fin="Ahorro e Inversión",
        ancla=None,
        palabras=("LIBREINVERSION", "COMPRADECARTERA"),
        columnas=(
            _Columna("credito_rotativo", "Libre inversión"),
            _Columna("credito_rotativo", "Compra de cartera"),
        ),
    ),
    _Seccion(
        inicio="Préstamo Personal",
        fin="Crédito Rotativo",
        ancla="Líneas de Crédito",
        palabras=("LIBREINVERSION", "COMPRADECARTERA"),
        columnas=(
            _Columna("libre_inversion"),
            _Columna("compra_cartera"),
        ),
    ),
    _Seccion(
        inicio="Crédito Rotativo",
        fin="Crédito de Libranza",
        ancla="Líneas de Crédito",
        palabras=("LIBREINVERSION", "COMPRADECARTERA"),
        columnas=(
            _Columna("credito_rotativo", "Libre inversión"),
            _Columna("credito_rotativo", "Compra de cartera"),
        ),
    ),
    _Seccion(
        inicio="Crédito de Libranza",
        fin="Programa Fondo de Pensiones Voluntarias",
        ancla=None,
        palabras=("LIBREINVERSION", "COMPRADECARTERA", "RETANQUEO"),
        columnas=(
            _Columna("libranza", "Libre inversión"),
            _Columna("libranza", "Compra de cartera"),
            _Columna("libranza", "Retanqueo"),
        ),
    ),
    _Seccion(
        inicio="Tasas Vivienda",
        fin="Rango Clear",
        ancla=None,
        palabras=("HIPOTECARIO", "LEASING"),
        columnas=(
            _Columna("vivienda", "Crédito hipotecario"),
            _Columna("vivienda", "Leasing habitacional"),
        ),
    ),
)


def cargar_config_tasas(ruta: Path | None = None) -> ConfiguracionTasas:
    """Carga `config/tasas.toml` y devuelve la configuración tipada.

    Args:
        ruta: archivo TOML alternativo; por defecto `config/tasas.toml`.

    Returns:
        La fuente, los archivos y la usura del período.

    Raises:
        ValueError: si una vigencia no es una fecha ISO.
    """
    archivo = RUTA_CONFIG_TASAS if ruta is None else ruta
    datos: dict[str, Any] = {}
    if archivo.exists():
        with archivo.open("rb") as fh:
            datos = tomllib.load(fh)

    fuente = dict(datos.get("fuente", {}))
    archivos = dict(datos.get("archivo", {}))
    usura_datos = dict(datos.get("usura", {}))

    vigencia_desde = _fecha_iso(fuente.get("vigencia_desde"), date(2026, 11, 1))
    vigencia_hasta = _fecha_iso(fuente.get("vigencia_hasta"), date(2026, 11, 30))
    tabla = _ruta(
        archivos.get("tabla"),
        PROJECT_ROOT / "data" / "gold" / "tasas" / f"tasas-personas-{vigencia_desde:%Y-%m}.jsonl",
    )
    exceptuados = usura_datos.get("exceptuados", sorted(PRODUCTOS_EXCEPTUADOS))

    return ConfiguracionTasas(
        fuente=str(fuente.get("url", "")),
        pagina=str(fuente.get("pagina", "")),
        vigencia_desde=vigencia_desde,
        vigencia_hasta=vigencia_hasta,
        pdf=_ruta(archivos.get("pdf"), PROJECT_ROOT / "data/raw/documents/989be43a0ed19eb3.pdf"),
        sha256=str(archivos.get("sha256", "")),
        tabla=tabla,
        usura=Usura(
            tasa_ea=Decimal(str(usura_datos.get("tasa_ea", 0))),
            vigencia_desde=_fecha_iso(usura_datos.get("vigencia_desde"), vigencia_desde),
            vigencia_hasta=_fecha_iso(usura_datos.get("vigencia_hasta"), vigencia_hasta),
            fuente=str(usura_datos.get("fuente", "")),
            resolucion=str(usura_datos.get("resolucion", "")),
            exceptuados=frozenset(str(producto) for producto in exceptuados),
        ),
    )


def leer_texto_pdf(ruta: Path) -> str:
    """Extrae el texto del PDF página por página con `pypdfium2`.

    Args:
        ruta: PDF descargado en Bronze.

    Returns:
        El texto con un marcador `## Pagina N` por página.
    """
    import pypdfium2 as pdfium

    logging.getLogger("pypdfium2").setLevel(logging.ERROR)
    pdf = pdfium.PdfDocument(str(ruta))
    try:
        partes: list[str] = []
        for numero in range(len(pdf)):
            texto = pdf[numero].get_textpage().get_text_range() or ""
            texto = texto.replace("\r\n", "\n").replace("\r", "\n").replace("\x00", " ")
            texto = re.sub(r"[ \t]+", " ", texto)
            texto = re.sub(r"\n{3,}", "\n\n", texto).strip()
            partes.append(f"## Pagina {numero + 1}\n\n{texto}")
    finally:
        pdf.close()
    return "\n\n".join(partes)


def filas_desde_texto(
    texto: str,
    *,
    fuente: str,
    sha256_pdf: str,
    fecha_extraccion: date,
    vigencia_desde: date,
    vigencia_hasta: date,
) -> list[FilaTasa]:
    """Convierte el texto del PDF en filas de la tabla Gold.

    Args:
        texto: texto extraído del PDF.
        fuente: URL pública del PDF.
        sha256_pdf: huella del PDF de Bronze.
        fecha_extraccion: fecha en que se generó la tabla.
        vigencia_desde: inicio de la vigencia por defecto.
        vigencia_hasta: fin de la vigencia por defecto.

    Returns:
        Filas ordenadas y sin duplicados exactos.

    Raises:
        TablaIncompleta: si una tabla reconocida no se puede leer.
    """
    meta = _Metadatos(
        fuente=fuente,
        sha256_pdf=sha256_pdf,
        fecha_extraccion=fecha_extraccion,
        vigencia_desde=vigencia_desde,
        vigencia_hasta=vigencia_hasta,
    )
    lineas = [linea.rstrip() for linea in texto.splitlines()]
    filas: list[FilaTasa] = []
    for seccion in _SECCIONES:
        bloque = _recorte(lineas, seccion.inicio, seccion.fin, seccion.ancla)
        if bloque is None:
            continue
        filas.extend(_filas_seccion(bloque, seccion, meta))
    filas.extend(_filas_tarjeta(lineas, meta))
    filas.extend(_filas_vehiculos(texto, meta))
    filas.extend(_filas_cdt(lineas, meta))
    filas.extend(_filas_ahorro(lineas, meta))
    return _deduplicar(filas)


def validar_filas(filas: Iterable[FilaTasa]) -> None:
    """Comprueba que cada tasa es un decimal entre 0 y 1 y que el rango es válido.

    Args:
        filas: filas de la tabla Gold.

    Raises:
        TasaFueraDeRango: si una tasa se sale del rango o las fechas se cruzan.
    """
    for fila in filas:
        if not 0 <= fila.tasa_ea_desde <= fila.tasa_ea_hasta <= 1:
            raise TasaFueraDeRango(
                f"{fila.producto} ({fila.segmento or 'sin segmento'}): "
                f"E.A. {fila.tasa_ea_desde}–{fila.tasa_ea_hasta}"
            )
        if (
            fila.tasa_mv_desde is not None
            and fila.tasa_mv_hasta is not None
            and not 0 <= fila.tasa_mv_desde <= fila.tasa_mv_hasta <= 1
        ):
            raise TasaFueraDeRango(
                f"{fila.producto} ({fila.segmento or 'sin segmento'}): "
                f"M.V. {fila.tasa_mv_desde}–{fila.tasa_mv_hasta}"
            )
        if fila.vigencia_desde > fila.vigencia_hasta:
            raise TasaFueraDeRango(
                f"{fila.producto}: vigencia {fila.vigencia_desde} > {fila.vigencia_hasta}"
            )


def validar_usura(filas: Iterable[FilaTasa], usura: Usura) -> None:
    """Valida cada tasa de crédito contra la usura certificada del período.

    Args:
        filas: filas de la tabla Gold.
        usura: usura certificada con sus productos exceptuados.

    Raises:
        UsuraSinCertificar: si la usura conserva el centinela 0,0.
        TasaSobreUsura: si una tasa de crédito supera la usura.
    """
    if not usura.certificada:
        raise UsuraSinCertificar(
            f"no hay usura certificada entre {usura.vigencia_desde} y {usura.vigencia_hasta}"
        )
    for fila in filas:
        if fila.tipo_tasa != "fija" or fila.producto in usura.exceptuados:
            continue
        if fila.tasa_ea_hasta > usura.tasa_ea:
            raise TasaSobreUsura(
                f"{fila.producto} ({fila.segmento or 'sin segmento'}) publica "
                f"{fila.tasa_ea_hasta:%} E.A. y la usura es {usura.tasa_ea:%} E.A."
            )


def validar_coherencia_tasas(
    filas: Iterable[FilaTasa], tolerancia: Decimal = TOLERANCIA_MV
) -> None:
    """Comprueba que la M.V. publicada corresponda a la E.A. del mismo renglón.

    El PDF imprime la tasa mensual vencida junto a la efectiva anual. La
    equivalencia es `(1 + E.A.) ** (1/12) - 1`; se compara con una tolerancia de
    0,01 puntos porcentuales para absorber el redondeo de dos decimales del PDF.

    Args:
        filas: filas de la tabla Gold.
        tolerancia: diferencia máxima admitida, en fracción.

    Raises:
        TasaIncoherente: si una M.V. publicada no corresponde a su E.A.
    """
    for fila in filas:
        if fila.tipo_tasa != "fija":
            continue
        if fila.tasa_mv_desde is None or fila.tasa_mv_hasta is None:
            continue
        for etiqueta, ea, mv in (
            ("desde", fila.tasa_ea_desde, fila.tasa_mv_desde),
            ("hasta", fila.tasa_ea_hasta, fila.tasa_mv_hasta),
        ):
            mensual = (Decimal(1) + ea) ** (Decimal(1) / Decimal(12)) - Decimal(1)
            if abs(mensual - mv) > tolerancia:
                raise TasaIncoherente(
                    f"{fila.producto} ({fila.segmento or 'sin segmento'}) {etiqueta}: "
                    f"E.A. {ea:%} equivale a {mensual:.4%} mensual y la M.V. publica {mv:%}"
                )


def es_spread(fila: FilaTasa) -> bool:
    """Indica si la cifra de la fila es un spread sobre IPC o sobre IBR.

    Args:
        fila: fila de la tabla Gold.

    Returns:
        True si la fila no es una tasa fija.
    """
    return fila.tipo_tasa != "fija"


def tasas_fijas(filas: Iterable[FilaTasa]) -> list[FilaTasa]:
    """Filtra las filas que son tasas fijas y deja fuera los spreads.

    Toda consulta que devuelva «la tasa» de un producto (por ejemplo
    `tasa_vigente` o `tasas_producto`) debe partir de esta lista: un spread
    sobre IPC o IBR no es una tasa y no se puede comparar con una usura ni
    presentar como porcentaje E.A.

    Args:
        filas: filas de la tabla Gold.

    Returns:
        Las filas con `tipo_tasa="fija"`, en el orden recibido.
    """
    return [fila for fila in filas if not es_spread(fila)]


def describir_tasa(fila: FilaTasa) -> str:
    """Presenta una cifra de la tabla como tasa o como spread, sin confundirlas.

    Args:
        fila: fila de la tabla Gold.

    Returns:
        `«24,31 % E.A.»` para una tasa fija, `«IPC + 3,20 puntos»` para un
        spread sobre IPC y `«IBR + 0,20 puntos»` para un spread sobre IBR.
    """
    if fila.tipo_tasa == "spread_ipc":
        return f"{_spread(fila)} puntos"
    if fila.tipo_tasa == "spread_ibr":
        return f"{_spread(fila)} puntos"
    if fila.tasa_ea_desde == fila.tasa_ea_hasta:
        return f"{_porcentaje(fila.tasa_ea_desde)} % E.A."
    return f"{_porcentaje(fila.tasa_ea_desde)}–{_porcentaje(fila.tasa_ea_hasta)} % E.A."


def _spread(fila: FilaTasa) -> str:
    """Escribe el spread con su índice y sus puntos, sin la palabra «puntos»."""
    indice = "IPC" if fila.tipo_tasa == "spread_ipc" else "IBR"
    return f"{indice} + {_puntos(fila)}"


def _porcentaje(valor: Decimal) -> str:
    """Formatea un decimal como porcentaje con dos decimales y coma."""
    return f"{valor * 100:.2f}".replace(".", ",")


def _puntos(fila: FilaTasa) -> str:
    """Formatea el spread en puntos porcentuales, con coma decimal."""
    if fila.tasa_ea_desde == fila.tasa_ea_hasta:
        return _porcentaje(fila.tasa_ea_desde)
    return f"{_porcentaje(fila.tasa_ea_desde)}–{_porcentaje(fila.tasa_ea_hasta)}"


def clave_producto(producto: str) -> str:
    """Normaliza el nombre de un producto a su clave de la tabla Gold.

    Acepta «Libre inversión», «libre inversión» o «libre_inversion» y devuelve
    siempre la misma clave, para que la consulta no dependa de cómo se escriba.

    Args:
        producto: nombre o clave del producto.

    Returns:
        La clave canónica, en minúsculas y con guiones bajos.
    """
    descompuesto = unicodedata.normalize("NFKD", producto)
    sin_tildes = "".join(
        caracter for caracter in descompuesto if not unicodedata.combining(caracter)
    )
    return re.sub(r"[^a-z0-9]+", "_", sin_tildes.casefold()).strip("_")


def nombre_producto(producto: str) -> str:
    """Devuelve el nombre visible del producto; si no está en el alcance, la clave.

    Args:
        producto: clave canónica del producto.

    Returns:
        El nombre en español que se muestra en el Tablero.
    """
    return NOMBRES_PRODUCTO.get(producto, producto.replace("_", " ").capitalize())


def etiqueta_banda(segmento: str) -> str:
    """Devuelve la etiqueta legible de una banda de monto del CDT.

    El texto del PDF (`$500M- $99 MM`) se conserva en Gold; el Tablero muestra
    `De $500 mil a $99 millones`. Una banda desconocida se deja como está.

    Args:
        segmento: texto del segmento tal como lo publica el PDF.

    Returns:
        La etiqueta legible o el mismo texto si la banda no está en la tabla.
    """
    clave = _clave_banda(segmento)
    for banda in BANDAS_MONTO:
        if clave == _clave_banda(banda.publicado):
            return banda.etiqueta
    return segmento


def banda_de_concepto(concepto: str) -> BandaMonto | None:
    """Busca la banda de monto del CDT que nombra el concepto de una fila.

    Args:
        concepto: concepto de la fila del Tablero.

    Returns:
        La banda con sus extremos en pesos, o None si el concepto no nombra una.
    """
    texto = " ".join(concepto.split())
    for banda in BANDAS_MONTO:
        if banda.etiqueta in texto or _clave_banda(banda.publicado) in texto:
            return banda
    return None


def montos_en_texto(texto: str) -> list[int]:
    """Devuelve, en pesos, las cifras de monto que trae una pregunta.

    Reconoce la moneda (`$5.000.000`) y la unidad escrita (`200 millones`,
    `500 mil`). Una cifra sin unidad («a 360 días», «2 años») no es un monto.

    Args:
        texto: pregunta del cliente.

    Returns:
        Los montos en pesos, en el orden en que aparecen.
    """
    montos: list[int] = []
    for encontrado in _RE_MONTO.finditer(normalizar(texto)):
        numero = encontrado.group("pesos") or encontrado.group("numero")
        if not numero:
            continue
        valor = _numero_de_pesos(numero)
        unidad = encontrado.group("unidad")
        if unidad == "mil":
            valor *= 1_000
        elif unidad is not None:
            valor *= 1_000_000
        montos.append(int(valor))
    return montos


def sin_montos(texto: str) -> str:
    """Quita de la pregunta las cifras de monto, que se responden por banda.

    Así «por 200 millones» o «por $5.000.000» no se confunden con una cifra de
    la tabla al buscar la fila; el monto se usa después para elegir la banda.

    Args:
        texto: pregunta del cliente.

    Returns:
        La pregunta sin las expresiones de monto.
    """
    return " ".join(_RE_MONTO.sub(" ", normalizar(texto)).split())


def vigencia_legible(desde: date, hasta: date) -> str:
    """Escribe una vigencia en español, como «del 1 al 30 de noviembre de 2026».

    Args:
        desde: primer día de la vigencia.
        hasta: último día de la vigencia.

    Returns:
        La vigencia en texto, con el mes repetido solo si cambia.
    """
    if (desde.month, desde.year) == (hasta.month, hasta.year):
        return f"del {desde.day} al {hasta.day} de {_NOMBRES_MES[hasta.month]} de {hasta.year}"
    return (
        f"del {desde.day} de {_NOMBRES_MES[desde.month]} de {desde.year} al "
        f"{hasta.day} de {_NOMBRES_MES[hasta.month]} de {hasta.year}"
    )


def plazo_legible(dias: int) -> str:
    """Escribe un plazo en días con su equivalencia en meses o años.

    Args:
        dias: plazo publicado por el PDF, con mes de 30 y año de 360 días.

    Returns:
        «360 días (12 meses)», «720 días (2 años)» o «45 días».
    """
    if dias >= 720 and dias % 360 == 0:
        return f"{dias} días ({dias // 360} años)"
    if dias % 30 == 0:
        return f"{dias} días ({dias // 30} meses)"
    return f"{dias} días"


def concepto_tablero(fila: FilaTasa) -> str:
    """Arma el concepto con el que la tasa aparece en el Tablero.

    Args:
        fila: fila de la tabla Gold.

    Returns:
        «Libre inversión», «Libranza · Retanqueo» o «CDT · IPC · 720 días (2 años)».
    """
    partes = [nombre_producto(fila.producto)]
    if fila.segmento:
        partes.append(etiqueta_banda(fila.segmento))
    if fila.plazo_dias is not None:
        partes.append(plazo_legible(fila.plazo_dias))
    return " · ".join(partes)


def categoria_tablero(fila: FilaTasa) -> str:
    """Agrupa las filas que responden la misma pregunta de tasa.

    Incluye el producto y, cuando lo hay, el plazo: las bandas de monto y los
    índices de un mismo plazo son una sola respuesta y no una consulta ambigua.

    Args:
        fila: fila de la tabla Gold.

    Returns:
        La categoría del Tablero, como «tasa de interés · CDT · 360 días».
    """
    categoria = f"tasa de interés · {nombre_producto(fila.producto).casefold()}"
    if fila.plazo_dias is not None:
        categoria += f" · {fila.plazo_dias} días"
    return categoria


def fila_tablero(fila: FilaTasa, pagina: str) -> Fila:
    """Convierte una fila de tasas en una fila del Tablero.

    Una tasa fija sale como rango en `valor` con moneda `%`; un spread sobre IPC
    o IBR sale como «IPC + X puntos» con moneda `puntos`, nunca como porcentaje
    E.A. La periodicidad cita la vigencia completa y `fuente` es el PDF.

    Args:
        fila: fila de la tabla Gold.
        pagina: ruta de la tabla Gold que respalda la cifra.

    Returns:
        La fila con las diez columnas del contrato del Tablero.
    """
    vigencia = vigencia_legible(fila.vigencia_desde, fila.vigencia_hasta)
    if es_spread(fila):
        valor = _spread(fila)
        moneda = "puntos"
        periodicidad = f"vigencia {vigencia}"
    else:
        valor = _puntos(fila)
        moneda = "%"
        periodicidad = f"E.A., vigencia {vigencia}"
    return Fila(
        concepto=concepto_tablero(fila),
        categoria=categoria_tablero(fila),
        valor=valor,
        moneda=moneda,
        recargos="",
        periodicidad=periodicidad,
        vigente_desde=fila.vigencia_desde.isoformat(),
        origen="tasa",
        pagina=pagina,
        fuente=fila.fuente,
    )


def filas_tablero(filas: Iterable[FilaTasa], pagina: str) -> list[Fila]:
    """Convierte la tabla de tasas en filas del Tablero, sin duplicados.

    Args:
        filas: filas de la tabla Gold de la vigencia publicada.
        pagina: ruta de la tabla Gold que respalda las cifras.

    Returns:
        Una fila del Tablero por producto, segmento y plazo.
    """
    unicas: dict[tuple[object, ...], Fila] = {}
    for fila in filas:
        convertida = fila_tablero(fila, pagina)
        unicas.setdefault(_clave_fila_tablero(convertida), convertida)
    return sorted(unicas.values(), key=lambda convertida: convertida.concepto)


def tabla_mas_reciente(directorio: Path) -> Path | None:
    """Devuelve la tabla Gold de tasas de la vigencia más reciente.

    Args:
        directorio: carpeta `data/gold/tasas` con las tablas por vigencia.

    Returns:
        El archivo `tasas-personas-<AAAA-MM>.jsonl` más reciente, o None si la
        carpeta no existe o no tiene tablas.
    """
    if not directorio.is_dir():
        return None
    tablas = sorted(directorio.glob("tasas-personas-*.jsonl"))
    return tablas[-1] if tablas else None


def tablas_gold(raiz: Path | None = None) -> list[Path]:
    """Devuelve las tablas Gold de tasas, de la vigencia más antigua a la última.

    Args:
        raiz: carpeta de las tablas; por defecto la declarada en `config/tasas.toml`.

    Returns:
        Las tablas por vigencia en orden ascendente de nombre.
    """
    directorio = raiz if raiz is not None else cargar_config_tasas().tabla.parent
    if not directorio.is_dir():
        return []
    return sorted(directorio.glob("tasas-personas-*.jsonl"))


def cargar_tabla(ruta: Path) -> list[FilaTasa]:
    """Lee una tabla Gold descartando las filas que no cumplen el contrato.

    Normaliza la coma decimal y rechaza, sin corregir, la fila cuya tasa sea
    negativa, supere el 100 % o tenga la vigencia invertida. Cada descarte queda
    en el log con su número de línea.

    Args:
        ruta: archivo JSONL de la vigencia.

    Returns:
        Las filas válidas; vacío si el archivo no existe.
    """
    if not ruta.exists():
        return []
    filas: list[FilaTasa] = []
    for numero, linea in enumerate(ruta.read_text(encoding="utf-8").splitlines(), 1):
        if not linea.strip():
            continue
        try:
            fila = FilaTasa.model_validate(_normalizar_datos(json.loads(linea)))
        except (json.JSONDecodeError, ValidationError, TypeError, ValueError) as exc:
            log.warning("fila %d de %s descartada: %s", numero, ruta.name, exc)
            continue
        if not _rango_valido(fila):
            log.warning(
                "fila %d de %s descartada: tasa fuera de rango o vigencia invertida",
                numero,
                ruta.name,
            )
            continue
        filas.append(fila)
    return filas


def tasas_producto(
    producto: str,
    fecha: date | None = None,
    *,
    raiz: Path | None = None,
) -> list[FilaTasa]:
    """Devuelve las tasas fijas por segmento del producto en su vigencia vigente.

    Parte de `tasas_fijas`: un spread sobre IPC o IBR no es «la tasa» del
    producto y solo se presenta con `describir_tasa`. Elige la vigencia más
    reciente que contenga la fecha consultada (por defecto, la más reciente de
    la tabla) y no mezcla tasas de vigencias distintas.

    Args:
        producto: nombre o clave del producto.
        fecha: fecha consultada; por defecto, la vigencia más reciente.
        raiz: carpeta de las tablas; por defecto la de `config/tasas.toml`.

    Returns:
        Las filas por segmento de la vigencia elegida, en orden determinista.

    Raises:
        TasaNoDisponible: si el producto no tiene tasa o ninguna vigencia
            contiene la fecha consultada.
    """
    clave = clave_producto(producto)
    todas = [fila for ruta in tablas_gold(raiz) for fila in cargar_tabla(ruta)]
    fijas = [fila for fila in tasas_fijas(todas) if fila.producto == clave]
    if not fijas:
        raise TasaNoDisponible(f"no hay tasa publicada para «{producto}»")
    vigencia = _vigencia_elegida(fijas, fecha)
    elegidas: dict[tuple[object, ...], FilaTasa] = {}
    for fila in fijas:
        if fila.vigencia_desde == vigencia:
            elegidas.setdefault(_clave_fila(fila), fila)
    return sorted(elegidas.values(), key=_orden)


def tasa_vigente(
    producto: str,
    fecha: date | None = None,
    *,
    raiz: Path | None = None,
) -> TasaVigente:
    """Devuelve el rango E.A./M.V. del producto con su vigencia y su fuente.

    Con varios segmentos devuelve la envolvente del producto: el `desde` más
    bajo y el `hasta` más alto, sin promediar. La M.V. solo se informa cuando
    todas las filas elegidas la publican; si falta, queda vacía.

    Args:
        producto: nombre o clave del producto.
        fecha: fecha consultada; por defecto, la vigencia más reciente.
        raiz: carpeta de las tablas; por defecto la de `config/tasas.toml`.

    Returns:
        La envolvente de la tasa en la vigencia elegida.

    Raises:
        TasaNoDisponible: si el producto no tiene tasa publicado.
        TasaFueraDeRango: si el rango resultante no es un decimal válido.
    """
    filas = tasas_producto(producto, fecha, raiz=raiz)
    desde = min(fila.tasa_ea_desde for fila in filas)
    hasta = max(fila.tasa_ea_hasta for fila in filas)
    if not 0 <= desde <= hasta <= 1:
        raise TasaFueraDeRango(f"{filas[0].producto}: la envolvente E.A. queda en {desde}–{hasta}")
    mensuales = [
        (fila.tasa_mv_desde, fila.tasa_mv_hasta)
        for fila in filas
        if fila.tasa_mv_desde is not None and fila.tasa_mv_hasta is not None
    ]
    publicadas = len(mensuales) == len(filas)
    segmentos = {fila.segmento for fila in filas}
    huellas = {fila.sha256_pdf for fila in filas}
    if len(huellas) > 1:
        log.warning(
            "la vigencia %s mezcla PDF: %d huellas distintas",
            filas[0].vigencia_desde,
            len(huellas),
        )
    return TasaVigente(
        producto=filas[0].producto,
        segmento=segmentos.pop() if len(segmentos) == 1 else None,
        tasa_ea_desde=desde,
        tasa_ea_hasta=hasta,
        tasa_mv_desde=min(valor[0] for valor in mensuales) if publicadas else None,
        tasa_mv_hasta=max(valor[1] for valor in mensuales) if publicadas else None,
        vigencia_desde=min(fila.vigencia_desde for fila in filas),
        vigencia_hasta=max(fila.vigencia_hasta for fila in filas),
        fuente=filas[0].fuente,
        sha256_pdf=filas[0].sha256_pdf,
        fecha_extraccion=filas[0].fecha_extraccion,
    )


def _vigencia_elegida(filas: Sequence[FilaTasa], fecha: date | None) -> date:
    """Elige la vigencia más reciente que contenga la fecha consultada."""
    if fecha is None:
        return max(fila.vigencia_desde for fila in filas)
    candidatas = [
        fila.vigencia_desde for fila in filas if fila.vigencia_desde <= fecha <= fila.vigencia_hasta
    ]
    if not candidatas:
        raise TasaNoDisponible(f"{filas[0].producto}: sin tasa vigente el {fecha.isoformat()}")
    return max(candidatas)


def _numero_de_pesos(texto: str) -> Decimal:
    """Convierte una cifra escrita a su valor en pesos, sin la unidad."""
    limpio = texto.rstrip(".,")
    if re.fullmatch(r"\d{1,3}(?:\.\d{3})+", limpio):
        limpio = limpio.replace(".", "")
    elif "," in limpio:
        limpio = limpio.replace(".", "").replace(",", ".")
    return Decimal(limpio)


def _clave_banda(texto: str) -> str:
    """Normaliza los espacios de una banda para comparar dos textos."""
    return " ".join(texto.split())


def _normalizar_datos(datos: object) -> dict[str, object]:
    """Normaliza la coma decimal de las tasas de una fila cruda del JSONL."""
    if not isinstance(datos, dict):
        raise TypeError("la fila no es un objeto JSON")
    limpio = dict(datos)
    for campo in ("tasa_ea_desde", "tasa_ea_hasta", "tasa_mv_desde", "tasa_mv_hasta"):
        valor = limpio.get(campo)
        if isinstance(valor, str):
            limpio[campo] = valor.replace(",", ".")
    return limpio


def _rango_valido(fila: FilaTasa) -> bool:
    """Indica si la fila tiene tasas entre 0 y 1 y la vigencia en orden."""
    if not 0 <= fila.tasa_ea_desde <= fila.tasa_ea_hasta <= 1:
        return False
    if (
        fila.tasa_mv_desde is not None
        and fila.tasa_mv_hasta is not None
        and not 0 <= fila.tasa_mv_desde <= fila.tasa_mv_hasta <= 1
    ):
        return False
    return fila.vigencia_desde <= fila.vigencia_hasta


def _clave_fila_tablero(fila: Fila) -> tuple[str, ...]:
    """Identidad de una fila del Tablero, para no duplicarla."""
    return (fila.concepto, fila.categoria, fila.valor, fila.origen)


def escribir_tabla(ruta: Path, filas: Iterable[FilaTasa]) -> int:
    """Reescribe completa la tabla Gold de la vigencia y devuelve el total.

    Args:
        ruta: archivo JSONL de la vigencia.
        filas: filas a publicar; se ordenan y se deduplican.

    Returns:
        El número de filas escritas.
    """
    ordenadas = _deduplicar(filas)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    temporal = ruta.with_name(f"{ruta.name}.tmp")
    with temporal.open("w", encoding="utf-8", newline="\n") as fh:
        for fila in ordenadas:
            fh.write(json.dumps(fila.como_dict(), ensure_ascii=False) + "\n")
    temporal.replace(ruta)
    return len(ordenadas)


def leer_tabla(ruta: Path) -> list[FilaTasa]:
    """Lee la tabla Gold de una vigencia y devuelve las filas tipadas.

    Args:
        ruta: archivo JSONL de la vigencia.

    Returns:
        Las filas de la tabla, o una lista vacía si el archivo no existe.
    """
    if not ruta.exists():
        return []
    filas: list[FilaTasa] = []
    with ruta.open(encoding="utf-8") as fh:
        for linea in fh:
            if linea.strip():
                filas.append(FilaTasa.model_validate(json.loads(linea)))
    return filas


def extraer_tasas(
    ruta_pdf: Path | None = None,
    salida: Path | None = None,
    *,
    configuracion: ConfiguracionTasas | None = None,
    fecha_extraccion: date | None = None,
) -> list[FilaTasa]:
    """Extrae las tasas del PDF de Bronze y publica la tabla Gold.

    Args:
        ruta_pdf: PDF a leer; por defecto el declarado en `config/tasas.toml`.
        salida: archivo JSONL; por defecto la tabla Gold de la vigencia.
        configuracion: configuración ya cargada.
        fecha_extraccion: fecha de la extracción; por defecto hoy.

    Returns:
        Las filas publicadas.

    Raises:
        TablaIncompleta: si una tabla reconocida no se puede leer.
        TasaFueraDeRango: si una tasa se sale del rango.
        TasaSobreUsura: si una tasa de crédito supera la usura.
        UsuraSinCertificar: si la usura no está certificada.
        TasaIncoherente: si una M.V. no corresponde a su E.A.
    """
    config = configuracion or cargar_config_tasas()
    pdf = ruta_pdf or config.pdf
    destino = salida or config.tabla
    sha256_pdf = _sha256(pdf)
    if config.sha256 and config.sha256 != sha256_pdf:
        log.warning("el PDF de tasas cambió: %s != %s", sha256_pdf, config.sha256)
    filas = filas_desde_texto(
        leer_texto_pdf(pdf),
        fuente=config.fuente,
        sha256_pdf=sha256_pdf,
        fecha_extraccion=fecha_extraccion or date.today(),
        vigencia_desde=config.vigencia_desde,
        vigencia_hasta=config.vigencia_hasta,
    )
    validar_filas(filas)
    validar_usura(filas, config.usura)
    validar_coherencia_tasas(filas)
    escribir_tabla(destino, filas)
    return filas


def main(argv: Sequence[str] | None = None) -> int:
    """Punto de entrada de `python -m banco_occidente_corpus.tablero.tasas`.

    Args:
        argv: argumentos de línea de comandos; por defecto `sys.argv[1:]`.

    Returns:
        El código de salida del proceso.
    """
    parser = argparse.ArgumentParser(description="Extrae las tasas de personas del PDF de Bronze.")
    parser.add_argument("--pdf", type=Path, default=None, help="PDF de Bronze a leer.")
    parser.add_argument("--salida", type=Path, default=None, help="tabla Gold JSONL de salida.")
    parser.add_argument("--config", type=Path, default=None, help="TOML de tasas alternativo.")
    parser.add_argument(
        "--fecha", type=date.fromisoformat, default=None, help="fecha de extracción."
    )
    args = parser.parse_args(argv)

    configuracion = cargar_config_tasas(args.config)
    filas = extraer_tasas(
        args.pdf,
        args.salida,
        configuracion=configuracion,
        fecha_extraccion=args.fecha,
    )
    destino = args.salida or configuracion.tabla
    print(f"{len(filas)} filas -> {destino}")
    return 0


def _filas_seccion(bloque: Sequence[str], seccion: _Seccion, meta: _Metadatos) -> list[FilaTasa]:
    """Lee una tabla «desde/hasta» y devuelve una fila por columna.

    Args:
        bloque: líneas del bloque, sin su encabezado.
        seccion: producto y segmento de cada columna.
        meta: trazabilidad de la extracción.

    Returns:
        Las filas de la sección.

    Raises:
        TablaIncompleta: si la cabecera o las tasas no cuadran con las columnas.
    """
    cabecera = _clave(" ".join(bloque[:8]))
    if not all(palabra in cabecera for palabra in seccion.palabras):
        raise TablaIncompleta(
            f"la tabla «{seccion.inicio}» no conserva la cabecera esperada: {seccion.palabras}"
        )
    ea = _valores_tasa(bloque, "TASAEA")
    if ea is None:
        raise TablaIncompleta(f"la tabla «{seccion.inicio}» no publica la fila Tasa E.A.")
    mv = _valores_tasa(bloque, "TASAMV")
    cantidad = len(seccion.columnas)
    if len(ea) != 2 * cantidad or (mv is not None and len(mv) != 2 * cantidad):
        raise TablaIncompleta(
            f"la tabla «{seccion.inicio}» publica {len(ea)} tasas E.A. para {cantidad} columnas"
        )
    vigencia = _vigencia("\n".join(bloque), (meta.vigencia_desde, meta.vigencia_hasta))
    filas: list[FilaTasa] = []
    for indice, columna in enumerate(seccion.columnas):
        rango_ea = (ea[2 * indice], ea[2 * indice + 1])
        rango_mv = None if mv is None else (mv[2 * indice], mv[2 * indice + 1])
        filas.append(
            _nueva_fila(meta, columna.producto, columna.segmento, rango_ea, rango_mv, vigencia)
        )
    return filas


def _filas_tarjeta(lineas: Sequence[str], meta: _Metadatos) -> list[FilaTasa]:
    """Lee la tasa de compras y avances de la tarjeta en pesos y en dólares.

    El PDF publica la tasa «n.v.» (nominal vencida), no la M.V., así que esas
    filas quedan con `tasa_mv_*` vacía.

    Args:
        lineas: líneas del PDF.
        meta: trazabilidad de la extracción.

    Returns:
        Una fila por moneda publicada.
    """
    bloque = _recorte(lineas, "Visa clásica", "Líneas de Crédito")
    if bloque is None:
        return []
    texto = "\n".join(bloque)
    pesos: Decimal | None = None
    dolares: Decimal | None = None
    for encontrado in _RE_TARJETA.finditer(texto):
        pesos = pesos or _decimal(encontrado.group(1))
        if encontrado.group(3):
            dolares = dolares or _decimal(encontrado.group(3))
    vigencia = _vigencia(texto, (meta.vigencia_desde, meta.vigencia_hasta))
    filas: list[FilaTasa] = []
    if pesos is not None:
        filas.append(_nueva_fila(meta, "tarjeta_credito", "Pesos", (pesos, pesos), None, vigencia))
    if dolares is not None:
        filas.append(
            _nueva_fila(meta, "tarjeta_credito", "Dólares", (dolares, dolares), None, vigencia)
        )
    return filas


def _filas_vehiculos(texto: str, meta: _Metadatos) -> list[FilaTasa]:
    """Lee las tasas fijas de vehículo nuevo y usado de Occiauto.

    Args:
        texto: texto completo del PDF.
        meta: trazabilidad de la extracción.

    Returns:
        Una fila por modelo publicado.
    """
    encontrados: dict[str, tuple[Decimal, Decimal]] = {}
    for encontrado in _RE_VEHICULO.finditer(texto):
        modelo = encontrado.group(1).casefold()
        encontrados.setdefault(
            modelo, (_decimal(encontrado.group(2)), _decimal(encontrado.group(3)))
        )
    filas: list[FilaTasa] = []
    for modelo, producto in (("nuevo", "vehiculo_nuevo"), ("usado", "vehiculo_usado")):
        if modelo not in encontrados:
            continue
        mv, ea = encontrados[modelo]
        filas.append(_nueva_fila(meta, producto, "Persona natural", (ea, ea), (mv, mv)))
    return filas


def _filas_cdt(lineas: Sequence[str], meta: _Metadatos) -> list[FilaTasa]:
    """Lee las dos tablas de CDT: tasa fija por plazo y monto, y largo plazo.

    La tabla corta publica una tasa por plazo y por rango de monto. La tabla de
    largo plazo publica dos componentes por plazo, IPC (% E.A.) e IBR (% sobre
    IBR a 30 días); se guardan tal como se imprimen, cada una en su segmento.

    Args:
        lineas: líneas del PDF.
        meta: trazabilidad de la extracción.

    Returns:
        Una fila por plazo y rango de monto, y una por plazo e índice.

    Raises:
        TablaIncompleta: si la cabecera o los renglones no se pueden leer.
    """
    return [
        *_filas_cdt_corto(lineas, meta),
        *_filas_cdt_largo(lineas, meta),
    ]


def _filas_cdt_corto(lineas: Sequence[str], meta: _Metadatos) -> list[FilaTasa]:
    """Lee el CDT a tasa fija con una fila por plazo y rango de monto.

    Args:
        lineas: líneas del PDF.
        meta: trazabilidad de la extracción.

    Returns:
        Las filas de la tabla de CDT corto.

    Raises:
        TablaIncompleta: si la cabecera o los renglones no se pueden leer.
    """
    bloque = _recorte(
        lineas, "Tasas CDT (% Efectivo Anual)", "Tasas de Captación de CDT LARGO PLAZO"
    )
    if bloque is None:
        return []
    bandas: list[str] = []
    for linea in bloque:
        encontradas = _RE_BANDA_CDT.findall(linea)
        if len(encontradas) == 3:
            bandas = [" ".join(banda.split()) for banda in encontradas]
            break
    if not bandas:
        raise TablaIncompleta("la tabla de CDT no publica sus tres rangos de monto")
    filas: list[FilaTasa] = []
    for linea in bloque:
        encontrado = _RE_FILA_CDT.match(linea.strip())
        if encontrado is None:
            continue
        tasas = _porcentajes(encontrado.group("valores"))
        if len(tasas) != len(bandas):
            raise TablaIncompleta(f"el renglón «{encontrado.group('plazo')}» no publica tres tasas")
        plazo = _plazo_en_dias(encontrado.group("plazo"))
        if plazo is None:
            raise TablaIncompleta(f"el renglón «{encontrado.group('plazo')}» no declara plazo")
        for banda, tasa in zip(bandas, tasas, strict=True):
            filas.append(_nueva_fila(meta, "cdt", banda, (tasa, tasa), plazo_dias=plazo))
    return filas


def _filas_cdt_largo(lineas: Sequence[str], meta: _Metadatos) -> list[FilaTasa]:
    """Lee el CDT de largo plazo: componentes IPC e IBR por plazo.

    Args:
        lineas: líneas del PDF.
        meta: trazabilidad de la extracción.

    Returns:
        Una fila por plazo e índice publicado con tasa.
    """
    bloque = _recorte(lineas, "Tasas de Captación de CDT LARGO PLAZO", "SALDO DIARIO")
    if bloque is None:
        return []
    filas: list[FilaTasa] = []
    for linea in bloque:
        encontrado = _RE_FILA_CDT_LARGO.match(linea.strip())
        if encontrado is None:
            continue
        plazo = _plazo_en_dias(encontrado.group("plazo"))
        if plazo is None:
            continue
        ipc = _porcentajes(encontrado.group("ipc"))
        ibr = _porcentajes(encontrado.group("ibr"))
        if ipc:
            filas.append(
                _nueva_fila(
                    meta,
                    "cdt",
                    "IPC",
                    (ipc[0], ipc[0]),
                    plazo_dias=plazo,
                    tipo_tasa="spread_ipc",
                )
            )
        if ibr:
            filas.append(
                _nueva_fila(
                    meta,
                    "cdt",
                    "IBR a 30 días",
                    (ibr[0], ibr[0]),
                    plazo_dias=plazo,
                    tipo_tasa="spread_ibr",
                )
            )
    return filas


def _filas_ahorro(lineas: Sequence[str], meta: _Metadatos) -> list[FilaTasa]:
    """Lee los tramos de saldo de la cuenta de ahorros con su tasa E.A.

    Args:
        lineas: líneas del PDF.
        meta: trazabilidad de la extracción.

    Returns:
        Una fila por tramo de saldo publicado con tasa.
    """
    bloque = _recorte(lineas, "Tasas de Captación Cuenta de Ahorros", "KUBO")
    if bloque is None:
        return []
    texto = " ".join(linea.strip() for linea in bloque if linea.strip())
    vigencia = _vigencia(texto, (meta.vigencia_desde, meta.vigencia_hasta))
    filas: list[FilaTasa] = []
    for encontrado in _RE_TRAMO_AHORRO.finditer(texto):
        tramo = " ".join(encontrado.group(1).split())
        tasa = _decimal(encontrado.group(2))
        filas.append(_nueva_fila(meta, "ahorro", tramo, (tasa, tasa), None, vigencia))
    return filas


def _nueva_fila(
    meta: _Metadatos,
    producto: str,
    segmento: str | None,
    ea: tuple[Decimal, Decimal],
    mv: tuple[Decimal, Decimal] | None = None,
    vigencia: tuple[date, date] | None = None,
    plazo_dias: int | None = None,
    tipo_tasa: Literal["fija", "spread_ipc", "spread_ibr"] = "fija",
) -> FilaTasa:
    """Arma una fila de la tabla con la trazabilidad de la extracción.

    Args:
        meta: trazabilidad de la extracción.
        producto: clave canónica del producto.
        segmento: segmento publicado, si lo hay.
        ea: rango de tasa efectiva anual, como decimales.
        mv: rango de tasa mensual vencida, si el PDF lo publica.
        vigencia: vigencia publicada; por defecto la de la fuente.
        plazo_dias: plazo del CDT en días, si el producto lo publica.
        tipo_tasa: tasa fija o spread sobre IPC o IBR.

    Returns:
        La fila lista para publicar.
    """
    desde, hasta = vigencia or (meta.vigencia_desde, meta.vigencia_hasta)
    return FilaTasa(
        producto=producto,
        segmento=segmento,
        tipo_tasa=tipo_tasa,
        plazo_dias=plazo_dias,
        tasa_ea_desde=ea[0],
        tasa_ea_hasta=ea[1],
        tasa_mv_desde=None if mv is None else mv[0],
        tasa_mv_hasta=None if mv is None else mv[1],
        vigencia_desde=desde,
        vigencia_hasta=hasta,
        fuente=meta.fuente,
        sha256_pdf=meta.sha256_pdf,
        fecha_extraccion=meta.fecha_extraccion,
    )


def _plazo_en_dias(texto: str) -> int | None:
    """Convierte un plazo publicado (`18 Meses`, `2 Años`, `90 Días`) a días.

    Args:
        texto: etiqueta del plazo tal como la imprime el PDF.

    Returns:
        El plazo en días con mes de 30 y año de 360, o None si no se reconoce.
    """
    encontrado = _RE_PLAZO.search(texto)
    if encontrado is None:
        return None
    cantidad = int(encontrado.group(1))
    unidad = encontrado.group(2).casefold()
    if unidad.startswith("mes"):
        return cantidad * 30
    if unidad.startswith("año"):
        return cantidad * 360
    return cantidad


def _recorte(
    lineas: Sequence[str], inicio: str, fin: str, ancla: str | None = None
) -> list[str] | None:
    """Devuelve las líneas entre un encabezado y su terminador.

    Args:
        lineas: líneas del PDF.
        inicio: texto con el que empieza el bloque.
        fin: texto con el que empieza la sección siguiente.
        ancla: texto previo desde el cual buscar el bloque.

    Returns:
        Las líneas del bloque, o None si el PDF no lo publica.

    Raises:
        TablaIncompleta: si el bloque empieza y no termina.
    """
    desde = 0
    if ancla is not None:
        posicion = _linea(lineas, ancla, 0)
        if posicion is None:
            return None
        desde = posicion + 1
    comienzo = _linea(lineas, inicio, desde)
    if comienzo is None:
        return None
    final = _linea(lineas, fin, comienzo + 1)
    if final is None:
        raise TablaIncompleta(f"la sección «{inicio}» no cierra con «{fin}»")
    return list(lineas[comienzo + 1 : final])


def _linea(lineas: Sequence[str], prefijo: str, desde: int) -> int | None:
    """Devuelve el índice de la primera línea que empieza con `prefijo`."""
    for indice in range(desde, len(lineas)):
        if lineas[indice].strip().startswith(prefijo):
            return indice
    return None


def _valores_tasa(bloque: Sequence[str], etiqueta: str) -> list[Decimal] | None:
    """Devuelve los porcentajes de la fila «Tasa E.A.» o «Tasa M.V.».

    Args:
        bloque: líneas de la tabla.
        etiqueta: `TASAEA` o `TASAMV`, ya normalizada.

    Returns:
        Los porcentajes en el orden publicado, o None si la fila no existe.
    """
    for indice, linea in enumerate(bloque):
        if _etiqueta(linea) != etiqueta:
            continue
        valores = _porcentajes(linea)
        if valores:
            return valores
        for siguiente in bloque[indice + 1 : indice + 7]:
            if "Vigencia del" in siguiente:
                break
            if not siguiente.strip():
                continue
            valores = _porcentajes(siguiente)
            if valores:
                return valores
    return None


def _etiqueta(linea: str) -> str:
    """Normaliza la etiqueta de una fila de tasas, antes de la primera cifra."""
    return _clave(re.split(r"\d", linea, maxsplit=1)[0])


def _porcentajes(linea: str) -> list[Decimal]:
    """Devuelve los porcentajes de una línea como decimales entre 0 y 1."""
    return [_decimal(valor) for valor in _RE_PORCENTAJE.findall(linea)]


def _decimal(valor: str) -> Decimal:
    """Convierte `28,17` o `28.17` en el decimal `0.2817`."""
    return Decimal(valor.replace(",", ".")) / _CIEN


def _vigencia(texto: str, defecto: tuple[date, date]) -> tuple[date, date]:
    """Devuelve la vigencia impresa en el texto; si no hay, la de la fuente.

    Args:
        texto: bloque o página donde buscar la nota de vigencia.
        defecto: vigencia de la fuente.

    Returns:
        La vigencia publicada o la de la fuente.

    Raises:
        TablaIncompleta: si la nota de vigencia trae una fecha imposible.
    """
    encontrado = _RE_VIGENCIA.search(texto)
    if encontrado is None:
        return defecto
    dia_desde, dia_hasta, mes, anio = encontrado.groups()
    numero_mes = _MESES.get(_clave(mes).casefold())
    if numero_mes is None:
        return defecto
    try:
        return (
            date(int(anio), numero_mes, int(dia_desde)),
            date(int(anio), numero_mes, int(dia_hasta)),
        )
    except ValueError as exc:
        raise TablaIncompleta(f"vigencia imposible en «{encontrado.group(0)}»") from exc


def _deduplicar(filas: Iterable[FilaTasa]) -> list[FilaTasa]:
    """Elimina filas idénticas y las ordena de forma determinista."""
    unicas: dict[tuple[object, ...], FilaTasa] = {}
    for fila in filas:
        unicas.setdefault(_clave_fila(fila), fila)
    return sorted(unicas.values(), key=_orden)


def _clave_fila(fila: FilaTasa) -> tuple[object, ...]:
    """Devuelve la identidad de una fila para deduplicar."""
    return (
        fila.producto,
        fila.segmento,
        fila.tipo_tasa,
        fila.plazo_dias,
        fila.tasa_ea_desde,
        fila.tasa_ea_hasta,
        fila.tasa_mv_desde,
        fila.tasa_mv_hasta,
        fila.vigencia_desde,
        fila.vigencia_hasta,
        fila.fuente,
        fila.sha256_pdf,
        fila.fecha_extraccion,
    )


def _orden(fila: FilaTasa) -> tuple[object, ...]:
    """Clave de orden determinista de la tabla Gold."""
    return (
        fila.producto,
        fila.tipo_tasa,
        fila.segmento or "",
        fila.plazo_dias or 0,
        fila.vigencia_desde,
        fila.tasa_ea_desde,
        fila.tasa_ea_hasta,
    )


def _clave(texto: str) -> str:
    """Normaliza un texto a letras y dígitos en mayúsculas, sin tildes."""
    descompuesto = unicodedata.normalize("NFKD", texto)
    sin_tildes = "".join(
        caracter for caracter in descompuesto if not unicodedata.combining(caracter)
    )
    return re.sub(r"[^A-Za-z0-9]", "", sin_tildes).upper()


def _fecha_iso(valor: object, defecto: date) -> date:
    """Convierte una fecha ISO del TOML; si falta, devuelve el defecto."""
    if valor is None or valor == "":
        return defecto
    return date.fromisoformat(str(valor))


def _ruta(valor: object, defecto: Path) -> Path:
    """Resuelve una ruta del TOML contra la raíz del proyecto."""
    if not isinstance(valor, str) or not valor:
        return defecto
    candidata = Path(valor)
    return candidata if candidata.is_absolute() else PROJECT_ROOT / candidata


def _sha256(ruta: Path) -> str:
    """Devuelve la huella SHA-256 del archivo."""
    return hashlib.sha256(ruta.read_bytes()).hexdigest()


if __name__ == "__main__":  # pragma: no cover - entrada de línea de comandos
    raise SystemExit(main())
