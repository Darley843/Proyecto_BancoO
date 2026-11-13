"""Mapa 2D de la Bóveda: PCA de los vectores del índice y proyección de la pregunta.

`make indice` llama a `construir_mapa` con los mismos vectores que inserta en
el almacén vectorial y escribe `data/boveda/mapa.json`. El archivo guarda, además de un punto
por fragmento, la transformación (media, componentes, mínimo y rango) para
ubicar después cualquier pregunta en el mismo plano, sin volver a ajustar PCA.

Las coordenadas `x` e `y` se normalizan aquí de 0 a 100, para que el frontend no
tenga que conocer la escala de PCA. Los vectores se normalizan a norma 1 antes de
ajustar, porque el índice compara por coseno. PCA es una vista exploratoria: no
decide rutas ni recupera; el top de la pregunta lo da el recuperador real.
"""

from __future__ import annotations

import json
import math
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, cast

import numpy as np
from langchain_core.embeddings import Embeddings
from sklearn.decomposition import PCA

from ..config import Config
from .fragmentos import ALCANCES, Alcance
from .rutas import carpeta_boveda
from .tipos import Fragmento, Recuperador

#: Nombre del archivo del mapa dentro de `data/boveda/`.
NOMBRE_MAPA: str = "mapa.json"
#: Fragmentos del top que acompañan a la pregunta.
TOP_K: int = 5
#: Decimales de las coordenadas expuestas.
DECIMALES: int = 2


@dataclass(frozen=True, slots=True)
class Proyeccion:
    """Transformación fija que lleva un vector del índice al plano 0–100."""

    media: list[float]
    componentes: list[list[float]]
    minimo: list[float]
    rango: list[float]

    def ubicar(self, vector: Sequence[float]) -> dict[str, float]:
        """Proyecta un vector y lo normaliza de 0 a 100 (recortado a ese rango).

        Args:
            vector: embedding con la misma dimensión del índice.

        Returns:
            Diccionario con `x` e `y` entre 0 y 100.

        Raises:
            ValueError: si la dimensión no coincide o el vector es nulo.
        """
        if len(vector) != len(self.media):
            raise ValueError(
                f"El vector tiene dimensión {len(vector)} y el mapa espera {len(self.media)}"
            )
        unitario = _unitarios(np.asarray([vector], dtype=float))[0]
        plano = (unitario - np.asarray(self.media)) @ np.asarray(self.componentes).T
        return _normalizar(plano, self.minimo, self.rango)


def ruta_mapa(config: Config) -> Path:
    """Devuelve la ruta de `data/boveda/mapa.json`."""
    return config.paths.root / "data" / "boveda" / NOMBRE_MAPA


def construir_mapa(
    fragmentos: Sequence[Fragmento],
    vectores: Sequence[Sequence[float]],
    *,
    alcance: Alcance = "base",
) -> dict[str, Any]:
    """Ajusta PCA de dos componentes y ubica cada fragmento de 0 a 100.

    Args:
        fragmentos: fragmentos indexados, en el mismo orden que sus vectores.
        vectores: embeddings de los fragmentos (todos de la misma dimensión).
        alcance: alcance del índice, que se guarda junto al mapa.

    Returns:
        Diccionario con `alcance`, `puntos` (x, y, id, seccion, titulo, url) y
        `proyeccion` (la transformación para ubicar preguntas).

    Raises:
        ValueError: si no hay al menos dos fragmentos o las listas no coinciden.
    """
    if len(fragmentos) != len(vectores):
        raise ValueError(
            f"Hay {len(fragmentos)} fragmentos y {len(vectores)} vectores: deben coincidir"
        )
    if len(fragmentos) < 2:
        raise ValueError("El mapa necesita al menos dos fragmentos para ajustar PCA")

    matriz = _unitarios(np.asarray(vectores, dtype=float))
    pca = PCA(n_components=2, svd_solver="full")
    planos = pca.fit_transform(matriz)
    minimo = planos.min(axis=0)
    rango = planos.max(axis=0) - minimo
    rango[rango == 0] = 1.0

    proyeccion = Proyeccion(
        media=pca.mean_.tolist(),
        componentes=pca.components_.tolist(),
        minimo=minimo.tolist(),
        rango=rango.tolist(),
    )
    puntos = [
        {
            **_normalizar(plano, proyeccion.minimo, proyeccion.rango),
            "id": fragmento.id,
            "seccion": fragmento.seccion,
            "titulo": fragmento.titulo,
            "url": fragmento.url,
        }
        for fragmento, plano in zip(fragmentos, planos, strict=True)
    ]
    return {"alcance": alcance, "puntos": puntos, "proyeccion": asdict(proyeccion)}


