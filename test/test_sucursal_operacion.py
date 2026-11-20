"""Pruebas sin red de ``GET /api/operacion`` (OpenSpec corresponsal-whatsapp, 8.7).

Crean bases SQLite de prueba con el esquema de ``design.md`` y comprueban que
el resumen cuenta bien, separa la caché, marca las muestras pequeñas, no
devuelve números, nombres ni textos y funciona con la base vacía.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from test_sucursal_api import preparar

from banco_occidente_corpus.sucursal.operacion import (
    RUTA_CONFIG_WHATSAPP,
    RUTA_LATENCIAS,
    RUTA_ROBA,
    RUTA_WHATSAPP,
    VARIABLES_CANAL,
    OperacionRespuesta,
    estado_canal,
    percentil_nearest_rank,
    resumen_operacion,
)

RAIZ = Path(__file__).resolve().parents[1]
EJEMPLO = RAIZ / "app" / "web" / "datos-ejemplo" / "operacion.json"
AHORA = datetime.fromisoformat("2026-11-18T19:30:00-05:00")
HUELLA = "a" * 64
#: Número ficticio que nunca debe aparecer en la respuesta.
NUMERO_FICTICIO = "573000000000"

ESQUEMA_CANAL = """
CREATE TABLE mensajes (id_mensaje TEXT PRIMARY KEY, usuario_id TEXT NOT NULL,
    estado TEXT NOT NULL, recibido_en TEXT NOT NULL, procesado_en TEXT);
CREATE TABLE consentimientos (usuario_id TEXT PRIMARY KEY, version TEXT NOT NULL,
    aceptado_en TEXT NOT NULL, revocado_en TEXT);
CREATE TABLE envios (clave TEXT PRIMARY KEY, id_mensaje TEXT NOT NULL,
    usuario_id TEXT NOT NULL, estado TEXT NOT NULL, creado_en TEXT NOT NULL);
CREATE TABLE casos (id_caso TEXT PRIMARY KEY, usuario_id TEXT NOT NULL,
    motivo TEXT NOT NULL, semaforo TEXT NOT NULL, resultado_json TEXT NOT NULL,
    estado TEXT NOT NULL, creado_en TEXT NOT NULL);
