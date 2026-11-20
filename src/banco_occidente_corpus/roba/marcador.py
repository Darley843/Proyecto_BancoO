"""Marcador de Roba la Bóveda en ``data/asistente/roba.sqlite`` (tarea 7.7).

Guarda un intento por fila con su sesión, número, categoría, hash, texto y
respuesta **saneados** (sin datos personales), éxito, puntos, defensa y fecha.
La tabla ``intentos`` incluye las columnas ``categoria``, ``exito`` y ``puntos``
que lee ``sucursal/operacion.py`` para el resumen de ``GET /api/operacion``.

El límite de intentos por sesión se comprueba dentro de la misma transacción
que inserta, abierta con ``BEGIN IMMEDIATE`` (bloqueo de escritura de SQLite,
válido también entre procesos) y además con un candado de hilo, para que dos
peticiones simultáneas no lo superen. La exportación es determinista: no lleva
la sesión ni las fechas y omite el texto de los intentos que traían un dato
personal.
"""

from __future__ import annotations

import sqlite3
import threading
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from .clasificador import CATEGORIAS, huella

#: Zona horaria de las fechas del marcador.
ZONA_HORARIA = ZoneInfo("America/Bogota")
#: Versión del formato de exportación.
VERSION_EXPORTACION = 1

ESQUEMA = """
CREATE TABLE IF NOT EXISTS intentos (
    sesion TEXT NOT NULL,
    n INTEGER NOT NULL,
    categoria TEXT NOT NULL,
    hash TEXT NOT NULL,
    texto TEXT NOT NULL,
    respuesta TEXT NOT NULL,
    con_pii INTEGER NOT NULL DEFAULT 0,
    exito INTEGER NOT NULL,
    puntos INTEGER NOT NULL,
    defensa TEXT NOT NULL,
    creado TEXT NOT NULL,
    PRIMARY KEY (sesion, n)
);
"""


class LimiteAlcanzado(Exception):
    """La sesión ya usó todos sus intentos."""


@dataclass(frozen=True, slots=True)
class IntentoGuardado:
    """Intento ya registrado, con el número que le tocó en la sesión."""

    n: int
    categoria: str
    exito: bool
    puntos: int
    defensa: str
    texto: str
    respuesta: str
    creado: str


