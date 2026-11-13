"""Metricas del Arqueo de la fase 2: funciones puras, sin red ni indice.

Reutiliza ``asistente.metricas.leer_uso`` para no duplicar la lectura de tokens
ni el respaldo sobre ``response_metadata.token_usage``. Las URL se comparan
exactamente, igual que en ``test/test_preguntas_fase2.py``. Incluye hit@k, MRR,
recall@k y nDCG@k con relevancia binaria por URL.
"""

from __future__ import annotations

import math
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from statistics import NormalDist
from typing import Any, NamedTuple

from ..asistente.metricas import leer_uso
from ..texto import normalizar

#: Nivel de significancia usado en el informe del Arqueo.
ALFA: float = 0.05

#: Ventana de recall@k y nDCG@k del Arqueo y de la skill boveda-rag.
K_RECALL: int = 10


@dataclass(frozen=True, slots=True)
class Tarifas:
    """Tarifas en USD por millon de tokens.

    Valores consultados el 2026-10-24 en ``https://api-docs.deepseek.com``.
    ``TARIFAS_DEEPSEEK_FLASH`` es la tarifa valle y
    ``TARIFAS_DEEPSEEK_FLASH_PICO`` la de pico, que aplica de 01:00 a 04:00 y
    de 06:00 a 10:00 UTC, de lunes a viernes.
    """

    entrada: float
    cache: float
    salida: float


#: Tarifa valle del modelo ``deepseek-flash`` (USD por millon de tokens).
TARIFAS_DEEPSEEK_FLASH = Tarifas(entrada=0.15, cache=0.003, salida=0.60)

#: Tarifa pico del modelo ``deepseek-flash`` (USD por millon de tokens).
TARIFAS_DEEPSEEK_FLASH_PICO = Tarifas(entrada=0.30, cache=0.006, salida=1.20)


@dataclass(frozen=True, slots=True)
class ResumenUso:
    """Totales y promedios de uso, costo y tiempo de una corrida.

    ``registros`` cuenta los registros incluidos y ``errores`` los excluidos
    por traer un ``error`` no vacio. Los promedios se calculan sobre
    ``registros``.
    """

    registros: int = 0
    errores: int = 0
    entrada_total: int = 0
    entrada_promedio: float = 0.0
    salida_total: int = 0
    salida_promedio: float = 0.0
    cache_total: int = 0
    cache_promedio: float = 0.0
    costo_usd_total: float = 0.0
    costo_usd_promedio: float = 0.0
    tiempo_promedio: float = 0.0
    tiempo_maximo: float = 0.0


class ResultadoMcNemar(NamedTuple):
    """Conteos discordantes, p exacta de dos colas y pares excluidos."""

    b: int
    c: int
    n: int
    p: float
    excluidos: int


def _pares(
    recuperadas: Sequence[Sequence[str]],
    esperadas: Sequence[Sequence[str]],
) -> Iterator[tuple[Sequence[str], Sequence[str]]]:
    """Empareja las listas por pregunta y exige el mismo largo."""
    if len(recuperadas) != len(esperadas):
        raise ValueError(
            f"Las listas deben tener el mismo largo: {len(recuperadas)} != {len(esperadas)}"
        )
    return zip(recuperadas, esperadas, strict=True)


def hit_at_k(
    recuperadas: Sequence[Sequence[str]],
    esperadas: Sequence[Sequence[str]],
    k: int = 5,
) -> float | None:
    """Proporcion de preguntas con una URL esperada entre las k primeras.

    Solo cuentan las preguntas con ``esperadas`` no vacia. Las URL se comparan
    exactamente. Devuelve ``None`` si no hay preguntas evaluables y lanza
    ``ValueError`` si ``k`` no es positivo.
    """
    if k <= 0:
        raise ValueError("k debe ser mayor que cero")
    evaluables = 0
    aciertos = 0
    for recuperadas_q, esperadas_q in _pares(recuperadas, esperadas):
        if not esperadas_q:
            continue
        evaluables += 1
        esperadas_set = set(esperadas_q)
        if any(url in esperadas_set for url in recuperadas_q[:k]):
            aciertos += 1
    return aciertos / evaluables if evaluables else None


