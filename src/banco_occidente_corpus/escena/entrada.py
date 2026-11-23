"""Entrada del voluntario por voz o teclado: letras A–F, montos y confirmación.

El parser es determinista: no usa modelo ni red. El navegador transcribe con su
propio reconocimiento de voz y aquí solo se interpreta el texto, que se descarta
al confirmar. Las letras y sus rangos salen de ``config/diagnostico.toml``; el
monto declarado se usa solo si cae dentro del rango de la letra y, si no, se usa
el valor del rango y se explica: nunca se recorta en silencio.

Las pruebas viven en ``test/test_escena_entrada.py``.
"""

from __future__ import annotations

import re
import tomllib
import unicodedata
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Literal, cast

from ..asistente.validacion import detectar_pii
from ..diagnostico import motor
from .contratos import PerfilEscena, RespuestaEscena
from .perfiles import LETRAS, OpcionEscena, opciones_escena

#: Preguntas de la escena, en el orden en que se hacen.
PREGUNTAS: tuple[Literal["monto", "ingresos", "gastos", "deudas"], ...] = (
    "monto",
    "ingresos",
    "gastos",
    "deudas",
)
Letra = Literal["A", "B", "C", "D", "E", "F"]
Pregunta = Literal["monto", "ingresos", "gastos", "deudas"]
Confirmacion = Literal["si", "no", "cambia"]

#: Intentos por pregunta antes de pasar al perfil seguro.
INTENTOS_MAXIMOS = 2

#: Límites del monto, en pesos, tomados de `config/diagnostico.toml`.
MONTO_MINIMO = Decimal(500_000)
MONTO_MAXIMO = Decimal(2_000_000_000)

#: Nombres de las letras que también se dicen como palabra.
_NOMBRE_LETRA: dict[str, str] = {
    "a": "A",
    "b": "B",
    "be": "B",
    "c": "C",
    "ce": "C",
    "d": "D",
    "de": "D",
    "e": "E",
    "f": "F",
    "efe": "F",
}

_UNIDADES: dict[str, int] = {
    "cero": 0,
    "un": 1,
    "uno": 1,
    "una": 1,
    "dos": 2,
    "tres": 3,
    "cuatro": 4,
    "cinco": 5,
    "seis": 6,
    "siete": 7,
    "ocho": 8,
    "nueve": 9,
    "diez": 10,
    "once": 11,
    "doce": 12,
    "trece": 13,
    "catorce": 14,
    "quince": 15,
    "dieciseis": 16,
    "diecisiete": 17,
    "dieciocho": 18,
    "diecinueve": 19,
    "veinte": 20,
    "veintiuno": 21,
    "veintidos": 22,
    "veintitres": 23,
    "veinticuatro": 24,
    "veinticinco": 25,
    "veintiseis": 26,
    "veintisiete": 27,
    "veintiocho": 28,
    "veintinueve": 29,
    "treinta": 30,
    "cuarenta": 40,
    "cincuenta": 50,
    "sesenta": 60,
    "setenta": 70,
    "ochenta": 80,
    "noventa": 90,
    "cien": 100,
    "ciento": 100,
}
_ESCALAS: dict[str, int] = {
    "mil": 1_000,
    "millon": 1_000_000,
    "millones": 1_000_000,
    "palo": 1_000_000,
    "palos": 1_000_000,
    "luca": 1_000,
    "lucas": 1_000,
}
_RE_LETRA_EXPLICITA = re.compile(r"\b(?:letra|opcion|tarjeta)\s+([a-f])\b")
_RE_DIGITOS = re.compile(r"\$?\s*(\d[\d.\s]*(?:,\d+)?)")
_RE_ESCALA = re.compile(r"\b(millones|millon|palos|palo|lucas|luca|mil)\b")
_RE_SI = re.compile(r"^(si|confirmo|dale|correcto|listo|de acuerdo|asi es)\b")
_RE_NO = re.compile(r"^(no|incorrecto|cambia|otra vez|espera|revisemos)\b")


@dataclass(frozen=True, slots=True)
class PreguntaEscena:
    """Una de las cuatro preguntas con sus tarjetas A–F."""

    clave: Pregunta
    pregunta: str
    opciones: tuple[OpcionEscena, ...]


@dataclass(frozen=True, slots=True)
class Interpretacion:
    """Resultado de interpretar el texto del voluntario."""

    respuesta: RespuestaEscena | None
    ajustado: bool = False
    mensaje: str | None = None
    seguro: bool = False


