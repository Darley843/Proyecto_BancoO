"""Pruebas sin red del costo, el gasto diario y la caché."""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from banco_occidente_corpus.sucursal.ajustes import (
    ConfiguracionSucursal,
    cargar_configuracion_sucursal,
    modo_demo,
    tope_efectivo,
)
from banco_occidente_corpus.sucursal.costo import (
    CacheRespuestas,
    GastoDiario,
    costo_de_uso,
    tarifas_para,
)


def uso(*, entrada: int = 0, salida: int = 0, cache: int = 0) -> dict[str, object]:
    """Construye métricas con la forma de `extraer_metricas`."""
    return {
        "uso": {
            "input_tokens": entrada,
            "output_tokens": salida,
            "input_token_details": {"cache_read": cache},
        }
    }


@pytest.mark.parametrize(
    ("momento", "pico"),
    [
        (datetime(2026, 11, 5, 2, 0, tzinfo=UTC), True),  # jueves 02:00
        (datetime(2026, 11, 5, 6, 0, tzinfo=UTC), True),  # borde de las 06:00
        (datetime(2026, 11, 5, 10, 0, tzinfo=UTC), False),  # borde de las 10:00
        (datetime(2026, 11, 5, 5, 0, tzinfo=UTC), False),
        (datetime(2026, 11, 7, 2, 0, tzinfo=UTC), False),  # sábado
    ],
)
def test_tarifas_por_franja(momento: datetime, pico: bool) -> None:
    """La tarifa pico aplica de lunes a viernes en las dos franjas UTC."""
    tarifas = tarifas_para(momento)

    if pico:
        assert tarifas.entrada == pytest.approx(0.30)
    else:
        assert tarifas.entrada == pytest.approx(0.15)


def test_costo_de_uso_sin_cache() -> None:
    """Un millón de tokens de entrada cuesta la tarifa valle completa."""
    costo, tokens = costo_de_uso(
        uso(entrada=1_000_000), tarifas_para(datetime(2026, 11, 5, 5, tzinfo=UTC))
    )

    assert costo == pytest.approx(0.15)
    assert tokens == 1_000_000


def test_costo_de_uso_con_cache_y_salida() -> None:
    """La caché se cobra aparte y la salida usa su propia tarifa."""
    detalle = uso(entrada=1_000_000, salida=1_000_000, cache=500_000)

    costo, tokens = costo_de_uso(detalle, tarifas_para(datetime(2026, 11, 5, 5, tzinfo=UTC)))

    assert costo == pytest.approx((500_000 * 0.15 + 500_000 * 0.003 + 1_000_000 * 0.60) / 1_000_000)
    assert tokens == 2_000_000


def test_costo_sin_uso_es_cero() -> None:
    """Sin métricas no hay costo ni tokens."""
    assert costo_de_uso(None, tarifas_para(datetime.now(UTC))) == (0.0, 0)


def test_gasto_diario_acumula_y_separa_dias(tmp_path: Path) -> None:
    """El gasto del día suma y no mezcla fechas."""
    gasto = GastoDiario(tmp_path / "gasto.sqlite")
    hoy = date(2026, 11, 5)

    gasto.sumar(0.05, 100, fecha=hoy)
    gasto.sumar(0.02, 50, llamadas=2, fecha=hoy)
    gasto.sumar(1.00, 1000, fecha=date(2026, 11, 4))

    assert gasto.hoy(hoy) == (pytest.approx(0.07), 3, 150)
    assert gasto.hoy(date(2026, 11, 4)) == (pytest.approx(1.0), 1, 1000)
    assert gasto.hoy(date(2026, 11, 3)) == (0.0, 0, 0)


def test_gasto_rechaza_negativos(tmp_path: Path) -> None:
    """No se puede sumar gasto negativo."""
    gasto = GastoDiario(tmp_path / "gasto.sqlite")

    with pytest.raises(ValueError):
        gasto.sumar(-0.01, 10)


