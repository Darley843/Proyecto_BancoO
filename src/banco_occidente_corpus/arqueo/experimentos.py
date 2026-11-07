"""Experimentos del Arqueo: cargador de fase 2, barrido de pesos y comparaciones.

El modulo no llama a DeepSeek: los embeddings son locales (Ollama) o se inyectan
en las pruebas. Los pesos se aplican sobre el mismo indice vectorial, de modo que
cambiar de configuracion no reindexa el almacen. El unico indice extra es el de
``data/boveda/experimentos/sin_prefijos``, que se mide con los pesos por defecto.
"""

from __future__ import annotations

import hashlib
import tomllib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Literal, cast

from langchain_core.embeddings import Embeddings

from ..asistente.evaluacion import COBERTURAS, PreguntasInvalidas, Revision
from ..boveda.almacen import AlmacenVectorial
from ..boveda.configuracion import (
    ConfiguracionEmbeddings,
    ConfiguracionRecuperacion,
    cargar_configuracion_embeddings,
    cargar_configuracion_recuperacion,
)
from ..boveda.embeddings import crear_embeddings
from ..boveda.fragmentos import Alcance
from ..boveda.indice import (
    NOMBRE_ALMACEN,
    NOMBRE_METADATOS,
    ResumenIndice,
    construir_indice_en,
    leer_fragmentos,
    leer_metadatos,
)
from ..boveda.recuperador import RecuperadorHibrido, RecuperadorVectorial
from ..boveda.tipos import Fragmento
from ..config import PROJECT_ROOT, Config
from .metricas import (
    ResultadoMcNemar,
    hit_at_k,
    intervalo_wilson,
    mcnemar,
    mrr,
)

#: Tipo de pregunta del banco de la fase 2.
TipoPregunta = Literal["alcance", "tabla", "seguimiento", "fuera"]
#: Ruta esperada de una pregunta: Boveda, Tablero o fuera de alcance.
RutaPregunta = Literal["B", "T", "X"]

#: Archivo versionado con las 44 preguntas de la fase 2.
ARCHIVO_PREGUNTAS_FASE2: Path = PROJECT_ROOT / "config" / "evaluacion" / "preguntas_fase2.toml"
#: Revision humana de las respuestas v1.
ARCHIVO_REVISION_V1: Path = PROJECT_ROOT / "config" / "evaluacion" / "revision_humana.toml"
#: Revision humana de las respuestas v2; puede no existir todavia.
ARCHIVO_REVISION_V2: Path = PROJECT_ROOT / "config" / "evaluacion" / "revision_humana_v2.toml"
#: Fragmentos que devuelve el recuperador y tamano de la ventana de las metricas.
K_POR_DEFECTO: int = 5
#: Archivo con la huella del contenido del indice sin prefijos.
NOMBRE_HUELLA: str = "huella.txt"
#: Configuraciones del barrido, en el orden en que se reportan.
PESOS_BARRIDO: tuple[tuple[float, float], ...] = (
    (1.0, 0.0),
    (0.0, 1.0),
    (0.2, 0.8),
    (0.4, 0.6),
    (0.6, 0.4),
    (0.8, 0.2),
)
#: Tipos de pregunta en el orden estable del reporte.
TIPOS: tuple[str, ...] = ("alcance", "tabla", "seguimiento", "fuera")
#: Rutas esperadas validas.
RUTAS: tuple[str, ...] = ("B", "T", "X")
#: Correspondencia entre tipo y ruta esperada.
RUTAS_POR_TIPO: dict[str, frozenset[str]] = {
    "alcance": frozenset({"B"}),
    "tabla": frozenset({"T"}),
    "seguimiento": frozenset({"B", "T"}),
    "fuera": frozenset({"X"}),
}
#: Campos que debe traer cada pregunta de la fase 2.
CAMPOS_OBLIGATORIOS: frozenset[str] = frozenset(
    {
        "id",
        "pregunta",
        "cobertura",
        "tipo",
        "ruta_esperada",
        "terminos",
        "fuentes_esperadas",
    }
)
#: Veredicto humano convertido a acierto booleano.
VEREDICTOS_ACIERTO: dict[str, bool] = {
    "correcta": True,
    "rechazo_correcto": True,
    "parcial": False,
    "incorrecta": False,
}


