"""Voces de la escena: texto a voz local con Piper, una voz por personaje.

La voz se genera en el computador, sin internet: el texto nunca sale a un
servicio externo. Los modelos de Piper se descargan una sola vez con
``make voz-modelo`` en ``data/modelos/voz/`` (no se versiona). Si falta el
modelo de un personaje o Piper falla, `VozEscena.audio` lanza `VozNoDisponible`
y la web usa la voz del navegador para ese personaje.

Cada personaje del contrato del turno de escena (``pana``, ``don_gota``,
``joven``, ``agente_joven``, ``agente_banco``, ``auditor``) tiene su modelo,
hablante, velocidad y tono en ``config/voz.toml``, para que el público los
distinga sin mirar la pantalla. El tono se cambia remuestreando el audio y la
velocidad se compensa al sintetizar, así que un tono grave no habla más lento.

El audio sale como OGG con códec Opus (el de las notas de voz, que los
navegadores reproducen). Opus solo acepta 8, 12, 16, 24 o 48 kHz, así que el
audio se remuestrea a 48 kHz cuando hace falta.

Las pruebas viven en ``test/test_voz.py`` con un sintetizador falso, para no
depender de los modelos.
"""

from __future__ import annotations

import io
import logging
import threading
import tomllib
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import soundfile

from ..config import PROJECT_ROOT

LOGGER = logging.getLogger(__name__)

RUTA_CONFIG_VOZ: Path = PROJECT_ROOT / "config" / "voz.toml"
#: Personajes del contrato del turno de escena, en el orden de la escena.
PERSONAJES: tuple[str, ...] = (
    "pana",
    "don_gota",
    "joven",
    "agente_joven",
    "agente_banco",
    "auditor",
)
#: Frecuencias que acepta Opus.
FRECUENCIAS_OPUS: frozenset[int] = frozenset({8000, 12000, 16000, 24000, 48000})
#: Frecuencia a la que se remuestrea si la voz usa otra.
FRECUENCIA_DESTINO = 48000
#: Tope de peso de un audio (el de WhatsApp: 16 MB).
PESO_MAXIMO_AUDIO = 16 * 1024 * 1024
#: Audios que se guardan en memoria; el más viejo sale primero.
MAXIMO_EN_MEMORIA = 64
#: Rango permitido del tono, para no volver irreconocible la voz.
TONO_MINIMO, TONO_MAXIMO = 0.7, 1.4
#: Motores de voz que puede usar un personaje.
MOTORES: tuple[str, ...] = ("piper", "navegador")
#: Rangos que acepta ``speechSynthesis`` para tono y velocidad.
TONO_NAVEGADOR_MAXIMO = 2.0
VELOCIDAD_NAVEGADOR_MINIMA, VELOCIDAD_NAVEGADOR_MAXIMA = 0.1, 10.0


class VozNoDisponible(RuntimeError):
    """No hay voz: falta el modelo, Piper falló o la voz está apagada."""


@dataclass(frozen=True)
class VozPersonaje:
    """Cómo suena un personaje.

    Attributes:
        modelo: nombre de la voz de Piper, por ejemplo ``es_MX-ald-medium``.
        hablante: número de hablante en voces con varios; ``None`` si tiene uno.
        velocidad: ``length_scale`` de Piper (más de 1 habla más lento).
        tono: factor de tono (menos de 1 más grave, más de 1 más agudo).
        motor: ``piper`` o ``navegador``.
        navegador: parte del nombre de la voz del navegador, por ejemplo
            ``Salome``; vacío para la primera voz en español.
        tono_navegador: ``pitch`` de ``speechSynthesis`` (0 a 2).
        velocidad_navegador: ``rate`` de ``speechSynthesis`` (0,1 a 10).
    """

    modelo: str
    hablante: int | None = None
    velocidad: float = 1.0
    tono: float = 1.0
    motor: str = "piper"
    navegador: str = ""
    tono_navegador: float = 1.0
    velocidad_navegador: float = 1.0


#: Voz de respaldo si el TOML no trae personajes.
VOZ_POR_DEFECTO = VozPersonaje(modelo="es_MX-ald-medium")


