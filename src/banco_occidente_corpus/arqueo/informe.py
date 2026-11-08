"""Informe del Arqueo: construye ``arqueo.json`` y ``docs/ARQUEO.md``.

El JSON conserva las cinco claves del contrato de ``design.md`` y agrega solo
claves nuevas (``uso``, ``mcnemar_pesos``, ``detalle``, ``conteos``, ``avisos``,
``referencia_anexo_a`` y ``sensibilidad``). Cada bloque de McNemar incluye
``p_minimo`` y ``alfa``. El costo de v2, tanto el total como el de las 20
preguntas de alcance, es una cota inferior: cuenta el turno de respuesta pero no
el clasificador de dudas ni la reformulacion (#93); el numero de preguntas que
usaron el clasificador sale del motivo registrado en `resultados_v2.jsonl`, no
de una constante.
``citas_correctas`` de v1 usa ``resultado.fuente`` y la de v2 usa
``metricas["fuentes"]``, asi que no se comparan entre versiones.

El Markdown se genera del mismo diccionario y con el mismo redondeo, para que
las cifras coincidan y dos corridas identicas den los mismos bytes. Ninguna
salida lleva fecha ni rutas absolutas. El modulo no llama a DeepSeek: como mucho
usa Ollama para los embeddings locales.
"""

from __future__ import annotations

import json
import tomllib
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any

from langchain_core.embeddings import Embeddings

from ..asistente.evaluacion import (
    VEREDICTOS,
    ResultadoEvaluacion,
    Revision,
    cargar_resultados,
    cargar_revision,
)
from ..boveda.almacen import AlmacenVectorial, ChromaAlmacen
from ..boveda.configuracion import (
    cargar_configuracion_embeddings,
    cargar_configuracion_recuperacion,
)
from ..boveda.embeddings import crear_embeddings
from ..boveda.fragmentos import Alcance
from ..boveda.indice import leer_fragmentos, leer_metadatos, ruta_almacen
from ..config import PROJECT_ROOT, Config
from .cache_embeddings import EmbeddingsEnCache
from .experimentos import (
    ARCHIVO_REVISION_V1,
    ARCHIVO_REVISION_V2,
    Barrido,
    MetricasRecuperacion,
    PreguntaFase2,
    ResultadoConfiguracion,
    aciertos_por_revision,
    barrer_pesos,
    cargar_preguntas_fase2,
    carpeta_sin_prefijos,
    comparar_pesos,
    comparar_versiones,
    construir_indice_sin_prefijos,
    diferencias_vectorial_directo,
    etiqueta_pesos,
    ids_por_ruta,
    medir_configuracion,
    vectorial_directo,
)
from .metricas import (
    ALFA,
    ResultadoMcNemar,
    ResumenUso,
    citas_correctas,
    exactitud,
    p_minimo_mcnemar,
    resumen_uso,
)

#: Reporte legible por personas.
SALIDA_MD: Path = PROJECT_ROOT / "docs" / "ARQUEO.md"
#: Reporte para la app y las pruebas de forma.
SALIDA_JSON: Path = PROJECT_ROOT / "data" / "evaluacion" / "arqueo.json"
#: Resultados de la evaluacion v1 (respuestas del modelo).
ARCHIVO_RESULTADOS_V1: Path = PROJECT_ROOT / "data" / "evaluacion" / "resultados.jsonl"
#: Resultados de la evaluacion v2; puede no existir todavia.
ARCHIVO_RESULTADOS_V2: Path = PROJECT_ROOT / "data" / "evaluacion" / "resultados_v2.jsonl"

#: Ruta versionada de la referencia medida por el grupo con el script del anexo A.
RUTA_REFERENCIA_ANEXO_A: Path = PROJECT_ROOT / "config" / "evaluacion" / "referencia_anexo_a.toml"
#: Decimales del reporte para proporciones y para probabilidades.
DECIMALES: int = 4
#: Decimales del reporte para costo en USD.
DECIMALES_COSTO: int = 6


def cargar_referencia_anexo_a(ruta: Path | None = None) -> dict[str, dict[str, float]]:
    """Carga la referencia del anexo A desde un TOML.

    Los valores se midieron con el indice de 846 fragmentos, sin los 81 de PDF
    (ver PR #78). No son un umbral: solo sirven para verificar la corrida local.

    Args:
        ruta: TOML alternativo; por defecto
            ``config/evaluacion/referencia_anexo_a.toml``.

    Returns:
        Los valores esperados por configuracion: ``1/0`` y ``por_defecto``.

    Raises:
        FileNotFoundError: si falta el archivo, con la ruta en el mensaje.
        ValueError: si el TOML no trae las dos configuraciones o sus cifras.
    """
    archivo = ruta or RUTA_REFERENCIA_ANEXO_A
    if not archivo.exists():
        raise FileNotFoundError(
            f"No existe la referencia del anexo A: {archivo}. "
            "Crea config/evaluacion/referencia_anexo_a.toml."
        )
    datos: dict[str, Any] = tomllib.loads(archivo.read_text(encoding="utf-8"))
    bloque = datos.get("referencia_anexo_a")
    if not isinstance(bloque, dict):
        raise ValueError(f"{archivo}: falta la tabla [referencia_anexo_a]")

    referencia: dict[str, dict[str, float]] = {}
    for nombre in ("1/0", "por_defecto"):
        fila = bloque.get(nombre)
        if not isinstance(fila, dict):
            raise ValueError(f'{archivo}: falta la tabla [referencia_anexo_a."{nombre}"]')
        valores: dict[str, float] = {}
        for metrica in ("hit_at_5", "mrr"):
            valor = fila.get(metrica)
            if isinstance(valor, bool) or not isinstance(valor, (int, float)):
                raise ValueError(f"{archivo}: {nombre}.{metrica} debe ser un numero")
            valores[metrica] = float(valor)
        referencia[nombre] = valores
    return referencia


@dataclass(frozen=True, slots=True)
class CambioSensibilidad:
    """Cambio de veredicto de un escenario de sensibilidad."""

    id: int
    veredicto: str
    nota: str = ""


@dataclass(frozen=True, slots=True)
class Sensibilidad:
    """Escenario alterno de la revision humana.

    No reemplaza el veredicto principal ni la segunda firma: solo se aplica al
    bloque ``sensibilidad`` del reporte.
    """

    revisor: str
    cambios: tuple[CambioSensibilidad, ...] = ()


@dataclass(frozen=True, slots=True)
class ConteoClasificador:
    """Preguntas de alcance resueltas con clasificador y filas sin motivo."""

    con_clasificador: int
    sin_motivo: int


