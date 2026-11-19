"""Resumen de operación del corresponsal de WhatsApp (OpenSpec corresponsal-whatsapp, 8.7).

Arma la respuesta de `GET /api/operacion` leyendo, solo en modo lectura, las
bases locales del canal:

- `data/asistente/whatsapp.sqlite`: mensajes, consentimientos y casos del
  asesor (esquema de `design.md`, «Esquema SQLite del canal»);
- `data/asistente/latencias.sqlite`: tabla `latencias` (`flujo`, `ms`,
  `cache`, `creado`) que escribe `medir(flujo, cache)`;
- `data/asistente/roba.sqlite`: tabla `intentos` del marcador de Roba la Bóveda;
- `config/whatsapp.toml` y las variables de entorno, solo para saber si el
  canal está configurado (nunca se leen ni se devuelven sus valores).

Reglas:

- **Sin datos personales.** No se consultan columnas de usuario ni de texto:
  la respuesta solo lleva conteos, ids de caso, motivos, semáforos y fechas.
- **Nunca crea archivos.** Las bases se abren con `mode=ro`; si una falta,
  está vacía o tiene otro esquema, ese bloque sale en cero o vacío y la ruta
  sigue respondiendo (spec: «funciona con la base vacía»).
- **Latencia reproducible.** p50 y p95 son nearest-rank y una muestra con
  menos de 30 corridas se marca como insuficiente; la caché va aparte.
"""

from __future__ import annotations

import math
import os
import re
import sqlite3
import tomllib
from collections.abc import Mapping, Sequence
from contextlib import closing
from datetime import datetime
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field

#: Base del canal (mensajes, consentimientos, envíos y casos).
RUTA_WHATSAPP = "data/asistente/whatsapp.sqlite"
#: Base de las mediciones de latencia.
RUTA_LATENCIAS = "data/asistente/latencias.sqlite"
#: Base del marcador de Roba la Bóveda.
RUTA_ROBA = "data/asistente/roba.sqlite"
#: Configuración del canal, sin secretos.
RUTA_CONFIG_WHATSAPP = "config/whatsapp.toml"

#: Variables que deben existir para considerar el canal configurado.
VARIABLES_CANAL = (
    "WHATSAPP_VERIFY_TOKEN",
    "WHATSAPP_APP_SECRET",
    "WHATSAPP_ACCESS_TOKEN",
    "WHATSAPP_PHONE_NUMBER_ID",
    "WHATSAPP_ID_SALT",
)
#: Corridas mínimas para que un percentil sea concluyente.
MINIMO_CORRIDAS = 30
#: Casos pendientes que se listan como máximo.
MAXIMO_CASOS_LISTADOS = 50
#: Zona horaria en la que se informa la hora del corte.
ZONA_HORARIA = ZoneInfo("America/Bogota")
#: Una huella válida es un HMAC-SHA256 en hexadecimal.
PATRON_HUELLA = re.compile(r"^[0-9a-f]{64}$")

ModoCanal = Literal["real", "falso", "deshabilitado"]
Semaforo = Literal["verde", "amarillo", "rojo"]


class CanalOperacion(BaseModel):
    """Estado del canal: si está configurado, cómo envía y cuántos números acepta."""

    configurado: bool
    modo: ModoCanal
    numeros_autorizados: int


class MensajesOperacion(BaseModel):
    """Conteo de mensajes por estado; `duplicados` es None si no se registran."""

    recibidos: int = 0
    respondidos: int = 0
    errores: int = 0
    pendientes: int = 0
    duplicados: int | None = None


class ConsentimientosOperacion(BaseModel):
    """Consentimientos de la Ley 1581 de 2012: aceptados, por aceptar y revocados."""

    aceptados: int = 0
    pendientes: int = 0
    revocados: int = 0


class CasoOperacion(BaseModel):
    """Caso del asesor sin datos de la persona: solo id, motivo, semáforo, estado y fecha."""

    id: str
    motivo: str
    semaforo: Semaforo
    estado: str
    creado: str


