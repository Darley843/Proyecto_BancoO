"""Pruebas sin red de la API local: estado, datos y estados ausentes."""

from __future__ import annotations

import importlib.util
import json
from datetime import date
from pathlib import Path
from types import ModuleType

from fastapi.testclient import TestClient

from banco_occidente_corpus.config import Config, Paths
from banco_occidente_corpus.sucursal.ajustes import ConfiguracionSucursal
from banco_occidente_corpus.sucursal.costo import GastoDiario
from banco_occidente_corpus.tablero.tipos import Fila, escribir_filas

RAIZ = Path(__file__).resolve().parents[1]
URL = "https://www.bancodeoccidente.com.co/tarifas"


def cargar_app() -> ModuleType:
    """Carga el `app.py` de la raíz como módulo, igual que la app real."""
    especificacion = importlib.util.spec_from_file_location(
        "arranque_sucursal_api", RAIZ / "app.py"
    )
    assert especificacion and especificacion.loader
    modulo = importlib.util.module_from_spec(especificacion)
    especificacion.loader.exec_module(modulo)
    return modulo


def make_config(tmp_path: Path) -> Config:
    """Configuración aislada con las rutas del corpus."""
    return Config(
        paths=Paths(
            root=tmp_path,
            raw=tmp_path / "data/raw",
            processed=tmp_path / "data/processed",
            gold=tmp_path / "data/gold",
            knowledge=tmp_path / "data/knowledge",
        )
    )


def fila(concepto: str = "Cuota de manejo tarjeta débito") -> Fila:
    """Fila de prueba para el CSV del Tablero."""
    return Fila(
        concepto=concepto,
        categoria="tarifas",
        valor="16.700",
        moneda="COP",
        recargos="",
        periodicidad="mensual",
        vigente_desde="2025-11-20",
        origen="tarifario",
        pagina="data/gold/documents/tarifas.md",
        fuente=URL,
    )


def preparar(tmp_path: Path, *, demo: bool = True) -> tuple[TestClient, Config]:
    """Crea la app con datos mínimos en tmp_path."""
    config = make_config(tmp_path)
    web = tmp_path / "web"
    web.mkdir(parents=True)
    (web / "index.html").write_text("<!doctype html><title>Sucursal</title>", encoding="utf-8")

    escribir_filas(
        tmp_path / "data/estructurados/tablero.csv",
        [fila(), fila("Cuota de manejo tarjeta crédito")],
    )
    indice = tmp_path / "data/boveda/indice.json"
    indice.parent.mkdir(parents=True)
    indice.write_text(
        json.dumps(
            {
                "modelo": "nomic-embed-text-v2-moe",
                "prefijos": True,
                "alcance": "base",
                "fragmentos": 10,
                "dimension": 768,
            }
        ),
        encoding="utf-8",
    )
    vestibulo = tmp_path / "config/vestibulo.toml"
    vestibulo.parent.mkdir(parents=True)
    vestibulo.write_text(
        '[[hito]]\nanio = 1965\ntexto = "Nace el banco"\nurl = "https://example.com"\n',
        encoding="utf-8",
    )
    ajustes = ConfiguracionSucursal(tope_diario_usd=0.2, cache_ttl_segundos=60, demo=demo)
    return TestClient(cargar_app().crear_app(web, config=config, ajustes=ajustes)), config


def test_estado_devuelve_los_seis_campos(tmp_path: Path) -> None:
    """El estado informa demo, gasto, tope e índice."""
    cliente, config = preparar(tmp_path)
    GastoDiario(config.paths.root / "data/asistente/gasto.sqlite").sumar(0.03, 100)

    respuesta = cliente.get("/api/estado")

    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    assert cuerpo["modo_demo"] is True
    assert cuerpo["gasto_hoy_usd"] == 0.03
    assert cuerpo["tope_usd"] == 0.2
    assert cuerpo["indice_listo"] is True
    assert cuerpo["fragmentos_indexados"] == 10
    assert cuerpo["modelo_embeddings"] == "nomic-embed-text-v2-moe"


def test_estado_sin_indice(tmp_path: Path) -> None:
    """Sin indice.json el estado lo declara y deja los conteos en cero."""
    cliente, config = preparar(tmp_path)
    (config.paths.root / "data/boveda/indice.json").unlink()

    cuerpo = cliente.get("/api/estado").json()

    assert cuerpo["indice_listo"] is False
    assert cuerpo["fragmentos_indexados"] == 0
    assert cuerpo["modelo_embeddings"] == ""


def test_tablero_filtra_por_texto(tmp_path: Path) -> None:
    """El filtro devuelve solo las filas cuyo concepto coincide."""
    cliente, _ = preparar(tmp_path)

    cuerpo = cliente.get("/api/tablero", params={"q": "débito"}).json()

    assert cuerpo["total"] == 1
    assert cuerpo["filas"][0]["valor"] == "16.700"
    assert cuerpo["filas"][0]["fuente"] == URL


