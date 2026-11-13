"""Pruebas sin red del reporte del Arqueo: JSON, Markdown y determinismo.

Usa el banco real de 44 preguntas, revision humana real y un almacen en memoria
con embeddings `DeterministicFakeEmbedding`. No llama a Ollama ni a DeepSeek.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import asdict
from pathlib import Path
from typing import Any

import pytest
from langchain_core.embeddings import DeterministicFakeEmbedding

from banco_occidente_corpus.arqueo.experimentos import (
    ARCHIVO_REVISION_V1,
    ARCHIVO_REVISION_V2,
    Barrido,
    barrer_pesos,
    cargar_preguntas_fase2,
    medir_configuracion,
    vectorial_directo,
)
from banco_occidente_corpus.arqueo.informe import (
    ARCHIVO_RESULTADOS_V1,
    ARCHIVO_RESULTADOS_V2,
    FichaCorrida,
    Sensibilidad,
    cargar_referencia_anexo_a,
    cargar_sensibilidad,
    construir_arqueo,
    contar_preguntas_con_clasificador,
    ejecutar_arqueo,
    render_markdown,
)
from banco_occidente_corpus.asistente.evaluacion import (
    ResultadoEvaluacion,
    Revision,
    cargar_resultados,
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

    def buscar(
        self,
        vector: Sequence[float],
        k: int = 5,
        filtro: Mapping[str, Any] | None = None,
    ) -> list[Coincidencia]:
        """Devuelve el orden fijo recortado a k."""
        return self._coincidencias[:k]

    def vectores(self, ids: Sequence[str]) -> dict[str, list[float]]:
        """No guarda vectores: el recuperador los calcula con sus embeddings."""
        return {}

    def contar(self) -> int:
        """Devuelve el numero de coincidencias."""
        return len(self._coincidencias)

    def reiniciar(self) -> None:
        """No hace nada."""

    def cerrar(self) -> None:
        """No hace nada: el doble vive en memoria y no tiene cliente que liberar."""


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


def resultado_con_motivo(identificador: int, motivo: str | None) -> ResultadoEvaluacion:
    """Fila minima de v2 con el motivo guardado en ``metricas``."""
    return ResultadoEvaluacion(
        id=identificador,
        pregunta="pregunta",
        cobertura="si",
        clasificacion="correcta",
        respuesta="",
        fuente="",
        sin_datos=False,
        metricas={"motivo": motivo},
    )


def corrida_de_prueba(
    *,
    revision_v1: Mapping[int, Revision] | None = None,
    resultados_v1: Sequence[ResultadoEvaluacion] | None = None,
    resultados_v2: Sequence[ResultadoEvaluacion] = (),
    revision_v2: Mapping[int, Revision] | None = None,
    sensibilidad: Sensibilidad | None = None,
) -> tuple[dict[str, Any], str, FichaCorrida]:
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
        revision_v1=(
            revision_v1 if revision_v1 is not None else cargar_revision(ARCHIVO_REVISION_V1)
        ),
        revision_v2=revision_v2,
        resultados_v1=resultados_v1 if resultados_v1 is not None else resultados_de_prueba(),
        resultados_v2=resultados_v2,
        vectorial=vectorial_directo(almacen, embeddings, preguntas),
        sensibilidad=sensibilidad,
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


def corrida_con_v2() -> tuple[dict[str, Any], str, FichaCorrida]:
    """Arma el reporte con los resultados y la revision reales de v2."""
    return corrida_de_prueba(
        resultados_v1=cargar_resultados(ARCHIVO_RESULTADOS_V1),
        resultados_v2=cargar_resultados(ARCHIVO_RESULTADOS_V2),
        revision_v2=cargar_revision(ARCHIVO_REVISION_V2),
        sensibilidad=cargar_sensibilidad(ARCHIVO_REVISION_V2),
    )


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
    """Cada hit@5, MRR, recall@10, nDCG@10 e intervalo aparece en el Markdown."""
    # Act
    arqueo, texto, _ = corrida_de_prueba()

    # Assert
    assert "recall@10" in texto
    assert "nDCG@10" in texto
    for configuracion in arqueo["recuperacion"]:
        if configuracion["hit_at_5"] is not None:
            assert f"{configuracion['hit_at_5']:.4f}" in texto
        if configuracion["mrr"] is not None:
            assert f"{configuracion['mrr']:.4f}" in texto
        if configuracion["recall_at_10"] is not None:
            assert f"{configuracion['recall_at_10']:.4f}" in texto
        if configuracion["ndcg_at_10"] is not None:
            assert f"{configuracion['ndcg_at_10']:.4f}" in texto
        intervalo = configuracion["intervalo95"]
        if intervalo is not None:
            assert f"{intervalo[0]:.4f}" in texto
            assert f"{intervalo[1]:.4f}" in texto


def test_json_incluye_recall_y_ndcg_en_todas_las_configuraciones() -> None:
    """Las métricas nuevas están en el total, por tipo y sin el Tablero."""
    # Act
    arqueo, _, _ = corrida_de_prueba()

    # Assert
    for configuracion in arqueo["recuperacion"]:
        assert {"recall_at_10", "ndcg_at_10"} <= set(configuracion)
        assert {"recall_at_10", "ndcg_at_10"} <= set(configuracion["sin_tablero"])
        for metricas in configuracion["por_tipo"].values():
            assert {"recall_at_10", "ndcg_at_10"} <= set(metricas)


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


def test_v2_citas_cuentan_las_fuentes_citadas_y_no_solo_la_primera() -> None:
    """Una URL esperada que no es la primera fuente citada tambien cuenta en v2."""
    # Arrange
    resultados = cargar_resultados(ARCHIVO_RESULTADOS_V2)
    pregunta_12 = next(resultado for resultado in resultados if resultado.id == 12)

    # Act
    arqueo, _, _ = corrida_de_prueba(
        resultados_v2=[pregunta_12],
        revision_v2=cargar_revision(ARCHIVO_REVISION_V2),
    )

    # Assert
    esperada = "https://www.bancodeoccidente.com.co/sistema-kubo"
    assert pregunta_12.fuente != esperada
    assert esperada in pregunta_12.metricas["fuentes"]
    v2 = arqueo["evaluacion"]["v2"]
    assert v2 is not None
    assert v2["citas_correctas"] == 1.0


def test_v2_con_los_datos_reales_da_citas_de_05556() -> None:
    """La revision y los resultados reales de v2 producen la cifra del informe."""
    # Act
    arqueo, _, _ = corrida_con_v2()

    # Assert
    v2 = arqueo["evaluacion"]["v2"]
    assert v2 is not None
    assert v2["aciertos"] == 11
    assert v2["total"] == 20
    assert v2["exactitud"] == 0.55
    assert v2["citas_correctas"] == 0.5556
    assert arqueo["mcnemar"]["b"] == 5
    assert arqueo["mcnemar"]["c"] == 0
    assert arqueo["mcnemar"]["n"] == 5
    assert arqueo["mcnemar"]["p"] == 0.0625


def test_costo_de_alcance_es_cota_inferior_y_el_ahorro_es_un_maximo() -> None:
    """El costo de v2 en alcance se midio antes del #93 y es una cota historica."""
    # Act
    arqueo, texto, _ = corrida_con_v2()
    costo = arqueo["costo"]

    # Assert
    assert costo["v2_alcance_usd"] == 0.011873
    assert costo["v2_usd"] == 0.015728
    assert costo["v2_alcance_cota_inferior"] is True
    assert costo["v2_total_cota_inferior"] is True
    assert costo["v2_alcance_con_clasificador"] == 15
    assert costo["v2_alcance_sin_motivo"] == 0
    assert costo["ahorro_alcance_pct"] == 57.0
    seccion = texto.split("## Costo y uso", 1)[1].split("\n## ", 1)[0]
    limites = texto.split("## Limites", 1)[1].split("\n## ", 1)[0]
    assert "cota inferior" in seccion
    assert "antes del arreglo del #93" in seccion
    assert "hasta 57.0 % menos" in seccion
    assert "15 de las 20" in seccion
    assert "completa" not in seccion
    assert "cota inferior historica" in limites
    assert "antes del arreglo del #93" in limites


