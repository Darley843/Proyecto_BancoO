"""Ingesta de noticias: hechos relevantes oficiales y prensa externa curada."""

from __future__ import annotations

import logging
import re
import unicodedata
from collections.abc import Mapping
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlsplit, urlunsplit

import yaml
from bs4 import BeautifulSoup, Tag

from .utils import read_jsonl

log = logging.getLogger(__name__)

#: Base publica usada para convertir los enlaces relativos de la tabla oficial.
BASE_URL = "https://www.bancodeoccidente.com.co"

#: Tope de hechos oficiales que se conservan despues de ordenar por fecha.
MAX_HECHOS_OFICIALES = 40

#: Columnas que identifican la tabla de hechos relevantes.
COLUMNAS_HECHOS = ("fecha", "tema", "resumen", "anexo descargable")

_MESES_ES: dict[str, int] = {
    "enero": 1,
    "febrero": 2,
    "marzo": 3,
    "abril": 4,
    "mayo": 5,
    "junio": 6,
    "julio": 7,
    "agosto": 8,
    "septiembre": 9,
    "setiembre": 9,
    "octubre": 10,
    "noviembre": 11,
    "diciembre": 12,
}

_FECHA_ES = re.compile(r"^(?P<mes>[a-z]+)\s+(?P<dia>\d{1,2})\s*-\s*(?P<anio>\d{4})$")

_TEMAS_DIVIDENDO = {
    "dividendos",
    "pago de dividendos",
    "pago de dividendo",
    "aviso de dividendos",
    "aviso de pago de dividendos",
    "aviso de pago de dividendo",
}

_PII_CORREO = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_PII_NIT = re.compile(r"\bnit\b[^\d]{0,12}\d{3}[.\s]?\d{3}[.\s]?\d{3}-?\d?")
_PII_CEDULA = re.compile(
    r"(?:\bc\.?\s?c\.?|\bcedula(?: de ciudadania)?\b|\bdocumento de identidad\b)"
    r"[^\d]{0,12}(?:\d{6,10}|\d{1,3}(?:[.\s]\d{3}){1,3})"
)
_PII_TELEFONO = re.compile(
    r"(?:\b(?:telefono|celular|tel|movil)\b[^\d]{0,12}(?:\+?57[.\s-]*)?(?:\d[.\s-]?){7,10}"
    r"|\+57[.\s-]*(?:\d[.\s-]?){7,10})"
)

_HOSTS_BANCO = {
    "bancodeoccidente.com.co",
    "www.bancodeoccidente.com.co",
    "portalpublico.bancodeoccidente.com.co",
}

_CAMPOS_PRENSA = (
    "id",
    "fecha",
    "medio",
    "titulo",
    "url",
    "resumen",
    "temas",
    "relevancia",
    "estado",
)

_ESTADOS_PRENSA = frozenset({"pendiente", "verificado"})
_RELEVANCIAS_PRENSA = frozenset({"alta", "media", "baja"})
_FECHA_ISO = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _normalizar_espacios(texto: str) -> str:
    """Colapsa espacios, saltos de linea y extremos de un texto."""
    return re.sub(r"\s+", " ", (texto or "")).strip()


def _sin_acentos(texto: str) -> str:
    """Pasa un texto a minusculas y le quita las tildes para compararlo."""
    descompuesto = unicodedata.normalize("NFKD", texto.lower())
    return "".join(caracter for caracter in descompuesto if not unicodedata.combining(caracter))


def parse_fecha_es(texto: str) -> date:
    """Convierte una fecha oficial como ``Octubre 19-2026`` a ``date``.

    Admite nombres de mes en espanol con o sin tildes, dia de una o dos cifras
    y un guion con espacios opcionales antes del anio. Tambien acepta una fecha
    ISO ya normalizada. Lanza ``ValueError`` si el texto no es una fecha valida.
    """
    original = texto
    limpio = _sin_acentos(_normalizar_espacios(texto)).strip(" .")
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", limpio):
        try:
            return date.fromisoformat(limpio)
        except ValueError as exc:
            raise ValueError(f"Fecha invalida: {original!r}") from exc

    coincidencia = _FECHA_ES.match(limpio)
    if not coincidencia:
        raise ValueError(f"Fecha no reconocida: {original!r}")

    mes = _MESES_ES.get(coincidencia.group("mes"))
    if mes is None:
        raise ValueError(f"Mes no reconocido en la fecha: {original!r}")

    try:
        return date(int(coincidencia.group("anio")), mes, int(coincidencia.group("dia")))
    except ValueError as exc:
        raise ValueError(f"Fecha invalida: {original!r}") from exc


