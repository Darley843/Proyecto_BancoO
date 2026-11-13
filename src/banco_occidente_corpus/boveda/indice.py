"""Construcción del índice vectorial de la Bóveda por alcance.

`make indice` es el único que escribe el índice: reinicia la colección y vuelve a
insertar todos los fragmentos del alcance para no dejar vectores huérfanos. El
archivo `data/boveda/indice.json` declara modelo, prefijos, alcance, fragmentos y
dimensión, para detectar cuándo el índice dejó de ser compatible. Con los mismos
vectores se regenera `data/boveda/mapa.json` (PCA, ver `mapa.py`).
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import httpx
from langchain_core.embeddings import Embeddings

from ..config import Config
from .almacen import AlmacenVectorial, cerrar_almacen, crear_almacen, crear_almacen_en
from .configuracion import (
    ConfiguracionEmbeddings,
    cargar_configuracion_almacen,
    cargar_configuracion_embeddings,
)
from .embeddings import crear_embeddings
from .fragmentos import ALCANCES, Alcance, ruta_fragmentos
from .mapa import construir_mapa, escribir_mapa
from .rutas import (
    NOMBRE_METADATOS,
    NOMBRE_QDRANT,
    TipoAlmacen,
    carpeta_boveda,
    ruta_almacen,
    ruta_almacen_en,
    ruta_metadatos,
)
from .tipos import Fragmento

#: Fragmentos que se envían a Ollama en cada lote.
LOTE_EMBEDDINGS: int = 64
#: Fragmentos que se insertan en el almacén en cada lote.
LOTE_ALMACEN: int = 256
#: Nombre de la carpeta del almacén por defecto (compatibilidad con el Arqueo).
NOMBRE_ALMACEN: str = NOMBRE_QDRANT

__all__ = [
    "AvisoLote",
    "Progreso",
    "ResumenIndice",
    "TiempoAgotadoEmbeddings",
    "carpeta_boveda",
    "comprobar_almacen",
    "construir_indice",
    "construir_indice_en",
    "escribir_metadatos",
    "formatear_duracion",
    "formatear_resumen_indice",
    "leer_fragmentos",
    "leer_metadatos",
    "metadatos_fragmento",
    "ruta_almacen",
    "ruta_metadatos",
]


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
    almacen: TipoAlmacen = "qdrant"


@dataclass(frozen=True, slots=True)
class AvisoLote:
    """Avance de la vectorización después de terminar un lote."""

    lote: int
    lotes: int
    procesados: int
    total: int


#: Callback opcional que recibe el avance de cada lote terminado.
Progreso = Callable[[AvisoLote], None]


class TiempoAgotadoEmbeddings(RuntimeError):
    """El proveedor de embeddings no respondió dentro del tiempo configurado."""

    def __init__(self, *, lote: int, lotes: int, timeout_segundos: float) -> None:
        """Guarda el lote que falló y el tiempo de espera configurado."""
        super().__init__(f"tiempo de espera agotado al vectorizar el lote {lote} de {lotes}")
        self.lote = lote
        self.lotes = lotes
        self.timeout_segundos = timeout_segundos


def comprobar_almacen(config: Config, carpeta: Path | None = None) -> dict[str, Any] | None:
    """Comprueba que el índice existente corresponda al almacén configurado.

    Un `indice.json` sin la clave `almacen` se considera compatible: es el
    formato anterior a la migración. Si la clave existe y no coincide con
    `[almacen].tipo`, el error explica qué comando ejecutar.

    Args:
        config: configuración con las rutas del corpus.
        carpeta: carpeta del índice; por defecto `data/boveda`.

    Returns:
        Los metadatos del índice, o `None` si no hay `indice.json`.

    Raises:
        ValueError: si el índice declara un almacén distinto del configurado.
    """
    metadatos = leer_metadatos(carpeta or carpeta_boveda(config))
    if metadatos is None:
        return None
    declarado = metadatos.get("almacen")
    configurado = cargar_configuracion_almacen().tipo
    if isinstance(declarado, str) and declarado != configurado:
        raise ValueError(
            f"El índice se construyó con {declarado} y la configuración pide "
            f"{configurado}: ejecuta `make migrar-qdrant` o cambia [almacen].tipo "
            "en config/sucursal.toml."
        )
    return metadatos


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
    progreso: Progreso | None = None,
) -> ResumenIndice:
    """Reconstruye el índice del alcance y escribe sus metadatos.

    Args:
        config: configuración con las rutas del corpus.
        alcance: `base` (web, PDF de producto y hechos) o `completo`.
        configuracion: parámetros de embeddings; se cargan del TOML si faltan.
        embeddings: proveedor alternativo (pruebas); por defecto Ollama.
        almacen: almacén alternativo (pruebas); por defecto el que devuelve
            `crear_almacen(config)` (Qdrant por defecto).
        progreso: callback opcional que recibe el avance de cada lote.

    Returns:
        El resumen del índice construido.
    """
    ajustes = configuracion or cargar_configuracion_embeddings()
    fragmentos = leer_fragmentos(config, alcance)
    if not fragmentos:
        raise ValueError(f"No hay fragmentos para indexar en el alcance {alcance!r}")
    proveedor = embeddings or crear_embeddings(ajustes)
    creado = almacen is None
    destino = almacen or crear_almacen(config)
    try:
        return construir_indice_en(
            carpeta_boveda(config),
            fragmentos,
            alcance=alcance,
            ajustes=ajustes,
            embeddings=proveedor,
            almacen=destino,
            config_mapa=config,
            progreso=progreso,
        )
    finally:
        if creado:
            cerrar_almacen(destino)


def construir_indice_en(
    carpeta: Path,
    fragmentos: Sequence[Fragmento],
    *,
    alcance: Alcance = "base",
    ajustes: ConfiguracionEmbeddings,
    embeddings: Embeddings,
    config_mapa: Config | None = None,
    almacen: AlmacenVectorial | None = None,
    tipo_almacen: TipoAlmacen = "qdrant",
    progreso: Progreso | None = None,
) -> ResumenIndice:
    """Construye un índice en una carpeta arbitraria y escribe sus metadatos.

    Es la variante que usan los experimentos del Arqueo y las pruebas: no lee
    `data/boveda/`, recibe la lista de fragmentos y el proveedor ya resueltos.
    No cambia el comportamiento de `construir_indice`, que delega aquí.

    Args:
        carpeta: carpeta del índice; contendrá `qdrant/` o `chroma/` e `indice.json`.
        fragmentos: fragmentos que se van a vectorizar e insertar.
        alcance: alcance declarado en los metadatos.
        ajustes: parámetros de embeddings (modelo, prefijos y timeout).
        embeddings: proveedor que vectoriza los fragmentos.
        config_mapa: configuracion del proyecto para escribir `mapa.json`; solo la
            pasa el indice principal. Sin este parametro no se toca el mapa, para
            que el indice sin prefijos no sobrescriba el mapa principal.
        almacen: almacén alternativo; por defecto el motor `tipo_almacen`.
        tipo_almacen: `qdrant` o `chroma` cuando no se inyecta un almacén.
        progreso: callback opcional que recibe el avance de cada lote.

    Returns:
        El resumen del índice construido.
    """
    if not fragmentos:
        raise ValueError(f"No hay fragmentos para indexar en el alcance {alcance!r}")
    creado = almacen is None
    destino = almacen or crear_almacen_en(carpeta, tipo_almacen)
    tipo: TipoAlmacen = getattr(destino, "tipo", tipo_almacen)
    try:
        # Vectorizar primero: si el proveedor falla, el índice anterior queda intacto.
        vectores = _vectorizar(
            embeddings,
            fragmentos,
            timeout_segundos=ajustes.timeout,
            progreso=progreso,
        )
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
            ruta_metadatos=carpeta / NOMBRE_METADATOS,
            ruta_almacen=ruta_almacen_en(carpeta, tipo),
            almacen=tipo,
        )
        _escribir_metadatos(resumen)
        if config_mapa is not None and len(fragmentos) >= 2:
            # El mapa usa los mismos vectores recién insertados: no vuelve a llamar a Ollama.
            escribir_mapa(config_mapa, construir_mapa(fragmentos, vectores, alcance=alcance))
        return resumen
    finally:
        if creado:
            cerrar_almacen(destino)


def leer_metadatos(carpeta: Path) -> dict[str, Any] | None:
    """Lee `indice.json` de una carpeta de índice; devuelve `None` si falta.

    Raises:
        ValueError: si el archivo no contiene un objeto JSON.
    """
    ruta = carpeta / NOMBRE_METADATOS
    if not ruta.exists():
        return None
    datos = json.loads(ruta.read_text(encoding="utf-8"))
    if not isinstance(datos, dict):
        raise ValueError(f"{ruta} no contiene un objeto JSON")
    return {str(clave): valor for clave, valor in datos.items()}


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


def formatear_duracion(segundos: float) -> str:
    """Convierte segundos en un texto corto como `2 min 10 s`."""
    total = max(0, int(segundos))
    minutos, resto = divmod(total, 60)
    if minutos == 0:
        return f"{resto} s"
    return f"{minutos} min {resto} s"


def _vectorizar(
    proveedor: Embeddings,
    fragmentos: Sequence[Fragmento],
    *,
    timeout_segundos: float,
    progreso: Progreso | None = None,
) -> list[list[float]]:
    """Vectoriza los fragmentos por lotes y avisa del avance de cada uno."""
    vectores: list[list[float]] = []
    total = len(fragmentos)
    lotes = (total + LOTE_EMBEDDINGS - 1) // LOTE_EMBEDDINGS
    for numero, lote in enumerate(_lotes(fragmentos, LOTE_EMBEDDINGS), start=1):
        try:
            calculados = proveedor.embed_documents([fragmento.texto for fragmento in lote])
        except httpx.TimeoutException as error:
            raise TiempoAgotadoEmbeddings(
                lote=numero,
                lotes=lotes,
                timeout_segundos=timeout_segundos,
            ) from error
        vectores.extend([float(valor) for valor in vector] for vector in calculados)
        if progreso is not None:
            progreso(
                AvisoLote(
                    lote=numero,
                    lotes=lotes,
                    procesados=len(vectores),
                    total=total,
                )
            )
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
            metadatos=[metadatos_fragmento(fragmento) for fragmento in lote],
        )


def metadatos_fragmento(fragmento: Fragmento) -> dict[str, Any]:
    """Convierte un fragmento en metadatos planos para el almacén."""
    datos = asdict(fragmento)
    datos.pop("puntaje", None)
    datos.pop("texto", None)
    return datos


def _lotes(items: Sequence[Fragmento], tamano: int) -> Iterator[Sequence[Fragmento]]:
    """Recorre una secuencia en lotes de tamaño fijo."""
    for inicio in range(0, len(items), tamano):
        yield items[inicio : inicio + tamano]


def escribir_metadatos(carpeta: Path, metadatos: Mapping[str, Any]) -> Path:
    """Escribe `indice.json` de forma determinista y devuelve su ruta."""
    ruta = carpeta / NOMBRE_METADATOS
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(
        json.dumps(dict(metadatos), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return ruta


def _escribir_metadatos(resumen: ResumenIndice) -> None:
    """Escribe `indice.json` con el alcance y el almacén del resumen."""
    escribir_metadatos(
        resumen.ruta_metadatos.parent,
        {
            "modelo": resumen.modelo,
            "prefijos": resumen.prefijos,
            "alcance": resumen.alcance,
            "fragmentos": resumen.fragmentos,
            "dimension": resumen.dimension,
            "almacen": resumen.almacen,
        },
    )
