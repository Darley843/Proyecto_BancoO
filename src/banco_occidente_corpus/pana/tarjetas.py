"""Tarjetas con imagen de Pana: diagnóstico y «¿Y si…?».

Cada tarjeta tiene su **texto equivalente** (``texto_diagnostico`` y
``texto_escenario``) con los mismos datos: semáforo, lo que se paga al mes,
tasa con vigencia y fuente, y el aviso. El canal manda siempre el texto; la
imagen es un extra que puede fallar sin dejar la respuesta incompleta.

Reglas de privacidad (Ley 1581 de 2012):

- Los modelos no tienen campos para nombre, teléfono ni documento.
- Los textos libres (producto, pregunta) rechazan secuencias de 7 o más
  dígitos, para que no se cuele un número de teléfono o de cédula.
- Las imágenes se generan en memoria (``bytes``) y esta capa nunca escribe
  en disco; solo ``python -m banco_occidente_corpus.pana`` guarda muestras
  con datos inventados cuando alguien lo pide.
"""

from __future__ import annotations

import io
import re
from decimal import ROUND_HALF_UP, Decimal
from functools import cache
from importlib import resources
from typing import Literal

from PIL import Image, ImageDraw, ImageFont
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .personaje import VERDE, Expresion, insignia

Semaforo = Literal["verde", "amarillo", "rojo"]
"""Colores del semáforo del diagnóstico."""

LADO = 1080
"""Lado de la tarjeta cuadrada en píxeles (WhatsApp la muestra completa)."""

PESO_MAXIMO = 1_000_000
"""La tarjeta debe pesar menos que esto (bytes); WhatsApp acepta 5 MB, así carga rápido."""

AVISO = (
    "Orientativo, no es una aprobación de crédito. Pana es el asistente de un "
    "proyecto académico de la UAO, no del Banco de Occidente."
)
"""Aviso que llevan la imagen y el texto."""

COLOR_SEMAFORO: dict[Semaforo, tuple[int, int, int]] = {
    "verde": (79, 154, 106),
    "amarillo": (226, 178, 58),
    "rojo": (200, 85, 61),
}
"""Color de la luz de cada semáforo."""

FONDO_SEMAFORO: dict[Semaforo, tuple[int, int, int]] = {
    "verde": (238, 247, 238),
    "amarillo": (255, 248, 230),
    "rojo": (252, 236, 230),
}
"""Color de la caja de cada semáforo."""

TITULO_SEMAFORO: dict[Semaforo, str] = {
    "verde": "Verde: va bien",
    "amarillo": "Amarillo: se puede, con cuidado",
    "rojo": "Rojo: calma, hay plan",
}
"""Frase corta de cada semáforo, en el tono de Pana."""

EXPRESION_SEMAFORO: dict[Semaforo, Expresion] = {
    "verde": "feliz",
    "amarillo": "pensativo",
    "rojo": "calma",
}
"""Cara de Pana que acompaña a cada semáforo."""

CREMA = (244, 236, 216)
GUILLOCHE = (232, 221, 194)
TINTA = (43, 42, 39)
GRIS = (91, 87, 79)
GRIS_CLARO = (107, 102, 92)
LINEA = (185, 173, 143)

_DIGITOS_LARGOS = re.compile(r"\d{7,}")

_MONTO_EN_PESOS = re.compile(r"-?\$\s?\d[\d.]*(?:,\d+)?")
"""Montos con signo de pesos («$1.393.023», «$1393023»): no son teléfonos."""


