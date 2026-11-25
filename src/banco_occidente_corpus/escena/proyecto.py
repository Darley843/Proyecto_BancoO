"""Recuperador BM25 en memoria de la documentación del proyecto.

El paso 2 de ``POST /api/escena/pregunta`` responde las preguntas que hablan del
repositorio, del corpus, del RAG, de las decisiones de diseño o del taller. Para
eso usa un índice **aparte y solo BM25** sobre un corpus fijo y versionado:
``README.md``, ``AGENTS.md``, ``CONSTITUTION.md`` y los ``.md`` de ``docs/``.
No usa Ollama, no toca Qdrant ni Chroma, no calcula embeddings y no escribe en
disco: el índice se arma en memoria la primera vez que se pregunta y muere con
el proceso.

El corpus es acotado. Una ruta de ``config/escena.toml [preguntas.proyecto]``
que salga del repositorio, o que no sea uno de los tres archivos de la raíz ni
un ``.md`` dentro de ``docs/``, se ignora. Así una ruta mal escrita no amplía el
corpus ni expone archivos de fuera.

Este módulo no decide si la pregunta es del proyecto por el puntaje solo: el
corpus de ``docs/`` también contiene las preguntas del banco y el Tablero. La
señal léxica de :func:`es_pregunta_del_proyecto` evita que una pregunta de tasa
o de producto se responda con un documento de diseño; el puntaje mínimo del
llamador confirma que el fragmento elegido es relevante.
"""

from __future__ import annotations

import re
import threading
import tomllib
from collections.abc import Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Protocol

from rank_bm25 import BM25Okapi

from ..config import PROJECT_ROOT
from ..texto import normalizar

#: Archivo versionado con las rutas del corpus del proyecto.
RUTA_CONFIG = PROJECT_ROOT / "config" / "escena.toml"
#: Rutas por defecto del corpus del proyecto, relativas a la raíz.
RUTAS_PROYECTO: tuple[str, ...] = ("README.md", "AGENTS.md", "CONSTITUTION.md", "docs")
#: Archivos de la raíz que sí entran al corpus.
ARCHIVOS_RAIZ: frozenset[str] = frozenset({"README.md", "AGENTS.md", "CONSTITUTION.md"})
#: Caracteres máximos de un fragmento; las secciones muy largas se recortan.
MAX_CARACTERES_FRAGMENTO = 3000
#: Fragmentos que devuelve una búsqueda por defecto.
MAX_FRAGMENTOS = 3
#: Puntaje mínimo de trabajo del fragmento elegido.
PUNTAJE_MINIMO = 0.9
#: Encabezado Markdown de nivel 1 a 6.
_ENCABEZADO = re.compile(r"(?m)^(?P<nivel>#{1,6})[ \t]+(?P<titulo>.+?)[ \t]*$")
#: Palabra alfanumérica ya normalizada.
_PALABRA = re.compile(r"[a-z0-9]+")

