"""Evaluación del filtro de dominio: fuga y rechazo indebido con intervalos de Wilson.

El módulo es puro: no conoce el Digiturno ni el canal. Recibe un clasificador
``texto -> Decision`` y un conjunto de casos etiquetados (ver ``docs/ALCANCE.md``)
y devuelve las métricas con su intervalo de confianza.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from banco_occidente_corpus.arqueo.metricas import intervalo_wilson


class Decision(StrEnum):
    """Decisión del filtro sobre un mensaje."""

    ACEPTAR = "aceptar"
    RECHAZAR = "rechazar"


class Categoria(StrEnum):
    """Grupo del caso dentro del conjunto de evaluación."""

    DENTRO = "dentro"
    FUERA = "fuera"
    FRONTERA = "frontera"


Clasificador = Callable[[str], Decision]
"""Función que decide si un texto entra al grafo (aceptar) o se redirige (rechazar)."""


class CasoDominio(BaseModel):
    """Un caso etiquetado del conjunto del filtro de dominio."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(pattern=r"^(dentro|fuera|frontera)-\d{3}$")
    texto: str = Field(min_length=1)
    esperado: Decision
    categoria: Categoria
    subcategoria: str = Field(min_length=1)
    nota: str | None = None

    @model_validator(mode="after")
    def _coherencia(self) -> CasoDominio:
        """Exige que la categoría, el prefijo del id y la decisión esperada concuerden."""
        if not self.id.startswith(f"{self.categoria.value}-"):
            raise ValueError(f"el id {self.id!r} no corresponde a la categoría {self.categoria}")
        if self.categoria is Categoria.DENTRO and self.esperado is not Decision.ACEPTAR:
            raise ValueError("un caso 'dentro' debe esperar 'aceptar'")
        if self.categoria is Categoria.FUERA and self.esperado is not Decision.RECHAZAR:
            raise ValueError("un caso 'fuera' debe esperar 'rechazar'")
        if self.categoria is Categoria.FRONTERA and not self.nota:
            raise ValueError("un caso 'frontera' debe documentar su decisión en 'nota'")
        return self


class IntervaloWilson(BaseModel):
    """Proporción observada con su intervalo de Wilson."""

    model_config = ConfigDict(frozen=True)

    exitos: int = Field(ge=0)
    n: int = Field(gt=0)
    proporcion: float
    inferior: float
    superior: float
    confianza: float

    def como_texto(self) -> str:
        """Devuelve la proporción y el intervalo en porcentaje, p. ej. ``4,0 % [1,1 %; 13,5 %]``."""

        def pct(x: float) -> str:
            return f"{x * 100:.1f}".replace(".", ",") + " %"

        return f"{pct(self.proporcion)} [{pct(self.inferior)}; {pct(self.superior)}]"


class ResultadoFiltro(BaseModel):
    """Métricas del filtro sobre un conjunto de casos."""

    model_config = ConfigDict(frozen=True)

    fuga: IntervaloWilson | None
    rechazo_indebido: IntervaloWilson | None
    acierto_frontera: IntervaloWilson | None
    ids_fuga: tuple[str, ...]
    ids_rechazo_indebido: tuple[str, ...]
    ids_frontera_fallidos: tuple[str, ...]


def intervalo(exitos: int, n: int, confianza: float = 0.95) -> IntervaloWilson | None:
    """Calcula la proporción y su intervalo con ``arqueo.metricas.intervalo_wilson``.

    Se usa Wilson y no Wald porque no produce límites fuera de [0, 1] ni ancho cero
    cuando la proporción observada es 0 o 1, que es lo esperable en un filtro bueno.
    Devuelve ``None`` si no hay casos.
    """
    limites = intervalo_wilson(exitos, n, confianza)
    if limites is None:
        return None
    inferior, superior = limites
    return IntervaloWilson(
        exitos=exitos,
        n=n,
        proporcion=exitos / n,
        inferior=inferior,
        superior=superior,
        confianza=confianza,
    )


def cargar_casos(ruta: Path) -> tuple[CasoDominio, ...]:
    """Lee el conjunto JSONL; falla con el número de línea si una fila es inválida."""
    casos: list[CasoDominio] = []
    vistos: set[str] = set()
    with ruta.open(encoding="utf-8") as archivo:
        for numero, linea in enumerate(archivo, start=1):
            if not linea.strip():
                continue
            try:
                caso = CasoDominio.model_validate(json.loads(linea))
            except (json.JSONDecodeError, ValidationError) as error:
                raise ValueError(f"{ruta}:{numero}: fila inválida: {error}") from error
            if caso.id in vistos:
                raise ValueError(f"{ruta}:{numero}: id repetido {caso.id!r}")
            vistos.add(caso.id)
            casos.append(caso)
    return tuple(casos)


def evaluar_filtro(
    casos: Iterable[CasoDominio],
    clasificador: Clasificador,
    *,
    confianza: float = 0.95,
) -> ResultadoFiltro:
    """Aplica el clasificador a cada caso y calcula fuga, rechazo indebido y frontera.

    - Fuga: casos ``fuera`` aceptados sobre el total de ``fuera``.
    - Rechazo indebido: casos ``dentro`` rechazados sobre el total de ``dentro``.
    - Acierto en frontera: casos ``frontera`` con la decisión esperada sobre su total.
    """
    fugas: list[str] = []
    rechazos: list[str] = []
    frontera_fallidos: list[str] = []
    totales = dict.fromkeys(Categoria, 0)
    for caso in casos:
        obtenida = Decision(clasificador(caso.texto))
        totales[caso.categoria] += 1
        if caso.categoria is Categoria.FUERA and obtenida is Decision.ACEPTAR:
            fugas.append(caso.id)
        elif caso.categoria is Categoria.DENTRO and obtenida is Decision.RECHAZAR:
            rechazos.append(caso.id)
        elif caso.categoria is Categoria.FRONTERA and obtenida is not caso.esperado:
            frontera_fallidos.append(caso.id)

    n_frontera = totales[Categoria.FRONTERA]
    return ResultadoFiltro(
        fuga=intervalo(len(fugas), totales[Categoria.FUERA], confianza),
        rechazo_indebido=intervalo(len(rechazos), totales[Categoria.DENTRO], confianza),
        acierto_frontera=intervalo(n_frontera - len(frontera_fallidos), n_frontera, confianza),
        ids_fuga=tuple(fugas),
        ids_rechazo_indebido=tuple(rechazos),
        ids_frontera_fallidos=tuple(frontera_fallidos),
    )


def reporte_markdown(resultado: ResultadoFiltro) -> str:
    """Devuelve una tabla Markdown lista para el informe del Arqueo."""
    filas = [
        ("Fuga (fuera de tema aceptadas)", resultado.fuga, resultado.ids_fuga),
        (
            "Rechazo indebido (legítimas rechazadas)",
            resultado.rechazo_indebido,
            resultado.ids_rechazo_indebido,
        ),
        ("Acierto en frontera", resultado.acierto_frontera, resultado.ids_frontera_fallidos),
    ]
    lineas = [
        "| Métrica | Casos | Proporción [IC Wilson 95 %] | Casos con error |",
        "|---|---:|---|---|",
    ]
    for nombre, intervalo, ids in filas:
        if intervalo is None:
            lineas.append(f"| {nombre} | 0 | — | — |")
            continue
        detalle = ", ".join(ids) if ids else "—"
        lineas.append(
            f"| {nombre} | {intervalo.exitos}/{intervalo.n} | {intervalo.como_texto()} | {detalle} |"
        )
    return "\n".join(lineas) + "\n"
