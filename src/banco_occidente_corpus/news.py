"""Ingesta de noticias: hechos relevantes oficiales y prensa externa curada."""

from __future__ import annotations

import logging
import re
import unicodedata
from collections import Counter
from collections.abc import Mapping
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlsplit, urlunsplit

import yaml
from bs4 import BeautifulSoup, Tag

from .config import Config
from .net import BlockedError, HttpClient
from .utils import (
    append_jsonl,
    count_words,
    estimate_tokens,
    read_jsonl,
    sha256_text,
    short_hash,
    slugify,
    utc_now,
    write_jsonl,
)

log = logging.getLogger(__name__)

#: Base publica usada para convertir los enlaces relativos de la tabla oficial.
BASE_URL = "https://www.bancodeoccidente.com.co"

#: Pagina oficial que contiene la tabla "Informacion Relevante".
OFFICIAL_PAGE_URL = f"{BASE_URL}/quienes-somos/informacion-inversionistas"

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

#: Temas oficiales demasiado genericos: el titular se deriva del resumen.
_TEMAS_GENERICOS = {
    "otro evento",
    "otros eventos",
    "informe de fin de ejercicio",
    "informes de fin de ejercicio",
}

#: Temas de tramite que no deben desplazar a un hito material en el tope.
_TEMAS_RUTINARIOS = {
    "convocatoria de asamblea de inversionistas",
    "convocatorias de asamblea de inversionistas",
    "convocatoria de asambleas de inversionistas",
    "convocatorias de asambleas de inversionistas",
}

_CLAVES_RELEVANCIA_ALTA = (
    "absorcion",
    "adquisicion",
    "aporte en especie",
    "acuerdo material",
    "credito subordinado",
    "emision de valores",
    "escision",
    "esision",
    "fusion",
    "reestructuracion",
)

_CLAVES_RELEVANCIA_MEDIA = (
    "acciones ordinarias",
    "bonos subordinados",
    "calificacion",
    "decisiones adoptadas",
    "distribucion de utilidades",
    "estados financieros",
    "informe de fin de ejercicio",
    "informe periodico",
    "junta directiva",
    "mejores practicas corporativas",
    "nombramiento",
    "novedades de los directores",
    "patrimonio adicional",
    "renuncia",
    "resultados",
)

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


def _tema_plano(tema: str) -> str:
    """Normaliza un tema oficial para compararlo sin tildes ni puntuacion."""
    return _sin_acentos(_normalizar_espacios(tema)).strip(" .;:")


def es_tema_generico(tema: str) -> bool:
    """Indica si el tema es un cajon de sastre y el titulo debe salir del resumen."""
    return _tema_plano(tema) in _TEMAS_GENERICOS


def _titulo_desde_resumen(resumen: str) -> str:
    """Extrae del resumen una frase corta que explique que ocurrio.

    Quita el encabezado de alcance, el sujeto ``Banco de Occidente``, los
    verbos de comunicacion y las clausulas legales o temporales iniciales. Si
    aun queda texto, devuelve la primera frase como titular.
    """
    texto = _normalizar_espacios(resumen)
    if not texto:
        return ""

    texto = re.sub(r"^alcance\s*[-–—:]\s*", "", texto, flags=re.IGNORECASE)

    if texto.casefold().startswith(("en cumplimiento", "conforme", "de acuerdo")):
        banco = re.search(r"\b(?:el\s+)?banco de occidente\b", texto, flags=re.IGNORECASE)
        if banco is not None and 0 < banco.start() <= 300:
            texto = texto[banco.start() :]
        else:
            texto = re.sub(
                r"^(?:en cumplimiento|conforme|de acuerdo)\b[^,]{0,240},\s*",
                "",
                texto,
                flags=re.IGNORECASE,
            )

    texto = re.sub(
        r"^(?:el\s+)?banco de occidente(?:\s+s\.a\.)?\s*[,;:]?\s*",
        "",
        texto,
        flags=re.IGNORECASE,
    )

    for _ in range(2):
        texto = re.sub(
            r"^(?:se permite\s+)?informa(?:r)?(?: al mercado)?\s*,?\s*(?:que\s*,?\s*)?",
            "",
            texto,
            flags=re.IGNORECASE,
        )
        texto = re.sub(
            r"^(?:adjunta|remite|publica|transmite|transmitimos)\s+",
            "",
            texto,
            flags=re.IGNORECASE,
        )
        texto = re.sub(r"^sobre\s+", "", texto, flags=re.IGNORECASE)
        texto = re.sub(
            r"^(?:el|en el)\s+d[ií]a de hoy\s*,\s*",
            "",
            texto,
            flags=re.IGNORECASE,
        )
        texto = re.sub(
            r"^(?:contando|conforme|de acuerdo|en cumplimiento|mediante)\b[^,]{0,180},\s*",
            "",
            texto,
            flags=re.IGNORECASE,
        )

    texto = _primera_frase(texto).strip(" .;:,")
    texto = re.sub(r"^(?:el|la|los|las|un|una)\s+", "", texto, flags=re.IGNORECASE)
    return texto.strip(" .;:,")


