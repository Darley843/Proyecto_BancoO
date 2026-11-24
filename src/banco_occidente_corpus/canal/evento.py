"""Modo evento del canal: ventana de tiempo y cuotas de la demostración.

La lista cerrada de ``[autorizados]`` solo atiende a los números de prueba. El
modo evento abre el canal a cualquier número **durante una ventana explícita**,
sin saltarse la ley: el primer mensaje recibe el aviso de la Ley 1581 y sin
«Acepto» no se procesa nada.

Lo que el modo evento añade, porque una lista cerrada no lo necesitaba:

- una ventana ``desde``/``hasta`` que se puede cerrar sin tocar código;
- cuota por persona (por hora y total) y tope global de mensajes;
- una ventana de respuesta de 24 horas, la misma que exige Meta para contestar
  con texto libre sin plantilla.

Las fechas del TOML llevan zona horaria (``2026-11-28T08:00:00-05:00``). Si
llegan sin zona se interpretan como UTC, nunca como hora local del servidor.

El evento **no** recorta el alcance: quien acepta el consentimiento recibe el
mismo diagnóstico que un número de la lista, siempre con el consentimiento
primero y las cuotas controlando el gasto.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

#: Horas de la ventana de servicio de Meta para responder sin plantilla.
HORAS_SERVICIO: int = 24


@dataclass(frozen=True, slots=True)
class Evento:
    """Ventana y cuotas del modo evento.

    Attributes:
        activo: si el modo evento está encendido.
        desde: inicio de la ventana; ``None`` significa «desde ya».
        hasta: fin de la ventana; ``None`` significa «sin hora de cierre».
        max_por_hora: mensajes admitidos por persona en una hora.
        max_por_usuario: mensajes admitidos por persona en todo el evento.
        max_total: mensajes admitidos en el evento completo.
        ventana_respuesta_horas: horas durante las que se puede responder a
            quien escribió; la ventana de servicio de Meta.
    """

    activo: bool = False
    desde: datetime | None = None
    hasta: datetime | None = None
    max_por_hora: int = 30
    max_por_usuario: int = 40
    max_total: int = 300
    ventana_respuesta_horas: int = HORAS_SERVICIO

    def vigente(self, momento: datetime | None = None) -> bool:
        """Indica si el evento está encendido y dentro de su ventana.

        Args:
            momento: instante a evaluar; por defecto, ahora.

        Returns:
            ``True`` solo si está activo, ya empezó y todavía no cerró.
        """
        instante = consciente(momento)
        if not self.activo:
            return False
        if self.desde is not None and instante < self.desde:
            return False
        return not (self.hasta is not None and instante > self.hasta)

    def inicio(self, momento: datetime | None = None) -> datetime:
        """Devuelve el instante desde el que se cuentan los totales.

        Args:
            momento: instante de referencia; por defecto, ahora.

        Returns:
            ``desde`` si está definido; si no, 24 horas antes de ``momento``.
        """
        if self.desde is not None:
            return self.desde
        return consciente(momento) - timedelta(hours=HORAS_SERVICIO)

    def limite_respuesta(self, momento: datetime | None = None) -> datetime:
        """Devuelve el corte de la ventana de servicio para responder.

        Args:
            momento: instante de referencia; por defecto, ahora.

        Returns:
            El instante a partir del cual un mensaje entrante ya no habilita una
            respuesta con texto libre.
        """
        return consciente(momento) - timedelta(hours=self.ventana_respuesta_horas)


def consciente(momento: datetime | None = None) -> datetime:
    """Normaliza un instante a UTC con zona horaria.

    Args:
        momento: instante a normalizar; por defecto, ahora.

    Returns:
        El mismo instante en UTC; una fecha sin zona se asume UTC.
    """
    instante = momento or datetime.now(UTC)
    if instante.tzinfo is None:
        return instante.replace(tzinfo=UTC)
    return instante.astimezone(UTC)


def leer_evento(datos: dict[str, Any], *, activo_entorno: bool | None = None) -> Evento:
    """Construye el evento desde la sección ``[evento]`` del TOML.

    Args:
        datos: sección ``evento`` ya cargada del archivo.
        activo_entorno: sobrescritura de ``WHATSAPP_EVENTO``; si llega, manda
            sobre el valor del archivo.

    Returns:
        El evento tipado; sin sección devuelve el modo evento apagado.

    Raises:
        ValueError: si una cuota no es un entero positivo.
    """
    activo = bool(datos.get("activo", False))
    if activo_entorno is not None:
        activo = activo_entorno
    return Evento(
        activo=activo,
        desde=_fecha(datos.get("desde")),
        hasta=_fecha(datos.get("hasta")),
        max_por_hora=_cuota(datos, "max_por_hora", 30),
        max_por_usuario=_cuota(datos, "max_por_usuario", 40),
        max_total=_cuota(datos, "max_total", 300),
    )


def _fecha(valor: object) -> datetime | None:
    """Convierte un valor ISO del TOML a un instante consciente."""
    if valor is None:
        return None
    texto = str(valor).strip()
    if not texto:
        return None
    return consciente(datetime.fromisoformat(texto))


def _cuota(datos: dict[str, Any], clave: str, defecto: int) -> int:
    """Lee una cuota entera positiva del TOML.

    Raises:
        ValueError: si la cuota no es un entero mayor que cero.
    """
    valor = datos.get(clave, defecto)
    if isinstance(valor, bool) or not isinstance(valor, int) or valor <= 0:
        raise ValueError(f"whatsapp.evento.{clave} debe ser un entero mayor que cero")
    return valor