def _sin_numeros_largos(valor: str) -> str:
    """Rechaza textos con 7 o más dígitos seguidos (teléfono o cédula).

    Los montos que empiezan con ``$`` se permiten, porque el motor del
    diagnóstico los escribe en sus motivos («reduce la cuota en $1.393.023»).

    Args:
        valor: texto libre de la tarjeta.

    Returns:
        El mismo texto, sin espacios en los extremos.

    Raises:
        ValueError: si el texto queda vacío sin los espacios de los extremos,
            o si (sin montos en pesos, espacios, puntos ni guiones) tiene una
            secuencia de 7 o más dígitos.
    """
    if not valor.strip():
        raise ValueError("el texto no puede estar vacío")
    sin_montos = _MONTO_EN_PESOS.sub("", valor)
    compacto = re.sub(r"[\s.\-()+]", "", sin_montos)
    if _DIGITOS_LARGOS.search(compacto):
        raise ValueError("la tarjeta no puede llevar números de teléfono ni de documento")
    return valor.strip()


class DatosDiagnostico(BaseModel):
    """Datos de la tarjeta del diagnóstico. Sin datos personales.

    Attributes:
        producto: nombre corto del crédito o del propósito («Portátil»).
        monto: monto pedido en pesos.
        plazo_meses: plazo en meses.
        semaforo: color del diagnóstico.
        cuota_min: límite inferior de lo que se paga al mes.
        cuota_max: límite superior de lo que se paga al mes.
        razon: frase corta que explica el color.
        tasa_mensual_pct: tasa de referencia mensual, en porcentaje.
        tasa_vigencia: corte de la tasa («nov. 2026»).
        tasa_fuente: de dónde sale la tasa («Tablero de tasas»).
        ahorro_mensual: en compra de cartera, cuánto baja la cuota al mes al
            trasladar las deudas; ``None`` en los demás créditos.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    producto: str = Field(min_length=1, max_length=40)
    monto: Decimal = Field(gt=0)
    plazo_meses: int = Field(ge=1, le=360)
    semaforo: Semaforo
    cuota_min: Decimal = Field(gt=0)
    cuota_max: Decimal = Field(gt=0)
    razon: str = Field(min_length=1, max_length=110)
    tasa_mensual_pct: Decimal = Field(gt=0, lt=10)
    tasa_vigencia: str = Field(min_length=1, max_length=30)
    tasa_fuente: str = Field(min_length=1, max_length=40)
    ahorro_mensual: Decimal | None = Field(default=None, gt=0)

    @field_validator("producto", "razon", "tasa_vigencia", "tasa_fuente")
    @classmethod
    def _textos_sin_numeros(cls, valor: str) -> str:
        """Aplica la regla de no llevar teléfonos ni documentos.

        Args:
            valor: texto del campo.

        Returns:
            El texto validado.
        """
        return _sin_numeros_largos(valor)

    @model_validator(mode="after")
    def _rango_ordenado(self) -> DatosDiagnostico:
        """Comprueba que el rango de la cuota esté en orden.

        Returns:
            El modelo validado.

        Raises:
            ValueError: si ``cuota_min`` es mayor que ``cuota_max``.
        """
        if self.cuota_min > self.cuota_max:
            raise ValueError("cuota_min no puede ser mayor que cuota_max")
        return self


class FotoEscenario(BaseModel):
    """Un lado de la comparación «¿Y si…?».

    Attributes:
        plazo_meses: plazo del escenario.
        semaforo: color del escenario.
        cuota_min: límite inferior de lo que se paga al mes.
        cuota_max: límite superior de lo que se paga al mes.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    plazo_meses: int = Field(ge=1, le=360)
    semaforo: Semaforo
    cuota_min: Decimal = Field(gt=0)
    cuota_max: Decimal = Field(gt=0)

    @model_validator(mode="after")
    def _rango_ordenado(self) -> FotoEscenario:
        """Comprueba que el rango de la cuota esté en orden.

        Returns:
            El modelo validado.

        Raises:
            ValueError: si ``cuota_min`` es mayor que ``cuota_max``.
        """
        if self.cuota_min > self.cuota_max:
            raise ValueError("cuota_min no puede ser mayor que cuota_max")
        return self


