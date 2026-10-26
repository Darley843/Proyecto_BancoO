"""Lectura del contexto consolidado y extraccion del canal oficial.

Por defecto se lee ``data/contexto/contexto_banco.md`` **completo y verbatim**:
el mismo texto, en el mismo orden, al inicio del mensaje de sistema. Ese prefijo
identico permite aprovechar la cache de contexto del proveedor. La opcion
experimental ``--max-contexto`` recorta en fronteras de bloque y conserva
siempre el bloque del canal oficial y la informacion comun del sitio.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from ..config import load_config
from ..contexto import RutasContexto
from ..utils import stable_tokens

#: Separadores que se ignoran al comparar cifras y telefonos.
_SEPARADORES = re.compile(r"[\s\u00a0.,\-]")

_TITULO = re.compile(r"^##\s+(?P<titulo>.+?)\s*$")
_URL = re.compile(r"https?://\S+")

_NACIONAL = re.compile(r"018000[\s.-]?\d{6}")
_PATRONES_TELEFONO = (
    _NACIONAL,
    re.compile(r"\(60\d\)[\s.-]?\d{7}"),
    re.compile(r"\b60\d[\s.-]?\d{7}\b"),
    re.compile(r"\+\d{10,13}\b"),
)

_TITULO_COMUN = "informacion comun del sitio"
_RUTA_CANAL = "/ayuda/linea-servicio-cliente"


class ContextoAusente(RuntimeError):
    """No existe ``contexto_banco.md``; hay que generarlo con ``make contexto``."""


class PresupuestoContextoError(RuntimeError):
    """El recorte experimental no alcanza ni para los bloques fijos."""


@dataclass(frozen=True, slots=True)
class CanalOficial:
    """Canal oficial extraido del propio contexto; no hay constantes en el codigo."""

    url: str
    telefono: str
    telefonos: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Bloque:
    """Bloque ``##`` del contexto consolidado."""

    titulo: str
    url: str
    seccion: str
    cuerpo: str
    texto: str
    tokens: int


@dataclass(frozen=True, slots=True)
class ContextoPrompt:
    """Contexto listo para el mensaje de sistema y sus metadatos."""

    texto: str
    tokens: int
    completo: bool
    bloques: int
    descartados: int
    urls: frozenset[str]
    canal: CanalOficial | None


def normalizar_digitos(texto: str) -> str:
    """Quita espacios, puntos, comas y guiones; conserva el resto del texto."""
    return _SEPARADORES.sub("", texto)


def _normalizar_titulo(texto: str) -> str:
    """Minusculas sin acentos y con separadores colapsados, para comparar titulos."""
    sin_acentos = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode("ascii")
    limpio = re.sub(r"[^a-z0-9]+", " ", sin_acentos.lower())
    return " ".join(limpio.split())


def _es_canal(bloque: Bloque) -> bool:
    """Indica si el bloque es la pagina de lineas de servicio al cliente."""
    return (
        "lineas de servicio al cliente" in _normalizar_titulo(bloque.titulo)
        or _RUTA_CANAL in bloque.url
    )


def separar_bloques(texto: str) -> list[Bloque]:
    """Parte el contexto en bloques que empiezan con ``## ``.

    Cada bloque conserva su texto original para poder reconstruir el contexto
    sin reescribir el contenido.
    """
    lineas = texto.splitlines()
    inicios = [indice for indice, linea in enumerate(lineas) if _TITULO.match(linea)]

    bloques: list[Bloque] = []
    for posicion, inicio in enumerate(inicios):
        fin = inicios[posicion + 1] if posicion + 1 < len(inicios) else len(lineas)
        sublineas = lineas[inicio:fin]
        match = _TITULO.match(sublineas[0])
        if not match:
            continue
        titulo = match.group("titulo").strip()

        url = ""
        seccion = ""
        cuerpo_inicio = 1
        for indice in range(1, min(len(sublineas), 8)):
            linea = sublineas[indice].strip()
            if linea.startswith("Fuente:"):
                url = linea.split("Fuente:", 1)[1].strip()
                cuerpo_inicio = indice + 1
            elif linea.startswith("Sección:") or linea.startswith("Seccion:"):
                seccion = linea.split(":", 1)[1].strip()
                cuerpo_inicio = indice + 1
            elif not linea:
                cuerpo_inicio = indice + 1
                break
            else:
                break

        cuerpo = "\n".join(sublineas[cuerpo_inicio:]).strip()
        bloque_texto = "\n".join(sublineas).strip()
        bloques.append(
            Bloque(
                titulo=titulo,
                url=url,
                seccion=seccion,
                cuerpo=cuerpo,
                texto=bloque_texto,
                tokens=stable_tokens(bloque_texto),
            )
        )
    return bloques