#: Señales léxicas de que la pregunta habla del proyecto y no del banco.
#: Se comparan por palabra completa y ya normalizadas (sin tildes).
#: Una palabra del banco que no aparezca aquí deja la pregunta en el paso 3,
#: aunque el corpus de ``docs/`` también mencione tasas y productos.
PALABRAS_PROYECTO: frozenset[str] = frozenset(
    {
        "1581",
        "agente",
        "anny",
        "arqueo",
        "arquitectura",
        "auditor",
        "bm25",
        "boveda",
        "bronze",
        "chunk",
        "chunks",
        "chroma",
        "comite",
        "construyeron",
        "corpus",
        "darley",
        "dataset",
        "datasets",
        "decision",
        "decisiones",
        "deepseek",
        "diseno",
        "disenos",
        "eligieron",
        "embedding",
        "embeddings",
        "equipo",
        "escena",
        "escenas",
        "evaluacion",
        "evaluaron",
        "exposicion",
        "ficha",
        "fichas",
        "fragmento",
        "fragmentos",
        "gateway",
        "git",
        "github",
        "gold",
        "gota",
        "herramientas",
        "hicieron",
        "implementacion",
        "implementaron",
        "indice",
        "indices",
        "integrantes",
        "inyeccion",
        "jan",
        "langchain",
        "langgraph",
        "latencia",
        "ley",
        "licencia",
        "limitaciones",
        "mcnemar",
        "mcp",
        "medallion",
        "memoria",
        "metrica",
        "metricas",
        "midieron",
        "modelo",
        "modelos",
        "nayla",
        "ndcg",
        "noticia",
        "noticias",
        "ollama",
        "openclaw",
        "pana",
        "pdf",
        "pdfs",
        "piper",
        "pipeline",
        "polanco",
        "prompt",
        "prompts",
        "pruebas",
        "proyecto",
        "proyectos",
        "qdrant",
        "rag",
        "recuperacion",
        "recuperador",
        "repositorio",
        "repositorios",
        "retrato",
        "retratos",
        "rostro",
        "rostros",
        "scraping",
        "silver",
        "simulacion",
        "simulador",
        "sitemap",
        "sustentacion",
        "taaml",
        "taller",
        "tallerista",
        "trafilatura",
        "uao",
        "usaron",
        "vectorial",
        "video",
        "videos",
        "voces",
        "voz",
        "whatsapp",
        "yoldy",
    }
)


@dataclass(frozen=True, slots=True)
class FragmentoProyecto:
    """Sección de un documento del proyecto, con su ruta y su ancla.

    ``puntaje`` lo llena la búsqueda: es el BM25 del fragmento dividido por el
    IDF máximo del corpus, de modo que un valor mayor que el mínimo del llamador
    indica una coincidencia real y no solo una palabra común.
    """

    ruta: str
    ancla: str
    titulo: str
    texto: str
    puntaje: float = 0.0

    @property
    def referencia(self) -> str:
        """Referencia verificable ``ruta#ancla`` que cita el turno."""
        return f"{self.ruta}#{self.ancla}"


class RecuperadorProyecto(Protocol):
    """Parte del recuperador del proyecto que necesita el enrutador."""

    def buscar(self, consulta: str, k: int = MAX_FRAGMENTOS) -> list[FragmentoProyecto]:
        """Devuelve hasta ``k`` fragmentos ordenados de mayor a menor puntaje."""
        ...


def cargar_rutas_proyecto(ruta: Path | None = None) -> tuple[str, ...]:
    """Lee ``[preguntas.proyecto]`` de ``config/escena.toml``.

    Args:
        ruta: archivo TOML alternativo; por defecto ``config/escena.toml``.

    Returns:
        Las rutas configuradas o las de :data:`RUTAS_PROYECTO` si la sección
        falta. La validación de que cada ruta viva dentro del repositorio la
        hace :class:`RecuperadorBM25Proyecto` al indexar.
    """
    archivo = RUTA_CONFIG if ruta is None else Path(ruta)
    if not archivo.exists():
        return RUTAS_PROYECTO
    with archivo.open("rb") as fh:
        datos = tomllib.load(fh)
    seccion = datos.get("preguntas", {})
    proyecto = seccion.get("proyecto", {}) if isinstance(seccion, dict) else {}
    rutas = proyecto.get("rutas", list(RUTAS_PROYECTO)) if isinstance(proyecto, dict) else None
    if not isinstance(rutas, list) or not rutas:
        return RUTAS_PROYECTO
    limpias = tuple(str(valor).strip() for valor in rutas if str(valor).strip())
    return limpias or RUTAS_PROYECTO


