"""Migración del índice de Chroma a Qdrant sin recalcular embeddings.

`make migrar-qdrant` copia los vectores y los metadatos que ya existen en
`data/boveda/chroma` a `data/boveda/qdrant`. No recibe proveedor de embeddings y
no llama a Ollama: solo lee y escribe puntos. El índice de Chroma se conserva
intacto y `indice.json` se actualiza para declarar `almacen = "qdrant"`.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from ..config import Config
from .almacen import (
    AlmacenVectorial,
    ChromaAlmacen,
    QdrantAlmacen,
    cerrar_almacen,
)
from .fragmentos import ALCANCES, Alcance
from .indice import (
    carpeta_boveda,
    escribir_metadatos,
    leer_fragmentos,
    leer_metadatos,
    metadatos_fragmento,
)
from .rutas import NOMBRE_CHROMA, NOMBRE_QDRANT
from .tipos import Fragmento

#: Fragmentos que se copian en cada lote.
LOTE_MIGRACION: int = 256


@dataclass(frozen=True, slots=True)
class ResumenMigracion:
    """Resultado de copiar el índice de Chroma a Qdrant."""

    fragmentos: int
    dimension: int
    alcance: Alcance
    ruta_origen: Path
    ruta_destino: Path


def migrar_a_qdrant(
    config: Config,
    *,
    origen: AlmacenVectorial | None = None,
    destino: AlmacenVectorial | None = None,
    lote: int = LOTE_MIGRACION,
) -> ResumenMigracion:
    """Copia el índice de Chroma a Qdrant y deja `indice.json` coherente.

    Valida el origen completo antes de reiniciar el destino: si falta un vector,
    el índice de Qdrant anterior queda intacto.

    Args:
        config: configuración con las rutas del corpus.
        origen: almacén de Chroma alternativo (pruebas); por defecto el del proyecto.
        destino: almacén de Qdrant alternativo (pruebas); por defecto el del proyecto.
        lote: fragmentos que se insertan en cada lote.

    Returns:
        El resumen con fragmentos, dimensión y rutas.

    Raises:
        FileNotFoundError: si falta `indice.json` o la colección de Chroma.
        ValueError: si el alcance, el conteo o la dimensión no coinciden.
        RuntimeError: si Qdrant no queda con todos los vectores.
    """
    if lote <= 0:
        raise ValueError("El lote de migración debe ser mayor que cero")

    carpeta = carpeta_boveda(config)
    metadatos = leer_metadatos(carpeta)
    if metadatos is None:
        raise FileNotFoundError(
            f"No hay índice en {carpeta}: ejecuta `make indice` antes de migrar."
        )
    alcance = str(metadatos.get("alcance", ""))
    if alcance not in ALCANCES:
        raise ValueError(f"El índice declara un alcance desconocido: {alcance!r}")
    elegido = alcance
    fragmentos = leer_fragmentos(config, elegido)
    if not fragmentos:
        raise ValueError(f"No hay fragmentos para migrar en el alcance {alcance!r}")

    ruta_origen = carpeta / NOMBRE_CHROMA
    ruta_destino = carpeta / NOMBRE_QDRANT
    fuente = origen or ChromaAlmacen(ruta_origen)
    if not fuente.existe():
        raise FileNotFoundError(
            f"No hay índice de Chroma en {ruta_origen}: no hay nada que migrar."
        )

    copiados = fuente.contar()
    if copiados != len(fragmentos):
        raise ValueError(
            f"El índice de Chroma tiene {copiados} vectores y el JSONL tiene "
            f"{len(fragmentos)} fragmentos: ejecuta `make indice` antes de migrar."
        )

    por_id = fuente.vectores([fragmento.id for fragmento in fragmentos])
    faltan = [fragmento.id for fragmento in fragmentos if fragmento.id not in por_id]
    if faltan:
        raise ValueError(
            f"Al índice de Chroma le faltan {len(faltan)} vectores: "
            "ejecuta `make indice` antes de migrar."
        )
    dimension = _dimension(metadatos, por_id, fragmentos)

    creado = destino is None
    meta = destino or QdrantAlmacen(ruta_destino, dimension=dimension)
    try:
        meta.reiniciar()
        for inicio in range(0, len(fragmentos), lote):
            bloque = fragmentos[inicio : inicio + lote]
            meta.agregar(
                ids=[fragmento.id for fragmento in bloque],
                vectores=[por_id[fragmento.id] for fragmento in bloque],
                documentos=[fragmento.texto for fragmento in bloque],
                metadatos=[metadatos_fragmento(fragmento) for fragmento in bloque],
            )
        contados = meta.contar()
        if contados != len(fragmentos):
            raise RuntimeError(
                f"Qdrant declara {contados} vectores y se migraron {len(fragmentos)}"
            )

        actualizados = dict(metadatos)
        actualizados["almacen"] = "qdrant"
        actualizados["fragmentos"] = len(fragmentos)
        actualizados["dimension"] = dimension
        escribir_metadatos(carpeta, actualizados)
    finally:
        if creado:
            cerrar_almacen(meta)

    return ResumenMigracion(
        fragmentos=len(fragmentos),
        dimension=dimension,
        alcance=elegido,
        ruta_origen=ruta_origen,
        ruta_destino=ruta_destino,
    )


def formatear_resumen_migracion(resumen: ResumenMigracion) -> str:
    """Devuelve el texto legible de una migración terminada."""
    return "\n".join(
        [
            f"Índice migrado: {resumen.ruta_origen} → {resumen.ruta_destino}",
            f"Alcance: {resumen.alcance}",
            f"Fragmentos copiados: {resumen.fragmentos} | dimension={resumen.dimension}",
            "No se recalcularon embeddings y el índice de Chroma se conserva.",
        ]
    )


def _dimension(
    metadatos: dict[str, object],
    por_id: dict[str, list[float]],
    fragmentos: Sequence[Fragmento],
) -> int:
    """Comprueba la dimensión declarada contra los vectores copiados."""
    declarada = metadatos.get("dimension")
    primera = len(por_id[fragmentos[0].id])
    if isinstance(declarada, int) and declarada != primera:
        raise ValueError(
            f"indice.json declara dimensión {declarada} y Chroma guarda {primera}: "
            "ejecuta `make indice` antes de migrar."
        )
    distintas = [f.id for f in fragmentos if len(por_id[f.id]) != primera]
    if distintas:
        raise ValueError(f"Hay {len(distintas)} vectores con dimensión distinta en Chroma")
    return primera
