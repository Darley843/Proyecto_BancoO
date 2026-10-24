"""Valida un borrador de conocimiento sin escribir en data/knowledge.

Uso:
    uv run python .opencode/skills/semantic-extraction/scripts/validate.py \
        data/knowledge/draft-identidad.jsonl

Sale con codigo 1 si el borrador no cumple el esquema o la evidencia.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from banco_occidente_corpus.config import load_config
from banco_occidente_corpus.knowledge import merge_draft


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("file", type=Path, help="JSONL candidato")
    args = parser.parse_args()

    if not args.file.exists():
        print(f"No existe: {args.file}", file=sys.stderr)
        return 2

    config = load_config()
    records, errors, warnings = merge_draft(config, args.file)

    total = sum(len(rows) for rows in records.values())
    print(f"Borrador : {args.file}")
    print(f"Registros: {total} (entidades, hechos y relaciones tras fusionar)")

    for warning in warnings[:10]:
        print(f"AVISO  {warning}")
    for error in errors[:30]:
        print(f"ERROR  {error}")
    if len(errors) > 30:
        print(f"... y {len(errors) - 30} errores mas")

    if errors:
        print(f"\nRESULTADO: FALLA ({len(errors)} errores)")
        return 1

    print("\nRESULTADO: OK (borrador listo para --merge)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
