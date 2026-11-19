"""Personas sintéticas: guiones de turnos que se convierten en payloads del webhook.

Cada persona es la entrevista del diagnóstico con el resultado esperado. Los ids
de botones y filas son los canónicos de ``docs/DIAGNOSTICO.md``. El consentimiento
y la confirmación los define el canal: se agregan con ``preambulo`` y ``cierre``
de :func:`conversacion`. Se usan en las pruebas de punta a punta sin red y en el
Arqueo.
"""

from __future__ import annotations

import json
from enum import StrEnum
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from banco_occidente_corpus.simulador.payloads import (
    MARCA_TIEMPO_BASE,
    Payload,
    numero_ficticio,
    payload_boton,
    payload_lista,
    payload_texto,
)


class SemaforoEsperado(StrEnum):
    """Color esperado del diagnóstico según ``docs/DIAGNOSTICO.md``."""

    VERDE = "verde"
    AMARILLO = "amarillo"
    ROJO = "rojo"
    SIN_TASA = "sin_tasa"


class Turno(BaseModel):
    """Un mensaje que envía la persona."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    tipo: Literal["texto", "boton", "lista"]
    valor: str = Field(min_length=1, description="Texto libre, o id del botón o de la fila.")
    titulo: str | None = Field(default=None, description="Título visible del botón o la fila.")
    descripcion: str | None = None


class Esperado(BaseModel):
    """Lo que el sistema debe producir al final de la conversación."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    semaforo: SemaforoEsperado | None
    deriva_asesor: bool
    bloquea_inyeccion: bool = False
    nota: str


class Persona(BaseModel):
    """Persona sintética con su guion de turnos."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(pattern=r"^[a-z_]+$")
    nombre: str
    perfil: str
    indice_numero: int = Field(ge=0, lt=100_000)
    turnos: tuple[Turno, ...] = Field(min_length=1)
    esperado: Esperado

    @property
    def numero(self) -> str:
        """Número ficticio de WhatsApp de la persona."""
        return numero_ficticio(self.indice_numero)


def cargar_personas(ruta: Path) -> tuple[Persona, ...]:
    """Lee el archivo JSON de personas y valida ids y números únicos."""
    datos = json.loads(ruta.read_text(encoding="utf-8"))
    personas = tuple(Persona.model_validate(p) for p in datos["personas"])
    ids = [p.id for p in personas]
    if len(ids) != len(set(ids)):
        raise ValueError("hay ids de persona repetidos")
    indices = [p.indice_numero for p in personas]
    if len(indices) != len(set(indices)):
        raise ValueError("hay personas con el mismo número")
    return personas


def conversacion(
    persona: Persona,
    *,
    preambulo: tuple[Turno, ...] = (),
    cierre: tuple[Turno, ...] = (),
    marca_tiempo_inicial: int = MARCA_TIEMPO_BASE,
    segundos_entre_turnos: int = 20,
) -> list[Payload]:
    """Convierte el guion de la persona en la lista ordenada de payloads del webhook.

    Args:
        persona: persona sintética con sus turnos de entrevista.
        preambulo: turnos del canal antes de la entrevista (p. ej., el botón de consentimiento).
        cierre: turnos del canal después de la entrevista (p. ej., el botón de confirmación).
        marca_tiempo_inicial: hora Unix del primer mensaje.
        segundos_entre_turnos: separación entre mensajes consecutivos.
    """
    if segundos_entre_turnos <= 0:
        raise ValueError("segundos_entre_turnos debe ser positivo")
    payloads: list[Payload] = []
    for posicion, turno in enumerate((*preambulo, *persona.turnos, *cierre)):
        marca = marca_tiempo_inicial + posicion * segundos_entre_turnos
        if turno.tipo == "texto":
            payloads.append(
                payload_texto(
                    persona.numero, turno.valor, marca_tiempo=marca, nombre=persona.nombre
                )
            )
        elif turno.tipo == "boton":
            payloads.append(
                payload_boton(
                    persona.numero,
                    turno.valor,
                    turno.titulo or turno.valor,
                    marca_tiempo=marca,
                    nombre=persona.nombre,
                )
            )
        else:
            payloads.append(
                payload_lista(
                    persona.numero,
                    turno.valor,
                    turno.titulo or turno.valor,
                    turno.descripcion,
                    marca_tiempo=marca,
                    nombre=persona.nombre,
                )
            )
    return payloads