def extraer_urls(texto: str) -> frozenset[str]:
    """URLs de las lineas ``Fuente:`` del contexto (solo las que son http)."""
    urls: set[str] = set()
    for linea in texto.splitlines():
        if not linea.strip().lower().startswith("fuente:"):
            continue
        for match in _URL.finditer(linea):
            urls.add(match.group(0).rstrip(").,;]"))
    return frozenset(urls)


def _telefonos(texto: str) -> tuple[str, ...]:
    """Numeros publicos del bloque del canal, normalizados a digitos."""
    encontrados: list[str] = []
    for patron in _PATRONES_TELEFONO:
        for match in patron.finditer(texto):
            digitos = re.sub(r"\D", "", match.group(0))
            if digitos and digitos not in encontrados:
                encontrados.append(digitos)
    return tuple(encontrados)


def _extraer_canal(bloques: list[Bloque]) -> CanalOficial | None:
    """Toma URL y telefonos del bloque de lineas de servicio al cliente."""
    for bloque in bloques:
        if not bloque.url or not _es_canal(bloque):
            continue
        contenido = f"{bloque.titulo}\n{bloque.cuerpo}"
        telefonos = _telefonos(contenido)
        nacional = _NACIONAL.search(contenido)
        if nacional:
            telefono = re.sub(r"[\s.-]+", " ", nacional.group(0)).strip()
        elif telefonos:
            telefono = telefonos[0]
        else:
            telefono = ""
        return CanalOficial(url=bloque.url, telefono=telefono, telefonos=telefonos)
    return None


def _leer_texto(ruta: Path) -> str:
    """Lee el contexto sin traducir saltos de linea (prefijo estable para cache)."""
    with ruta.open("r", encoding="utf-8", newline="") as archivo:
        return archivo.read()


def _construir(preambulo: str, bloques: list[Bloque], indices: set[int]) -> str:
    """Reconstruye el contexto con los bloques elegidos, en el orden original."""
    partes = [preambulo] if preambulo else []
    partes.extend(bloques[indice].texto for indice in sorted(indices))
    return "\n\n".join(partes).strip() + "\n"


def _recortar(texto: str, bloques: list[Bloque], max_tokens: int) -> tuple[str, int, int]:
    """Recorte experimental: prefijo de bloques, conservando los bloques fijos."""
    if not bloques:
        if stable_tokens(texto) <= max_tokens:
            return texto, 0, 0
        raise PresupuestoContextoError(
            f"El contexto no cabe en max_tokens={max_tokens} y no tiene bloques que recortar."
        )

    primer_bloque = texto.find("## ")
    preambulo = (texto[:primer_bloque] if primer_bloque >= 0 else "").strip()
    fijos = {
        indice
        for indice, bloque in enumerate(bloques)
        if _normalizar_titulo(bloque.titulo) == _TITULO_COMUN or _es_canal(bloque)
    }

    actual = _construir(preambulo, bloques, fijos)
    if stable_tokens(actual) > max_tokens:
        raise PresupuestoContextoError(
            f"El contexto no cabe en max_tokens={max_tokens}: el preambulo y los bloques "
            "fijos (informacion comun y canal oficial) ya lo exceden."
        )

    seleccionados = set(fijos)
    for indice in range(len(bloques)):
        if indice in seleccionados:
            continue
        tentativa = seleccionados | {indice}
        if stable_tokens(_construir(preambulo, bloques, tentativa)) <= max_tokens:
            seleccionados = tentativa
        else:
            break

    resultado = _construir(preambulo, bloques, seleccionados)
    return resultado, len(seleccionados), len(bloques) - len(seleccionados)


def cargar_contexto(
    *,
    archivo: Path | None = None,
    max_tokens: int | None = None,
) -> ContextoPrompt:
    """Carga el contexto completo o, en modo experimental, recortado por bloques."""
    ruta = Path(archivo).expanduser() if archivo else RutasContexto.desde(load_config()).archivo
    if not ruta.exists():
        raise ContextoAusente(
            f"No hay contexto en {ruta}. Ejecuta 'make contexto' para generarlo desde Gold."
        )

    texto = _leer_texto(ruta)
    bloques = separar_bloques(texto)
    total_tokens = stable_tokens(texto)
    urls = extraer_urls(texto)
    canal = _extraer_canal(bloques)

    if max_tokens is None:
        return ContextoPrompt(
            texto=texto,
            tokens=total_tokens,
            completo=True,
            bloques=len(bloques),
            descartados=0,
            urls=urls,
            canal=canal,
        )

    if max_tokens <= 0:
        raise ValueError("max_tokens debe ser un entero positivo.")

    recortado, conservados, descartados = _recortar(texto, bloques, max_tokens)
    bloques_recortados = separar_bloques(recortado)
    return ContextoPrompt(
        texto=recortado,
        tokens=stable_tokens(recortado),
        completo=False,
        bloques=conservados,
        descartados=descartados,
        urls=extraer_urls(recortado),
        canal=_extraer_canal(bloques_recortados),
    )