"""


def ejecutar(ruta: Path, script: str, filas: dict[str, list[tuple]] | None = None) -> None:
    """Crea la base ``ruta`` con ``script`` e inserta ``filas`` por tabla."""
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(ruta)) as conexion:
        conexion.executescript(script)
        for tabla, valores in (filas or {}).items():
            marcas = ",".join("?" * len(valores[0]))
            conexion.executemany(f"INSERT INTO {tabla} VALUES ({marcas})", valores)
        conexion.commit()


def poblar_canal(raiz: Path) -> None:
    """Base del canal con tres usuarios, cinco mensajes y tres casos."""
    ejecutar(
        raiz / RUTA_WHATSAPP,
        ESQUEMA_CANAL,
        {
            "mensajes": [
                ("m1", "u1", "respondido", "2026-11-18T10:00", "2026-11-18T10:01"),
                ("m2", "u1", "respondido", "2026-11-18T10:02", "2026-11-18T10:03"),
                ("m3", "u2", "error", "2026-11-18T10:04", None),
                ("m4", "u2", "encolado", "2026-11-18T10:05", None),
                ("m5", "u3", "recibido", "2026-11-18T10:06", None),
            ],
            "consentimientos": [
                ("u1", "2026-11", "2026-11-18T09:59", None),
                ("u2", "2026-11", "2026-11-18T09:59", "2026-11-18T11:00"),
            ],
            "casos": [
                (
                    "caso-1",
                    "u1",
                    "semaforo_rojo",
                    "rojo",
                    f'{{"tel": "{NUMERO_FICTICIO}"}}',
                    "pendiente",
                    "2026-11-18T10:10",
                ),
                (
                    "caso-2",
                    "u2",
                    "solicitud_usuario",
                    "amarillo",
                    "{}",
                    "descartado",
                    "2026-11-18T10:11",
                ),
                (
                    "caso-3",
                    "u1",
                    "solicitud_usuario",
                    "verde",
                    "{}",
                    "contactado",
                    "2026-11-18T10:12",
                ),
            ],
        },
    )


def poblar_latencias(raiz: Path, n_webhook: int = 30, n_hitl: int = 5) -> None:
    """Latencias del webhook (1..n ms), del HITL y dos corridas con caché."""
    filas = [("webhook", float(ms), 0, "2026-11-18") for ms in range(1, n_webhook + 1)]
    filas += [("hitl", 500.0 + ms, 0, "2026-11-18") for ms in range(n_hitl)]
    filas += [("webhook", 4.0, 1, "2026-11-18"), ("webhook", 6.0, 1, "2026-11-18")]
    ejecutar(
        raiz / RUTA_LATENCIAS,
        "CREATE TABLE latencias (flujo TEXT, ms REAL, cache INTEGER, creado TEXT);",
        {"latencias": filas},
    )


def poblar_roba(raiz: Path) -> None:
    """Marcador con dos inyecciones (una exitosa) y una pregunta legítima."""
    ejecutar(
        raiz / RUTA_ROBA,
        "CREATE TABLE intentos (sesion TEXT, categoria TEXT, hash TEXT, texto TEXT,"
        " exito INTEGER, puntos INTEGER, creado TEXT);",
        {
            "intentos": [
                ("s1", "inyeccion", "h1", "ignora todo", 1, 3, "2026-11-18"),
                ("s1", "inyeccion", "h2", "actua como", 0, 0, "2026-11-18"),
                ("s2", "legitimo", "h3", "cuota de manejo", 0, 0, "2026-11-18"),
            ]
        },
    )


def entorno_completo(modo: str = "") -> dict[str, str]:
    """Variables del canal con valores de relleno (no son secretos reales)."""
    entorno = dict.fromkeys(VARIABLES_CANAL, "relleno")
    if modo:
        entorno["WHATSAPP_MODO"] = modo
    return entorno


def test_base_vacia_responde_en_cero_sin_crear_archivos(tmp_path: Path) -> None:
    """Sin bases ni configuración, todo sale en cero y no se crea nada."""
    resumen = resumen_operacion(tmp_path, entorno={}, ahora=AHORA)
    assert resumen.canal.model_dump() == {
        "configurado": False,
        "modo": "deshabilitado",
        "numeros_autorizados": 0,
    }
    assert resumen.mensajes.recibidos == 0
    assert resumen.mensajes.duplicados is None
    assert resumen.casos.lista == []
    assert resumen.latencia == {} and resumen.latencia_cache == {}
    assert resumen.roba.intentos == 0
    assert resumen.generado == "2026-11-18T19:30:00-05:00"
    assert not (tmp_path / "data").exists()


def test_cuenta_mensajes_consentimientos_y_casos(tmp_path: Path) -> None:
    """Los conteos salen de las tablas del esquema del diseño."""
    poblar_canal(tmp_path)
    resumen = resumen_operacion(tmp_path, entorno={}, ahora=AHORA)
    assert resumen.mensajes.model_dump() == {
        "recibidos": 5,
        "respondidos": 2,
        "errores": 1,
        "pendientes": 2,
        "duplicados": None,
    }
    assert resumen.consentimientos.model_dump() == {"aceptados": 1, "pendientes": 1, "revocados": 1}
    assert (resumen.casos.pendientes, resumen.casos.contactados, resumen.casos.descartados) == (
        1,
        1,
        1,
    )
    assert [caso.id for caso in resumen.casos.lista] == ["caso-1"]
    assert resumen.casos.lista[0].semaforo == "rojo"


def test_respuesta_sin_usuarios_ni_textos(tmp_path: Path) -> None:
    """Ni ids de usuario, ni el resultado del diagnóstico, ni textos del juego."""
    poblar_canal(tmp_path)
    poblar_roba(tmp_path)
    crudo = resumen_operacion(tmp_path, entorno={}, ahora=AHORA).model_dump_json()
    for prohibido in (
        '"u1"',
        '"u2"',
        '"u3"',
        NUMERO_FICTICIO,
        "ignora todo",
        "usuario_id",
        "resultado_json",
    ):
        assert prohibido not in crudo, prohibido


def test_latencia_nearest_rank_y_cache_aparte(tmp_path: Path) -> None:
    """Con 1..30 ms, p50 = 15 y p95 = 29; la caché va en su propio bloque."""
    poblar_latencias(tmp_path)
    resumen = resumen_operacion(tmp_path, entorno={}, ahora=AHORA)
    webhook = resumen.latencia["webhook"]
    assert (webhook.p50_ms, webhook.p95_ms, webhook.n, webhook.suficiente) == (15.0, 29.0, 30, True)
    assert resumen.latencia["hitl"].suficiente is False
    assert resumen.latencia["hitl"].n == 5
    cache = resumen.latencia_cache["webhook"]
    assert (cache.p50_ms, cache.n, cache.suficiente) == (4.0, 2, False)


def test_29_corridas_no_son_concluyentes(tmp_path: Path) -> None:
    """La regla de mínimo 30 corridas marca 29 como insuficiente."""
    poblar_latencias(tmp_path, n_webhook=29)
    assert resumen_operacion(tmp_path, entorno={}).latencia["webhook"].suficiente is False


@pytest.mark.parametrize(
    ("valores", "percentil", "esperado"),
    [
        ([5.0], 50, 5.0),
        ([1.0, 2.0, 3.0, 4.0], 50, 2.0),
        ([1.0, 2.0, 3.0, 4.0], 95, 4.0),
        ([3.0, 1.0, 2.0], 100, 3.0),
    ],
)
def test_percentil_nearest_rank(valores: list[float], percentil: float, esperado: float) -> None:
    """El percentil es un valor de la muestra, sin interpolar."""
    assert percentil_nearest_rank(valores, percentil) == esperado


@pytest.mark.parametrize(("valores", "percentil"), [([], 50), ([1.0], 0), ([1.0], 101)])
def test_percentil_rechaza_entradas_invalidas(valores: list[float], percentil: float) -> None:
    """Muestra vacía o percentil fuera de rango levantan ValueError."""
    with pytest.raises(ValueError):
        percentil_nearest_rank(valores, percentil)


def test_roba_suma_todas_las_sesiones(tmp_path: Path) -> None:
    """Intentos, éxitos y puntos globales; por categoría solo los éxitos."""
    poblar_roba(tmp_path)
    roba = resumen_operacion(tmp_path, entorno={}).roba
    assert roba.model_dump() == {
        "intentos": 3,
        "exitos": 1,
        "puntos": 3,
        "por_categoria": {"inyeccion": 1},
    }


def test_canal_configurado_solo_con_las_cinco_variables(tmp_path: Path) -> None:
    """Falta una variable → deshabilitado; con todas, el modo sale del entorno o del TOML."""
    config = tmp_path / RUTA_CONFIG_WHATSAPP
    config.parent.mkdir(parents=True)
    config.write_text(
        f'[canal]\nmodo = "real"\n[autorizados]\nhuellas = ["{HUELLA}", "<huella-2>", "{HUELLA}"]\n',
        encoding="utf-8",
    )
    incompleto = entorno_completo()
    del incompleto["WHATSAPP_ID_SALT"]
    assert estado_canal(tmp_path, incompleto).modo == "deshabilitado"
    assert estado_canal(tmp_path, entorno_completo()).model_dump() == {
        "configurado": True,
        "modo": "real",
        "numeros_autorizados": 2,
    }
    assert estado_canal(tmp_path, entorno_completo("falso")).modo == "falso"


def test_canal_no_devuelve_valores_del_entorno(tmp_path: Path) -> None:
    """Los valores de las variables nunca aparecen en la respuesta."""
    entorno = {nombre: f"secreto-{nombre}" for nombre in VARIABLES_CANAL}
    crudo = resumen_operacion(tmp_path, entorno=entorno).model_dump_json()
    assert "secreto-" not in crudo


def test_base_con_otro_esquema_no_rompe_la_ruta(tmp_path: Path) -> None:
    """Una base corrupta o sin las tablas esperadas deja el bloque en cero."""
    (tmp_path / RUTA_WHATSAPP).parent.mkdir(parents=True)
    (tmp_path / RUTA_WHATSAPP).write_bytes(b"esto no es sqlite")
    ejecutar(tmp_path / RUTA_ROBA, "CREATE TABLE otra (x INTEGER);")
    resumen = resumen_operacion(tmp_path, entorno={})
    assert resumen.mensajes.recibidos == 0
    assert resumen.roba.intentos == 0


def test_ejemplo_de_la_web_cumple_el_modelo() -> None:
    """``datos-ejemplo/operacion.json`` valida contra ``OperacionRespuesta`` (8.8)."""
    datos = json.loads(EJEMPLO.read_text(encoding="utf-8"))
    modelo = OperacionRespuesta.model_validate(datos)
    assert set(modelo.model_dump()) == set(datos)


def test_endpoint_operacion_con_base_vacia(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """``GET /api/operacion`` responde 200 sin bases y sin variables del canal."""
    for nombre in (*VARIABLES_CANAL, "WHATSAPP_MODO"):
        monkeypatch.delenv(nombre, raising=False)
    cliente, _ = preparar(tmp_path)
    respuesta = cliente.get("/api/operacion")
    assert respuesta.status_code == 200
    datos = respuesta.json()
    assert datos["canal"]["modo"] == "deshabilitado"
    assert set(datos) == set(json.loads(EJEMPLO.read_text(encoding="utf-8")))


def test_endpoint_operacion_con_datos(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Con bases pobladas, la ruta devuelve los mismos conteos que el servicio."""
    for nombre in (*VARIABLES_CANAL, "WHATSAPP_MODO"):
        monkeypatch.delenv(nombre, raising=False)
    cliente: TestClient
    cliente, config = preparar(tmp_path)
    poblar_canal(config.paths.root)
    poblar_latencias(config.paths.root)
    datos = cliente.get("/api/operacion").json()
    assert datos["mensajes"]["recibidos"] == 5
    assert datos["latencia"]["webhook"]["p95_ms"] == 29.0
    assert NUMERO_FICTICIO not in json.dumps(datos)
