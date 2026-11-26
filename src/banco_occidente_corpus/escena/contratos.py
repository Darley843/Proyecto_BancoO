"""Contrato único de la escena demo: `TurnoEscena` y sus modelos.

La pantalla, la voz, la entrada por voz y el auditor consumen los mismos
objetos. La pantalla no calcula cifras ni decide rutas: pinta lo que recibe.
Toda `CifraEscena` declara una `FuenteCifra` verificable y el veredicto del
auditor (`conforme`, `con_observaciones`, `objeta`) no usa colores, para no
confundirlo con el semáforo financiero del crédito (`verde`, `amarillo`,
`rojo`).

Los modelos rechazan campos extra: el contrato es explícito y cualquier dato
nuevo obliga a actualizar el diseño, `app/web/escena/contrato.js` y este
archivo en el mismo cambio.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from ..canal.contratos import ResultadoDiagnostico

#: Personajes de la escena; salvo `invitado`, coinciden con las claves de
#: `config/voz.toml`. El invitado es el voluntario que escribe por WhatsApp y
#: va solo en subtítulo, sin voz.
PersonajeEscena = Literal[
    "pana", "don_gota", "joven", "agente_joven", "agente_banco", "auditor", "invitado"
]
#: Origen de un turno. Don Gota siempre usa `guion_fijo`; `canal` distingue los
#: turnos que publica el canal de WhatsApp (mensaje del invitado o respuesta de
#: Pana) de los que salen de una herramienta o del guion.
OrigenTurno = Literal["guion_fijo", "motor", "llm", "reglas", "entrada_voz", "canal"]
#: Naturaleza verificable de una cifra. `documento` cita un archivo del
#: repositorio con su ancla (`docs/ARQUEO.md#ancla`).
TipoFuente = Literal["config", "gold", "motor", "calculo_gota", "usura", "guion", "documento"]
#: Unidad de una cifra. Las tasas se guardan como fracción (0,2834 = 28,34 %).
UnidadCifra = Literal["pesos", "porcentaje_ea", "porcentaje", "meses", "dias", "veces"]
#: Semáforo financiero del crédito, distinto del veredicto del auditor.
SemaforoCifra = Literal["verde", "amarillo", "rojo"]


class _ModeloEscena(BaseModel):
    """Base de los modelos de la escena: cierra el contrato a campos extra."""

    model_config = ConfigDict(extra="forbid")


class FuenteCifra(_ModeloEscena):
    """Origen verificable de una cifra de la escena."""

    tipo: TipoFuente
    referencia: str = Field(min_length=1)
    vigencia: str | None = None
    sha256: str | None = None


class CifraEscena(_ModeloEscena):
    """Cifra que un turno dice, con su valor de máquina y su texto legible.

    `valor` sigue la convención del motor: las tasas son fracciones y los
    pesos son unidades. `valor_legible` es el texto que se muestra y que la
    plantilla usa en el turno, para que no diverjan.
    """

    etiqueta: str = Field(min_length=1)
    valor: Decimal
    valor_legible: str = Field(min_length=1)
    unidad: UnidadCifra
    fuente: FuenteCifra


class EscenarioEscena(_ModeloEscena):
    """Escenario precalculado por el motor, con la decisión del código."""

    codigo: str = Field(min_length=1)
    descripcion: str = Field(min_length=1)
    producto: str = Field(min_length=1)
    monto: Decimal
    plazo_meses: int | None = None
    cuota_mensual: Decimal | None = None
    total_pagado: Decimal | None = None
    total_intereses: Decimal | None = None
    semaforo: SemaforoCifra | None = None
    razon_endeudamiento: Decimal | None = None
    margen_despues_cuota: Decimal | None = None
    aceptable: bool
    ofertable: bool


class HallazgoEscena(_ModeloEscena):
    """Hallazgo del auditor sobre un turno concreto."""

    codigo: str = Field(min_length=1)
    turno_id: str | None = None
    detalle: str = Field(min_length=1)
    gravedad: Literal["alta", "media"]


class TurnoEscena(_ModeloEscena):
    """Unidad que comparten voz, subtítulos, entrada por voz y auditor."""

    id: str = Field(min_length=1)
    orden: int = Field(ge=0)
    personaje: PersonajeEscena
    texto: str = Field(min_length=1)
    subtitulo: str | None = None
    cifras: tuple[CifraEscena, ...] = ()
    escenario: EscenarioEscena | None = None
    origen: OrigenTurno
    hallazgos: tuple[HallazgoEscena, ...] = ()


class PrestamoGota(_ModeloEscena):
    """Resultado determinista del préstamo de Don Gota."""

    version_formula: str = Field(min_length=1)
    monto: Decimal
    tasa_mensual: Decimal
    dias_ciclo: int = Field(gt=0)
    meses_horizonte: int = Field(gt=0)
    interes_mensual: Decimal
    total_ciclo: Decimal
    cuota_diaria: Decimal
    intereses_horizonte: Decimal
    total_pagado_horizonte: Decimal
    tasa_ea: Decimal
    supuesto: str = Field(min_length=1)
    fuente: FuenteCifra


class ComparacionGota(_ModeloEscena):
    """Comparación de Pana entre Don Gota, el banco y la usura.

    `usura_ea`, `usura_vigencia`, `veces_usura` y `fuente_usura` quedan vacíos
    cuando la usura no está certificada: la comparación no calcula el ratio ni
    inventa una cifra.
    """

    monto: Decimal
    plazo_meses: int = Field(gt=0)
    tasa_ea_banco: Decimal
    tasa_ea_gota: Decimal
    usura_ea: Decimal | None
    usura_vigencia: str | None
    total_banco: Decimal
    total_gota: Decimal
    diferencia: Decimal
    veces_total: Decimal | None
    veces_usura: Decimal | None
    articulo_305: str = Field(min_length=1)
    supuestos: tuple[str, ...]
    fuente_usura: FuenteCifra | None


class RespuestaEscena(_ModeloEscena):
    """Respuesta del voluntario a una de las cuatro preguntas."""

    pregunta: Literal["monto", "ingresos", "gastos", "deudas"]
    letra: Literal["A", "B", "C", "D", "E", "F"]
    opcion_id: str = Field(min_length=1)
    texto: str = Field(min_length=1)
    valor: Decimal


class PerfilEscena(_ModeloEscena):
    """Perfil ficticio que sostiene la escena; no contiene datos personales."""

    personaje: str = Field(min_length=1)
    proposito: str = Field(min_length=1)
    monto_declarado: Decimal
    monto_calculo: Decimal
    respuestas: tuple[RespuestaEscena, ...]
    vinculacion: Literal["empleado"] = "empleado"
    plazo_meses: Literal[36] = 36
    producto: Literal["libre_inversion"] = "libre_inversion"
    confirmado: bool


class SeleccionVoluntario(_ModeloEscena):
    """Fila y silla elegidas al azar; no identifica a la persona."""

    fila: int = Field(ge=1)
    silla: int = Field(ge=1)
    filas: int = Field(ge=1)
    sillas: int = Field(ge=1)
    metodo: Literal["azar", "manual"]


class VeredictoAuditor(_ModeloEscena):
    """Veredicto del auditor, independiente del semáforo del crédito.

    Los únicos valores aceptados son `conforme`, `con_observaciones` y
    `objeta`: un color del semáforo no es un veredicto.
    """

    veredicto: Literal["conforme", "con_observaciones", "objeta"]
    hallazgos: tuple[HallazgoEscena, ...]
    turnos_revisados: tuple[str, ...]
    reglas: tuple[str, ...]
    alternativas: tuple[str, ...] = ()


class Escena(_ModeloEscena):
    """Escena completa que consume la pantalla."""

    id: str = Field(min_length=1)
    modo: Literal["vivo", "seguro", "nucleo", "proyectado"]
    perfil: PerfilEscena
    seleccion: SeleccionVoluntario | None = None
    diagnostico: ResultadoDiagnostico
    gota: PrestamoGota
    comparacion: ComparacionGota
    escenarios: tuple[EscenarioEscena, ...]
    turnos: tuple[TurnoEscena, ...]
    veredicto: VeredictoAuditor
    sellos: dict[str, str] = Field(default_factory=dict)


class NegociacionEscena(_ModeloEscena):
    """Turnos de la negociación y veredicto sobre la escena completa."""

    turnos: tuple[TurnoEscena, ...]
    escenarios: tuple[EscenarioEscena, ...]
    veredicto: VeredictoAuditor
    registro: tuple[str, ...] = ()