def es_pregunta_del_proyecto(pregunta: str) -> bool:
    """Decide si la pregunta habla del proyecto y no solo del banco.

    La señal es léxica y determinista: al menos una palabra normalizada de la
    pregunta pertenece a :data:`PALABRAS_PROYECTO`. El corpus de ``docs/``
    incluye las preguntas del banco; sin esta señal, una pregunta de tasa
    encontraría un documento que la menciona y el paso 2 la respondería como si
    fuera de diseño. La decisión final la confirma el puntaje BM25.

    Args:
        pregunta: texto del público, ya saneado o no.

    Returns:
        True si la pregunta menciona el repositorio, el corpus, el RAG, una
        decisión de diseño o el taller.
    """
    return bool(set(_tokenizar(pregunta)) & PALABRAS_PROYECTO)


def crear_recuperador_proyecto(
    raiz: Path | None = None,
    rutas: Sequence[str] | None = None,
) -> RecuperadorBM25Proyecto:
    """Crea el recuperador BM25 del proyecto con el corpus versionado.

    Args:
        raiz: raíz del repositorio; por defecto ``PROJECT_ROOT``.
        rutas: rutas relativas del corpus; por defecto las del TOML.

    Returns:
        Un recuperador que arma su índice en memoria en la primera búsqueda.
    """
    return RecuperadorBM25Proyecto(
        raiz=raiz or PROJECT_ROOT,
        rutas=rutas if rutas is not None else cargar_rutas_proyecto(),
    )


class RecuperadorBM25Proyecto:
    """Índice BM25 en memoria sobre el corpus acotado del proyecto."""

    def __init__(
        self,
        raiz: Path,
        rutas: Sequence[str],
    ) -> None:
        """Guarda la raíz y las rutas; el índice se arma en la primera búsqueda.

        Args:
            raiz: raíz del repositorio.
            rutas: rutas relativas de archivos o carpetas del corpus.
        """
        self._raiz = Path(raiz).resolve()
        self._rutas = tuple(rutas)
        self._fragmentos: tuple[FragmentoProyecto, ...] | None = None
        self._bm25: Any | None = None
        self._max_idf = 1.0
        self._candado = threading.Lock()

    def rutas_indexadas(self) -> tuple[str, ...]:
        """Devuelve las rutas relativas que entraron al índice, sin repetir.

        Returns:
            Las rutas en orden estable; vacío si el corpus no tiene archivos.
        """
        fragmentos = self._indice()[0]
        return tuple(dict.fromkeys(fragmento.ruta for fragmento in fragmentos))

    def buscar(self, consulta: str, k: int = MAX_FRAGMENTOS) -> list[FragmentoProyecto]:
        """Busca los fragmentos más relevantes para la consulta.

        Args:
            consulta: pregunta del público.
            k: número máximo de fragmentos que se devuelven.

        Returns:
            Los fragmentos con mayor BM25, con ``puntaje`` normalizado por el
            IDF máximo del corpus. Una consulta sin palabras devuelve una lista
            vacía.

        Raises:
            ValueError: si ``k`` no es mayor que cero.
        """
        if k <= 0:
            raise ValueError("k debe ser mayor que cero")
        palabras = _tokenizar(consulta)
        if not palabras:
            return []
        fragmentos, bm25, max_idf = self._indice()
        if bm25 is None or not fragmentos:
            return []
        puntajes = [float(valor) for valor in bm25.get_scores(palabras)]
        orden = sorted(range(len(fragmentos)), key=lambda posicion: (-puntajes[posicion], posicion))
        resultados: list[FragmentoProyecto] = []
        for posicion in orden[:k]:
            if puntajes[posicion] <= 0:
                continue
            resultados.append(replace(fragmentos[posicion], puntaje=puntajes[posicion] / max_idf))
        return resultados

    def _indice(self) -> tuple[tuple[FragmentoProyecto, ...], Any | None, float]:
        """Arma el índice una sola vez y lo reutiliza en las búsquedas siguientes."""
        if self._fragmentos is not None:
            return self._fragmentos, self._bm25, self._max_idf
        with self._candado:
            if self._fragmentos is None:
                fragmentos = self._leer_fragmentos()
                self._fragmentos = tuple(fragmentos)
                if fragmentos:
                    self._bm25 = BM25Okapi(
                        [_tokenizar(fragmento.texto) for fragmento in fragmentos]
                    )
                    self._max_idf = max(float(valor) for valor in self._bm25.idf.values())
                    if self._max_idf <= 0:
                        self._max_idf = 1.0
        return self._fragmentos, self._bm25, self._max_idf

    def _leer_fragmentos(self) -> list[FragmentoProyecto]:
        """Lee el corpus acotado y lo parte por encabezados Markdown."""
        fragmentos: list[FragmentoProyecto] = []
        for archivo in self._archivos():
            try:
                contenido = archivo.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            ruta = archivo.relative_to(self._raiz).as_posix()
            fragmentos.extend(_partir_documento(ruta, contenido))
        return fragmentos

    def _archivos(self) -> list[Path]:
        """Lista los archivos permitidos del corpus, sin salir de la raíz."""
        vistos: set[Path] = set()
        archivos: list[Path] = []
        for entrada in self._rutas:
            candidato = (self._raiz / entrada).resolve()
            if candidato.is_dir():
                candidatos = sorted(ruta for ruta in candidato.rglob("*.md") if ruta.is_file())
            elif candidato.is_file():
                candidatos = [candidato]
            else:
                continue
            for archivo in candidatos:
                resuelto = archivo.resolve()
                if resuelto in vistos or not self._permitida(resuelto):
                    continue
                vistos.add(resuelto)
                archivos.append(resuelto)
        return archivos

    def _permitida(self, archivo: Path) -> bool:
        """Comprueba que el archivo sea un ``.md`` del corpus acotado."""
        if archivo.suffix.lower() != ".md":
            return False
        try:
            relativa = archivo.relative_to(self._raiz)
        except ValueError:
            return False
        if relativa.as_posix() in ARCHIVOS_RAIZ:
            return True
        return bool(relativa.parts) and relativa.parts[0] == "docs"


