"""Pruebas de configuracion, parser oficial y fuente curada de noticias."""

from __future__ import annotations

import importlib.util
import logging
from datetime import date
from pathlib import Path
from typing import Any

import pytest
import yaml

from banco_occidente_corpus import cli, documents, news
from banco_occidente_corpus.config import (
    Config,
    NewsConfig,
    Paths,
    SiteConfig,
    load_config,
)
from banco_occidente_corpus.net import Response
from banco_occidente_corpus.news import (
    build_noticias,
    cargar_indice_documentos,
    deduplicar,
    derivar_resumen,
    derivar_titulo,
    es_aviso_dividendo,
    filtrar_verificadas,
    load_prensa,
    merge_corpus,
    parse_fecha_es,
    parse_hechos_relevantes,
    render_ficha,
    validar_ficha,
    validar_pii,
    vincular_documento,
    write_noticias_index,
)
from banco_occidente_corpus.utils import read_jsonl, write_jsonl

FIXTURES = Path(__file__).parent / "fixtures"


def _ficha_prensa(**cambios: object) -> dict[str, object]:
    """Devuelve una ficha de prensa valida para las pruebas locales."""
    ficha: dict[str, object] = {
        "id": "noticia-2026-01-01-ejemplo",
        "fecha": "2026-01-01",
        "medio": "Medio de prueba",
        "titulo": "Banco de Occidente anuncia una iniciativa",
        "url": "https://example.com/noticia",
        "resumen": "Resumen propio de la noticia para las pruebas locales.",
        "temas": ["digital"],
        "relevancia": "alta",
        "estado": "verificado",
    }
    ficha.update(cambios)
    return ficha


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


def test_load_prensa_lee_y_normaliza_fechas() -> None:
    """El registro real se carga y sus fechas quedan como texto ISO."""
    config = load_config()
    fichas = load_prensa(config.paths.news_prensa)

    assert 15 <= len(fichas) <= 20
    assert all(isinstance(ficha["fecha"], str) for ficha in fichas)
    assert all(validar_ficha(ficha) == [] for ficha in fichas)


def test_validar_ficha_rechaza_campo_faltante() -> None:
    """Una ficha sin uno de los campos obligatorios no es valida."""
    ficha = _ficha_prensa()
    del ficha["titulo"]

    assert any("titulo" in error for error in validar_ficha(ficha))


@pytest.mark.parametrize(
    ("campo", "valor", "mensaje"),
    [
        ("fecha", "2025-13-40", "fecha"),
        ("url", "ftp://example.com/noticia", "url"),
        ("estado", "revision", "estado"),
        ("resumen", "   ", "resumen"),
    ],
)
def test_validar_ficha_rechaza_valores_invalidos(campo: str, valor: object, mensaje: str) -> None:
    """Rechaza fecha, URL, estado y resumen que no cumplen el contrato."""
    ficha = _ficha_prensa()
    ficha[campo] = valor

    assert any(mensaje in error for error in validar_ficha(ficha))


def test_load_prensa_falla_con_campo_faltante(tmp_path: Path) -> None:
    """El cargador informa el archivo y el campo invalido."""
    ficha = _ficha_prensa()
    del ficha["resumen"]
    path = tmp_path / "prensa.yaml"
    path.write_text(yaml.safe_dump([ficha], allow_unicode=True), encoding="utf-8")

    with pytest.raises(ValueError, match="resumen"):
        load_prensa(path)


