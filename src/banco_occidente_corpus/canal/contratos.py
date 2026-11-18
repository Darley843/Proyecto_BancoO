"""Contratos Pydantic del canal de WhatsApp y del diagnóstico financiero.

Son la frontera entre el webhook de Meta, el almacén local, el grafo de la
sucursal y el motor de diagnóstico. Todos los modelos prohíben campos extra:
un cambio de formato en Meta o un error de programación debe fallar aquí y no
más adelante, cuando ya hay datos escritos.

``MensajeEntrante.remitente`` existe solo en memoria: el almacén guarda el
``usuario_id`` y borra el número antes de persistir. Ningún modelo de resultado
contiene nombre ni número.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class BotonCanal(BaseModel):
    """Un botón de respuesta rápida de WhatsApp."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=256)
    titulo: str = Field(min_length=1, max_length=20)


class MensajeEntrante(BaseModel):
    """Mensaje normalizado que llega desde el webhook."""

    model_config = ConfigDict(extra="forbid")

    id_mensaje: str = Field(min_length=1, max_length=128)
    remitente: str = Field(min_length=8, max_length=20)
    texto: str = Field(min_length=1, max_length=4096)
    tipo: Literal["texto", "boton", "interactivo"] = "texto"
    id_boton: str | None = None
    recibido_en: datetime


class RespuestaCanal(BaseModel):
    """Respuesta que el canal envía al usuario."""

    model_config = ConfigDict(extra="forbid")

    usuario_id: str
    id_mensaje_origen: str
    texto: str = Field(min_length=1, max_length=4096)
    tipo: Literal["texto", "botones", "error"] = "texto"
    botones: list[BotonCanal] = Field(default_factory=list, max_length=3)
    metadatos: dict[str, str] = Field(default_factory=dict)


class PerfilUsuario(BaseModel):
    """Perfil mínimo del usuario del canal, fuera del repositorio."""

    model_config = ConfigDict(extra="forbid")

    usuario_id: str
    nombre: str | None = Field(default=None, max_length=80)
    rol: Literal["cliente", "asesor"] = "cliente"
    consentimiento: bool = False
    version_consentimiento: str = ""


class RangoDecimal(BaseModel):
    """Valor mínimo y máximo de una tasa, una cuota o un total."""

    model_config = ConfigDict(extra="forbid")

    desde: Decimal
    hasta: Decimal

    @model_validator(mode="after")
    def _orden(self) -> Self:
        """Exige que ``desde`` no supere a ``hasta``."""
        if self.desde > self.hasta:
            raise ValueError("el rango debe cumplir desde <= hasta")
        return self


class EntradaDiagnostico(BaseModel):
    """Insumos normalizados de un diagnóstico."""

    model_config = ConfigDict(extra="forbid")

    producto: str
    ingreso_mensual: Decimal
    gastos_mensuales: Decimal
    cuotas_deudas: Decimal
    monto_credito: Decimal
    # Vivienda llega a 240 meses; el resto de productos no pasa de 72.
    plazo_meses: int = Field(ge=6, le=240)


class ResultadoDiagnostico(BaseModel):
    """Resultado determinista y trazable del diagnóstico."""

    model_config = ConfigDict(extra="forbid")

    version_formula: str = "v1"
    entrada: EntradaDiagnostico
    tasa_ea: RangoDecimal
    tasa_mensual: RangoDecimal
    cuota_mensual: RangoDecimal
    total_intereses: RangoDecimal
    total_pagado: RangoDecimal
    base_semaforo: Literal["tasa_maxima"] = "tasa_maxima"
    razon_endeudamiento: Decimal
    capacidad_pago: Decimal
    semaforo: Literal["verde", "amarillo", "rojo"]
    recomendaciones: list[str]
    fuente_tasa: str
    vigencia_tasa_desde: date
    vigencia_tasa_hasta: date
    sha256_pdf: str
    umbrales: dict[str, Decimal]
    aviso: str
    escenario_de: str | None = None


class CasoAsesor(BaseModel):
    """Caso que se entrega a un asesor humano."""

    model_config = ConfigDict(extra="forbid")

    id_caso: str
    usuario_id: str
    motivo: str
    semaforo: Literal["verde", "amarillo", "rojo"]
    resultado: ResultadoDiagnostico | None = None
    creado_en: datetime
    estado: Literal["pendiente", "contactado", "descartado", "cerrado"] = "pendiente"
    origen: Literal["diagnostico", "solicitud_directa"] = "diagnostico"