def _partir_documento(ruta: str, contenido: str) -> list[FragmentoProyecto]:
    """Parte un documento por encabezados y calcula un ancla única por sección."""
    coincidencias = list(_ENCABEZADO.finditer(contenido))
    if not coincidencias:
        texto = contenido.strip()
        return (
            [FragmentoProyecto(ruta, "inicio", ruta, texto[:MAX_CARACTERES_FRAGMENTO])]
            if texto
            else []
        )

    fragmentos: list[FragmentoProyecto] = []
    vistos: dict[str, int] = {}
    preambulo = contenido[: coincidencias[0].start()].strip()
    if preambulo:
        fragmentos.append(
            FragmentoProyecto(ruta, "inicio", ruta, preambulo[:MAX_CARACTERES_FRAGMENTO])
        )
    for indice, coincidencia in enumerate(coincidencias):
        fin = (
            coincidencias[indice + 1].start() if indice + 1 < len(coincidencias) else len(contenido)
        )
        cuerpo = contenido[coincidencia.end() : fin].strip()
        if not cuerpo:
            continue
        titulo = coincidencia.group("titulo").strip()
        ancla = _ancla(titulo, vistos)
        texto = f"{titulo}\n{cuerpo}"[:MAX_CARACTERES_FRAGMENTO]
        fragmentos.append(FragmentoProyecto(ruta, ancla, titulo, texto))
    return fragmentos


def _ancla(titulo: str, vistos: dict[str, int]) -> str:
    """Convierte un título en un ancla estable y única dentro del archivo."""
    base = re.sub(r"[^a-z0-9]+", "-", normalizar(titulo)).strip("-") or "seccion"
    cantidad = vistos.get(base, 0) + 1
    vistos[base] = cantidad
    return base if cantidad == 1 else f"{base}-{cantidad}"


def _tokenizar(texto: str) -> list[str]:
    """Divide un texto en palabras normalizadas (sin tildes) para BM25."""
    return _PALABRA.findall(normalizar(texto))