def mrr(
    recuperadas: Sequence[Sequence[str]],
    esperadas: Sequence[Sequence[str]],
    k: int = 5,
) -> float | None:
    """Rango reciproco medio de la primera URL esperada dentro de las k primeras.

    Solo cuentan las preguntas con ``esperadas`` no vacia. Las URL se comparan
    exactamente. Devuelve ``None`` si no hay preguntas evaluables y lanza
    ``ValueError`` si ``k`` no es positivo.
    """
    if k <= 0:
        raise ValueError("k debe ser mayor que cero")
    evaluables = 0
    suma = 0.0
    for recuperadas_q, esperadas_q in _pares(recuperadas, esperadas):
        if not esperadas_q:
            continue
        evaluables += 1
        esperadas_set = set(esperadas_q)
        for posicion, url in enumerate(recuperadas_q[:k], start=1):
            if url in esperadas_set:
                suma += 1.0 / posicion
                break
    return suma / evaluables if evaluables else None


def _relevancias(
    recuperadas_q: Sequence[str],
    esperadas_q: Sequence[str],
    k: int,
) -> list[int]:
    """Devuelve la ganancia binaria de cada posicion del top k.

    Una URL esperada aporta 1 en su primera aparicion; si se repite mas adelante
    dentro del top k, aporta 0. Las URL esperadas se comparan exactamente y se
    deduplican, igual que en ``hit_at_k`` y ``mrr``.
    """
    esperadas_set = set(esperadas_q)
    vistas: set[str] = set()
    relevancias: list[int] = []
    for url in recuperadas_q[:k]:
        relevante = url in esperadas_set and url not in vistas
        relevancias.append(1 if relevante else 0)
        vistas.add(url)
    return relevancias


def recall_at_k(
    recuperadas: Sequence[Sequence[str]],
    esperadas: Sequence[Sequence[str]],
    k: int = K_RECALL,
) -> float | None:
    """Proporcion de fuentes esperadas encontradas en el top k.

    La relevancia es binaria y por URL: cada fuente esperada aporta 1 si
    aparece al menos una vez entre las k primeras. Las URL se comparan
    exactamente y las esperadas se deduplican. Solo cuentan las preguntas con
    ``esperadas`` no vacia. Devuelve ``None`` si no hay preguntas evaluables y
    lanza ``ValueError`` si ``k`` no es positivo.

    Formula, con ``E_q`` el conjunto de fuentes esperadas y ``r_i`` la ganancia
    de la posicion ``i``::

        recall@k(q) = sum(r_i, i=1..k) / |E_q|
    """
    if k <= 0:
        raise ValueError("k debe ser mayor que cero")
    evaluables = 0
    suma = 0.0
    for recuperadas_q, esperadas_q in _pares(recuperadas, esperadas):
        if not esperadas_q:
            continue
        evaluables += 1
        encontradas = sum(_relevancias(recuperadas_q, esperadas_q, k))
        suma += encontradas / len(set(esperadas_q))
    return suma / evaluables if evaluables else None


def ndcg_at_k(
    recuperadas: Sequence[Sequence[str]],
    esperadas: Sequence[Sequence[str]],
    k: int = K_RECALL,
) -> float | None:
    """nDCG@k con ganancia binaria por URL y descuento ``log2(posicion + 1)``.

    Cada URL esperada aporta ganancia 1 en su primera aparicion dentro del top
    k; una repeticion posterior aporta 0. Las URL se comparan exactamente y las
    esperadas se deduplican. El ideal usa una ganancia 1 por cada fuente
    esperada distinta, hasta ``k``. Solo cuentan las preguntas con ``esperadas``
    no vacia. Devuelve ``None`` si no hay preguntas evaluables y lanza
    ``ValueError`` si ``k`` no es positivo.

    Formulas, con ``r_i`` la ganancia de la posicion ``i`` y ``n_q`` el numero
    de fuentes esperadas distintas::

        DCG@k(q)  = sum(r_i / log2(i + 1), i=1..k)
        IDCG@k(q) = sum(1 / log2(j + 1), j=1..min(n_q, k))
        nDCG@k(q) = DCG@k(q) / IDCG@k(q)
    """
    if k <= 0:
        raise ValueError("k debe ser mayor que cero")
    evaluables = 0
    suma = 0.0
    for recuperadas_q, esperadas_q in _pares(recuperadas, esperadas):
        if not esperadas_q:
            continue
        evaluables += 1
        relevancias = _relevancias(recuperadas_q, esperadas_q, k)
        dcg = sum(
            ganancia / math.log2(posicion + 1)
            for posicion, ganancia in enumerate(relevancias, start=1)
        )
        ideales = min(len(set(esperadas_q)), k)
        idcg = sum(1.0 / math.log2(posicion + 1) for posicion in range(1, ideales + 1))
        suma += dcg / idcg
    return suma / evaluables if evaluables else None