def test_contar_preguntas_con_clasificador_lee_el_motivo_guardado() -> None:
    """Clasifica por motivo: regla, clasificador y filas sin motivo aparte."""
    # Arrange
    resultados = [
        resultado_con_motivo(1, "identidad"),
        resultado_con_motivo(2, "tarifas"),
        resultado_con_motivo(3, "tablero_generico"),
        resultado_con_motivo(4, "Consulta general sobre productos."),
        resultado_con_motivo(5, ""),
        resultado_con_motivo(6, None),
        resultado_con_motivo(7, "Consulta general fuera del alcance de la prueba."),
    ]

    # Act
    conteo = contar_preguntas_con_clasificador(resultados, [1, 2, 3, 4, 5, 6, 7])

    # Assert
    assert conteo.con_clasificador == 2
    assert conteo.sin_motivo == 2


def test_conteo_real_de_clasificador_sigue_dando_15_de_20() -> None:
    """Con los motivos reales de v2, 15 preguntas pasaron por el clasificador."""
    # Arrange
    preguntas = cargar_preguntas_fase2()
    ids = [pregunta.id for pregunta in preguntas if pregunta.tipo == "alcance"]

    # Act
    conteo = contar_preguntas_con_clasificador(cargar_resultados(ARCHIVO_RESULTADOS_V2), ids)

    # Assert
    assert conteo.con_clasificador == 15
    assert conteo.sin_motivo == 0