def derivar_titulo(tema: str, resumen: str) -> str:
    """Deriva un titular legible a partir del tema oficial o del resumen."""
    base = _normalizar_espacios(tema).rstrip(" .;:")
    if not base:
        base = _primera_frase(_normalizar_espacios(resumen)).rstrip(" .;:")
    if not base:
        return "Hecho relevante"
    if len(base) > 120:
        base = base[:120].rsplit(" ", 1)[0].rstrip(" ,;:") + "..."
    return base[0].upper() + base[1:]


def derivar_resumen(resumen: str, *, limite: int = 600) -> str:
    """Normaliza el resumen oficial y lo recorta a un maximo legible."""
    texto = _normalizar_espacios(resumen)
    if len(texto) <= limite:
        return texto
    recorte = texto[:limite].rsplit(" ", 1)[0].rstrip(" ,;:")
    return f"{recorte}..."


def es_aviso_dividendo(tema: str, resumen: str) -> bool:
    """Indica si el evento es un aviso mensual rutinario de dividendos."""
    tema_plano = _sin_acentos(_normalizar_espacios(tema)).strip(" .;:")
    if tema_plano in _TEMAS_DIVIDENDO:
        return True

    texto = _sin_acentos(f"{tema} {resumen}")
    if "dividendo" not in texto:
        return False
    return bool(
        re.search(r"\b(aviso|pago|pagos)\b", texto)
        and re.search(r"\b(mensual|mensuales|mes)\b", texto)
    )


def validar_pii(titulo: str, resumen: str) -> list[str]:
    """Devuelve las categorias de datos personales halladas en la ficha.

    Revisa cedula, NIT, correo y telefono en el titulo y el resumen. Una lista
    vacia significa que la ficha puede publicarse desde el punto de vista de
    privacidad.
    """
    texto = _sin_acentos(_normalizar_espacios(f"{titulo} {resumen}"))
    hallazgos: list[str] = []
    if _PII_CORREO.search(texto):
        hallazgos.append("correo")
    if _PII_NIT.search(texto):
        hallazgos.append("nit")
    if _PII_CEDULA.search(texto):
        hallazgos.append("cedula")
    if _PII_TELEFONO.search(texto):
        hallazgos.append("telefono")
    return hallazgos


def _primera_frase(texto: str) -> str:
    """Devuelve la primera frase de un texto ya normalizado."""
    coincidencia = re.match(r"(.+?[.!?])(?:\s|$)", texto)
    return coincidencia.group(1) if coincidencia else texto


def _columnas_de_encabezado(fila: Tag) -> dict[str, int]:
    """Mapea las etiquetas normalizadas de una fila de encabezado a su columna."""
    columnas: dict[str, int] = {}
    for indice, celda in enumerate(fila.find_all(["th", "td"], recursive=False)):
        etiqueta = _sin_acentos(_normalizar_espacios(celda.get_text(" ", strip=True)))
        if etiqueta in COLUMNAS_HECHOS:
            columnas[etiqueta] = indice
    return columnas


def _buscar_tabla_hechos(tabla: Tag) -> tuple[int, dict[str, int]] | None:
    """Localiza la fila de encabezados y las columnas de la tabla de hechos."""
    for posicion, fila in enumerate(tabla.find_all("tr")):
        columnas = _columnas_de_encabezado(fila)
        if all(nombre in columnas for nombre in COLUMNAS_HECHOS):
            return posicion, columnas
    return None


def _normalizar_anexo(href: str) -> str | None:
    """Convierte un enlace de anexo en una URL absoluta y sin fragmento."""
    limpio = _normalizar_espacios(href)
    if not limpio or limpio.startswith(("#", "javascript:", "mailto:", "tel:")):
        return None

    absoluta = urljoin(f"{BASE_URL}/", limpio)
    partes = urlsplit(absoluta)
    if partes.scheme not in {"http", "https"} or not partes.netloc:
        return None
    return urlunsplit((partes.scheme, partes.netloc.lower(), partes.path, partes.query, ""))


