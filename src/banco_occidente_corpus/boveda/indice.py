"""Construcción del índice vectorial de la Bóveda por alcance.

`make indice` es el único que escribe el índice: reinicia la colección y vuelve a
insertar todos los fragmentos del alcance para no dejar vectores huérfanos. El
archivo `data/boveda/indice.json` declara modelo, prefijos, alcance, fragmentos y
dimensión, para detectar cuándo el índice dejó de ser compatible.
"""

from __future__ import annotations

import json
from collections.abc import Iterator, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from langchain_core.embeddings import Embeddings

from ..config import Config
from .almacen import AlmacenVectorial, ChromaAlmacen
from .configuracion import ConfiguracionEmbeddings, cargar_configuracion_embeddings
from .embeddings import crear_embeddings
from .fragmentos import ALCANCES, Alcance, ruta_fragmentos
from .tipos import Fragmento

#: Fragmentos que se envían a Ollama en cada lote.
LOTE_EMBEDDINGS: int = 64
#: Fragmentos que se insertan en Chroma en cada lote.
LOTE_ALMACEN: int = 256
#: Archivo de metadatos del índice.
NOMBRE_METADATOS: str = "indice.json"
#: Carpeta del índice persistente.
NOMBRE_ALMACEN: str = "chroma"


@dataclass(frozen=True, slots=True)
class ResumenIndice:
    """Resultado de una construcción del índice."""

    alcance: Alcance
    modelo: str
    prefijos: bool
    fragmentos: int
    dimension: int
    ruta_metadatos: Path
    ruta_almacen: Path


def carpeta_boveda(config: Config) -> Path:
    """Devuelve `data/boveda` para el proyecto configurado."""
    return config.paths.root / "data" / "boveda"


def ruta_metadatos(config: Config) -> Path:
    """Devuelve la ruta de `data/boveda/indice.json`."""
    return carpeta_boveda(config) / NOMBRE_METADATOS


def ruta_almacen(config: Config) -> Path:
    """Devuelve la ruta de `data/boveda/chroma`."""
    return carpeta_boveda(config) / NOMBRE_ALMACEN


def leer_fragmentos(config: Config, alcance: Alcance = "base") -> list[Fragmento]:
    """Lee el JSONL de fragmentos del alcance pedido.

    Raises:
        ValueError: si el alcance no existe.
        FileNotFoundError: si falta el JSONL de fragmentos.
    """
    if alcance not in ALCANCES:
        raise ValueError(f"alcance desconocido: {alcance!r}; usa {', '.join(ALCANCES)}")
    ruta = ruta_fragmentos(config, alcance)
    if not ruta.exists():
        raise FileNotFoundError(
            f"No hay fragmentos en {ruta}: ejecuta `make fragmentos --alcance {alcance}`."
        )

    fragmentos: list[Fragmento] = []
    with ruta.open(encoding="utf-8") as fh:
        for numero, linea in enumerate(fh, start=1):
            texto = linea.strip()
            if not texto:
                continue
            try:
                fila: dict[str, Any] = json.loads(texto)
                fragmentos.append(Fragmento(**fila))
            except (json.JSONDecodeError, TypeError) as error:
                raise ValueError(f"fragmento inválido en {ruta}:{numero}: {error}") from error
    return fragmentos