def normalizar(texto: str) -> str:
    """Pasa el texto a minúsculas, sin tildes y con espacios simples.

    Args:
        texto: lo que dijo o escribió el voluntario.

    Returns:
        El texto normalizado, sin signos que no sean ``$``, coma o punto.
    """
    descompuesto = unicodedata.normalize("NFD", str(texto))
    sin_tildes = "".join(c for c in descompuesto if unicodedata.category(c) != "Mn")
    limpio = re.sub(r"[^0-9a-z$,.\s]", " ", sin_tildes.lower())
    return re.sub(r"\s+", " ", limpio).strip()


def preguntas_escena(ruta: Path | None = None) -> tuple[PreguntaEscena, ...]:
    """Lee las preguntas y sus tarjetas A–F desde el TOML del diagnóstico.

    Args:
        ruta: archivo del diagnóstico alternativo; por defecto el del motor.

    Returns:
        Las cuatro preguntas, en el orden de la escena, con sus opciones.

    Raises:
        ValueError: si el TOML no declara una pregunta de la escena.
    """
    archivo = Path(ruta) if ruta is not None else motor.RUTA_CONFIG
    with archivo.open("rb") as fh:
        datos = tomllib.load(fh)
    claves = {str(rango.get("clave")): rango for rango in datos.get("rango", [])}
    mapa = {"monto": "monto", "ingresos": "ingresos", "gastos": "gastos", "deudas": "cuotas"}
    opciones = opciones_escena(ruta)
    preguntas: list[PreguntaEscena] = []
    for clave in PREGUNTAS:
        rango = claves.get(mapa[clave])
        if rango is None:
            raise ValueError(f"config/diagnostico.toml no declara el rango «{mapa[clave]}»")
        preguntas.append(
            PreguntaEscena(
                clave=clave,
                pregunta=str(rango.get("pregunta", "")).strip(),
                opciones=opciones[clave],
            )
        )
    return tuple(preguntas)


def letra_de(texto: str) -> Letra | None:
    """Reconoce una letra A–F en lo que dijo el voluntario.

    Acepta ``"A"``, ``"be"``, ``"letra C"`` y ``"opción D"``. Una letra que
    también es palabra corriente (``a``, ``e``, ``de``) solo cuenta si es la
    respuesta completa o viene con ``letra``, ``opción`` o ``tarjeta``: así
    «de» no se confunde con la preposición.

    Args:
        texto: texto del voluntario.

    Returns:
        La letra en mayúscula, o ``None`` si no hay una letra clara.
    """
    limpio = normalizar(texto)
    explicita = _RE_LETRA_EXPLICITA.search(limpio)
    if explicita:
        return cast(Letra, _NOMBRE_LETRA[explicita.group(1)])
    palabras = limpio.split()
    if len(palabras) == 1:
        palabra = palabras[0]
        if palabra in _NOMBRE_LETRA:
            return cast(Letra, _NOMBRE_LETRA[palabra])
    return None


def _a_decimal(bruto: str) -> Decimal | None:
    """Convierte un número escrito con separadores colombianos a `Decimal`.

    Args:
        bruto: dígitos con puntos de miles o coma decimal.

    Returns:
        El número, o ``None`` si no se puede leer.
    """
    limpio = bruto.replace("$", "").replace(" ", "").strip()
    if not limpio:
        return None
    if "," in limpio:
        entero, _, decimales = limpio.rpartition(",")
        entero = entero.replace(".", "")
        texto = f"{entero or '0'}.{decimales}"
    elif "." in limpio:
        partes = limpio.split(".")
        if len(partes) > 1 and all(len(parte) == 3 for parte in partes[1:]):
            texto = "".join(partes)
        else:
            texto = limpio
    else:
        texto = limpio
    try:
        valor = Decimal(texto)
    except InvalidOperation:
        return None
    return valor if valor.is_finite() else None


def _palabras_a_numero(palabras: list[str]) -> Decimal | None:
    """Convierte una secuencia de números en palabras a `Decimal`.

    Entiende unidades, decenas, ``mil``, ``millón``, ``palo`` y ``luca``, que son
    los giros que aparecen en la escena («ocho millones», «dos palos»).

    Args:
        palabras: tokens normalizados del texto.

    Returns:
        El número, o ``None`` si no hay ninguno.
    """
    total = 0
    actual = 0
    hubo = False
    for palabra in palabras:
        if palabra == "y":
            continue
        if palabra in _UNIDADES:
            valor = _UNIDADES[palabra]
            if palabra in ("cien", "ciento") and actual:
                actual += 100
            else:
                actual += valor
            hubo = True
        elif palabra in _ESCALAS:
            escala = _ESCALAS[palabra]
            if escala == 1_000:
                total += (actual or 1) * 1_000
            else:
                total += (actual or 1) * escala
            actual = 0
            hubo = True
    if not hubo:
        return None
    return Decimal(total + actual)