class CasosOperacion(BaseModel):
    """Totales de casos HITL y la lista de los pendientes."""

    pendientes: int = 0
    contactados: int = 0
    descartados: int = 0
    lista: list[CasoOperacion] = Field(default_factory=list)


class LatenciaFlujo(BaseModel):
    """Percentiles nearest-rank de un flujo y si la muestra alcanza."""

    p50_ms: float
    p95_ms: float
    n: int
    suficiente: bool


class RobaOperacion(BaseModel):
    """Resumen global de Roba la Bóveda; `por_categoria` cuenta éxitos."""

    intentos: int = 0
    exitos: int = 0
    puntos: int = 0
    por_categoria: dict[str, int] = Field(default_factory=dict)


class OperacionRespuesta(BaseModel):
    """Respuesta de `GET /api/operacion` (design.md, decisión 16)."""

    generado: str
    canal: CanalOperacion
    mensajes: MensajesOperacion
    consentimientos: ConsentimientosOperacion
    casos: CasosOperacion
    latencia: dict[str, LatenciaFlujo] = Field(default_factory=dict)
    latencia_cache: dict[str, LatenciaFlujo] = Field(default_factory=dict)
    roba: RobaOperacion


def resumen_operacion(
    raiz: Path,
    entorno: Mapping[str, str] | None = None,
    ahora: datetime | None = None,
) -> OperacionRespuesta:
    """Arma el resumen de operación a partir de las bases locales.

    Args:
        raiz: raíz del proyecto (`config.paths.root`).
        entorno: variables de entorno; por defecto `os.environ`. Solo se mira
            si existen, nunca su valor.
        ahora: hora del corte; por defecto, la hora actual en Bogotá.

    Returns:
        El resumen, con bloques en cero o vacíos cuando falta una base.
    """
    variables = os.environ if entorno is None else entorno
    momento = ahora or datetime.now(ZONA_HORARIA)
    canal = estado_canal(raiz, variables)
    normales, con_cache = resumen_latencias(raiz / RUTA_LATENCIAS)
    ruta_canal = raiz / RUTA_WHATSAPP
    return OperacionRespuesta(
        generado=momento.astimezone(ZONA_HORARIA).isoformat(timespec="seconds"),
        canal=canal,
        mensajes=contar_mensajes(ruta_canal),
        consentimientos=contar_consentimientos(ruta_canal),
        casos=resumen_casos(ruta_canal),
        latencia=normales,
        latencia_cache=con_cache,
        roba=resumen_roba(raiz / RUTA_ROBA),
    )


def estado_canal(raiz: Path, entorno: Mapping[str, str]) -> CanalOperacion:
    """Decide si el canal está configurado, su modo y cuántos números autoriza.

    El canal está configurado solo si existen las cinco variables de
    `VARIABLES_CANAL`. El modo sale de `WHATSAPP_MODO` o de `canal.modo` en
    `config/whatsapp.toml`; sin configuración, es `deshabilitado`.

    Args:
        raiz: raíz del proyecto.
        entorno: variables de entorno (solo se comprueba que no estén vacías).

    Returns:
        El bloque `canal` del resumen.
    """
    datos = _leer_toml(raiz / RUTA_CONFIG_WHATSAPP)
    seccion_canal = datos.get("canal")
    seccion_autorizados = datos.get("autorizados")
    huellas = (
        seccion_autorizados.get("huellas", []) if isinstance(seccion_autorizados, dict) else []
    )
    if not isinstance(huellas, list):
        huellas = []
    autorizados = sum(
        1 for huella in huellas if isinstance(huella, str) and PATRON_HUELLA.match(huella)
    )

    configurado = all(entorno.get(nombre, "").strip() for nombre in VARIABLES_CANAL)
    if not configurado:
        return CanalOperacion(
            configurado=False, modo="deshabilitado", numeros_autorizados=autorizados
        )

    modo_toml = seccion_canal.get("modo", "falso") if isinstance(seccion_canal, dict) else "falso"
    modo = (entorno.get("WHATSAPP_MODO") or str(modo_toml)).strip().lower()
    return CanalOperacion(
        configurado=True,
        modo="real" if modo == "real" else "falso",
        numeros_autorizados=autorizados,
    )