def escribir_mapa(config: Config, mapa: dict[str, Any]) -> Path:
    """Escribe `mapa.json` de forma determinista y devuelve su ruta."""
    ruta = ruta_mapa(config)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(
        json.dumps(mapa, ensure_ascii=False, separators=(",", ":")) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return ruta


def leer_mapa(config: Config) -> dict[str, Any] | None:
    """Lee `mapa.json` si existe y es un objeto JSON con puntos.

    Returns:
        El mapa o None si falta, está dañado o no trae puntos.
    """
    ruta = ruta_mapa(config)
    if not ruta.exists():
        return None
    try:
        datos = json.loads(ruta.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(datos, dict) or not isinstance(datos.get("puntos"), list):
        return None
    return datos


def leer_proyeccion(mapa: dict[str, Any]) -> Proyeccion | None:
    """Reconstruye la transformación guardada en el mapa, si está completa."""
    datos = mapa.get("proyeccion")
    if not isinstance(datos, dict):
        return None
    try:
        return Proyeccion(
            media=[float(valor) for valor in datos["media"]],
            componentes=[[float(valor) for valor in fila] for fila in datos["componentes"]],
            minimo=[float(valor) for valor in datos["minimo"]],
            rango=[float(valor) for valor in datos["rango"]],
        )
    except (KeyError, TypeError, ValueError):
        return None


def _metadatos_indice(config: Config) -> dict[str, Any] | None:
    """Lee `indice.json`; devuelve None si falta o no se puede interpretar."""
    from .indice import leer_metadatos

    try:
        return leer_metadatos(carpeta_boveda(config))
    except (OSError, ValueError):
        return None


def _alcance_indice(config: Config) -> Alcance:
    """Devuelve el alcance declarado en `indice.json`, o `base` si no consta."""
    metadatos = _metadatos_indice(config) or {}
    alcance = metadatos.get("alcance")
    return cast(Alcance, alcance) if alcance in ALCANCES else "base"


def _mapa_desactualizado(config: Config, mapa: dict[str, Any]) -> bool:
    """Indica si el mapa guardado quedó de un índice anterior.

    Compara el número de puntos con el de `indice.json` y el alcance declarado.
    Si no hay metadatos legibles, no se puede afirmar que el mapa esté viejo.
    """
    metadatos = _metadatos_indice(config)
    if metadatos is None:
        return False
    declarados = metadatos.get("fragmentos")
    puntos = mapa.get("puntos")
    if isinstance(declarados, int) and isinstance(puntos, list) and len(puntos) != declarados:
        return True
    return metadatos.get("alcance") != mapa.get("alcance") and metadatos.get("alcance") is not None


class ServicioMapa:
    """Responde el mapa de la API: puntos, pregunta proyectada y top del recuperador.

    Los embeddings y el recuperador se crean la primera vez que llega una
    pregunta, no al arrancar la app. Si falta `mapa.json` o quedó de un índice
    anterior, lo calcula una vez leyendo los vectores del almacén y lo escribe.
    """

    def __init__(
        self,
        config: Config,
        *,
        embeddings: Callable[[], Embeddings] | None = None,
        recuperador: Callable[[], Recuperador] | None = None,
        vectores: Callable[[], tuple[list[Fragmento], list[list[float]]]] | None = None,
    ) -> None:
        """Guarda las fábricas; por defecto usan Ollama y el índice de `data/boveda/`.

        Args:
            config: configuración con las rutas del proyecto.
            embeddings: fábrica alternativa del proveedor de embeddings (pruebas).
            recuperador: fábrica alternativa del recuperador híbrido (pruebas).
            vectores: fábrica alternativa de fragmentos y vectores indexados (pruebas).
        """
        self._config = config
        self._fabrica_embeddings = embeddings or _embeddings_por_defecto
        self._fabrica_recuperador = recuperador or (lambda: _recuperador_por_defecto(config))
        self._fabrica_vectores = vectores or (
            lambda: leer_vectores_indexados(config, _alcance_indice(config))
        )
        self._embeddings: Embeddings | None = None
        self._recuperador: Recuperador | None = None

    def mapa(self) -> dict[str, Any] | None:
        """Devuelve el mapa guardado o lo recalcula cuando no corresponde al índice.

        Un `mapa.json` con otro número de puntos (o de otro alcance) quedó de un
        índice anterior: se reconstruye desde los vectores actuales y se
        sobrescribe. Si la reconstrucción no es posible, se conserva el mapa
        guardado para no dejar la vista vacía.

        Returns:
            El mapa, o None si no hay índice ni mapa del que partir.
        """
        guardado = leer_mapa(self._config)
        if guardado is not None and not _mapa_desactualizado(self._config, guardado):
            return guardado
        try:
            fragmentos, vectores = self._fabrica_vectores()
            mapa = construir_mapa(fragmentos, vectores, alcance=_alcance_indice(self._config))
        except (FileNotFoundError, ValueError, RuntimeError, ImportError):
            return guardado
        escribir_mapa(self._config, mapa)
        return mapa

    def ubicar(self, mapa: dict[str, Any], pregunta: str) -> dict[str, float]:
        """Proyecta la pregunta con la transformación guardada en el mapa.

        Raises:
            ValueError: si el mapa no trae su transformación o la dimensión no coincide.
        """
        proyeccion = leer_proyeccion(mapa)
        if proyeccion is None:
            raise ValueError("El mapa no trae su proyección: vuelve a ejecutar `make indice`.")
        if self._embeddings is None:
            self._embeddings = self._fabrica_embeddings()
        return proyeccion.ubicar(self._embeddings.embed_query(pregunta))

    def top(self, pregunta: str, k: int = TOP_K) -> list[dict[str, Any]]:
        """Devuelve el top de fragmentos del recuperador real, con su puntaje."""
        if self._recuperador is None:
            self._recuperador = self._fabrica_recuperador()
        return [asdict(fragmento) for fragmento in self._recuperador.buscar(pregunta, k=k)]


def leer_vectores_indexados(
    config: Config, alcance: Alcance = "base"
) -> tuple[list[Fragmento], list[list[float]]]:
    """Lee del índice los vectores de los fragmentos del alcance, en su orden.

    Raises:
        FileNotFoundError: si no existe el índice persistente.
        ValueError: si al índice le faltan vectores de algún fragmento.
    """
    from .almacen import cerrar_almacen, crear_almacen
    from .indice import comprobar_almacen, leer_fragmentos, ruta_almacen

    ruta = ruta_almacen(config)
    if not ruta.exists():
        raise FileNotFoundError(f"No hay índice en {ruta}: ejecuta `make indice`.")
    comprobar_almacen(config)
    fragmentos = leer_fragmentos(config, alcance)

    almacen = crear_almacen(config)
    try:
        por_id = almacen.vectores([fragmento.id for fragmento in fragmentos])
    finally:
        cerrar_almacen(almacen)
    faltan = [f.id for f in fragmentos if f.id not in por_id]
    if faltan:
        raise ValueError(f"Al índice le faltan {len(faltan)} vectores: ejecuta `make indice`.")
    return fragmentos, [por_id[f.id] for f in fragmentos]


def _unitarios(matriz: np.ndarray) -> np.ndarray:
    """Divide cada fila por su norma; rechaza vectores nulos o no finitos."""
    if not np.all(np.isfinite(matriz)):
        raise ValueError("Hay vectores con valores no finitos")
    normas = np.linalg.norm(matriz, axis=1, keepdims=True)
    if np.any(normas == 0):
        raise ValueError("Hay vectores nulos: no se pueden ubicar en el mapa")
    return matriz / normas


def _normalizar(
    plano: Sequence[float], minimo: Sequence[float], rango: Sequence[float]
) -> dict[str, float]:
    """Lleva un punto del plano PCA a 0–100, recortado y redondeado."""
    valores = []
    for valor, base, ancho in zip(plano, minimo, rango, strict=True):
        escalado = (float(valor) - base) / ancho * 100
        if not math.isfinite(escalado):
            raise ValueError("La proyección produjo una coordenada no finita")
        valores.append(round(min(max(escalado, 0.0), 100.0), DECIMALES))
    return {"x": valores[0], "y": valores[1]}


def _embeddings_por_defecto() -> Embeddings:
    """Crea los embeddings configurados (Ollama con prefijos)."""
    from .embeddings import crear_embeddings

    return crear_embeddings()


def _recuperador_por_defecto(config: Config) -> Recuperador:
    """Crea el recuperador híbrido real sobre el alcance base."""
    from .recuperador import crear_recuperador

    return crear_recuperador(config, "base")