def test_cache_clave_normaliza_tildes_y_mayusculas() -> None:
    """La misma pregunta con distinta caja o tilde comparte clave."""
    izquierda = CacheRespuestas.clave("¿Cuál es la CUOTA?", "B", "v2")
    derecha = CacheRespuestas.clave("cual es la cuota", "B", "v2")

    assert izquierda == derecha
    assert izquierda != CacheRespuestas.clave("¿Cuál es la cuota?", "T", "v2")
    assert izquierda != CacheRespuestas.clave("¿Cuál es la cuota?", "B", "v1")


def test_cache_guarda_y_devuelve(tmp_path: Path) -> None:
    """Una respuesta guardada se recupera mientras esté vigente."""
    cache = CacheRespuestas(tmp_path / "cache.sqlite", ttl_segundos=60)

    cache.guardar("clave", {"respuesta": "hola", "costo": 0.0})

    assert cache.obtener("clave") == {"respuesta": "hola", "costo": 0.0}
    assert cache.obtener("otra") is None


def test_cache_expira(tmp_path: Path) -> None:
    """Con TTL cero la entrada vence de inmediato."""
    cache = CacheRespuestas(tmp_path / "cache.sqlite", ttl_segundos=0)
    cache.guardar("clave", {"respuesta": "hola"})

    assert cache.obtener("clave") is None


def test_cache_limpiar(tmp_path: Path) -> None:
    """Limpiar borra todas las entradas."""
    cache = CacheRespuestas(tmp_path / "cache.sqlite", ttl_segundos=60)
    cache.guardar("a", {"x": 1})
    cache.guardar("b", {"x": 2})

    cache.limpiar()

    assert cache.obtener("a") is None
    assert cache.obtener("b") is None


def test_tope_efectivo_lee_entorno(monkeypatch: pytest.MonkeyPatch) -> None:
    """SUCURSAL_TOPE_USD sobrescribe el tope del TOML."""
    monkeypatch.setenv("SUCURSAL_TOPE_USD", "0.05")

    assert tope_efectivo(ConfiguracionSucursal(tope_diario_usd=0.2)) == pytest.approx(0.05)


def test_tope_efectivo_por_defecto(monkeypatch: pytest.MonkeyPatch) -> None:
    """Sin variable de entorno manda el valor del TOML."""
    monkeypatch.delenv("SUCURSAL_TOPE_USD", raising=False)

    assert tope_efectivo(ConfiguracionSucursal(tope_diario_usd=0.2)) == pytest.approx(0.2)


def test_config_lee_tope_y_ttl(tmp_path: Path) -> None:
    """La sección [sucursal] se carga con validación."""
    ruta = tmp_path / "sucursal.toml"
    ruta.write_text(
        "[sucursal]\ntope_diario_usd = 0.5\ncache_ttl_segundos = 30\n", encoding="utf-8"
    )

    ajustes = cargar_configuracion_sucursal(ruta)

    assert ajustes.tope_diario_usd == pytest.approx(0.5)
    assert ajustes.cache_ttl_segundos == 30


@pytest.mark.parametrize(
    "contenido",
    [
        "[sucursal]\ntope_diario_usd = 0\n",
        "[sucursal]\ntope_diario_usd = -1\n",
        "[sucursal]\ncache_ttl_segundos = -1\n",
    ],
)
def test_config_invalida(tmp_path: Path, contenido: str) -> None:
    """Un tope no positivo o un TTL negativo se rechazan."""
    ruta = tmp_path / "sucursal.toml"
    ruta.write_text(contenido, encoding="utf-8")

    with pytest.raises(ValueError):
        cargar_configuracion_sucursal(ruta)


def test_modo_demo_lee_entorno(monkeypatch: pytest.MonkeyPatch) -> None:
    """SUCURSAL_DEMO acepta 1, true o sí."""
    monkeypatch.setenv("SUCURSAL_DEMO", "1")

    assert modo_demo() is True
    monkeypatch.setenv("SUCURSAL_DEMO", "0")

    assert modo_demo() is False
