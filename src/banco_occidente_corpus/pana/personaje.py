"""Dibujo de Pana con Pillow: un joven con buzo gris y pelo peinado hacia arriba.

El dibujo es original y se hace solo con figuras (círculos, arcos y
polígonos), sin archivos de imagen ni logos. Pana se ve de los hombros hacia
arriba, con camiseta blanca y buzo con capucha, como el público al que le
habla: jóvenes que piden su primer crédito. Hay tres expresiones, una por
color del semáforo: ``feliz`` (verde), ``pensativo`` (amarillo) y ``calma``
(rojo, «calma, hay plan»). Se dibuja cuatro veces más grande y luego se
reduce, para que los bordes salgan suaves.
"""

from __future__ import annotations

import io
from collections.abc import Sequence
from typing import Literal, get_args

from PIL import Image, ImageDraw

Expresion = Literal["feliz", "pensativo", "calma"]
"""Las tres caras de Pana."""

EXPRESIONES: tuple[Expresion, ...] = get_args(Expresion)
"""Expresiones disponibles, en el orden verde, amarillo y rojo."""

ESCALA = 4
"""Factor de sobremuestreo para suavizar los bordes."""

PIEL = (238, 196, 160)
PIEL_SOMBRA = (218, 168, 128)
PELO = (107, 70, 44)
PELO_CLARO = (140, 96, 62)
BUZO = (122, 124, 130)
BUZO_OSCURO = (92, 94, 100)
CAMISETA = (246, 245, 240)
TINTA = (43, 42, 39)
VERDE = (47, 93, 80)
CREMA = (244, 236, 216)
MEJILLA = (232, 150, 130)
AMARILLO = (226, 178, 58)

Punto = tuple[float, float]
"""Punto en unidades de 0 a 100."""


def _caja(cx: float, cy: float, rx: float, ry: float, s: int) -> tuple[int, int, int, int]:
    """Devuelve la caja de una elipse con centro y radios en unidades de 100.

    Args:
        cx: centro horizontal (0 a 100).
        cy: centro vertical (0 a 100).
        rx: radio horizontal.
        ry: radio vertical.
        s: píxeles por unidad.

    Returns:
        Tupla ``(x0, y0, x1, y1)`` en píxeles.
    """
    return (round((cx - rx) * s), round((cy - ry) * s), round((cx + rx) * s), round((cy + ry) * s))


def _pts(puntos: Sequence[Punto], s: int) -> list[tuple[int, int]]:
    """Convierte puntos de unidades de 100 a píxeles.

    Args:
        puntos: lista de puntos ``(x, y)`` de 0 a 100.
        s: píxeles por unidad.

    Returns:
        Los mismos puntos en píxeles.
    """
    return [(round(x * s), round(y * s)) for x, y in puntos]


def _cuerpo(d: ImageDraw.ImageDraw, s: int) -> None:
    """Dibuja hombros, buzo con capucha, camiseta y cuello.

    Args:
        d: lienzo de dibujo.
        s: píxeles por unidad.
    """
    # Hombros y buzo.
    d.rounded_rectangle(_caja(50, 99, 37, 19, s), radius=round(14 * s), fill=BUZO)
    # Capucha caída detrás del cuello.
    d.ellipse(_caja(50, 82, 17, 5, s), fill=BUZO_OSCURO)
    # Camiseta en V.
    d.polygon(_pts([(39, 81), (61, 81), (55, 100), (45, 100)], s), fill=CAMISETA)
    # Cuello.
    d.rounded_rectangle(_caja(50, 75, 6.5, 6, s), radius=round(3 * s), fill=PIEL_SOMBRA)
    d.polygon(_pts([(43.5, 79), (56.5, 79), (50, 87)], s), fill=PIEL_SOMBRA)
    # Solapas del buzo abierto y cordones.
    d.polygon(_pts([(32, 83), (41, 81), (47, 100), (36, 100)], s), fill=BUZO_OSCURO)
    d.polygon(_pts([(68, 83), (59, 81), (53, 100), (64, 100)], s), fill=BUZO_OSCURO)
    grosor = max(1, round(1.2 * s))
    for x, dx in ((42, 1), (58, -1)):
        d.line(_pts([(x, 84), (x + dx, 95)], s), fill=CAMISETA, width=grosor)
        d.ellipse(_caja(x + dx, 96, 1.2, 1.2, s), fill=CAMISETA)


