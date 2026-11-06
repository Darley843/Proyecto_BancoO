"""Pruebas sin red del Tablero: esquema, tarifario, tablas y consultas."""

from __future__ import annotations

import csv
import tomllib
from pathlib import Path
from typing import Any

import pytest

from banco_occidente_corpus.config import Config, Paths
from banco_occidente_corpus.tablero import (
    Fila,
    buscar_filas,
    comparar_filas,
    concepto_sin_franquicia,
    filas_para_plantilla,
)
from banco_occidente_corpus.tablero.__main__ import main
from banco_occidente_corpus.tablero.construir import (
    Falla,
    ResumenTablero,
    cargar_preguntas_tabla,
    escribir_tablero,
    formatear_resumen,
    verificar_preguntas,
)
from banco_occidente_corpus.tablero.tablas_web import (
    asistencia_vehicular,
    cuota_protegida,
    leer_tablas,
    promociones,
    proyectos_vivienda,
    viajes_nacionales,
)
from banco_occidente_corpus.tablero.tarifas import extraer_tarifario
from banco_occidente_corpus.tablero.tipos import COLUMNAS, escribir_filas, leer_filas
from banco_occidente_corpus.utils import write_jsonl

URL_VIAJES = "https://www.bancodeoccidente.com.co/asistencias-en-viajes-nacionales"
URL_TARJETAS = (
    "https://www.bancodeoccidente.com.co/tarjetas-credito/asistencias-tarjetas-de-credito"
)
URL_CUOTA = "https://www.bancodeoccidente.com.co/seguros/libranza/cuota-protegida"
URL_VEHICULAR = "https://www.bancodeoccidente.com.co/asistencia-vehicular"
URL_PROMOS = "https://www.bancodeoccidente.com.co/tarjetas-credito/promociones"
URL_VIVIENDA = "https://www.bancodeoccidente.com.co/proyectos-de-vivienda"
PAGINA = "data/gold/pages/pagina.md"
RAIZ = Path(__file__).resolve().parents[1]
ARCHIVO_PREGUNTAS = RAIZ / "config" / "evaluacion" / "preguntas_fase2.toml"
ARCHIVO_TABLERO = RAIZ / "data" / "estructurados" / "tablero.csv"


def make_config(tmp_path: Path) -> Config:
    """Configuración aislada con las rutas del corpus."""
    return Config(
        paths=Paths(
            root=tmp_path,
            raw=tmp_path / "data/raw",
            processed=tmp_path / "data/processed",
            gold=tmp_path / "data/gold",
            knowledge=tmp_path / "data/knowledge",
        )
    )


def fila(
    concepto: str,
    valor: str,
    *,
    moneda: str = "COP",
    periodicidad: str = "",
    fuente: str = URL_VIAJES,
) -> Fila:
    """Construye una fila del Tablero para las pruebas."""
    return Fila(
        concepto=concepto,
        categoria="prueba",
        valor=valor,
        moneda=moneda,
        recargos="",
        periodicidad=periodicidad,
        vigente_desde="",
        origen="tarifario",
        pagina=PAGINA,
        fuente=fuente,
    )


def test_escribir_filas_encabezado_utf8_e_idempotencia(tmp_path: Path) -> None:
    """El CSV tiene las diez columnas y dos escrituras son idénticas."""
    ruta = tmp_path / "tablero.csv"
    filas = [fila("Cuota de manejo", "16.700"), fila("Apertura", "0")]

    escribir_filas(ruta, filas)
    primera = ruta.read_bytes()
    escribir_filas(ruta, filas)

    assert ruta.read_bytes() == primera
    with ruta.open(encoding="utf-8", newline="") as fh:
        assert next(csv.reader(fh)) == list(COLUMNAS)
    assert "Cuota de manejo" in ruta.read_text(encoding="utf-8")


def test_leer_filas_devuelve_tipos(tmp_path: Path) -> None:
    """El CSV se puede releer como filas tipadas."""
    ruta = tmp_path / "tablero.csv"
    escribir_filas(ruta, [fila("Cuota", "16.700")])

    filas = leer_filas(ruta)

    assert filas == [fila("Cuota", "16.700")]


