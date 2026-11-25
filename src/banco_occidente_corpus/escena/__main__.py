"""CLI de la escena: genera el JSON de respaldo sin abrir puertos ni usar red.

```text
uv run python -m banco_occidente_corpus.escena --proyectado
uv run python -m banco_occidente_corpus.escena --nucleo
uv run python -m banco_occidente_corpus.escena --perfil verde_computador
```

`--proyectado` escribe `data/escena/proyectado.json` con la escena completa
(fase 1, negociación y cierre) y `--nucleo` escribe `data/escena/nucleo.json` con
Don Gota, Pana y el auditor. El comando no necesita `DEEPSEEK_API_KEY` ni Ollama:
la negociación cae a la política determinista.

Las pruebas viven en ``test/test_escena_cli.py``.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from ..tablero.tasas import TasaNoDisponible
from .perfiles import perfil_seguro
from .servicio import (
    RUTA_SALIDA,
    construir_escena,
    construir_nucleo,
    guardar_escena,
    resumen_escena,
)

#: Código de salida cuando faltan datos (tasa o usura) para construir la escena.
SALIDA_SIN_DATOS = 3


def _analizador() -> argparse.ArgumentParser:
    """Arma el analizador de argumentos del CLI."""
    analizador = argparse.ArgumentParser(
        prog="python -m banco_occidente_corpus.escena",
        description="Genera la escena de respaldo de Pana vs. el gota a gota.",
    )
    grupo = analizador.add_mutually_exclusive_group(required=True)
    grupo.add_argument(
        "--proyectado",
        action="store_true",
        help="escribe data/escena/proyectado.json con la escena completa",
    )
    grupo.add_argument(
        "--nucleo",
        action="store_true",
        help="escribe data/escena/nucleo.json con Don Gota, Pana y el auditor",
    )
    analizador.add_argument(
        "--perfil",
        default=None,
        help="id del perfil seguro; por defecto el de [seguro] por_defecto",
    )
    analizador.add_argument(
        "--salida",
        default=RUTA_SALIDA,
        help=f"carpeta de salida (por defecto {RUTA_SALIDA})",
    )
    return analizador


def main(argv: Sequence[str] | None = None) -> int:
    """Genera la escena pedida y escribe el JSON de respaldo.

    Args:
        argv: argumentos de la línea de comandos; por defecto los del proceso.

    Returns:
        ``0`` si escribió la escena, ``2`` si los argumentos o el perfil no son
        válidos y ``3`` si faltan datos para calcularla.
    """
    argumentos = _analizador().parse_args(argv)
    try:
        perfil = perfil_seguro(argumentos.perfil)
        if argumentos.nucleo:
            escena = construir_nucleo(perfil)
            nombre = "nucleo.json"
        else:
            escena = construir_escena(
                perfil,
                modo="proyectado",
                incluir_negociacion=True,
                entorno={"SUCURSAL_DEMO": "1"},
            )
            nombre = "proyectado.json"
        ruta = guardar_escena(escena, Path(argumentos.salida) / nombre)
    except TasaNoDisponible as exc:
        print(f"No hay datos para la escena: {exc}", file=sys.stderr)
        return SALIDA_SIN_DATOS
    except ValueError as exc:
        print(f"No se pudo construir la escena: {exc}", file=sys.stderr)
        return 2
    print(resumen_escena(escena))
    print(f"Escrito en {ruta}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
