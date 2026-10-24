"""Pruebas de configuracion, parser oficial y fuente curada de noticias."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
import yaml

from banco_occidente_corpus import documents
from banco_occidente_corpus.config import load_config
from banco_occidente_corpus.news import (
    cargar_indice_documentos,
    derivar_resumen,
    derivar_titulo,
    es_aviso_dividendo,
    parse_fecha_es,
    parse_hechos_relevantes,
    validar_pii,
    vincular_documento,
)

FIXTURES = Path(__file__).parent / "fixtures"


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


# ---------------------------------------------------------------- fechas


@pytest.mark.parametrize(
    ("texto", "esperado"),
    [
        ("Octubre 19-2026", date(2026, 10, 19)),
        ("Septiembre 01-2026", date(2026, 9, 1)),
        ("Enero 2-2025", date(2025, 1, 2)),
        ("Agosto 20 - 2020", date(2020, 8, 20)),
        ("2025-03-26", date(2025, 3, 26)),
    ],
)
def test_parse_fecha_es(texto: str, esperado: date) -> None:
    """Convierte fechas oficiales en espanol y fechas ISO al mismo tipo."""
    assert parse_fecha_es(texto) == esperado


@pytest.mark.parametrize("texto", ["Febrero 30-2025", "19/10/2026", "Mes invalido 12-2025", ""])
def test_parse_fecha_es_invalida(texto: str) -> None:
    """Rechaza fechas con dia, formato o mes que no existen."""
    with pytest.raises(ValueError):
        parse_fecha_es(texto)


# ---------------------------------------------------------------- hechos oficiales


def test_parse_hechos_relevantes_filtra_ventana_y_anexos() -> None:
    """Selecciona la tabla correcta, filtra la ventana y normaliza anexos."""
    html = (FIXTURES / "inversionistas.html").read_text(encoding="utf-8")
    hechos = parse_hechos_relevantes(html, date(2025, 1, 1), date(2026, 10, 24))

    fechas = [hecho["fecha"] for hecho in hechos]
    assert fechas == [date(2026, 10, 19), date(2026, 9, 1), date(2025, 3, 26)]

    octubre = next(hecho for hecho in hechos if hecho["fecha"] == date(2026, 10, 19))
    assert octubre["anexo"] == (
        "https://www.bancodeoccidente.com.co/documents/d/guest/ir-final-oct-2026?download=true"
    )
    septiembre = next(hecho for hecho in hechos if hecho["fecha"] == date(2026, 9, 1))
    assert septiembre["anexo"] is None


def test_parse_hechos_relevantes_deriva_titulo_y_resumen() -> None:
    """Deriva el titular del tema oficial y normaliza el resumen."""
    html = (FIXTURES / "inversionistas.html").read_text(encoding="utf-8")
    hechos = parse_hechos_relevantes(html, date(2025, 1, 1), date(2026, 10, 24))
    octubre = next(hecho for hecho in hechos if hecho["fecha"] == date(2026, 10, 19))

    assert octubre["titulo"] == "Emisión de valores"
    assert octubre["resumen"] == (
        "Banco de Occidente informa la colocación de bonos ordinarios por $500.000 millones."
    )
    assert derivar_titulo("", "") == "Hecho relevante"
    assert derivar_resumen(" Texto   con   espacios ") == "Texto con espacios"


def test_parse_hechos_relevantes_excluye_dividendos() -> None:
    """Un aviso mensual de dividendos no genera ficha; un hito si genera."""
    html = (FIXTURES / "inversionistas.html").read_text(encoding="utf-8")
    hechos = parse_hechos_relevantes(html, date(2025, 1, 1), date(2026, 10, 24))
    fechas = {hecho["fecha"] for hecho in hechos}

    assert date(2025, 1, 2) not in fechas
    assert date(2025, 3, 26) in fechas
    assert es_aviso_dividendo(
        "Pago de dividendos",
        "Pago mensual de dividendos del mes de enero.",
    )
    assert not es_aviso_dividendo(
        "Decisiones adoptadas por la Asamblea de Inversionistas",
        "Distribución de utilidades aprobada por la asamblea.",
    )


def test_parse_hechos_relevantes_ignora_accionistas_y_pii() -> None:
    """La tabla de accionistas y las filas con datos personales no llegan al resultado."""
    html = (FIXTURES / "inversionistas.html").read_text(encoding="utf-8")
    hechos = parse_hechos_relevantes(html, date(2025, 1, 1), date(2026, 10, 24))
    volcado = " ".join(
        f"{hecho['titulo']} {hecho['resumen']} {hecho['anexo'] or ''}" for hecho in hechos
    )

    assert "ACCIONISTA UNO" not in volcado
    assert "1.020.456.789" not in volcado
    assert "890.300.279" not in volcado
    assert "persona@example.com" not in volcado
    assert date(2026, 8, 20) not in {hecho["fecha"] for hecho in hechos}


def test_parse_hechos_relevantes_aplica_tope() -> None:
    """Conserva como maximo el numero de hechos indicado, del mas nuevo al mas viejo."""
    html = (FIXTURES / "inversionistas.html").read_text(encoding="utf-8")
    hechos = parse_hechos_relevantes(
        html,
        date(2025, 1, 1),
        date(2026, 10, 24),
        max_oficiales=2,
    )

    assert [hecho["fecha"] for hecho in hechos] == [date(2026, 10, 19), date(2026, 9, 1)]


# ---------------------------------------------------------------- privacidad


@pytest.mark.parametrize(
    ("texto", "categoria"),
    [
        ("Cédula 1.020.456.789", "cedula"),
        ("NIT 890.300.279-4", "nit"),
        ("Escriba a persona@example.com", "correo"),
        ("Teléfono 310 123 4567", "telefono"),
    ],
)
def test_validar_pii_detecta_cada_dato(texto: str, categoria: str) -> None:
    """Cada dato personal prohibido se reporta con su categoria."""
    assert categoria in validar_pii(texto, "")


def test_validar_pii_acepta_texto_limpio() -> None:
    """Un titulo y resumen sin datos personales no generan hallazgos."""
    assert validar_pii("Resultados del banco", "Utilidad de $500.000 millones.") == []


# ---------------------------------------------------------------- documentos Gold


def test_vincular_documento_reconoce_variantes_de_url() -> None:
    """Une el anexo con el indice aunque cambie el host o el query."""
    indice = cargar_indice_documentos(FIXTURES / "documents_index.jsonl")

    octubre = vincular_documento(
        "https://www.bancodeoccidente.com.co/documents/d/guest/ir-final-oct-2026?download=true",
        indice,
    )
    assert octubre == {
        "documento_id": "ir-final-oct-2026",
        "documento_archivo": "ir-final-oct-2026.md",
        "documento_titulo": "Informe Final Octubre 2026",
    }

    acta = vincular_documento(
        "https://portalpublico.bancodeoccidente.com.co/documents/d/guest/acta-asamblea-2025",
        indice,
    )
    assert acta is not None
    assert acta["documento_id"] == "acta-asamblea-2025"


def test_vincular_documento_sin_coincidencia() -> None:
    """Un anexo que no esta en Gold no produce campos de documento."""
    indice = cargar_indice_documentos(FIXTURES / "documents_index.jsonl")
    assert (
        vincular_documento("https://www.bancodeoccidente.com.co/documents/d/guest/otro", indice)
        is None
    )
    assert vincular_documento(None, indice) is None


def test_vincular_documento_no_descarga_ni_extrae(monkeypatch: pytest.MonkeyPatch) -> None:
    """La vinculacion solo consulta el indice; no descarga ni reextrae PDFs."""

    def no_permitido(*args: object, **kwargs: object) -> None:
        """Falla si alguna rutina de documentos intenta ejecutarse."""
        raise AssertionError("la vinculacion no debe descargar ni extraer documentos")

    monkeypatch.setattr(documents, "discover_documents", no_permitido)
    monkeypatch.setattr(documents, "fetch_documents", no_permitido)
    monkeypatch.setattr(documents, "extract_documents", no_permitido)

    indice = cargar_indice_documentos(FIXTURES / "documents_index.jsonl")
    vinculado = vincular_documento(
        "https://www.bancodeoccidente.com.co/documents/d/guest/ir-final-oct-2026",
        indice,
    )
    assert vinculado is not None


# ---------------------------------------------------------------- documentacion


def test_fuentes_documenta_tabla_y_privacidad() -> None:
    """FUENTES describe la tabla oficial, Ver Anexo y la exclusion de accionistas."""
    config = load_config()
    fuentes = (config.paths.root / "docs" / "FUENTES.md").read_text(encoding="utf-8")

    assert "informacion-inversionistas" in fuentes
    assert "Anexo Descargable" in fuentes
    assert "Ver Anexo" in fuentes
    assert "tabla de accionistas" in fuentes
    assert "inversionistas.html" in fuentes
    assert "test/test_news.py" in fuentes