def _anexo_de_celda(celda: Tag | None) -> str | None:
    """Extrae y normaliza el enlace ``Ver Anexo`` de la celda de anexos."""
    if celda is None:
        return None
    enlace = celda.find("a", href=True)
    if enlace is None:
        return None
    return _normalizar_anexo(str(enlace.get("href", "")))


def _texto_celda(celdas: list[Tag], columnas: dict[str, int], nombre: str) -> str:
    """Devuelve el texto normalizado de una columna concreta de la fila."""
    indice = columnas[nombre]
    if indice >= len(celdas):
        return ""
    return _normalizar_espacios(celdas[indice].get_text(" ", strip=True))


def parse_hechos_relevantes(
    html: str,
    desde: date,
    hasta: date,
    *,
    max_oficiales: int = MAX_HECHOS_OFICIALES,
) -> list[dict[str, Any]]:
    """Extrae los hechos relevantes oficiales dentro de una ventana de fechas.

    Solo procesa las tablas cuyos encabezados sean ``Fecha``, ``Tema``,
    ``Resumen`` y ``Anexo Descargable``. Ignora la tabla de accionistas, los
    avisos mensuales de dividendos y cualquier fila con datos personales.
    Ordena de mas reciente a mas antiguo y aplica el tope indicado.
    """
    if hasta < desde:
        raise ValueError("La fecha 'hasta' no puede ser anterior a 'desde'")

    sopa = BeautifulSoup(html, "lxml")
    hechos: list[dict[str, Any]] = []
    vistos: set[tuple[str, str, str, str]] = set()

    for tabla in sopa.find_all("table"):
        ubicacion = _buscar_tabla_hechos(tabla)
        if ubicacion is None:
            continue

        posicion_encabezado, columnas = ubicacion
        for fila in tabla.find_all("tr")[posicion_encabezado + 1 :]:
            celdas = fila.find_all(["td", "th"], recursive=False)
            if not celdas or len(celdas) <= max(columnas.values()):
                continue

            fecha_texto = _texto_celda(celdas, columnas, "fecha")
            tema = _texto_celda(celdas, columnas, "tema")
            resumen_crudo = _texto_celda(celdas, columnas, "resumen")
            try:
                fecha = parse_fecha_es(fecha_texto)
            except ValueError:
                log.warning("Se omite una fila con fecha invalida: %r", fecha_texto)
                continue

            if not desde <= fecha <= hasta:
                continue
            if es_aviso_dividendo(tema, resumen_crudo):
                log.info("Se excluye un aviso rutinario de dividendos del %s", fecha)
                continue

            titulo = derivar_titulo(tema, resumen_crudo)
            resumen = derivar_resumen(resumen_crudo)
            hallazgos = validar_pii(titulo, resumen)
            if hallazgos:
                log.warning(
                    "Se omite un hecho del %s con datos personales: %s",
                    fecha,
                    ", ".join(hallazgos),
                )
                continue

            indice_anexo = columnas["anexo descargable"]
            anexo = _anexo_de_celda(celdas[indice_anexo]) if indice_anexo < len(celdas) else None
            clave = (fecha.isoformat(), titulo, resumen, anexo or "")
            if clave in vistos:
                continue
            vistos.add(clave)

            hechos.append(
                {
                    "fecha": fecha,
                    "tema": tema,
                    "titulo": titulo,
                    "resumen": resumen,
                    "anexo": anexo,
                }
            )

    hechos.sort(key=lambda hecho: hecho["fecha"], reverse=True)
    if len(hechos) > max_oficiales:
        log.warning(
            "Se descartaron %d hechos por el tope de %d",
            len(hechos) - max_oficiales,
            max_oficiales,
        )
        hechos = hechos[:max_oficiales]
    return hechos


def _url_canonica(url: str) -> str:
    """Normaliza una URL para comparar variantes del mismo anexo oficial.

    Ignora esquema, query y fragmento, unifica el host del banco entre ``www``
    y ``portalpublico`` y elimina la barra final del camino.
    """
    if not url:
        return ""
    partes = urlsplit(url.strip())
    host = partes.netloc.lower()
    if host in _HOSTS_BANCO:
        host = "bancodeoccidente.com.co"
    camino = partes.path.rstrip("/") or "/"
    return f"{host}{camino}"


