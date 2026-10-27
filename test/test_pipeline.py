"""Pruebas del pipeline: descubrimiento, limpieza y capa Gold."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from banco_occidente_corpus.checklist import coverage, evaluate
from banco_occidente_corpus.config import Config, GoldConfig, Paths, SiteConfig
from banco_occidente_corpus.dedupe import find_boilerplate, normalize_line, strip_boilerplate
from banco_occidente_corpus.discover import (
    is_capture_target,
    is_document,
    normalize_url,
    parse_robots,
    parse_sitemap,
)
from banco_occidente_corpus.extract import extract_all, extract_page
from banco_occidente_corpus.gold import build_gold, render_document
from banco_occidente_corpus.section import classify
from banco_occidente_corpus.utils import page_slug, read_jsonl, sha256_text

FIXTURES = Path(__file__).parent / "fixtures"


# ---------------------------------------------------------------- descubrir


def test_parse_sitemap_index() -> None:
    """Parse sitemap index."""
    kind, locs = parse_sitemap((FIXTURES / "sitemap_index.xml").read_text(encoding="utf-8"))
    assert kind == "sitemapindex"
    assert len(locs) == 2
    assert "&groupId" in locs[0]


def test_parse_sitemap_urlset() -> None:
    """Parse sitemap urlset."""
    kind, locs = parse_sitemap((FIXTURES / "sitemap_child.xml").read_text(encoding="utf-8"))
    assert kind == "urlset"
    assert "https://www.bancodeoccidente.com.co/personas" in locs


def test_parse_sitemap_invalid() -> None:
    """Parse sitemap invalid."""
    assert parse_sitemap("<html>no es un sitemap</html>") == ("", [])
    assert parse_sitemap("") == ("", [])


def test_parse_robots() -> None:
    """Parse robots."""
    text = "User-agent: *\nDisallow: /portaltransaccional/\nCrawl-delay: 2\nSitemap: https://x.co/sitemap.xml\n"
    parser, delay, sitemaps = parse_robots(text)
    assert delay == 2.0
    assert sitemaps == ["https://x.co/sitemap.xml"]
    assert not parser.can_fetch("TAAML-bot/1.0", "https://x.co/portaltransaccional/login")
    assert parser.can_fetch("TAAML-bot/1.0", "https://x.co/personas")


def test_normalize_url_quita_fragmento() -> None:
    """Normalize url quita fragmento."""
    assert normalize_url("https://www.bancodeoccidente.com.co/a#top") == (
        "https://www.bancodeoccidente.com.co/a"
    )


def test_normalize_url_quita_prefijo_friendly_url() -> None:
    """Normalize url quita prefijo friendly url."""
    # Liferay publica /w/<slug> en el sitemap pero sirve /<slug>.
    assert normalize_url("https://www.bancodeoccidente.com.co/w/cuenta-de-ahorros") == (
        "https://www.bancodeoccidente.com.co/cuenta-de-ahorros"
    )
    assert normalize_url("https://www.bancodeoccidente.com.co/w/") == (
        "https://www.bancodeoccidente.com.co/"
    )


def test_filtros_de_alcance(config: Config) -> None:
    """Filtros de alcance."""
    assert is_capture_target("https://www.bancodeoccidente.com.co/quienes-somos", config)
    assert not is_capture_target(
        "https://www.bancodeoccidente.com.co/portaltransaccional/x", config
    )
    assert not is_capture_target("https://otro-sitio.com/personas", config)
    assert not is_capture_target("https://www.bancodeoccidente.com.co/logo.png", config)
    assert is_document("https://www.bancodeoccidente.com.co/documents/catalogo.pdf", config)


# ---------------------------------------------------------------- clasificar


@pytest.mark.parametrize(
    ("url", "esperado"),
    [
        ("https://x.co/quienes-somos", "identidad"),
        ("https://x.co/personas/cuentas-de-ahorro", "oferta"),
        ("https://x.co/sala-de-prensa/noticia-1", "presencia"),
        ("https://x.co/inversionistas/informe-anual", "datos"),
        ("https://x.co/politica-de-privacidad", "legal"),
        ("https://x.co/sucursales", "atencion"),
        ("https://x.co/xyz", "otros"),
    ],
)
def test_classify(url: str, esperado: str) -> None:
    """Classify."""
    assert classify(url) == esperado


# ---------------------------------------------------------------- extraer


def test_extract_page_quita_navegacion_y_footer() -> None:
    """Extract page quita navegacion y footer."""
    html = (FIXTURES / "quienes_somos.html").read_text(encoding="utf-8")
    page = extract_page(html, "https://www.bancodeoccidente.com.co/quienes-somos")
    assert page.title
    assert "Mision" in page.markdown or "Misi" in page.markdown
    assert "fundada en 1965" in page.markdown
    assert "NIT 890.300.279-4" not in page.markdown
    assert "Usamos cookies" not in page.markdown
    assert page.section == "identidad"


def test_boilerplate_detecta_footer_repetido() -> None:
    """Boilerplate detecta footer repetido."""
    footer = "Vigilado Superintendencia Financiera de Colombia"
    docs = [[f"Contenido unico {i}", "Mision del banco", footer] for i in range(6)]
    boilerplate = find_boilerplate(docs, min_docs=5, ratio=0.35)
    assert normalize_line(footer) in boilerplate
    assert normalize_line("Mision del banco") in boilerplate  # tambien se repite


def test_strip_boilerplate_conserva_cuerpo() -> None:
    """Strip boilerplate conserva cuerpo."""
    text = "# Titulo\n\nCuerpo util de la pagina.\n\nFooter repetido\n\n---"
    limpio = strip_boilerplate(text, {normalize_line("Footer repetido")})
    assert "Cuerpo util" in limpio
    assert "Footer repetido" not in limpio


def test_pagina_corta_no_rompe() -> None:
    """Pagina corta no rompe."""
    page = extract_page("<html><body><p>hola</p></body></html>", "https://x.co/a")
    assert page.markdown.strip() == "hola" or page.markdown == ""


def test_nuestro_banco_conserva_la_cronologia() -> None:
    """Nuestro banco conserva la cronologia."""
    # Arrange: recorte del Bronze real; la cronologia vive en acordeones
    html = (FIXTURES / "nuestro_banco.html").read_text(encoding="utf-8")
    url = "https://www.bancodeoccidente.com.co/quienes-somos/nuestro-banco"

    # Act
    page = extract_page(html, url)

    # Assert
    assert page.method == "trafilatura"
    assert "Década de los 60s" in page.markdown
    assert "1965" in page.markdown
    assert "3 de mayo" in page.markdown
    assert "Década de los 70s" in page.markdown


def test_inversionistas_conserva_la_junta_directiva() -> None:
    """Inversionistas conserva la junta directiva."""
    # Arrange: recorte del Bronze real; las fichas viven en acordeones
    html = (FIXTURES / "informacion_inversionistas.html").read_text(encoding="utf-8")
    url = "https://www.bancodeoccidente.com.co/quienes-somos/informacion-inversionistas"

    # Act
    page = extract_page(html, url)

    # Assert
    assert page.method == "trafilatura"
    assert "Gerardo Silva Castro" in page.markdown
    assert "Junta Directiva" in page.markdown  # "Presidente de la Junta Directiva"
    assert "Universidad Javeriana" in page.markdown  # la ficha, no solo el nombre
    assert "Texto de pruebas" not in page.markdown  # no se cuela el acordeon de ejemplo


# ---------------------------------------------------------------- gold


def test_page_slug_es_estable() -> None:
    """Page slug es estable."""
    url = "https://www.bancodeoccidente.com.co/quienes-somos"
    assert page_slug(url, "Quienes somos") == page_slug(url, "Quienes somos")
    assert page_slug(url, "Quienes somos").startswith("quienes-somos-")


def test_render_document_tiene_frontmatter() -> None:
    """Render document tiene frontmatter."""
    doc = render_document(
        {"fuente": "https://x.co/a", "titulo": "A", "seccion": "identidad", "tokens": 10},
        "# A\n\nContenido",
    )
    assert doc.startswith("---\n")
    assert "fuente: https://x.co/a" in doc
    assert doc.rstrip().endswith("Contenido")


def test_pipeline_completo(tmp_path: Path) -> None:
    """Bronze -> Silver -> Gold sin red, con la pagina de fixture."""
    config = make_config(tmp_path)
    html = (FIXTURES / "quienes_somos.html").read_text(encoding="utf-8")
    url = "https://www.bancodeoccidente.com.co/quienes-somos"

    raw_file = config.paths.raw_html / "abc.html"
    config.paths.raw_html.mkdir(parents=True, exist_ok=True)
    raw_file.write_text(html, encoding="utf-8")
    (config.paths.raw / "capture.jsonl").write_text(
        json.dumps(
            {
                "url": url,
                "status": 200,
                "archivo": raw_file.relative_to(config.paths.root).as_posix(),
                "sha256": sha256_text(html),
            }
        )
        + "\n",
        encoding="utf-8",
    )

    silver = extract_all(config)
    assert len(silver) == 1

    corpus = build_gold(config)
    assert len(corpus) == 1
    assert corpus[0]["seccion"] == "identidad"
    assert corpus[0]["tokens"] > 0

    row = corpus[0]
    gold_file = config.paths.root / row["archivo"]
    assert gold_file.exists()
    texto = gold_file.read_text(encoding="utf-8")
    assert texto.startswith("---\n")
    assert "empresa: Banco de Occidente" in texto
    assert "seccion: identidad" in texto

    guardado = list(read_jsonl(config.paths.corpus_file))
    assert len(guardado) == 1


def test_gold_descarta_duplicados(tmp_path: Path) -> None:
    """Gold descarta duplicados."""
    config = make_config(tmp_path)
    config.paths.silver_markdown.mkdir(parents=True, exist_ok=True)
    texto = "Contenido identico repetido en dos URLs distintas del sitio. " * 5
    rows = [
        {
            "url": f"https://x.co/pagina-{i}",
            "titulo": f"Pagina {i}",
            "seccion": "otros",
            "texto": texto,
            "idioma": "es",
            "metodo": "trafilatura",
        }
        for i in range(2)
    ]
    (config.paths.processed / "silver.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8"
    )

    corpus = build_gold(config)
    assert len(corpus) == 1


def test_gold_descarta_urls_excluidas(tmp_path: Path) -> None:
    """Gold descarta urls excluidas."""
    config = make_config(tmp_path)
    config.discovery.exclude_patterns = ["/ayuda/agendar-cita-asesor"]
    config.paths.silver_markdown.mkdir(parents=True, exist_ok=True)
    rows = [
        {
            "url": "https://x.co/ayuda/agendar-cita-asesor",
            "titulo": "Agenda tu cita",
            "texto": "Formulario para dejar los datos y que un asesor te contacte. " * 3,
        },
        {
            "url": "https://x.co/cuentas",
            "titulo": "Cuentas",
            "texto": "Informacion publica de las cuentas de ahorro del banco. " * 3,
        },
    ]
    (config.paths.processed / "silver.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8"
    )

    corpus = build_gold(config)

    assert [row["fuente"] for row in corpus] == ["https://x.co/cuentas"]
    assert not (config.paths.gold_markdown / "agenda-tu-cita.md").exists()


FORMULARIOS_EXCLUIDOS = (
    "/ayuda/agendar-cita-asesor",
    "/formulario-autorizacion",
    "/proyectos-vivienda-form",
)


def test_gold_versionado_no_contiene_formularios() -> None:
    """Regresion de #21 y #33: ningun formulario queda en el Gold versionado."""
    from banco_occidente_corpus.config import load_config
    from banco_occidente_corpus.utils import is_excluded_url

    config = load_config()
    for ruta in FORMULARIOS_EXCLUIDOS:
        assert ruta in config.discovery.exclude_patterns
    fuentes = [row["fuente"] for row in read_jsonl(config.paths.corpus_file)]
    assert fuentes, "corpus.jsonl no deberia estar vacio"
    excluidas = [f for f in fuentes if is_excluded_url(f, FORMULARIOS_EXCLUIDOS)]
    assert excluidas == []
    for pagina in config.paths.gold_markdown.glob("*.md"):
        cabecera = pagina.read_text(encoding="utf-8")[:400]
        assert not is_excluded_url(cabecera, FORMULARIOS_EXCLUIDOS), pagina.name