def test_sensibilidad_cambia_solo_el_escenario_alterno() -> None:
    """La nota de Nayla no toca el veredicto principal ni la segunda firma."""
    # Act
    arqueo, texto, _ = corrida_con_v2()
    sensibilidad = arqueo["sensibilidad"]

    # Assert
    assert sensibilidad is not None
    assert sensibilidad["revisor"] == "Nayla Ledesma"
    assert sensibilidad["cambios"] == [
        {
            "id": 2,
            "de": "incorrecta",
            "a": "rechazo_correcto",
            "nota": (
                "El corpus solo cita la Carrera 3 No. 8-13 de Cali como lugar de la "
                "asamblea de accionistas; no dice que sea una oficina, asi que no "
                "encontrar el dato es un rechazo correcto."
            ),
        }
    ]
    evaluacion = sensibilidad["evaluacion"]
    alterno = sensibilidad["mcnemar"]
    assert evaluacion is not None
    assert evaluacion["aciertos"] == 12
    assert evaluacion["exactitud"] == 0.6
    assert alterno["b"] == 5
    assert alterno["c"] == 1
    assert alterno["n"] == 6
    assert alterno["p"] == 0.21875
    assert alterno["p_minimo"] == 0.03125
    assert arqueo["evaluacion"]["v2"]["aciertos"] == 11
    assert arqueo["mcnemar"]["b"] == 5
    assert arqueo["mcnemar"]["c"] == 0
    revision = cargar_revision(ARCHIVO_REVISION_V2)
    assert revision[2].veredicto == "incorrecta"
    assert revision[2].veredicto_2 == "incorrecta"
    assert revision[2].revisor_2 == "Darley843"
    assert "## Sensibilidad de la revision humana" in texto
    assert "Nayla Ledesma" in texto
    assert "0.218750" in texto
    assert "0.031250" in texto


def test_mcnemar_explica_aciertos_discordantes_y_p_minimo() -> None:
    """El caso real dice 16 y 11 de 20, favorece a v1 y explica el p minimo."""
    # Act
    arqueo, texto, _ = corrida_con_v2()
    mcnemar = arqueo["mcnemar"]
    seccion = texto.split("## McNemar v1 frente a v2", 1)[1].split("\n## ", 1)[0]

    # Assert
    assert mcnemar["p"] == 0.0625
    assert mcnemar["p_minimo"] == 0.0625
    assert "16 de 20" in seccion
    assert "11 de 20" in seccion
    assert "favorece a v1" in seccion
    assert "2·(1/2)^5" in seccion
    assert "umbral de 0.05" in seccion
    assert "ningun reparto de esos pares podria ser significativo" in seccion
    assert "mejora" not in seccion
    assert "ALFA" not in seccion
    assert "0.050000" not in seccion


