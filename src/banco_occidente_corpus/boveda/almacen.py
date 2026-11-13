"""Almacén vectorial de la Bóveda: contrato mínimo, Qdrant y Chroma.

Qdrant es el almacén por defecto y corre embebido en `data/boveda/qdrant`, sin
servidor ni puerto. Chroma queda disponible como opción de compatibilidad. La
colección se crea con distancia coseno y los parámetros HNSW por defecto de
Qdrant; el modo embebido resuelve la búsqueda de forma exacta.

Los ids de los fragmentos son cadenas (`frag:...`), pero Qdrant solo acepta
enteros o UUID. `id_punto` los convierte con UUIDv5 determinista y el id
original viaja en el payload.
"""

from __future__ import annotations

import os
import shutil
import threading
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol, cast

from .configuracion import ConfiguracionAlmacen, cargar_configuracion_almacen
from .rutas import CARPETAS, TipoAlmacen, carpeta_boveda

if TYPE_CHECKING:
    from ..config import Config

#: Nombre de la colección por defecto dentro del almacén.
COLECCION_POR_DEFECTO: str = "boveda"
#: Métrica exigida por el diseño; se fija al crear la colección.
METRICA_POR_DEFECTO: str = "cosine"
#: Dimensión de `nomic-embed-text-v2-moe`.
DIMENSION_POR_DEFECTO: int = 768

#: Namespace estable del proyecto para convertir ids de fragmento en UUID.
ESPACIO_IDS: uuid.UUID = uuid.uuid5(uuid.NAMESPACE_URL, "banco-occidente/boveda")


@dataclass(frozen=True, slots=True)
class Coincidencia:
    """Fragmento devuelto por el almacén, con su distancia y su similitud."""

    id: str
    documento: str
    metadatos: dict[str, Any]
    distancia: float

    @property
    def similitud(self) -> float:
        """Similitud coseno equivalente a `1 - distancia`."""
        return 1.0 - self.distancia


class AlmacenBloqueado(RuntimeError):
    """La carpeta persistente del almacén ya está abierta por otro proceso."""

    def __init__(self, ruta: Path | None) -> None:
        """Redacta el error con la ruta bloqueada y la acción recomendada."""
        ubicacion = "en memoria" if ruta is None else str(ruta)
        super().__init__(
            f"La carpeta de Qdrant {ubicacion} está en uso por otro proceso. "
            "Cierra la app antes de medir (`make app`) o espera a que termine "
            "`make indice`, y vuelve a intentarlo."
        )
        self.ruta = ruta


class AlmacenVectorial(Protocol):
    """Contrato de un almacén de vectores persistente."""

    def crear(self) -> None:
        """Crea la colección si no existe."""
        ...

    def agregar(
        self,
        ids: Sequence[str],
        vectores: Sequence[Sequence[float]],
        documentos: Sequence[str],
        metadatos: Sequence[dict[str, Any]],
    ) -> None:
        """Inserta vectores con su documento y sus metadatos."""
        ...

    def buscar(
        self,
        vector: Sequence[float],
        k: int = 5,
        filtro: Mapping[str, Any] | None = None,
    ) -> list[Coincidencia]:
        """Devuelve las k coincidencias más cercanas por distancia coseno.

        Args:
            vector: embedding de la consulta.
            k: número máximo de coincidencias.
            filtro: igualdad por campos del payload, por ejemplo
                `{"seccion": "identidad"}`; vacío o `None` no filtra.
        """
        ...

    def vectores(self, ids: Sequence[str]) -> dict[str, list[float]]:
        """Devuelve los vectores guardados de los ids originales que existan."""
        ...

    def contar(self) -> int:
        """Devuelve el número de vectores almacenados."""
        ...

    def reiniciar(self) -> None:
        """Borra todos los vectores y deja la colección vacía con su métrica."""
        ...

    def existe(self) -> bool:
        """Indica si la colección ya existe, sin crearla."""
        ...

    def metrica_almacenada(self) -> str:
        """Devuelve la métrica de distancia que declara la colección."""
        ...

    def dimension_almacenada(self) -> int:
        """Devuelve la dimensión de los vectores, o 0 si no hay colección."""
        ...

    def cerrar(self) -> None:
        """Libera el cliente y, en Qdrant, el bloqueo de la carpeta."""
        ...

    @property
    def tipo(self) -> TipoAlmacen:
        """Motor del almacén: `qdrant` o `chroma`."""
        ...

    @property
    def coleccion(self) -> str:
        """Nombre de la colección que guarda los vectores."""
        ...