def test_tarifario_concepto_valor_y_fecha() -> None:
    """La línea canónica produce valor, moneda, fecha ISO y origen tarifario."""
    texto = (
        "Productos relacionados con Cuenta Corriente y Cuenta de Ahorros Comisión Vigente desde\n"
        "Cuota de Manejo Tarjeta Débito $16.700 20-nov-25\n"
    )

    filas = extraer_tarifario(texto, PAGINA, "https://tarifas")

    assert filas[0].concepto == "Cuota de Manejo Tarjeta Débito"
    assert filas[0].valor == "16.700"
    assert filas[0].moneda == "COP"
    assert filas[0].vigente_desde == "2025-11-20"
    assert filas[0].origen == "tarifario"
    assert filas[0].categoria.startswith("Productos relacionados")


def test_tarifario_conserva_recargos() -> None:
    """`+ IVA` y `+ Seguro2` se guardan aparte y no se suman al valor."""
    texto = (
        "Cheque de Gerencia $34.400 + IVA 20-nov-25\n"
        "Cuota de Manejo Especial $ 20.000 + Seguro2 20-nov-25\n"
    )

    filas = extraer_tarifario(texto, PAGINA, "https://tarifas")

    assert filas[0].valor == "34.400"
    assert filas[0].recargos == "+ IVA"
    assert filas[1].valor == "20.000"
    assert filas[1].recargos == "+ Seguro2"


def test_tarifario_sin_fecha_no_inventa_vigencia() -> None:
    """Una línea sin fecha queda con vigencia vacía."""
    filas = extraer_tarifario("Retiro en cajero $28.400\n", PAGINA, "https://tarifas")

    assert filas[0].vigente_desde == ""


def test_leer_tablas_respeta_pipes_escapados() -> None:
    """Un `\\|` dentro de una celda no rompe la tabla."""
    texto = "| Concepto | Valor |\n| --- | --- |\n| A \\| B | 10 |\n"

    tablas = leer_tablas(texto)

    assert tablas[0].encabezados == ("Concepto", "Valor")
    assert tablas[0].filas == (("A | B", "10"),)


def test_viajes_nacionales_extrae_usd() -> None:
    """Viajes nacionales produce USD 2.000 y USD 10.000 por franquicia."""
    texto = (
        "| # | Asistencia | Visa | Mastercard |\n"
        "| --- | --- | --- | --- |\n"
        "| 1 | Gastos médicos | USD 2.000 | USD 2.000 |\n"
        "| 3 | Traslados | USD 10.000 | USD 10.000 |\n"
    )

    filas = viajes_nacionales(texto, PAGINA, URL_VIAJES)

    valores = {(fila.valor, fila.moneda) for fila in filas}
    assert ("2.000", "USD") in valores
    assert ("10.000", "USD") in valores
    assert all(fila.fuente == URL_VIAJES for fila in filas)


def test_asistencias_tarjetas_extrae_eur() -> None:
    """La tabla de tarjetas conserva EUR 20.000."""
    texto = (
        "| Asistencias |  | Visa | Mastercard |\n"
        "| --- | --- | --- | --- |\n"
        "| 2 | Gastos médicos Schengen | EUR 20.000 | EUR 20.000 |\n"
    )

    filas = viajes_nacionales(texto, PAGINA, URL_TARJETAS)

    assert ("20.000", "EUR") in {(fila.valor, fila.moneda) for fila in filas}


def test_cuota_protegida_extrae_dias() -> None:
    """Los períodos de carencia quedan como 30 y 90 días."""
    texto = (
        "| Cobertura |  | Período de Carencia |\n"
        "| --- | --- | --- |\n"
        "| Desempleo |  | 30 días |\n"
        "| Enfermedades Graves |  | 90 días |\n"
    )

    filas = cuota_protegida(texto, PAGINA, URL_CUOTA)

    assert [(fila.concepto, fila.valor, fila.periodicidad) for fila in filas] == [
        ("Desempleo", "30", "días"),
        ("Enfermedades Graves", "90", "días"),
    ]


