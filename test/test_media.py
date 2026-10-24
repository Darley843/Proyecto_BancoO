"""Pruebas de documentos y videos: filtros, prioridad y limpieza de VTT."""

from __future__ import annotations

from banco_occidente_corpus.documents import _classify, _is_document, _priority, _year
from banco_occidente_corpus.videos import _video_id, parse_vtt


def test_clasifica_documentos():
    assert (
        _classify(
            "Estado Financiero Consolidado",
            "https://x.co/documents/estado-financiero-2025.pdf",
        )
        == "financiero"
    )
    assert (
        _classify(
            "Codigo de Gobierno Corporativo",
            "https://x.co/documents/codigo-gobierno.pdf",
        )
        == "gobierno"
    )
    assert (
        _classify("Brochure seguro de vida", "https://x.co/documents/brochure-vida.pdf")
        == "producto"
    )
    assert (
        _classify(
            "Politica de tratamiento de datos",
            "https://x.co/documents/politica-datos.pdf",
        )
        == "legal"
    )
    assert _classify("Documento suelto", "https://x.co/documents/otro.pdf") == "otro"


def test_prioridad_por_anio_y_categoria():
    assert _priority("financiero", 2025) == 1
    assert _priority("gobierno", 2024) == 1
    assert _priority("financiero", 2019) == 2
    assert _priority("producto", 2023) == 2
    assert _priority("producto", 2015) == 3
    assert _priority("otro", None) == 3


def test_anio_toma_el_mas_reciente():
    assert _year("Informe 2024 publicado en 2025") == 2025
    assert _year("sin fecha") is None
    assert _year("codigo 2098") is None


def test_solo_pdfs_y_adjuntos_liferay():
    assert _is_document("https://www.bancodeoccidente.com.co/a/b.pdf")
    assert _is_document("https://www.bancodeoccidente.com.co/documents/d/guest/eeff-2025")
    assert not _is_document("https://www.bancodeoccidente.com.co/a/b.xlsx")
    assert not _is_document("https://www.bancodeoccidente.com.co/libre-inversion-digital/x.pdf")


def test_video_id_formatos():
    assert _video_id("https://www.youtube.com/watch?v=abc123") == "abc123"
    assert _video_id("https://youtu.be/abc123?t=10") == "abc123"
    assert _video_id("https://www.youtube.com/shorts/xyz789") == "xyz789"
    assert _video_id("https://www.youtube.com/@canal/videos") is None


def test_parse_vtt_limpia_timestamps_y_duplicados():
    vtt = """WEBVTT
Kind: captions
Language: es

00:00:01.000 --> 00:00:03.000
Hola a todos

00:00:03.000 --> 00:00:05.000
Hola a todos

00:00:05.000 --> 00:00:07.000
Bienvenidos al <b>Banco</b>
"""
    text = parse_vtt(vtt)
    assert "00:00" not in text
    assert "<b>" not in text
    assert text.count("Hola a todos") == 1
    assert "Bienvenidos al Banco" in text