def _cabeza(d: ImageDraw.ImageDraw, s: int) -> None:
    """Dibuja orejas, cara y pelo peinado hacia arriba.

    Args:
        d: lienzo de dibujo.
        s: píxeles por unidad.
    """
    for cx in (30, 70):
        d.ellipse(_caja(cx, 51, 4, 5.5, s), fill=PIEL, outline=PIEL_SOMBRA, width=s)
    d.ellipse(_caja(50, 49, 20, 22, s), fill=PIEL)
    # Pelo corto a los lados: la mitad de arriba de una elipse.
    d.chord(_caja(50, 43, 21, 17, s), start=180, end=360, fill=PELO)
    # Copete en puntas, peinado hacia arriba y a la derecha.
    d.polygon(
        _pts(
            [
                (30, 43),
                (31, 34),
                (35, 28),
                (40, 25),
                (41, 19),
                (46, 23),
                (49, 15),
                (54, 21),
                (59, 13),
                (62, 21),
                (68, 17),
                (67, 25),
                (71, 32),
                (70, 43),
            ],
            s,
        ),
        fill=PELO,
    )
    # Brillo del copete.
    d.line(_pts([(47, 24), (52, 19), (57, 17)], s), fill=PELO_CLARO, width=max(1, round(1.6 * s)))
    # Flequillo ladeado: el borde baja hacia la derecha.
    d.polygon(
        _pts([(30, 43), (32, 37), (52, 36), (70, 41), (70, 45), (60, 41), (46, 40), (34, 42)], s),
        fill=PELO,
    )
    # Patillas.
    for x0, x1 in ((30, 33), (67, 70)):
        d.polygon(_pts([(x0, 42), (x1, 42), (x1 - 0.5, 50), (x0 + 0.5, 48)], s), fill=PELO)


def _cejas(d: ImageDraw.ImageDraw, expresion: Expresion, s: int) -> None:
    """Dibuja las cejas según la expresión.

    Args:
        d: lienzo de dibujo.
        expresion: cara que se dibuja.
        s: píxeles por unidad.
    """
    grosor = max(1, round(1.8 * s))
    if expresion == "pensativo":
        izquierda = [(37, 43.5), (45, 44.5)]
        derecha = [(55, 42.5), (63, 40)]
    else:
        izquierda = [(37, 44.5), (41, 43), (45, 44)]
        derecha = [(55, 44), (59, 43), (63, 44.5)]
    d.line(_pts(izquierda, s), fill=PELO, width=grosor, joint="curve")
    d.line(_pts(derecha, s), fill=PELO, width=grosor, joint="curve")


def _ojos(d: ImageDraw.ImageDraw, expresion: Expresion, s: int) -> None:
    """Dibuja los ojos según la expresión.

    Args:
        d: lienzo de dibujo.
        expresion: cara que se dibuja.
        s: píxeles por unidad.
    """
    grosor = max(1, round(1.8 * s))
    for cx in (41, 62.5):
        if expresion == "calma":
            # Ojos cerrados y tranquilos.
            d.arc(_caja(cx, 50, 3.6, 2.8, s), start=200, end=340, fill=TINTA, width=grosor)
        else:
            d.ellipse(_caja(cx, 50.5, 3.2, 3.8, s), fill=TINTA)
            # Brillo; en «pensativo» la mirada se va hacia arriba a la derecha.
            bx, by = (cx + 1.1, 49.1) if expresion == "feliz" else (cx + 1.4, 48.3)
            d.ellipse(_caja(bx, by, 1.1, 1.1, s), fill=CREMA)


def _cara(d: ImageDraw.ImageDraw, expresion: Expresion, s: int) -> None:
    """Dibuja nariz, mejillas y boca según la expresión.

    Args:
        d: lienzo de dibujo.
        expresion: cara que se dibuja.
        s: píxeles por unidad.
    """
    grosor = max(1, round(1.8 * s))
    d.arc(_caja(50, 55.5, 2.4, 2, s), start=20, end=160, fill=PIEL_SOMBRA, width=grosor)
    for cx in (37, 66.5):
        d.ellipse(_caja(cx, 58.5, 3.6, 2.4, s), fill=MEJILLA)
    if expresion == "feliz":
        d.chord(_caja(50, 60.5, 8, 6.5, s), start=0, end=180, fill=TINTA)
        d.chord(_caja(50, 63.7, 4.4, 2.8, s), start=0, end=180, fill=MEJILLA)
    elif expresion == "pensativo":
        d.line(_pts([(45, 64.5), (55, 62.5)], s), fill=TINTA, width=grosor)
    else:
        d.arc(_caja(50, 61, 6, 4, s), start=20, end=160, fill=TINTA, width=grosor)