def test_tablero_sin_coincidencias(tmp_path: Path) -> None:
    """Un filtro sin coincidencias devuelve una lista vacía, no un error."""
    cliente, _ = preparar(tmp_path)

    cuerpo = cliente.get("/api/tablero", params={"q": "inexistente"}).json()

    assert cuerpo == {"filas": [], "total": 0}


def test_mapa_ausente_es_explicable(tmp_path: Path) -> None:
    """Sin mapa.json la API no dibuja un mapa vacío como si hubiera datos."""
    cliente, _ = preparar(tmp_path)

    cuerpo = cliente.get("/api/boveda/mapa").json()

    assert cuerpo["disponible"] is False
    assert cuerpo["puntos"] == []
    assert cuerpo["pregunta"] is None
    assert "make indice" in cuerpo["error"]


def test_mapa_presente(tmp_path: Path) -> None:
    """Con mapa.json devuelve puntos, pregunta y top."""
    cliente, config = preparar(tmp_path)
    mapa = config.paths.root / "data/boveda/mapa.json"
    mapa.write_text(
        json.dumps(
            {
                "puntos": [{"x": 10.0, "y": 20.0, "seccion": "oferta", "titulo": "T"}],
                "pregunta": {"x": 1.0, "y": 2.0},
                "top": [{"id": "frag:1"}],
            }
        ),
        encoding="utf-8",
    )

    cuerpo = cliente.get("/api/boveda/mapa").json()

    assert cuerpo["disponible"] is True
    assert cuerpo["puntos"][0]["x"] == 10.0
    assert cuerpo["pregunta"] == {"x": 1.0, "y": 2.0}
    assert cuerpo["top"] == [{"id": "frag:1"}]


def test_pipeline_incluye_indexacion(tmp_path: Path) -> None:
    """El pipeline trae etapas y el estado de indexación."""
    cliente, _ = preparar(tmp_path)

    cuerpo = cliente.get("/api/pipeline").json()

    assert "etapas" in cuerpo
    assert cuerpo["indexacion"]["indice_listo"] is True
    assert cuerpo["indexacion"]["fragmentos_indexados"] == 10
    assert cuerpo["indexacion"]["alcance"] == "base"


def test_arqueo_ausente(tmp_path: Path) -> None:
    """Sin arqueo.json la respuesta declara disponible false."""
    cliente, _ = preparar(tmp_path)

    cuerpo = cliente.get("/api/arqueo").json()

    assert cuerpo["disponible"] is False
    assert cuerpo["datos"] == {}
    assert "make arqueo" in cuerpo["error"]


def test_arqueo_presente(tmp_path: Path) -> None:
    """Con arqueo.json devuelve su contenido."""
    cliente, config = preparar(tmp_path)
    ruta = config.paths.root / "data/evaluacion/arqueo.json"
    ruta.parent.mkdir(parents=True)
    ruta.write_text(json.dumps({"recuperacion": [], "evaluacion": {}}), encoding="utf-8")

    cuerpo = cliente.get("/api/arqueo").json()

    assert cuerpo["disponible"] is True
    assert cuerpo["datos"]["recuperacion"] == []
    assert cuerpo["error"] is None


def test_vestibulo_devuelve_hitos(tmp_path: Path) -> None:
    """Los hitos salen de config/vestibulo.toml."""
    cliente, _ = preparar(tmp_path)

    cuerpo = cliente.get("/api/vestibulo").json()

    assert cuerpo["hitos"] == [
        {"anio": 1965, "texto": "Nace el banco", "url": "https://example.com"}
    ]


def test_vestibulo_sin_config(tmp_path: Path) -> None:
    """Sin TOML devuelve una lista vacía, sin error."""
    cliente, config = preparar(tmp_path)
    (config.paths.root / "config/vestibulo.toml").unlink()

    assert cliente.get("/api/vestibulo").json() == {"hitos": []}


def test_gasto_se_acumula_en_el_dia(tmp_path: Path) -> None:
    """El estado refleja el gasto del día en la SQLite de la Sucursal."""
    cliente, config = preparar(tmp_path)
    gasto = GastoDiario(config.paths.root / "data/asistente/gasto.sqlite")
    gasto.sumar(0.10, 200)
    gasto.sumar(0.05, 100)

    cuerpo = cliente.get("/api/estado").json()

    assert cuerpo["gasto_hoy_usd"] == 0.15


def test_gasto_de_otro_dia_no_cuenta(tmp_path: Path) -> None:
    """El gasto de ayer no se mezcla con el de hoy."""
    cliente, config = preparar(tmp_path)
    gasto = GastoDiario(config.paths.root / "data/asistente/gasto.sqlite")
    gasto.sumar(0.50, 100, fecha=date(2020, 1, 1))

    assert cliente.get("/api/estado").json()["gasto_hoy_usd"] == 0.0