@dataclass(frozen=True)
class ConfiguracionVoz:
    """Valores de ``config/voz.toml``."""

    activa: bool = True
    carpeta: Path = Path("data/modelos/voz")
    largo_maximo: int = 900
    personajes: Mapping[str, VozPersonaje] = field(
        default_factory=lambda: dict.fromkeys(PERSONAJES, VOZ_POR_DEFECTO)
    )

    def ruta_modelo(self, modelo: str, raiz: Path = PROJECT_ROOT) -> Path:
        """Devuelve la ruta del ``.onnx`` de una voz.

        Args:
            modelo: nombre de la voz de Piper.
            raiz: raíz del proyecto, para resolver una carpeta relativa.

        Returns:
            ``<raiz>/<carpeta>/<modelo>.onnx``.
        """
        carpeta = self.carpeta if self.carpeta.is_absolute() else raiz / self.carpeta
        return carpeta / f"{modelo}.onnx"

    def modelos(self) -> tuple[str, ...]:
        """Devuelve los modelos de Piper distintos que se usan, ordenados.

        Los personajes con ``motor = "navegador"`` no cuentan: no hay que
        descargar nada para ellos.
        """
        return tuple(
            sorted({voz.modelo for voz in self.personajes.values() if voz.motor == "piper"})
        )


def _voz_personaje(nombre: str, datos: Mapping[str, Any]) -> VozPersonaje:
    """Valida y arma la voz de un personaje del TOML."""
    hablante = datos.get("hablante")
    voz = VozPersonaje(
        modelo=str(datos.get("modelo", VOZ_POR_DEFECTO.modelo)),
        hablante=None if hablante is None else int(hablante),
        velocidad=float(datos.get("velocidad", 1.0)),
        tono=float(datos.get("tono", 1.0)),
        motor=str(datos.get("motor", "piper")),
        navegador=str(datos.get("navegador", "")),
        tono_navegador=float(datos.get("tono_navegador", 1.0)),
        velocidad_navegador=float(datos.get("velocidad_navegador", 1.0)),
    )
    if voz.motor not in MOTORES:
        raise ValueError(f"voz.personajes.{nombre}.motor debe ser uno de {MOTORES}")
    if not 0 <= voz.tono_navegador <= TONO_NAVEGADOR_MAXIMO:
        raise ValueError(f"voz.personajes.{nombre}.tono_navegador debe estar entre 0 y 2")
    if not VELOCIDAD_NAVEGADOR_MINIMA <= voz.velocidad_navegador <= VELOCIDAD_NAVEGADOR_MAXIMA:
        raise ValueError(f"voz.personajes.{nombre}.velocidad_navegador debe estar entre 0.1 y 10")
    if voz.velocidad <= 0:
        raise ValueError(f"voz.personajes.{nombre}.velocidad debe ser positiva")
    if not TONO_MINIMO <= voz.tono <= TONO_MAXIMO:
        raise ValueError(
            f"voz.personajes.{nombre}.tono debe estar entre {TONO_MINIMO} y {TONO_MAXIMO}"
        )
    if voz.hablante is not None and voz.hablante < 0:
        raise ValueError(f"voz.personajes.{nombre}.hablante no puede ser negativo")
    return voz


def cargar_configuracion_voz(ruta: Path | None = None) -> ConfiguracionVoz:
    """Carga ``config/voz.toml``; si falta, usa los valores por defecto.

    Args:
        ruta: archivo TOML alternativo.

    Returns:
        La configuración de las voces.

    Raises:
        ValueError: si un personaje no es del contrato, o si el largo máximo,
            la velocidad, el tono o el hablante no son válidos.
    """
    archivo = RUTA_CONFIG_VOZ if ruta is None else ruta
    datos: dict[str, Any] = {}
    if archivo.exists():
        with archivo.open("rb") as fh:
            datos = dict(tomllib.load(fh))
    general: Mapping[str, Any] = datos.get("voz", {})
    crudos: Mapping[str, Any] = datos.get("personajes", {})
    desconocidos = sorted(set(crudos) - set(PERSONAJES))
    if desconocidos:
        raise ValueError(f"personajes desconocidos en config/voz.toml: {desconocidos}")
    personajes = {
        nombre: _voz_personaje(nombre, crudos[nombre]) if nombre in crudos else VOZ_POR_DEFECTO
        for nombre in PERSONAJES
    }
    config = ConfiguracionVoz(
        activa=bool(general.get("activa", True)),
        carpeta=Path(str(general.get("carpeta", "data/modelos/voz"))),
        largo_maximo=int(general.get("largo_maximo", 900)),
        personajes=personajes,
    )
    if config.largo_maximo <= 0:
        raise ValueError("voz.largo_maximo debe ser positivo")
    return config