def monto_de(texto: str) -> Decimal | None:
    """Reconoce un monto en pesos dicho o escrito de cualquier forma corriente.

    Acepta ``"1.500.000"``, ``"1,5 millones"``, ``"ocho millones"``,
    ``"dos palos"``, ``"20 lucas"`` y ``"500 mil"``.

    Args:
        texto: texto del voluntario.

    Returns:
        El monto en pesos, o ``None`` si no hay uno reconocible.
    """
    limpio = normalizar(texto)
    if not limpio:
        return None
    # Primero la forma con palabras («ocho millones»), que no trae dígitos.
    if not re.search(r"\d", limpio):
        return _palabras_a_numero(limpio.split())
    coincidencia = _RE_DIGITOS.search(limpio)
    if coincidencia is None:
        return _palabras_a_numero(limpio.split())
    valor = _a_decimal(coincidencia.group(1))
    if valor is None:
        return None
    resto = limpio[coincidencia.end() :]
    escala = _RE_ESCALA.search(resto)
    if escala:
        valor *= _ESCALAS[escala.group(1)]
    return valor


def confirmacion_de(texto: str) -> Confirmacion | None:
    """Reconoce una confirmación, una negativa o una petición de cambio.

    Args:
        texto: texto del voluntario.

    Returns:
        ``"si"``, ``"no"`` o ``"cambia"``; ``None`` si no es una confirmación.
    """
    limpio = normalizar(texto)
    if not limpio:
        return None
    if _RE_SI.search(limpio):
        return "si"
    if _RE_NO.search(limpio):
        return "cambia" if "cambia" in limpio or "otra" in limpio else "no"
    return None


def _opcion_por_letra(opciones: tuple[OpcionEscena, ...], letra: str) -> OpcionEscena | None:
    """Devuelve la opción de una letra si existe en esa pregunta."""
    if letra not in LETRAS:
        return None
    posicion = LETRAS.index(letra)
    return opciones[posicion] if posicion < len(opciones) else None


def _opcion_por_monto(opciones: tuple[OpcionEscena, ...], monto: Decimal) -> OpcionEscena | None:
    """Devuelve la primera opción cuyo rango contiene el monto."""
    for opcion in opciones:
        if opcion.contiene(monto):
            return opcion
    return None


def _respuesta(opcion: OpcionEscena, valor: Decimal) -> RespuestaEscena:
    """Arma el contrato de respuesta con el valor efectivo."""
    return RespuestaEscena(
        pregunta=cast(Pregunta, opcion.pregunta),
        letra=opcion.letra,
        opcion_id=opcion.opcion_id,
        texto=opcion.texto,
        valor=valor,
    )


def interpretar(
    texto: str,
    pregunta: Pregunta,
    *,
    monto: Decimal | None = None,
    opciones: dict[str, tuple[OpcionEscena, ...]] | None = None,
) -> Interpretacion:
    """Interpreta una respuesta del voluntario para una de las cuatro preguntas.

    La letra fija el rango. El monto declarado se usa solo si cae dentro de ese
    rango; si no, se usa el valor del rango y se explica. Sin letra, el monto
    busca la tarjeta que lo contiene.

    Args:
        texto: lo que dijo o escribió el voluntario.
        pregunta: una de ``monto``, ``ingresos``, ``gastos`` o ``deudas``.
        monto: monto declarado por la interfaz, si lo hay.
        opciones: tarjetas ya cargadas; por defecto se leen del TOML.

    Returns:
        La respuesta, si el ajuste de monto y el motivo para explicarlo.

    Raises:
        ValueError: si la pregunta no es una de las cuatro de la escena.
    """
    if pregunta not in PREGUNTAS:
        raise ValueError(f"pregunta desconocida: {pregunta}")
    if detectar_pii(texto) is not None:
        return Interpretacion(
            respuesta=None,
            mensaje="No guardo datos personales. Dime solo un rango o una letra A–F.",
        )
    catalogo = opciones if opciones is not None else opciones_escena()
    disponibles = catalogo[pregunta]
    letra = letra_de(texto)
    declarado = monto if monto is not None else monto_de(texto)
    if (
        pregunta == "monto"
        and declarado is not None
        and not (MONTO_MINIMO <= declarado <= MONTO_MAXIMO)
    ):
        return Interpretacion(
            respuesta=None,
            mensaje=(
                "Ese monto está fuera de los límites de la demo (entre $500.000 y $2.000.000.000)."
            ),
        )
    opcion: OpcionEscena | None = None
    if letra is not None:
        opcion = _opcion_por_letra(disponibles, letra)
        if opcion is None:
            return Interpretacion(
                respuesta=None,
                mensaje=f"Esta pregunta solo tiene tarjetas A–{disponibles[-1].letra}.",
            )
    elif declarado is not None:
        opcion = _opcion_por_monto(disponibles, declarado)
        if opcion is None:
            return Interpretacion(
                respuesta=None,
                mensaje="Ese monto no cae en ninguna tarjeta. Elige una letra A–F.",
            )
    if opcion is None:
        return Interpretacion(
            respuesta=None,
            mensaje="No entendí la respuesta. Dime una letra A–F o un monto.",
        )
    if declarado is None:
        return Interpretacion(respuesta=_respuesta(opcion, opcion.valor))
    if opcion.contiene(declarado):
        return Interpretacion(respuesta=_respuesta(opcion, declarado))
    ajustada = _respuesta(opcion, opcion.valor)
    return Interpretacion(
        respuesta=ajustada,
        ajustado=True,
        mensaje=(
            f"El monto que dijiste no cabe en la tarjeta {opcion.letra}; "
            f"uso {opcion.texto.lower()}."
        ),
    )