def contar_mensajes(ruta: Path) -> MensajesOperacion:
    """Cuenta los mensajes por estado en la tabla `mensajes`.

    `respondido` cuenta como respondido, `error` como error y cualquier otro
    estado (recibido, encolado, procesando) como pendiente en la cola.

    Args:
        ruta: base `whatsapp.sqlite`.

    Returns:
        El bloque `mensajes`; en cero si la base o la tabla no existen.
    """
    filas = _consultar(ruta, "SELECT estado, COUNT(*) FROM mensajes GROUP BY estado")
    conteo = {str(estado): int(total) for estado, total in filas}
    respondidos = conteo.pop("respondido", 0)
    errores = conteo.pop("error", 0)
    pendientes = sum(conteo.values())
    return MensajesOperacion(
        recibidos=respondidos + errores + pendientes,
        respondidos=respondidos,
        errores=errores,
        pendientes=pendientes,
    )


def contar_consentimientos(ruta: Path) -> ConsentimientosOperacion:
    """Cuenta consentimientos vigentes, revocados y personas que aún no aceptan.

    «Por aceptar» son los usuarios que escribieron (tabla `mensajes`) y no
    tienen fila en `consentimientos`. Solo se cuentan: los ids no salen.

    Args:
        ruta: base `whatsapp.sqlite`.

    Returns:
        El bloque `consentimientos`; en cero si la base no existe.
    """
    estados = _consultar(
        ruta,
        "SELECT revocado_en IS NULL, COUNT(*) FROM consentimientos GROUP BY revocado_en IS NULL",
    )
    vigentes = {bool(vigente): int(total) for vigente, total in estados}
    sin_aceptar = _consultar(
        ruta,
        "SELECT COUNT(DISTINCT m.usuario_id) FROM mensajes AS m "
        "LEFT JOIN consentimientos AS c ON c.usuario_id = m.usuario_id "
        "WHERE c.usuario_id IS NULL",
    )
    return ConsentimientosOperacion(
        aceptados=vigentes.get(True, 0),
        revocados=vigentes.get(False, 0),
        pendientes=int(sin_aceptar[0][0]) if sin_aceptar else 0,
    )


def resumen_casos(ruta: Path) -> CasosOperacion:
    """Resume los casos del asesor y lista los pendientes sin datos personales.

    No se leen `usuario_id` ni `resultado_json`: solo id, motivo, semáforo,
    estado y fecha. Un caso con semáforo desconocido no se lista.

    Args:
        ruta: base `whatsapp.sqlite`.

    Returns:
        El bloque `casos`; vacío si la base no existe.
    """
    totales = {
        str(estado): int(total)
        for estado, total in _consultar(ruta, "SELECT estado, COUNT(*) FROM casos GROUP BY estado")
    }
    filas = _consultar(
        ruta,
        "SELECT id_caso, motivo, semaforo, estado, creado_en FROM casos "
        "WHERE estado = 'pendiente' ORDER BY creado_en LIMIT ?",
        (MAXIMO_CASOS_LISTADOS,),
    )
    lista = [
        CasoOperacion(
            id=str(id_caso),
            motivo=str(motivo),
            semaforo=semaforo,
            estado=str(estado),
            creado=str(creado),
        )
        for id_caso, motivo, semaforo, estado, creado in filas
        if semaforo in ("verde", "amarillo", "rojo")
    ]
    return CasosOperacion(
        pendientes=totales.get("pendiente", 0),
        contactados=totales.get("contactado", 0),
        descartados=totales.get("descartado", 0),
        lista=lista,
    )