#: Firma de un sintetizador: (texto, voz) → (muestras float32 entre -1 y 1, frecuencia).
Sintetizador = Callable[[str, VozPersonaje], tuple[np.ndarray, int]]


def sintetizador_piper(config: ConfiguracionVoz, raiz: Path = PROJECT_ROOT) -> Sintetizador:
    """Crea un sintetizador con Piper que carga cada modelo la primera vez.

    Args:
        config: configuración con la carpeta de los modelos.
        raiz: raíz del proyecto.

    Returns:
        Una función (texto, voz) → (muestras, frecuencia).
    """
    cargadas: dict[str, Any] = {}
    candado = threading.Lock()

    def sintetizar(texto: str, voz: VozPersonaje) -> tuple[np.ndarray, int]:
        """Convierte el texto en muestras con la voz de Piper del personaje."""
        from piper import PiperVoice, SynthesisConfig

        modelo = config.ruta_modelo(voz.modelo, raiz)
        with candado:
            if voz.modelo not in cargadas:
                if not modelo.exists():
                    raise VozNoDisponible(f"falta la voz {voz.modelo}: ejecuta `make voz-modelo`")
                cargadas[voz.modelo] = PiperVoice.load(str(modelo))
            ajustes = SynthesisConfig(
                speaker_id=voz.hablante, length_scale=voz.velocidad * voz.tono
            )
            trozos = list(cargadas[voz.modelo].synthesize(texto, ajustes))
        if not trozos:
            raise VozNoDisponible("Piper no devolvió audio")
        muestras = np.concatenate([trozo.audio_float_array for trozo in trozos])
        return muestras.astype(np.float32), int(trozos[0].sample_rate)

    return sintetizar


def remuestrear(muestras: np.ndarray, origen: int, destino: int) -> np.ndarray:
    """Cambia la frecuencia del audio con interpolación lineal.

    Basta para voz; evita sumar una dependencia solo para esto.

    Args:
        muestras: audio mono en float.
        origen: frecuencia actual en Hz.
        destino: frecuencia deseada en Hz.

    Returns:
        El audio a la nueva frecuencia, en float32.
    """
    if origen == destino or muestras.size == 0:
        return muestras.astype(np.float32)
    largo = max(1, round(muestras.size * destino / origen))
    posiciones = np.linspace(0, muestras.size - 1, largo)
    return np.interp(posiciones, np.arange(muestras.size), muestras).astype(np.float32)


def cambiar_tono(muestras: np.ndarray, tono: float) -> np.ndarray:
    """Sube o baja el tono comprimiendo o estirando el audio.

    Con ``tono`` menor que 1 el audio queda más largo y, a la misma frecuencia,
    suena más grave; por eso `sintetizador_piper` habla más rápido en la misma
    proporción y la duración final se conserva.

    Args:
        muestras: audio mono en float.
        tono: factor de tono; 1 lo deja igual.

    Returns:
        El audio con el tono cambiado.
    """
    if tono == 1.0 or muestras.size == 0:
        return muestras.astype(np.float32)
    return remuestrear(muestras, round(1000 * tono), 1000)


def a_ogg_opus(muestras: np.ndarray, frecuencia: int) -> bytes:
    """Codifica audio mono como OGG/Opus.

    Args:
        muestras: audio mono en float entre -1 y 1.
        frecuencia: frecuencia en Hz.

    Returns:
        Los bytes del ``.ogg``.

    Raises:
        VozNoDisponible: si el audio está vacío o pasa el tope de peso.
    """
    if muestras.size == 0:
        raise VozNoDisponible("el audio está vacío")
    if frecuencia not in FRECUENCIAS_OPUS:
        muestras = remuestrear(muestras, frecuencia, FRECUENCIA_DESTINO)
        frecuencia = FRECUENCIA_DESTINO
    salida = io.BytesIO()
    soundfile.write(salida, np.clip(muestras, -1.0, 1.0), frecuencia, format="OGG", subtype="OPUS")
    datos = salida.getvalue()
    if len(datos) >= PESO_MAXIMO_AUDIO:
        raise VozNoDisponible("el audio pasa el tope de 16 MB")
    return datos