def test_lectura_del_mcnemar_es_identica_en_json_y_markdown() -> None:
    """La frase guardada en el JSON es exactamente la que imprime el Markdown."""
    # Act
    arqueo, texto, _ = corrida_con_v2()
    principal = arqueo["mcnemar"]["lectura"]
    alterno = arqueo["sensibilidad"]["mcnemar"]["lectura"]

    # Assert
    assert isinstance(principal, str)
    assert isinstance(alterno, str)
    seccion = texto.split("## McNemar v1 frente a v2", 1)[1].split("\n## ", 1)[0]
    assert principal in seccion
    seccion_sensibilidad = texto.split("## Sensibilidad de la revision humana", 1)[1]
    seccion_sensibilidad = seccion_sensibilidad.split("\n## ", 1)[0]
    assert alterno in seccion_sensibilidad


def test_mcnemar_con_c_mayor_que_b_dice_favorece_a_v2() -> None:
    """Con c>b y p<0.05 el parrafo declara la direccion hacia v2."""
    # Arrange
    preguntas = cargar_preguntas_fase2()
    ids = [pregunta.id for pregunta in preguntas if pregunta.tipo == "alcance"]
    revision_v1 = {identificador: Revision(veredicto="incorrecta") for identificador in ids}
    revision_v2 = {
        identificador: Revision(veredicto="correcta" if identificador <= 6 else "incorrecta")
        for identificador in ids
    }

    # Act
    arqueo, texto, _ = corrida_de_prueba(
        revision_v1=revision_v1,
        revision_v2=revision_v2,
        resultados_v2=cargar_resultados(ARCHIVO_RESULTADOS_V2),
    )
    mcnemar = arqueo["mcnemar"]
    seccion = texto.split("## McNemar v1 frente a v2", 1)[1].split("\n## ", 1)[0]

    # Assert
    assert mcnemar["b"] == 0
    assert mcnemar["c"] == 6
    assert mcnemar["p"] < 0.05
    assert "favorece a v2" in seccion
    assert "diferencia es significativa" in seccion
    assert "mejora" not in seccion


def test_cargar_sensibilidad_lee_la_tabla_del_proyecto() -> None:
    """La tabla [sensibilidad] del TOML real trae el revisor y el cambio."""
    # Act
    sensibilidad = cargar_sensibilidad(ARCHIVO_REVISION_V2)

    # Assert
    assert sensibilidad is not None
    assert sensibilidad.revisor == "Nayla Ledesma"
    assert [cambio.id for cambio in sensibilidad.cambios] == [2]
    assert sensibilidad.cambios[0].veredicto == "rechazo_correcto"
    assert "Carrera 3 No. 8-13" in sensibilidad.cambios[0].nota


def test_cargar_sensibilidad_sin_tabla_devuelve_none(tmp_path: Path) -> None:
    """Un TOML de revision sin [sensibilidad] no inventa un escenario."""
    # Arrange
    archivo = tmp_path / "revision.toml"
    archivo.write_text(
        '[[revision]]\nid = 1\nveredicto = "correcta"\nrevisor = "Alguien"\n',
        encoding="utf-8",
    )

    # Act
    sensibilidad = cargar_sensibilidad(archivo)

    # Assert
    assert sensibilidad is None


def test_cargar_sensibilidad_rechaza_un_veredicto_desconocido(tmp_path: Path) -> None:
    """Un veredicto fuera de VEREDICTOS se rechaza con la ruta en el mensaje."""
    # Arrange
    archivo = tmp_path / "revision.toml"
    archivo.write_text(
        "[sensibilidad]\n"
        'revisor = "Nayla Ledesma"\n'
        "\n"
        "[[sensibilidad.cambio]]\n"
        "id = 2\n"
        'veredicto = "inventado"\n',
        encoding="utf-8",
    )

    # Act / Assert
    with pytest.raises(ValueError) as error:
        cargar_sensibilidad(archivo)
    assert str(archivo) in str(error.value)