def acierta_terminos(respuesta: str, terminos: Sequence[Sequence[str]]) -> bool | None:
    """True si cada grupo tiene al menos una alternativa en la respuesta.

    La comparacion usa ``texto.normalizar``: ``casefold``, NFKD y sin marcas
    combinantes, asi que ignora mayusculas y tildes. ``terminos`` vacio
    devuelve ``None``.
    """
    if not terminos:
        return None
    texto = normalizar(respuesta)
    return all(any(normalizar(termino) in texto for termino in grupo) for grupo in terminos)


def exactitud(aciertos: Sequence[bool | None]) -> float | None:
    """Proporcion de ``True``, ignorando los ``None``.

    Devuelve ``None`` si no hay aciertos evaluables.
    """
    evaluables = [acierto for acierto in aciertos if acierto is not None]
    if not evaluables:
        return None
    return sum(1 for acierto in evaluables if acierto is True) / len(evaluables)


def citas_correctas(
    citadas: Sequence[Sequence[str]],
    esperadas: Sequence[Sequence[str]],
) -> float | None:
    """Proporcion de preguntas con al menos una cita esperada.

    Solo cuentan las preguntas con ``esperadas`` no vacia. Las URL se comparan
    exactamente. Devuelve ``None`` si no hay preguntas evaluables.
    """
    evaluables = 0
    aciertos = 0
    for citadas_q, esperadas_q in _pares(citadas, esperadas):
        if not esperadas_q:
            continue
        evaluables += 1
        esperadas_set = set(esperadas_q)
        if any(url in esperadas_set for url in citadas_q):
            aciertos += 1
    return aciertos / evaluables if evaluables else None


def _flotante(valor: object) -> float | None:
    """Devuelve el valor como float si es un numero; ignora booleanos."""
    if isinstance(valor, (int, float)) and not isinstance(valor, bool):
        return float(valor)
    return None


def _tiene_error(registro: Mapping[str, Any]) -> bool:
    """Indica si el registro trae un error no vacio."""
    error = registro.get("error")
    if error is None:
        return False
    if isinstance(error, str):
        return bool(error.strip())
    return bool(error)


def _costo(entrada: int, salida: int, cache: int, tarifas: Tarifas) -> float:
    """Calcula el costo en USD de un registro con tarifas por millon."""
    sin_cache = max(entrada - cache, 0)
    return (
        sin_cache * tarifas.entrada + cache * tarifas.cache + salida * tarifas.salida
    ) / 1_000_000


def resumen_uso(
    registros: Sequence[Mapping[str, Any]],
    *,
    tarifas: Tarifas = TARIFAS_DEEPSEEK_FLASH,
) -> ResumenUso:
    """Agrega tokens, costo y tiempo; excluye registros con error no vacio.

    Cada registro es un mapeo con ``metricas`` (formato de ``leer_uso``) y
    ``segundos``. Los campos ausentes cuentan como cero. El costo se calcula
    con ``tarifas`` en USD por millon de tokens.
    """
    validos = [registro for registro in registros if not _tiene_error(registro)]
    errores = len(registros) - len(validos)
    if not validos:
        return ResumenUso(errores=errores)

    entrada_total = 0
    salida_total = 0
    cache_total = 0
    costo_total = 0.0
    tiempo_total = 0.0
    tiempo_maximo = 0.0
    for registro in validos:
        uso = leer_uso(registro.get("metricas"))
        entrada = uso.entrada or 0
        salida = uso.salida or 0
        cache = min(uso.cache or 0, entrada)
        entrada_total += entrada
        salida_total += salida
        cache_total += cache
        costo_total += _costo(entrada, salida, cache, tarifas)
        segundos = _flotante(registro.get("segundos")) or 0.0
        tiempo_total += segundos
        tiempo_maximo = max(tiempo_maximo, segundos)

    n = len(validos)
    return ResumenUso(
        registros=n,
        errores=errores,
        entrada_total=entrada_total,
        entrada_promedio=entrada_total / n,
        salida_total=salida_total,
        salida_promedio=salida_total / n,
        cache_total=cache_total,
        cache_promedio=cache_total / n,
        costo_usd_total=costo_total,
        costo_usd_promedio=costo_total / n,
        tiempo_promedio=tiempo_total / n,
        tiempo_maximo=tiempo_maximo,
    )


