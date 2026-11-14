"""Costo, gasto diario y caché de respuestas de la Sucursal.

Las tarifas viven solo en `arqueo/metricas.py`; este módulo elige valle o pico
según la hora UTC y acumula el gasto del día en SQLite. La caché guarda la
respuesta completa de un turno que usó el modelo, con TTL configurable.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import threading
import time
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from ..arqueo.metricas import (
    TARIFAS_DEEPSEEK_FLASH,
    TARIFAS_DEEPSEEK_FLASH_PICO,
    Tarifas,
)
from ..asistente.metricas import leer_uso
from ..texto import normalizar

#: Franjas de pico en UTC, de lunes a viernes: [inicio, fin).
FRANJAS_PICO: tuple[tuple[int, int], ...] = ((1, 4), (6, 10))


def tarifas_para(momento_utc: datetime) -> Tarifas:
    """Elige la tarifa valle o pico según la hora UTC.

    Args:
        momento_utc: instante con zona UTC.

    Returns:
        Las tarifas de DeepSeek Flash aplicables.
    """
    momento = momento_utc.astimezone(UTC)
    if momento.weekday() < 5 and any(inicio <= momento.hour < fin for inicio, fin in FRANJAS_PICO):
        return TARIFAS_DEEPSEEK_FLASH_PICO
    return TARIFAS_DEEPSEEK_FLASH


def costo_de_uso(uso: Mapping[str, Any] | None, tarifas: Tarifas) -> tuple[float, int]:
    """Calcula el costo en USD y los tokens totales de un uso del modelo.

    Args:
        uso: métricas en el formato de `asistente.metricas.extraer_metricas`.
        tarifas: tarifas por millón de tokens ya elegidas.

    Returns:
        Una tupla `(costo_usd, tokens_totales)`.
    """
    detalle = leer_uso(uso)
    entrada = detalle.entrada or 0
    salida = detalle.salida or 0
    cache = min(detalle.cache or 0, entrada)
    costo = (
        (entrada - cache) * tarifas.entrada + cache * tarifas.cache + salida * tarifas.salida
    ) / 1_000_000
    return costo, entrada + salida


@dataclass
class GastoDiario:
    """Acumulado por día de llamadas, tokens y costo en USD."""

    ruta: Path

    def __post_init__(self) -> None:
        """Crea la carpeta y la tabla si no existen."""
        self.ruta.parent.mkdir(parents=True, exist_ok=True)
        self._candado = threading.Lock()
        with self._conectar() as conexion:
            conexion.execute(
                "CREATE TABLE IF NOT EXISTS gasto ("
                "fecha TEXT PRIMARY KEY, costo_usd REAL NOT NULL, "
                "llamadas INTEGER NOT NULL, tokens INTEGER NOT NULL)"
            )

    def hoy(self, fecha: date | None = None) -> tuple[float, int, int]:
        """Devuelve `(costo, llamadas, tokens)` del día indicado (hoy por defecto)."""
        clave = (fecha or datetime.now(UTC).date()).isoformat()
        with self._conectar() as conexion:
            fila = conexion.execute(
                "SELECT costo_usd, llamadas, tokens FROM gasto WHERE fecha = ?", (clave,)
            ).fetchone()
        if fila is None:
            return 0.0, 0, 0
        return float(fila[0]), int(fila[1]), int(fila[2])

    def sumar(
        self,
        costo_usd: float,
        tokens: int,
        *,
        llamadas: int = 1,
        fecha: date | None = None,
    ) -> None:
        """Suma una llamada al acumulado del día."""
        if costo_usd < 0 or tokens < 0 or llamadas < 0:
            raise ValueError("El gasto, los tokens y las llamadas no pueden ser negativos")
        clave = (fecha or datetime.now(UTC).date()).isoformat()
        with self._candado, self._conectar() as conexion:
            conexion.execute(
                "INSERT INTO gasto (fecha, costo_usd, llamadas, tokens) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(fecha) DO UPDATE SET "
                "costo_usd = costo_usd + excluded.costo_usd, "
                "llamadas = llamadas + excluded.llamadas, "
                "tokens = tokens + excluded.tokens",
                (clave, costo_usd, llamadas, tokens),
            )

    def _conectar(self) -> sqlite3.Connection:
        """Abre una conexión corta con la SQLite del gasto."""
        return sqlite3.connect(str(self.ruta), check_same_thread=False)


@dataclass
class CacheRespuestas:
    """Caché de respuestas por clave, con vencimiento."""

    ruta: Path
    ttl_segundos: int = 3600

    def __post_init__(self) -> None:
        """Crea la carpeta y la tabla si no existen."""
        self.ruta.parent.mkdir(parents=True, exist_ok=True)
        with self._conectar() as conexion:
            conexion.execute(
                "CREATE TABLE IF NOT EXISTS cache ("
                "clave TEXT PRIMARY KEY, respuesta_json TEXT NOT NULL, "
                "creado REAL NOT NULL, expira REAL NOT NULL)"
            )

    @staticmethod
    def clave(pregunta: str, ruta: str, version: str, perfil_id: str = "") -> str:
        """Devuelve la clave estable `sha256(pregunta normalizada|ruta|versión)`.

        ``perfil_id`` se añade solo cuando no está vacío. La ruta de perfil no
        usa la caché; este parámetro es una defensa para que un cambio futuro no
        pueda servir la respuesta de un perfil a otro.
        """
        limpia = " ".join(re.sub(r"[^\w\s]", " ", normalizar(pregunta)).split())
        material = f"{limpia}|{ruta}|{version}"
        if perfil_id:
            huella = hashlib.sha256(perfil_id.encode("utf-8")).hexdigest()
            material = f"{material}|{huella}"
        return hashlib.sha256(material.encode("utf-8")).hexdigest()

    def obtener(self, clave: str) -> dict[str, Any] | None:
        """Devuelve la respuesta vigente o None si no existe o expiró."""
        ahora = time.time()
        with self._conectar() as conexion:
            fila = conexion.execute(
                "SELECT respuesta_json, expira FROM cache WHERE clave = ?", (clave,)
            ).fetchone()
            if fila is None:
                return None
            if float(fila[1]) <= ahora:
                conexion.execute("DELETE FROM cache WHERE clave = ?", (clave,))
                return None
        return dict(json.loads(fila[0]))

    def guardar(self, clave: str, respuesta: Mapping[str, Any]) -> None:
        """Guarda una respuesta con el TTL configurado."""
        ahora = time.time()
        expira = ahora + self.ttl_segundos
        with self._conectar() as conexion:
            conexion.execute(
                "INSERT OR REPLACE INTO cache (clave, respuesta_json, creado, expira) "
                "VALUES (?, ?, ?, ?)",
                (clave, json.dumps(dict(respuesta), ensure_ascii=False), ahora, expira),
            )

    def limpiar(self) -> None:
        """Borra todas las entradas de la caché."""
        with self._conectar() as conexion:
            conexion.execute("DELETE FROM cache")

    def _conectar(self) -> sqlite3.Connection:
        """Abre una conexión corta con la SQLite de la caché."""
        return sqlite3.connect(str(self.ruta), check_same_thread=False)