def test_deduplicar_por_id_fuente_y_evento_medio(tmp_path: Path) -> None:
    """Descarta ids, URLs y pares evento-medio repetidos y aplica el tope."""
    fichas = [
        _ficha_prensa(
            id="noticia-1",
            url="https://example.com/a",
            medio="Medio A",
            evento="evento-1",
        ),
        _ficha_prensa(
            id="noticia-1",
            url="https://example.com/id-repetido",
            medio="Medio B",
            evento="evento-2",
        ),
        _ficha_prensa(
            id="noticia-2",
            url="https://example.com/a",
            medio="Medio C",
            evento="evento-3",
        ),
        _ficha_prensa(
            id="noticia-3",
            url="https://example.com/evento-medio",
            medio="Medio A",
            evento="evento-1",
        ),
        _ficha_prensa(
            id="noticia-4",
            url="https://example.com/evento-4-a",
            medio="Medio A",
            evento="evento-4",
        ),
        _ficha_prensa(
            id="noticia-5",
            url="https://example.com/evento-4-b",
            medio="Medio B",
            evento="evento-4",
        ),
        _ficha_prensa(
            id="noticia-6",
            url="https://example.com/evento-4-c",
            medio="Medio C",
            evento="evento-4",
        ),
    ]
    path = tmp_path / "prensa.yaml"
    path.write_text(
        yaml.safe_dump(fichas, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )

    resultado = deduplicar(load_prensa(path), max_por_evento=2)

    assert [ficha["id"] for ficha in resultado] == ["noticia-1", "noticia-4", "noticia-5"]


def test_filtrar_verificadas_excluye_pendientes(tmp_path: Path) -> None:
    """Solo las fichas verificadas quedan disponibles para publicar en Gold."""
    fichas = [
        _ficha_prensa(
            id="noticia-pendiente",
            url="https://example.com/pendiente",
            estado="pendiente",
        ),
        _ficha_prensa(
            id="noticia-verificada",
            url="https://example.com/verificada",
            estado="verificado",
        ),
    ]
    path = tmp_path / "prensa.yaml"
    path.write_text(
        yaml.safe_dump(fichas, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )

    publicables = filtrar_verificadas(deduplicar(load_prensa(path)))

    assert [ficha["id"] for ficha in publicables] == ["noticia-verificada"]


def test_readme_documenta_limites_y_verificacion() -> None:
    """El README explica el rango 15-20, los campos, los temas y la verificación."""
    config = load_config()
    readme = (config.paths.news_source / "README.md").read_text(encoding="utf-8")
    compacto = " ".join(readme.split())

    assert "15 y 20" in readme
    assert "estado: pendiente" in readme
    assert "estado: verificado" in readme
    assert "Banco de Occidente de Colombia" in readme
    assert "título, fecha, medio, enlace original y resumen propio" in compacto
    assert "No se guarda el cuerpo del artículo" in compacto
    assert "no se copian párrafos del artículo" in compacto
    assert "## Campos" in readme
    assert "Vocabulario de `temas`" in readme
    assert "## Verificación humana" in readme


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


# ---------------------------------------------------------------- Gold local


def _config_temporal(tmp_path: Path) -> Config:
    """Construye una configuracion aislada en ``tmp_path`` para probar Gold."""
    return Config(
        site=SiteConfig(
            name="Banco de Occidente",
            language="es",
            base_url="https://www.bancodeoccidente.com.co",
        ),
        news=NewsConfig(desde="2025-01-01", hasta="2026-12-31"),
        paths=Paths(
            root=tmp_path,
            raw=tmp_path / "data/raw",
            processed=tmp_path / "data/processed",
            gold=tmp_path / "data/gold",
        ),
    )


def _fila_hecho(**cambios: object) -> dict[str, object]:
    """Devuelve una fila publicable de hecho oficial para las pruebas Gold."""
    fila: dict[str, object] = {
        "id": "hecho-2026-10-19-emision-de-valores",
        "tipo": "hecho",
        "origen": "oficial",
        "titulo": "Emisión de valores",
        "fecha_publicacion": "2026-10-19",
        "fecha_captura": "2026-10-24",
        "fuente": "https://www.bancodeoccidente.com.co/inversionistas",
        "medio": "Banco de Occidente",
        "resumen": "Colocación de bonos ordinarios por $500.000 millones.",
        "temas": ["financiacion"],
        "relevancia": "alta",
        "estado": "verificado",
        "anexo": "https://www.bancodeoccidente.com.co/documents/d/guest/ir-final-oct-2026",
    }
    fila.update(cambios)
    return fila


def test_render_ficha_contrato_y_cuerpo_minimo(tmp_path: Path) -> None:
    """La ficha tiene frontmatter completo y un cuerpo sin el articulo original."""
    config = _config_temporal(tmp_path)
    fila = _fila_hecho(
        cuerpo="Parrafo completo del articulo que no debe copiarse.",
        imagen="https://example.com/foto.jpg",
        documento_id="ir-final-oct-2026",
        documento_archivo="data/gold/documents/ir-final-oct-2026.md",
        documento_titulo="Informe Final Octubre 2026",
    )

    frontmatter, cuerpo = render_ficha(fila, config)

    obligatorios = {
        "id",
        "tipo",
        "origen",
        "seccion",
        "empresa",
        "titulo",
        "fecha_publicacion",
        "fecha_captura",
        "idioma",
        "fuente",
        "medio",
        "resumen",
        "temas",
        "relevancia",
        "estado",
        "tokens",
        "hash",
        "palabras",
        "metodo",
        "documento_id",
        "documento_archivo",
        "documento_titulo",
    }
    assert obligatorios <= set(frontmatter)
    assert frontmatter["id"] == "hecho-2026-10-19-emision-de-valores"
    assert frontmatter["tipo"] == "hecho"
    assert frontmatter["origen"] == "oficial"
    assert frontmatter["documento_archivo"] == "ir-final-oct-2026.md"
    assert frontmatter["estado"] == "verificado"
    assert len(str(frontmatter["hash"])) == 8

    assert "Emisión de valores" in cuerpo
    assert "Banco de Occidente" in cuerpo
    assert "2026-10-19" in cuerpo
    assert str(fila["fuente"]) in cuerpo
    assert str(fila["resumen"]) in cuerpo
    assert "../documents/ir-final-oct-2026.md" in cuerpo
    assert "Parrafo completo" not in cuerpo
    assert "![" not in cuerpo
    assert "<img" not in cuerpo
    assert "\n## " not in cuerpo


def test_render_ficha_rechaza_campos_minimos_ausentes(tmp_path: Path) -> None:
    """Sin titulo, resumen o fecha valida la ficha no se puede renderizar."""
    config = _config_temporal(tmp_path)

    with pytest.raises(ValueError, match="titulo"):
        render_ficha(_fila_hecho(titulo=""), config)
    with pytest.raises(ValueError, match="resumen"):
        render_ficha(_fila_hecho(resumen=""), config)
    with pytest.raises(ValueError, match="Fecha"):
        render_ficha(_fila_hecho(fecha_publicacion="2026-13-40"), config)


def test_render_ficha_ids_distintos_mismo_dia_y_tema(tmp_path: Path) -> None:
    """Dos hechos de la misma fecha y tema con anexos distintos no colisionan."""
    config = _config_temporal(tmp_path)
    primero, _ = render_ficha(
        _fila_hecho(id="", resumen="Informe A del mismo dia.", anexo="https://x.co/a.pdf"),
        config,
    )
    segundo, _ = render_ficha(
        _fila_hecho(id="", resumen="Informe B del mismo dia.", anexo="https://x.co/b.pdf"),
        config,
    )

    assert primero["id"] != segundo["id"]
    assert primero["id"].startswith("hecho-2026-10-19-")


def test_merge_corpus_conserva_sitio_y_no_duplica(tmp_path: Path) -> None:
    """La fusion elimina fichas viejas, conserva el sitio y es idempotente."""
    config = _config_temporal(tmp_path)
    sitio = {
        "id": "quienes-somos-abc",
        "fuente": "https://x.co/quienes-somos",
        "titulo": "Quienes somos",
    }
    antigua = {
        "id": "noticia-2024-01-01-vieja",
        "fuente": "https://x.co/vieja",
        "titulo": "Vieja",
    }
    write_jsonl(config.paths.corpus_file, [sitio, antigua])

    nuevas: list[dict[str, Any]] = [
        _fila_hecho(),
        {
            "id": "noticia-2026-01-01-ejemplo",
            "fuente": "https://example.com/noticia",
            "fecha_publicacion": "2026-01-01",
            "titulo": "Nota externa",
            "medio": "Medio",
        },
    ]

    primera = merge_corpus(config, nuevas)
    segunda = merge_corpus(config, nuevas)

    assert len(primera) == len(segunda) == 3
    ids = [fila["id"] for fila in read_jsonl(config.paths.corpus_file)]
    assert ids.count("quienes-somos-abc") == 1
    assert ids.count("hecho-2026-10-19-emision-de-valores") == 1
    assert ids.count("noticia-2026-01-01-ejemplo") == 1
    assert "noticia-2024-01-01-vieja" not in ids


def test_write_noticias_index_refleja_fichas(tmp_path: Path) -> None:
    """El indice muestra ventana, conteos, fechas, enlaces y documentos."""
    config = _config_temporal(tmp_path)
    hecho, _ = render_ficha(
        _fila_hecho(
            documento_id="ir-final-oct-2026",
            documento_archivo="ir-final-oct-2026.md",
            documento_titulo="Informe Final Octubre 2026",
            evento="2026-10-19-emision",
        ),
        config,
    )
    prensa, _ = render_ficha(
        _ficha_prensa(
            id="noticia-2026-01-01-ejemplo",
            fecha="2026-01-01",
            url="https://example.com/noticia",
        ),
        config,
    )

    contenido = write_noticias_index(config, [hecho, prensa])

    assert config.paths.news_index.exists()
    assert config.paths.news_index.read_text(encoding="utf-8") == contenido
    assert "**Ventana:** 2025-01-01 a 2026-12-31" in contenido
    assert "**Fichas publicadas:** 2" in contenido
    assert "2026-10-19" in contenido
    assert "2026-01-01" in contenido
    assert "https://example.com/noticia" in contenido
    assert "documents/ir-final-oct-2026.md" in contenido
    assert "| hecho | 1 |" in contenido
    assert "| oficial | 1 |" in contenido
    assert "| prensa | 1 |" in contenido


def test_write_noticias_index_sin_fichas(tmp_path: Path) -> None:
    """Sin fichas publicadas el indice deja conteos en cero y una nota."""
    config = _config_temporal(tmp_path)

    contenido = write_noticias_index(config, [])

    assert "**Fichas publicadas:** 0" in contenido
    assert "_No hubo publicaciones en la ventana._" in contenido
    assert "| - | 0 |" in contenido


def _cargar_healthcheck() -> Any:
    """Carga el script healthcheck de la skill sin instalarlo como paquete."""
    ruta = (
        Path(__file__).resolve().parents[1]
        / ".opencode"
        / "skills"
        / "corpus-extraction"
        / "scripts"
        / "healthcheck.py"
    )
    spec = importlib.util.spec_from_file_location("healthcheck_noticias", ruta)
    assert spec is not None
    assert spec.loader is not None
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


def _escribir_pagina_noticia(
    directorio: Path,
    nombre: str,
    meta: dict[str, object],
) -> Path:
    """Escribe una pagina Gold de noticias con frontmatter YAML en ``directorio``."""
    directorio.mkdir(parents=True, exist_ok=True)
    ruta = directorio / nombre
    cabecera = yaml.safe_dump(meta, allow_unicode=True, sort_keys=False).strip()
    ruta.write_text(f"---\n{cabecera}\n---\n\n# Ficha\n", encoding="utf-8")
    return ruta


def test_healthcheck_noticias_validas(tmp_path: Path) -> None:
    """Una ficha con sus campos y su documento vinculado pasa el healthcheck."""
    modulo = _cargar_healthcheck()
    paginas = tmp_path / "pages"
    documentos_dir = tmp_path / "documents"
    documentos_dir.mkdir()
    (documentos_dir / "informe.md").write_text("# Informe\n", encoding="utf-8")
    pagina = _escribir_pagina_noticia(
        paginas,
        "hecho-2026-10-19-emision.md",
        {
            "id": "hecho-2026-10-19-emision",
            "fecha_publicacion": "2026-10-19",
            "tipo": "hecho",
            "origen": "oficial",
            "medio": "Banco de Occidente",
            "resumen": "Colocacion de bonos.",
            "documento_id": "doc-1",
            "documento_archivo": "informe.md",
        },
    )
    documentos = [{"id": "doc-1", "archivo": "data/gold/documents/informe.md"}]

    assert modulo.validate_noticias([pagina], documentos_dir, documentos) == []


def test_healthcheck_noticias_invalidas(tmp_path: Path) -> None:
    """El healthcheck detecta campos faltantes, ids repetidos y enlaces rotos."""
    modulo = _cargar_healthcheck()
    paginas = tmp_path / "pages"
    documentos_dir = tmp_path / "documents"
    documentos_dir.mkdir()
    base: dict[str, object] = {
        "fecha_publicacion": "2026-10-19",
        "tipo": "hecho",
        "origen": "oficial",
        "medio": "Banco de Occidente",
        "resumen": "Colocacion de bonos.",
    }
    primera = _escribir_pagina_noticia(paginas, "hecho-a.md", {**base, "id": "hecho-duplicado"})
    segunda = _escribir_pagina_noticia(paginas, "hecho-b.md", {**base, "id": "hecho-duplicado"})
    sin_medio = _escribir_pagina_noticia(
        paginas, "hecho-c.md", {**base, "id": "hecho-c", "medio": ""}
    )
    roto = _escribir_pagina_noticia(
        paginas,
        "hecho-d.md",
        {
            **base,
            "id": "hecho-d",
            "documento_id": "doc-x",
            "documento_archivo": "no-existe.md",
        },
    )

    errores = modulo.validate_noticias([primera, segunda, sin_medio, roto], documentos_dir, [])
    texto = " ".join(errores)

    assert "id duplicado" in texto
    assert "medio" in texto
    assert "documento_archivo no existe" in texto
    assert "documento_id ausente de documents.jsonl" in texto


# ---------------------------------------------------------------- integracion CLI


def _preparar_bronce(config: Config, html: str) -> None:
    """Guarda el HTML oficial como Bronze y su registro en ``capture.jsonl``."""
    ruta = config.paths.raw_html / "inversionistas.html"
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(html, encoding="utf-8")
    write_jsonl(
        config.paths.capture_file,
        [
            {
                "url": news.OFFICIAL_PAGE_URL,
                "status": 200,
                "archivo": ruta.relative_to(config.paths.root).as_posix(),
            }
        ],
    )


def _preparar_prensa(config: Config) -> None:
    """Escribe una ficha verificada y una pendiente en la curaduria temporal."""
    config.paths.news_source.mkdir(parents=True, exist_ok=True)
    fichas = [
        _ficha_prensa(),
        _ficha_prensa(
            id="noticia-pendiente",
            url="https://example.com/pendiente",
            estado="pendiente",
        ),
    ]
    config.paths.news_prensa.write_text(
        yaml.safe_dump(fichas, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


def _preparar_indice_documentos(config: Config) -> None:
    """Crea un ``documents.jsonl`` de solo lectura con el anexo de octubre."""
    write_jsonl(
        config.paths.documents_index,
        [
            {
                "id": "ir-final-oct-2026",
                "titulo": "Informe Final Octubre 2026",
                "fuente": (
                    "https://portalpublico.bancodeoccidente.com.co/documents/d/guest/"
                    "ir-final-oct-2026"
                ),
                "archivo": "data/gold/documents/ir-final-oct-2026.md",
            }
        ],
    )


def _prohibir_red(monkeypatch: pytest.MonkeyPatch) -> None:
    """Hace fallar cualquier peticion o descarga real durante la prueba."""

    def no_permitido(*args: object, **kwargs: object) -> None:
        """Falla si una rutina intenta tocar la red o descargar PDFs."""
        raise AssertionError("la prueba no debe tocar la red ni descargar PDFs")

    monkeypatch.setattr(news.HttpClient, "get", no_permitido)
    monkeypatch.setattr(documents, "discover_documents", no_permitido)
    monkeypatch.setattr(documents, "fetch_documents", no_permitido)
    monkeypatch.setattr(documents, "extract_documents", no_permitido)


def test_build_noticias_sin_red_genera_tres_artefactos(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Con Bronze y ``--sin-red`` publica fichas, corpus e indice sin red."""
    config = _config_temporal(tmp_path)
    html = (FIXTURES / "inversionistas.html").read_text(encoding="utf-8")
    _preparar_bronce(config, html)
    _preparar_prensa(config)
    _preparar_indice_documentos(config)
    _prohibir_red(monkeypatch)

    filas = build_noticias(
        config,
        desde=date(2025, 1, 1),
        hasta=date(2026, 10, 24),
        sin_red=True,
    )

    oficiales = [fila for fila in filas if fila["origen"] == "oficial"]
    prensa = [fila for fila in filas if fila["origen"] == "prensa"]
    assert len(oficiales) == 3
    assert [fila["id"] for fila in prensa] == ["noticia-2026-01-01-ejemplo"]
    assert "noticia-pendiente" not in {fila["id"] for fila in filas}

    assert len(list(config.paths.gold_markdown.glob("hecho-*.md"))) == 3
    assert len(list(config.paths.gold_markdown.glob("noticia-*.md"))) == 1
    filas_corpus = list(read_jsonl(config.paths.corpus_file))
    assert len(filas_corpus) == 4
    assert all(
        fila.get("archivo") and config.paths.root.joinpath(fila["archivo"]).exists()
        for fila in filas_corpus
    )
    assert config.paths.news_index.exists()
    indice = config.paths.news_index.read_text(encoding="utf-8")
    assert "**Fichas publicadas:** 4" in indice
    assert "2025-03-26" in indice

    octubre = next(fila for fila in oficiales if fila["fecha_publicacion"] == "2026-10-19")
    assert octubre["documento_id"] == "ir-final-oct-2026"
    pagina = config.paths.gold_markdown / f"{octubre['id']}.md"
    assert "../documents/ir-final-oct-2026.md" in pagina.read_text(encoding="utf-8")
    assert not list((tmp_path / "data/gold/documents").glob("*.pdf"))


def test_build_noticias_sin_red_sin_bronce_no_toca_red(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sin Bronze y con ``--sin-red`` omite oficiales y publica la curaduria."""
    config = _config_temporal(tmp_path)
    _preparar_prensa(config)
    _prohibir_red(monkeypatch)

    filas = build_noticias(
        config,
        desde=date(2025, 1, 1),
        hasta=date(2026, 10, 24),
        sin_red=True,
    )

    assert len(filas) == 1
    assert filas[0]["origen"] == "prensa"
    assert config.paths.news_index.exists()
    assert not list(config.paths.gold_markdown.glob("hecho-*.md"))


def test_cli_noticias_403_avisa_y_no_escribe(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Ante 403 el comando falla, muestra el motivo y no escribe fichas."""
    config = _config_temporal(tmp_path)

    def get_403(self: object, url: str, *, accept: str | None = None) -> Response:
        """Simula un 403 del WAF sin salir a la red."""
        return Response(
            url=url,
            status=403,
            text="",
            content_type="text/html",
            elapsed=0.0,
            error="HTTP 403",
        )

    monkeypatch.setattr(news.HttpClient, "get", get_403)
    monkeypatch.setattr(cli, "load_config", lambda path=None: config)

    with caplog.at_level(logging.ERROR, logger="corpus"):
        codigo = cli.main(["noticias"])

    assert codigo == 2
    assert "403" in caplog.text
    assert "bloqueo" in caplog.text
    assert "intentarlo mas tarde" in caplog.text
    assert not list(config.paths.gold_markdown.glob("*.md"))
    assert not config.paths.corpus_file.exists()
    assert not config.paths.news_index.exists()


def test_cli_noticias_help(capsys: pytest.CaptureFixture[str]) -> None:
    """El subcomando noticias expone las cuatro opciones del contrato."""
    with pytest.raises(SystemExit):
        cli.main(["noticias", "--help"])

    salida = capsys.readouterr().out
    for opcion in ("--desde", "--hasta", "--sin-red", "--force"):
        assert opcion in salida


def test_makefile_target_noticias_independiente() -> None:
    """El makefile añade noticias sin encadenarlo a los targets existentes."""
    config = load_config()
    texto = (config.paths.root / "makefile").read_text(encoding="utf-8")

    assert "noticias:" in texto
    assert "$(CORPUS) noticias" in texto
    for objetivo in (
        "all",
        "gold",
        "deliver",
        "docs",
        "docs-finanzas",
        "videos",
        "media",
    ):
        for linea in texto.splitlines():
            if linea.startswith(f"{objetivo}:"):
                assert "noticias" not in linea


def test_documentacion_noticias_independiente() -> None:
    """README y AGENTS documentan el comando y su independencia del pipeline."""
    config = load_config()
    readme = (config.paths.root / "README.md").read_text(encoding="utf-8")
    agents = (config.paths.root / "AGENTS.md").read_text(encoding="utf-8")
    compacto = " ".join(readme.split())

    assert "make noticias" in readme
    assert "## Noticias y hechos relevantes" in readme
    assert "no forma parte de" in compacto
    for objetivo in (
        "all",
        "gold",
        "deliver",
        "docs",
        "docs-finanzas",
        "videos",
        "media",
    ):
        assert f"`make {objetivo}`" in compacto
    assert "make noticias" in agents
    assert "independiente" in agents