@dataclass
class VozEscena:
    """Genera el audio de cada personaje y guarda en memoria los repetidos.

    Las frases con guion (Don Gota, la presentación de Pana) se repiten en los
    ensayos: la memoria evita sintetizarlas de nuevo. Guarda a lo sumo
    `MAXIMO_EN_MEMORIA` audios, solo en memoria.
    """

    sintetizador: Sintetizador
    personajes: Mapping[str, VozPersonaje] = field(
        default_factory=lambda: dict.fromkeys(PERSONAJES, VOZ_POR_DEFECTO)
    )
    largo_maximo: int = 900
    _memoria: dict[tuple[str, str], bytes] = field(default_factory=dict, init=False, repr=False)
    _candado: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)

    def audio(self, texto: str, personaje: str = "pana") -> bytes:
        """Devuelve el OGG/Opus del texto con la voz del personaje.

        Args:
            texto: lo que dice el personaje.
            personaje: uno de `PERSONAJES`.

        Returns:
            Los bytes del audio.

        Raises:
            ValueError: si el personaje no es del contrato.
            VozNoDisponible: si el texto está vacío o es muy largo, si falta el
                modelo o si la síntesis falla.
        """
        if personaje not in PERSONAJES:
            raise ValueError(f"personaje desconocido: {personaje}")
        limpio = texto.strip()
        if not limpio:
            raise VozNoDisponible("no hay texto para leer")
        if len(limpio) > self.largo_maximo:
            raise VozNoDisponible("el texto es muy largo para leerlo")
        clave = (personaje, limpio)
        with self._candado:
            if clave in self._memoria:
                return self._memoria[clave]
        voz = self.personajes.get(personaje, VOZ_POR_DEFECTO)
        if voz.motor != "piper":
            raise VozNoDisponible(f"{personaje} usa la voz del navegador")
        try:
            muestras, frecuencia = self.sintetizador(limpio, voz)
        except VozNoDisponible:
            raise
        except Exception as error:
            LOGGER.warning(
                "evento=voz_fallo personaje=%s error=%s", personaje, type(error).__name__
            )
            raise VozNoDisponible("no se pudo generar la voz") from error
        audio = a_ogg_opus(cambiar_tono(muestras, voz.tono), frecuencia)
        with self._candado:
            if len(self._memoria) >= MAXIMO_EN_MEMORIA:
                self._memoria.pop(next(iter(self._memoria)))
            self._memoria[clave] = audio
        return audio


def crear_voz(config: ConfiguracionVoz, raiz: Path = PROJECT_ROOT) -> VozEscena | None:
    """Arma las voces de la escena a partir de la configuración.

    Args:
        config: valores de ``config/voz.toml``.
        raiz: raíz del proyecto.

    Returns:
        Las voces listas, o ``None`` si están apagadas. Si un modelo no está
        descargado, la voz se crea igual y avisa con `VozNoDisponible` al usarla.
    """
    if not config.activa:
        return None
    return VozEscena(
        sintetizador=sintetizador_piper(config, raiz),
        personajes=config.personajes,
        largo_maximo=config.largo_maximo,
    )


def modelos_disponibles(config: ConfiguracionVoz, raiz: Path = PROJECT_ROOT) -> dict[str, bool]:
    """Dice qué personajes tienen voz de Piper lista (motor piper y modelo descargado).

    Args:
        config: valores de ``config/voz.toml``.
        raiz: raíz del proyecto.

    Returns:
        ``{personaje: True/False}`` en el orden de `PERSONAJES`.
    """
    return {
        nombre: config.activa
        and voz.motor == "piper"
        and config.ruta_modelo(voz.modelo, raiz).exists()
        for nombre, voz in config.personajes.items()
    }
