"""Pruebas del arranque de la app web (tarea 15.3), sin red y sin navegador.

Usan ``TestClient`` de FastAPI: no abren ningún puerto.
"""

from __future__ import annotations

import importlib.util
import threading
from pathlib import Path
from types import ModuleType

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from banco_occidente_corpus.canal.configuracion import cargar_configuracion_canal
from banco_occidente_corpus.config import load_config
from banco_occidente_corpus.sucursal.ajustes import ConfiguracionSucursal
from banco_occidente_corpus.sucursal.transmision import TransmisionTurno

RAIZ = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def modulo_app() -> ModuleType:
    """Carga ``app.py`` por ruta, para no confundirlo con la carpeta ``app/``."""
    spec = importlib.util.spec_from_file_location("arranque_sucursal", RAIZ / "app.py")
    assert spec is not None and spec.loader is not None
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


@pytest.fixture(scope="module")
def cliente(modulo_app: ModuleType) -> TestClient:
    """Cliente de prueba sobre la app real de la sucursal."""
    return TestClient(modulo_app.app)


def test_escucha_solo_en_localhost(modulo_app: ModuleType) -> None:
    """La escucha configurada es ``127.0.0.1:8000``, nunca un host público."""
    assert modulo_app.HOST == "127.0.0.1"
    assert modulo_app.PUERTO == 8000


def test_raiz_sirve_el_html_de_la_sucursal(cliente: TestClient) -> None:
    """``/`` devuelve ``index.html`` con la navegación de la sucursal."""
    respuesta = cliente.get("/")
    assert respuesta.status_code == 200
    assert "text/html" in respuesta.headers["content-type"]
    assert "Sucursal 1965" in respuesta.text


@pytest.mark.parametrize(
    "ruta",
    [
        "/estilos.css",
        "/app.js",
        "/comun.js",
        "/vistas/boveda.js",
        "/vistas/ventanilla.js",
        "/datos-ejemplo/estado.json",
        "/datos-ejemplo/preguntar.json",
    ],
)
def test_sirve_los_archivos_de_la_app(cliente: TestClient, ruta: str) -> None:
    """Los estáticos de ``app/web/`` se sirven con su ruta relativa."""
    assert cliente.get(ruta).status_code == 200


@pytest.mark.parametrize(
    "ruta",
    [
        "/escena.html",
        "/escena/escena.js",
        "/escena/contrato.js",
        "/escena/escena.css",
        "/escena/respaldo.js",
        "/escena/traza.js",
    ],
)
def test_la_app_sirve_la_pantalla_de_la_escena(cliente: TestClient, ruta: str) -> None:
    """La escena es una página aparte servida por la app real (tarea 6.9)."""
    assert cliente.get(ruta).status_code == 200


def test_la_escena_trae_sus_botones(cliente: TestClient) -> None:
    """``escena.html`` trae los botones de quien presenta, incluido el plan B."""
    html = cliente.get("/escena.html").text
    for texto in (
        "Empezar",
        "Siguiente turno",
        "Reiniciar",
        "Preguntas (Q)",
        "Núcleo (N)",
        "Trazabilidad (T)",
        "Solo subtítulos",
    ):
        assert texto in html, texto
    assert 'aria-live="polite"' in html


def test_la_sucursal_no_enlaza_la_escena(cliente: TestClient) -> None:
    """La escena no entra en la SPA: ``index.html`` y ``app.js`` no la enlazan."""
    assert "escena.html" not in cliente.get("/").text
    assert "escena.html" not in cliente.get("/app.js").text


def test_la_api_responde_estado(cliente: TestClient) -> None:
    """Con el PR 10 la API existe y ``/api/estado`` trae los seis campos."""
    respuesta = cliente.get("/api/estado")

    assert respuesta.status_code == 200
    assert "indice_listo" in respuesta.json()


def test_crear_app_acepta_otra_carpeta(modulo_app: ModuleType, tmp_path: Path) -> None:
    """``crear_app`` sirve la carpeta que se le indique."""
    (tmp_path / "index.html").write_text("<p>prueba</p>", encoding="utf-8")
    respuesta = TestClient(modulo_app.crear_app(tmp_path)).get("/")

    assert respuesta.text == "<p>prueba</p>"


def _app_de_prueba(modulo_app: ModuleType, raiz: Path, *, demo: bool) -> FastAPI:
    """App con la raíz del corpus en una carpeta temporal y sin red."""
    (raiz / "index.html").write_text("<p>prueba</p>", encoding="utf-8")
    config = load_config()
    config.paths.root = raiz
    return modulo_app.crear_app(
        raiz,
        config=config,
        ajustes=ConfiguracionSucursal(demo=demo),
    )


def test_health_sin_indice_responde_503(modulo_app: ModuleType, tmp_path: Path) -> None:
    """Sin índice y fuera del demo, ``/health`` avisa que falta la Bóveda."""
    respuesta = TestClient(_app_de_prueba(modulo_app, tmp_path, demo=False)).get("/health")

    assert respuesta.status_code == 503
    datos = respuesta.json()
    assert datos["estado"] == "degradado"
    assert datos["indice_listo"] is False
    assert datos["fragmentos_indexados"] == 0