def _extras(d: ImageDraw.ImageDraw, expresion: Expresion, s: int) -> None:
    """Dibuja los detalles propios de cada expresión.

    Args:
        d: lienzo de dibujo.
        expresion: cara que se dibuja.
        s: píxeles por unidad.
    """
    if expresion == "pensativo":
        # Burbujas de pensamiento a la derecha.
        for cx, cy, r in ((78, 30, 1.8), (84, 23, 2.6), (90, 14, 3.6)):
            d.ellipse(_caja(cx, cy, r, r, s), fill=AMARILLO)
    elif expresion == "calma":
        # Un corazón pequeño: «calma, hay plan».
        d.ellipse(_caja(82, 22, 3.2, 3.2, s), fill=MEJILLA)
        d.ellipse(_caja(87.5, 22, 3.2, 3.2, s), fill=MEJILLA)
        d.polygon(_pts([(79, 23.5), (90.7, 23.5), (84.8, 30)], s), fill=MEJILLA)


def dibujar_pana(expresion: Expresion = "feliz", lado: int = 512) -> Image.Image:
    """Dibuja a Pana de los hombros hacia arriba, con fondo transparente.

    Args:
        expresion: ``feliz``, ``pensativo`` o ``calma``.
        lado: tamaño en píxeles de la imagen cuadrada.

    Returns:
        Imagen RGBA de ``lado`` × ``lado``.

    Raises:
        ValueError: si la expresión no existe o el lado es menor de 32.
    """
    if expresion not in EXPRESIONES:
        raise ValueError(f"expresión desconocida: {expresion!r}")
    if lado < 32:
        raise ValueError("el lado mínimo es 32 píxeles")

    grande = lado * ESCALA
    s = grande // 100
    img = Image.new("RGBA", (grande, grande), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    _cuerpo(d, s)
    _cabeza(d, s)
    _cejas(d, expresion, s)
    _ojos(d, expresion, s)
    _cara(d, expresion, s)
    _extras(d, expresion, s)

    return img.resize((lado, lado), Image.Resampling.LANCZOS)


def insignia(expresion: Expresion = "feliz", lado: int = 640) -> Image.Image:
    """Dibuja a Pana dentro de un círculo crema con aro verde.

    Args:
        expresion: cara de Pana.
        lado: diámetro en píxeles.

    Returns:
        Imagen RGBA redonda, con las esquinas transparentes.
    """
    grande = lado * ESCALA
    borde = max(2, grande // 40)
    img = Image.new("RGBA", (grande, grande), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse((0, 0, grande - 1, grande - 1), fill=CREMA)
    pana = dibujar_pana(expresion, round(grande * 0.9))
    margen = (grande - pana.width) // 2
    capa = Image.new("RGBA", (grande, grande), (0, 0, 0, 0))
    capa.paste(pana, (margen, margen + grande // 12), pana)
    # Solo queda lo que cae dentro del círculo.
    mascara = Image.new("L", (grande, grande), 0)
    ImageDraw.Draw(mascara).ellipse((borde, borde, grande - borde, grande - borde), fill=255)
    img.paste(capa, (0, 0), Image.composite(capa.getchannel("A"), mascara, mascara))
    d.ellipse((0, 0, grande - 1, grande - 1), outline=VERDE, width=borde)
    return img.resize((lado, lado), Image.Resampling.LANCZOS)


def foto_de_perfil(lado: int = 640) -> bytes:
    """Genera la foto de perfil de Pana en PNG, en memoria.

    Fondo crema con Pana feliz en un círculo con aro verde, para el número de
    WhatsApp en Meta y para la web. No escribe nada en disco.

    Args:
        lado: tamaño en píxeles (Meta recomienda al menos 640).

    Returns:
        Bytes del PNG.
    """
    fondo = Image.new("RGB", (lado, lado), CREMA)
    circulo = insignia("feliz", lado)
    fondo.paste(circulo, (0, 0), circulo)
    salida = io.BytesIO()
    fondo.save(salida, format="PNG", optimize=True)
    return salida.getvalue()
