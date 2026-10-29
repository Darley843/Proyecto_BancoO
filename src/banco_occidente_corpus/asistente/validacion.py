"""Validacion determinista de preguntas y respuestas del asistente.

El prompt no basta como garantia: aqui se comprueban los topes de palabras, la
fuente dentro del contexto, las cifras inventadas, la fuga del prompt y los
datos personales. Las cifras se comparan sin espacios, puntos, comas ni guiones
para que un mismo numero escrito con distinto formato sea equivalente.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass

from .contexto_prompt import CanalOficial, normalizar_digitos

FRASE_SIN_DATOS = "No encuentro esa información en las fuentes públicas del banco"
LIMITE_QA = 150
LIMITE_RESUMEN = 300

_CORREO = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b", re.IGNORECASE)
_TARJETA = re.compile(r"\b(?:\d[ -]?){13,19}\b")
_MOVIL = re.compile(r"(?:\+?57[\s.-]?)?\b3\d{2}[\s.-]?\d{3}[\s.-]?\d{4}\b")
_FIJO = re.compile(r"\(?60\d\)?[\s.-]?\d{7}\b")
_INTERNACIONAL = re.compile(r"\+\d{10,13}\b")
_CUE_DOC = re.compile(
    r"(c[eé]dula|cedula|\bCC\b|\bC\.C\.|pasaporte|nuip|documento de identidad)",
    re.IGNORECASE,
)
_NUM_DOC = re.compile(r"\b\d{1,3}(?:[.\s]\d{3}){1,3}\b|\b\d{6,10}\b")

_ETIQUETA = re.compile(r"</?(?:contexto|pregunta|reglas_clave)\s*/?>", re.IGNORECASE)
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
_FUENTE_LINEA = re.compile(r"^\s*Fuente:\s*(?P<resto>.+)$", re.IGNORECASE)
_CIFRA = re.compile(r"(?:\$|COP\s*)?(?:\d[\d\s.,\-]*\d|\d)(?:\s?[%％])?")
_URL = re.compile(r"https?://\S+")
_URL_TEXTO = re.compile(r"https?://[^\s)\]>,]+")

_MARCADORES_FUGA = (
    "instrucciones del sistema",
    "prompt del sistema",
    "system prompt",
    "mis instrucciones",
    "ignore previous",
    "ignora las instrucciones",
    "<contexto>",
    "</contexto>",
    "<reglas_clave>",
    "<pregunta>",
)


@dataclass(frozen=True, slots=True)
class DeteccionPII:
    """Categoria de dato personal detectado; nunca guarda el valor."""

    categoria: str


def _luhn(digitos: str) -> bool:
    """Valida el digito de control de una tarjeta (Luhn)."""
    total = 0
    for posicion, caracter in enumerate(reversed(digitos)):
        numero = int(caracter)
        if posicion % 2 == 1:
            numero *= 2
            if numero > 9:
                numero -= 9
        total += numero
    return total % 10 == 0


def detectar_pii(texto: str, *, permitidos: Iterable[str] = ()) -> DeteccionPII | None:
    """Detecta datos personales con criterio conservador.

    ``permitidos`` contiene los telefonos publicos del banco ya normalizados;
    esos numeros no se consideran datos personales.
    """
    permitidos_set = {normalizar_cifra(valor) for valor in permitidos}

    if _CORREO.search(texto):
        return DeteccionPII("correo")

    for match in _TARJETA.finditer(texto):
        digitos = normalizar_cifra(match.group(0))
        if 13 <= len(digitos) <= 19 and _luhn(digitos) and digitos not in permitidos_set:
            return DeteccionPII("número de tarjeta")

    for clave in _CUE_DOC.finditer(texto):
        for numero in _NUM_DOC.finditer(texto):
            if abs(clave.start() - numero.start()) > 60:
                continue
            digitos = normalizar_cifra(numero.group(0))
            if digitos and digitos not in permitidos_set:
                return DeteccionPII("documento de identidad")

    for patron in (_MOVIL, _FIJO, _INTERNACIONAL):
        for match in patron.finditer(texto):
            digitos = normalizar_cifra(match.group(0))
            if digitos and digitos not in permitidos_set:
                return DeteccionPII("teléfono")

    return None


def sanear_pregunta(pregunta: str, *, limite: int = 2000) -> str:
    """Quita etiquetas internas, controles y exceso de espacios de la pregunta."""
    texto = _ETIQUETA.sub(" ", pregunta)
    texto = _CONTROL.sub("", texto)
    texto = re.sub(r"\s+", " ", texto).strip()
    if not texto:
        raise ValueError("La pregunta esta vacia.")
    return texto[:limite].strip()


def normalizar_cifra(token: str) -> str:
    """Deja solo los digitos de una cifra (quita espacios, puntos, comas y guiones)."""
    return re.sub(r"\D", "", normalizar_digitos(token))


def _sin_urls(texto: str) -> str:
    """Quita las URLs para que sus digitos no cuenten como cifras."""
    return _URL.sub(" ", texto)


def cifras_duras(texto: str) -> set[str]:
    """Cifras normalizadas: porcentajes, montos y numeros de tres o mas digitos."""
    cifras: set[str] = set()
    for match in _CIFRA.finditer(_sin_urls(texto)):
        token = match.group(0)
        digitos = normalizar_cifra(token)
        if not digitos:
            continue
        marca = "%" in token or "％" in token or "$" in token or "cop" in token.casefold()
        if marca or len(digitos) >= 3:
            cifras.add(digitos)
    return cifras


def cifras_inventadas(
    respuesta: str,
    contexto: str | None = None,
    *,
    cifras_contexto: set[str] | None = None,
) -> set[str]:
    """Cifras de la respuesta que no aparecen en el contexto."""
    permitidas = cifras_contexto if cifras_contexto is not None else cifras_duras(contexto or "")
    return cifras_duras(respuesta) - permitidas


def url_en_contexto(url: str, urls: Iterable[str]) -> bool:
    """Compara URLs ignorando solo la barra final."""
    limpia = url.strip().rstrip("/")
    return any(limpia == candidata.strip().rstrip("/") for candidata in urls)


def validar_fuente(texto: str, urls: Iterable[str]) -> str | None:
    """Devuelve la URL de la ultima linea ``Fuente:`` si pertenece al contexto."""
    for linea in reversed(texto.splitlines()):
        match = _FUENTE_LINEA.match(linea)
        if not match:
            continue
        url_match = re.search(r"https?://\S+", match.group("resto"))
        if not url_match:
            return None
        url = url_match.group(0).rstrip(").,;]")
        return url if url_en_contexto(url, urls) else None
    return None


def contar_palabras(texto: str) -> int:
    """Cuenta palabras como secuencias separadas por espacio."""
    return len(re.findall(r"\S+", texto))


def limitar_palabras(texto: str, limite: int) -> tuple[str, bool]:
    """Recorta a ``limite`` palabras conservando la ultima linea ``Fuente:``."""
    lineas = texto.rstrip().splitlines()
    fuente = ""
    if lineas and lineas[-1].strip().lower().startswith("fuente:"):
        fuente = lineas[-1].strip()
        cuerpo = "\n".join(lineas[:-1]).strip()
    else:
        cuerpo = texto.strip()

    presupuesto = max(0, limite - (contar_palabras(fuente) if fuente else 0))
    palabras = cuerpo.split()
    if len(palabras) <= presupuesto:
        return texto.strip(), False

    if presupuesto == 0:
        recorte = ""
    elif presupuesto == 1:
        recorte = "…"
    else:
        recorte = " ".join(palabras[: presupuesto - 1]) + " …"

    return f"{recorte}\n{fuente}".strip() if fuente else recorte, True


def separar_fuentes(texto: str) -> tuple[str, str]:
    """Separa el cuerpo del bloque final ``Fuentes:`` del resumen."""
    match = re.search(r"^Fuentes:\s*$", texto, flags=re.MULTILINE)
    if not match:
        return texto.strip(), ""
    return texto[: match.start()].strip(), texto[match.start() :].strip()


def limitar_resumen(texto: str, limite: int = LIMITE_RESUMEN) -> tuple[str, bool]:
    """Recorta el resumen a ``limite`` palabras sin perder el bloque de fuentes."""
    if contar_palabras(texto) <= limite:
        return texto.strip(), False

    cuerpo, fuentes = separar_fuentes(texto)
    if not fuentes:
        return limitar_palabras(texto, limite)

    presupuesto = max(0, limite - contar_palabras(fuentes))
    cuerpo_recortado, _ = limitar_palabras(cuerpo, presupuesto)
    return f"{cuerpo_recortado}\n\n{fuentes}".strip(), True


def extraer_urls_texto(texto: str) -> tuple[str, ...]:
    """URLs de un texto libre, en orden de aparicion y sin repetir."""
    urls: list[str] = []
    for match in _URL_TEXTO.finditer(texto):
        url = match.group(0).rstrip(".,;:")
        if url not in urls:
            urls.append(url)
    return tuple(urls)


def detectar_fuga_prompt(texto: str) -> bool:
    """Detecta respuestas que revelan instrucciones internas o etiquetas del prompt."""
    minusculas = texto.casefold()
    return any(marcador in minusculas for marcador in _MARCADORES_FUGA)


def es_sin_datos(texto: str) -> bool:
    """True si la respuesta *empieza* con la frase fija (rechazo completo).

    Una respuesta parcial que da lo que si esta en el contexto y usa la frase
    fija solo para el dato que falta ("Sobre la tasa: No encuentro esa
    informacion...") no es un rechazo: se valida como cualquier otra respuesta.
    """
    inicio = texto.lstrip(" \t\n*_>#-").casefold()
    return inicio.startswith(FRASE_SIN_DATOS.casefold())


def limpiar_respuesta(texto: str) -> str:
    """Quita espacios, cercas de codigo y lineas en blanco repetidas."""
    limpio = texto.strip()
    limpio = re.sub(r"^```(?:markdown|md)?\s*", "", limpio, flags=re.IGNORECASE)
    limpio = re.sub(r"\s*```$", "", limpio)
    limpio = re.sub(r"\n{3,}", "\n\n", limpio)
    return limpio.strip()


def texto_de_contenido(contenido: object) -> str:
    """Extrae el texto de un contenido de mensaje (cadena o bloques)."""
    if isinstance(contenido, str):
        return contenido
    if isinstance(contenido, list):
        partes: list[str] = []
        for bloque in contenido:
            if isinstance(bloque, str):
                partes.append(bloque)
            elif isinstance(bloque, dict):
                valor = bloque.get("text")
                if isinstance(valor, str):
                    partes.append(valor)
        return "".join(partes)
    return str(contenido)


def respuesta_sin_datos(canal: CanalOficial | None) -> str:
    """Fallback determinista con la frase exacta y el canal oficial del contexto."""
    lineas = [FRASE_SIN_DATOS]
    if canal and canal.url:
        if canal.telefono:
            lineas.append(
                f"Puedes consultar la Línea de Servicio al Cliente {canal.telefono} "
                f"o los canales oficiales en {canal.url}"
            )
        else:
            lineas.append(f"Puedes consultar los canales oficiales en {canal.url}")
        lineas.append(f"Fuente: {canal.url}")
    else:
        lineas.append("Puedes consultar los canales oficiales del banco.")
    return "\n".join(lineas)


def mensaje_pii(categoria: str, canal: CanalOficial | None) -> str:
    """Explica por que no se procesa un mensaje con datos personales."""
    lineas = [
        "Por seguridad no proceso datos personales en este chat (Ley 1581 de 2012).",
        f"Detecté un posible {categoria} en tu mensaje.",
        "Puedo ayudarte con información pública del banco.",
    ]
    if canal and canal.url:
        if canal.telefono:
            lineas.append(
                "Para tu caso específico usa la Línea de Servicio al Cliente "
                f"{canal.telefono} o los canales oficiales:"
            )
        else:
            lineas.append("Para tu caso específico usa los canales oficiales:")
        lineas.append(canal.url)
        lineas.append(f"Fuente: {canal.url}")
    else:
        lineas.append("Para tu caso específico consulta los canales oficiales del banco.")
    return "\n".join(lineas)