def construir_indice(
    config: Config,
    alcance: Alcance = "base",
    *,
    configuracion: ConfiguracionEmbeddings | None = None,
    embeddings: Embeddings | None = None,
    almacen: AlmacenVectorial | None = None,
) -> ResumenIndice:
    """Reconstruye el índice del alcance y escribe sus metadatos.

    Args:
        config: configuración con las rutas del corpus.
        alcance: `base` (web, PDF de producto y hechos) o `completo`.
        configuracion: parámetros de embeddings; se cargan del TOML si faltan.
        embeddings: proveedor alternativo (pruebas); por defecto Ollama.
        almacen: almacén alternativo (pruebas); por defecto Chroma.

    Returns:
        El resumen del índice construido.
    """
    ajustes = configuracion or cargar_configuracion_embeddings()
    fragmentos = leer_fragmentos(config, alcance)
    if not fragmentos:
        raise ValueError(f"No hay fragmentos para indexar en el alcance {alcance!r}")
    proveedor = embeddings or crear_embeddings(ajustes)
    destino = almacen or ChromaAlmacen(ruta_almacen(config))

    # Vectorizar primero: si Ollama falla, el índice anterior queda intacto.
    vectores = _vectorizar(proveedor, fragmentos)
    dimension = len(vectores[0])
    if dimension == 0:
        raise ValueError("El proveedor de embeddings devolvió vectores vacíos")
    if any(len(vector) != dimension for vector in vectores):
        raise ValueError("El proveedor de embeddings devolvió vectores de distinta dimensión")

    destino.reiniciar()
    _insertar(destino, fragmentos, vectores)
    contados = destino.contar()
    if contados != len(fragmentos):
        raise RuntimeError(
            f"El almacén declara {contados} vectores pero se insertaron {len(fragmentos)}"
        )

    resumen = ResumenIndice(
        alcance=alcance,
        modelo=ajustes.modelo,
        prefijos=ajustes.prefijos,
        fragmentos=len(fragmentos),
        dimension=dimension,
        ruta_metadatos=ruta_metadatos(config),
        ruta_almacen=ruta_almacen(config),
    )
    _escribir_metadatos(resumen)
    return resumen


def formatear_resumen_indice(resumen: ResumenIndice) -> str:
    """Devuelve el texto legible con el resumen del índice."""
    prefijos = "sí" if resumen.prefijos else "no"
    return "\n".join(
        [
            f"Índice construido: {resumen.ruta_almacen}",
            f"Alcance: {resumen.alcance}",
            f"Modelo: {resumen.modelo} | dimension={resumen.dimension} | prefijos={prefijos}",
            f"Fragmentos indexados: {resumen.fragmentos}",
            f"Metadatos: {resumen.ruta_metadatos}",
        ]
    )


def _vectorizar(proveedor: Embeddings, fragmentos: Sequence[Fragmento]) -> list[list[float]]:
    """Vectoriza los fragmentos por lotes y devuelve listas de flotantes."""
    vectores: list[list[float]] = []
    for lote in _lotes(fragmentos, LOTE_EMBEDDINGS):
        calculados = proveedor.embed_documents([fragmento.texto for fragmento in lote])
        vectores.extend([float(valor) for valor in vector] for vector in calculados)
    if len(vectores) != len(fragmentos):
        raise ValueError(f"Se esperaban {len(fragmentos)} vectores y se obtuvieron {len(vectores)}")
    return vectores


def _insertar(
    almacen: AlmacenVectorial,
    fragmentos: Sequence[Fragmento],
    vectores: Sequence[Sequence[float]],
) -> None:
    """Inserta fragmentos y vectores en el almacén por lotes."""
    for inicio in range(0, len(fragmentos), LOTE_ALMACEN):
        lote = fragmentos[inicio : inicio + LOTE_ALMACEN]
        almacen.agregar(
            ids=[fragmento.id for fragmento in lote],
            vectores=vectores[inicio : inicio + LOTE_ALMACEN],
            documentos=[fragmento.texto for fragmento in lote],
            metadatos=[_metadatos(fragmento) for fragmento in lote],
        )


def _metadatos(fragmento: Fragmento) -> dict[str, Any]:
    """Convierte un fragmento en metadatos planos para Chroma."""
    datos = asdict(fragmento)
    datos.pop("puntaje", None)
    datos.pop("texto", None)
    return datos


def _lotes(items: Sequence[Fragmento], tamano: int) -> Iterator[Sequence[Fragmento]]:
    """Recorre una secuencia en lotes de tamaño fijo."""
    for inicio in range(0, len(items), tamano):
        yield items[inicio : inicio + tamano]


def _escribir_metadatos(resumen: ResumenIndice) -> None:
    """Escribe `indice.json` de forma determinista."""
    metadatos = {
        "modelo": resumen.modelo,
        "prefijos": resumen.prefijos,
        "alcance": resumen.alcance,
        "fragmentos": resumen.fragmentos,
        "dimension": resumen.dimension,
    }
    resumen.ruta_metadatos.parent.mkdir(parents=True, exist_ok=True)
    resumen.ruta_metadatos.write_text(
        json.dumps(metadatos, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