def cargar_indice_documentos(path: Path) -> dict[str, dict[str, Any]]:
    """Carga ``documents.jsonl`` en un indice por URL canonica de la fuente."""
    indice: dict[str, dict[str, Any]] = {}
    for fila in read_jsonl(path):
        fuente = str(fila.get("fuente") or fila.get("url") or "").strip()
        if not fuente:
            continue
        indice.setdefault(_url_canonica(fuente), fila)
    return indice


def vincular_documento(
    anexo: str | None, indice: Mapping[str, dict[str, Any]]
) -> dict[str, str] | None:
    """Busca un anexo en el indice Gold de documentos sin descargarlo.

    Acepta el indice indexado por URL canonica o por URL original. Devuelve los
    campos que se copian a la ficha o ``None`` si el anexo no existe en Gold.
    """
    if not anexo:
        return None

    clave = _url_canonica(anexo)
    fila = indice.get(clave)
    if fila is None:
        for url, candidata in indice.items():
            if _url_canonica(url) == clave:
                fila = candidata
                break
    if fila is None:
        return None

    documento_id = str(fila.get("id") or "").strip()
    archivo = Path(str(fila.get("archivo") or "")).name
    if not documento_id or not archivo:
        return None

    return {
        "documento_id": documento_id,
        "documento_archivo": archivo,
        "documento_titulo": str(fila.get("titulo") or "").strip(),
    }


def _tiene_contenido(valor: Any) -> bool:
    """Indica si un valor obligatorio tiene contenido util."""
    if isinstance(valor, str):
        return bool(valor.strip())
    if isinstance(valor, (list, tuple, set, dict)):
        return bool(valor)
    return valor is not None


def _normalizar_fecha(valor: Any) -> str | None:
    """Convierte una fecha ISO o un ``date`` de YAML a ``YYYY-MM-DD``."""
    if isinstance(valor, date):
        return valor.strftime("%Y-%m-%d")
    if not isinstance(valor, str):
        return None
    texto = valor.strip()
    if not _FECHA_ISO.fullmatch(texto):
        return None
    try:
        return date.fromisoformat(texto).isoformat()
    except ValueError:
        return None


def validar_ficha(ficha: Mapping[str, Any]) -> list[str]:
    """Valida los campos minimos de una ficha de prensa externa.

    Devuelve una lista de errores legibles; una lista vacia indica que la ficha
    cumple el contrato minimo. No consulta la red ni modifica la ficha.
    """
    errores: list[str] = []
    for campo in _CAMPOS_PRENSA:
        if not _tiene_contenido(ficha.get(campo)):
            errores.append(f"falta el campo obligatorio '{campo}'")

    for campo in ("id", "medio", "titulo", "resumen"):
        valor = ficha.get(campo)
        if _tiene_contenido(valor) and not isinstance(valor, str):
            errores.append(f"'{campo}' debe ser texto")

    fecha = ficha.get("fecha")
    if _tiene_contenido(fecha) and _normalizar_fecha(fecha) is None:
        errores.append("'fecha' debe ser una fecha ISO valida (YYYY-MM-DD)")

    url = ficha.get("url")
    if _tiene_contenido(url):
        if not isinstance(url, str):
            errores.append("'url' debe ser una URL http(s) valida")
        else:
            partes = urlsplit(url.strip())
            if partes.scheme.lower() not in {"http", "https"} or not partes.netloc:
                errores.append("'url' debe ser una URL http(s) valida")

    estado = ficha.get("estado")
    if _tiene_contenido(estado) and (
        not isinstance(estado, str) or estado.strip().casefold() not in _ESTADOS_PRENSA
    ):
        errores.append("'estado' debe ser 'pendiente' o 'verificado'")

    temas = ficha.get("temas")
    if _tiene_contenido(temas):
        if not isinstance(temas, list):
            errores.append("'temas' debe ser una lista de textos")
        elif not all(isinstance(tema, str) and bool(tema.strip()) for tema in temas):
            errores.append("'temas' no puede contener elementos vacios")

    relevancia = ficha.get("relevancia")
    if _tiene_contenido(relevancia) and (
        not isinstance(relevancia, str) or relevancia.strip().casefold() not in _RELEVANCIAS_PRENSA
    ):
        errores.append("'relevancia' debe ser 'alta', 'media' o 'baja'")

    return errores