def derivar_titulo(tema: str, resumen: str) -> str:
    """Deriva un titular legible a partir del tema oficial o del resumen.

    Los temas genericos como ``Otros eventos`` o ``Informes de fin de
    ejercicio`` no identifican el hecho: en esos casos el titular se toma de la
    primera frase util del resumen.
    """
    tema_limpio = _normalizar_espacios(tema).rstrip(" .;:")
    base = _titulo_desde_resumen(resumen) if es_tema_generico(tema) else tema_limpio
    if not base:
        base = tema_limpio or "Hecho relevante"
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
    """Devuelve la primera frase sin cortar abreviaturas como ``S.A.``."""
    return re.split(r"(?<=[.!?])\s+(?=[A-ZÁÉÍÓÚÜÑ¿¡])", texto, maxsplit=1)[0]


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


def _puntaje_relevancia(tema: str, resumen: str) -> int:
    """Asigna una prioridad numerica a un hecho segun su materialidad.

    Cero corresponde a una convocatoria rutinaria; los valores mas altos a
    hitos corporativos. El resumen tambien pesa porque ``Otros eventos`` puede
    esconder una absorcion o un credito subordinado.
    """
    tema_plano = _tema_plano(tema)
    if tema_plano in _TEMAS_RUTINARIOS or (
        "convocatoria" in tema_plano and "asamblea" in tema_plano
    ):
        return 0

    texto = _sin_acentos(f"{tema} {resumen}")
    if any(clave in texto for clave in _CLAVES_RELEVANCIA_ALTA):
        return 5
    if any(clave in texto for clave in _CLAVES_RELEVANCIA_MEDIA):
        return 4
    if tema_plano in _TEMAS_GENERICOS:
        return 2
    return 3


def _etiqueta_relevancia(puntaje: int) -> str:
    """Traduce el puntaje interno a la etiqueta del contrato Gold."""
    if puntaje >= 4:
        return "alta"
    if puntaje == 3:
        return "media"
    return "baja"