@dataclass(slots=True)
class CapturaEscena:
    """Máquina de la captura: cuatro respuestas, confirmación y dos intentos.

    No persiste nada: la instancia vive en la petición y el texto se descarta al
    confirmar. A los dos intentos fallidos se marca `seguro` para que la escena
    pase al perfil seguro sin inventar respuestas.
    """

    opciones: dict[str, tuple[OpcionEscena, ...]] = field(default_factory=opciones_escena)
    respuestas: dict[str, RespuestaEscena] = field(default_factory=dict)
    intentos: dict[str, int] = field(default_factory=dict)
    intentos_confirmacion: int = 0
    seguro: bool = False

    def registrar(
        self, pregunta: Pregunta, texto: str, *, monto: Decimal | None = None
    ) -> Interpretacion:
        """Registra la respuesta a una pregunta y cuenta los intentos.

        Args:
            pregunta: pregunta que se está respondiendo.
            texto: lo que dijo o escribió el voluntario.
            monto: monto declarado por la interfaz, si lo hay.

        Returns:
            La interpretación, con `seguro` cuando se agotaron los intentos.
        """
        resultado = interpretar(texto, pregunta, monto=monto, opciones=self.opciones)
        if resultado.respuesta is None:
            self.intentos[pregunta] = self.intentos.get(pregunta, 0) + 1
            if self.intentos[pregunta] >= INTENTOS_MAXIMOS:
                self.seguro = True
            return Interpretacion(
                respuesta=None,
                mensaje=resultado.mensaje,
                seguro=self.seguro,
            )
        self.respuestas[pregunta] = resultado.respuesta
        return resultado

    def confirmar(self, texto: str) -> Literal["confirmado", "repetir", "seguro", "incompleto"]:
        """Aplica la confirmación de Pana antes de avanzar.

        Args:
            texto: lo que dijo o escribió el voluntario.

        Returns:
            ``"confirmado"`` si aceptó las cuatro respuestas, ``"repetir"`` si
            pidió cambiarlas, ``"incompleto"`` si faltan respuestas y
            ``"seguro"`` si se agotaron los intentos.
        """
        if self.seguro:
            return "seguro"
        if len(self.respuestas) < len(PREGUNTAS):
            return "incompleto"
        decision = confirmacion_de(texto)
        if decision == "si":
            return "confirmado"
        if decision in ("no", "cambia"):
            self.intentos_confirmacion = 0
            return "repetir"
        self.intentos_confirmacion += 1
        if self.intentos_confirmacion >= INTENTOS_MAXIMOS:
            self.seguro = True
            return "seguro"
        return "repetir"

    def perfil(
        self,
        *,
        personaje: str = "Voluntario de la sala",
        proposito: str = "Crédito de libre inversión",
        monto_declarado: Decimal | None = None,
    ) -> PerfilEscena:
        """Arma el perfil confirmado desde las cuatro respuestas.

        Args:
            personaje: descripción ficticia del voluntario; sin datos personales.
            proposito: para qué pide el crédito.
            monto_declarado: monto que dijo el voluntario; si falta, el de la
                respuesta de monto.

        Returns:
            El perfil de la escena, ya confirmado.

        Raises:
            ValueError: si faltan respuestas o el monto no es positivo.
        """
        faltan = [pregunta for pregunta in PREGUNTAS if pregunta not in self.respuestas]
        if faltan:
            raise ValueError("faltan respuestas: " + ", ".join(faltan))
        respuestas = tuple(self.respuestas[pregunta] for pregunta in PREGUNTAS)
        calculo = self.respuestas["monto"].valor
        declarado = monto_declarado if monto_declarado is not None else calculo
        if declarado <= 0 or calculo <= 0:
            raise ValueError("el monto del perfil debe ser positivo")
        return PerfilEscena(
            personaje=personaje,
            proposito=proposito,
            monto_declarado=declarado,
            monto_calculo=calculo,
            respuestas=respuestas,
            confirmado=True,
        )