def test_health_con_indice_responde_200(modulo_app: ModuleType, tmp_path: Path) -> None:
    """Con ``indice.json`` presente, ``/health`` lo cuenta sin llamar a Ollama."""
    carpeta = tmp_path / "data" / "boveda"
    carpeta.mkdir(parents=True)
    (carpeta / "indice.json").write_text(
        '{"fragmentos": 874, "modelo": "nomic-embed-text-v2-moe"}',
        encoding="utf-8",
    )

    respuesta = TestClient(_app_de_prueba(modulo_app, tmp_path, demo=False)).get("/health")

    assert respuesta.status_code == 200
    datos = respuesta.json()
    assert datos["estado"] == "ok"
    assert datos["indice_listo"] is True
    assert datos["fragmentos_indexados"] == 874
    assert datos["modelo_embeddings"] == "nomic-embed-text-v2-moe"


def test_health_en_demo_responde_200(modulo_app: ModuleType, tmp_path: Path) -> None:
    """El modo demo responde ``ok`` aunque no haya índice."""
    respuesta = TestClient(_app_de_prueba(modulo_app, tmp_path, demo=True)).get("/health")

    assert respuesta.status_code == 200
    assert respuesta.json()["modo_demo"] is True


def test_health_no_expone_claves_ni_rutas(modulo_app: ModuleType, tmp_path: Path) -> None:
    """El chequeo solo publica booleanos y conteos, nada del entorno."""
    datos = TestClient(_app_de_prueba(modulo_app, tmp_path, demo=False)).get("/health").json()

    assert set(datos) == {
        "estado",
        "indice_listo",
        "fragmentos_indexados",
        "modelo_embeddings",
        "modo_demo",
    }


def test_main_acota_la_espera_del_apagado(
    modulo_app: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """``main`` limita la espera de uvicorn para que Ctrl + C siempre termine."""
    llamadas: list[dict[str, object]] = []

    def run_falso(aplicacion: object, **opciones: object) -> None:
        """Registra la llamada a uvicorn en lugar de abrir un puerto."""
        llamadas.append({"app": aplicacion, **opciones})

    monkeypatch.setattr(modulo_app.uvicorn, "run", run_falso)
    modulo_app.main()
    capsys.readouterr()

    assert llamadas[0]["timeout_graceful_shutdown"] == (modulo_app.ESPERA_APAGADO_SEGUNDOS)
    assert modulo_app.ESPERA_APAGADO_SEGUNDOS > 0


def test_el_apagado_suelta_las_transmisiones(modulo_app: ModuleType, tmp_path: Path) -> None:
    """Al cerrar la app, el ciclo de vida corta un stream que sigue abierto."""
    suelta = threading.Event()

    def atender() -> dict[str, object]:
        """Se queda esperando, como un turno a mitad del modelo."""
        suelta.wait(10)
        return {}

    app = _app_de_prueba(modulo_app, tmp_path, demo=False)
    transmision = TransmisionTurno(atender).iniciar()

    with TestClient(app):
        pass

    assert list(transmision.eventos_sse()) == []
    suelta.set()


def test_crear_app_purga_los_datos_vencidos_del_canal(
    modulo_app: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Al arrancar se cumplen los plazos de casos, entrevista y resultado."""
    monkeypatch.setenv("WHATSAPP_ID_SALT", "sal-de-prueba")
    creadas: dict[str, list[dict[str, object]]] = {"maquina": [], "entrevista": []}
    purgas: list[str] = []

    class MaquinaFalsa:
        """Reemplazo de la máquina de consentimiento para observar el arranque."""

        def __init__(self, *args: object, **kwargs: object) -> None:
            creadas["maquina"].append(dict(kwargs))

        def purgar_casos_vencidos(self, momento: object | None = None) -> int:
            """Anota la purga de los casos."""
            purgas.append("casos")
            return 0

    class EntrevistaFalsa:
        """Reemplazo de la entrevista para observar la purga del arranque."""

        def __init__(self, *args: object, **kwargs: object) -> None:
            creadas["entrevista"].append(dict(kwargs))

        def purgar_vencidos(self, momento: object | None = None) -> int:
            """Anota la purga de entrevistas y resultados."""
            purgas.append("entrevista")
            return 0

    monkeypatch.setattr(modulo_app, "MaquinaConsentimiento", MaquinaFalsa)
    monkeypatch.setattr(modulo_app, "EntrevistaCanal", EntrevistaFalsa)

    modulo_app.crear_app(tmp_path)

    canal = cargar_configuracion_canal()
    assert purgas == ["casos", "entrevista"]
    assert creadas["maquina"][0]["retencion_dias"] == canal.retencion_dias
    assert creadas["entrevista"][0]["ttl_minutos"] == canal.entrevista_ttl_minutos


def test_la_api_de_la_escena_esta_montada(cliente: TestClient) -> None:
    """El router de la escena responde antes de los estaticos."""
    respuesta = cliente.get("/api/escena/opciones")
    assert respuesta.status_code == 200
    assert len(respuesta.json()["preguntas"]) == 4


def test_la_pantalla_de_la_escena_se_sirve_aparte(cliente: TestClient) -> None:
    """La escena abre como pagina aparte, sin pasar por la SPA."""
    respuesta = cliente.get("/escena.html")
    assert respuesta.status_code == 200
    assert "Pana vs. el gota a gota" in respuesta.text