class ChromaAlmacen:
    """Almacén persistente en una carpeta de Chroma con métrica coseno."""

    def __init__(
        self,
        ruta: Path,
        coleccion: str = COLECCION_POR_DEFECTO,
        metrica: str = METRICA_POR_DEFECTO,
    ) -> None:
        """Guarda la ruta y los metadatos con los que se creará la colección."""
        self._ruta = ruta
        self._nombre = coleccion
        self._metrica = metrica
        self._cliente: Any | None = None
        self._coleccion: Any | None = None

    @property
    def ruta(self) -> Path:
        """Ruta en disco del índice de Chroma."""
        return self._ruta

    @property
    def coleccion(self) -> str:
        """Nombre de la colección."""
        return self._nombre

    @property
    def metrica(self) -> str:
        """Métrica de distancia con la que se crea la colección."""
        return self._metrica

    @property
    def tipo(self) -> TipoAlmacen:
        """Motor del almacén."""
        return "chroma"

    def crear(self) -> None:
        """Crea la colección con la métrica configurada y sin embedder propio."""
        if self._coleccion is not None:
            return
        self._ruta.mkdir(parents=True, exist_ok=True)
        if self._cliente is None:
            import chromadb

            self._cliente = chromadb.PersistentClient(path=str(self._ruta))
        self._coleccion = self._cliente.get_or_create_collection(
            name=self._nombre,
            metadata={"hnsw:space": self._metrica},
            embedding_function=None,
        )

    def agregar(
        self,
        ids: Sequence[str],
        vectores: Sequence[Sequence[float]],
        documentos: Sequence[str],
        metadatos: Sequence[dict[str, Any]],
    ) -> None:
        """Inserta un lote de vectores ya calculados."""
        if not (len(ids) == len(vectores) == len(documentos) == len(metadatos)):
            raise ValueError("ids, vectores, documentos y metadatos deben tener el mismo tamaño")
        if not ids:
            return
        self.crear()
        assert self._coleccion is not None
        self._coleccion.add(
            ids=list(ids),
            embeddings=[list(vector) for vector in vectores],
            documents=list(documentos),
            metadatas=list(metadatos),
        )

    def buscar(
        self,
        vector: Sequence[float],
        k: int = 5,
        filtro: Mapping[str, Any] | None = None,
    ) -> list[Coincidencia]:
        """Devuelve las k coincidencias más cercanas, con distancia coseno."""
        if k <= 0:
            raise ValueError("k debe ser mayor que cero")
        self.crear()
        assert self._coleccion is not None
        parametros: dict[str, Any] = {
            "query_embeddings": [list(vector)],
            "n_results": k,
            "include": ["documents", "metadatas", "distances"],
        }
        where = _filtro_chroma(filtro)
        if where is not None:
            parametros["where"] = where
        resultado = self._coleccion.query(**parametros)
        ids = resultado.get("ids", [[]])[0]
        documentos = resultado.get("documents", [[]])[0]
        metadatos = resultado.get("metadatas", [[]])[0]
        distancias = resultado.get("distances", [[]])[0]
        return [
            Coincidencia(
                id=str(identificador),
                documento=str(documento or ""),
                metadatos=dict(datos or {}),
                distancia=float(distancia),
            )
            for identificador, documento, datos, distancia in zip(
                ids, documentos, metadatos, distancias, strict=True
            )
        ]

    def vectores(self, ids: Sequence[str]) -> dict[str, list[float]]:
        """Lee del índice los vectores ya guardados, sin llamar al modelo."""
        if not ids:
            return {}
        self.crear()
        assert self._coleccion is not None
        resultado = self._coleccion.get(ids=list(ids), include=["embeddings"])
        identificadores = resultado.get("ids")
        incrustaciones = resultado.get("embeddings")
        if not identificadores or incrustaciones is None:
            return {}
        return {
            str(identificador): [float(valor) for valor in vector]
            for identificador, vector in zip(identificadores, incrustaciones, strict=True)
        }

    def contar(self) -> int:
        """Cuenta los vectores de la colección."""
        self.crear()
        assert self._coleccion is not None
        return int(self._coleccion.count())

    def metrica_almacenada(self) -> str:
        """Devuelve la métrica que declara la colección ya creada en Chroma."""
        self.crear()
        assert self._coleccion is not None
        return str((self._coleccion.metadata or {}).get("hnsw:space", ""))

    def dimension_almacenada(self) -> int:
        """Devuelve la dimensión del primer vector, o 0 si no hay colección."""
        if not self.existe():
            return 0
        self.crear()
        assert self._coleccion is not None
        resultado = self._coleccion.get(limit=1, include=["embeddings"])
        vectores = resultado.get("embeddings")
        if vectores is None or len(vectores) == 0:
            return 0
        return len(vectores[0])

    def existe(self) -> bool:
        """Indica si la colección existe, sin crearla."""
        if not self._ruta.exists():
            return False
        if self._cliente is None:
            import chromadb

            self._cliente = chromadb.PersistentClient(path=str(self._ruta))
        nombres = {
            str(getattr(coleccion, "name", coleccion))
            for coleccion in self._cliente.list_collections()
        }
        return self._nombre in nombres

    def reiniciar(self) -> None:
        """Borra la colección y la vuelve a crear vacía con la misma métrica."""
        self.crear()
        assert self._cliente is not None
        assert self._coleccion is not None
        self._cliente.delete_collection(self._nombre)
        self._coleccion = None
        self.crear()

    def cerrar(self) -> None:
        """Suelta las referencias al cliente; Chroma no expone un cierre explícito."""
        self._coleccion = None
        self._cliente = None


