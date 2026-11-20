"""Entrevista guiada del diagnóstico: una pregunta por turno.

Este módulo es el estado de la entrevista, no su transporte. Recibe las
respuestas ya elegidas (los ids canónicos de `docs/DIAGNOSTICO.md`) y dice cuál
es la siguiente pregunta con sus opciones. No conoce WhatsApp, ni el grafo, ni
el motor: cuando la entrevista termina, `motor.entrada_desde_respuestas` toma el
diccionario y calcula.

Las preguntas y los textos de los rangos se leen de `config/diagnostico.toml`
(`preguntas` y `textos` de `motor.cargar_config`). Los bloques fijos `objetivo`
y `vinculacion` viven aquí porque son listas cerradas, no rangos con valores de
cálculo. La entrevista no repite preguntas: `pregunta_pendiente` devuelve siempre
el primer bloque sin responder del producto elegido.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

from ..texto import normalizar
from .motor import ConfigDiagnostico, cargar_config

#: Identificador del botón que arranca la entrevista.
ID_EMPEZAR: str = "diagnostico.empezar"
#: Identificador del botón que abandona la entrevista.
ID_CANCELAR: str = "diagnostico.cancelar"
#: Identificador del botón que pide un asesor humano.
ID_ASESOR: str = "diagnostico.asesor"

#: Pregunta del primer paso, común a todos los productos.
TEXTO_OBJETIVO: str = "¿Qué te gustaría revisar?"
#: Pregunta del segundo paso, común a todos los productos.
TEXTO_VINCULACION: str = "¿Cómo recibes tus ingresos?"

#: Opciones del bloque `objetivo`, en el orden del guion. El título es corto
#: porque una fila de lista admite 24 caracteres; el detalle va en la
#: descripción.
OBJETIVOS: tuple[tuple[str, str, str], ...] = (
    ("objetivo.libre_inversion", "Libre inversión", "Un préstamo de libre destino"),
    ("objetivo.compra_cartera", "Compra de cartera", "Pasar mis deudas a una mejor tasa"),
    ("objetivo.vehiculo_nuevo", "Vehículo nuevo", "Comprar carro o moto nueva"),
    ("objetivo.vehiculo_usado", "Vehículo usado", "Comprar carro o moto usada"),
    ("objetivo.vivienda", "Vivienda", "Crédito hipotecario"),
    ("objetivo.libranza", "Libranza", "Descuento por nómina o pensión"),
    ("objetivo.ahorro", "Solo ahorrar", "Cuenta de ahorros o CDT"),
)

#: Opciones del bloque `vinculacion`, en el orden del guion.
VINCULACIONES: tuple[tuple[str, str], ...] = (
    ("vinculacion.empleado", "Empleado"),
    ("vinculacion.independiente", "Independiente"),
    ("vinculacion.pensionado", "Pensionado"),
)

#: Bloques que se preguntan siempre, en orden.
BLOQUES_BASE: tuple[str, ...] = ("objetivo", "vinculacion", "ingresos", "gastos", "cuotas")

#: Bloques que dependen del producto elegido.
BLOQUES_CREDITO: tuple[str, ...] = ("monto", "plazo")

#: Producto que además pregunta por la cuota que se quiere trasladar.
PRODUCTO_TRASLADO: str = "compra_cartera"

#: Producto que no simula cuota de crédito.
PRODUCTO_AHORRO: str = "ahorro"

#: Cantidad máxima de opciones que WhatsApp admite como botones.
MAXIMO_BOTONES: int = 3


class RespuestaInvalida(ValueError):
    """La respuesta no es una de las opciones de la pregunta pendiente."""


@dataclass(frozen=True, slots=True)
class OpcionEntrevista:
    """Una opción que la persona puede elegir en un paso.

    Attributes:
        id: id canónico de `docs/DIAGNOSTICO.md`.
        titulo: texto corto que se muestra en el botón o en la fila.
        descripcion: detalle de la fila; los botones no lo usan.
    """

    id: str
    titulo: str
    descripcion: str | None = None


@dataclass(frozen=True, slots=True)
class Pregunta:
    """Un paso de la entrevista con sus opciones.

    Attributes:
        clave: bloque del guion (`objetivo`, `ingresos`, `monto`, …).
        texto: enunciado que se envía a la persona.
        opciones: opciones válidas, en el orden del guion.
    """

    clave: str
    texto: str
    opciones: tuple[OpcionEntrevista, ...]

    @property
    def tipo(self) -> Literal["botones", "lista"]:
        """Forma de envío: botones hasta tres opciones; lista si son más."""
        return "botones" if len(self.opciones) <= MAXIMO_BOTONES else "lista"


def bloques(producto: str | None) -> tuple[str, ...]:
    """Devuelve los bloques que faltan preguntar para un producto.

    Args:
        producto: clave canónica del producto, o ``None`` si todavía no se
            respondió el objetivo.

    Returns:
        Los bloques en el orden del guion. El ahorro se queda en los cinco
        bloques base; la compra de cartera añade la cuota a trasladar; los
        demás productos añaden monto y plazo.
    """
    pasos = list(BLOQUES_BASE)
    if producto == PRODUCTO_TRASLADO:
        pasos.append("cuota_trasladar")
    if producto is not None and producto != PRODUCTO_AHORRO:
        pasos.extend(BLOQUES_CREDITO)
    return tuple(pasos)


def _resolver(clave: str, producto: str | None, config: ConfigDiagnostico) -> str:
    """Traduce `monto` o `plazo` a la variante que aplica al producto.

    Args:
        clave: bloque genérico (`monto` o `plazo`).
        producto: producto elegido.
        config: configuración con los bloques y su aplicabilidad.

    Returns:
        La clave real del bloque (`monto_vivienda`, `plazo_vivienda`, …); la
        misma clave si no hay variante.
    """
    if clave not in BLOQUES_CREDITO or producto is None:
        return clave
    for candidato in config.orden:
        if candidato != clave and not candidato.startswith(f"{clave}_"):
            continue
        bloque = config.bloques.get(candidato)
        if bloque is not None and producto in bloque.productos:
            return candidato
    return clave


def _opciones(clave: str, config: ConfigDiagnostico) -> tuple[OpcionEntrevista, ...]:
    """Arma las opciones de un bloque a partir de la configuración."""
    if clave == "objetivo":
        return tuple(OpcionEntrevista(*datos) for datos in OBJETIVOS)
    if clave == "vinculacion":
        return tuple(OpcionEntrevista(*datos) for datos in VINCULACIONES)
    return tuple(
        OpcionEntrevista(ident, config.textos.get(ident, ident))
        for ident, bloque in config.claves.items()
        if bloque == clave
    )


def _texto(clave: str, config: ConfigDiagnostico) -> str:
    """Devuelve el enunciado de un bloque."""
    if clave == "objetivo":
        return TEXTO_OBJETIVO
    if clave == "vinculacion":
        return TEXTO_VINCULACION
    return config.preguntas.get(clave, clave)


def pregunta_pendiente(
    respuestas: Mapping[str, str],
    *,
    config: ConfigDiagnostico | None = None,
) -> Pregunta | None:
    """Devuelve la siguiente pregunta o ``None`` si la entrevista terminó.

    Args:
        respuestas: respuestas guardadas, con la clave del bloque por llave.
        config: configuración ya cargada; por defecto se lee el TOML.

    Returns:
        La primera pregunta sin responder para el producto elegido, o ``None``
        cuando ya están todas.

    Raises:
        ValueError: si las respuestas traen un objetivo que no existe.
    """
    ajustes = config if config is not None else cargar_config()
    producto = _producto(respuestas)
    for clave in bloques(producto):
        real = _resolver(clave, producto, ajustes)
        if real in respuestas or clave in respuestas:
            continue
        return Pregunta(real, _texto(real, ajustes), _opciones(real, ajustes))
    return None


def _producto(respuestas: Mapping[str, str]) -> str | None:
    """Extrae el producto del id del objetivo, o ``None`` si no se respondió."""
    elegido = respuestas.get("objetivo")
    if not elegido:
        return None
    if not elegido.startswith("objetivo."):
        raise ValueError(f"«{elegido}» no es un objetivo del diagnóstico")
    return elegido.split(".", 1)[1]


def _clave(texto: str) -> str:
    """Normaliza un texto para comparar títulos sin tildes ni signos."""
    limpio = re.sub(r"[$.*]", " ", normalizar(texto))
    return re.sub(r"\s+", " ", limpio).strip()


def _coincidir(pregunta: Pregunta, texto: str, id_boton: str | None) -> str | None:
    """Busca la opción elegida por id o por título.

    Args:
        pregunta: paso pendiente.
        texto: texto que escribió la persona (o el título de la fila).
        id_boton: id canónico que devolvió el botón o la fila, si lo hay.

    Returns:
        El id de la opción elegida, o ``None`` si no coincide con ninguna.
    """
    candidatos = [valor for valor in (id_boton, texto) if valor]
    for candidato in candidatos:
        for opcion in pregunta.opciones:
            if candidato.strip() == opcion.id:
                return opcion.id
    for candidato in candidatos:
        buscado = _clave(candidato)
        for opcion in pregunta.opciones:
            if buscado and buscado in {_clave(opcion.titulo), _clave(opcion.id)}:
                return opcion.id
    return None


def _validar_traslado(respuestas: Mapping[str, str], config: ConfigDiagnostico) -> None:
    """Exige que la cuota a trasladar no supere las cuotas actuales.

    Raises:
        RespuestaInvalida: si la cuota trasladada es mayor.
    """
    traslado = respuestas.get("cuota_trasladar")
    cuotas = respuestas.get("cuotas")
    if not traslado or not cuotas:
        return
    if config.valores.get(traslado, 0) > config.valores.get(cuotas, 0):
        raise RespuestaInvalida(
            "La cuota que quieres trasladar no puede ser mayor que las cuotas que "
            "pagas hoy. Elige una opción menor."
        )


def registrar_respuesta(
    respuestas: Mapping[str, str],
    texto: str,
    id_boton: str | None = None,
    *,
    config: ConfigDiagnostico | None = None,
) -> dict[str, str]:
    """Valida la respuesta del paso pendiente y devuelve las respuestas nuevas.

    Args:
        respuestas: respuestas ya guardadas.
        texto: texto que escribió la persona o título de la fila elegida.
        id_boton: id canónico del botón o de la fila, si vino.
        config: configuración ya cargada; por defecto se lee el TOML.

    Returns:
        Una copia de las respuestas con el bloque pendiente registrado.

    Raises:
        RespuestaInvalida: si la opción no es válida o si la cuota trasladada
            supera las cuotas actuales.
        ValueError: si la entrevista ya está completa.
    """
    ajustes = config if config is not None else cargar_config()
    pregunta = pregunta_pendiente(respuestas, config=ajustes)
    if pregunta is None:
        raise ValueError("la entrevista ya está completa")
    elegido = _coincidir(pregunta, texto, id_boton)
    if elegido is None:
        raise RespuestaInvalida(
            f"«{texto}» no es una de las opciones. Elige una de la lista o escribe «cancelar»."
        )
    nuevas = dict(respuestas)
    nuevas[pregunta.clave] = elegido
    _validar_traslado(nuevas, ajustes)
    return nuevas


def titulo_de(ident: str, *, config: ConfigDiagnostico | None = None) -> str:
    """Devuelve el texto visible de un id, para confirmar lo anotado.

    Args:
        ident: id canónico elegido.
        config: configuración ya cargada; por defecto se lee el TOML.

    Returns:
        El título corto de la opción, o el mismo id si no está en el guion.
    """
    for datos in OBJETIVOS:
        if datos[0] == ident:
            return datos[1]
    for datos in VINCULACIONES:
        if datos[0] == ident:
            return datos[1]
    ajustes = config if config is not None else cargar_config()
    return ajustes.textos.get(ident, ident)


def comando(texto: str, id_boton: str | None = None) -> str | None:
    """Reconoce las órdenes que no son respuestas de la entrevista.

    Args:
        texto: mensaje de la persona.
        id_boton: id del botón o de la fila, si vino.

    Returns:
        ``"empezar"``, ``"cancelar"``, ``"asesor"`` o ``None`` si es una
        respuesta normal.
    """
    if id_boton == ID_EMPEZAR:
        return "empezar"
    if id_boton == ID_CANCELAR:
        return "cancelar"
    if id_boton == ID_ASESOR:
        return "asesor"
    normalizado = _clave(texto)
    if normalizado in {"cancelar", "salir", "dejalo", "no quiero"}:
        return "cancelar"
    if normalizado in {"asesor", "prefiero un asesor", "hablar con un asesor", "un asesor"}:
        return "asesor"
    return None
