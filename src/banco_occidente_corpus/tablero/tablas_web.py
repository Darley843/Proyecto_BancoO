"""Tablas Markdown de Gold convertidas en filas del Tablero.

El lector respeta los pipes escapados (`\\|`) y descarta las filas separadoras.
Cada adaptador conoce la forma de su página: asistencias con columnas por
franquicia, períodos de carencia, tabla de hogar, promociones y proyectos.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from ..config import Config
from ..utils import read_jsonl
from .tipos import Fila

#: Valores que no son una cifra y no generan fila.
_NO_CIFRA = frozenset({"ilimitado", "no cubre", "n/a", "na", "", "-"})
#: Moneda o monto al inicio de una celda.
_VALOR = re.compile(r"(?P<moneda>USD|EUR|COP|\$)?\s*(?P<valor>\d[\d.,]*)", re.IGNORECASE)
#: Porcentaje de una promoción.
_PORCENTAJE = re.compile(r"(?P<valor>\d{1,3})\s*%")
#: Precio «desde $407,027,630».
_PRECIO = re.compile(r"desde\s*\$?\s*(?P<valor>\d[\d.,]{5,})", re.IGNORECASE)
#: Días de carencia.
_DIAS = re.compile(r"(?P<valor>\d+)\s*d[ií]as", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class Tabla:
    """Tabla Markdown ya separada en encabezados y filas."""

    encabezados: tuple[str, ...]
    filas: tuple[tuple[str, ...], ...]


def leer_tablas(texto: str) -> list[Tabla]:
    """Extrae las tablas Markdown del texto, respetando pipes escapados."""
    tablas: list[Tabla] = []
    bloque: list[str] = []

    def cerrar() -> None:
        if bloque:
            tabla = _construir_tabla(bloque)
            if tabla is not None:
                tablas.append(tabla)
            bloque.clear()

    for linea in texto.splitlines():
        if linea.strip().startswith("|"):
            bloque.append(linea)
        else:
            cerrar()
    cerrar()
    return tablas


def viajes_nacionales(texto: str, pagina: str, fuente: str) -> list[Fila]:
    """Asistencias de viajes (nacionales o al exterior), una fila por franquicia.

    La tabla internacional trae una columna extra de numeración
    (`| Asistencias | | Visa | Mastercard |`), así que el concepto es la celda
    inmediatamente anterior a la columna de la franquicia.
    """
    categoria = (
        "asistencia de viajes nacionales"
        if "nacional" in fuente
        else "asistencia de viajes al exterior"
    )
    filas: list[Fila] = []
    for tabla in leer_tablas(texto):
        columnas = [encabezado.casefold() for encabezado in tabla.encabezados]
        if "visa" not in columnas:
            continue
        indice_concepto = columnas.index("visa") - 1
        if indice_concepto < 0:
            continue
        for franquicia in ("visa", "mastercard"):
            if franquicia not in columnas:
                continue
            indice_franquicia = columnas.index(franquicia)
            for fila in tabla.filas:
                if len(fila) <= max(indice_concepto, indice_franquicia):
                    continue
                concepto = fila[indice_concepto].strip()
                celda = fila[indice_franquicia].strip()
                if not concepto or celda.casefold() in _NO_CIFRA:
                    continue
                encontrado = _VALOR.search(celda)
                if not encontrado:
                    continue
                filas.append(
                    Fila(
                        concepto=f"{concepto} ({franquicia.title()})",
                        categoria=categoria,
                        valor=encontrado.group("valor").strip(".,"),
                        moneda=(encontrado.group("moneda") or "USD").upper().replace("$", "COP"),
                        recargos="",
                        periodicidad="por día" if "día" in celda.casefold() else "por viaje",
                        vigente_desde="",
                        origen="tabla_web",
                        pagina=pagina,
                        fuente=fuente,
                    )
                )
    return filas


def cuota_protegida(texto: str, pagina: str, fuente: str) -> list[Fila]:
    """Períodos de carencia de Cuota Protegida (desempleo y enfermedades)."""
    filas: list[Fila] = []
    for tabla in leer_tablas(texto):
        columnas = [encabezado.casefold() for encabezado in tabla.encabezados]
        if not any("carencia" in columna for columna in columnas):
            continue
        for fila in tabla.filas:
            if len(fila) < 3:
                continue
            concepto = fila[0].strip()
            encontrado = _DIAS.search(fila[-1])
            if not concepto or not encontrado:
                continue
            filas.append(
                Fila(
                    concepto=concepto,
                    categoria="cuota protegida",
                    valor=encontrado.group("valor"),
                    moneda="",
                    recargos="",
                    periodicidad="días",
                    vigente_desde="",
                    origen="tabla_web",
                    pagina=pagina,
                    fuente=fuente,
                )
            )
    return filas


def asistencia_vehicular(texto: str, pagina: str, fuente: str) -> list[Fila]:
    """Tabla de hogar de la página de asistencia vehicular."""
    filas: list[Fila] = []
    for tabla in leer_tablas(texto):
        columnas = [encabezado.casefold() for encabezado in tabla.encabezados]
        if not any("asistencia" in columna for columna in columnas):
            continue
        for fila in tabla.filas:
            if len(fila) < 3:
                continue
            concepto = fila[1].strip()
            encontrado = _VALOR.search(fila[2])
            if not concepto or not encontrado:
                continue
            filas.append(
                Fila(
                    concepto=concepto,
                    categoria="asistencia vehicular (hogar)",
                    valor=encontrado.group("valor").strip(".,"),
                    moneda=(encontrado.group("moneda") or "USD").upper().replace("$", "COP"),
                    recargos="",
                    periodicidad="por evento",
                    vigente_desde="",
                    origen="tabla_web",
                    pagina=pagina,
                    fuente=fuente,
                )
            )
    return filas


def promociones(texto: str, pagina: str, fuente: str) -> list[Fila]:
    """Descuentos declarados en la página de promociones."""
    filas: list[Fila] = []
    for tabla in leer_tablas(texto):
        for fila in tabla.filas:
            texto_fila = " ".join(celda.strip() for celda in fila if celda.strip())
            if "%" not in texto_fila:
                continue
            if "descuento" not in texto_fila.casefold() and "off" not in texto_fila.casefold():
                continue
            encontrado = _PORCENTAJE.search(texto_fila)
            if not encontrado:
                continue
            filas.append(
                Fila(
                    concepto=_recortar(texto_fila, 160),
                    categoria="promociones",
                    valor=encontrado.group("valor"),
                    moneda="%",
                    recargos="",
                    periodicidad="",
                    vigente_desde="",
                    origen="tabla_web",
                    pagina=pagina,
                    fuente=fuente,
                )
            )
    return filas


def proyectos_vivienda(texto: str, pagina: str, fuente: str) -> list[Fila]:
    """Precios «desde» de los proyectos de vivienda, con el encabezado vigente."""
    filas: list[Fila] = []
    encabezado = ""
    for linea in texto.splitlines():
        if linea.startswith("## "):
            encabezado = linea[3:].strip()
            continue
        if not linea.strip().startswith("|"):
            continue
        encontrado = _PRECIO.search(linea)
        if not encontrado:
            continue
        concepto = encabezado or _recortar(linea.strip("| "), 100)
        filas.append(
            Fila(
                concepto=concepto,
                categoria="proyectos de vivienda",
                valor=encontrado.group("valor"),
                moneda="COP",
                recargos="",
                periodicidad="",
                vigente_desde="",
                origen="tabla_web",
                pagina=pagina,
                fuente=fuente,
            )
        )
    return filas


#: Páginas de Gold que alimentan el Tablero, con su adaptador.
PAGINAS: tuple[tuple[str, Callable[[str, str, str], list[Fila]]], ...] = (
    (
        "https://www.bancodeoccidente.com.co/asistencias-en-viajes-nacionales",
        viajes_nacionales,
    ),
    (
        "https://www.bancodeoccidente.com.co/tarjetas-credito/asistencias-tarjetas-de-credito",
        viajes_nacionales,
    ),
    (
        "https://www.bancodeoccidente.com.co/seguros/libranza/cuota-protegida",
        cuota_protegida,
    ),
    (
        "https://www.bancodeoccidente.com.co/asistencia-vehicular",
        asistencia_vehicular,
    ),
    (
        "https://www.bancodeoccidente.com.co/tarjetas-credito/promociones",
        promociones,
    ),
    (
        "https://www.bancodeoccidente.com.co/proyectos-de-vivienda",
        proyectos_vivienda,
    ),
)


def extraer_tablas_web(config: Config) -> list[Fila]:
    """Recorre las páginas conocidas y devuelve sus filas `tabla_web`."""
    rutas = _rutas_por_fuente(config)
    filas: list[Fila] = []
    for fuente, adaptador in PAGINAS:
        ruta = rutas.get(fuente)
        if ruta is None or not ruta.exists():
            continue
        texto = ruta.read_text(encoding="utf-8", errors="replace")
        filas.extend(adaptador(texto, _relativa(config, ruta), fuente))
    return filas


def _rutas_por_fuente(config: Config) -> dict[str, Path]:
    """Mapea URL pública al archivo Gold correspondiente."""
    rutas: dict[str, Path] = {}
    for indice in (config.paths.corpus_file, config.paths.documents_index):
        for fila in read_jsonl(indice):
            fuente = str(fila.get("fuente", "")).strip()
            archivo = str(fila.get("archivo", "")).strip()
            if fuente and archivo:
                rutas[fuente] = config.paths.root / archivo
    return rutas


def _relativa(config: Config, ruta: Path) -> str:
    """Devuelve la ruta relativa al repositorio, con separador `/`."""
    try:
        return ruta.relative_to(config.paths.root).as_posix()
    except ValueError:
        return ruta.as_posix()


def _construir_tabla(lineas: Sequence[str]) -> Tabla | None:
    """Convierte un bloque de líneas `|...|` en una tabla tipada."""
    filas = [_celdas(linea) for linea in lineas]
    if not filas:
        return None
    separador = len(filas) > 1 and all(_es_separador(celda) for celda in filas[1])
    encabezados = filas[0]
    cuerpo = filas[2:] if separador else filas[1:]
    if not encabezados or not cuerpo:
        return None
    return Tabla(encabezados=tuple(encabezados), filas=tuple(tuple(fila) for fila in cuerpo))


def _celdas(linea: str) -> list[str]:
    """Parte una fila Markdown en celdas, respetando `\\|`."""
    texto = linea.strip()
    if texto.startswith("|"):
        texto = texto[1:]
    if texto.endswith("|") and not texto.endswith("\\|"):
        texto = texto[:-1]

    celdas: list[str] = []
    actual: list[str] = []
    escapado = False
    for caracter in texto:
        if escapado:
            actual.append(caracter)
            escapado = False
        elif caracter == "\\":
            escapado = True
        elif caracter == "|":
            celdas.append("".join(actual).strip())
            actual = []
        else:
            actual.append(caracter)
    celdas.append("".join(actual).strip())
    return celdas


def _es_separador(celda: str) -> bool:
    """Indica si la celda pertenece a la fila separadora de la tabla."""
    return bool(re.fullmatch(r":?-{3,}:?", celda.strip()))


def _recortar(texto: str, limite: int) -> str:
    """Recorta un texto largo conservando palabras completas."""
    limpio = " ".join(texto.replace("**", "").split())
    if len(limpio) <= limite:
        return limpio
    return limpio[:limite].rsplit(" ", 1)[0] + "…"