class QdrantAlmacen:
    """Almacén persistente en una carpeta de Qdrant, con distancia coseno.

    Con `ruta=None` se usa el modo en memoria de Qdrant, indicado para pruebas.
    La colección declara los parámetros HNSW por defecto del servidor; el modo
    embebido busca de forma exacta sobre los mismos puntos.
    """

    def __init__(
        self,
        ruta: Path | None = None,
        coleccion: str = COLECCION_POR_DEFECTO,
        metrica: str = METRICA_POR_DEFECTO,
        dimension: int = DIMENSION_POR_DEFECTO,
        cliente: Any | None = None,
    ) -> None:
        """Guarda la ruta, la colección y la dimensión inicial.

        Args:
            ruta: carpeta persistente; `None` abre Qdrant en memoria.
            coleccion: nombre de la colección.
            metrica: métrica de distancia; la Bóveda solo usa `cosine`.
            dimension: dimensión con la que se crea la colección si no hay
                vectores de los que inferirla.
            cliente: cliente ya construido (pruebas); si falta, se abre uno.
        """
        self._ruta = ruta
        self._nombre = coleccion
        self._metrica = metrica
        self._dimension = dimension
        self._cliente = cliente
        self._coleccion_lista = False
        self._candado = threading.RLock()

    @property
    def ruta(self) -> Path | None:
        """Carpeta en disco del índice, o `None` si está en memoria."""
        return self._ruta

    @property
    def coleccion(self) -> str:
        """Nombre de la colección."""
        return self._nombre

    @property
    def metrica(self) -> str:
        """Métrica de distancia con la que se crea la colección."""
        return self._metrica

    @property
    def tipo(self) -> TipoAlmacen:
        """Motor del almacén."""
        return "qdrant"

    def crear(self) -> None:
        """Crea la colección con la dimensión configurada si no existe."""
        with self._candado:
            if self._coleccion_lista:
                return
            cliente = self._abrir()
            if cliente.collection_exists(self._nombre):
                existente = self._dimension_actual(cliente)
                if existente:
                    self._dimension = existente
            else:
                self._crear_coleccion(cliente, self._dimension)
            self._coleccion_lista = True

    def agregar(
        self,
        ids: Sequence[str],
        vectores: Sequence[Sequence[float]],
        documentos: Sequence[str],
        metadatos: Sequence[dict[str, Any]],
    ) -> None:
        """Inserta un lote de vectores con el id original en el payload."""
        if not (len(ids) == len(vectores) == len(documentos) == len(metadatos)):
            raise ValueError("ids, vectores, documentos y metadatos deben tener el mismo tamaño")
        if not ids:
            return
        dimension = len(vectores[0])
        if dimension == 0:
            raise ValueError("Los vectores no pueden estar vacíos")
        if any(len(vector) != dimension for vector in vectores):
            raise ValueError("Los vectores del lote deben tener la misma dimensión")

        puntos = [id_punto(identificador) for identificador in ids]
        if len(set(puntos)) != len(puntos):
            raise ValueError("Dos ids de fragmento producen el mismo UUID en Qdrant")

        self._asegurar_coleccion(dimension)
        from qdrant_client.models import PointStruct

        lote = [
            PointStruct(
                id=punto,
                vector=[float(valor) for valor in vector],
                payload=_payload(identificador, documento, datos),
            )
            for punto, identificador, vector, documento, datos in zip(
                puntos, ids, vectores, documentos, metadatos, strict=True
            )
        ]
        with self._candado:
            assert self._cliente is not None
            self._cliente.upsert(collection_name=self._nombre, points=lote)

    def buscar(
        self,
        vector: Sequence[float],
        k: int = 5,
        filtro: Mapping[str, Any] | None = None,
    ) -> list[Coincidencia]:
        """Devuelve las k coincidencias más cercanas por similitud coseno."""
        if k <= 0:
            raise ValueError("k debe ser mayor que cero")
        self.crear()
        with self._candado:
            assert self._cliente is not None
            respuesta = self._cliente.query_points(
                collection_name=self._nombre,
                query=[float(valor) for valor in vector],
                query_filter=_filtro_qdrant(filtro),
                limit=k,
                with_payload=True,
                with_vectors=False,
            )
        coincidencias: list[Coincidencia] = []
        for punto in respuesta.points:
            payload = dict(punto.payload or {})
            identificador = str(payload.pop("id", punto.id))
            documento = str(payload.pop("texto", "") or "")
            coincidencias.append(
                Coincidencia(
                    id=identificador,
                    documento=documento,
                    metadatos=payload,
                    distancia=1.0 - float(punto.score),
                )
            )
        return coincidencias

    def vectores(self, ids: Sequence[str]) -> dict[str, list[float]]:
        """Lee los vectores por id original, sin llamar al modelo."""
        if not ids:
            return {}
        self.crear()
        with self._candado:
            assert self._cliente is not None
            registros = self._cliente.retrieve(
                collection_name=self._nombre,
                ids=[id_punto(identificador) for identificador in ids],
                with_payload=True,
                with_vectors=True,
            )
        guardados: dict[str, list[float]] = {}
        for registro in registros:
            payload = dict(registro.payload or {})
            identificador = str(payload.get("id", ""))
            if not identificador:
                continue
            vector = registro.vector
            if isinstance(vector, dict):
                vector = vector.get("", next(iter(vector.values()), []))
            if not isinstance(vector, (list, tuple)):
                continue
            guardados[identificador] = [float(cast(float, valor)) for valor in vector]
        return guardados

    def contar(self) -> int:
        """Cuenta los puntos de la colección."""
        self.crear()
        with self._candado:
            assert self._cliente is not None
            return int(self._cliente.count(collection_name=self._nombre, exact=True).count)

    def existe(self) -> bool:
        """Indica si la colección existe, sin crearla."""
        with self._candado:
            if self._ruta is not None and not self._ruta.exists():
                return False
            cliente = self._abrir()
            return bool(cliente.collection_exists(self._nombre))

    def metrica_almacenada(self) -> str:
        """Devuelve la distancia que declara la colección, en minúsculas."""
        with self._candado:
            cliente = self._abrir()
            if not cliente.collection_exists(self._nombre):
                return ""
            vectores = cliente.get_collection(self._nombre).config.params.vectors
            if isinstance(vectores, dict):
                return ""
            distancia = vectores.distance
            return str(getattr(distancia, "value", distancia)).lower()

    def dimension_almacenada(self) -> int:
        """Devuelve la dimensión de la colección, o 0 si no existe."""
        with self._candado:
            cliente = self._abrir()
            if not cliente.collection_exists(self._nombre):
                return 0
            return self._dimension_actual(cliente)

    def reiniciar(self) -> None:
        """Borra la colección y la recrea vacía si ya existía."""
        with self._candado:
            cliente = self._abrir()
            if cliente.collection_exists(self._nombre):
                self._dimension = self._dimension_actual(cliente) or self._dimension
                self._recrear_vacia(self._dimension)
            else:
                # Sin colección no se crea todavía: `agregar` infiere la dimensión.
                self._coleccion_lista = False

    def cerrar(self) -> None:
        """Suelta este consumidor; el cliente se cierra cuando ya nadie lo usa.

        Los almacenes persistentes se comparten por carpeta dentro del proceso
        (ver `crear_almacen_en_ruta`). Por eso cerrar solo libera el cliente y el
        bloqueo de la carpeta cuando el último consumidor lo suelta; los demás
        siguen trabajando con la misma instancia.
        """
        with self._candado:
            _soltar_compartido(self)

    def __enter__(self) -> QdrantAlmacen:
        """Abre la colección al entrar en un bloque `with`."""
        self.crear()
        return self

    def __exit__(self, *_: object) -> None:
        """Cierra el cliente al salir del bloque `with`."""
        self.cerrar()

    def _cerrar_cliente(self) -> None:
        """Cierra el cliente sin tocar el registro de almacenes compartidos."""
        if self._cliente is not None:
            cerrar = getattr(self._cliente, "close", None)
            if cerrar is not None:
                cerrar()
            self._cliente = None
        self._coleccion_lista = False

    def _abrir(self) -> Any:
        """Abre el cliente de Qdrant, traduciendo el bloqueo de la carpeta."""
        if self._cliente is not None:
            return self._cliente
        from qdrant_client import QdrantClient

        if self._ruta is None:
            self._cliente = QdrantClient(location=":memory:")
            return self._cliente

        self._ruta.mkdir(parents=True, exist_ok=True)
        try:
            self._cliente = QdrantClient(
                path=str(self._ruta),
                force_disable_check_same_thread=True,
            )
        except RuntimeError as error:
            if _es_bloqueo(error):
                raise AlmacenBloqueado(self._ruta) from error
            raise
        return self._cliente

    def _asegurar_coleccion(self, dimension: int) -> None:
        """Crea la colección o comprueba que su dimensión coincida."""
        with self._candado:
            cliente = self._abrir()
            if cliente.collection_exists(self._nombre):
                existente = self._dimension_actual(cliente)
                if existente and existente != dimension:
                    vacia = cliente.count(collection_name=self._nombre, exact=True).count == 0
                    if vacia:
                        self._recrear_vacia(dimension)
                        return
                    raise ValueError(
                        f"La colección {self._nombre!r} tiene dimensión {existente} "
                        f"y se intentaron insertar vectores de {dimension}"
                    )
                self._dimension = self._dimension_actual(cliente) or dimension
            else:
                self._crear_coleccion(cliente, dimension)
            self._coleccion_lista = True

    def _recrear_vacia(self, dimension: int) -> None:
        """Recrea la colección vacía, liberando antes los archivos en Windows.

        `delete_collection` de Qdrant no cierra el SQLite de la colección en
        Windows; si se recrea en el mismo proceso, los puntos viejos sobreviven.
        Por eso se cierra el cliente y se borra la carpeta antes de reabrir.
        """
        if self._ruta is None:
            cliente = self._abrir()
            if cliente.collection_exists(self._nombre):
                cliente.delete_collection(self._nombre)
        else:
            self._cerrar_cliente()
            shutil.rmtree(self._ruta, ignore_errors=True)
            cliente = self._abrir()
        self._crear_coleccion(cliente, dimension)
        self._coleccion_lista = True

    def _crear_coleccion(self, cliente: Any, dimension: int) -> None:
        """Crea la colección con distancia coseno y HNSW por defecto."""
        from qdrant_client.models import Distance, VectorParams

        cliente.create_collection(
            collection_name=self._nombre,
            vectors_config=VectorParams(size=dimension, distance=Distance.COSINE),
        )
        self._dimension = dimension

    def _dimension_actual(self, cliente: Any) -> int:
        """Lee la dimensión declarada por la colección existente."""
        vectores = cliente.get_collection(self._nombre).config.params.vectors
        if isinstance(vectores, dict):
            return 0
        return int(vectores.size)