def test_asistencia_vehicular_extrae_doscientos() -> None:
    """La tabla de hogar produce USD 200 por evento."""
    texto = (
        "| # | Asistencia | Visa / Mastercard |  |\n"
        "| --- | --- | --- | --- |\n"
        "| 1 | Gastos menores de reparación | USD 200 / Por Evento |  |\n"
    )

    filas = asistencia_vehicular(texto, PAGINA, URL_VEHICULAR)

    assert filas[0].valor == "200"
    assert filas[0].moneda == "USD"
    assert filas[0].periodicidad == "por evento"


def test_promociones_extrae_porcentaje() -> None:
    """Una promoción con 20 % de descuento se guarda como valor 20 y moneda %."""
    texto = (
        "| Promoción |\n"
        "| --- |\n"
        "| Por compras en McDonald's recibirás un **20% de descuento** vigente. |\n"
    )

    filas = promociones(texto, PAGINA, URL_PROMOS)

    assert filas[0].valor == "20"
    assert filas[0].moneda == "%"
    assert "McDonald's" in filas[0].concepto


def test_proyectos_vivienda_extrae_precio() -> None:
    """El precio «desde $407,027,630» se conserva con moneda COP."""
    texto = (
        "## Apartamentos exclusivos\n"
        "| Proyecto ubicado en Calasanz con apartamentos desde $407,027,630 en obra gris. |\n"
    )

    filas = proyectos_vivienda(texto, PAGINA, URL_VIVIENDA)

    assert filas[0].valor == "407,027,630"
    assert filas[0].moneda == "COP"
    assert filas[0].concepto == "Apartamentos exclusivos"


def test_buscar_filas_ignora_tildes_y_mayusculas() -> None:
    """La búsqueda no distingue tildes ni mayúsculas."""
    filas = [fila("Cuota de Manejo Tarjeta Débito", "16.700"), fila("Apertura", "0")]

    assert [f.concepto for f in buscar_filas(filas, "CUOTA DE MANEJO")] == [
        "Cuota de Manejo Tarjeta Débito"
    ]
    assert buscar_filas(filas, "inexistente") == []


def test_buscar_filas_atiende_pregunta_natural() -> None:
    """Una pregunta con muletillas encuentra la fila por sus palabras clave."""
    filas = [
        fila("Cuota de Manejo Tarjeta Débito", "16.700"),
        fila("Cuota de Manejo Visa", "31.800"),
    ]

    encontradas = buscar_filas(filas, "¿Cuánto cuesta la cuota de manejo de la tarjeta débito?")

    assert [f.concepto for f in encontradas] == ["Cuota de Manejo Tarjeta Débito"]


def test_buscar_filas_compara_plurales_y_flexiones() -> None:
    """«desempleado» encuentra «Desempleo» y no arrastra filas de otra carencia."""
    filas = [fila("Desempleo", "30"), fila("Enfermedades Graves", "90")]

    assert [f.concepto for f in buscar_filas(filas, "¿Y si quedo desempleado?")] == ["Desempleo"]


def test_buscar_filas_sin_palabras_significativas_no_devuelve_todo() -> None:
    """Una consulta de solo artículos no se interpreta como «cualquier fila»."""
    filas = [fila("Apertura", "0")]

    assert buscar_filas(filas, "de la") == []
    assert buscar_filas(filas, "") == filas


def test_buscar_filas_encuentra_por_el_valor() -> None:
    """El buscador también compara el valor de la fila."""
    filas = [fila("Cuota de manejo", "16.700"), fila("Apertura", "0")]

    assert [f.concepto for f in buscar_filas(filas, "16.700")] == ["Cuota de manejo"]