@dataclass(frozen=True, slots=True)
class PreguntaFase2:
    """Una pregunta del banco de la fase 2 con su ruta y sus fuentes."""

    id: int
    pregunta: str
    cobertura: str
    tipo: TipoPregunta
    ruta_esperada: RutaPregunta
    fuentes_esperadas: tuple[str, ...]
    previa: str
    terminos: tuple[tuple[str, ...], ...]
    nota: str = ""


@dataclass(frozen=True, slots=True)
class DetallePregunta:
    """Posicion y URLs recuperadas para una pregunta en cada configuracion."""

    id: int
    tipo: str
    ruta_esperada: str
    evaluable: bool
    fuente_indexada: bool | None
    posiciones: dict[str, int | None]
    urls: dict[str, tuple[str, ...]]


@dataclass(frozen=True, slots=True)
class MetricasRecuperacion:
    """hit@5, MRR e intervalo de Wilson de un conjunto de preguntas."""

    evaluables: int
    aciertos: int
    hit_at_5: float | None
    mrr: float | None
    intervalo95: tuple[float, float] | None


@dataclass(frozen=True, slots=True)
class ResultadoConfiguracion:
    """Resultado agregado de una configuracion de pesos sobre un indice."""

    etiqueta: str
    vectorial: float
    bm25: float
    prefijos: bool
    por_defecto: bool
    metricas: MetricasRecuperacion
    por_tipo: dict[str, MetricasRecuperacion]
    sin_tablero: MetricasRecuperacion
    diferencias_url: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class Barrido:
    """Barrido completo: configuraciones medidas y detalle por pregunta."""

    configuraciones: tuple[ResultadoConfiguracion, ...]
    preguntas: tuple[DetallePregunta, ...]
    por_defecto: str
    vectorial: str
    bm25: str
    no_indexadas: tuple[int, ...]


def etiqueta_pesos(vectorial: float, bm25: float) -> str:
    """Devuelve una etiqueta corta como ``1/0`` o ``0.2/0.8``."""
    return f"{vectorial:g}/{bm25:g}"


