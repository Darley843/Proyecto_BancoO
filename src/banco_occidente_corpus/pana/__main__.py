"""Guarda muestras de Pana y sus tarjetas con datos inventados.

Uso: ``uv run python -m banco_occidente_corpus.pana --muestras <carpeta>``.

Es la única parte del paquete que escribe en disco, y solo cuando alguien lo
pide: sirve para revisar el diseño, para las capturas del PR y para subir la
foto de perfil al número de prueba en Meta. Los datos son ficticios.
"""

from __future__ import annotations

import argparse
import sys
from decimal import Decimal
from pathlib import Path

from .personaje import EXPRESIONES, dibujar_pana, foto_de_perfil
from .tarjetas import (
    DatosDiagnostico,
    DatosEscenario,
    FotoEscenario,
    tarjeta_diagnostico,
    tarjeta_escenario,
)

EJEMPLO_DIAGNOSTICO = DatosDiagnostico(
    producto="Portátil",
    monto=Decimal(3_000_000),
    plazo_meses=24,
    semaforo="amarillo",
    cuota_min=Decimal(150_000),
    cuota_max=Decimal(170_000),
    razon="El pago se lleva entre 30 % y 40 % de lo que te queda libre cada mes.",
    tasa_mensual_pct=Decimal("1.9"),
    tasa_vigencia="nov. 2026",
    tasa_fuente="Tablero de tasas",
)
"""Diagnóstico ficticio de la demo (Camila y el portátil)."""

EJEMPLO_ESCENARIO = DatosEscenario(
    pregunta="¿Y si lo pagas en 36 meses?",
    antes=FotoEscenario(
        plazo_meses=24, semaforo="amarillo", cuota_min=Decimal(150_000), cuota_max=Decimal(170_000)
    ),
    despues=FotoEscenario(
        plazo_meses=36, semaforo="verde", cuota_min=Decimal(110_000), cuota_max=Decimal(125_000)
    ),
    nota="Pagas menos al mes, pero más en total. Tu diagnóstico original no cambió.",
)
"""Escenario ficticio de la demo."""


def guardar_muestras(carpeta: Path) -> list[Path]:
    """Escribe la foto de perfil, las tres caras y las dos tarjetas.

    Args:
        carpeta: carpeta de destino (se crea si no existe).

    Returns:
        Rutas de los archivos escritos.
    """
    carpeta.mkdir(parents=True, exist_ok=True)
    escritos: list[Path] = []

    perfil = carpeta / "pana-perfil.png"
    perfil.write_bytes(foto_de_perfil())
    escritos.append(perfil)

    for expresion in EXPRESIONES:
        ruta = carpeta / f"pana-{expresion}.png"
        dibujar_pana(expresion, 512).save(ruta, format="PNG")
        escritos.append(ruta)

    for nombre, contenido in (
        ("tarjeta-diagnostico.png", tarjeta_diagnostico(EJEMPLO_DIAGNOSTICO)),
        ("tarjeta-escenario.png", tarjeta_escenario(EJEMPLO_ESCENARIO)),
    ):
        ruta = carpeta / nombre
        ruta.write_bytes(contenido)
        escritos.append(ruta)
    return escritos


def main(argv: list[str] | None = None) -> int:
    """Punto de entrada de la línea de comandos.

    Args:
        argv: argumentos (por defecto, los del proceso).

    Returns:
        Código de salida (0 si todo salió bien).
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--muestras", type=Path, required=True, help="carpeta de destino")
    args = parser.parse_args(argv)
    for ruta in guardar_muestras(args.muestras):
        print(ruta)
    return 0


if __name__ == "__main__":
    sys.exit(main())