def test_buscar_filas_no_mezcla_credito_y_debito() -> None:
    """Una pregunta de tarjeta de crédito no se responde con la de débito."""
    filas = [
        fila("Cuota de Manejo Tarjeta Débito", "16.700"),
        fila("Tarjeta Crédito Joven", "19.700"),
    ]

    encontradas = buscar_filas(filas, "cuota de manejo de la tarjeta de crédito")

    assert [f.concepto for f in encontradas] == ["Tarjeta Crédito Joven"]


def test_buscar_filas_entiende_europa_como_schengen() -> None:
    """«Europa» encuentra la cobertura de los países Schengen."""
    filas = [fila("Gastos médicos países Schengen (Visa)", "20.000", moneda="EUR")]

    assert [f.concepto for f in buscar_filas(filas, "¿Cuánto cubren en Europa?")] == [
        "Gastos médicos países Schengen (Visa)"
    ]


def test_filas_para_plantilla_prefiere_el_concepto_mas_corto() -> None:
    """«Cheque de Gerencia» gana sobre sus variantes más largas."""
    filas = [
        fila("Cheque de Gerencia", "34.400"),
        fila("Anulación o no utilización de Cheques de Gerencia", "5.500"),
        fila("Con Cheque de Gerencia", "29.000"),
    ]

    encontradas = filas_para_plantilla(filas, "¿Cuánto cuesta un cheque de gerencia?")

    assert [f.concepto for f in encontradas] == ["Cheque de Gerencia"]


def test_filas_para_plantilla_no_confunde_schengen_con_no_schengen() -> None:
    """La frase completa descarta la variante que niega la cobertura."""
    filas = [
        fila("Gastos médicos países Schengen (Visa)", "20.000", moneda="EUR"),
        fila("Gastos médicos países NO Schengen (Visa)", "20.000", moneda="USD"),
    ]

    encontradas = filas_para_plantilla(
        filas, "¿Cuánto cubre la tarjeta por gastos médicos en países Schengen?"
    )

    assert [f.concepto for f in encontradas] == ["Gastos médicos países Schengen (Visa)"]


def test_concepto_sin_franquicia_quita_el_sufijo() -> None:
    """El concepto base sirve para reconocer filas del mismo producto."""
    assert concepto_sin_franquicia("Gastos médicos (Mastercard)") == "gastos medicos"
    assert concepto_sin_franquicia("Cuota de manejo") == "cuota de manejo"


def test_viajes_nacionales_lee_la_tabla_internacional() -> None:
    """La tabla con columna de numeración toma el concepto correcto."""
    texto = (
        "| Asistencias |  | Visa | Mastercard |\n"
        "| --- | --- | --- | --- |\n"
        "| 1 | Gastos médicos países NO Schengen | USD 20.000 | USD 20.000 |\n"
        "| 2 | Gastos médicos países Schengen | EUR 20.000 | EUR 20.000 |\n"
    )

    filas = viajes_nacionales(texto, PAGINA, URL_TARJETAS)

    schengen = [fila for fila in filas if "Schengen" in fila.concepto and "NO" not in fila.concepto]
    assert {fila.concepto for fila in schengen} == {
        "Gastos médicos países Schengen (Visa)",
        "Gastos médicos países Schengen (Mastercard)",
    }
    assert all(fila.categoria == "asistencia de viajes al exterior" for fila in filas)
    assert {fila.moneda for fila in schengen} == {"EUR"}


def test_las_preguntas_de_tabla_encuentran_al_menos_una_fila() -> None:
    """Las 14 preguntas T del set dejan de caer en «tablero_sin_filas»."""
    preguntas = tomllib.loads(ARCHIVO_PREGUNTAS.read_text(encoding="utf-8"))["pregunta"]
    de_tabla = [pregunta for pregunta in preguntas if pregunta["ruta_esperada"] == "T"]
    filas = leer_filas(ARCHIVO_TABLERO)

    assert len(de_tabla) == 14
    for pregunta in de_tabla:
        encontradas = buscar_filas(filas, str(pregunta["pregunta"]))
        assert encontradas, f"la pregunta {pregunta['id']} no encontró filas"