# ---------------------------------------------------------------- checklist


def test_checklist_marca_evidencia(config: Config) -> None:
    """Checklist marca evidencia."""
    corpus = [
        {
            "id": "a",
            "titulo": "Quienes somos",
            "fuente": "https://x.co/quienes-somos",
            "seccion": "identidad",
            "tokens": 10,
        }
    ]
    textos = {"a": "Nuestra mision y vision. Fundado en 1965. Junta directiva."}
    items = evaluate(corpus, textos)
    encontrados = [i.item for i in items if i.encontrado]
    assert "Mision y vision" in encontrados
    assert "Historia (fundacion, hitos)" in encontrados
    found, total, percent = coverage(items)
    assert total == 24
    assert 0 < found < total
    assert 0 < percent < 100


# ---------------------------------------------------------------- red


def test_headers_incluyen_identificacion() -> None:
    """Headers incluyen identificacion."""
    from banco_occidente_corpus.config import SiteConfig
    from banco_occidente_corpus.net import HttpClient

    cfg = Config(site=SiteConfig(user_agent="UA-test", contact="a@b.co"))
    client = HttpClient(cfg, delay=0)
    try:
        headers = client._headers()
        assert headers["User-Agent"] == "UA-test"
        assert headers["From"] == "a@b.co"
    finally:
        client.close()