def id_punto(identificador: str) -> str:
    """Convierte un id de fragmento en el UUID determinista que usa Qdrant."""
    return str(uuid.uuid5(ESPACIO_IDS, identificador))


def crear_almacen(
    config: Config,
    *,
    tipo: TipoAlmacen | None = None,
    configuracion: ConfiguracionAlmacen | None = None,
) -> AlmacenVectorial:
    """Crea el almacén configurado para la Bóveda del proyecto.

    Args:
        config: configuración con las rutas del corpus.
        tipo: fuerza `qdrant` o `chroma`; si falta, se lee `[almacen].tipo`.
        configuracion: `ConfiguracionAlmacen` alternativa (pruebas).

    Returns:
        Un almacén listo para `crear` o `agregar`.
    """
    ajustes = configuracion or cargar_configuracion_almacen()
    elegido: TipoAlmacen = tipo or ajustes.tipo
    return crear_almacen_en(carpeta_boveda(config), elegido)


def crear_almacen_en(
    carpeta: Path,
    tipo: TipoAlmacen = "qdrant",
    *,
    dimension: int = DIMENSION_POR_DEFECTO,
    cliente: Any | None = None,
) -> AlmacenVectorial:
    """Crea el almacén dentro de una carpeta de índice que contiene `qdrant/` o `chroma/`."""
    return crear_almacen_en_ruta(
        carpeta / CARPETAS[tipo],
        tipo,
        dimension=dimension,
        cliente=cliente,
    )