def test_la_pregunta_41_encuentra_la_cuota_de_manejo() -> None:
    """La pregunta 41 devuelve la cuota de la tarjeta débito con su valor."""
    filas = leer_filas(ARCHIVO_TABLERO)

    encontradas = buscar_filas(filas, "¿Cuánto cuesta la cuota de manejo de la tarjeta débito?")

    assert [(f.concepto, f.valor) for f in encontradas] == [
        ("Cuota de Manejo Tarjeta Débito", "16.700")
    ]


def test_comparar_filas_visa_mastercard() -> None:
    """La comparación lista valores distintos y filas de un solo lado."""
    visa = [
        fila("Gastos médicos (Visa)", "2.000", moneda="USD"),
        fila("Equipaje (Visa)", "500", moneda="USD"),
    ]
    mastercard = [
        fila("Gastos médicos (Mastercard)", "2.500", moneda="USD"),
        fila("Hotel (Mastercard)", "100", moneda="USD"),
    ]

    comparacion = comparar_filas(visa, mastercard)

    assert [f.concepto for f in comparacion.solo_izquierda] == ["Equipaje (Visa)"]
    assert [f.concepto for f in comparacion.solo_derecha] == ["Hotel (Mastercard)"]
    assert comparacion.distintas[0][0].concepto == "Gastos médicos (Visa)"
    assert not comparacion.vacia


def test_comparar_filas_iguales_es_vacia() -> None:
    """Dos grupos equivalentes no producen diferencias."""
    filas = [fila("Cuota", "16.700")]

    assert comparar_filas(filas, filas).vacia


def test_verificar_preguntas_detecta_falta_de_fila() -> None:
    """Una pregunta sin filas de su fuente se reporta como falla."""
    preguntas = [
        {
            "id": "q1",
            "pregunta": "¿Cuánto cuesta?",
            "fuentes_esperadas": [URL_VIAJES],
            "terminos": [["2.000"]],
        }
    ]

    fallas = verificar_preguntas([fila("Otra", "1", fuente="https://otro.example")], preguntas)

    assert len(fallas) == 1
    assert "sin fila" in fallas[0].motivo


def test_verificar_preguntas_acepta_fila_con_termino() -> None:
    """Con fila de la fuente y el término, la pregunta pasa."""
    preguntas = [
        {
            "id": "q1",
            "pregunta": "¿Cuánto cuesta?",
            "fuentes_esperadas": [URL_VIAJES],
            "terminos": [["2.000", "2000"]],
        }
    ]

    assert verificar_preguntas([fila("Gastos médicos", "2.000")], preguntas) == []


def test_escribir_tablero_genera_csv_y_cubre_preguntas(tmp_path: Path) -> None:
    """Construye el CSV desde Gold local y verifica las preguntas de tabla."""
    config = make_config(tmp_path)
    preparar_gold(config)
    config.paths.root.mkdir(parents=True, exist_ok=True)
    preguntas = tmp_path / "config/evaluacion/preguntas_fase2.toml"
    preguntas.parent.mkdir(parents=True, exist_ok=True)
    preguntas.write_text(
        "[[pregunta]]\n"
        'id = "q1"\n'
        'pregunta = "¿Cobertura médica?"\n'
        'tipo = "tabla"\n'
        'fuentes_esperadas = ["' + URL_VIAJES + '"]\n'
        'terminos = [["2.000", "2000"]]\n',
        encoding="utf-8",
    )

    resumen = escribir_tablero(config)

    assert resumen.ruta.exists()
    assert resumen.preguntas == 1
    assert resumen.fallas == ()
    assert "1/1" in formatear_resumen(resumen)