def intervalo_wilson(
    aciertos: int,
    evaluables: int,
    confianza: float = 0.95,
) -> tuple[float, float] | None:
    """Intervalo de confianza de Wilson para una proporcion binomial.

    Args:
        aciertos: numero de respuestas correctas.
        evaluables: total de preguntas que entran en el calculo.
        confianza: nivel de confianza entre cero y uno; por defecto 0,95.

    Returns:
        La tupla ``(limite_inferior, limite_superior)`` acotada a [0, 1], o
        ``None`` si no hay preguntas evaluables.

    Raises:
        ValueError: si los conteos son negativos, ``aciertos`` supera a
            ``evaluables`` o ``confianza`` no esta entre cero y uno.
    """
    if evaluables < 0:
        raise ValueError("evaluables no puede ser negativo")
    if aciertos < 0 or aciertos > evaluables:
        raise ValueError("aciertos debe estar entre cero y evaluables")
    if not 0 < confianza < 1:
        raise ValueError("confianza debe estar entre cero y uno")
    if evaluables == 0:
        return None

    z = NormalDist().inv_cdf(1 - (1 - confianza) / 2)
    proporcion = aciertos / evaluables
    denominador = 1 + z * z / evaluables
    centro = (proporcion + z * z / (2 * evaluables)) / denominador
    margen = (
        z
        * math.sqrt(
            proporcion * (1 - proporcion) / evaluables + z * z / (4 * evaluables * evaluables)
        )
        / denominador
    )
    return (
        0.0 if aciertos == 0 else max(0.0, centro - margen),
        1.0 if aciertos == evaluables else min(1.0, centro + margen),
    )


def p_minimo_mcnemar(n: int) -> float:
    """p minima de dos colas de la prueba exacta de McNemar con ``n`` pares.

    El reparto mas extremo posible es ``b=0`` y ``c=n`` (o al reves), asi que
    la p minima es ``2 * C(n, 0) / 2**n``. Sirve para saber si algun reparto
    con ese numero de pares discordantes podria ser significativo.

    Args:
        n: numero de pares discordantes; no puede ser negativo.

    Returns:
        La p minima alcanzable; 1.0 si no hay pares discordantes.

    Raises:
        ValueError: si ``n`` es negativo.
    """
    if n < 0:
        raise ValueError("n no puede ser negativo")
    if n == 0:
        return 1.0
    return min(1.0, 2 * math.comb(n, 0) / (2**n))


def mcnemar(
    aciertos_v1: Sequence[bool | None],
    aciertos_v2: Sequence[bool | None],
) -> ResultadoMcNemar:
    """Prueba exacta de McNemar para dos versiones pareadas.

    ``b`` cuenta los pares donde v1 acierta y v2 falla; ``c`` lo contrario.
    Los pares con ``None`` en cualquiera de las dos versiones se excluyen y se
    cuentan en ``excluidos``. Exige el mismo largo. Si no hay pares
    discordantes, ``p`` es 1.
    """
    if len(aciertos_v1) != len(aciertos_v2):
        raise ValueError(
            f"Las listas deben tener el mismo largo: {len(aciertos_v1)} != {len(aciertos_v2)}"
        )
    b = 0
    c = 0
    excluidos = 0
    for v1, v2 in zip(aciertos_v1, aciertos_v2, strict=True):
        if v1 is None or v2 is None:
            excluidos += 1
            continue
        if v1 and not v2:
            b += 1
        elif v2 and not v1:
            c += 1
    n = b + c
    if n == 0:
        return ResultadoMcNemar(b=b, c=c, n=n, p=1.0, excluidos=excluidos)
    cola = sum(math.comb(n, i) for i in range(min(b, c) + 1))
    p = min(1.0, 2 * cola / (2**n))
    return ResultadoMcNemar(b=b, c=c, n=n, p=p, excluidos=excluidos)
