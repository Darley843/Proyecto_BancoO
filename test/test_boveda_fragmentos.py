"""Pruebas de la Bóveda: contratos, fragmentos, hechos, alcance y salida."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from banco_occidente_corpus.boveda import Fragmento, Recuperador
from banco_occidente_corpus.boveda.__main__ import main
from banco_occidente_corpus.boveda.fragmentos import (
    RATIO_REPETIDAS,
    TOKENS_MAXIMOS,
    TOKENS_MINIMOS,
    LineaRepetida,
    ResumenFragmentos,
    cargar_chunks,
    construir_fragmentos,
    escribir_fragmentos,
    formatear_resumen,
)
from banco_occidente_corpus.config import Config, Paths
from banco_occidente_corpus.utils import sha256_text, stable_tokens, write_jsonl

URL = "https://www.bancodeoccidente.com.co/productos"
OTRA_URL = "https://www.bancodeoccidente.com.co/otra"


def make_config(tmp_path: Path) -> Config:
    """Crea una configuración aislada en tmp_path, sin tocar el corpus real."""
    return Config(
        paths=Paths(
            root=tmp_path,
            raw=tmp_path / "data/raw",
            processed=tmp_path / "data/processed",
            gold=tmp_path / "data/gold",
            knowledge=tmp_path / "data/knowledge",
        )
    )


def chunk(
    page_id: str,
    texto: str,
    *,
    heading: str = "",
    url: str = URL,
    section: str = "oferta",
) -> dict[str, Any]:
    """Construye una fila de chunk con la misma forma que produce knowledge.py."""
    digest = sha256_text(f"{page_id}|{heading}|{texto}")
    return {
        "chunk_id": f"chk:{digest[:12]}",
        "page_id": page_id,
        "url": url,
        "section": section,
        "heading": heading,
        "level": 1,
        "text": texto,
        "tokens": stable_tokens(texto),
        "hash": digest,
    }


def write_chunks(config: Config, filas: list[dict[str, Any]], nombre: str = "chunks.jsonl") -> None:
    """Escribe filas de chunks en la capa Knowledge temporal."""
    config.paths.knowledge.mkdir(parents=True, exist_ok=True)
    write_jsonl(config.paths.knowledge / nombre, filas)


def write_indices(
    config: Config,
    *,
    paginas: list[dict[str, Any]] | None = None,
    documentos: list[dict[str, Any]] | None = None,
    videos: list[dict[str, Any]] | None = None,
) -> None:
    """Escribe los índices de Gold que usa la Bóveda para deducir el origen."""
    config.paths.gold.mkdir(parents=True, exist_ok=True)
    write_jsonl(config.paths.corpus_file, paginas or [])
    write_jsonl(config.paths.documents_index, documentos or [])
    write_jsonl(config.paths.videos_index, videos or [])


def hecho(
    fact_id: str,
    valor: str,
    *,
    url: str = URL,
    page_id: str = "pagina-demo",
    section: str = "identidad",
    heading: str = "Banco de Occidente",
    predicate: str = "tiene_proposito",
    entity_id: str = "ent:banco",
    review: str = "pending",
    quote: str = "",
) -> dict[str, Any]:
    """Construye un hecho verificado con la evidencia que exige la Bóveda."""
    return {
        "record_type": "fact",
        "id": fact_id,
        "entity_id": entity_id,
        "predicate": predicate,
        "value": valor,
        "value_type": "text",
        "evidence": {
            "url": url,
            "page_id": page_id,
            "chunk_id": "chk:demo",
            "section": section,
            "heading": heading,
            "quote": quote or valor,
        },
        "confidence": 0.9,
        "review": review,
    }


def test_contrato_fragmento_y_recuperador() -> None:
    """El fragmento acepta los nueve campos y un doble cumple el Protocol."""
    fragmento = Fragmento(
        id="frag:abc",
        texto="texto",
        url=URL,
        titulo="Título",
        seccion="oferta",
        encabezado="Encabezado",
        tipo="pagina",
        tokens=2,
    )
    assert fragmento.puntaje == 0.0
    assert fragmento.tipo == "pagina"

    class RecuperadorFalso:
        """Recuperador simulado que implementa el contrato sin heredar."""

        def buscar(self, consulta: str, k: int = 5) -> list[Fragmento]:
            """Devuelve el fragmento de prueba recortado a k."""
            assert consulta
            return [fragmento][:k]

    recuperador: Recuperador = RecuperadorFalso()
    assert recuperador.buscar("cuenta", k=5)[0].id == "frag:abc"


def test_fusion_llega_a_80_y_conserva_encabezados(tmp_path: Path) -> None:
    """Dos chunks cortos se fusionan y ambos encabezados quedan en el texto."""
    config = make_config(tmp_path)
    write_indices(config, paginas=[{"id": "pagina-demo", "titulo": "Página demo"}])
    write_chunks(
        config,
        [
            chunk("pagina-demo", "palabra " * 30, heading="Cuenta Plata"),
            chunk("pagina-demo", "termino " * 20, heading="Cuenta Oro"),
            chunk("pagina-demo", "cierre " * 10, heading="Cuenta Platinum"),
        ],
    )

    resultado = construir_fragmentos(config, "base")

    assert len(resultado.fragmentos) == 2
    primero, ultimo = resultado.fragmentos
    assert primero.tokens >= TOKENS_MINIMOS
    assert primero.encabezado == "Cuenta Plata"
    assert "Cuenta Plata" in primero.texto
    assert "Cuenta Oro" in primero.texto
    assert primero.texto.index("Cuenta Plata") < primero.texto.index("Cuenta Oro")
    assert ultimo.tokens < TOKENS_MINIMOS
    assert "Cuenta Platinum" in ultimo.texto


def test_particion_sobre_400_conserva_tabla_entera(tmp_path: Path) -> None:
    """Un texto largo se parte por párrafos y la tabla queda completa."""
    config = make_config(tmp_path)
    write_indices(config, paginas=[{"id": "pagina-demo", "titulo": "Página demo"}])
    parrafo_uno = "Contenido introductorio " * 50
    parrafo_dos = "Detalle adicional " * 45
    tabla = "| Concepto | Valor |\n|---|---|\n| Cuota | 16.700 |"
    write_chunks(
        config,
        [chunk("pagina-demo", f"{parrafo_uno}\n\n{parrafo_dos}\n\n{tabla}")],
    )

    resultado = construir_fragmentos(config, "base")

    assert len(resultado.fragmentos) >= 2
    assert all(fragmento.tokens <= TOKENS_MAXIMOS for fragmento in resultado.fragmentos)
    con_tabla = [
        fragmento for fragmento in resultado.fragmentos if "| Cuota | 16.700 |" in fragmento.texto
    ]
    assert len(con_tabla) == 1
    assert "| Concepto | Valor |" in con_tabla[0].texto
    assert "|---|---|" in con_tabla[0].texto
    assert resultado.resumen.tablas_enteras == 1
    assert resultado.resumen.tablas_partidas == 0


def test_parrafo_de_1000_tokens_sin_lineas_en_blanco_se_parte_por_lineas(tmp_path: Path) -> None:
    """Un párrafo sin líneas en blanco se parte por líneas y ningún fragmento supera 400."""
    config = make_config(tmp_path)
    write_indices(config, paginas=[{"id": "pagina-demo", "titulo": "Página demo"}])
    lineas = [
        f"Linea {indice:03d} con contenido suficiente para el parrafo." for indice in range(70)
    ]
    texto = "\n".join(lineas)
    assert TOKENS_MAXIMOS < stable_tokens(texto) < 1100
    write_chunks(config, [chunk("pagina-demo", texto)])

    resultado = construir_fragmentos(config, "base")

    assert len(resultado.fragmentos) >= 3
    assert all(fragmento.tokens <= TOKENS_MAXIMOS for fragmento in resultado.fragmentos)
    assert resultado.resumen.fragmentos_largos == 0
    unido = "\n".join(fragmento.texto for fragmento in resultado.fragmentos)
    assert all(linea in unido for linea in lineas)


def test_linea_unica_muy_larga_se_parte_por_oraciones(tmp_path: Path) -> None:
    """Una sola línea enorme se parte por oraciones y conserva todas las oraciones."""
    config = make_config(tmp_path)
    write_indices(config, paginas=[{"id": "pagina-demo", "titulo": "Página demo"}])
    oraciones = [
        f"La oracion numero {indice} explica un beneficio del producto." for indice in range(70)
    ]
    texto = " ".join(oraciones)
    assert stable_tokens(texto) > TOKENS_MAXIMOS
    write_chunks(config, [chunk("pagina-demo", texto)])

    resultado = construir_fragmentos(config, "base")

    assert len(resultado.fragmentos) >= 3
    assert all(fragmento.tokens <= TOKENS_MAXIMOS for fragmento in resultado.fragmentos)
    assert all(fragmento.texto.strip().endswith(".") for fragmento in resultado.fragmentos)
    assert resultado.resumen.fragmentos_largos == 0
    unido = " ".join(fragmento.texto for fragmento in resultado.fragmentos)
    assert all(oracion in unido for oracion in oraciones)


def test_tabla_de_30_filas_se_parte_repite_encabezado(tmp_path: Path) -> None:
    """Una tabla larga se parte por filas repitiendo encabezado y separador."""
    config = make_config(tmp_path)
    write_indices(config, paginas=[{"id": "pagina-demo", "titulo": "Página demo"}])
    encabezado = "| Producto | Descripción |"
    separador = "|---|---|"
    filas = [
        (
            f"| Producto {indice:02d} | Descripcion extensa del producto numero {indice} "
            "con condiciones y beneficios |"
        )
        for indice in range(30)
    ]
    texto = "\n".join([encabezado, separador, *filas])
    assert stable_tokens(texto) > TOKENS_MAXIMOS
    write_chunks(config, [chunk("pagina-demo", texto)])

    resultado = construir_fragmentos(config, "base")

    assert len(resultado.fragmentos) >= 2
    assert all(fragmento.tokens <= TOKENS_MAXIMOS for fragmento in resultado.fragmentos)
    assert resultado.resumen.fragmentos_largos == 0
    assert resultado.resumen.tablas_enteras == 0
    assert resultado.resumen.tablas_partidas == 1
    assert resultado.resumen.partes_tablas_partidas == len(resultado.fragmentos)
    for fragmento in resultado.fragmentos:
        lineas = [linea.strip() for linea in fragmento.texto.splitlines()]
        assert lineas[0] == encabezado
        assert lineas[1] == separador
    unido = "\n".join(fragmento.texto for fragmento in resultado.fragmentos)
    assert all(fila in unido for fila in filas)


def test_resumen_separa_tablas_enteras_y_partidas(tmp_path: Path) -> None:
    """El resumen distingue la tabla que cabe de la que se parte por filas."""
    config = make_config(tmp_path)
    write_indices(config, paginas=[{"id": "pagina-demo", "titulo": "Página demo"}])
    tabla_corta = "| A | B |\n|---|---|\n| 1 | 2 |"
    encabezado = "| Producto | Descripción |"
    separador = "|---|---|"
    filas = [
        (
            f"| Producto {indice:02d} | Descripcion extensa del producto numero {indice} "
            "con condiciones y beneficios |"
        )
        for indice in range(30)
    ]
    texto = "\n\n".join([tabla_corta, "\n".join([encabezado, separador, *filas])])
    write_chunks(config, [chunk("pagina-demo", texto)])

    resultado = construir_fragmentos(config, "base")

    assert resultado.resumen.tablas_enteras == 1
    assert resultado.resumen.tablas_partidas == 1
    assert resultado.resumen.partes_tablas_partidas >= 2


def test_descarta_ruido_y_conserva_separador_de_tabla(tmp_path: Path) -> None:
    """El ruido de navegación se retira, pero el separador de la tabla se conserva."""
    config = make_config(tmp_path)
    write_indices(config, paginas=[{"id": "pagina-demo", "titulo": "Página demo"}])
    texto = (
        "Contenido real de la página\n"
        "---\n"
        "[Menú](https://ejemplo.test)\n"
        "ab\n"
        "| Concepto | Valor |\n"
        "|---|---|\n"
        "| Cuota | 16.700 |\n"
        "> \n"
        "Otro párrafo útil"
    )
    write_chunks(config, [chunk("pagina-demo", texto, heading="Tarifas")])

    resultado = construir_fragmentos(config, "base")

    fragmento = resultado.fragmentos[0]
    lineas = [linea.strip() for linea in fragmento.texto.splitlines()]
    assert fragmento.texto.startswith("Tarifas")
    assert "Contenido real de la página" in fragmento.texto
    assert "Otro párrafo útil" in fragmento.texto
    assert "Menú" not in fragmento.texto
    assert "---" not in lineas
    assert "ab" not in lineas
    assert "|---|---|" in fragmento.texto
    assert "| Cuota | 16.700 |" in fragmento.texto


def test_ids_estables_entre_corridas(tmp_path: Path) -> None:
    """Dos construcciones y dos escrituras producen los mismos ids y bytes."""
    config = make_config(tmp_path)
    write_indices(config, paginas=[{"id": "pagina-demo", "titulo": "Página demo"}])
    write_chunks(
        config,
        [
            chunk("pagina-demo", "Contenido uno " * 30, heading="Uno"),
            chunk("pagina-demo", "Contenido dos " * 12, heading="Dos"),
        ],
    )

    primero = construir_fragmentos(config, "base")
    segundo = construir_fragmentos(config, "base")
    assert [f.id for f in primero.fragmentos] == [f.id for f in segundo.fragmentos]

    ruta_uno, _ = escribir_fragmentos(config, "base")
    bytes_uno = ruta_uno.read_bytes()
    ruta_dos, _ = escribir_fragmentos(config, "base")
    assert bytes_uno == ruta_dos.read_bytes()


def test_no_duplica_chunk_presente_en_ambos_archivos(tmp_path: Path) -> None:
    """Un chunk que está en chunks_web y en chunks se cuenta una sola vez."""
    config = make_config(tmp_path)
    write_indices(config, paginas=[{"id": "pagina-demo", "titulo": "Página demo"}])
    fila = chunk("pagina-demo", "Contenido repetido en los dos archivos " * 20)
    write_chunks(config, [fila], nombre="chunks_web.jsonl")
    write_chunks(config, [fila], nombre="chunks.jsonl")

    assert len(cargar_chunks(config)) == 1
    assert len(construir_fragmentos(config, "base").fragmentos) == 1


def test_hecho_con_pii_se_omite_y_texto_del_hecho(tmp_path: Path) -> None:
    """Un hecho válido se indexa con su entidad y los hechos con PII o sin evidencia se omiten."""
    config = make_config(tmp_path)
    write_indices(config, paginas=[{"id": "pagina-demo", "titulo": "Página demo"}])
    write_chunks(config, [])
    config.paths.knowledge.mkdir(parents=True, exist_ok=True)
    write_jsonl(
        config.paths.knowledge_entities,
        [{"record_type": "entity", "id": "ent:banco", "name": "Banco de Occidente"}],
    )
    write_jsonl(
        config.paths.knowledge_facts,
        [
            hecho("fact:valido", "Hacer realidad el desarrollo."),
            hecho("fact:pii", "Escribe a cliente@example.com para recibir ayuda."),
            hecho("fact:sin-url", "Valor sin evidencia", url=""),
        ],
    )

    resultado = construir_fragmentos(config, "base")

    assert len(resultado.fragmentos) == 1
    fragmento = resultado.fragmentos[0]
    assert fragmento.tipo == "hecho verificado"
    assert fragmento.texto == ("Proposito del Banco de Occidente: Hacer realidad el desarrollo.")
    assert fragmento.url == URL
    assert fragmento.seccion == "identidad"
    assert fragmento.encabezado == "Banco de Occidente"
    assert resultado.resumen.omitidos_pii == 1
    assert resultado.resumen.omitidos_sin_evidencia == 1
    assert resultado.resumen.hechos_por_revision == {"pending": 1}


def test_tipo_segun_origen_y_alcance(tmp_path: Path) -> None:
    """El tipo sale del origen y el alcance base excluye PDF no producto y videos."""
    config = make_config(tmp_path)
    write_indices(
        config,
        paginas=[{"id": "pagina-demo", "titulo": "Página demo"}],
        documentos=[
            {
                "id": "producto-demo",
                "titulo": "Documento de producto",
                "categoria_documento": "producto",
            },
            {
                "id": "financiero-demo",
                "titulo": "Estado financiero",
                "categoria_documento": "financiero",
            },
        ],
        videos=[{"id": "video-demo", "titulo": "Video demo"}],
    )
    write_chunks(
        config,
        [
            chunk("pagina-demo", "Contenido pagina " * 20),
            chunk("producto-demo", "Contenido producto " * 20),
            chunk("financiero-demo", "Contenido financiero " * 20),
            chunk("video-demo", "Contenido video " * 20),
        ],
    )

    base = construir_fragmentos(config, "base")
    textos_base = " ".join(fragmento.texto for fragmento in base.fragmentos)
    assert "Contenido pagina" in textos_base
    assert "Contenido producto" in textos_base
    assert "Contenido financiero" not in textos_base
    assert "Contenido video" not in textos_base
    assert {fragmento.tipo for fragmento in base.fragmentos} == {"pagina", "pdf"}
    titulos = {fragmento.texto: fragmento.titulo for fragmento in base.fragmentos}
    assert any(titulo == "Documento de producto" for titulo in titulos.values())

    completo = construir_fragmentos(config, "completo")
    textos_completos = " ".join(fragmento.texto for fragmento in completo.fragmentos)
    assert "Contenido financiero" in textos_completos
    assert "Contenido video" in textos_completos
    assert {fragmento.tipo for fragmento in completo.fragmentos} == {"pagina", "pdf", "video"}


def test_quita_lineas_repetidas_entre_paginas(tmp_path: Path) -> None:
    """Una línea que se repite en todas las páginas se quita; una única se conserva."""
    config = make_config(tmp_path)
    paginas = [{"id": f"pagina-{indice}", "titulo": f"Página {indice}"} for indice in range(6)]
    filas = [
        chunk(
            pagina["id"],
            f"Contenido propio de la pagina {indice}\nLinea repetida del menu",
        )
        for indice, pagina in enumerate(paginas)
    ]
    write_indices(config, paginas=paginas)
    write_chunks(config, filas)

    resultado = construir_fragmentos(config, "base")

    assert RATIO_REPETIDAS == 0.15
    assert all("Linea repetida del menu" not in f.texto for f in resultado.fragmentos)
    assert any("Contenido propio de la pagina 0" in f.texto for f in resultado.fragmentos)
    assert resultado.resumen.lineas_repetidas == 1
    assert len(resultado.resumen.lineas_frecuentes) == 1
    frecuente = resultado.resumen.lineas_frecuentes[0]
    assert frecuente.texto == "Linea repetida del menu"
    assert frecuente.paginas == 6


def test_escribir_fragmentos_solo_en_boveda(tmp_path: Path) -> None:
    """La escritura crea el JSONL en data/boveda y no modifica Gold ni Knowledge."""
    config = make_config(tmp_path)
    write_indices(config, paginas=[{"id": "pagina-demo", "titulo": "Página demo"}])
    write_chunks(config, [chunk("pagina-demo", "Contenido de la pagina " * 20)])
    config.paths.knowledge.mkdir(parents=True, exist_ok=True)
    write_jsonl(config.paths.knowledge_facts, [hecho("fact:valido", "Hacer realidad.")])

    antes_gold = {
        ruta: ruta.read_bytes() for ruta in config.paths.gold.rglob("*") if ruta.is_file()
    }
    antes_knowledge = {
        ruta: ruta.read_bytes() for ruta in config.paths.knowledge.rglob("*") if ruta.is_file()
    }

    ruta, resumen = escribir_fragmentos(config, "base")

    assert ruta == tmp_path / "data/boveda/fragmentos_base.jsonl"
    filas = [json.loads(linea) for linea in ruta.read_text(encoding="utf-8").splitlines()]
    assert filas
    assert set(filas[0]) == {
        "id",
        "texto",
        "url",
        "titulo",
        "seccion",
        "encabezado",
        "tipo",
        "tokens",
        "puntaje",
    }
    assert all(fila["puntaje"] == 0.0 for fila in filas)
    assert resumen.total == len(filas)
    assert antes_gold == {
        ruta_gold: ruta_gold.read_bytes()
        for ruta_gold in config.paths.gold.rglob("*")
        if ruta_gold.is_file()
    }
    assert antes_knowledge == {
        ruta_knowledge: ruta_knowledge.read_bytes()
        for ruta_knowledge in config.paths.knowledge.rglob("*")
        if ruta_knowledge.is_file()
    }


def test_formatear_resumen(tmp_path: Path) -> None:
    """El resumen de texto incluye conteos, líneas repetidas y su top cinco."""
    resumen = ResumenFragmentos(
        total=3,
        por_tipo={"pagina": 3},
        tokens_min=10,
        tokens_mediana=90.0,
        tokens_max=120,
        cortos=1,
        fragmentos_largos=0,
        tablas_enteras=2,
        tablas_partidas=1,
        partes_tablas_partidas=3,
        lineas_repetidas=1,
        lineas_frecuentes=(LineaRepetida(texto="Linea del menu", paginas=6),),
        hechos_por_revision={"pending": 1},
        omitidos_sin_evidencia=1,
        omitidos_pii=2,
    )

    texto = formatear_resumen(resumen, tmp_path / "fragmentos_base.jsonl")

    assert "Fragmentos escritos: 3" in texto
    assert "lineas_repetidas: 1" in texto
    assert "Fragmentos con más de 400 tokens: 0" in texto
    assert "Tablas enteras: 2" in texto
    assert "Tablas partidas por filas: 1 en 3 partes" in texto
    assert "6 páginas: Linea del menu" in texto
    assert "hechos" in texto.lower()


def test_main_escribe_archivo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """El comando fragmentos escribe el archivo e imprime el resumen."""
    config = make_config(tmp_path)
    write_indices(config, paginas=[{"id": "pagina-demo", "titulo": "Página demo"}])
    write_chunks(config, [chunk("pagina-demo", "Contenido de la pagina " * 20)])
    monkeypatch.setattr("banco_occidente_corpus.boveda.__main__.load_config", lambda: config)

    codigo = main(["fragmentos", "--alcance", "base"])

    assert codigo == 0
    salida = capsys.readouterr().out
    assert "Fragmentos escritos:" in salida
    assert "lineas_repetidas:" in salida
    assert (tmp_path / "data/boveda/fragmentos_base.jsonl").exists()


def test_alcance_invalido_falla(tmp_path: Path) -> None:
    """Un alcance desconocido se rechaza con ValueError."""
    config = make_config(tmp_path)
    write_chunks(config, [])

    with pytest.raises(ValueError, match="Alcance desconocido"):
        construir_fragmentos(config, "otro")  # type: ignore[arg-type]


def test_fragmentos_con_id_repetido_se_descartan(tmp_path: Path) -> None:
    """Dos chunks largos con el mismo texto generan un solo fragmento y un duplicado."""
    config = make_config(tmp_path)
    texto = "Cuota de manejo de la tarjeta debito por dieciseis mil setecientos pesos. " * 8
    fila = chunk("pagina-repetida", texto)
    repetido = dict(fila, chunk_id="chk:repetido")
    write_jsonl(config.paths.knowledge_chunks_web, [fila, repetido])

    resultado = construir_fragmentos(config)

    assert len(resultado.fragmentos) == 1
    assert resultado.resumen.total == 1
    assert resultado.resumen.duplicados == 1
