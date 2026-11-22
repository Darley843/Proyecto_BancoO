"""``python -m banco_occidente_corpus.voz``: muestras de las voces de la escena.

Genera ``data/modelos/voz/muestras/<personaje>.ogg`` con una frase corta por
personaje, para escucharlas y comprobar que se distinguen antes de la demo. No
envía nada a ningún servicio. Equivale a ``make voces-prueba``.

``python -m banco_occidente_corpus.voz descargar`` (``make voz-modelo``) baja
una sola vez los modelos que nombra ``config/voz.toml``, sin repetirlos, con
el User-Agent y el header ``From`` del proyecto (ver ``voz/descarga.py``).
"""

from __future__ import annotations

import sys

from ..config import PROJECT_ROOT, load_config
from .descarga import ErrorDescarga, descargar_modelos
from .presentacion import TEXTO_PRESENTACION
from .sintesis import PERSONAJES, VozNoDisponible, cargar_configuracion_voz, crear_voz

#: Frase de prueba de cada personaje (todo inventado, sin datos de nadie).
MUESTRAS: dict[str, str] = {
    "pana": TEXTO_PRESENTACION,
    "don_gota": (
        "Tranquilo, mijo, yo le presto hoy mismo, sin papeles. "
        "Son quinientos mil y me paga el veinte por ciento cada mes."
    ),
    "joven": "Necesito plata para un computador y no sé si me alcanza la cuota.",
    "agente_joven": "Mi cliente puede pagar hasta ciento ochenta mil pesos al mes.",
    "agente_banco": "Podemos ofrecer doce meses con una tasa efectiva anual publicada.",
    "auditor": "Revisé las cifras: la cuota coincide con el simulador. Semáforo verde.",
}


def descargar() -> int:
    """Descarga los modelos de ``config/voz.toml`` que aún no están.

    Returns:
        0 si quedaron todos; 1 si alguno no se pudo bajar.
    """
    config = cargar_configuracion_voz()
    sitio = load_config().site
    carpeta = config.ruta_modelo("x", PROJECT_ROOT).parent
    try:
        bajados = descargar_modelos(
            config.modelos(),
            carpeta,
            user_agent=sitio.user_agent,
            remitente=sitio.contact,
        )
    except (ErrorDescarga, ValueError) as error:
        print(f"No se pudo descargar: {error}")
        return 1
    if bajados:
        print("Descargadas:", ", ".join(bajados))
    else:
        print("Todas las voces ya estaban en", carpeta.relative_to(PROJECT_ROOT))
    return 0


def main(argumentos: list[str] | None = None) -> int:
    """Escribe un OGG por personaje y dice cuáles faltan, o descarga modelos.

    Args:
        argumentos: ``["descargar"]`` para bajar los modelos; vacío para muestras.

    Returns:
        0 si todo salió bien; 1 si la voz está apagada o falta algún modelo.
    """
    pedido = sys.argv[1:] if argumentos is None else argumentos
    if pedido[:1] == ["descargar"]:
        return descargar()
    config = cargar_configuracion_voz()
    voz = crear_voz(config, PROJECT_ROOT)
    if voz is None:
        print("Las voces están apagadas en config/voz.toml (activa = false).")
        return 1
    carpeta = config.ruta_modelo("x", PROJECT_ROOT).parent / "muestras"
    carpeta.mkdir(parents=True, exist_ok=True)
    faltan = 0
    for personaje in PERSONAJES:
        modelo = config.personajes[personaje].modelo
        if config.personajes[personaje].motor == "navegador":
            print(f"  {personaje:<13} usa la voz del navegador: pruébala en /voces.html")
            continue
        try:
            audio = voz.audio(MUESTRAS[personaje], personaje)
        except VozNoDisponible as error:
            print(f"  {personaje:<13} sin voz ({modelo}): {error}")
            faltan += 1
            continue
        destino = carpeta / f"{personaje}.ogg"
        destino.write_bytes(audio)
        print(f"  {personaje:<13} {destino.relative_to(PROJECT_ROOT)} ({modelo})")
    return 1 if faltan else 0


if __name__ == "__main__":
    sys.exit(main())
