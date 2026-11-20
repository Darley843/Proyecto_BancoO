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

#: Productos que el diagnóstico puede simular (docs/DIAGNOSTICO.md).
ProductoDiagnostico = Literal[
    "libre_inversion",
    "compra_cartera",
    "vehiculo_nuevo",
    "vehiculo_usado",
    "vivienda",
    "libranza",
    "ahorro",
]
#: Formas válidas de recibir ingresos en la entrevista.
Vinculacion = Literal["empleado", "independiente", "pensionado"]
#: Motivos estructurados que acompañan a un resultado sin cuota de crédito.
AlertaDiagnostico = Literal[
    "vivienda_30",
    "libranza_no_aplica",
    "capacidad_negativa",
    "vigencia_vencida",
]
#: Color del semáforo; ``None`` significa que el producto no tiene semáforo.
SemaforoDiagnostico = Literal["verde", "amarillo", "rojo"]

#: Peso máximo del PNG de Pana que viaja por el canal (bytes). WhatsApp acepta
#: hasta 5 MB, pero la tarjeta se genera por debajo de 1 MB.
PESO_MAXIMO_IMAGEN: int = 1_000_000


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
    """Respuesta que el canal envía al usuario.

    Una respuesta de tipo ``imagen`` lleva además el PNG de Pana en memoria:
    el texto viaja primero y la imagen después. El PNG se excluye de la
    representación para que sus bytes no terminen en un log.
    """

    model_config = ConfigDict(extra="forbid")

    usuario_id: str
    id_mensaje_origen: str
    texto: str = Field(min_length=1, max_length=4096)
    tipo: Literal["texto", "botones", "error", "imagen"] = "texto"
    botones: list[BotonCanal] = Field(default_factory=list, max_length=3)
    metadatos: dict[str, str] = Field(default_factory=dict)
    imagen: bytes | None = Field(default=None, repr=False)

    @model_validator(mode="after")
    def _imagen_coherente(self) -> Self:
        """Exige el PNG con el tipo imagen y lo prohíbe en los demás tipos.

        La imagen acompaña al texto y no reemplaza a los botones, así que una
        respuesta de imagen no los admite. El peso se controla antes de salir
        a la red.

        Returns:
            La respuesta validada.

        Raises:
            ValueError: si falta el PNG, si sobra, si lleva botones o si pesa
                1 MB o más.
        """
        if self.tipo == "imagen":
            if self.imagen is None:
                raise ValueError("la respuesta de tipo imagen necesita el PNG")
            if self.botones:
                raise ValueError("la respuesta de tipo imagen no lleva botones")
        elif self.imagen is not None:
            raise ValueError("solo la respuesta de tipo imagen lleva PNG")
        if self.imagen is not None and len(self.imagen) >= PESO_MAXIMO_IMAGEN:
            raise ValueError("la imagen del canal pesa 1 MB o más")
        return self


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
    """Insumos normalizados de un diagnóstico.

    ``monto_credito`` y ``plazo_meses`` son obligatorios para los productos de
    crédito y no aplican al ahorro: el validador rechaza un ahorro con monto o
    plazo y un crédito sin ellos. ``cuota_trasladar`` solo la usa la compra de
    cartera, donde el motor la exige al calcular.
    """

    model_config = ConfigDict(extra="forbid")

    producto: ProductoDiagnostico
    vinculacion: Vinculacion
    ingreso_mensual: Decimal = Field(ge=0)
    gastos_mensuales: Decimal = Field(ge=0)
    cuotas_deudas: Decimal = Field(ge=0)
    cuota_trasladar: Decimal | None = Field(default=None, ge=0)
    monto_credito: Decimal | None = Field(default=None, ge=0)
    # Vivienda llega a 240 meses; el resto de productos no pasa de 72.
    plazo_meses: int | None = Field(default=None, ge=6, le=240)
    #: Id canónico de la opción usada en cada bloque de la entrevista.
    rango_usado: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _insumos_por_producto(self) -> Self:
        """Exige monto y plazo en crédito y los prohíbe en ahorro."""
        if self.producto == "ahorro":
            if self.monto_credito is not None or self.plazo_meses is not None:
                raise ValueError("el ahorro no se simula con monto ni plazo de crédito")
            return self
        if self.monto_credito is None or self.plazo_meses is None:
            raise ValueError(
                "monto_credito y plazo_meses son obligatorios para productos de crédito"
            )
        return self


class TramoTasa(BaseModel):
    """Un plazo o un tramo de saldo con su propia tasa E.A."""

    model_config = ConfigDict(extra="forbid")

    etiqueta: str = Field(min_length=1)
    tasa_ea: RangoDecimal


class TasaCaptacion(BaseModel):
    """Tasa de ahorro o CDT vigente que acompaña a un resultado de ahorro.

    ``tasa_ea`` es la referencia que se muestra primero: en ahorro, el tramo de
    saldo más bajo, y en CDT, el rango por plazo del monto mínimo. ``referencia``
    nombra ese tramo y ``rango_completo`` conserva la envolvente del producto
    como dato adicional. En el CDT, ``tramos`` desagrega la tasa por plazo para
    que la respuesta no presente un solo porcentaje como «la tasa».
    """

    model_config = ConfigDict(extra="forbid")

    producto: Literal["ahorro", "cdt"]
    tasa_ea: RangoDecimal
    referencia: str | None = None
    rango_completo: RangoDecimal | None = None
    tramos: list[TramoTasa] = Field(default_factory=list, max_length=16)
    vigencia_desde: date
    vigencia_hasta: date
    fuente: str


class ResultadoDiagnostico(BaseModel):
    """Resultado determinista y trazable del diagnóstico.

    Los campos de crédito son opcionales porque no todos los productos simulan
    una cuota: el ahorro no tiene semáforo, la libranza no aplica a un
    independiente y la capacidad negativa no permite simular. En esos casos
    ``semaforo`` es ``None`` (salvo la capacidad negativa, que es rojo sin
    cuota) y ``cuota_mensual``, ``tasa_ea`` y los totales quedan vacíos; las
    ``alertas`` explican el motivo.
    """

    model_config = ConfigDict(extra="forbid")

    version_formula: str = "v1"
    entrada: EntradaDiagnostico
    base_semaforo: Literal["tasa_maxima"] = "tasa_maxima"
    tasa_ea: RangoDecimal | None = None
    tasa_mensual: RangoDecimal | None = None
    cuota_mensual: RangoDecimal | None = None
    total_intereses: RangoDecimal | None = None
    total_pagado: RangoDecimal | None = None
    razon_endeudamiento: Decimal | None = None
    capacidad_pago: Decimal
    margen_despues_cuota: Decimal | None = None
    ahorro_mensual_estimado: Decimal | None = None
    semaforo: SemaforoDiagnostico | None = None
    alertas: list[AlertaDiagnostico] = Field(default_factory=list)
    motivos: list[str] = Field(default_factory=list)
    recomendaciones: list[str]
    fuente_tasa: str | None = None
    vigencia_tasa_desde: date | None = None
    vigencia_tasa_hasta: date | None = None
    sha256_pdf: str | None = None
    umbrales: dict[str, Decimal] = Field(default_factory=dict)
    tasas_captacion: list[TasaCaptacion] = Field(default_factory=list)
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
