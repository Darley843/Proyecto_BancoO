"""Pruebas sin red del reporte del Arqueo: JSON, Markdown y determinismo.

Usa el banco real de 44 preguntas, revision humana real y un almacen en memoria
con embeddings `DeterministicFakeEmbedding`. No llama a Ollama ni a DeepSeek.
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from dataclasses import asdict
from pathlib import Path
from typing import Any

import pytest
from langchain_core.embeddings import DeterministicFakeEmbedding

from banco_occidente_corpus.arqueo.experimentos import (
    ARCHIVO_REVISION_V1,
    Barrido,
    barrer_pesos,
    cargar_preguntas_fase2,
    medir_configuracion,
    vectorial_directo,
)
from banco_occidente_corpus.arqueo.informe import (
    FichaCorrida,
    cargar_referencia_anexo_a,
    construir_arqueo,
    ejecutar_arqueo,
    render_markdown,
)
from banco_occidente_corpus.asistente.evaluacion import (
    ResultadoEvaluacion,
    cargar_revision,
)
from banco_occidente_corpus.boveda.almacen import Coincidencia
from banco_occidente_corpus.boveda.configuracion import ConfiguracionRecuperacion
from banco_occidente_corpus.boveda.fragmentos import ruta_fragmentos
from banco_occidente_corpus.boveda.tipos import Fragmento
from banco_occidente_corpus.config import PROJECT_ROOT, Config, Paths
from banco_occidente_corpus.utils import write_jsonl

URL_BASE = "https://www.bancodeoccidente.com.co"


class AlmacenFijo:
    """Almacen en memoria que devuelve los primeros fragmentos para toda consulta."""

    def __init__(self, fragmentos: Sequence[Fragmento]) -> None:
        self._coincidencias = [
            Coincidencia(
                id=fragmento.id,
                documento=fragmento.texto,
                metadatos={
                    "id": fragmento.id,
                    "url": fragmento.url,
                    "titulo": fragmento.titulo,
                    "seccion": fragmento.seccion,
                    "encabezado": fragmento.encabezado,
                    "tipo": fragmento.tipo,
                    "tokens": fragmento.tokens,
                },
                distancia=0.05 * posicion,
            )
            for posicion, fragmento in enumerate(fragmentos, start=1)
        ]

    def crear(self) -> None:
        """No hace nada: el almacen ya existe."""

    def agregar(
        self,
        ids: Sequence[str],
        vectores: Sequence[Sequence[float]],
        documentos: Sequence[str],
        metadatos: Sequence[dict[str, Any]],
    ) -> None:
        """No inserta: el doble se construye con los fragmentos."""

    def buscar(self, vector: Sequence[float], k: int = 5) -> list[Coincidencia]:
        """Devuelve el orden fijo recortado a k."""
        return self._coincidencias[:k]

    def contar(self) -> int:
        """Devuelve el numero de coincidencias."""
        return len(self._coincidencias)

    def reiniciar(self) -> None:
        """No hace nada."""


def fragmentos_de_prueba() -> list[Fragmento]:
    """Un fragmento por URL esperada, salvo las preguntas 41 a 44."""
    preguntas = cargar_preguntas_fase2()
    urls = sorted(
        {
            url
            for pregunta in preguntas
            if pregunta.id not in {41, 42, 43, 44}
            for url in pregunta.fuentes_esperadas
        }
    )
    return [
        Fragmento(
            id=f"frag:{posicion:04d}",
            texto=f"contenido de la fuente {posicion} sobre el banco",
            url=url,
            titulo="Fuente",
            seccion="oferta",
            encabezado="Productos",
            tipo="pagina",
            tokens=12,
        )
        for posicion, url in enumerate(urls, start=1)
    ]


def resultados_de_prueba() -> list[ResultadoEvaluacion]:
    """Resultados v1 sinteticos con uso y una fuente por pregunta."""
    preguntas = cargar_preguntas_fase2()
    return [
        ResultadoEvaluacion(
            id=pregunta.id,
            pregunta=pregunta.pregunta,
            cobertura=pregunta.cobertura,
            clasificacion="correcta",
            respuesta="respuesta",
            fuente=pregunta.fuentes_esperadas[0] if pregunta.fuentes_esperadas else "",
            sin_datos=False,
            terminos_encontrados=0,
            terminos_esperados=0,
            segundos=1.5,
            metricas={
                "uso": {
                    "input_tokens": 1000,
                    "output_tokens": 100,
                    "input_token_details": {"cache_read": 0},
                }
            },
        )
        for pregunta in preguntas
        if pregunta.tipo == "alcance"
    ]


def corrida_de_prueba() -> tuple[dict[str, Any], str, FichaCorrida]:
    """Ejecuta el barrido y arma el reporte con datos sinteticos."""
    preguntas = cargar_preguntas_fase2()
    fragmentos = fragmentos_de_prueba()
    almacen = AlmacenFijo(fragmentos)
    embeddings = DeterministicFakeEmbedding(size=16)
    barrido: Barrido = barrer_pesos(
        almacen,
        embeddings,
        fragmentos,
        preguntas,
        configuracion=ConfiguracionRecuperacion(k=5, peso_vectorial=0.6, peso_bm25=0.4),
    )
    sin_prefijos = medir_configuracion(
        almacen,
        embeddings,
        fragmentos,
        preguntas,
        etiqueta="0.6/0.4 sin prefijos",
        vectorial=0.6,
        bm25=0.4,
        prefijos=False,
    )
    arqueo = construir_arqueo(
        preguntas,
        barrido,
        sin_prefijos,
        revision_v1=cargar_revision(ARCHIVO_REVISION_V1),
        resultados_v1=resultados_de_prueba(),
        vectorial=vectorial_directo(almacen, embeddings, preguntas),
    )
    ficha = FichaCorrida(
        commit="abc1234",
        alcance="base",
        indice={
            "modelo": "nomic-embed-text-v2-moe",
            "prefijos": True,
            "fragmentos": len(fragmentos),
            "dimension": 16,
        },
        indice_sin_prefijos={
            "modelo": "nomic-embed-text-v2-moe",
            "prefijos": False,
            "fragmentos": len(fragmentos),
            "dimension": 16,
        },
        k=5,
        peso_vectorial=0.6,
        peso_bm25=0.4,
    )
    return arqueo, render_markdown(arqueo, ficha), ficha


def test_arqueo_conserva_las_cinco_claves_del_contrato() -> None:
    """Las claves del contrato siguen presentes y con su tipo."""
    # Act
    arqueo, _, _ = corrida_de_prueba()

    # Assert
    assert isinstance(arqueo["recuperacion"], list)
    assert set(arqueo["evaluacion"]) == {"v1", "v2"}
    assert {"b", "c", "n", "p", "excluidos"} <= set(arqueo["mcnemar"])
    assert {"v1_usd", "v2_usd", "preguntas"} <= set(arqueo["costo"])
    assert arqueo["preguntas_por_tipo"] == {
        "alcance": 20,
        "tabla": 12,
        "seguimiento": 6,
        "fuera": 6,
    }


def test_conteos_de_preguntas_evaluables_y_no_indexadas() -> None:
    """El reporte distingue Boveda, Tablero y fuentes ausentes del indice."""
    # Act
    arqueo, _, _ = corrida_de_prueba()

    # Assert
    assert arqueo["conteos"] == {
        "preguntas": 44,
        "con_fuente": 36,
        "evaluables_b": 22,
        "evaluables_t": 14,
        "no_indexadas": [41, 42, 43, 44],
    }
    assert any("41, 42, 43, 44" in aviso for aviso in arqueo["avisos"])
    assert any("tarifario" in aviso for aviso in arqueo["avisos"])


def test_mcnemar_pesos_principal_usa_las_22_de_ruta_b() -> None:
    """La comparacion principal son las preguntas de la Boveda."""
    # Act
    arqueo, _, _ = corrida_de_prueba()

    # Assert
    assert arqueo["mcnemar_pesos"]["preguntas"] == 22
    assert arqueo["mcnemar_pesos"]["principal"] is True
    assert arqueo["mcnemar_pesos_todas"]["preguntas"] == 36
    assert arqueo["mcnemar_pesos_todas"]["principal"] is False


def test_sin_revision_v2_el_reporte_lo_dice_y_no_falla() -> None:
    """Sin revision v2, la evaluacion v2 es nula y los 20 pares se excluyen."""
    # Act
    arqueo, texto, _ = corrida_de_prueba()

    # Assert
    assert arqueo["evaluacion"]["v2"] is None
    assert arqueo["mcnemar"]["excluidos"] == 20
    assert arqueo["mcnemar"]["n"] == 0
    assert any("revision_humana_v2.toml" in aviso for aviso in arqueo["avisos"])
    assert any("resultados_v2.jsonl" in aviso for aviso in arqueo["avisos"])
    assert "Pendiente" in texto


def test_evaluacion_v1_usa_la_revision_y_las_citas() -> None:
    """v1 resume aciertos, exactitud y citas de los resultados dados."""
    # Act
    arqueo, _, _ = corrida_de_prueba()

    # Assert
    v1 = arqueo["evaluacion"]["v1"]
    assert v1 is not None
    assert v1["total"] == 20
    assert v1["revisadas"] == 20
    assert v1["aciertos"] == 16
    assert v1["exactitud"] == 0.8
    assert v1["citas_correctas"] == 1.0


def test_costo_del_arqueo_es_cero_y_v1_tiene_costo_historico() -> None:
    """El Arqueo no gasta DeepSeek; v1 conserva su costo de evaluacion."""
    # Act
    arqueo, _, _ = corrida_de_prueba()

    # Assert
    assert arqueo["costo"]["arqueo_usd"] == 0.0
    assert arqueo["costo"]["preguntas"] == 44
    assert arqueo["costo"]["v1_usd"] > 0.0
    assert arqueo["costo"]["v2_usd"] is None
    assert arqueo["uso"]["v1"]["registros"] == 20
    assert arqueo["uso"]["v2"] is None


def test_render_es_determinista() -> None:
    """Dos renderizados con los mismos datos dan exactamente el mismo texto."""
    # Act
    arqueo, primera, ficha = corrida_de_prueba()
    segunda = render_markdown(arqueo, ficha)

    # Assert
    assert primera == segunda


def test_sin_fechas_ni_rutas_absolutas() -> None:
    """Ni el JSON ni el Markdown llevan fecha ISO ni rutas del equipo."""
    # Act
    arqueo, texto, _ = corrida_de_prueba()
    serializado = json.dumps(arqueo, ensure_ascii=False)
    absoluta = str(PROJECT_ROOT)

    # Assert
    assert not re.search(r"\b\d{4}-\d{2}-\d{2}\b", serializado)
    assert not re.search(r"\b\d{4}-\d{2}-\d{2}\b", texto)
    for ruta in (absoluta, "C:\\", "/home/", "/Users/"):
        assert ruta not in serializado
        assert ruta not in texto


def test_markdown_repite_las_cifras_del_json() -> None:
    """Cada hit@5, MRR e intervalo del JSON aparece en el Markdown."""
    # Act
    arqueo, texto, _ = corrida_de_prueba()

    # Assert
    for configuracion in arqueo["recuperacion"]:
        if configuracion["hit_at_5"] is not None:
            assert f"{configuracion['hit_at_5']:.4f}" in texto
        if configuracion["mrr"] is not None:
            assert f"{configuracion['mrr']:.4f}" in texto
        intervalo = configuracion["intervalo95"]
        if intervalo is not None:
            assert f"{intervalo[0]:.4f}" in texto
            assert f"{intervalo[1]:.4f}" in texto


def test_tabla_vectorial_frente_a_hibrido_tiene_una_fila_por_pregunta() -> None:
    """La tabla de posiciones cubre las 44 preguntas."""
    # Act
    _, texto, _ = corrida_de_prueba()
    seccion = texto.split("## Vectorial frente a hibrido, pregunta por pregunta", 1)[1]
    seccion = seccion.split("\n## ", 1)[0]
    filas = [
        linea
        for linea in seccion.splitlines()
        if linea.startswith("| ") and not linea.startswith("| #") and not linea.startswith("|---")
    ]

    # Assert
    assert len(filas) == 44
    assert "Vectorial 1/0" in texto
    assert "Hibrido por defecto" in texto


def test_referencia_anexo_a_incluye_esperado_y_medido() -> None:
    """La verificacion local muestra los valores del anexo A y los medidos."""
    # Act
    arqueo, texto, _ = corrida_de_prueba()

    # Assert
    referencia = arqueo["referencia_anexo_a"]
    assert referencia["esperado"]["1/0"]["hit_at_5"] == 0.64
    assert referencia["esperado"]["por_defecto"]["mrr"] == 0.48
    assert set(referencia["medido"]) == {"1/0", "por_defecto"}
    assert "Verificacion local contra el anexo A" in texto


def test_referencia_anexo_a_carga_un_toml_alternativo(tmp_path: Path) -> None:
    """La referencia se puede cargar desde un TOML distinto del del proyecto."""
    # Arrange
    archivo = tmp_path / "referencia_alternativa.toml"
    archivo.write_text(
        '[referencia_anexo_a."1/0"]\n'
        "hit_at_5 = 0.5\n"
        "mrr = 0.25\n"
        "\n"
        "[referencia_anexo_a.por_defecto]\n"
        "hit_at_5 = 0.75\n"
        "mrr = 0.5\n",
        encoding="utf-8",
    )

    # Act
    referencia = cargar_referencia_anexo_a(archivo)

    # Assert
    assert referencia == {
        "1/0": {"hit_at_5": 0.5, "mrr": 0.25},
        "por_defecto": {"hit_at_5": 0.75, "mrr": 0.5},
    }


def test_referencia_anexo_a_falla_si_falta_y_muestra_la_ruta(tmp_path: Path) -> None:
    """Sin el TOML, el error dice que archivo falta."""
    # Arrange
    archivo = tmp_path / "no-existe.toml"

    # Act / Assert
    with pytest.raises(FileNotFoundError) as error:
        cargar_referencia_anexo_a(archivo)
    assert str(archivo) in str(error.value)


def test_dos_corridas_dan_el_mismo_json_y_el_mismo_markdown() -> None:
    """Dos corridas con los mismos datos dan el mismo JSON y el mismo Markdown."""
    # Act
    primer_arqueo, primer_texto, _ = corrida_de_prueba()
    segundo_arqueo, segundo_texto, _ = corrida_de_prueba()
    primer_json = json.dumps(primer_arqueo, ensure_ascii=False)
    segundo_json = json.dumps(segundo_arqueo, ensure_ascii=False)

    # Assert
    assert primer_json == segundo_json
    assert primer_texto == segundo_texto
    for salida in (primer_json, primer_texto):
        assert not re.search(r"\b\d{4}-\d{2}-\d{2}\b", salida)
        assert str(PROJECT_ROOT) not in salida


def preparar_arqueo(tmp_path: Path) -> Config:
    """Prepara un corpus minimo y el indice principal para ejecutar el Arqueo."""
    config = Config(
        paths=Paths(
            root=tmp_path,
            raw=tmp_path / "data/raw",
            processed=tmp_path / "data/processed",
            gold=tmp_path / "data/gold",
            knowledge=tmp_path / "data/knowledge",
        )
    )
    fragmentos = fragmentos_de_prueba()
    write_jsonl(
        ruta_fragmentos(config, "base"),
        [asdict(fragmento) for fragmento in fragmentos],
    )
    carpeta = tmp_path / "data" / "boveda"
    carpeta.mkdir(parents=True, exist_ok=True)
    metadatos = {
        "modelo": "nomic-embed-text-v2-moe",
        "prefijos": True,
        "alcance": "base",
        "fragmentos": len(fragmentos),
        "dimension": 16,
    }
    (carpeta / "indice.json").write_text(
        json.dumps(metadatos, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return config


def test_el_estado_del_indice_extra_no_cambia_los_reportes(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Un indice extra nuevo y otro reconstruido dan el mismo JSON y Markdown."""
    # Arrange
    config = preparar_arqueo(tmp_path)
    fragmentos = fragmentos_de_prueba()
    embeddings = DeterministicFakeEmbedding(size=16)
    primer_json = tmp_path / "primero.json"
    primer_md = tmp_path / "primero.md"
    segundo_json = tmp_path / "segundo.json"
    segundo_md = tmp_path / "segundo.md"

    # Act
    ejecutar_arqueo(
        config,
        alcance="base",
        commit="abc1234",
        salida_json=primer_json,
        salida_md=primer_md,
        embeddings=embeddings,
        almacen=AlmacenFijo(fragmentos),
        almacen_sin_prefijos=AlmacenFijo(fragmentos),
    )
    primer_aviso = capsys.readouterr().out
    ejecutar_arqueo(
        config,
        alcance="base",
        commit="abc1234",
        salida_json=segundo_json,
        salida_md=segundo_md,
        embeddings=embeddings,
        almacen=AlmacenFijo(fragmentos),
        almacen_sin_prefijos=AlmacenFijo(fragmentos),
        reconstruir_sin_prefijos=True,
    )
    segundo_aviso = capsys.readouterr().out

    # Assert
    assert primer_json.read_bytes() == segundo_json.read_bytes()
    assert primer_md.read_bytes() == segundo_md.read_bytes()
    assert "se construyo en esta corrida" in primer_aviso
    assert "ya existia" in segundo_aviso