def crear_almacen_en_ruta(
    ruta: Path | None,
    tipo: TipoAlmacen = "qdrant",
    *,
    dimension: int = DIMENSION_POR_DEFECTO,
    cliente: Any | None = None,
) -> AlmacenVectorial:
    """Crea el almacén en una ruta concreta, ya sea de Qdrant o de Chroma.

    En Qdrant persistente la misma carpeta resuelta devuelve siempre el mismo
    `QdrantAlmacen` dentro del proceso: el modo local de Qdrant admite un solo
    cliente por carpeta y la app necesita que el recuperador y el mapa
    compartan ese cliente. `cerrar` no lo libera hasta que el último
    consumidor lo suelta. Un cliente inyectado (pruebas) o el modo en memoria
    conservan el comportamiento anterior, con una instancia por llamada.
    """
    if tipo == "chroma":
        if ruta is None:
            raise ValueError("Chroma necesita una ruta en disco")
        return ChromaAlmacen(ruta)
    if ruta is not None and cliente is None:
        return _adquirir_qdrant(ruta, dimension=dimension)
    return QdrantAlmacen(ruta, dimension=dimension, cliente=cliente)


def cerrar_almacen(almacen: AlmacenVectorial) -> None:
    """Cierra el almacén si el motor lo permite; los dobles de prueba pueden no tenerlo."""
    cerrar = getattr(almacen, "cerrar", None)
    if cerrar is not None:
        cerrar()


