"""Extracción del tarifario PDF en filas del Tablero.

Las líneas del PDF siguen el patrón «concepto, valor y fecha de vigencia»
(`Cuota de Manejo Tarjeta Débito $16.700 20-nov-25`). Una máquina de estados
arrastra la categoría y la periodicidad desde los encabezados de sección; si una
línea no trae fecha, la fila se conserva con vigencia vacía.
"""

from __future__ import annotations

import re

from .tipos import Fila

#: Meses abreviados del tarifario, en minúsculas.
MESES: dict[str, str] = {
    "ene": "01",
    "feb": "02",
    "mar": "03",
    "abr": "04",
    "may": "05",
    "jun": "06",
    "jul": "07",
    "ago": "08",
    "sep": "09",
    "set": "09",
    "oct": "10",
    "nov": "11",
    "dic": "12",
}
#: Patrón «concepto $valor [cola con recargos y fecha]».
_FILA = re.compile(
    r"^(?P<concepto>.*?)\s+\$?\s*(?P<valor>\d[\d.,]*)\s*(?P<cola>.*)$",
    re.IGNORECASE,
)
#: Fecha de vigencia `20-nov-25`.
_FECHA = re.compile(r"\b(?P<dia>\d{1,2})-(?P<mes>[a-záéíóú]{3})-(?P<anio>\d{2})\b", re.IGNORECASE)
#: Recargos `+ IVA`, `+ Seguro2`.
_RECARGO = re.compile(r"\+\s*(?P<recargo>[A-Za-zÁÉÍÓÚÑáéíóúñ0-9]+)")
#: Sufijo que convierte un encabezado en categoría.
_SUFIJO_ENCABEZADO = re.compile(
    r"\s*(comisi[oó]n vigente desde|comisi[oó]n|vigente desde)\s*$", re.IGNORECASE
)
#: Periodicidades reconocidas en el texto.
_PERIODICIDADES: tuple[tuple[str, str], ...] = (
    ("trimestre anticipado", "trimestral"),
    ("trimestral", "trimestral"),
    ("mensual", "mensual"),
    ("anual", "anual"),
    ("por evento", "por evento"),
    ("diario", "diaria"),
    ("diaria", "diaria"),
)
#: Valores que no son cifras y no deben convertirse en filas.
_NO_CIFRA = frozenset({"ilimitado", "no cubre", "n/a", "na"})


def extraer_tarifario(texto: str, pagina: str, fuente: str) -> list[Fila]:
    """Convierte el Markdown del tarifario en filas del Tablero.

    Args:
        texto: cuerpo Markdown del documento de Gold.
        pagina: ruta relativa del archivo Gold.
        fuente: URL pública del tarifario.

    Returns:
        Filas con origen `tarifario`, en el orden en que aparecen.
    """
    filas: list[Fila] = []
    categoria = ""
    periodicidad = ""
    for linea in texto.splitlines():
        limpia = linea.strip()
        if not limpia or limpia.startswith(("#", "|", "---")):
            continue

        encontrada = _interpretar_linea(limpia)
        if encontrada is None:
            if _es_encabezado(limpia):
                categoria = _limpiar_encabezado(limpia)
                periodicidad = _periodicidad(limpia)
            continue

        concepto, valor, recargos, fecha = encontrada
        filas.append(
            Fila(
                concepto=concepto,
                categoria=categoria,
                valor=valor,
                moneda="COP",
                recargos=recargos,
                periodicidad=periodicidad or _periodicidad(limpia),
                vigente_desde=fecha,
                origen="tarifario",
                pagina=pagina,
                fuente=fuente,
            )
        )
    return filas


def _interpretar_linea(linea: str) -> tuple[str, str, str, str] | None:
    """Extrae concepto, valor, recargos y fecha ISO de una línea, si aplica."""
    coincidencia = _FILA.match(linea)
    if not coincidencia:
        return None
    concepto = coincidencia.group("concepto").strip(" .;:-")
    if not concepto or len(concepto) < 3:
        return None
    valor = coincidencia.group("valor").strip(".,")
    if not any(caracter.isdigit() for caracter in valor):
        return None

    cola = coincidencia.group("cola").strip()
    fecha = ""
    encontrada = _FECHA.search(cola)
    if encontrada:
        fecha = _fecha_iso(encontrada.group(0))
        cola = (cola[: encontrada.start()] + " " + cola[encontrada.end() :]).strip()
    recargos = " ".join(match.group(0) for match in _RECARGO.finditer(cola))
    return concepto, valor, recargos, fecha


def _es_encabezado(linea: str) -> bool:
    """Decide si una línea sin cifra actúa como encabezado de sección."""
    if len(linea) > 90 or linea.startswith(("*", "-", "•")):
        return False
    if _SUFIJO_ENCABEZADO.search(linea):
        return True
    return bool(re.fullmatch(r"[A-ZÁÉÍÓÚÑ][\wÁÉÍÓÚÑáéíóúñ /()*-]{3,70}", linea))


def _limpiar_encabezado(linea: str) -> str:
    """Quita el sufijo «Comisión Vigente desde» y normaliza espacios."""
    return _SUFIJO_ENCABEZADO.sub("", linea).strip(" .")


def _periodicidad(texto: str) -> str:
    """Devuelve la periodicidad declarada en el texto, si la hay."""
    normalizado = texto.casefold()
    for clave, valor in _PERIODICIDADES:
        if clave in normalizado:
            return valor
    return ""


def _fecha_iso(fecha: str) -> str:
    """Convierte `20-nov-25` a `2025-11-20`; si no se puede, devuelve vacío."""
    if not fecha:
        return ""
    partes = fecha.split("-")
    if len(partes) != 3:
        return ""
    dia, mes, anio = partes
    numero_mes = MESES.get(mes.casefold())
    if numero_mes is None:
        return ""
    return f"20{anio}-{numero_mes}-{int(dia):02d}"