def cargar_sensibilidad(ruta: Path | None = None) -> Sensibilidad | None:
    """Carga la tabla ``[sensibilidad]`` de la revision humana v2.

    El escenario se declara con ``[[sensibilidad.cambio]]``: cada fila trae
    ``id``, ``veredicto`` y una ``nota`` corta. El veredicto principal y la
    segunda firma del archivo no se modifican.

    Args:
        ruta: TOML alternativo; por defecto
            ``config/evaluacion/revision_humana_v2.toml``.

    Returns:
        El escenario cargado, o ``None`` si el archivo o la tabla no existen.

    Raises:
        ValueError: si el TOML es invalido, falta el revisor, un cambio no
            tiene id entero, repite un id o usa un veredicto desconocido.
    """
    archivo = ruta or ARCHIVO_REVISION_V2
    if not archivo.exists():
        return None
    try:
        datos: dict[str, Any] = tomllib.loads(archivo.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise ValueError(f"TOML invalido en {archivo}: {exc}") from exc

    bloque = datos.get("sensibilidad")
    if not isinstance(bloque, dict):
        return None
    revisor = str(bloque.get("revisor", "")).strip()
    if not revisor:
        raise ValueError(f"{archivo}: [sensibilidad] sin revisor")
    filas = bloque.get("cambio", [])
    if not isinstance(filas, list):
        raise ValueError(f"{archivo}: 'sensibilidad.cambio' debe ser una lista de tablas")

    cambios: list[CambioSensibilidad] = []
    vistos: set[int] = set()
    for fila in filas:
        if not isinstance(fila, dict):
            raise ValueError(f"{archivo}: cada cambio de sensibilidad debe ser una tabla")
        identificador = fila.get("id")
        if not isinstance(identificador, int) or isinstance(identificador, bool):
            raise ValueError(f"{archivo}: cambio de sensibilidad sin id entero")
        if identificador in vistos:
            raise ValueError(f"{archivo}: id {identificador} repetido en sensibilidad")
        veredicto = str(fila.get("veredicto", "")).strip()
        if veredicto not in VEREDICTOS:
            raise ValueError(
                f"{archivo}: sensibilidad {identificador} tiene veredicto "
                f"'{veredicto}', que no es uno de {tuple(VEREDICTOS)}"
            )
        vistos.add(identificador)
        cambios.append(
            CambioSensibilidad(
                id=identificador,
                veredicto=veredicto,
                nota=str(fila.get("nota", "")).strip(),
            )
        )
    return Sensibilidad(
        revisor=revisor,
        cambios=tuple(sorted(cambios, key=lambda cambio: cambio.id)),
    )


@dataclass(frozen=True, slots=True)
class FichaCorrida:
    """Procedencia de una corrida: commit, indices y configuracion."""

    commit: str
    alcance: str
    indice: Mapping[str, Any]
    indice_sin_prefijos: Mapping[str, Any]
    k: int
    peso_vectorial: float
    peso_bm25: float
    confianza: float = 0.95
    ruta_indice: str = "data/boveda/indice.json"
    ruta_indice_sin_prefijos: str = "data/boveda/experimentos/sin_prefijos/indice.json"


def ejecutar_arqueo(
    config: Config,
    *,
    alcance: Alcance = "base",
    commit: str = "",
    archivo_preguntas: Path | None = None,
    archivo_revision_v1: Path | None = None,
    archivo_revision_v2: Path | None = None,
    archivo_resultados_v1: Path | None = None,
    archivo_resultados_v2: Path | None = None,
    salida_json: Path | None = None,
    salida_md: Path | None = None,
    embeddings: Embeddings | None = None,
    almacen: AlmacenVectorial | None = None,
    almacen_sin_prefijos: AlmacenVectorial | None = None,
    reconstruir_sin_prefijos: bool = False,
) -> tuple[dict[str, Any], str]:
    """Ejecuta el barrido, escribe los dos reportes y devuelve sus contenidos.

    No llama a DeepSeek: los embeddings son locales o se inyectan. El costo del
    Arqueo es cero; el costo de v1 y v2 es el historico de sus evaluaciones.

    Args:
        config: configuracion con las rutas del corpus.
        alcance: alcance del indice que se mide.
        commit: identificador corto de Git para la ficha; puede ir vacio.
        archivo_preguntas: TOML alternativo del banco de la fase 2.
        archivo_revision_v1: revision humana v1; por defecto la del proyecto.
        archivo_revision_v2: revision humana v2; por defecto la del proyecto.
        archivo_resultados_v1: resultados v1; por defecto los del proyecto.
        archivo_resultados_v2: resultados v2; por defecto los del proyecto.
        salida_json: ruta del JSON; por defecto ``data/evaluacion/arqueo.json``.
        salida_md: ruta del Markdown; por defecto ``docs/ARQUEO.md``.
        embeddings: proveedor alternativo (pruebas); por defecto Ollama.
        almacen: indice principal alternativo (pruebas); por defecto Chroma.
        almacen_sin_prefijos: indice extra alternativo (pruebas).
        reconstruir_sin_prefijos: fuerza a reconstruir el indice sin prefijos.

    Returns:
        El diccionario del JSON y el texto del Markdown.

    Raises:
        FileNotFoundError: si falta el indice principal o los fragmentos.
        ValueError: si la configuracion o el banco de preguntas son invalidos.
        RuntimeError: si el almacen no queda con los vectores insertados.
    """
    meta_principal = leer_metadatos(config.paths.root / "data" / "boveda")
    if meta_principal is None:
        raise FileNotFoundError(
            "No hay indice de la Boveda: ejecuta `make indice` antes de `make arqueo`."
        )
    if almacen is None and not ruta_almacen(config).exists():
        raise FileNotFoundError(
            "No hay indice de la Boveda en data/boveda/chroma: ejecuta `make indice`."
        )

    ajustes_embeddings = cargar_configuracion_embeddings()
    ajustes_recuperacion = cargar_configuracion_recuperacion()
    proveedor = EmbeddingsEnCache(embeddings or crear_embeddings(ajustes_embeddings))
    preguntas = cargar_preguntas_fase2(archivo_preguntas)
    fragmentos = leer_fragmentos(config, alcance)
    indice = almacen or ChromaAlmacen(ruta_almacen(config))

    barrido = barrer_pesos(
        indice,
        proveedor,
        fragmentos,
        preguntas,
        configuracion=ajustes_recuperacion,
    )

    carpeta_extra = carpeta_sin_prefijos(config)
    existia_extra = leer_metadatos(carpeta_extra) is not None
    resumen_extra = construir_indice_sin_prefijos(
        config,
        alcance,
        embeddings=embeddings,
        almacen=almacen_sin_prefijos,
        reconstruir=reconstruir_sin_prefijos,
        configuracion=ajustes_embeddings,
    )
    proveedor_sin = EmbeddingsEnCache(
        embeddings or crear_embeddings(replace(ajustes_embeddings, prefijos=False))
    )
    indice_extra = almacen_sin_prefijos or ChromaAlmacen(resumen_extra.ruta_almacen)
    etiqueta_extra = (
        f"{etiqueta_pesos(ajustes_recuperacion.peso_vectorial, ajustes_recuperacion.peso_bm25)}"
        " sin prefijos"
    )
    sin_prefijos = medir_configuracion(
        indice_extra,
        proveedor_sin,
        fragmentos,
        preguntas,
        etiqueta=etiqueta_extra,
        vectorial=ajustes_recuperacion.peso_vectorial,
        bm25=ajustes_recuperacion.peso_bm25,
        prefijos=False,
    )

    revision_v1 = cargar_revision(archivo_revision_v1 or ARCHIVO_REVISION_V1)
    ruta_revision_v2 = archivo_revision_v2 or ARCHIVO_REVISION_V2
    revision_v2 = cargar_revision(ruta_revision_v2)
    sensibilidad = cargar_sensibilidad(ruta_revision_v2)
    resultados_v1 = cargar_resultados(archivo_resultados_v1 or ARCHIVO_RESULTADOS_V1)
    resultados_v2 = cargar_resultados(archivo_resultados_v2 or ARCHIVO_RESULTADOS_V2)
    directo = vectorial_directo(indice, proveedor, preguntas)

    avisos: list[str] = []
    if meta_principal.get("fragmentos") != len(fragmentos):
        avisos.append(
            f"El indice declara {meta_principal.get('fragmentos')} fragmentos y el JSONL "
            f"tiene {len(fragmentos)}: ejecuta `make indice`."
        )
    if existia_extra:
        aviso_extra = (
            "El indice sin prefijos ya existia: se reutiliza si es compatible con el "
            "modelo y los fragmentos, y se reconstruye si no."
        )
    else:
        aviso_extra = "El indice sin prefijos se construyo en esta corrida."

    ficha = FichaCorrida(
        commit=commit,
        alcance=alcance,
        indice=meta_principal,
        indice_sin_prefijos=leer_metadatos(carpeta_extra) or {},
        k=ajustes_recuperacion.k,
        peso_vectorial=ajustes_recuperacion.peso_vectorial,
        peso_bm25=ajustes_recuperacion.peso_bm25,
    )
    arqueo = construir_arqueo(
        preguntas,
        barrido,
        sin_prefijos,
        revision_v1=revision_v1,
        revision_v2=revision_v2,
        resultados_v1=resultados_v1,
        resultados_v2=resultados_v2,
        vectorial=directo,
        avisos=avisos,
        sensibilidad=sensibilidad,
    )
    texto = render_markdown(arqueo, ficha)

    destino_json = salida_json or SALIDA_JSON
    destino_md = salida_md or SALIDA_MD
    escribir_json(arqueo, destino_json)
    escribir_markdown(texto, destino_md)
    print(aviso_extra)
    return arqueo, texto


def construir_arqueo(
    preguntas: Sequence[PreguntaFase2],
    barrido: Barrido,
    sin_prefijos: ResultadoConfiguracion,
    *,
    revision_v1: Mapping[int, Revision] | None = None,
    revision_v2: Mapping[int, Revision] | None = None,
    resultados_v1: Sequence[ResultadoEvaluacion] = (),
    resultados_v2: Sequence[ResultadoEvaluacion] = (),
    vectorial: Mapping[int, Sequence[str]] | None = None,
    avisos: Sequence[str] = (),
    sensibilidad: Sensibilidad | None = None,
) -> dict[str, Any]:
    """Arma el diccionario determinista de ``arqueo.json``.

    Args:
        preguntas: banco de la fase 2 cargado.
        barrido: configuraciones medidas sobre el indice con prefijos.
        sin_prefijos: medicion del indice extra con los pesos por defecto.
        revision_v1: revision humana v1 por id.
        revision_v2: revision humana v2 por id; vacia si aun no existe.
        resultados_v1: filas de ``resultados.jsonl``.
        resultados_v2: filas de ``resultados_v2.jsonl``.
        vectorial: top 5 de la busqueda vectorial directa, para diagnosticos.
        avisos: notas de la corrida que se agregan a las generadas aqui.
        sensibilidad: escenario alterno de la revision v2; si falta, el reporte
            no incluye el bloque ``sensibilidad``.

    Returns:
        El diccionario listo para serializar.
    """
    revisiones_v1 = revision_v1 or {}
    revisiones_v2 = revision_v2 or {}
    ids_alcance = [pregunta.id for pregunta in preguntas if pregunta.tipo == "alcance"]

    evaluacion_v1 = _evaluacion(
        preguntas,
        resultados_v1,
        revisiones_v1,
        ids_alcance,
    )
    evaluacion_v2 = (
        _evaluacion(
            preguntas,
            resultados_v2,
            revisiones_v2,
            ids_alcance,
            fuentes_citadas=True,
        )
        if revisiones_v2
        else None
    )
    mcnemar_versiones = comparar_versiones(
        revisiones_v1,
        revisiones_v2,
        ids_alcance,
    )
    ids_boveda = ids_por_ruta(barrido, "B")
    ids_evaluables = ids_por_ruta(barrido)
    mcnemar_pesos = comparar_pesos(barrido, ids_boveda)
    mcnemar_pesos_todas = comparar_pesos(barrido, ids_evaluables)

    configuraciones = (*barrido.configuraciones, sin_prefijos)
    recuperacion = [_resultado_json(configuracion) for configuracion in configuraciones]
    conteos = {
        "preguntas": len(preguntas),
        "con_fuente": sum(1 for pregunta in preguntas if pregunta.fuentes_esperadas),
        "evaluables_b": len(ids_boveda),
        "evaluables_t": sum(
            1 for detalle in barrido.preguntas if detalle.evaluable and detalle.ruta_esperada == "T"
        ),
        "no_indexadas": list(barrido.no_indexadas),
    }

    lista_avisos = list(avisos)
    if not revisiones_v2:
        lista_avisos.append(
            "revision_humana_v2.toml no existe o no tiene revisiones: el McNemar v1 vs v2 "
            f"queda pendiente y se excluyen los {len(ids_alcance)} pares."
        )
    if not resultados_v2:
        lista_avisos.append(
            "resultados_v2.jsonl no existe: la evaluacion v2 queda pendiente (tarea 22.3)."
        )
    if barrido.no_indexadas:
        lista_avisos.append(
            "Preguntas con fuente no indexada: "
            f"{_lista_ids(barrido.no_indexadas)}. La URL esperada no aparece en los "
            "fragmentos del alcance; el PDF del tarifario no esta en "
            "data/boveda/fragmentos_base.jsonl, aunque el alcance base deberia incluir "
            "los PDF de producto."
        )
    ids_url = sorted(
        {
            identificador
            for configuracion in configuraciones
            for identificador in configuracion.diferencias_url
        }
    )
    if ids_url:
        lista_avisos.append(
            "Diferencias solo por normalizacion de URL (minusculas y barra final): "
            f"{_lista_ids(ids_url)}. hit_at_5 y mrr comparan exactamente."
        )
    if vectorial is not None:
        ids_directo = diferencias_vectorial_directo(barrido, vectorial)
        if ids_directo:
            lista_avisos.append(
                "1/0 y la busqueda vectorial directa difieren en "
                f"{len(ids_directo)} pregunta(s): EnsembleRetriever deduplica por "
                "page_content y el indice tiene fragmentos con el mismo texto."
            )

    resumen_v1 = _resumen_uso(resultados_v1)
    resumen_v2 = _resumen_uso(resultados_v2)
    ids_alcance_set = set(ids_alcance)
    resultados_v1_alcance = [
        resultado for resultado in resultados_v1 if resultado.id in ids_alcance_set
    ]
    resultados_v2_alcance = [
        resultado for resultado in resultados_v2 if resultado.id in ids_alcance_set
    ]
    resumen_v1_alcance = _resumen_uso(resultados_v1_alcance)
    resumen_v2_alcance = _resumen_uso(resultados_v2_alcance)
    conteo_clasificador = (
        contar_preguntas_con_clasificador(resultados_v2, ids_alcance) if resultados_v2 else None
    )
    medido = {
        "1/0": _referencia_medida(barrido, barrido.vectorial),
        "por_defecto": _referencia_medida(barrido, barrido.por_defecto),
    }

    return {
        "recuperacion": recuperacion,
        "evaluacion": {"v1": evaluacion_v1, "v2": evaluacion_v2},
        "mcnemar": _mcnemar_json(mcnemar_versiones, ids_alcance),
        "costo": {
            "v1_usd": round(resumen_v1.costo_usd_total, DECIMALES_COSTO),
            "v2_usd": (
                round(resumen_v2.costo_usd_total, DECIMALES_COSTO) if resultados_v2 else None
            ),
            "v1_alcance_usd": (
                round(resumen_v1_alcance.costo_usd_total, DECIMALES_COSTO)
                if resultados_v1_alcance
                else None
            ),
            "v2_alcance_usd": (
                round(resumen_v2_alcance.costo_usd_total, DECIMALES_COSTO)
                if resultados_v2_alcance
                else None
            ),
            "v2_alcance_preguntas": len(ids_alcance),
            "v2_alcance_con_clasificador": (
                conteo_clasificador.con_clasificador if conteo_clasificador is not None else None
            ),
            "v2_alcance_sin_motivo": (
                conteo_clasificador.sin_motivo if conteo_clasificador is not None else None
            ),
            "v2_alcance_cota_inferior": bool(resultados_v2_alcance),
            "v2_total_cota_inferior": bool(resultados_v2),
            "ahorro_alcance_pct": _ahorro_alcance(resumen_v1_alcance, resumen_v2_alcance),
            "preguntas": len(preguntas),
            "arqueo_usd": 0.0,
        },
        "sensibilidad": _sensibilidad_json(
            sensibilidad,
            preguntas,
            revisiones_v1,
            revisiones_v2,
            resultados_v2,
            ids_alcance,
        ),
        "preguntas_por_tipo": _conteo_por_tipo(preguntas),
        "uso": {
            "v1": _resumen_json(resumen_v1),
            "v2": _resumen_json(resumen_v2) if resultados_v2 else None,
        },
        "mcnemar_pesos": {
            **_mcnemar_json(mcnemar_pesos, ids_boveda),
            "preguntas": len(ids_boveda),
            "principal": True,
        },
        "mcnemar_pesos_todas": {
            **_mcnemar_json(mcnemar_pesos_todas, ids_evaluables),
            "preguntas": len(ids_evaluables),
            "principal": False,
        },
        "detalle": {
            "configuraciones": [configuracion.etiqueta for configuracion in configuraciones],
            "preguntas": [
                {
                    "id": detalle.id,
                    "tipo": detalle.tipo,
                    "ruta_esperada": detalle.ruta_esperada,
                    "evaluable": detalle.evaluable,
                    "fuente_indexada": detalle.fuente_indexada,
                    "posiciones": dict(detalle.posiciones),
                }
                for detalle in barrido.preguntas
            ],
        },
        "conteos": conteos,
        "referencia_anexo_a": {
            "esperado": cargar_referencia_anexo_a(),
            "medido": medido,
        },
        "avisos": lista_avisos,
    }


def _resultado_json(configuracion: ResultadoConfiguracion) -> dict[str, Any]:
    """Serializa una configuracion con el redondeo unico del reporte."""
    return {
        "etiqueta": configuracion.etiqueta,
        "pesos": {
            "vectorial": configuracion.vectorial,
            "bm25": configuracion.bm25,
        },
        "prefijos": configuracion.prefijos,
        "por_defecto": configuracion.por_defecto,
        "hit_at_5": _redondear(configuracion.metricas.hit_at_5),
        "mrr": _redondear(configuracion.metricas.mrr),
        "evaluables": configuracion.metricas.evaluables,
        "aciertos": configuracion.metricas.aciertos,
        "intervalo95": _intervalo_json(configuracion.metricas.intervalo95),
        "por_tipo": {
            tipo: _metricas_json(metricas) for tipo, metricas in configuracion.por_tipo.items()
        },
        "sin_tablero": _metricas_json(configuracion.sin_tablero),
    }


def _metricas_json(metricas: MetricasRecuperacion) -> dict[str, Any]:
    """Serializa un bloque de metricas con el redondeo del reporte."""
    return {
        "evaluables": metricas.evaluables,
        "aciertos": metricas.aciertos,
        "hit_at_5": _redondear(metricas.hit_at_5),
        "mrr": _redondear(metricas.mrr),
        "intervalo95": _intervalo_json(metricas.intervalo95),
    }


def _intervalo_json(intervalo: tuple[float, float] | None) -> list[float] | None:
    """Redondea un intervalo de Wilson o devuelve ``None``."""
    if intervalo is None:
        return None
    return [
        round(float(intervalo[0]), DECIMALES),
        round(float(intervalo[1]), DECIMALES),
    ]


def contar_preguntas_con_clasificador(
    resultados: Sequence[ResultadoEvaluacion],
    ids: Sequence[int],
) -> ConteoClasificador:
    """Cuenta las preguntas de alcance segun el motivo guardado en la corrida.

    Lee ``metricas["motivo"]`` de cada fila de ``resultados_v2.jsonl``. Los
    motivos de regla y la marca ``tablero_generico`` no pasaron por el
    clasificador; un motivo de texto libre si. Una fila sin motivo no se cuenta
    como regla ni como clasificador: se informa aparte en ``sin_motivo``.

    Args:
        resultados: filas de ``resultados_v2.jsonl``.
        ids: ids de las preguntas de alcance.

    Returns:
        Cuantas preguntas usaron el clasificador y cuantas filas no traen motivo.
    """
    objetivo = set(ids)
    con_clasificador = 0
    sin_motivo = 0
    for resultado in resultados:
        if resultado.id not in objetivo:
            continue
        motivo = resultado.metricas.get("motivo")
        if not isinstance(motivo, str) or not motivo.strip():
            sin_motivo += 1
            continue
        if not _motivo_de_regla(motivo):
            con_clasificador += 1
    return ConteoClasificador(con_clasificador=con_clasificador, sin_motivo=sin_motivo)


#: Motivos que el digiturno o el tablero resuelven sin el clasificador de dudas.
#: ``tablero_generico`` es la marca determinista que deja el nodo de tablero.
MOTIVOS_DE_REGLA: frozenset[str] = frozenset(
    {"identidad", "tarifas", "fuera_alcance", "tablero_generico"}
)


def _motivo_de_regla(motivo: str) -> bool:
    """Indica si el motivo lo resolvio una regla y no el clasificador."""
    return motivo in MOTIVOS_DE_REGLA or motivo.startswith("pii:")


def _ahorro_alcance(v1: ResumenUso, v2: ResumenUso) -> float | None:
    """Ahorro porcentual de v2 frente a v1 en alcance, redondeado a un decimal.

    Es una cota superior del ahorro real porque el costo de v2 es una cota
    inferior. Devuelve ``None`` si v1 no gasto o si v2 no tiene registros.
    """
    if v1.costo_usd_total <= 0 or v2.registros == 0:
        return None
    ahorro = (v1.costo_usd_total - v2.costo_usd_total) / v1.costo_usd_total * 100
    return round(max(0.0, ahorro), 1)


def _evaluacion(
    preguntas: Sequence[PreguntaFase2],
    resultados: Sequence[ResultadoEvaluacion],
    revision: Mapping[int, Revision],
    ids: Sequence[int],
    *,
    fuentes_citadas: bool = False,
) -> dict[str, Any] | None:
    """Resume exactitud y citas de una version de la evaluacion.

    Con ``fuentes_citadas`` usa la lista ``metricas["fuentes"]`` de v2; sin
    ella usa ``resultado.fuente``, el unico campo que guarda v1.
    """
    if not resultados and not revision:
        return None
    aciertos = aciertos_por_revision(revision, ids)
    por_id = {resultado.id: resultado for resultado in resultados}
    conjunto = set(ids)
    citadas: list[list[str]] = []
    esperadas: list[list[str]] = []
    for pregunta in preguntas:
        if pregunta.id not in conjunto:
            continue
        resultado = por_id.get(pregunta.id)
        if resultado is None:
            continue
        if fuentes_citadas:
            guardadas = resultado.metricas.get("fuentes")
            citadas.append(
                [str(url) for url in guardadas if isinstance(url, str)]
                if isinstance(guardadas, list)
                else []
            )
        else:
            citadas.append([resultado.fuente] if resultado.fuente else [])
        esperadas.append(list(pregunta.fuentes_esperadas))
    citas = citas_correctas(citadas, esperadas) if citadas else None
    return {
        "aciertos": sum(1 for acierto in aciertos if acierto is True),
        "total": len(ids),
        "exactitud": _redondear(exactitud(aciertos)),
        "citas_correctas": _redondear(citas),
        "revisadas": sum(1 for acierto in aciertos if acierto is not None),
    }


def _sensibilidad_json(
    sensibilidad: Sensibilidad | None,
    preguntas: Sequence[PreguntaFase2],
    revision_v1: Mapping[int, Revision],
    revision_v2: Mapping[int, Revision],
    resultados_v2: Sequence[ResultadoEvaluacion],
    ids: Sequence[int],
) -> dict[str, Any] | None:
    """Aplica el escenario de sensibilidad y resume su evaluacion y McNemar."""
    if sensibilidad is None or not sensibilidad.cambios or not revision_v2:
        return None

    revisadas = dict(revision_v2)
    cambios: list[dict[str, Any]] = []
    for cambio in sensibilidad.cambios:
        previa = revisadas.get(cambio.id)
        if previa is None:
            raise ValueError(
                f"La sensibilidad referencia la pregunta {cambio.id}, que no esta en "
                "revision_humana_v2.toml."
            )
        cambios.append(
            {
                "id": cambio.id,
                "de": previa.veredicto,
                "a": cambio.veredicto,
                "nota": cambio.nota,
            }
        )
        revisadas[cambio.id] = replace(previa, veredicto=cambio.veredicto)

    evaluacion = _evaluacion(
        preguntas,
        resultados_v2,
        revisadas,
        ids,
        fuentes_citadas=True,
    )
    return {
        "revisor": sensibilidad.revisor,
        "cambios": cambios,
        "evaluacion": evaluacion,
        "mcnemar": _mcnemar_json(comparar_versiones(revision_v1, revisadas, ids), ids),
    }


def _resumen_uso(resultados: Sequence[ResultadoEvaluacion]) -> ResumenUso:
    """Agrega uso y costo de una corrida de evaluacion."""
    return resumen_uso(
        [
            {
                "metricas": resultado.metricas,
                "segundos": resultado.segundos,
                "error": resultado.error,
            }
            for resultado in resultados
        ]
    )


def _resumen_json(resumen: ResumenUso) -> dict[str, Any]:
    """Serializa un resumen de uso con seis decimales en los flotantes."""
    return {
        clave: (round(valor, DECIMALES_COSTO) if isinstance(valor, float) else valor)
        for clave, valor in asdict(resumen).items()
    }


def _mcnemar_json(resultado: ResultadoMcNemar, ids: Sequence[int]) -> dict[str, Any]:
    """Serializa un resultado de McNemar con sus conteos y su p minima."""
    return {
        "b": resultado.b,
        "c": resultado.c,
        "n": resultado.n,
        "p": _redondear(resultado.p, DECIMALES_COSTO),
        "p_minimo": _redondear(p_minimo_mcnemar(resultado.n), DECIMALES_COSTO),
        "alfa": _redondear(ALFA, DECIMALES_COSTO),
        "excluidos": resultado.excluidos,
        "preguntas": len(ids),
    }


def _conteo_por_tipo(preguntas: Sequence[PreguntaFase2]) -> dict[str, int]:
    """Cuenta las preguntas por tipo en el orden estable del reporte."""
    conteo = {"alcance": 0, "tabla": 0, "seguimiento": 0, "fuera": 0}
    for pregunta in preguntas:
        conteo[pregunta.tipo] = conteo.get(pregunta.tipo, 0) + 1
    return conteo


def _referencia_medida(barrido: Barrido, etiqueta: str) -> dict[str, float | None]:
    """Devuelve hit@5 y MRR medidos de una configuracion del barrido."""
    for configuracion in barrido.configuraciones:
        if configuracion.etiqueta == etiqueta:
            return {
                "hit_at_5": _redondear(configuracion.metricas.hit_at_5),
                "mrr": _redondear(configuracion.metricas.mrr),
            }
    return {"hit_at_5": None, "mrr": None}


def render_markdown(arqueo: Mapping[str, Any], ficha: FichaCorrida) -> str:
    """Renderiza ``docs/ARQUEO.md`` desde el mismo diccionario del JSON.

    Args:
        arqueo: diccionario devuelto por :func:`construir_arqueo`.
        ficha: procedencia de la corrida.

    Returns:
        El texto Markdown completo, sin fecha ni rutas absolutas.
    """
    conteos = arqueo["conteos"]
    lineas: list[str] = [
        "# Arqueo de la Sucursal 1965",
        "",
        "Reporte reproducible de recuperacion, evaluacion y costo de la fase 2. Se genera "
        "con `make arqueo` y no llama a DeepSeek; los embeddings son locales (Ollama). "
        "El JSON con las mismas cifras vive en `data/evaluacion/arqueo.json`.",
        "",
        "## Ficha de corrida",
        "",
        f"- Commit: `{ficha.commit or 'sin git'}`.",
        f"- Alcance del indice: `{ficha.alcance}`.",
        f"- Indice con prefijos: `{ficha.ruta_indice}` con modelo "
        f"`{ficha.indice.get('modelo', 'sin datos')}`, prefijos "
        f"{_si_no(bool(ficha.indice.get('prefijos')))}, "
        f"{ficha.indice.get('fragmentos', 'sin datos')} fragmentos y dimension "
        f"{ficha.indice.get('dimension', 'sin datos')}.",
        f"- Indice sin prefijos: `{ficha.ruta_indice_sin_prefijos}` con "
        f"{ficha.indice_sin_prefijos.get('fragmentos', 'sin datos')} fragmentos y "
        f"dimension {ficha.indice_sin_prefijos.get('dimension', 'sin datos')}.",
        f"- Configuracion: `k={ficha.k}`, pesos por defecto "
        f"`{etiqueta_pesos(ficha.peso_vectorial, ficha.peso_bm25)}`, "
        f"confianza `{ficha.confianza:g}` para los intervalos de Wilson.",
        f"- Preguntas: {conteos['preguntas']} "
        f"({_por_tipo_texto(arqueo)}); "
        f"{conteos['con_fuente']} con fuente; {conteos['evaluables_b']} evaluables de la "
        f"Boveda (ruta B) y {conteos['evaluables_t']} del Tablero (ruta T).",
        "",
        "Este es el formato de corrida que puede reutilizar la skill `boveda-rag`: commit "
        "de Git, metadatos de `indice.json`, configuracion de recuperacion y resultados "
        "por pregunta (en `detalle` del JSON).",
        "",
        "## Como se lee este reporte",
        "",
        "- **hit@5**: proporcion de preguntas con al menos una URL esperada entre los "
        "cinco primeros fragmentos. Solo cuentan las preguntas con fuente.",
        "- **MRR**: media del inverso de la posicion de la primera URL esperada.",
        "- **Wilson 95 %**: intervalo de confianza del hit@5; con 36 preguntas es ancho y "
        "no conviene leer diferencias pequenas como mejoras.",
        "- **Comparacion principal**: fijada de antemano, pesos por defecto frente a "
        "`1/0` sobre las preguntas de ruta B, con McNemar exacto. Las demas "
        "configuraciones son exploratorias: no se declara ganador por significancia.",
        "- **Ruta T**: la respuesta real viene del Tablero, no de la Boveda; su hit@5 se "
        "reporta aparte para no atribuir a la Boveda lo que resuelve el Tablero.",
        "",
        "## Recuperacion por configuracion",
        "",
        "| Configuracion | Prefijos | Evaluables | Aciertos | hit@5 | Wilson 95 % | MRR |",
        "|---|---|---:|---:|---:|---|---:|",
    ]
    for configuracion in arqueo["recuperacion"]:
        etiqueta = configuracion["etiqueta"]
        if configuracion["por_defecto"]:
            etiqueta = f"{etiqueta} (por defecto)"
        intervalo = configuracion["intervalo95"]
        lineas.append(
            f"| {etiqueta} | {_si_no(configuracion['prefijos'])} | "
            f"{configuracion['evaluables']} | {configuracion['aciertos']} | "
            f"{_num(configuracion['hit_at_5'])} | {_rango(intervalo)} | "
            f"{_num(configuracion['mrr'])} |"
        )

    lineas += [
        "",
        "## Por tipo de pregunta",
        "",
        "| Configuracion | Tipo | Evaluables | hit@5 | MRR |",
        "|---|---|---:|---:|---:|",
    ]
    for configuracion in arqueo["recuperacion"]:
        for tipo, metricas in configuracion["por_tipo"].items():
            lineas.append(
                f"| {configuracion['etiqueta']} | {tipo} | {metricas['evaluables']} | "
                f"{_num(metricas['hit_at_5'])} | {_num(metricas['mrr'])} |"
            )

    lineas += [
        "",
        "## Boveda frente a Tablero",
        "",
        "hit@5 con las 36 evaluables y sin las preguntas de ruta T:",
        "",
        "| Configuracion | hit@5 (36) | hit@5 (sin T) | MRR (36) | MRR (sin T) |",
        "|---|---:|---:|---:|---:|",
    ]
    for configuracion in arqueo["recuperacion"]:
        lineas.append(
            f"| {configuracion['etiqueta']} | {_num(configuracion['hit_at_5'])} | "
            f"{_num(configuracion['sin_tablero']['hit_at_5'])} | "
            f"{_num(configuracion['mrr'])} | {_num(configuracion['sin_tablero']['mrr'])} |"
        )

    principal = arqueo["mcnemar_pesos"]
    secundaria = arqueo["mcnemar_pesos_todas"]
    lineas += [
        "",
        "## Comparacion principal: pesos por defecto frente a 1/0",
        "",
        f"Preguntas de ruta B con fuente: {principal['preguntas']}. `b` cuenta los pares "
        "donde acierta la configuracion por defecto y falla `1/0`; `c`, lo contrario.",
        "",
        "| b | c | n | p exacta | Excluidos |",
        "|---:|---:|---:|---:|---:|",
        f"| {principal['b']} | {principal['c']} | {principal['n']} | "
        f"{_num(principal['p'], DECIMALES_COSTO)} | {principal['excluidos']} |",
        "",
        f"Analisis secundario sobre las {secundaria['preguntas']} preguntas evaluables "
        f"(incluye ruta T): b={secundaria['b']}, c={secundaria['c']}, "
        f"n={secundaria['n']}, p={_num(secundaria['p'], DECIMALES_COSTO)}, "
        f"excluidos={secundaria['excluidos']}.",
        "",
        "## Vectorial frente a hibrido, pregunta por pregunta",
        "",
        "Posicion 1 a 5 de la primera URL esperada en el top 5; `—` significa que no "
        "aparece. Vectorial es `1/0`; hibrido es la configuracion por defecto.",
        "",
        "| # | Tipo | Ruta | Fuente indexada | Vectorial 1/0 | Hibrido por defecto | Diferencia |",
        "|---:|---|---|---|---:|---:|---|",
    ]
    vectorial = next(
        (c for c in arqueo["recuperacion"] if c["etiqueta"] == "1/0"),
        None,
    )
    etiqueta_defecto = next(
        (c["etiqueta"] for c in arqueo["recuperacion"] if c["por_defecto"]),
        "",
    )
    for detalle in arqueo["detalle"]["preguntas"]:
        posiciones = detalle["posiciones"]
        posicion_vectorial = posiciones.get("1/0") if vectorial else None
        posicion_defecto = posiciones.get(etiqueta_defecto)
        lineas.append(
            f"| {detalle['id']} | {detalle['tipo']} | {detalle['ruta_esperada']} | "
            f"{_indexada(detalle['fuente_indexada'])} | "
            f"{_posicion(posicion_vectorial)} | {_posicion(posicion_defecto)} | "
            f"{_diferencia(posicion_vectorial, posicion_defecto)} |"
        )

    v1 = arqueo["evaluacion"]["v1"]
    v2 = arqueo["evaluacion"]["v2"]
    lineas += [
        "",
        "## Evaluacion v1 y v2",
        "",
        "| Version | Aciertos | Total | Exactitud | Citas correctas | Revisadas |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    lineas.append(_fila_evaluacion("v1", v1))
    lineas.append(_fila_evaluacion("v2", v2))

    mcnemar = arqueo["mcnemar"]
    lineas += [
        "",
        "## McNemar v1 frente a v2 (20 preguntas de alcance)",
        "",
    ]
    if v2 is None:
        lineas.append(
            "Pendiente: no existe `config/evaluacion/revision_humana_v2.toml` con "
            "veredictos, asi que los 20 pares quedan excluidos y no se declara diferencia. "
            "Cuando exista la revision v2, `make arqueo` la incorpora sin tocar codigo."
        )
    else:
        lineas += [
            "| b | c | n | p exacta | p minimo | Excluidos |",
            "|---:|---:|---:|---:|---:|---:|",
            f"| {mcnemar['b']} | {mcnemar['c']} | {mcnemar['n']} | "
            f"{_num(mcnemar['p'], DECIMALES_COSTO)} | "
            f"{_num(mcnemar['p_minimo'], DECIMALES_COSTO)} | {mcnemar['excluidos']} |",
            "",
            _frase_mcnemar(
                mcnemar,
                v1["aciertos"] if v1 is not None else 0,
                v2["aciertos"],
                mcnemar["preguntas"],
            ),
        ]

    lineas += _seccion_sensibilidad(arqueo, v2, mcnemar)

    costo = arqueo["costo"]
    lineas += [
        "",
        "## Costo y uso",
        "",
        "| Concepto | Valor |",
        "|---|---:|",
        f"| Costo del Arqueo (DeepSeek) | {_usd(costo['arqueo_usd'])} |",
        f"| Costo historico de v1 (20 de alcance) | {_usd(costo['v1_alcance_usd'])} |",
        f"| Costo historico de v2 (44 preguntas, cota inferior) | "
        f"{_usd(costo['v2_usd']) if costo['v2_usd'] is not None else 'pendiente'} |",
        f"| Costo de v2 en las 20 de alcance (cota inferior) | "
        f"{_usd(costo['v2_alcance_usd']) if costo['v2_alcance_usd'] is not None else 'pendiente'} |",
        f"| Ahorro maximo en las 20 de alcance | {_ahorro_texto(costo)} |",
        f"| Preguntas de alcance con clasificador en v2 | {_clasificador_texto(costo)} |",
        f"| Preguntas del banco | {costo['preguntas']} |",
        "",
        "El Arqueo no llama a DeepSeek: su costo es cero. `v1_alcance_usd`, `v2_usd` y "
        "`v2_alcance_usd` son el costo historico de las evaluaciones, calculado con las "
        "tarifas de `arqueo/metricas.py`. Las dos cifras de v2 son cotas inferiores: "
        "cuentan el turno de respuesta, pero no el clasificador de dudas "
        f"({_clasificador_frase(costo)}) ni la reformulacion (#93). v1 no usa "
        f"clasificador, asi que el ahorro en alcance se lee como {_ahorro_texto(costo)}; "
        "la cifra de v2 en alcance es una cota inferior, no una medicion cerrada.",
        "",
        "## Verificacion local contra el anexo A",
        "",
        "Referencia medida por el grupo con el script del anexo A sobre 36 preguntas con "
        "fuente. No es un umbral: sirve para comprobar que el barrido reproduce el orden "
        "del recuperador. Esa referencia se midio con el indice de 846 fragmentos, sin "
        "los 81 de PDF (faltaba `data/knowledge/chunks.jsonl`, ver #78). Con el indice "
        "completo, `medir_recuperacion.py` de la skill boveda-rag da las mismas cifras "
        "que este Arqueo; por eso lo medido supera a lo esperado.",
        "",
        "| Configuracion | hit@5 esperado | hit@5 medido | MRR esperado | MRR medido |",
        "|---|---:|---:|---:|---:|",
    ]
    referencia = arqueo["referencia_anexo_a"]
    for nombre in ("1/0", "por_defecto"):
        esperado = referencia["esperado"][nombre]
        medido = referencia["medido"][nombre]
        lineas.append(
            f"| {nombre} | {_num(esperado['hit_at_5'])} | {_num(medido['hit_at_5'])} | "
            f"{_num(esperado['mrr'])} | {_num(medido['mrr'])} |"
        )
    lineas += [
        "",
        "Diferencias por normalizacion de URL y por deduplicacion de texto se reportan "
        "como avisos del JSON y en la seccion de limites.",
        "",
        "## Limites",
        "",
    ]
    for aviso in arqueo["avisos"]:
        lineas.append(f"- {aviso}")
    lineas += [
        "- El costo de v2 en las 20 preguntas de alcance es una cota inferior: suma el "
        "turno de respuesta, pero no el clasificador de dudas "
        f"({_clasificador_frase(costo)}) ni la reformulacion (#93). El total de 44 "
        "tambien es una cota inferior. Por eso el ahorro frente a v1, que no usa "
        f"clasificador, se lee como {_ahorro_texto(costo)}, no como una cifra cerrada.",
        "- El indice sin prefijos se reutiliza si coinciden modelo, alcance, numero "
        "de fragmentos y huella del contenido; si no, se reconstruye.",
        "- El acierto se mide por URL, no por fragmento: una pregunta cuenta como "
        "acierto si aparece la pagina esperada aunque el fragmento con el dato no este "
        "en el top 5 (por ejemplo, la pregunta 7 y el fragmento de la fundacion en 1965).",
        "- El set no nombra el banco en sus preguntas. La prueba de robustez del #85 "
        "(indice de 893 fragmentos) mostro que agregar la marca a la consulta baja el "
        "hit@5 de 0.75 a 0.53 (McNemar p de 0.02).",
        "- `hit_at_5` y `mrr` comparan las URL exactamente. El script del anexo A "
        "normalizaba minusculas y barra final; el JSON informa en `avisos` si esa regla "
        "cambia algun resultado.",
        "- `EnsembleRetriever` deduplica por `page_content`. Si dos fragmentos comparten "
        "texto, `1/0` puede devolver menos de cinco resultados que una busqueda vectorial "
        "directa; la diferencia se cuenta, no se corrige en el recuperador.",
        "- `citas_correctas` no se compara entre versiones: v1 usa el campo `fuente` de "
        "`resultados.jsonl`, que registra una sola URL por respuesta, y v2 usa la lista "
        '`metricas["fuentes"]` con todas las URL citadas.',
        "- El barrido tiene en la practica dos estados. `EnsembleRetriever` fusiona por "
        "rangos reciprocos (peso / (posicion + 60)): con esa constante el orden depende "
        "sobre todo de que peso supera 0.5, no de su valor exacto. Dentro de cada lado "
        "(peso vectorial menor o mayor que 0.5) el hit@5 casi no cambia; lo que cambia "
        "es el orden dentro del top 5, que se ve en el MRR.",
        "- Los seguimientos se buscan uniendo `previa` y `pregunta`, como "
        "`medir_recuperacion.py`. En produccion la Sucursal reformula con el nodo "
        "`reformular` del grafo, asi que su cifra real puede ser distinta.",
        "- Las preguntas de ruta T responden desde el Tablero: su hit@5 no mide la "
        "Boveda y se reporta con y sin ellas.",
        "",
        "## Comando",
        "",
        "```bash",
        "make arqueo",
        "make arqueo ALCANCE=completo",
        "```",
        "",
        "No requiere `DEEPSEEK_API_KEY`. Requiere Ollama para los embeddings locales y "
        "el indice construido con `make indice`; si falta el indice sin prefijos, esta "
        "corrida lo construye una vez en `data/boveda/experimentos/sin_prefijos`.",
    ]
    return "\n".join(lineas).rstrip() + "\n"


def _seccion_sensibilidad(
    arqueo: Mapping[str, Any],
    v2: Mapping[str, Any] | None,
    mcnemar: Mapping[str, Any],
) -> list[str]:
    """Devuelve la seccion del escenario de sensibilidad, si existe."""
    sensibilidad = arqueo["sensibilidad"]
    if sensibilidad is None or v2 is None:
        return []
    evaluacion = sensibilidad["evaluacion"]
    if evaluacion is None:
        return []
    alterno = sensibilidad["mcnemar"]
    v1 = arqueo["evaluacion"]["v1"]
    lineas = [
        "",
        "## Sensibilidad de la revision humana",
        "",
        f"Escenario alterno con la nota de **{sensibilidad['revisor']}**. No cambia el "
        "veredicto principal ni la segunda firma.",
        "",
        "| # | Veredicto principal | Veredicto de sensibilidad | Nota |",
        "|---:|---|---|---|",
    ]
    for cambio in sensibilidad["cambios"]:
        lineas.append(
            f"| {cambio['id']} | {cambio['de']} | {cambio['a']} | {_celda(cambio['nota'])} |"
        )
    lineas += [
        "",
        "| Escenario | Aciertos v2 | Exactitud v2 | b | c | n | p exacta | p minimo |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
        f"| Principal | {v2['aciertos']} | {_num(v2['exactitud'])} | {mcnemar['b']} | "
        f"{mcnemar['c']} | {mcnemar['n']} | {_num(mcnemar['p'], DECIMALES_COSTO)} | "
        f"{_num(mcnemar['p_minimo'], DECIMALES_COSTO)} |",
        f"| Sensibilidad | {evaluacion['aciertos']} | {_num(evaluacion['exactitud'])} | "
        f"{alterno['b']} | {alterno['c']} | {alterno['n']} | "
        f"{_num(alterno['p'], DECIMALES_COSTO)} | "
        f"{_num(alterno['p_minimo'], DECIMALES_COSTO)} |",
        "",
        _frase_mcnemar(
            alterno,
            v1["aciertos"] if v1 is not None else 0,
            evaluacion["aciertos"],
            alterno["preguntas"],
        ),
    ]
    return lineas


def _frase_mcnemar(
    datos: Mapping[str, Any],
    aciertos_v1: int,
    aciertos_v2: int,
    total: int,
) -> str:
    """Explica aciertos, pares discordantes, direccion, p y excluidos.

    El texto sale de los conteos del McNemar y de los aciertos de cada version.
    Nunca usa la palabra ``mejora``: si la direccion favorece a v1, lo dice.
    """
    b = datos["b"]
    c = datos["c"]
    n = datos["n"]
    p = _num(datos["p"], DECIMALES_COSTO)
    if b > c:
        direccion = "favorece a v1"
        frase_direccion = "la direccion favorece a v1"
    elif c > b:
        direccion = "favorece a v2"
        frase_direccion = "la direccion favorece a v2"
    else:
        direccion = "no hay direccion"
        frase_direccion = "no hay direccion"

    partes = [
        f"v1 acierta {aciertos_v1} de {total} y v2 acierta {aciertos_v2} de {total}.",
        f"De los {n} pares discordantes, b={b} son pares donde v1 acierta y v2 falla, "
        f"y c={c} son pares donde v2 acierta y v1 falla; {frase_direccion}.",
    ]
    if n == 0:
        partes.append("Sin pares discordantes, la prueba no puede declarar diferencia.")
    elif datos["p"] < 0.05:
        partes.append(
            f"El p exacto ({p}) es menor que el umbral de 0.05: la diferencia es "
            f"significativa y {direccion}."
        )
    else:
        minimo = _num(datos["p_minimo"], DECIMALES_COSTO)
        umbral = f"Con {n} pares discordantes, el p minimo posible es 2·(1/2)^{n} = {minimo}"
        if datos["p_minimo"] >= 0.05:
            umbral += ", que ya es >= 0.05: ningun reparto de esos pares podria ser significativo."
        else:
            umbral += ", aunque el p observado no llega al umbral de 0.05."
        partes.append(f"El p exacto ({p}) no llega al umbral de 0.05. {umbral}")

    if datos["excluidos"]:
        partes.append(
            f"Se excluyeron {datos['excluidos']} pares sin veredicto en alguna de "
            "las dos versiones."
        )
    return " ".join(partes)


def _ahorro_texto(costo: Mapping[str, Any]) -> str:
    """Formatea el ahorro de alcance como ``hasta X % menos``."""
    valor = costo["ahorro_alcance_pct"]
    return "pendiente" if valor is None else f"hasta {float(valor):.1f} % menos"


def _clasificador_texto(costo: Mapping[str, Any]) -> str:
    """Muestra cuantas preguntas de alcance usaron clasificador en v2."""
    total = costo["v2_alcance_con_clasificador"]
    if total is None:
        return "pendiente"
    texto = f"{total} de {costo['v2_alcance_preguntas']}"
    sin_motivo = costo.get("v2_alcance_sin_motivo") or 0
    if sin_motivo:
        texto += f" ({sin_motivo} sin motivo)"
    return texto


def _clasificador_frase(costo: Mapping[str, Any]) -> str:
    """Frase con el conteo de preguntas de alcance que usaron clasificador."""
    total = costo["v2_alcance_con_clasificador"]
    if total is None:
        return "sin resultados v2 para contarlo"
    frase = f"se uso en {total} de las {costo['v2_alcance_preguntas']} preguntas de alcance"
    sin_motivo = costo.get("v2_alcance_sin_motivo") or 0
    if sin_motivo:
        frase += f"; {sin_motivo} fila(s) sin motivo no se pudieron determinar"
    return frase


def _celda(texto: str) -> str:
    """Ajusta un texto para una celda de tabla Markdown."""
    return " ".join(str(texto).replace("|", "\\|").split())


def _fila_evaluacion(nombre: str, datos: Mapping[str, Any] | None) -> str:
    """Devuelve una fila de la tabla de evaluacion v1/v2."""
    if datos is None:
        return f"| {nombre} | — | — | — | — | — |"
    return (
        f"| {nombre} | {datos['aciertos']} | {datos['total']} | "
        f"{_num(datos['exactitud'])} | {_num(datos['citas_correctas'])} | "
        f"{datos['revisadas']} |"
    )


def _por_tipo_texto(arqueo: Mapping[str, Any]) -> str:
    """Devuelve el conteo por tipo como texto para la ficha."""
    conteo = arqueo["preguntas_por_tipo"]
    return ", ".join(f"{tipo} {cantidad}" for tipo, cantidad in conteo.items())


def _lista_ids(ids: Sequence[int]) -> str:
    """Une ids con comas para los avisos."""
    return ", ".join(str(identificador) for identificador in ids)


def _redondear(valor: float | None, decimales: int = DECIMALES) -> float | None:
    """Redondea un flotante opcional; ``None`` permanece ``None``."""
    return None if valor is None else round(float(valor), decimales)


def _num(valor: float | None, decimales: int = DECIMALES) -> str:
    """Formatea un flotante opcional con el mismo numero de decimales del JSON."""
    return "—" if valor is None else f"{float(valor):.{decimales}f}"


def _usd(valor: float | None) -> str:
    """Formatea un costo en USD con seis decimales."""
    return "—" if valor is None else f"{float(valor):.{DECIMALES_COSTO}f}"


def _rango(intervalo: Sequence[float] | None) -> str:
    """Formatea un intervalo de Wilson como ``inferior a superior``."""
    if intervalo is None:
        return "—"
    return f"{_num(intervalo[0])} a {_num(intervalo[1])}"


def _posicion(posicion: int | None) -> str:
    """Muestra una posicion del top 5 o un guion."""
    return "—" if posicion is None else str(posicion)


def _indexada(valor: bool | None) -> str:
    """Muestra si la fuente esperada esta en el indice: si, no o guion."""
    if valor is None:
        return "—"
    return "si" if valor else "no"


def _diferencia(vectorial: int | None, hibrido: int | None) -> str:
    """Describe quien gana en una pregunta, sin declarar significancia."""
    if vectorial is None and hibrido is None:
        return "igual (fuera)"
    if vectorial is None:
        return "gana hibrido"
    if hibrido is None:
        return "gana vectorial"
    if vectorial == hibrido:
        return "igual"
    return "gana vectorial" if vectorial < hibrido else "gana hibrido"


def _si_no(valor: bool) -> str:
    """Convierte un booleano en ``si`` o ``no``."""
    return "si" if valor else "no"


def escribir_json(datos: Mapping[str, Any], destino: Path) -> Path:
    """Escribe el JSON de forma determinista, sin fecha ni rutas absolutas."""
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(
        json.dumps(datos, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return destino


def escribir_markdown(texto: str, destino: Path) -> Path:
    """Escribe el Markdown del reporte con salto de linea final."""
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(texto, encoding="utf-8", newline="\n")
    return destino
