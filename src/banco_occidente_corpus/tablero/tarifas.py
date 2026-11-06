"""Extracción del tarifario PDF en filas del Tablero.

Las líneas del PDF siguen el patrón «concepto, valor y fecha de vigencia»
(`Cuota de Manejo Tarjeta Débito $16.700 20-nov-25`). El valor es el monto que
acompaña a `$`/`USD` o el porcentaje, nunca el primer número del concepto: así
`Prórroga (x 30 días) 1,5% + IVA` vale 1,5 y no 30. Una máquina de estados
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
#: Valor con símbolo (`$ 2.700`, `USD 70`) o porcentaje (`0,75%`).
_VALOR = re.compile(
    r"(?:(?P<simbolo>\$|\bUSD\b)\s*(?P<monto>\d[\d.,]*)|(?P<porcentaje>\d[\d.,]*)\s*%)",
    re.IGNORECASE,
)
#: Respaldo para líneas sin símbolo ni porcentaje (por ejemplo `* 0` o `Al Costo`).
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
    concepto_previo = ""
    lineas = [
        recortada
        for recortada in (linea.strip() for linea in texto.splitlines())
        if recortada and not recortada.startswith(("#", "|", "---"))
    ]
    for indice, limpia in enumerate(lineas):
        siguiente = lineas[indice + 1] if indice + 1 < len(lineas) else ""
        if _es_concepto_de_valor_suelto(limpia, siguiente):
            if _es_encabezado(limpia):
                categoria = _limpiar_encabezado(limpia)
                periodicidad = _periodicidad(limpia)
            concepto_previo = limpia
            continue

        encontrada = _interpretar_linea(limpia, concepto_previo)
        if encontrada is None:
            if _es_encabezado(limpia):
                categoria = _limpiar_encabezado(limpia)
                periodicidad = _periodicidad(limpia)
            if _es_concepto_suelto(limpia):
                concepto_previo = limpia
            continue

        concepto, valor, moneda, recargos, fecha = encontrada
        filas.append(
            Fila(
                concepto=concepto,
                categoria=categoria,
                valor=valor,
                moneda=moneda,
                recargos=recargos,
                periodicidad=periodicidad or _periodicidad(limpia),
                vigente_desde=fecha,
                origen="tarifario",
                pagina=pagina,
                fuente=fuente,
            )
        )
    return filas


def _interpretar_linea(
    linea: str, concepto_previo: str = ""
) -> tuple[str, str, str, str, str] | None:
    """Extrae concepto, valor, moneda, recargos y fecha ISO de una línea, si aplica.

    El concepto es el texto anterior al símbolo del valor, con sus paréntesis
    incluidos. Cuando el PDF deja el valor solo (`$ 225.000 + IVA`), el concepto
    es el de la línea anterior (`Chequera Serie 30`). Una línea cortada deja un
    concepto desbalanceado y no se publica: es preferible omitir la fila a
    guardar un valor equivocado.

    Args:
        linea: línea ya recortada del Markdown de Gold.
        concepto_previo: texto de la última línea que no produjo fila.

    Returns:
        `(concepto, valor, moneda, recargos, fecha)` o None si la línea no es
        una fila del tarifario.
    """
    encontrado = _ultimo_valor(linea)
    if encontrado is None:
        coincidencia = _FILA.match(linea)
        if not coincidencia:
            return None
        concepto = coincidencia.group("concepto").strip(" .;:-")
        valor = coincidencia.group("valor").strip(".,")
        moneda = "COP"
        cola = coincidencia.group("cola").strip()
    else:
        concepto = linea[: encontrado.start()].strip(" .;:-")
        if len(concepto) < 3:
            concepto = concepto_previo
        valor = (encontrado.group("monto") or encontrado.group("porcentaje") or "").strip(".,")
        moneda = _moneda(encontrado)
        cola = linea[encontrado.end() :].strip()

    if len(concepto) < 3 or concepto.count("(") != concepto.count(")"):
        return None
    if not any(caracter.isdigit() for caracter in valor):
        return None

    fecha = ""
    encontrada = _FECHA.search(cola)
    if encontrada:
        fecha = _fecha_iso(encontrada.group(0))
        cola = (cola[: encontrada.start()] + " " + cola[encontrada.end() :]).strip()
    recargos = " ".join(match.group(0) for match in _RECARGO.finditer(cola))
    return concepto, valor, moneda, recargos, fecha


def _ultimo_valor(linea: str) -> re.Match[str] | None:
    """Devuelve el último monto con símbolo o porcentaje de la línea.

    Se toma el último para que un rango (`De $1.000 M a $20.000 M $ 15.800`)
    deje como valor la tarifa final y no el extremo del rango.
    """
    ultimo: re.Match[str] | None = None
    for encontrado in _VALOR.finditer(linea):
        ultimo = encontrado
    return ultimo


def _moneda(encontrado: re.Match[str]) -> str:
    """Devuelve `%`, `USD` o `COP` según el símbolo que acompaña al valor."""
    if encontrado.group("porcentaje") is not None:
        return "%"
    if (encontrado.group("simbolo") or "").upper() == "USD":
        return "USD"
    return "COP"


def _es_encabezado(linea: str) -> bool:
    """Decide si una línea sin cifra actúa como encabezado de sección."""
    if len(linea) > 90 or linea.startswith(("*", "-", "•")):
        return False
    if _SUFIJO_ENCABEZADO.search(linea):
        return True
    return bool(re.fullmatch(r"[A-ZÁÉÍÓÚÑ][\wÁÉÍÓÚÑáéíóúñ /()*-]{3,70}", linea))


def _es_concepto_de_valor_suelto(linea: str, siguiente: str) -> bool:
    """Decide si la línea es el concepto del valor que el PDF dejó solo.

    `Chequera Serie 30` seguida de `$ 225.000 + IVA` no es una fila de 30: la
    cifra del nombre del producto no es una tarifa.
    """
    if not siguiente or _VALOR.match(siguiente) is None:
        return False
    return _VALOR.match(linea) is None and _es_concepto_suelto(linea)


def _es_concepto_suelto(linea: str) -> bool:
    """Decide si una línea sin valor puede ceder su texto como concepto.

    El PDF corta algunas filas en dos (`Chequera Serie 30` y `$ 225.000 + IVA`);
    la primera línea no tiene cifra y sirve de concepto para la siguiente. Se
    descartan notas, viñetas y fragmentos que empiezan en minúscula o con cifra.
    """
    if not 12 <= len(linea) <= 140:
        return False
    if not linea[:1].isupper():
        return False
    if linea.startswith(("*", "-", "•")):
        return False
    normalizada = linea.casefold()
    if normalizada.startswith("nota"):
        return False
    return not linea.startswith(("$", "USD", "Usd"))


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