def _consolidar_hechos(hechos: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Agrupa por fecha y tema los hechos que describen el mismo acontecimiento.

    Une los resumenes sin repetirlos, conserva el primer anexo disponible y
    deriva un solo titulo y una sola relevancia para el grupo.
    """
    grupos: dict[tuple[str, str], dict[str, Any]] = {}
    orden: list[tuple[str, str]] = []

    for hecho in hechos:
        fecha = hecho["fecha"]
        clave = (fecha.isoformat(), _tema_plano(str(hecho.get("tema") or "")))
        grupo = grupos.get(clave)
        if grupo is None:
            grupo = {
                "fecha": fecha,
                "tema": str(hecho.get("tema") or ""),
                "resumenes": [],
                "anexos": [],
            }
            grupos[clave] = grupo
            orden.append(clave)

        resumen = _normalizar_espacios(str(hecho.get("resumen") or ""))
        if resumen and resumen not in grupo["resumenes"]:
            grupo["resumenes"].append(resumen)

        anexo = hecho.get("anexo")
        if isinstance(anexo, str) and anexo.strip() and anexo not in grupo["anexos"]:
            grupo["anexos"].append(anexo.strip())

    consolidados: list[dict[str, Any]] = []
    for clave in orden:
        grupo = grupos[clave]
        resumen = " ".join(grupo["resumenes"])
        tema = grupo["tema"]
        puntaje = _puntaje_relevancia(tema, resumen)
        consolidados.append(
            {
                "fecha": grupo["fecha"],
                "tema": tema,
                "titulo": derivar_titulo(tema, resumen),
                "resumen": derivar_resumen(resumen),
                "anexo": grupo["anexos"][0] if grupo["anexos"] else None,
                "relevancia": _etiqueta_relevancia(puntaje),
                "_puntaje": puntaje,
            }
        )
    return consolidados


def _seleccionar_hechos(
    hechos: list[dict[str, Any]],
    max_oficiales: int,
) -> list[dict[str, Any]]:
    """Aplica el tope priorizando materialidad y cobertura de la ventana.

    Ordena por relevancia y, en empate, por fecha descendente. Antes de llenar
    los cupos restantes reserva el mejor hecho material de cada anio presente
    para no perder la parte antigua de la ventana. Las convocatorias rutinarias
    solo ocupan cupos sobrantes.
    """
    if max_oficiales < 1:
        raise ValueError("max_oficiales debe ser al menos 1")

    ordenados = sorted(
        hechos,
        key=lambda hecho: (
            -int(hecho["_puntaje"]),
            -hecho["fecha"].toordinal(),
            _tema_plano(str(hecho.get("tema") or "")),
            str(hecho.get("titulo") or ""),
        ),
    )
    if len(ordenados) <= max_oficiales:
        seleccionados = list(ordenados)
    else:
        seleccionados = []
        elegidos: set[int] = set()
        anios = sorted({hecho["fecha"].year for hecho in ordenados})
        if len(anios) <= max_oficiales:
            for anio in anios:
                for hecho in ordenados:
                    if hecho["fecha"].year == anio:
                        if int(hecho["_puntaje"]) >= 3:
                            seleccionados.append(hecho)
                            elegidos.add(id(hecho))
                        break
        for hecho in ordenados:
            if len(seleccionados) >= max_oficiales:
                break
            if id(hecho) not in elegidos:
                seleccionados.append(hecho)
                elegidos.add(id(hecho))

    seleccionados.sort(key=lambda hecho: hecho["fecha"], reverse=True)
    return seleccionados


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
    Consolida los hechos del mismo tema y fecha, aplica el tope priorizando
    hitos materiales sobre convocatorias rutinarias y devuelve el resultado de
    mas reciente a mas antiguo.
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

    consolidados = _consolidar_hechos(hechos)
    if len(consolidados) < len(hechos):
        log.info(
            "Se consolidaron %d filas en %d hechos por fecha y tema",
            len(hechos),
            len(consolidados),
        )

    seleccionados = _seleccionar_hechos(consolidados, max_oficiales)
    if len(consolidados) > max_oficiales:
        log.warning(
            "Se descartaron %d hechos por el tope de %d, priorizando materialidad",
            len(consolidados) - max_oficiales,
            max_oficiales,
        )
    for hecho in seleccionados:
        hecho.pop("_puntaje", None)
    return seleccionados


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


def _es_id_ficha(valor: Any) -> bool:
    """Indica si un id corresponde a una ficha de noticias o de hechos."""
    return isinstance(valor, str) and valor.startswith(("noticia-", "hecho-"))


def _campo_texto(row: Mapping[str, Any], *claves: str, default: str = "") -> str:
    """Devuelve el primer valor de texto no vacio entre varias claves."""
    for clave in claves:
        valor = row.get(clave)
        if valor is None:
            continue
        texto = _normalizar_espacios(str(valor))
        if texto:
            return texto
    return default


def _lista_textos(valor: Any) -> list[str]:
    """Normaliza una lista de temas o una cadena separada por comas."""
    if valor is None:
        return []
    if isinstance(valor, str):
        return [
            tema for tema in (_normalizar_espacios(parte) for parte in valor.split(",")) if tema
        ]
    if isinstance(valor, (list, tuple, set)):
        textos = (_normalizar_espacios(str(elemento)) for elemento in valor)
        return [texto for texto in textos if texto]
    return []


def _fecha_iso_obligatoria(valor: Any) -> str:
    """Normaliza una fecha de publicacion a ISO o lanza ``ValueError``."""
    fecha = _normalizar_fecha(valor)
    if fecha is None:
        raise ValueError(f"Fecha de publicacion invalida: {valor!r}")
    return fecha


def _id_derivado(
    tipo: str,
    fecha: str,
    titulo: str,
    fuente: str,
    *,
    discriminante: str = "",
) -> str:
    """Deriva un id estable con prefijo de tipo y hash corto de la fuente.

    ``discriminante`` separa hechos de la misma fecha y tema que tienen
    resumen o anexo distintos, para que no colisionen en el mismo archivo.
    """
    prefijo = "hecho" if tipo == "hecho" else "noticia"
    base = f"{fuente}|{discriminante}" if discriminante else fuente
    return f"{prefijo}-{fecha}-{slugify(titulo, 60)}-{short_hash(base, 6)}"


def render_ficha(row: Mapping[str, Any], config: Config) -> tuple[dict[str, Any], str]:
    """Renderiza una ficha Gold con frontmatter completo y cuerpo minimo.

    El cuerpo solo incluye titulo, medio, fecha, enlace al origen y resumen
    propio. Si la fila ya trae un documento Gold vinculado, anade
    ``documento_id``, ``documento_archivo`` y ``documento_titulo`` al
    frontmatter y un enlace relativo ``../documents/<archivo>.md``. Ignora
    cualquier cuerpo de articulo, imagen o HTML que venga en la fila.

    Devuelve ``(frontmatter, cuerpo_markdown)``. Lanza ``ValueError`` si faltan
    titulo, resumen, medio o una fecha de publicacion valida.
    """
    titulo = _campo_texto(row, "titulo")
    resumen = _campo_texto(row, "resumen")
    if not titulo:
        raise ValueError("La ficha necesita un titulo")
    if not resumen:
        raise ValueError("La ficha necesita un resumen")

    origen = _campo_texto(row, "origen").casefold()
    if not origen:
        origen = "prensa" if _campo_texto(row, "medio") else "oficial"
    tipo = _campo_texto(row, "tipo").casefold() or ("hecho" if origen == "oficial" else "noticia")
    fecha_publicacion = _fecha_iso_obligatoria(row.get("fecha_publicacion") or row.get("fecha"))

    medio = _campo_texto(row, "medio")
    if not medio:
        medio = "Banco de Occidente" if origen == "oficial" else ""
    if not medio:
        raise ValueError("La ficha necesita un medio")

    fuente = _campo_texto(row, "fuente", "url", "anexo", default=config.site.base_url)
    fecha_captura = _normalizar_fecha(row.get("fecha_captura")) or utc_now()[:10]
    idioma = _campo_texto(row, "idioma") or config.site.language
    empresa = _campo_texto(row, "empresa") or config.site.name
    seccion = _campo_texto(row, "seccion") or "presencia"
    temas = _lista_textos(row.get("temas"))
    relevancia = _campo_texto(row, "relevancia").casefold() or "media"
    estado = _campo_texto(row, "estado").casefold()
    if not estado:
        estado = "verificado" if origen == "oficial" else "pendiente"
    metodo = _campo_texto(row, "metodo") or "noticias"

    documento_id = _campo_texto(row, "documento_id")
    documento_archivo = Path(_campo_texto(row, "documento_archivo")).name
    documento_titulo = _campo_texto(row, "documento_titulo")
    anexo = _campo_texto(row, "anexo")
    id_ficha = _campo_texto(row, "id") or _id_derivado(
        tipo,
        fecha_publicacion,
        titulo,
        fuente,
        discriminante=f"{resumen}|{anexo}",
    )

    texto_hash = sha256_text(f"{titulo}\n{resumen}")

    lineas = [
        f"# {titulo}",
        "",
        f"**Medio:** {medio}  ",
        f"**Fecha:** {fecha_publicacion}  ",
        f"**Enlace:** [{titulo}]({fuente})  ",
    ]
    if documento_id and documento_archivo:
        etiqueta = documento_titulo or documento_archivo
        lineas.append(f"**Documento:** [{etiqueta}](../documents/{documento_archivo})  ")
    lineas.extend(["", resumen])
    cuerpo = "\n".join(lineas).strip() + "\n"

    frontmatter: dict[str, Any] = {
        "id": id_ficha,
        "tipo": tipo,
        "origen": origen,
        "seccion": seccion,
        "empresa": empresa,
        "titulo": titulo,
        "fecha_publicacion": fecha_publicacion,
        "fecha_captura": fecha_captura,
        "idioma": idioma,
        "fuente": fuente,
        "medio": medio,
        "resumen": resumen,
        "temas": temas,
        "relevancia": relevancia,
        "estado": estado,
        "tokens": estimate_tokens(cuerpo),
        "hash": texto_hash[:8],
        "palabras": count_words(cuerpo),
        "metodo": metodo,
    }
    for clave in ("evento", "categoria", "anexo", "autor"):
        valor = _campo_texto(row, clave)
        if valor:
            frontmatter[clave] = valor
    if documento_id and documento_archivo:
        frontmatter["documento_id"] = documento_id
        frontmatter["documento_archivo"] = documento_archivo
        frontmatter["documento_titulo"] = documento_titulo

    return frontmatter, cuerpo


def merge_corpus(config: Config, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Fusiona fichas nuevas con ``corpus.jsonl`` sin duplicar registros.

    Conserva las filas del sitio, elimina las fichas antiguas ``noticia-*`` y
    ``hecho-*`` y anade las nuevas. Una segunda ejecucion con las mismas filas
    deja exactamente el mismo numero de registros. Escribe el resultado en
    ``data/gold/corpus.jsonl`` y lo devuelve.
    """
    existentes = list(read_jsonl(config.paths.corpus_file))
    conservadas = [fila for fila in existentes if not _es_id_ficha(fila.get("id"))]
    fusionadas = list(conservadas)
    ids_vistos = {str(fila.get("id")) for fila in conservadas}
    claves_vistas = {
        (
            _campo_texto(fila, "fuente"),
            _campo_texto(fila, "fecha_publicacion", "fecha"),
            _campo_texto(fila, "titulo"),
            _campo_texto(fila, "resumen"),
            _campo_texto(fila, "anexo"),
        )
        for fila in conservadas
    }

    for fila in rows:
        if not isinstance(fila, Mapping):
            continue
        nueva = dict(fila)
        id_ficha = _campo_texto(nueva, "id")
        if not id_ficha or not _es_id_ficha(id_ficha) or id_ficha in ids_vistos:
            continue
        clave = (
            _campo_texto(nueva, "fuente"),
            _campo_texto(nueva, "fecha_publicacion", "fecha"),
            _campo_texto(nueva, "titulo"),
            _campo_texto(nueva, "resumen"),
            _campo_texto(nueva, "anexo"),
        )
        if clave in claves_vistas:
            continue
        fusionadas.append(nueva)
        ids_vistos.add(id_ficha)
        claves_vistas.add(clave)

    write_jsonl(config.paths.corpus_file, fusionadas)
    log.info(
        "Corpus: %d filas del sitio y %d fichas de noticias",
        len(conservadas),
        len(fusionadas) - len(conservadas),
    )
    return fusionadas


def _celda(valor: Any) -> str:
    """Prepara un valor para una celda Markdown de una sola linea."""
    texto = _normalizar_espacios(str(valor or ""))
    return texto.replace("|", "/") or "-"


def _tabla_conteos(titulo: str, conteos: Counter[str]) -> list[str]:
    """Genera una tabla Markdown de conteos con una fila por valor."""
    lineas = [f"### {titulo}", "", "| Valor | Fichas |", "|---|---:|"]
    if conteos:
        for valor, cantidad in conteos.most_common():
            lineas.append(f"| {_celda(valor)} | {cantidad} |")
    else:
        lineas.append("| - | 0 |")
    lineas.append("")
    return lineas


def write_noticias_index(config: Config, rows: list[dict[str, Any]]) -> str:
    """Escribe ``data/gold/_NOTICIAS.md`` con la ventana, conteos y fichas.

    Solo incluye filas ``noticia-*`` y ``hecho-*``. La tabla refleja la fecha,
    el medio, el enlace y el documento vinculado de cada ficha. Si no hay
    fichas publicadas, deja los conteos en cero y una nota explicita.
    """
    fichas = [dict(fila) for fila in rows if _es_id_ficha(fila.get("id"))]
    fichas.sort(
        key=lambda fila: (
            _campo_texto(fila, "fecha_publicacion", "fecha"),
            _campo_texto(fila, "id"),
        ),
        reverse=True,
    )

    fechas = sorted(
        fecha for fila in fichas if (fecha := _campo_texto(fila, "fecha_publicacion", "fecha"))
    )
    desde = _campo_texto({"valor": config.news.desde}, "valor") or (fechas[0] if fechas else "")
    hasta = _campo_texto({"valor": config.news.hasta}, "valor") or (fechas[-1] if fechas else "")

    por_tipo: Counter[str] = Counter(_campo_texto(fila, "tipo") or "sin tipo" for fila in fichas)
    por_origen: Counter[str] = Counter(
        _campo_texto(fila, "origen") or "sin origen" for fila in fichas
    )
    por_anio: Counter[str] = Counter(
        _campo_texto(fila, "fecha_publicacion", "fecha")[:4] or "sin fecha" for fila in fichas
    )
    por_medio: Counter[str] = Counter(_campo_texto(fila, "medio") or "sin medio" for fila in fichas)

    lineas = [
        "# Noticias y hechos relevantes",
        "",
        f"**Ventana:** {desde or 'sin fecha'} a {hasta or 'sin fecha'}  ",
        f"**Fichas publicadas:** {len(fichas)}  ",
        f"**Hechos oficiales:** {por_tipo.get('hecho', 0)}  ",
        f"**Fichas de prensa:** {por_tipo.get('noticia', 0)}  ",
        "",
        "## Conteos",
        "",
    ]
    lineas.extend(_tabla_conteos("Por tipo", por_tipo))
    lineas.extend(_tabla_conteos("Por origen", por_origen))
    lineas.extend(_tabla_conteos("Por anio", por_anio))
    lineas.extend(_tabla_conteos("Por medio", por_medio))

    lineas.extend(["## Fichas", ""])
    if fichas:
        lineas.append("| Fecha | Tipo | Titulo | Medio | Enlace | Evento | Documento |")
        lineas.append("|---|---|---|---|---|---|---|")
        for fila in fichas:
            fecha = _campo_texto(fila, "fecha_publicacion", "fecha")
            tipo = _campo_texto(fila, "tipo")
            titulo = _campo_texto(fila, "titulo")
            medio = _campo_texto(fila, "medio")
            enlace = _campo_texto(fila, "fuente", "url", "anexo")
            evento = _campo_texto(fila, "evento")
            archivo = Path(_campo_texto(fila, "documento_archivo")).name
            documento = f"[{archivo}](documents/{archivo})" if archivo else "-"
            enlace_celda = f"[enlace]({enlace})" if enlace else "-"
            lineas.append(
                "| "
                + " | ".join(
                    [
                        _celda(fecha),
                        _celda(tipo),
                        _celda(titulo),
                        _celda(medio),
                        enlace_celda,
                        _celda(evento),
                        documento,
                    ]
                )
                + " |"
            )
    else:
        lineas.append("_No hubo publicaciones en la ventana._")
    lineas.append("")

    contenido = "\n".join(lineas)
    config.paths.news_index.parent.mkdir(parents=True, exist_ok=True)
    config.paths.news_index.write_text(contenido, encoding="utf-8", newline="\n")
    log.info("Indice de noticias escrito en %s", config.paths.news_index)
    return contenido


def _html_oficial_desde_bronze(config: Config) -> str | None:
    """Busca en Bronze el HTML de la pagina oficial de inversionistas."""
    from .fetch import load_capture

    objetivo = _url_canonica(OFFICIAL_PAGE_URL)
    for url, row in load_capture(config).items():
        if _url_canonica(url) != objetivo or row.get("status") != 200:
            continue
        archivo = str(row.get("archivo") or "").strip()
        if not archivo:
            continue
        ruta = config.paths.root / archivo
        if ruta.exists():
            return ruta.read_text(encoding="utf-8", errors="replace")
    return None


def _descargar_html_oficial(config: Config) -> str:
    """Hace una unica peticion de la pagina oficial y la guarda en Bronze.

    Lanza ``BlockedError`` ante un ``403`` o un bloqueo persistente. No altera
    el User-Agent, los proxies ni la velocidad configurada.
    """
    from .fetch import save_bronze

    with HttpClient(config) as client:
        response = client.get(OFFICIAL_PAGE_URL)

    if response.status == 403:
        raise BlockedError(
            f"{OFFICIAL_PAGE_URL} respondio 403. El sitio bloqueo la peticion: "
            "la ingesta se detiene sin evadir el bloqueo. Puedes intentarlo "
            "mas tarde."
        )
    if not response.ok:
        raise BlockedError(
            f"No se pudo leer {OFFICIAL_PAGE_URL}: {response.error or response.status}. "
            "La ingesta se detiene sin modificar la identificacion ni el ritmo."
        )

    config.paths.capture_file.parent.mkdir(parents=True, exist_ok=True)
    record = save_bronze(config, OFFICIAL_PAGE_URL, response.text)
    append_jsonl(config.paths.capture_file, record)
    log.info("Pagina oficial capturada en Bronze: %s", record["archivo"])
    return response.text


def _html_oficial(config: Config, *, sin_red: bool, force: bool) -> str | None:
    """Devuelve el HTML oficial desde Bronze o con una peticion puntual.

    En ``sin_red`` nunca se toca la red: si falta Bronze devuelve ``None`` y
    deja un aviso. ``force`` obliga a refrescar Bronze salvo en ``sin_red``.
    """
    if not force:
        html = _html_oficial_desde_bronze(config)
        if html is not None:
            return html
    if sin_red:
        log.warning(
            "No hay Bronze de %s y se ejecuto --sin-red: se omiten los hechos oficiales",
            OFFICIAL_PAGE_URL,
        )
        return None
    return _descargar_html_oficial(config)


def _fila_oficial(
    hecho: Mapping[str, Any],
    indice: Mapping[str, dict[str, Any]],
) -> dict[str, Any]:
    """Convierte un hecho oficial parseado en una fila publicable de Gold.

    Vincula el anexo con ``documents.jsonl`` en modo solo lectura; si no hay
    coincidencia conserva la URL del anexo y no descarga nada.
    """
    fecha = hecho.get("fecha")
    if not isinstance(fecha, date):
        raise ValueError(f"El hecho oficial no trae una fecha valida: {fecha!r}")

    fecha_iso = fecha.isoformat()
    titulo = _normalizar_espacios(str(hecho.get("titulo") or "Hecho relevante"))
    resumen = _normalizar_espacios(str(hecho.get("resumen") or ""))
    tema = _normalizar_espacios(str(hecho.get("tema") or ""))
    relevancia = _normalizar_espacios(str(hecho.get("relevancia") or "alta")).casefold()

    fila: dict[str, Any] = {
        "tipo": "hecho",
        "origen": "oficial",
        "seccion": "presencia",
        "titulo": titulo,
        "fecha_publicacion": fecha_iso,
        "fuente": OFFICIAL_PAGE_URL,
        "medio": "Banco de Occidente",
        "resumen": resumen,
        "temas": [slugify(tema, 40)] if tema else [],
        "relevancia": relevancia,
        "estado": "verificado",
        "metodo": "news-parser",
        "evento": f"{fecha_iso}-{slugify(titulo, 40)}",
    }
    if tema:
        fila["categoria"] = tema

    anexo = hecho.get("anexo")
    if isinstance(anexo, str) and anexo.strip():
        fila["anexo"] = anexo.strip()
        vinculado = vincular_documento(anexo, indice)
        if vinculado is not None:
            fila.update(vinculado)
    return fila


def _fila_prensa(ficha: Mapping[str, Any]) -> dict[str, Any]:
    """Convierte una ficha verificada de prensa en una fila publicable de Gold."""
    fila: dict[str, Any] = {
        "id": str(ficha.get("id") or "").strip(),
        "tipo": "noticia",
        "origen": "prensa",
        "seccion": "presencia",
        "titulo": _normalizar_espacios(str(ficha.get("titulo") or "")),
        "fecha_publicacion": _fecha_iso_obligatoria(ficha.get("fecha")),
        "fuente": _normalizar_espacios(str(ficha.get("url") or "")),
        "medio": _normalizar_espacios(str(ficha.get("medio") or "")),
        "resumen": _normalizar_espacios(str(ficha.get("resumen") or "")),
        "temas": _lista_textos(ficha.get("temas")),
        "relevancia": _normalizar_espacios(str(ficha.get("relevancia") or "media")).casefold(),
        "estado": "verificado",
        "metodo": "curaduria",
    }
    evento = _normalizar_espacios(str(ficha.get("evento") or ""))
    if evento:
        fila["evento"] = evento
    return fila


def _escribir_fichas(config: Config, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Renderiza y escribe las fichas en ``data/gold/pages``.

    Retira las fichas ``noticia-*`` y ``hecho-*`` que ya no se generan para que
    el indice y el healthcheck no vean publicaciones obsoletas.
    """
    from .gold import render_document

    config.paths.gold_markdown.mkdir(parents=True, exist_ok=True)
    generadas: list[dict[str, Any]] = []
    ids: set[str] = set()

    for row in rows:
        frontmatter, cuerpo = render_ficha(row, config)
        identificador = str(frontmatter["id"])
        ids.add(identificador)
        ruta = config.paths.gold_markdown / f"{identificador}.md"
        ruta.write_text(render_document(frontmatter, cuerpo), encoding="utf-8", newline="\n")
        fila = dict(frontmatter)
        fila["archivo"] = ruta.relative_to(config.paths.root).as_posix()
        generadas.append(fila)

    for ruta in config.paths.gold_markdown.glob("*.md"):
        if ruta.stem.startswith(("noticia-", "hecho-")) and ruta.stem not in ids:
            ruta.unlink()
            log.info("Se retira una ficha de noticias obsoleta: %s", ruta.name)

    return generadas


def build_noticias(
    config: Config,
    *,
    desde: date,
    hasta: date,
    sin_red: bool = False,
    force: bool = False,
) -> list[dict[str, Any]]:
    """Construye las fichas Gold de noticias y hechos sin tocar PDFs.

    Lee el HTML oficial desde Bronze, hace una unica peticion si falta (salvo
    en ``sin_red``), consulta ``documents.jsonl`` en modo solo lectura, publica
    las fichas verificadas de ``prensa.yaml`` y escribe las paginas Gold,
    ``corpus.jsonl`` y ``_NOTICIAS.md``. Ante ``403`` o bloqueo persistente
    lanza ``BlockedError`` antes de escribir cualquier ficha oficial.
    """
    if hasta < desde:
        raise ValueError("La fecha 'hasta' no puede ser anterior a 'desde'")

    html = _html_oficial(config, sin_red=sin_red, force=force)
    indice = (
        cargar_indice_documentos(config.paths.documents_index)
        if config.paths.documents_index.exists()
        else {}
    )
    hechos = (
        parse_hechos_relevantes(html, desde, hasta, max_oficiales=config.news.max_oficiales)
        if html is not None
        else []
    )

    filas: list[dict[str, Any]] = [_fila_oficial(hecho, indice) for hecho in hechos]
    prensa = filtrar_verificadas(
        deduplicar(
            load_prensa(config.paths.news_prensa),
            max_por_evento=config.news.max_por_evento,
        )
    )
    filas.extend(_fila_prensa(ficha) for ficha in prensa)

    generadas = _escribir_fichas(config, filas)
    corpus = merge_corpus(config, generadas)
    write_noticias_index(config, corpus)
    log.info(
        "Noticias: %d hechos oficiales, %d fichas de prensa, %d filas en corpus",
        len(hechos),
        len(prensa),
        len(corpus),
    )
    return generadas
