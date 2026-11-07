"""Búsqueda y comparación deterministas sobre las filas del Tablero.

No hay modelo ni red: solo normalización de texto y comparación de valores.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

from ..texto import normalizar
from .tipos import Fila

#: Sufijo de franquicia que se ignora al emparejar dos filas.
_FRANQUICIA = re.compile(r"\s*\((visa|mastercard)\)\s*$", re.IGNORECASE)
#: Palabra de la consulta o de una fila del Tablero.
_PALABRA = re.compile(r"\w+")
#: Equivalencias del dominio que no aparecen literalmente en las filas.
_SINONIMOS: dict[str, str] = {
    "europa": "schengen",
    "europea": "schengen",
    "europeo": "schengen",
    "extranjera": "exterior",
    "extranjero": "exterior",
}
#: Pares que no pueden describir la misma fila: si la consulta pide uno, la
#: fila que solo menciona el otro no es una respuesta válida.
_CONTRARIOS: tuple[tuple[str, str], ...] = (
    ("credito", "debito"),
    ("nacional", "exterior"),
    ("visa", "mastercard"),
)
#: Nombres de producto que deben aparecer en la fila cuando la consulta los pide.
_DISTINTIVOS = frozenset({"black", "gold", "platinum", "clasica", "joven", "business", "viajera"})
#: Palabras que no distinguen una tarifa: artículos, preposiciones y muletillas.
_VACIAS = frozenset(
    [
        "a",
        "al",
        "ante",
        "con",
        "contra",
        "de",
        "del",
        "desde",
        "durante",
        "e",
        "el",
        "en",
        "entre",
        "era",
        "es",
        "esa",
        "ese",
        "eso",
        "esta",
        "este",
        "esto",
        "fue",
        "fueron",
        "ha",
        "han",
        "has",
        "hasta",
        "hay",
        "he",
        "hacia",
        "la",
        "las",
        "le",
        "les",
        "lo",
        "los",
        "mas",
        "me",
        "mi",
        "mis",
        "muy",
        "ni",
        "no",
        "nos",
        "o",
        "os",
        "otra",
        "otro",
        "para",
        "pero",
        "por",
        "porque",
        "pues",
        "que",
        "se",
        "segun",
        "ser",
        "si",
        "sin",
        "sobre",
        "solo",
        "son",
        "su",
        "sus",
        "tan",
        "te",
        "todo",
        "toda",
        "todos",
        "todas",
        "tras",
        "tu",
        "tus",
        "u",
        "un",
        "una",
        "unas",
        "unos",
        "y",
        "ya",
    ]
)
#: Verbos y palabras de pregunta que acompañan la consulta sin ser el tema.
_PREGUNTA = frozenset(
    [
        "aplica",
        "aplican",
        "como",
        "cuando",
        "cuanta",
        "cuantas",
        "cuanto",
        "cuantos",
        "cual",
        "cuales",
        "cubre",
        "cubren",
        "cubrir",
        "cuesta",
        "cuestan",
        "da",
        "dan",
        "debe",
        "deben",
        "debo",
        "dime",
        "donde",
        "esperar",
        "favor",
        "hacer",
        "hago",
        "hola",
        "necesito",
        "ofrece",
        "ofrecen",
        "podria",
        "puedo",
        "quedo",
        "quien",
        "quienes",
        "quisiera",
        "sabes",
        "significa",
        "sirve",
        "sirven",
        "tiene",
        "tienen",
        "tengo",
        "usarla",
        "vale",
        "valen",
    ]
)


#: Sufijos que se recortan para comparar plurales y flexiones.
_SUFIJOS = (
    "amientos",
    "imiento",
    "aciones",
    "acion",
    "mente",
    "ados",
    "adas",
    "idos",
    "idas",
    "ado",
    "ada",
    "ido",
    "ida",
    "es",
    "os",
    "as",
    "o",
    "a",
    "e",
    "s",
)


@dataclass(frozen=True, slots=True)
class Comparacion:
    """Diferencias entre dos grupos de filas del Tablero."""

    solo_izquierda: tuple[Fila, ...]
    solo_derecha: tuple[Fila, ...]
    distintas: tuple[tuple[Fila, Fila], ...]

    @property
    def vacia(self) -> bool:
        """Indica si los dos grupos son equivalentes."""
        return not (self.solo_izquierda or self.solo_derecha or self.distintas)


def buscar_filas(filas: Sequence[Fila], consulta: str, categoria: str | None = None) -> list[Fila]:
    """Filtra por concepto, categoría, valor y moneda.

    La consulta se parte en palabras significativas: se descartan artículos,
    preposiciones y muletillas («cuánto», «cuesta», «la», «de»). Una fila
    coincide cuando contiene alguna de esas palabras; se conservan las que
    alcanzan el mayor número de coincidencias, para no exigirlas todas ni
    arrastrar filas que comparten una sola palabra. Si hay empate se devuelven
    todas las empatadas; ``filas_para_plantilla`` aplica el desempate por
    especificidad cuando la respuesta va al usuario.

    Args:
        filas: filas del Tablero.
        consulta: pregunta o términos a buscar.
        categoria: texto que debe aparecer en la categoría, si se indica.

    Returns:
        Las filas con más coincidencias, en el orden original.
    """
    terminos = _terminos(consulta)
    objetivo = normalizar(categoria) if categoria else ""
    elegibles = [fila for fila in filas if not objetivo or objetivo in normalizar(fila.categoria)]
    if not terminos:
        return [] if consulta.strip() else elegibles
    elegibles = _exigir_distintivos(elegibles, consulta)

    puntuadas: list[tuple[int, Fila]] = []
    raices = list(dict.fromkeys(_raiz(_SINONIMOS.get(termino, termino)) for termino in terminos))
    for fila in elegibles:
        palabras = {
            _raiz(palabra)
            for palabra in _PALABRA.findall(
                normalizar(f"{fila.concepto} {fila.categoria} {fila.valor} {fila.moneda}")
            )
        }
        if _contradice(raices, palabras):
            continue
        puntaje = sum(1 for raiz in raices if raiz in palabras)
        if puntaje:
            puntuadas.append((puntaje, fila))

    if not puntuadas:
        return []
    maximo = max(puntaje for puntaje, _ in puntuadas)
    return [fila for puntaje, fila in puntuadas if puntaje == maximo]


def filas_para_plantilla(
    filas: Sequence[Fila], consulta: str, categoria: str | None = None
) -> list[Fila]:
    """Elige las filas que mejor responden una pregunta del Tablero.

    Parte de ``buscar_filas`` y desempata por especificidad: primero conserva
    las filas con la frase más larga de la consulta en el mismo orden (así
    «países Schengen» no empata con «países NO Schengen») y después prefiere el
    concepto más corto (así «Cheque de Gerencia» gana sobre «Anulación ... de
    Cheques de Gerencia»). No llama al modelo ni a la red.

    Args:
        filas: filas del Tablero.
        consulta: pregunta o términos del cliente.
        categoria: texto que debe aparecer en la categoría, si se indica.

    Returns:
        Las filas más específicas entre las que empatan en coincidencias.
    """
    candidatas = buscar_filas(filas, consulta, categoria)
    if len(candidatas) <= 1:
        return candidatas

    raices_consulta = [_raiz(_SINONIMOS.get(termino, termino)) for termino in _terminos(consulta)]
    rachas = [
        _racha(
            [_raiz(palabra) for palabra in _PALABRA.findall(normalizar(fila.concepto))],
            raices_consulta,
        )
        for fila in candidatas
    ]
    maxima = max(rachas)
    candidatas = [fila for fila, racha in zip(candidatas, rachas, strict=True) if racha == maxima]

    longitudes = [len(normalizar(fila.concepto).split()) for fila in candidatas]
    minima = min(longitudes)
    return [
        fila for fila, longitud in zip(candidatas, longitudes, strict=True) if longitud == minima
    ]


def concepto_sin_franquicia(concepto: str) -> str:
    """Quita el sufijo «(Visa)» o «(Mastercard)» y normaliza los espacios."""
    return " ".join(_FRANQUICIA.sub("", normalizar(concepto)).split())


def _terminos(consulta: str) -> list[str]:
    """Devuelve las palabras significativas de la consulta, sin repetir."""
    palabras = _PALABRA.findall(normalizar(consulta))
    return list(
        dict.fromkeys(p for p in palabras if len(p) > 1 and p not in _VACIAS and p not in _PREGUNTA)
    )


def _raiz(palabra: str) -> str:
    """Recorta plurales y flexiones frecuentes para comparar dos palabras.

    No es un lematizador completo: solo evita que «cheques»/«cheque»,
    «tarjetas»/«tarjeta» o «desempleado»/«desempleo» se traten como términos
    distintos. Deja intactas las palabras cortas y las cifras.
    """
    for sufijo in _SUFIJOS:
        if palabra.endswith(sufijo) and len(palabra) - len(sufijo) >= 4:
            return palabra[: -len(sufijo)]
    return palabra


#: Raíces de los nombres de producto que se exigen en la fila.
_DISTINTIVOS_RAIZ = frozenset(_raiz(palabra) for palabra in _DISTINTIVOS)


def _exigir_distintivos(filas: Sequence[Fila], consulta: str) -> list[Fila]:
    """Si la consulta nombra Black, Gold o Platinum, exige ese nombre en la fila.

    Evita responder «¿cuánto cuesta la Black?» con la fila genérica de pago de
    tarjeta, que no menciona Black. Si ninguna fila tiene el nombre, devuelve
    una lista vacía para que la consulta pase a la Bóveda.
    """
    raices_consulta = {_raiz(termino) for termino in _terminos(consulta)}
    exigidos = raices_consulta & _DISTINTIVOS_RAIZ
    if not exigidos:
        return list(filas)
    resultado: list[Fila] = []
    for fila in filas:
        palabras = {
            _raiz(palabra)
            for palabra in _PALABRA.findall(normalizar(f"{fila.concepto} {fila.categoria}"))
        }
        if exigidos <= palabras:
            resultado.append(fila)
    return resultado


def _contradice(raices_consulta: Sequence[str], raices_fila: set[str]) -> bool:
    """Indica si la fila solo menciona el opuesto de lo que pide la consulta.

    Evita responder «cuota de manejo de la tarjeta de crédito» con la fila de
    la tarjeta débito, o «viajes nacionales» con una asistencia al exterior.
    """
    for uno, otro in _CONTRARIOS:
        raiz_uno, raiz_otro = _raiz(uno), _raiz(otro)
        if raiz_uno in raices_consulta and raiz_otro in raices_fila and raiz_uno not in raices_fila:
            return True
        if (
            raiz_otro in raices_consulta
            and raiz_uno in raices_fila
            and raiz_otro not in raices_fila
        ):
            return True
    return False


def _racha(raices_fila: Sequence[str], raices_consulta: Sequence[str]) -> int:
    """Longitud de la mayor subsecuencia contigua de la consulta en la fila."""
    mejor = 0
    for inicio in range(len(raices_consulta)):
        for fin in range(inicio + 1, len(raices_consulta) + 1):
            trozo = list(raices_consulta[inicio:fin])
            if _contiene_contiguo(raices_fila, trozo):
                mejor = max(mejor, len(trozo))
    return mejor


def _contiene_contiguo(raices_fila: Sequence[str], trozo: Sequence[str]) -> bool:
    """Indica si `trozo` aparece como bloque contiguo dentro de la fila."""
    if not trozo:
        return False
    for inicio in range(len(raices_fila) - len(trozo) + 1):
        if list(raices_fila[inicio : inicio + len(trozo)]) == list(trozo):
            return True
    return False


def comparar_filas(izquierda: Sequence[Fila], derecha: Sequence[Fila]) -> Comparacion:
    """Compara dos grupos y devuelve filas exclusivas y valores distintos."""
    mapa_izquierda = _por_concepto(izquierda)
    mapa_derecha = _por_concepto(derecha)
    solo_izquierda = tuple(
        fila for clave, fila in mapa_izquierda.items() if clave not in mapa_derecha
    )
    solo_derecha = tuple(
        fila for clave, fila in mapa_derecha.items() if clave not in mapa_izquierda
    )
    distintas: list[tuple[Fila, Fila]] = []
    for clave, fila in mapa_izquierda.items():
        otra = mapa_derecha.get(clave)
        if otra is not None and _valores(fila) != _valores(otra):
            distintas.append((fila, otra))
    return Comparacion(
        solo_izquierda=solo_izquierda,
        solo_derecha=solo_derecha,
        distintas=tuple(distintas),
    )


def _por_concepto(filas: Sequence[Fila]) -> dict[str, Fila]:
    """Indexa por concepto sin franquicia; conserva la primera aparición."""
    mapa: dict[str, Fila] = {}
    for fila in filas:
        clave = _FRANQUICIA.sub("", normalizar(fila.concepto)).strip()
        mapa.setdefault(clave, fila)
    return mapa


def _valores(fila: Fila) -> tuple[str, str, str]:
    """Valores que definen si dos filas son equivalentes."""
    return (fila.valor, fila.moneda, fila.periodicidad)