def load_prensa(path: Path) -> list[dict[str, Any]]:
    """Carga y valida la curaduria externa desde un YAML local.

    Normaliza la fecha a ``YYYY-MM-DD``. Lanza ``ValueError`` con el archivo y
    el campo invalido si el YAML no existe, no es una lista o alguna ficha no
    cumple el contrato minimo.
    """
    try:
        contenido = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"No existe la curaduria de prensa: {path}") from exc
    except yaml.YAMLError as exc:
        raise ValueError(f"YAML invalido en {path}: {exc}") from exc
    except OSError as exc:
        raise ValueError(f"No se pudo leer la curaduria de prensa {path}: {exc}") from exc

    if not isinstance(contenido, list):
        raise ValueError(f"{path} debe contener una lista de fichas de prensa")

    fichas: list[dict[str, Any]] = []
    for indice, fila in enumerate(contenido, start=1):
        if not isinstance(fila, dict):
            raise ValueError(f"{path}: la ficha {indice} no es un objeto")
        ficha = dict(fila)
        errores = validar_ficha(ficha)
        if errores:
            raise ValueError(f"{path}: ficha {indice} invalida: {'; '.join(errores)}")
        fecha = _normalizar_fecha(ficha.get("fecha"))
        if fecha is not None:
            ficha["fecha"] = fecha
        fichas.append(ficha)
    return fichas


def _clave_fuente(ficha: Mapping[str, Any]) -> str:
    """Normaliza la URL de la ficha para detectar la misma fuente.

    Acepta ``fuente`` (contrato Gold) o ``url`` (curaduria YAML). Ignora
    fragmentos, mayusculas del host y la barra final; conserva la query.
    """
    valor = ficha.get("fuente") or ficha.get("url") or ""
    if not isinstance(valor, str):
        valor = str(valor)
    url = valor.strip()
    if not url:
        return ""
    partes = urlsplit(url)
    if not partes.scheme or not partes.netloc:
        return url
    camino = partes.path.rstrip("/") or "/"
    return urlunsplit((partes.scheme.lower(), partes.netloc.lower(), camino, partes.query, ""))


def deduplicar(
    rows: list[dict[str, Any]],
    *,
    max_por_evento: int = 2,
) -> list[dict[str, Any]]:
    """Elimina fichas duplicadas y limita las coberturas por evento.

    Conserva la primera aparicion por ``id``, por URL de ``fuente``/``url`` y
    por la pareja ``evento`` + ``medio``. Ademas, acepta como maximo
    ``max_por_evento`` coberturas para un mismo evento. No consulta la red.
    """
    if max_por_evento < 1:
        raise ValueError("max_por_evento debe ser al menos 1")

    resultado: list[dict[str, Any]] = []
    ids: set[str] = set()
    fuentes: set[str] = set()
    pares_evento_medio: set[tuple[str, str]] = set()
    por_evento: dict[str, int] = {}

    for fila in rows:
        id_ficha = str(fila.get("id") or "").strip()
        if id_ficha and id_ficha in ids:
            continue

        fuente = _clave_fuente(fila)
        if fuente and fuente in fuentes:
            continue

        evento = _normalizar_espacios(str(fila.get("evento") or "")).casefold()
        medio = _normalizar_espacios(str(fila.get("medio") or "")).casefold()
        par = (evento, medio) if evento and medio else None
        if par is not None and par in pares_evento_medio:
            continue

        if evento and por_evento.get(evento, 0) >= max_por_evento:
            log.info("Se omite una cobertura adicional del evento %s", evento)
            continue

        resultado.append(fila)
        if id_ficha:
            ids.add(id_ficha)
        if fuente:
            fuentes.add(fuente)
        if par is not None:
            pares_evento_medio.add(par)
        if evento:
            por_evento[evento] = por_evento.get(evento, 0) + 1

    return resultado


def filtrar_verificadas(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Devuelve solo las fichas con estado ``verificado``.

    Las fichas ``pendiente`` requieren revision humana y no se publican en Gold.
    """
    return [
        fila for fila in rows if str(fila.get("estado") or "").strip().casefold() == "verificado"
    ]