@dataclass(slots=True)
class _Compartido:
    """Entrada del registro: el almacén de una carpeta y sus consumidores."""

    almacen: QdrantAlmacen
    usuarios: int = 1


#: Un solo Qdrant embebido por carpeta: su modo local no admite dos clientes.
_REGISTRO_CANDADO = threading.RLock()
_REGISTRO_QDRANT: dict[Path, _Compartido] = {}


def _clave_compartida(ruta: Path) -> Path:
    """Normaliza una carpeta para que dos rutas relativas apunten al mismo almacén."""
    resuelta = ruta.resolve()
    return Path(os.path.normcase(str(resuelta)))


def _adquirir_qdrant(ruta: Path, *, dimension: int) -> QdrantAlmacen:
    """Devuelve el almacén compartido de la carpeta, creándolo la primera vez."""
    clave = _clave_compartida(ruta)
    with _REGISTRO_CANDADO:
        entrada = _REGISTRO_QDRANT.get(clave)
        if entrada is None:
            almacen = QdrantAlmacen(ruta.resolve(), dimension=dimension)
            _REGISTRO_QDRANT[clave] = _Compartido(almacen)
            return almacen
        entrada.usuarios += 1
        return entrada.almacen


def _soltar_compartido(almacen: QdrantAlmacen) -> None:
    """Resta un consumidor y cierra el cliente cuando ya no queda ninguno.

    El cierre ocurre dentro del candado del registro para que ningún otro hilo
    cree un almacén nuevo sobre la misma carpeta mientras se libera el bloqueo.
    """
    with _REGISTRO_CANDADO:
        for clave, entrada in list(_REGISTRO_QDRANT.items()):
            if entrada.almacen is not almacen:
                continue
            entrada.usuarios -= 1
            if entrada.usuarios > 0:
                return
            del _REGISTRO_QDRANT[clave]
            break
        almacen._cerrar_cliente()