def cargar_preguntas_fase2(archivo: Path | None = None) -> list[PreguntaFase2]:
    """Carga y valida el banco de preguntas de la fase 2.

    No reemplaza a ``asistente.evaluacion.cargar_preguntas``: la evaluacion v1
    conserva su cargador y sus 20 preguntas.

    Args:
        archivo: TOML alternativo; por defecto ``config/evaluacion/preguntas_fase2.toml``.

    Returns:
        Las preguntas ordenadas por ``id``.

    Raises:
        PreguntasInvalidas: si el TOML no cumple el formato esperado.
    """
    ruta = archivo or ARCHIVO_PREGUNTAS_FASE2
    try:
        datos = tomllib.loads(ruta.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise PreguntasInvalidas(f"No existe el archivo de preguntas: {ruta}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise PreguntasInvalidas(f"TOML invalido en {ruta}: {exc}") from exc

    filas = datos.get("pregunta", [])
    if not isinstance(filas, list):
        raise PreguntasInvalidas(f"{ruta}: 'pregunta' debe ser una lista de tablas")
    preguntas = [_leer_pregunta(fila, ruta) for fila in filas]
    if not preguntas:
        raise PreguntasInvalidas(f"{ruta} no tiene preguntas")

    ids = [pregunta.id for pregunta in preguntas]
    if len(ids) != len(set(ids)):
        raise PreguntasInvalidas("Hay ids de pregunta repetidos")
    return sorted(preguntas, key=lambda pregunta: pregunta.id)


def _leer_pregunta(fila: Any, ruta: Path) -> PreguntaFase2:
    """Valida una fila del TOML y la convierte en ``PreguntaFase2``."""
    if not isinstance(fila, dict):
        raise PreguntasInvalidas(f"{ruta}: cada pregunta debe ser una tabla")

    identificador = fila.get("id")
    if not isinstance(identificador, int) or isinstance(identificador, bool):
        raise PreguntasInvalidas(f"{ruta}: pregunta sin id entero")
    faltan = CAMPOS_OBLIGATORIOS - fila.keys()
    if faltan:
        raise PreguntasInvalidas(f"Pregunta {identificador}: faltan los campos {sorted(faltan)}")

    texto = str(fila.get("pregunta", "")).strip()
    if not texto:
        raise PreguntasInvalidas(f"Pregunta {identificador}: texto vacio")

    cobertura = str(fila.get("cobertura", "")).strip()
    if cobertura not in COBERTURAS:
        raise PreguntasInvalidas(
            f"Pregunta {identificador}: cobertura '{cobertura}' no es una de {COBERTURAS}"
        )

    tipo = str(fila.get("tipo", "")).strip()
    if tipo not in TIPOS:
        raise PreguntasInvalidas(f"Pregunta {identificador}: tipo '{tipo}' no es uno de {TIPOS}")

    ruta_esperada = str(fila.get("ruta_esperada", "")).strip()
    if ruta_esperada not in RUTAS:
        raise PreguntasInvalidas(
            f"Pregunta {identificador}: ruta '{ruta_esperada}' no es una de {RUTAS}"
        )
    if ruta_esperada not in RUTAS_POR_TIPO[tipo]:
        raise PreguntasInvalidas(
            f"Pregunta {identificador}: el tipo '{tipo}' no admite la ruta "
            f"'{ruta_esperada}' (validas: {sorted(RUTAS_POR_TIPO[tipo])})"
        )

    previa = fila.get("previa", "")
    if tipo == "seguimiento":
        if not isinstance(previa, str) or not previa.strip():
            raise PreguntasInvalidas(f"Pregunta {identificador}: seguimiento sin 'previa'")
    elif "previa" in fila:
        raise PreguntasInvalidas(
            f"Pregunta {identificador}: 'previa' solo se admite en seguimiento"
        )
    else:
        previa = ""

    terminos = fila.get("terminos")
    if not isinstance(terminos, list) or not all(isinstance(grupo, list) for grupo in terminos):
        raise PreguntasInvalidas(
            f"Pregunta {identificador}: 'terminos' debe ser una lista de listas"
        )
    grupos = tuple(tuple(str(termino) for termino in grupo) for grupo in terminos)

    fuentes = fila.get("fuentes_esperadas")
    if not isinstance(fuentes, list) or not all(
        isinstance(fuente, str) and fuente.strip() for fuente in fuentes
    ):
        raise PreguntasInvalidas(
            f"Pregunta {identificador}: 'fuentes_esperadas' debe ser una lista de URLs"
        )

    return PreguntaFase2(
        id=identificador,
        pregunta=texto,
        cobertura=cobertura,
        tipo=cast(TipoPregunta, tipo),
        ruta_esperada=cast(RutaPregunta, ruta_esperada),
        fuentes_esperadas=tuple(str(fuente).strip() for fuente in fuentes),
        previa=previa.strip(),
        terminos=grupos,
        nota=str(fila.get("nota", "")).strip(),
    )


def posicion_en_top(
    recuperadas: Sequence[str],
    esperadas: Sequence[str],
    k: int = K_POR_DEFECTO,
) -> int | None:
    """Posicion 1..k de la primera URL esperada en lo recuperado.

    La comparacion es exacta, igual que ``arqueo.metricas.hit_at_k``. Devuelve
    ``None`` si no hay fuentes esperadas o si ninguna aparece en el top k.
    """
    if k <= 0:
        raise ValueError("k debe ser mayor que cero")
    esperadas_set = set(esperadas)
    for posicion, url in enumerate(recuperadas[:k], start=1):
        if url in esperadas_set:
            return posicion
    return None


def normalizar_url(url: str) -> str:
    """Normaliza una URL para el diagnostico: minusculas y sin barra final.

    No se usa en ``hit_at_k`` ni en ``mrr``; solo explica diferencias frente al
    script de referencia del anexo A, que comparaba con esta regla.
    """
    return url.strip().casefold().rstrip("/")


def consulta_de(pregunta: PreguntaFase2) -> str:
    """Devuelve el texto que se busca: une la previa y la actual en los seguimientos.

    Replica la regla de ``medir_recuperacion.py`` de la skill boveda-rag para que
    las dos mediciones coincidan. En produccion la Sucursal reformula con el nodo
    ``reformular`` del grafo.

    Args:
        pregunta: pregunta del banco de fase 2.

    Returns:
        La consulta que se envia al recuperador.
    """
    if pregunta.previa:
        return f"{pregunta.previa} {pregunta.pregunta}".strip()
    return pregunta.pregunta


def _metricas(
    recuperadas: Sequence[Sequence[str]],
    esperadas: Sequence[Sequence[str]],
    *,
    k: int = K_POR_DEFECTO,
) -> MetricasRecuperacion:
    """Calcula hit@5, MRR, aciertos e intervalo para listas ya emparejadas."""
    evaluables = sum(1 for fuentes in esperadas if fuentes)
    aciertos = sum(
        1
        for urls, fuentes in zip(recuperadas, esperadas, strict=True)
        if fuentes and posicion_en_top(urls, fuentes, k) is not None
    )
    return MetricasRecuperacion(
        evaluables=evaluables,
        aciertos=aciertos,
        hit_at_5=hit_at_k(recuperadas, esperadas, k=k),
        mrr=mrr(recuperadas, esperadas, k=k),
        intervalo95=intervalo_wilson(aciertos, evaluables),
    )


def _recuperar(
    almacen: AlmacenVectorial,
    embeddings: Embeddings,
    fragmentos: Sequence[Fragmento],
    preguntas: Sequence[PreguntaFase2],
    *,
    vectorial: float,
    bm25: float,
    k: int,
) -> dict[int, tuple[str, ...]]:
    """Recupera el top k de cada pregunta con una configuracion de pesos."""
    recuperador = RecuperadorHibrido(
        almacen,
        embeddings,
        fragmentos,
        ConfiguracionRecuperacion(k=k, peso_vectorial=vectorial, peso_bm25=bm25),
    )
    return {
        pregunta.id: tuple(
            fragmento.url for fragmento in recuperador.buscar(consulta_de(pregunta), k=k)
        )
        for pregunta in preguntas
    }


def _resultado(
    recuperadas: Mapping[int, tuple[str, ...]],
    preguntas: Sequence[PreguntaFase2],
    *,
    etiqueta: str,
    vectorial: float,
    bm25: float,
    prefijos: bool,
    por_defecto: bool,
    k: int,
) -> ResultadoConfiguracion:
    """Agrega las metricas de una configuracion a partir de lo recuperado."""
    esperadas = [list(pregunta.fuentes_esperadas) for pregunta in preguntas]
    obtenidas = [list(recuperadas[pregunta.id]) for pregunta in preguntas]
    metricas = _metricas(obtenidas, esperadas, k=k)

    por_tipo: dict[str, MetricasRecuperacion] = {}
    for tipo in TIPOS:
        indices = [posicion for posicion, pregunta in enumerate(preguntas) if pregunta.tipo == tipo]
        por_tipo[tipo] = _metricas(
            [obtenidas[posicion] for posicion in indices],
            [esperadas[posicion] for posicion in indices],
            k=k,
        )

    indices_sin_tablero = [
        posicion for posicion, pregunta in enumerate(preguntas) if pregunta.ruta_esperada != "T"
    ]
    sin_tablero = _metricas(
        [obtenidas[posicion] for posicion in indices_sin_tablero],
        [esperadas[posicion] for posicion in indices_sin_tablero],
        k=k,
    )

    return ResultadoConfiguracion(
        etiqueta=etiqueta,
        vectorial=vectorial,
        bm25=bm25,
        prefijos=prefijos,
        por_defecto=por_defecto,
        metricas=metricas,
        por_tipo=por_tipo,
        sin_tablero=sin_tablero,
        diferencias_url=_ids_diferencia_url(recuperadas, preguntas, k=k),
    )


def _ids_diferencia_url(
    recuperadas: Mapping[int, tuple[str, ...]],
    preguntas: Sequence[PreguntaFase2],
    *,
    k: int,
) -> tuple[int, ...]:
    """Ids donde el acierto solo aparece al normalizar las URL."""
    ids: list[int] = []
    for pregunta in preguntas:
        if not pregunta.fuentes_esperadas:
            continue
        urls = recuperadas[pregunta.id]
        if posicion_en_top(urls, pregunta.fuentes_esperadas, k) is not None:
            continue
        normalizadas = {normalizar_url(url) for url in pregunta.fuentes_esperadas}
        if any(normalizar_url(url) in normalizadas for url in urls[:k]):
            ids.append(pregunta.id)
    return tuple(ids)


def medir_configuracion(
    almacen: AlmacenVectorial,
    embeddings: Embeddings,
    fragmentos: Sequence[Fragmento],
    preguntas: Sequence[PreguntaFase2],
    *,
    etiqueta: str,
    vectorial: float,
    bm25: float,
    prefijos: bool,
    k: int = K_POR_DEFECTO,
) -> ResultadoConfiguracion:
    """Mide una configuracion aislada sobre un indice ya construido.

    Sirve para el indice extra sin prefijos, que se mide con los pesos por
    defecto y no forma parte del barrido principal.
    """
    recuperadas = _recuperar(
        almacen,
        embeddings,
        fragmentos,
        preguntas,
        vectorial=vectorial,
        bm25=bm25,
        k=k,
    )
    return _resultado(
        recuperadas,
        preguntas,
        etiqueta=etiqueta,
        vectorial=vectorial,
        bm25=bm25,
        prefijos=prefijos,
        por_defecto=False,
        k=k,
    )


def barrer_pesos(
    almacen: AlmacenVectorial,
    embeddings: Embeddings,
    fragmentos: Sequence[Fragmento],
    preguntas: Sequence[PreguntaFase2],
    *,
    configuracion: ConfiguracionRecuperacion | None = None,
    k: int = K_POR_DEFECTO,
) -> Barrido:
    """Mide hit@5 y MRR de cada configuracion sobre el mismo indice.

    No reconstruye el indice: reutiliza el almacen y los fragmentos recibidos.
    Si la configuracion por defecto del TOML ya esta en el barrido, se marca esa
    entrada en vez de medirla dos veces.

    Args:
        almacen: indice vectorial ya construido.
        embeddings: proveedor del indice; debe aplicar los prefijos que use.
        fragmentos: fragmentos del alcance, fuente de BM25 y de las URL.
        preguntas: banco de la fase 2 ya cargado.
        configuracion: k y pesos por defecto; se cargan del TOML si falta.
        k: tamano de la ventana de hit@5 y MRR.

    Returns:
        El barrido con las configuraciones y el detalle por pregunta.
    """
    if not fragmentos:
        raise ValueError("El barrido necesita al menos un fragmento indexado")
    ajustes = configuracion or cargar_configuracion_recuperacion()
    pares = list(PESOS_BARRIDO)
    defecto = (float(ajustes.peso_vectorial), float(ajustes.peso_bm25))
    if defecto not in pares:
        pares.append(defecto)

    urls_indexadas = {fragmento.url for fragmento in fragmentos}
    recuperadas: dict[str, dict[int, tuple[str, ...]]] = {}
    resultados: list[ResultadoConfiguracion] = []
    etiqueta_defecto = ""
    for vectorial, bm25 in pares:
        etiqueta = etiqueta_pesos(vectorial, bm25)
        if etiqueta in recuperadas:
            etiqueta = f"{etiqueta} (por defecto)"
        es_defecto = (vectorial, bm25) == defecto
        if es_defecto:
            etiqueta_defecto = etiqueta
        recuperadas[etiqueta] = _recuperar(
            almacen,
            embeddings,
            fragmentos,
            preguntas,
            vectorial=vectorial,
            bm25=bm25,
            k=k,
        )
        resultados.append(
            _resultado(
                recuperadas[etiqueta],
                preguntas,
                etiqueta=etiqueta,
                vectorial=vectorial,
                bm25=bm25,
                prefijos=True,
                por_defecto=es_defecto,
                k=k,
            )
        )

    etiquetas = [resultado.etiqueta for resultado in resultados]
    detalle = tuple(
        DetallePregunta(
            id=pregunta.id,
            tipo=pregunta.tipo,
            ruta_esperada=pregunta.ruta_esperada,
            evaluable=bool(pregunta.fuentes_esperadas),
            fuente_indexada=(
                bool(set(pregunta.fuentes_esperadas) & urls_indexadas)
                if pregunta.fuentes_esperadas
                else None
            ),
            posiciones={
                etiqueta: posicion_en_top(
                    recuperadas[etiqueta][pregunta.id],
                    pregunta.fuentes_esperadas,
                    k,
                )
                for etiqueta in etiquetas
            },
            urls={etiqueta: recuperadas[etiqueta][pregunta.id] for etiqueta in etiquetas},
        )
        for pregunta in preguntas
    )

    no_indexadas = tuple(
        pregunta.id
        for pregunta in preguntas
        if pregunta.fuentes_esperadas and not (set(pregunta.fuentes_esperadas) & urls_indexadas)
    )
    return Barrido(
        configuraciones=tuple(resultados),
        preguntas=detalle,
        por_defecto=etiqueta_defecto,
        vectorial=etiqueta_pesos(1.0, 0.0),
        bm25=etiqueta_pesos(0.0, 1.0),
        no_indexadas=no_indexadas,
    )


def vectorial_directo(
    almacen: AlmacenVectorial,
    embeddings: Embeddings,
    preguntas: Sequence[PreguntaFase2],
    *,
    k: int = K_POR_DEFECTO,
) -> dict[int, tuple[str, ...]]:
    """Recupera el top k con busqueda vectorial pura, sin fusion de rangos.

    Es el equivalente al script de referencia del anexo A en modo vectorial.
    """
    recuperador = RecuperadorVectorial(almacen=almacen, embeddings=embeddings, k=k)
    return {
        pregunta.id: tuple(
            str(documento.metadata.get("url", ""))
            for documento in recuperador.invoke(consulta_de(pregunta))
        )
        for pregunta in preguntas
    }


def diferencias_vectorial_directo(
    barrido: Barrido,
    vectorial: Mapping[int, Sequence[str]],
) -> tuple[int, ...]:
    """Ids donde 1/0 y la busqueda vectorial directa devuelven URL distintas.

    La diferencia esperada viene de que ``EnsembleRetriever`` deduplica por
    ``page_content`` y el indice tiene fragmentos con el mismo texto.
    """
    ids: list[int] = []
    for detalle in barrido.preguntas:
        if detalle.urls.get(barrido.vectorial) != tuple(vectorial.get(detalle.id, ())):
            ids.append(detalle.id)
    return tuple(ids)


def carpeta_sin_prefijos(config: Config) -> Path:
    """Devuelve ``data/boveda/experimentos/sin_prefijos``."""
    return config.paths.root / "data" / "boveda" / "experimentos" / "sin_prefijos"


def construir_indice_sin_prefijos(
    config: Config,
    alcance: Alcance = "base",
    *,
    embeddings: Embeddings | None = None,
    almacen: AlmacenVectorial | None = None,
    reconstruir: bool = False,
    configuracion: ConfiguracionEmbeddings | None = None,
) -> ResumenIndice:
    """Construye o reutiliza el unico indice del experimento sin prefijos.

    Si ``indice.json`` declara el mismo modelo, alcance y numero de fragmentos,
    la carpeta de Chroma existe y ``huella.txt`` coincide con los ids y textos
    actuales, se reutiliza para no vectorizar de nuevo. Si la huella falta o no
    coincide, el indice se reconstruye y la huella se vuelve a escribir.

    Args:
        config: configuracion con las rutas del corpus.
        alcance: alcance de los fragmentos que se indexan.
        embeddings: proveedor alternativo (pruebas); por defecto Ollama.
        almacen: almacen alternativo (pruebas); por defecto Chroma.
        reconstruir: fuerza la reconstruccion aunque exista un indice compatible.
        configuracion: parametros de embeddings; se cargan del TOML si faltan.

    Returns:
        El resumen del indice sin prefijos.
    """
    ajustes = replace(configuracion or cargar_configuracion_embeddings(), prefijos=False)
    fragmentos = leer_fragmentos(config, alcance)
    if not fragmentos:
        raise ValueError(f"No hay fragmentos para indexar en el alcance {alcance!r}")
    carpeta = carpeta_sin_prefijos(config)
    metadatos = leer_metadatos(carpeta)
    huella = _huella_fragmentos(fragmentos)
    if not reconstruir and _compatible(
        metadatos, carpeta, ajustes, len(fragmentos), alcance, huella
    ):
        assert metadatos is not None
        return ResumenIndice(
            alcance=alcance,
            modelo=str(metadatos["modelo"]),
            prefijos=False,
            fragmentos=len(fragmentos),
            dimension=int(metadatos["dimension"]),
            ruta_metadatos=carpeta / NOMBRE_METADATOS,
            ruta_almacen=carpeta / NOMBRE_ALMACEN,
        )

    proveedor = embeddings or crear_embeddings(ajustes)
    resumen = construir_indice_en(
        carpeta,
        fragmentos,
        alcance=alcance,
        ajustes=ajustes,
        embeddings=proveedor,
        almacen=almacen,
    )
    _escribir_huella(carpeta, huella)
    return resumen


def _huella_fragmentos(fragmentos: Sequence[Fragmento]) -> str:
    """Calcula el SHA-256 de los ids y textos de los fragmentos en orden."""
    resumen = hashlib.sha256()
    for fragmento in fragmentos:
        resumen.update(fragmento.id.encode("utf-8"))
        resumen.update(b"\x00")
        resumen.update(fragmento.texto.encode("utf-8"))
        resumen.update(b"\x00")
    return resumen.hexdigest()


def _escribir_huella(carpeta: Path, huella: str) -> Path:
    """Escribe ``huella.txt`` de forma determinista y devuelve su ruta."""
    ruta = carpeta / NOMBRE_HUELLA
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(huella + "\n", encoding="utf-8", newline="\n")
    return ruta


def _compatible(
    metadatos: Mapping[str, Any] | None,
    carpeta: Path,
    ajustes: ConfiguracionEmbeddings,
    fragmentos: int,
    alcance: Alcance,
    huella: str,
) -> bool:
    """Indica si el indice sin prefijos existente se puede reutilizar."""
    if metadatos is None:
        return False
    if not (carpeta / NOMBRE_ALMACEN).exists():
        return False
    ruta_huella = carpeta / NOMBRE_HUELLA
    if not ruta_huella.exists() or ruta_huella.read_text(encoding="utf-8").strip() != huella:
        return False
    return (
        metadatos.get("prefijos") is False
        and metadatos.get("modelo") == ajustes.modelo
        and metadatos.get("alcance") == alcance
        and metadatos.get("fragmentos") == fragmentos
        and isinstance(metadatos.get("dimension"), int)
    )


def aciertos_por_revision(
    revision: Mapping[int, Revision],
    ids: Sequence[int],
) -> list[bool | None]:
    """Convierte los veredictos humanos de ``ids`` en aciertos booleanos.

    ``correcta`` y ``rechazo_correcto`` cuentan como acierto; ``parcial`` e
    ``incorrecta`` como fallo; una pregunta sin revision queda en ``None``.
    """
    return [
        VEREDICTOS_ACIERTO.get(revision[identificador].veredicto)
        if identificador in revision
        else None
        for identificador in ids
    ]


def comparar_versiones(
    revision_v1: Mapping[int, Revision],
    revision_v2: Mapping[int, Revision],
    ids: Sequence[int],
) -> ResultadoMcNemar:
    """Aplica McNemar a los veredictos de v1 y v2 sobre las mismas preguntas."""
    return mcnemar(
        aciertos_por_revision(revision_v1, ids),
        aciertos_por_revision(revision_v2, ids),
    )


def ids_por_ruta(barrido: Barrido, ruta: str | None = None) -> list[int]:
    """Ids evaluables del barrido, opcionalmente filtrados por ruta esperada."""
    return [
        detalle.id
        for detalle in barrido.preguntas
        if detalle.evaluable and (ruta is None or detalle.ruta_esperada == ruta)
    ]


def comparar_pesos(
    barrido: Barrido,
    ids: Sequence[int] | None = None,
) -> ResultadoMcNemar:
    """Compara los pesos por defecto contra 1/0 pregunta por pregunta.

    Por defecto usa las preguntas evaluables de ruta ``B``, que son las que
    responden desde la Boveda. ``b`` cuenta los pares donde acierta la
    configuracion por defecto y falla 1/0; ``c`` lo contrario.
    """
    objetivo = list(ids) if ids is not None else ids_por_ruta(barrido, "B")
    por_id = {detalle.id: detalle for detalle in barrido.preguntas}
    aciertos_defecto: list[bool | None] = []
    aciertos_vectorial: list[bool | None] = []
    for identificador in objetivo:
        detalle = por_id[identificador]
        if not detalle.evaluable:
            aciertos_defecto.append(None)
            aciertos_vectorial.append(None)
            continue
        aciertos_defecto.append(detalle.posiciones[barrido.por_defecto] is not None)
        aciertos_vectorial.append(detalle.posiciones[barrido.vectorial] is not None)
    return mcnemar(aciertos_defecto, aciertos_vectorial)