def test_escribir_tablero_reporta_pregunta_sin_fila(tmp_path: Path) -> None:
    """Si la pregunta no tiene fila, el resumen lista la falla."""
    config = make_config(tmp_path)
    preparar_gold(config)
    preguntas = tmp_path / "config/evaluacion/preguntas_fase2.toml"
    preguntas.parent.mkdir(parents=True, exist_ok=True)
    preguntas.write_text(
        "[[pregunta]]\n"
        'id = "q9"\n'
        'pregunta = "¿Dato inexistente?"\n'
        'tipo = "tabla"\n'
        'fuentes_esperadas = ["https://otro.example"]\n'
        'terminos = [["999"]]\n',
        encoding="utf-8",
    )

    resumen = escribir_tablero(config)

    assert len(resumen.fallas) == 1
    assert "q9" in formatear_resumen(resumen)


def test_cargar_preguntas_tabla_solo_tipo_tabla(tmp_path: Path) -> None:
    """El cargador filtra las preguntas que no son de tabla."""
    config = make_config(tmp_path)
    ruta = tmp_path / "config/evaluacion/preguntas_fase2.toml"
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(
        '[[pregunta]]\nid = "a"\ntipo = "tabla"\n[[pregunta]]\nid = "b"\ntipo = "alcance"\n',
        encoding="utf-8",
    )

    assert [p["id"] for p in cargar_preguntas_tabla(config)] == ["a"]


def preparar_gold(config: Config) -> None:
    """Crea el tarifario y la página de viajes mínimos en tmp_path."""
    tarifario = config.paths.documents_gold / "ver-tarifas-2025-2025-a46157.md"
    tarifario.parent.mkdir(parents=True, exist_ok=True)
    tarifario.write_text("Cuota de Manejo Tarjeta Débito $16.700 20-nov-25\n", encoding="utf-8")
    pagina = config.paths.gold_markdown / "viajes.md"
    pagina.parent.mkdir(parents=True, exist_ok=True)
    pagina.write_text(
        "| # | Asistencia | Visa | Mastercard |\n"
        "| --- | --- | --- | --- |\n"
        "| 1 | Gastos médicos | USD 2.000 | USD 2.000 |\n",
        encoding="utf-8",
    )
    documentos: list[dict[str, Any]] = [
        {
            "id": "tarifario",
            "fuente": "https://www.bancodeoccidente.com.co/documents/d/guest/tarifas-persona-1",
            "archivo": "data/gold/documents/ver-tarifas-2025-2025-a46157.md",
        }
    ]
    write_jsonl(config.paths.documents_index, documentos)
    write_jsonl(
        config.paths.corpus_file,
        [
            {
                "id": "viajes",
                "fuente": URL_VIAJES,
                "archivo": "data/gold/pages/viajes.md",
            }
        ],
    )


def test_main_imprime_el_resumen(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """El punto de entrada devuelve 0 y reporta el CSV construido."""
    resumen = ResumenTablero(
        ruta=tmp_path / "tablero.csv",
        total=3,
        por_origen={"tarifario": 3},
        preguntas=1,
        fallas=(),
    )
    monkeypatch.setattr(
        "banco_occidente_corpus.tablero.__main__.escribir_tablero", lambda config: resumen
    )

    assert main() == 0
    assert "Tablero escrito" in capsys.readouterr().out


def test_main_devuelve_1_con_fallas(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Si una pregunta no se cubre, el punto de entrada falla y lo detalla."""
    resumen = ResumenTablero(
        ruta=tmp_path / "tablero.csv",
        total=1,
        por_origen={"tarifario": 1},
        preguntas=1,
        fallas=(Falla("q1", "¿Cuánto?", "sin fila con la fuente esperada"),),
    )
    monkeypatch.setattr(
        "banco_occidente_corpus.tablero.__main__.escribir_tablero", lambda config: resumen
    )

    assert main() == 1


def test_main_reporta_error_por_stderr(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Un error de lectura devuelve 1 y explica el motivo por stderr."""

    def fallar(config: Config) -> ResumenTablero:
        raise FileNotFoundError("falta el tarifario")

    monkeypatch.setattr("banco_occidente_corpus.tablero.__main__.escribir_tablero", fallar)

    assert main() == 1
    assert "falta el tarifario" in capsys.readouterr().err
