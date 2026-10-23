"""Demo offline: corre Bronze -> Silver -> Gold con una pagina local.

No toca la red ni el corpus real: escribe en .demo/ y muestra el resultado.
Sirve para validar el entorno antes de lanzar el scraping.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

from banco_occidente_corpus.config import Config, GoldConfig, Paths
from banco_occidente_corpus.extract import extract_all
from banco_occidente_corpus.gold import build_gold, load_corpus

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "test" / "fixtures" / "quienes_somos.html"
WORK = ROOT / ".demo"


def main() -> int:
    if not FIXTURE.exists():
        print(f"No encuentro el fixture: {FIXTURE}", file=sys.stderr)
        return 1

    if WORK.exists():
        shutil.rmtree(WORK)
    WORK.mkdir(parents=True)

    config = Config(
        gold=GoldConfig(boilerplate_min_docs=5, boilerplate_ratio=0.35),
        paths=Paths(
            root=WORK,
            raw=WORK / "data/raw",
            processed=WORK / "data/processed",
            gold=WORK / "data/gold",
        ),
    )
    config.paths.ensure()

    html = FIXTURE.read_text(encoding="utf-8")
    url = "https://www.bancodeoccidente.com.co/quienes-somos"
    destino = config.paths.raw_html / "demo.html"
    destino.write_text(html, encoding="utf-8")

    registro = {
        "url": url,
        "status": 200,
        "archivo": destino.relative_to(config.paths.root).as_posix(),
    }
    (config.paths.raw / "capture.jsonl").write_text(json.dumps(registro) + "\n", encoding="utf-8")

    silver = extract_all(config)
    gold = build_gold(config)

    print(f"Bronze : {destino.relative_to(ROOT)}")
    print(f"Silver : {len(silver)} documento(s)")
    print(f"Gold   : {len(gold)} documento(s)")
    print()
    for row in load_corpus(config):
        path = config.paths.root / row["archivo"]
        print(f"--- {path.relative_to(ROOT)} ---")
        print(path.read_text(encoding="utf-8"))
    print(f"Todo en: {WORK.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