def test_cliente_sin_contacto_falla_antes_de_pedir() -> None:
    """Issue #30: sin site.contact no se crea el cliente (From es obligatorio)."""
    from banco_occidente_corpus.config import SiteConfig
    from banco_occidente_corpus.net import FaltaContacto, HttpClient

    cfg = Config(site=SiteConfig(user_agent="UA-test", contact="  "))
    with pytest.raises(FaltaContacto):
        HttpClient(cfg, delay=0)


def test_config_real_identifica_al_autor() -> None:
    """Config real identifica al autor."""
    from banco_occidente_corpus.config import load_config

    cfg = load_config()
    assert cfg.site.contact
    assert "@" in cfg.site.contact
    assert "Mozilla" in cfg.site.user_agent


def test_render_document_normaliza_cr() -> None:
    """Render document normaliza cr."""
    doc = render_document({"titulo": "x"}, "linea1\r\nlinea2\rlinea3")
    assert "\r" not in doc
    assert "linea1\nlinea2\nlinea3" in doc


# ---------------------------------------------------------------- helpers


def make_config(tmp_path: Path) -> Config:
    """Configuracion aislada en ``tmp_path``, sin tocar los datos del repositorio."""
    return Config(
        site=_site(),
        gold=GoldConfig(boilerplate_min_docs=5, boilerplate_ratio=0.35),
        paths=Paths(
            root=tmp_path,
            raw=tmp_path / "data/raw",
            processed=tmp_path / "data/processed",
            gold=tmp_path / "data/gold",
        ),
    )


def _site() -> SiteConfig:
    """Sitio de prueba con contacto para el header From."""
    return SiteConfig(
        allowed_hosts=["www.bancodeoccidente.com.co"],
        sitemap_url="",
        user_agent="TAAML-bot/1.0",
        contact="grupo@uao.edu.co",
    )


@pytest.fixture
def config() -> Config:
    from banco_occidente_corpus.config import DiscoveryConfig

    return Config(
        site=_site(),
        discovery=DiscoveryConfig(
            document_extensions=[".pdf"], exclude_patterns=["/portaltransaccional"]
        ),
    )