def _payload(
    identificador: str,
    documento: str,
    metadatos: Mapping[str, Any],
) -> dict[str, Any]:
    """Arma el payload de Qdrant con el id original y el texto recuperable."""
    datos = dict(metadatos)
    datos.pop("texto", None)
    datos["id"] = str(identificador)
    datos["texto"] = str(documento)
    return datos


def _filtro_qdrant(filtro: Mapping[str, Any] | None) -> Any | None:
    """Convierte igualdades de payload al filtro de Qdrant."""
    if not filtro:
        return None
    from qdrant_client.models import FieldCondition, Filter, MatchValue

    return Filter(
        must=[
            FieldCondition(key=str(clave), match=MatchValue(value=valor))
            for clave, valor in filtro.items()
        ]
    )


def _filtro_chroma(filtro: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """Convierte igualdades de payload al `where` de Chroma."""
    if not filtro:
        return None
    if len(filtro) == 1:
        clave, valor = next(iter(filtro.items()))
        return {str(clave): valor}
    return {"$and": [{str(clave): {"$eq": valor}} for clave, valor in filtro.items()]}


def _es_bloqueo(error: RuntimeError) -> bool:
    """Reconoce el error de Qdrant cuando la carpeta ya está abierta."""
    mensaje = str(error).lower()
    return "already accessed" in mensaje or "already locked" in mensaje or "lock" in mensaje
