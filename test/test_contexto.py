"""Pruebas de la capa Contexto: prompt de sistema derivado de Gold."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

from banco_occidente_corpus import config as config_mod
from banco_occidente_corpus.config import Config, Paths, SiteConfig
from banco_occidente_corpus.contexto import (
    ContextoConfig,
    PresupuestoExcedido,
    ResultadoContexto,
    build_contexto,
    build_parser,
    load_contexto_config,
)
from banco_occidente_corpus.dedupe import strip_boilerplate, strip_boilerplate_detailed
from banco_occidente_corpus.gold import render_document
from banco_occidente_corpus.utils import stable_tokens, write_jsonl

TELEFONO = "018000514652"
CUERPO = "Contenido institucional del Banco de Occidente para el corpus."
SECCIONES = {
    "identidad": 1,
    "atencion": 2,
    "oferta": 3,
    "legal": 4,
    "datos": 5,
    "presencia": 6,
    "otros": 7,
}


# ---------------------------------------------------------------- helpers


def _page(
    tmp_path: Path,
    pid: str,
    titulo: str,
    seccion: str,
    cuerpo: str,
    *,
    url: str | None = None,
    tipo: str = "",
    fecha: str = "",
    estado: str = "",
) -> dict[str, Any]:
    """Escribe una pagina Gold minima y devuelve su fila de corpus.jsonl."""
    destino = tmp_path / "data/gold/pages"
    destino.mkdir(parents=True, exist_ok=True)
    url = url or f"https://www.bancodeoccidente.com.co/{pid}"
    meta: dict[str, object] = {
        "fuente": url,
        "titulo": titulo,
        "seccion": seccion,
        "empresa": "Banco de Occidente",
        "fecha_captura": "2026-10-23",
        "idioma": "es",
        "tokens": 0,
        "hash": "0" * 8,
        "palabras": 0,
        "metodo": "trafilatura",
    }
    if tipo:
        meta["tipo"] = tipo
    if fecha:
        meta["fecha_publicacion"] = fecha
    if estado:
        meta["estado"] = estado
    ruta = destino / f"{pid}.md"
    ruta.write_text(render_document(meta, cuerpo), encoding="utf-8", newline="\n")
    return {
        "id": pid,
        "fuente": url,
        "titulo": titulo,
        "seccion": seccion,
        "empresa": "Banco de Occidente",
        "fecha_captura": "2026-10-23",
        "idioma": "es",
        "tokens": 10,
        "palabras": 5,
        "hash": "0" * 64,
        "archivo": ruta.relative_to(tmp_path).as_posix(),
    }


def _gold(tmp_path: Path, filas: list[dict[str, Any]]) -> None:
    write_jsonl(tmp_path / "data/gold/corpus.jsonl", filas)


def _config(tmp_path: Path) -> Config:
    return Config(
        site=SiteConfig(name="Banco de Occidente", language="es"),
        paths=Paths(
            root=tmp_path,
            raw=tmp_path / "data/raw",
            processed=tmp_path / "data/processed",
            gold=tmp_path / "data/gold",
        ),
    )


def _ctx(**cambios: object) -> ContextoConfig:
    base: dict[str, object] = {
        "max_tokens": 175000,
        "incluir_noticias": True,
        "max_noticias": 12,
        "boilerplate_min_docs": 5,
        "boilerplate_ratio": 0.5,
        "patrones_url_excluidos": [],
        "secciones": dict(SECCIONES),
    }
    base.update(cambios)
    return ContextoConfig(**base)  # type: ignore[arg-type]


def _lectura(resultado: ResultadoContexto) -> str:
    return resultado.archivo.read_text(encoding="utf-8")


def _manifest(resultado: ResultadoContexto) -> dict[str, Any]:
    return json.loads(resultado.manifest.read_text(encoding="utf-8"))


def _titulos(md: str) -> list[str]:
    return [linea[3:] for linea in md.splitlines() if linea.startswith("## ")]


# ---------------------------------------------------------------- contenido


def test_sin_frontmatter(tmp_path: Path) -> None:
    # Arrange: una pagina Gold con el frontmatter real que produce gold.py.
    filas = [
        _page(
            tmp_path,
            "quienes-somos",
            "Quiénes Somos",
            "identidad",
            "### Nuestro Banco\nMás de 60 años de experiencia nos respaldan.",
        )
    ]
    _gold(tmp_path, filas)

    # Act
    md = _lectura(build_contexto(_config(tmp_path), _ctx()))

    # Assert: se conserva el cuerpo y desaparece el YAML.
    assert "---" not in md
    assert "\nfuente:" not in md
    assert "tokens:" not in md
    assert "### Nuestro Banco" in md
    assert "Más de 60 años de experiencia nos respaldan." in md


def test_bloque_fuente_y_seccion(tmp_path: Path) -> None:
    # Arrange
    filas = [
        _page(
            tmp_path,
            "quienes-somos",
            "Quiénes Somos",
            "identidad",
            CUERPO,
            url="https://www.bancodeoccidente.com.co/quienes-somos",
        )
    ]
    _gold(tmp_path, filas)

    # Act
    md = _lectura(build_contexto(_config(tmp_path), _ctx()))

    # Assert: cabecera, fuente y seccion en ese orden.
    assert "## Quiénes Somos" in md
    assert "Fuente: https://www.bancodeoccidente.com.co/quienes-somos" in md
    assert "Sección: identidad" in md
    assert md.index("## Quiénes Somos") < md.index("Fuente: ")


def test_orden_prioridad_y_titulo(tmp_path: Path) -> None:
    # Arrange: titulos desordenados y secciones en orden invertido.
    filas = [
        _page(tmp_path, "z-otros", "Zeta", "otros", f"Otros servicios. {CUERPO}"),
        _page(tmp_path, "b-identidad", "Beta", "identidad", f"Beta. {CUERPO}"),
        _page(tmp_path, "a-identidad", "Alfa", "identidad", f"Alfa. {CUERPO}"),
        _page(tmp_path, "a-oferta", "Alfa oferta", "oferta", f"Oferta. {CUERPO}"),
    ]
    _gold(tmp_path, filas)

    # Act
    md = _lectura(build_contexto(_config(tmp_path), _ctx()))

    # Assert: identidad antes que oferta y otros; titulos alfabeticos dentro de cada seccion.
    assert _titulos(md) == ["Alfa", "Beta", "Alfa oferta", "Zeta"]


def test_dedupe_por_hash(tmp_path: Path) -> None:
    # Arrange: dos URLs con el mismo cuerpo.
    cuerpo = "Contenido idéntico copiado en dos direcciones del sitio."
    filas = [
        _page(tmp_path, "a-clon", "Alfa", "identidad", cuerpo),
        _page(tmp_path, "b-clon", "Beta", "identidad", cuerpo),
    ]
    _gold(tmp_path, filas)

    # Act
    resultado = build_contexto(_config(tmp_path), _ctx())
    md = _lectura(resultado)

    # Assert: gana el primero en el orden determinista y el otro queda auditado.
    assert len(resultado.incluidas) == 1
    assert resultado.incluidas[0].id == "a-clon"
    assert "## Beta" not in md
    duplicadas = [e for e in resultado.excluidas if e["motivo"] == "duplicado"]
    assert len(duplicadas) == 1
    assert duplicadas[0]["id"] == "b-clon"
    assert duplicadas[0]["detalle"] == "duplicado_de:a-clon"


def test_dedupe_antes_de_boilerplate(tmp_path: Path) -> None:
    # Arrange: dos cuerpos distintos, cada uno clonado una vez, y una linea comun
    # que solo seria boilerplate si los clones contaran como documentos.
    comun = f"Línea de atención: {TELEFONO}"
    cuerpo_a = f"Contenido del servicio alfa con texto suficiente.\n{comun}"
    cuerpo_b = f"Contenido del servicio beta con texto suficiente.\n{comun}"
    filas = [
        _page(tmp_path, "a-original", "Alfa", "atencion", cuerpo_a),
        _page(tmp_path, "b-original", "Beta", "atencion", cuerpo_b),
        _page(tmp_path, "a-clon", "Alfa clon", "atencion", cuerpo_a),
        _page(tmp_path, "b-clon", "Beta clon", "atencion", cuerpo_b),
    ]
    _gold(tmp_path, filas)

    # Act: con cuatro documentos la linea seria repetida; con dos unicos, no.
    resultado = build_contexto(
        _config(tmp_path),
        _ctx(boilerplate_min_docs=3, boilerplate_ratio=0.5),
    )
    md = _lectura(resultado)

    # Assert: los clones se excluyen antes y la linea comun sobrevive en cada pagina.
    assert {pagina.id for pagina in resultado.incluidas} == {"a-original", "b-original"}
    assert len([e for e in resultado.excluidas if e["motivo"] == "duplicado"]) == 2
    assert resultado.comunes == []
    assert md.count(TELEFONO) == 2


def test_boilerplate_bloque_comun(tmp_path: Path) -> None:
    # Arrange: seis paginas que repiten la misma linea de atencion.
    filas = [
        _page(
            tmp_path,
            f"pagina-{i}",
            f"Pagina {i}",
            "identidad",
            f"Contenido propio de la pagina numero {i} con texto suficiente.\n"
            f"Línea de atención: {TELEFONO}",
        )
        for i in range(6)
    ]
    _gold(tmp_path, filas)

    # Act
    resultado = build_contexto(_config(tmp_path), _ctx())
    md = _lectura(resultado)

    # Assert: la linea se retira de las paginas y se conserva una sola vez al inicio.
    assert md.count(TELEFONO) == 1
    assert resultado.comunes == [f"Línea de atención: {TELEFONO}"]
    inicio_comun = md.index("## Información común del sitio")
    primera_pagina = md.index("## Pagina 0")
    assert inicio_comun < md.index(TELEFONO) < primera_pagina


def test_numero_de_atencion_y_fuentes_sobreviven(tmp_path: Path) -> None:
    # Arrange: el telefono aparece en todas las paginas, o sea que es boilerplate.
    filas = [
        _page(
            tmp_path,
            f"servicio-{i}",
            f"Servicio {i}",
            "atencion",
            f"Atención al cliente del servicio {i}, con horario extendido.\n"
            f"018000514652 (Solo teléfonos fijos)",
        )
        for i in range(6)
    ]
    _gold(tmp_path, filas)

    # Act
    resultado = build_contexto(_config(tmp_path), _ctx())
    md = _lectura(resultado)

    # Assert: el dato repetido no se pierde y cada pagina conserva su Fuente.
    assert md.count(TELEFONO) == 1
    assert md.index(TELEFONO) < md.index("## Servicio 0")
    fuentes = [linea for linea in md.splitlines() if linea.startswith("Fuente: https://")]
    assert len(fuentes) == len(resultado.incluidas)
    assert len(resultado.incluidas) == 6


def test_degrada_encabezados_del_cuerpo(tmp_path: Path) -> None:
    # Arrange: un cuerpo con `##` (57 paginas de Gold) y otro con `#` (fichas de prensa).
    filas = [
        _page(
            tmp_path,
            "producto",
            "Producto",
            "oferta",
            f"## Características y requisitos\n{CUERPO}\n\n### Subsección\n{CUERPO}",
        ),
        _page(
            tmp_path,
            "noticia-2026-01-01-ejemplo",
            "Ficha de prensa",
            "presencia",
            f"# Banco de Occidente anuncia una iniciativa\n\n**Medio:** Portafolio\n{CUERPO}",
            tipo="noticia",
            fecha="2026-01-01",
            estado="verificado",
        ),
    ]
    _gold(tmp_path, filas)

    # Act
    md = _lectura(build_contexto(_config(tmp_path), _ctx()))

    # Assert: el cuerpo se degrada y nunca queda un encabezado en `##`.
    assert "### Características y requisitos" in md
    assert "#### Subsección" in md
    assert "### Banco de Occidente anuncia una iniciativa" in md
    assert "## Características y requisitos" not in md.splitlines()
    assert "## Banco de Occidente anuncia una iniciativa" not in md.splitlines()
    original = (tmp_path / "data/gold/pages/producto.md").read_text(encoding="utf-8")
    assert "## Características y requisitos" in original


def test_todo_encabezado_de_pagina_tiene_fuente(tmp_path: Path) -> None:
    # Arrange: paginas con encabezados propios y una linea repetida (bloque comun).
    filas = [
        _page(
            tmp_path,
            f"pagina-{i}",
            f"Pagina {i}",
            "identidad",
            f"## Sección interna\nContenido propio de la pagina {i} con texto suficiente.\n"
            f"Línea de atención: {TELEFONO}",
        )
        for i in range(6)
    ]
    _gold(tmp_path, filas)

    # Act
    resultado = build_contexto(_config(tmp_path), _ctx())
    lineas = _lectura(resultado).splitlines()

    # Assert: cada "## " del archivo es un bloque y le sigue su Fuente.
    encabezados = [i for i, linea in enumerate(lineas) if linea.startswith("## ")]
    assert len(encabezados) == len(resultado.incluidas) + 1  # + bloque comun
    for indice in encabezados:
        assert lineas[indice + 1].startswith("Fuente: "), lineas[indice]
    assert all(not linea.startswith("## Sección interna") for linea in lineas)


def test_equivalencia_strip_boilerplate() -> None:
    # Arrange
    boilerplate = {"linea repetida"}
    texto = "Titulo\n\nLinea repetida\nTexto util\n- [enlace](https://x.co)\n\n---\n"

    # Act
    limpio, retiradas = strip_boilerplate_detailed(texto, boilerplate)

    # Assert: la funcion nueva no altera el resultado de la existente.
    assert limpio == strip_boilerplate(texto, boilerplate)
    assert retiradas == ["Linea repetida"]
    assert "Texto util" in limpio


# ---------------------------------------------------------------- seleccion


def test_max_noticias_toma_las_mas_recientes(tmp_path: Path) -> None:
    # Arrange: cinco fichas con fechas distintas y una pagina del sitio.
    filas = [
        _page(tmp_path, "quienes-somos", "Quiénes Somos", "identidad", CUERPO),
    ]
    for dia in ("01", "02", "03", "04", "05"):
        filas.append(
            _page(
                tmp_path,
                f"hecho-2026-01-{dia}",
                f"Ficha {dia}",
                "presencia",
                f"Resumen propio de la ficha {dia} con texto suficiente.",
                tipo="hecho",
                fecha=f"2026-01-{dia}",
                estado="verificado",
            )
        )
    _gold(tmp_path, filas)

    # Act
    resultado = build_contexto(_config(tmp_path), _ctx(max_noticias=2))
    md = _lectura(resultado)

    # Assert
    fichas = [p.id for p in resultado.incluidas if p.tipo == "hecho"]
    assert set(fichas) == {"hecho-2026-01-05", "hecho-2026-01-04"}
    assert "Ficha 03" not in md
    fuera = [e for e in resultado.excluidas if e["motivo"] == "ficha_fuera_de_ventana"]
    assert len(fuera) == 3


def test_ficha_pendiente_excluida(tmp_path: Path) -> None:
    # Arrange
    filas = [
        _page(
            tmp_path,
            "hecho-pendiente",
            "Ficha pendiente",
            "presencia",
            "Resumen pendiente de validacion humana.",
            tipo="hecho",
            fecha="2026-10-19",
            estado="pendiente",
        )
    ]
    _gold(tmp_path, filas)

    # Act
    resultado = build_contexto(_config(tmp_path), _ctx())

    # Assert
    assert resultado.incluidas == []
    assert resultado.excluidas[0]["motivo"] == "ficha_pendiente"


def test_url_excluida(tmp_path: Path) -> None:
    # Arrange
    filas = [
        _page(
            tmp_path,
            "buscador",
            "Buscador",
            "otros",
            "Resultados de busqueda sin contenido propio.",
            url="https://www.bancodeoccidente.com.co/Buscador",
        )
    ]
    _gold(tmp_path, filas)

    # Act
    resultado = build_contexto(_config(tmp_path), _ctx(patrones_url_excluidos=["/buscador"]))

    # Assert
    assert resultado.incluidas == []
    assert resultado.excluidas[0]["motivo"] == "url_excluida"


def test_seccion_no_incluida(tmp_path: Path) -> None:
    # Arrange
    filas = [_page(tmp_path, "tarjeta", "Tarjeta", "oferta", CUERPO)]
    _gold(tmp_path, filas)

    # Act
    resultado = build_contexto(_config(tmp_path), _ctx(secciones={"identidad": 1}))

    # Assert
    assert resultado.incluidas == []
    assert resultado.excluidas[0]["motivo"] == "seccion_no_incluida"


def test_ignora_documents_y_videos(tmp_path: Path) -> None:
    # Arrange: una fila que apunta fuera de data/gold/pages.
    ruta = tmp_path / "data/gold/documents/balance-2025.md"
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text("---\ntitulo: Balance\n---\n\nTexto del PDF.", encoding="utf-8")
    filas = [
        {
            "id": "balance-2025",
            "fuente": "https://www.bancodeoccidente.com.co/documents/balance.pdf",
            "titulo": "Balance 2025",
            "seccion": "datos",
            "empresa": "Banco de Occidente",
            "fecha_captura": "2026-10-23",
            "idioma": "es",
            "tokens": 10,
            "palabras": 5,
            "hash": "0" * 64,
            "archivo": ruta.relative_to(tmp_path).as_posix(),
        }
    ]
    _gold(tmp_path, filas)

    # Act
    resultado = build_contexto(_config(tmp_path), _ctx())

    # Assert: solo se leen paginas del sitio, nunca documents/ ni videos/.
    assert resultado.incluidas == []
    assert resultado.excluidas[0]["motivo"] == "fuente_no_pagina"


def test_respeta_max_tokens(tmp_path: Path) -> None:
    # Arrange: una seccion prioritaria corta y una de menor prioridad muy larga.
    filas = [
        _page(
            tmp_path,
            "identidad",
            "Identidad",
            "identidad",
            f"Banco fundado en 1965 en Cali. {CUERPO}",
        ),
        _page(tmp_path, "otros", "Otros", "otros", "Relleno de baja prioridad. " * 16),
    ]
    _gold(tmp_path, filas)

    # Act
    resultado = build_contexto(_config(tmp_path), _ctx(max_tokens=120))
    md = _lectura(resultado)

    # Assert
    assert resultado.tokens <= 120
    assert "## Identidad" in md
    assert "## Otros" not in md
    assert resultado.descartadas_por_presupuesto[0]["seccion"] == "otros"


def test_fit_budget_falla_si_no_cabe(tmp_path: Path) -> None:
    # Arrange: una sola pagina que no cabe ni con max_tokens minimo.
    filas = [_page(tmp_path, "quienes-somos", "Quiénes Somos", "identidad", CUERPO)]
    _gold(tmp_path, filas)

    # Act / Assert: error claro y sin escribir el archivo.
    with pytest.raises(PresupuestoExcedido, match="max_tokens=1"):
        build_contexto(_config(tmp_path), _ctx(max_tokens=1))
    assert not (tmp_path / "data/contexto/contexto_banco.md").exists()
    assert not (tmp_path / "data/contexto/manifest.json").exists()


# ---------------------------------------------------------------- contrato


def test_determinista(tmp_path: Path) -> None:
    # Arrange
    filas = [
        _page(tmp_path, "quienes-somos", "Quiénes Somos", "identidad", CUERPO),
        _page(tmp_path, "tarjeta", "Tarjeta", "oferta", CUERPO),
    ]
    _gold(tmp_path, filas)
    config, ctx = _config(tmp_path), _ctx()

    # Act
    primero = build_contexto(config, ctx)
    md_uno = primero.archivo.read_bytes()
    manifest_uno = primero.manifest.read_bytes()
    segundo = build_contexto(config, ctx)

    # Assert: misma entrada, mismos bytes.
    assert segundo.archivo.read_bytes() == md_uno
    assert segundo.manifest.read_bytes() == manifest_uno


def test_estimador_no_depende_de_tiktoken(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange: una pagina y el contador de utils (sin tiktoken disponible).
    filas = [_page(tmp_path, "quienes-somos", "Quiénes Somos", "identidad", CUERPO)]
    _gold(tmp_path, filas)
    config, ctx = _config(tmp_path), _ctx()
    esperado = build_contexto(config, ctx)

    # Act
    monkeypatch.setitem(sys.modules, "tiktoken", None)
    resultado = build_contexto(config, ctx)

    # Assert: el recorte no cambia aunque tiktoken no exista.
    assert resultado.tokens == esperado.tokens
    assert resultado.archivo.read_bytes() == esperado.archivo.read_bytes()
    assert resultado.tokens == stable_tokens(_lectura(resultado))


def test_manifest_lista_incluidas_y_excluidas(tmp_path: Path) -> None:
    # Arrange
    filas = [
        _page(tmp_path, "quienes-somos", "Quiénes Somos", "identidad", CUERPO),
        _page(tmp_path, "tarjeta", "Tarjeta", "oferta", CUERPO),
    ]
    _gold(tmp_path, filas)

    # Act
    manifest = _manifest(build_contexto(_config(tmp_path), _ctx(secciones={"identidad": 1})))

    # Assert
    assert manifest["paginas"] == {"leidas": 2, "incluidas": 1, "excluidas": 1}
    assert manifest["tokens_metodo"].startswith("stable_tokens")
    assert manifest["incluidas"][0]["id"] == "quienes-somos"
    assert manifest["excluidas"][0]["motivo"] == "seccion_no_incluida"
    assert set(manifest["tokens_por_seccion"]) == {"identidad"}


# ---------------------------------------------------------------- CLI y config


def test_config_contexto_defaults(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange: raiz temporal sin config/contexto.toml y sin variables de entorno.
    monkeypatch.setattr(config_mod, "PROJECT_ROOT", tmp_path)
    monkeypatch.delenv("CORPUS_CONTEXTO_CONFIG", raising=False)

    # Act
    ctx = load_contexto_config()

    # Assert: valores por defecto oficiales, sin leer el TOML real.
    assert ctx.max_tokens == 175000
    assert ctx.incluir_noticias is True
    assert ctx.max_noticias == 12
    assert ctx.boilerplate_min_docs == 5
    assert ctx.boilerplate_ratio == 0.10
    assert ctx.bloque_comun is True
    assert list(ctx.secciones.items()) == [
        ("identidad", 1),
        ("atencion", 2),
        ("oferta", 3),
        ("legal", 4),
        ("datos", 5),
        ("presencia", 6),
        ("otros", 7),
    ]
    assert ctx.patrones_url_excluidos == ["/buscador", "/error", "^https?://[^/]+/?$"]


def test_config_contexto_carga_toml(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange: un contexto.toml de ejemplo dentro de tmp_path.
    destino = tmp_path / "config"
    destino.mkdir()
    (destino / "contexto.toml").write_text(
        "\n".join(
            [
                "max_tokens = 90000",
                "incluir_noticias = false",
                "max_noticias = 3",
                "boilerplate_min_docs = 4",
                "boilerplate_ratio = 0.25",
                "bloque_comun = false",
                'patrones_url_excluidos = ["/login", "/error"]',
                "",
                "[secciones]",
                "identidad = 1",
                "oferta = 2",
                "",
            ]
        ),
        encoding="utf-8",
        newline="\n",
    )
    monkeypatch.setattr(config_mod, "PROJECT_ROOT", tmp_path)
    monkeypatch.delenv("CORPUS_CONTEXTO_CONFIG", raising=False)

    # Act
    ctx = load_contexto_config()

    # Assert: se respeta cada valor del archivo, sin tocar el entorno.
    assert ctx.max_tokens == 90000
    assert ctx.incluir_noticias is False
    assert ctx.max_noticias == 3
    assert ctx.boilerplate_min_docs == 4
    assert ctx.boilerplate_ratio == 0.25
    assert ctx.bloque_comun is False
    assert ctx.secciones == {"identidad": 1, "oferta": 2}
    assert ctx.patrones_url_excluidos == ["/login", "/error"]


def test_parser_contexto() -> None:
    # Act
    args = build_parser().parse_args(["--max-tokens", "1000", "--sin-noticias"])

    # Assert
    assert args.max_tokens == 1000
    assert args.sin_noticias is True
    assert not hasattr(args, "conteo_tiktoken")