class DatosEscenario(BaseModel):
    """Datos de la tarjeta «¿Y si…?». Sin datos personales.

    Attributes:
        pregunta: la pregunta tal como se muestra («¿Y si lo pagas en 36 meses?»).
        antes: el diagnóstico original.
        despues: el escenario nuevo.
        nota: frase corta sobre lo que cambia.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    pregunta: str = Field(min_length=1, max_length=60)
    antes: FotoEscenario
    despues: FotoEscenario
    nota: str = Field(min_length=1, max_length=120)

    @field_validator("pregunta", "nota")
    @classmethod
    def _textos_sin_numeros(cls, valor: str) -> str:
        """Aplica la regla de no llevar teléfonos ni documentos.

        Args:
            valor: texto del campo.

        Returns:
            El texto validado.
        """
        return _sin_numeros_largos(valor)


class TasaCaptacion(BaseModel):
    """Una tasa de ahorro o CDT para la tarjeta de ahorro.

    Attributes:
        etiqueta: nombre corto del producto o plazo («CDT a 90 días»).
        ea_min_pct: tasa efectiva anual mínima, en porcentaje.
        ea_max_pct: tasa efectiva anual máxima, en porcentaje.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    etiqueta: str = Field(min_length=1, max_length=30)
    ea_min_pct: Decimal = Field(ge=0, lt=100)
    ea_max_pct: Decimal = Field(ge=0, lt=100)

    @field_validator("etiqueta")
    @classmethod
    def _etiqueta_sin_numeros(cls, valor: str) -> str:
        """Aplica la regla de no llevar teléfonos ni documentos.

        Args:
            valor: texto del campo.

        Returns:
            El texto validado.
        """
        return _sin_numeros_largos(valor)

    @model_validator(mode="after")
    def _rango_ordenado(self) -> TasaCaptacion:
        """Comprueba que el rango de la tasa esté en orden.

        Returns:
            El modelo validado.

        Raises:
            ValueError: si ``ea_min_pct`` es mayor que ``ea_max_pct``.
        """
        if self.ea_min_pct > self.ea_max_pct:
            raise ValueError("ea_min_pct no puede ser mayor que ea_max_pct")
        return self


class DatosAhorro(BaseModel):
    """Datos de la tarjeta de ahorro: sin semáforo y sin datos personales.

    Attributes:
        capacidad_ahorro: lo que queda libre al mes; cero o negativo si no
            hay margen.
        razon: frase corta del motor («El ahorro no tiene semáforo…»).
        tasas: hasta tres tasas de ahorro o CDT de referencia.
        tasa_vigencia: corte de las tasas («nov. 2026»).
        tasa_fuente: de dónde salen las tasas («Tablero de tasas»).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    capacidad_ahorro: Decimal
    razon: str = Field(min_length=1, max_length=110)
    tasas: list[TasaCaptacion] = Field(default_factory=list, max_length=3)
    tasa_vigencia: str = Field(min_length=1, max_length=30)
    tasa_fuente: str = Field(min_length=1, max_length=40)

    @field_validator("razon", "tasa_vigencia", "tasa_fuente")
    @classmethod
    def _textos_sin_numeros(cls, valor: str) -> str:
        """Aplica la regla de no llevar teléfonos ni documentos.

        Args:
            valor: texto del campo.

        Returns:
            El texto validado.
        """
        return _sin_numeros_largos(valor)


class DatosNoAplica(BaseModel):
    """Datos de la tarjeta cuando el producto no se puede simular.

    Por ejemplo, la libranza para una persona independiente: no hay cuota ni
    semáforo, solo la explicación y la alternativa.

    Attributes:
        producto: nombre corto del producto («Libranza»).
        razon: por qué no aplica.
        alternativa: lo que sí se puede hacer.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    producto: str = Field(min_length=1, max_length=40)
    razon: str = Field(min_length=1, max_length=140)
    alternativa: str = Field(min_length=1, max_length=110)

    @field_validator("producto", "razon", "alternativa")
    @classmethod
    def _textos_sin_numeros(cls, valor: str) -> str:
        """Aplica la regla de no llevar teléfonos ni documentos.

        Args:
            valor: texto del campo.

        Returns:
            El texto validado.
        """
        return _sin_numeros_largos(valor)