def resumen_latencias(ruta: Path) -> tuple[dict[str, LatenciaFlujo], dict[str, LatenciaFlujo]]:
    """Calcula p50 y p95 por flujo, separando las corridas que respondió la caché.

    Args:
        ruta: base `latencias.sqlite`.

    Returns:
        Dos diccionarios flujo → percentiles: sin caché y con caché.
    """
    muestras: dict[tuple[str, bool], list[float]] = {}
    for flujo, ms, cache in _consultar(ruta, "SELECT flujo, ms, cache FROM latencias"):
        try:
            valor = float(ms)
        except (TypeError, ValueError):
            continue
        if math.isfinite(valor) and valor >= 0:
            muestras.setdefault((str(flujo), bool(cache)), []).append(valor)

    normales: dict[str, LatenciaFlujo] = {}
    con_cache: dict[str, LatenciaFlujo] = {}
    for (flujo, es_cache), valores in sorted(muestras.items()):
        destino = con_cache if es_cache else normales
        destino[flujo] = LatenciaFlujo(
            p50_ms=percentil_nearest_rank(valores, 50),
            p95_ms=percentil_nearest_rank(valores, 95),
            n=len(valores),
            suficiente=len(valores) >= MINIMO_CORRIDAS,
        )
    return normales, con_cache


def percentil_nearest_rank(valores: Sequence[float], percentil: float) -> float:
    """Percentil por rango más cercano: el valor en la posición ⌈p/100 · n⌉.

    Siempre devuelve un valor que sí ocurrió (no interpola), así el reporte es
    reproducible y fácil de verificar a mano.

    Args:
        valores: muestra no vacía.
        percentil: entre 0 (excluido) y 100.

    Returns:
        El valor de la muestra en ese percentil.

    Raises:
        ValueError: si la muestra está vacía o el percentil está fuera de rango.
    """
    if not valores:
        raise ValueError("La muestra de latencias está vacía.")
    if not 0 < percentil <= 100:
        raise ValueError("El percentil debe estar entre 0 (excluido) y 100.")
    ordenados = sorted(valores)
    rango = math.ceil(percentil / 100 * len(ordenados))
    return ordenados[rango - 1]


def resumen_roba(ruta: Path) -> RobaOperacion:
    """Suma intentos, éxitos y puntos de Roba la Bóveda de todas las sesiones.

    Solo lee `categoria`, `exito` y `puntos`: el texto saneado no sale.

    Args:
        ruta: base `roba.sqlite`.

    Returns:
        El bloque `roba`; en cero si la base no existe.
    """
    filas = _consultar(
        ruta,
        "SELECT categoria, COUNT(*), COALESCE(SUM(exito), 0), COALESCE(SUM(puntos), 0) "
        "FROM intentos GROUP BY categoria",
    )
    resumen = RobaOperacion()
    for categoria, intentos, exitos, puntos in filas:
        resumen.intentos += int(intentos)
        resumen.exitos += int(exitos)
        resumen.puntos += int(puntos)
        if int(exitos) > 0:
            resumen.por_categoria[str(categoria)] = int(exitos)
    return resumen


def _consultar(ruta: Path, sql: str, parametros: Sequence[object] = ()) -> list[tuple]:
    """Ejecuta una consulta en modo solo lectura y tolera bases ausentes.

    Args:
        ruta: archivo SQLite.
        sql: consulta de lectura.
        parametros: valores de los `?` de la consulta.

    Returns:
        Las filas, o una lista vacía si la base no existe o la tabla no está.
    """
    if not ruta.is_file():
        return []
    uri = f"{ruta.resolve().as_uri()}?mode=ro"
    try:
        with closing(sqlite3.connect(uri, uri=True)) as conexion:
            return list(conexion.execute(sql, tuple(parametros)).fetchall())
    except sqlite3.Error:
        return []


def _leer_toml(ruta: Path) -> dict[str, object]:
    """Lee un TOML si existe; si falta o está mal formado, devuelve un dict vacío.

    Args:
        ruta: archivo TOML.

    Returns:
        El contenido como diccionario.
    """
    if not ruta.is_file():
        return {}
    try:
        with ruta.open("rb") as fh:
            return tomllib.load(fh)
    except (OSError, tomllib.TOMLDecodeError):
        return {}