class MarcadorRoba:
    """Marcador persistente por sesión, con límite de intentos."""

    def __init__(self, ruta: Path, limite: int) -> None:
        """Guarda la ruta de la base y el límite; la base se crea al primer uso.

        Args:
            ruta: archivo SQLite del marcador.
            limite: intentos permitidos por sesión.

        Raises:
            ValueError: si el límite no es positivo.
        """
        if limite <= 0:
            raise ValueError("el límite de intentos debe ser mayor que cero")
        self.ruta = ruta
        self.limite = limite
        self._candado = threading.Lock()

    def _conectar(self) -> sqlite3.Connection:
        """Abre la base y crea la tabla si falta."""
        self.ruta.parent.mkdir(parents=True, exist_ok=True)
        conexion = sqlite3.connect(self.ruta, timeout=5, isolation_level=None)
        conexion.executescript(ESQUEMA)
        return conexion

    def contar(self, sesion: str) -> int:
        """Devuelve cuántos intentos lleva la sesión.

        Args:
            sesion: identificador de la sesión del juego.

        Returns:
            El número de intentos registrados.
        """
        with closing(self._conectar()) as conexion:
            fila = conexion.execute(
                "SELECT COUNT(*) FROM intentos WHERE sesion = ?", (sesion,)
            ).fetchone()
        return int(fila[0]) if fila else 0

    def registrar(
        self,
        sesion: str,
        *,
        categoria: str,
        texto: str,
        respuesta: str,
        exito: bool,
        puntos: int,
        con_pii: bool,
        ahora: datetime | None = None,
    ) -> IntentoGuardado:
        """Registra un intento si la sesión no llegó al límite.

        El texto y la respuesta deben llegar ya saneados: un intento con un dato
        personal llega con una marca fija en lugar del texto.

        Args:
            sesion: identificador de la sesión del juego.
            categoria: categoría definitiva del intento.
            texto: intento saneado.
            respuesta: respuesta saneada del asistente.
            exito: True si la defensa cayó.
            puntos: puntos ganados.
            con_pii: True si el intento original traía un dato personal.
            ahora: fecha del intento; por defecto la hora actual en Bogotá.

        Returns:
            El intento guardado con su número.

        Raises:
            LimiteAlcanzado: si la sesión ya usó todos sus intentos.
            ValueError: si la categoría no es una de las cinco.
        """
        if categoria not in CATEGORIAS:
            raise ValueError(f"categoría desconocida: {categoria}")
        momento = (ahora or datetime.now(ZONA_HORARIA)).astimezone(ZONA_HORARIA)
        creado = momento.isoformat(timespec="seconds")
        defensa = "vulnerada" if exito else "resistida"
        with self._candado, closing(self._conectar()) as conexion:
            conexion.execute("BEGIN IMMEDIATE")
            fila = conexion.execute(
                "SELECT COUNT(*), COALESCE(MAX(n), 0) FROM intentos WHERE sesion = ?",
                (sesion,),
            ).fetchone()
            usados, ultimo = (int(fila[0]), int(fila[1])) if fila else (0, 0)
            if usados >= self.limite:
                conexion.execute("ROLLBACK")
                raise LimiteAlcanzado(f"la sesión ya usó sus {self.limite} intentos")
            numero = ultimo + 1
            conexion.execute(
                "INSERT INTO intentos (sesion, n, categoria, hash, texto, respuesta, con_pii,"
                " exito, puntos, defensa, creado) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    sesion,
                    numero,
                    categoria,
                    huella(texto),
                    texto,
                    respuesta,
                    int(con_pii),
                    int(exito),
                    puntos,
                    defensa,
                    creado,
                ),
            )
            conexion.execute("COMMIT")
        return IntentoGuardado(
            n=numero,
            categoria=categoria,
            exito=exito,
            puntos=puntos,
            defensa=defensa,
            texto=texto,
            respuesta=respuesta,
            creado=creado,
        )

    def _filas(self, sesion: str) -> list[tuple[Any, ...]]:
        """Lee los intentos de la sesión en orden."""
        with closing(self._conectar()) as conexion:
            return list(
                conexion.execute(
                    "SELECT n, categoria, hash, texto, respuesta, con_pii, exito, puntos,"
                    " defensa, creado FROM intentos WHERE sesion = ? ORDER BY n",
                    (sesion,),
                ).fetchall()
            )

    @staticmethod
    def _totales(filas: list[tuple[Any, ...]]) -> dict[str, Any]:
        """Suma intentos, éxitos y puntos, en total y por categoría."""
        por_categoria: dict[str, dict[str, int]] = {}
        for _, categoria, _, _, _, _, exito, puntos, _, _ in filas:
            fila = por_categoria.setdefault(
                str(categoria), {"intentos": 0, "exitos": 0, "puntos": 0}
            )
            fila["intentos"] += 1
            fila["exitos"] += int(exito)
            fila["puntos"] += int(puntos)
        ordenadas = {
            categoria: por_categoria[categoria]
            for categoria in CATEGORIAS
            if categoria in por_categoria
        }
        return {
            "intentos": len(filas),
            "exitos": sum(int(fila[6]) for fila in filas),
            "puntos": sum(int(fila[7]) for fila in filas),
            "por_categoria": ordenadas,
        }

    def totales(self, sesion: str) -> dict[str, Any]:
        """Devuelve el marcador de la sesión.

        Args:
            sesion: identificador de la sesión del juego.

        Returns:
            Intentos, éxitos, puntos y la tabla por categoría.
        """
        return self._totales(self._filas(sesion))

    def estado(self, sesion: str) -> dict[str, Any]:
        """Devuelve el cuerpo de ``GET /api/roba``: límite, marcador e historial.

        Args:
            sesion: identificador de la sesión del juego.

        Returns:
            El diccionario del contrato, con los textos ya saneados.
        """
        filas = self._filas(sesion)
        intentos = [
            {
                "n": int(n),
                "categoria": str(categoria),
                "exito": bool(exito),
                "puntos": int(puntos),
                "defensa": str(defensa),
                "texto": str(texto),
                "respuesta": str(respuesta),
                "creado": str(creado),
            }
            for n, categoria, _, texto, respuesta, _, exito, puntos, defensa, creado in filas
        ]
        return {
            "sesion": sesion,
            "limite": self.limite,
            "marcador": self._totales(filas),
            "intentos": intentos,
        }

    def reiniciar(self, sesion: str) -> int:
        """Borra los intentos de la sesión; el corpus y el índice no se tocan.

        Args:
            sesion: identificador de la sesión del juego.

        Returns:
            Cuántos intentos se borraron.
        """
        with self._candado, closing(self._conectar()) as conexion:
            cursor = conexion.execute("DELETE FROM intentos WHERE sesion = ?", (sesion,))
            return int(cursor.rowcount)

    def exportar(self, sesion: str) -> dict[str, Any]:
        """Arma el resumen para el Arqueo, determinista y sin datos personales.

        No incluye la sesión, las fechas ni las respuestas. De cada intento
        conserva número, categoría, éxito, puntos y hash; el texto solo va si el
        intento original no traía un dato personal.

        Args:
            sesion: identificador de la sesión del juego.

        Returns:
            El resumen con totales, tasa de resistencia y detalle por intento.
        """
        filas = self._filas(sesion)
        totales = self._totales(filas)
        ataques = [fila for fila in filas if fila[1] != "legitimo"]
        resistidos = sum(1 for fila in ataques if not int(fila[6]))
        detalle: list[dict[str, Any]] = []
        for n, categoria, hash_texto, texto, _, con_pii, exito, puntos, _, _ in filas:
            item: dict[str, Any] = {
                "n": int(n),
                "categoria": str(categoria),
                "exito": bool(exito),
                "puntos": int(puntos),
            }
            if not int(con_pii):
                item["hash"] = str(hash_texto)
                item["texto"] = str(texto)
            detalle.append(item)
        return {
            "version": VERSION_EXPORTACION,
            "limite": self.limite,
            "intentos": totales["intentos"],
            "ataques": len(ataques),
            "exitos": totales["exitos"],
            "puntos": totales["puntos"],
            "resistencia": round(resistidos / len(ataques), 4) if ataques else None,
            "por_categoria": totales["por_categoria"],
            "detalle": detalle,
        }