# --- formato --------------------------------------------------------------


def pesos(valor: Decimal) -> str:
    """Formatea pesos colombianos con punto de miles y sin decimales.

    Args:
        valor: cantidad en pesos.

    Returns:
        Texto como ``$150.000``.
    """
    entero = int(valor.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    return "$" + f"{entero:,}".replace(",", ".")


def rango_pesos(minimo: Decimal, maximo: Decimal) -> str:
    """Formatea un rango de pesos; si los extremos coinciden, da un solo valor.

    Args:
        minimo: límite inferior.
        maximo: límite superior.

    Returns:
        Texto como ``$150.000 – $170.000``.
    """
    if pesos(minimo) == pesos(maximo):
        return pesos(minimo)
    return f"{pesos(minimo)} – {pesos(maximo)}"


def porcentaje(valor: Decimal) -> str:
    """Formatea un porcentaje con coma decimal y hasta dos decimales.

    Args:
        valor: porcentaje (``1.9`` es 1,9 %).

    Returns:
        Texto como ``1,9 %``.
    """
    texto = f"{valor.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP):f}".rstrip("0").rstrip(".")
    return texto.replace(".", ",") + " %"


def monto_corto(valor: Decimal) -> str:
    """Formatea un monto grande en millones cuando es redondo.

    Args:
        valor: monto en pesos.

    Returns:
        ``$3 millones``, ``$2,5 millones`` o el valor completo si es menor
        de un millón.
    """
    if valor < 1_000_000:
        return pesos(valor)
    millones = (valor / Decimal(1_000_000)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    texto = f"{millones:f}".rstrip("0").rstrip(".").replace(".", ",")
    return f"${texto} millones" if texto != "1" else "$1 millón"


# --- texto equivalente ----------------------------------------------------


def texto_diagnostico(datos: DatosDiagnostico) -> str:
    """Escribe el texto que acompaña a la tarjeta del diagnóstico.

    Lleva los mismos datos que la imagen, para que la respuesta esté
    completa aunque la imagen no llegue.

    Args:
        datos: datos validados del diagnóstico.

    Returns:
        Texto listo para WhatsApp (negritas con asteriscos).
    """
    return (
        f"*{TITULO_SEMAFORO[datos.semaforo]}*\n"
        f"{datos.producto} · {monto_corto(datos.monto)} a {datos.plazo_meses} meses\n"
        f"{datos.razon}\n\n"
        f"Lo que pagarías al mes: *{rango_pesos(datos.cuota_min, datos.cuota_max)}*\n"
        f"Tasa de referencia: {porcentaje(datos.tasa_mensual_pct)} mensual "
        f"({datos.tasa_fuente}, {datos.tasa_vigencia})\n"
        + (
            f"Ahorro mensual estimado: *{pesos(datos.ahorro_mensual)}*\n"
            if datos.ahorro_mensual is not None
            else ""
        )
        + f"\n_{AVISO}_"
    )


def texto_escenario(datos: DatosEscenario) -> str:
    """Escribe el texto que acompaña a la tarjeta «¿Y si…?».

    Args:
        datos: datos validados del escenario.

    Returns:
        Texto listo para WhatsApp con los dos lados de la comparación.
    """
    a, b = datos.antes, datos.despues
    return (
        f"*{datos.pregunta}*\n"
        f"Hoy, {a.plazo_meses} meses: {rango_pesos(a.cuota_min, a.cuota_max)} al mes "
        f"({a.semaforo})\n"
        f"Escenario, {b.plazo_meses} meses: {rango_pesos(b.cuota_min, b.cuota_max)} al mes "
        f"({b.semaforo})\n"
        f"{datos.nota}\n\n"
        f"_{AVISO}_"
    )


def _rango_ea(tasa: TasaCaptacion) -> str:
    """Formatea el rango efectivo anual de una tasa de captación.

    Args:
        tasa: tasa de ahorro o CDT.

    Returns:
        Texto como ``8,5 % E.A.`` o ``8 % – 9,2 % E.A.``.
    """
    if tasa.ea_min_pct == tasa.ea_max_pct:
        return f"{porcentaje(tasa.ea_min_pct)} E.A."
    return f"{porcentaje(tasa.ea_min_pct)} – {porcentaje(tasa.ea_max_pct)} E.A."


def _frase_capacidad(capacidad: Decimal) -> str:
    """Resume la capacidad de ahorro en una frase corta.

    Args:
        capacidad: lo que queda libre al mes.

    Returns:
        «Puedes ahorrar hasta $X al mes» o que hoy no queda margen.
    """
    if capacidad > 0:
        return f"Puedes ahorrar hasta {pesos(capacidad)} al mes"
    return "Hoy no queda margen para ahorrar"


def texto_ahorro(datos: DatosAhorro) -> str:
    """Escribe el texto que acompaña a la tarjeta de ahorro.

    Args:
        datos: datos validados del ahorro.

    Returns:
        Texto listo para WhatsApp con la capacidad, las tasas y el aviso.
    """
    lineas = [f"*{_frase_capacidad(datos.capacidad_ahorro)}*", datos.razon, ""]
    lineas += [f"{tasa.etiqueta}: {_rango_ea(tasa)}" for tasa in datos.tasas]
    lineas.append(f"Tasas: {datos.tasa_fuente}, {datos.tasa_vigencia}")
    return "\n".join(lineas) + f"\n\n_{AVISO}_"


def texto_no_aplica(datos: DatosNoAplica) -> str:
    """Escribe el texto que acompaña a la tarjeta de «no aplica».

    Args:
        datos: datos validados.

    Returns:
        Texto listo para WhatsApp con la razón, la alternativa y el aviso.
    """
    return (
        f"*{datos.producto}: esta opción no aplica*\n"
        f"{datos.razon}\n\n"
        f"Lo que sí puedes hacer: {datos.alternativa}\n\n"
        f"_{AVISO}_"
    )


# --- dibujo ---------------------------------------------------------------


@cache
def _fuente(tamano: int, negrita: bool = False) -> ImageFont.FreeTypeFont:
    """Carga DejaVu Sans desde el paquete, igual en Windows y en Linux.

    Args:
        tamano: tamaño en píxeles.
        negrita: ``True`` para DejaVu Sans Bold.

    Returns:
        La fuente cargada (se guarda en caché por tamaño).
    """
    nombre = "DejaVuSans-Bold.ttf" if negrita else "DejaVuSans.ttf"
    datos = resources.files(__package__).joinpath("fuentes", nombre).read_bytes()
    return ImageFont.truetype(io.BytesIO(datos), tamano)


def _envolver(texto: str, fuente: ImageFont.FreeTypeFont, ancho: int) -> list[str]:
    """Parte un texto en líneas que caben en un ancho.

    Args:
        texto: texto a partir.
        fuente: fuente con la que se mide.
        ancho: ancho máximo en píxeles.

    Returns:
        Lista de líneas.
    """
    lineas: list[str] = []
    actual = ""
    for palabra in texto.split():
        prueba = f"{actual} {palabra}".strip()
        if fuente.getlength(prueba) <= ancho or not actual:
            actual = prueba
        else:
            lineas.append(actual)
            actual = palabra
    if actual:
        lineas.append(actual)
    return lineas


def _parrafo(
    d: ImageDraw.ImageDraw,
    xy: tuple[int, int],
    texto: str,
    fuente: ImageFont.FreeTypeFont,
    ancho: int,
    color: tuple[int, int, int],
    interlineado: float = 1.3,
) -> int:
    """Escribe un párrafo envuelto y devuelve la altura que ocupó.

    Args:
        d: lienzo de dibujo.
        xy: esquina superior izquierda.
        texto: texto a escribir.
        fuente: fuente.
        ancho: ancho máximo.
        color: color del texto.
        interlineado: separación entre líneas, en múltiplos del tamaño.

    Returns:
        Altura usada en píxeles.
    """
    x, y = xy
    paso = round(fuente.size * interlineado)
    lineas = _envolver(texto, fuente, ancho)
    for i, linea in enumerate(lineas):
        d.text((x, y + i * paso), linea, font=fuente, fill=color)
    return paso * len(lineas)


def _lienzo() -> tuple[Image.Image, ImageDraw.ImageDraw]:
    """Crea el fondo común: crema, guilloché suave y marco verde.

    Returns:
        La imagen y su lienzo de dibujo.
    """
    img = Image.new("RGB", (LADO, LADO), CREMA)
    d = ImageDraw.Draw(img)
    # Guilloché: círculos concéntricos desde la esquina superior derecha.
    for r in range(40, 1500, 22):
        d.ellipse((LADO - r, -r, LADO + r, r), outline=GUILLOCHE, width=1)
    d.rounded_rectangle((36, 36, LADO - 36, LADO - 36), radius=28, outline=VERDE, width=4)
    return img, d


def _encabezado(
    img: Image.Image, d: ImageDraw.ImageDraw, rotulo: str, expresion: Expresion
) -> None:
    """Dibuja el rótulo superior y la cara de Pana.

    Args:
        img: imagen de la tarjeta.
        d: lienzo de dibujo.
        rotulo: texto del rótulo («SUCURSAL 1965 · PANA»).
        expresion: cara de Pana.
    """
    d.text((92, 118), rotulo.upper(), font=_fuente(30, negrita=True), fill=VERDE)
    cara = insignia(expresion, 160)
    img.paste(cara, (LADO - 92 - 160, 70), cara)


def _a_png(img: Image.Image) -> bytes:
    """Convierte la imagen a PNG en memoria y controla el peso.

    Args:
        img: imagen terminada.

    Returns:
        Bytes del PNG.

    Raises:
        RuntimeError: si el PNG llega a ``PESO_MAXIMO`` o lo supera.
    """
    salida = io.BytesIO()
    img.save(salida, format="PNG", optimize=True)
    datos = salida.getvalue()
    if len(datos) >= PESO_MAXIMO:
        raise RuntimeError("la tarjeta pesa 1 MB o más")
    return datos


def _tabla(d: ImageDraw.ImageDraw, filas: list[tuple[str, str]], y: int, paso: int) -> None:
    """Dibuja filas «etiqueta … valor» con una línea debajo de cada una.

    Args:
        d: lienzo de dibujo.
        filas: pares ``(etiqueta, valor)``.
        y: altura de la primera fila.
        paso: separación entre filas en píxeles.
    """
    fuente_valor = _fuente(30, negrita=True)
    for etiqueta, valor in filas:
        d.text((92, y), etiqueta, font=_fuente(30), fill=TINTA)
        d.text((LADO - 92 - fuente_valor.getlength(valor), y), valor, font=fuente_valor, fill=TINTA)
        y += paso
        d.line((92, y - 14, LADO - 92, y - 14), fill=LINEA, width=1)


def _caja_mensaje(
    d: ImageDraw.ImageDraw,
    titulo: str,
    detalle: str,
    fondo: tuple[int, int, int],
    borde: tuple[int, int, int],
) -> None:
    """Dibuja la caja central con un título y una frase, sin luz de semáforo.

    Args:
        d: lienzo de dibujo.
        titulo: frase principal.
        detalle: frase de apoyo.
        fondo: color de relleno.
        borde: color del borde.
    """
    caja = (92, 430, LADO - 92, 660)
    d.rounded_rectangle(caja, radius=22, fill=fondo, outline=borde, width=3)
    ancho = caja[2] - caja[0] - 76
    alto = _parrafo(d, (130, 466), titulo, _fuente(40, True), ancho, TINTA, 1.2)
    _parrafo(d, (130, 476 + alto), detalle, _fuente(28), ancho, GRIS, 1.3)


def tarjeta_diagnostico(datos: DatosDiagnostico) -> bytes:
    """Dibuja la tarjeta del diagnóstico en PNG, en memoria.

    Args:
        datos: datos validados del diagnóstico.

    Returns:
        Bytes del PNG de 1080 × 1080.
    """
    img, d = _lienzo()
    _encabezado(img, d, "Sucursal 1965 · Pana", EXPRESION_SEMAFORO[datos.semaforo])
    ancho = LADO - 2 * 92

    d.text((92, 270), "Tu diagnóstico", font=_fuente(64, negrita=True), fill=TINTA)
    subtitulo = f"{datos.producto} · {monto_corto(datos.monto)} a {datos.plazo_meses} meses"
    d.text((92, 356), subtitulo, font=_fuente(32), fill=GRIS)

    # Caja del semáforo.
    color = COLOR_SEMAFORO[datos.semaforo]
    caja = (92, 430, LADO - 92, 660)
    d.rounded_rectangle(
        caja, radius=22, fill=FONDO_SEMAFORO[datos.semaforo], outline=color, width=3
    )
    d.ellipse((130, 485, 250, 605), fill=color)
    texto_x = 285
    ancho_caja = caja[2] - texto_x - 30
    alto = _parrafo(
        d,
        (texto_x, 470),
        TITULO_SEMAFORO[datos.semaforo],
        _fuente(40, True),
        ancho_caja,
        TINTA,
        1.2,
    )
    _parrafo(d, (texto_x, 478 + alto), datos.razon, _fuente(28), ancho_caja, GRIS, 1.3)

    # Tabla de cifras.
    filas = [
        ("Lo que pagarías al mes", rango_pesos(datos.cuota_min, datos.cuota_max)),
        ("Tasa de referencia", f"{porcentaje(datos.tasa_mensual_pct)} mensual"),
        ("Fuente de la tasa", f"{datos.tasa_fuente}, {datos.tasa_vigencia}"),
    ]
    if datos.ahorro_mensual is not None:
        filas.append(("Ahorro mensual estimado", pesos(datos.ahorro_mensual)))
    _tabla(d, filas, 690, 62 if len(filas) <= 3 else 56)

    _parrafo(d, (92, LADO - 150), AVISO, _fuente(23), ancho, GRIS_CLARO, 1.35)
    return _a_png(img)


def _lado_escenario(
    d: ImageDraw.ImageDraw, caja: tuple[int, int, int, int], titulo: str, foto: FotoEscenario
) -> None:
    """Dibuja un lado de la comparación «¿Y si…?».

    Args:
        d: lienzo de dibujo.
        caja: rectángulo del lado.
        titulo: rótulo («Hoy · 24 meses»).
        foto: datos de ese lado.
    """
    color = COLOR_SEMAFORO[foto.semaforo]
    d.rounded_rectangle(caja, radius=22, fill=FONDO_SEMAFORO[foto.semaforo], outline=color, width=3)
    x, y = caja[0] + 32, caja[1] + 32
    d.text((x, y), titulo.upper(), font=_fuente(26, negrita=True), fill=GRIS)
    d.ellipse((x, y + 60, x + 70, y + 130), fill=color)
    d.text((x + 92, y + 76), foto.semaforo.capitalize(), font=_fuente(32, negrita=True), fill=TINTA)
    d.text((x, y + 170), "Al mes", font=_fuente(28), fill=TINTA)
    ancho = caja[2] - caja[0] - 64
    _parrafo(
        d,
        (x, y + 215),
        rango_pesos(foto.cuota_min, foto.cuota_max),
        _fuente(34, True),
        ancho,
        TINTA,
        1.25,
    )


def tarjeta_escenario(datos: DatosEscenario) -> bytes:
    """Dibuja la tarjeta «¿Y si…?» con los dos escenarios lado a lado.

    Args:
        datos: datos validados del escenario.

    Returns:
        Bytes del PNG de 1080 × 1080.
    """
    img, d = _lienzo()
    _encabezado(img, d, "Sucursal 1965 · ¿Y si…?", EXPRESION_SEMAFORO[datos.despues.semaforo])
    ancho = LADO - 2 * 92

    alto = _parrafo(d, (92, 270), datos.pregunta, _fuente(52, negrita=True), ancho, TINTA, 1.2)
    arriba = max(380, 290 + alto)
    mitad = LADO // 2
    _lado_escenario(
        d,
        (92, arriba, mitad - 40, arriba + 380),
        f"Hoy · {datos.antes.plazo_meses} meses",
        datos.antes,
    )
    _lado_escenario(
        d,
        (mitad + 40, arriba, LADO - 92, arriba + 380),
        f"Escenario · {datos.despues.plazo_meses} meses",
        datos.despues,
    )
    flecha_y = arriba + 190
    d.line((mitad - 22, flecha_y, mitad + 22, flecha_y), fill=VERDE, width=6)
    d.polygon(
        [(mitad + 26, flecha_y), (mitad + 8, flecha_y - 16), (mitad + 8, flecha_y + 16)],
        fill=VERDE,
    )
    _parrafo(d, (92, arriba + 420), datos.nota, _fuente(30), ancho, TINTA, 1.35)
    _parrafo(d, (92, LADO - 150), AVISO, _fuente(23), ancho, GRIS_CLARO, 1.35)
    return _a_png(img)


FONDO_NEUTRO = (234, 242, 238)
"""Relleno de las tarjetas sin semáforo (ahorro y «no aplica»)."""


def tarjeta_ahorro(datos: DatosAhorro) -> bytes:
    """Dibuja la tarjeta de ahorro, sin semáforo, en PNG y en memoria.

    Args:
        datos: datos validados del ahorro.

    Returns:
        Bytes del PNG de 1080 × 1080.
    """
    img, d = _lienzo()
    expresion: Expresion = "feliz" if datos.capacidad_ahorro > 0 else "calma"
    _encabezado(img, d, "Sucursal 1965 · Pana", expresion)
    d.text((92, 270), "Tu plan de ahorro", font=_fuente(64, negrita=True), fill=TINTA)
    d.text((92, 356), "El ahorro no lleva semáforo", font=_fuente(32), fill=GRIS)
    _caja_mensaje(d, _frase_capacidad(datos.capacidad_ahorro), datos.razon, FONDO_NEUTRO, VERDE)
    filas = [(tasa.etiqueta, _rango_ea(tasa)) for tasa in datos.tasas]
    filas.append(("Fuente de las tasas", f"{datos.tasa_fuente}, {datos.tasa_vigencia}"))
    _tabla(d, filas, 690, 62 if len(filas) <= 3 else 56)
    _parrafo(d, (92, LADO - 150), AVISO, _fuente(23), LADO - 2 * 92, GRIS_CLARO, 1.35)
    return _a_png(img)


def tarjeta_no_aplica(datos: DatosNoAplica) -> bytes:
    """Dibuja la tarjeta de un producto que no se puede simular.

    Args:
        datos: datos validados.

    Returns:
        Bytes del PNG de 1080 × 1080.
    """
    img, d = _lienzo()
    _encabezado(img, d, "Sucursal 1965 · Pana", "calma")
    ancho = LADO - 2 * 92
    d.text((92, 270), datos.producto, font=_fuente(64, negrita=True), fill=TINTA)
    d.text((92, 356), "Esta opción no aplica para ti", font=_fuente(32), fill=GRIS)
    _caja_mensaje(d, "Calma, hay otro camino", datos.razon, (241, 238, 232), GRIS_CLARO)
    d.text((92, 700), "Lo que sí puedes hacer", font=_fuente(30, negrita=True), fill=VERDE)
    _parrafo(d, (92, 750), datos.alternativa, _fuente(32), ancho, TINTA, 1.35)
    _parrafo(d, (92, LADO - 150), AVISO, _fuente(23), ancho, GRIS_CLARO, 1.35)
    return _a_png(img)
