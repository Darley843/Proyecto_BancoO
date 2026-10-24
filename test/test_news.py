"""Pruebas de configuracion y fuente curada de noticias."""

from __future__ import annotations

from datetime import date

import yaml

from banco_occidente_corpus.config import load_config


def test_config_noticias() -> None:
    """La configuracion expone las rutas y parametros de noticias esperados."""
    config = load_config()
    assert config.paths.news_source.name == "noticias"
    assert config.paths.news_prensa == config.paths.news_source / "prensa.yaml"
    assert config.paths.news_index.name == "_NOTICIAS.md"
    assert config.news.desde == "2025-01-01"
    assert config.news.hasta == ""
    assert config.news.prensa == "data/noticias/prensa.yaml"
    assert config.news.max_por_evento == 2
    assert config.news.max_oficiales == 40


def test_prensa_yaml_carga_y_estado_valido() -> None:
    """El registro tiene 15-20 fichas, campos minimos y estado valido."""
    config = load_config()
    rows = yaml.safe_load(config.paths.news_prensa.read_text(encoding="utf-8"))
    assert isinstance(rows, list)
    assert 15 <= len(rows) <= 20

    required = {
        "id",
        "fecha",
        "medio",
        "titulo",
        "url",
        "resumen",
        "temas",
        "relevancia",
        "estado",
    }
    ids: set[str] = set()
    for row in rows:
        assert required <= set(row)
        assert row["estado"] in {"pendiente", "verificado"}
        assert row["url"].startswith("https://")
        assert row["id"] not in ids
        assert len(row["resumen"].split()) >= 10
        fecha = row["fecha"].isoformat() if isinstance(row["fecha"], date) else str(row["fecha"])
        date.fromisoformat(fecha)
        ids.add(row["id"])


def test_readme_documenta_limites_y_verificacion() -> None:
    """El README explica el rango 15-20 y el paso de pendiente a verificado."""
    config = load_config()
    readme = (config.paths.news_source / "README.md").read_text(encoding="utf-8")
    assert "15 y 20" in readme
    assert "estado: pendiente" in readme
    assert "estado: verificado" in readme
    assert "Banco de Occidente de Colombia" in readme
