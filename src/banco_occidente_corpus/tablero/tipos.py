"""Esquema único del Tablero y escritura determinista del CSV."""

from __future__ import annotations

import csv
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal, cast

from ..config import Config

#: Columnas del CSV, en el orden exacto del contrato.
COLUMNAS: tuple[str, ...] = (
    "concepto",
    "categoria",
    "valor",
    "moneda",
    "recargos",
    "periodicidad",
    "vigente_desde",
    "origen",
    "pagina",
    "fuente",
)
#: Orígenes admitidos de una fila.
Origen = Literal["tarifario", "tabla_web"]


@dataclass(frozen=True, slots=True)
class Fila:
    """Una cifra del Tablero con su categoría, vigencia y trazabilidad."""

    concepto: str
    categoria: str
    valor: str
    moneda: str
    recargos: str
    periodicidad: str
    vigente_desde: str
    origen: Origen
    pagina: str
    fuente: str

    def como_dict(self) -> dict[str, str]:
        """Devuelve la fila como diccionario con las columnas del CSV."""
        return asdict(self)


def ruta_tablero(config: Config) -> Path:
    """Devuelve `data/estructurados/tablero.csv`."""
    return config.paths.root / "data" / "estructurados" / "tablero.csv"


def escribir_filas(ruta: Path, filas: list[Fila]) -> int:
    """Escribe las filas ordenadas y sin duplicados exactos; devuelve el total."""
    unicas = sorted(set(filas), key=_orden)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with ruta.open("w", encoding="utf-8", newline="") as fh:
        escritor = csv.DictWriter(fh, fieldnames=COLUMNAS, lineterminator="\n")
        escritor.writeheader()
        for fila in unicas:
            escritor.writerow(fila.como_dict())
    return len(unicas)


def leer_filas(ruta: Path) -> list[Fila]:
    """Lee el CSV del Tablero y devuelve las filas tipadas."""
    if not ruta.exists():
        return []
    filas: list[Fila] = []
    with ruta.open(encoding="utf-8", newline="") as fh:
        for fila in csv.DictReader(fh):
            filas.append(
                Fila(
                    concepto=fila["concepto"],
                    categoria=fila["categoria"],
                    valor=fila["valor"],
                    moneda=fila["moneda"],
                    recargos=fila["recargos"],
                    periodicidad=fila["periodicidad"],
                    vigente_desde=fila["vigente_desde"],
                    origen=cast(Origen, fila["origen"]),
                    pagina=fila["pagina"],
                    fuente=fila["fuente"],
                )
            )
    return filas


def _orden(fila: Fila) -> tuple[str, ...]:
    """Clave de orden determinista: origen, página y concepto antes del valor."""
    return (
        fila.origen,
        fila.pagina,
        fila.concepto,
        fila.categoria,
        fila.valor,
        fila.moneda,
        fila.periodicidad,
        fila.vigente_desde,
        fila.fuente,
    )
