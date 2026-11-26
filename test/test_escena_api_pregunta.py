"""Pruebas de `POST /api/escena/pregunta`, la ruta de la tecla Q de la pantalla.

Sin red ni DeepSeek: el respondedor real corre en modo demo (sin modelo) y
responde con la ficha de `config/escena.toml [preguntas]`.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from banco_occidente_corpus.escena import respondedor as modulo
from banco_occidente_corpus.escena.api import crear_router_escena
from banco_occidente_corpus.escena.contratos import TurnoEscena
from banco_occidente_corpus.escena.respondedor import crear_respondedor, tema_del_turno

RUTA = "/api/escena/pregunta"
RAIZ = Path(__file__).resolve().parents[1]


def _cliente(respondedor: modulo.Respondedor | None = None) -> TestClient:
    """App mínima con el router de la escena y el respondedor dado."""
    app = FastAPI()
    app.include_router(crear_router_escena(respondedor=respondedor))
    return TestClient(app)


@pytest.fixture(scope="module")
def real() -> modulo.Respondedor:
    """Respondedor real en modo demo: ficha y recuperador, sin modelo."""
    with pytest.MonkeyPatch.context() as parche:
        parche.setenv("SUCURSAL_DEMO", "1")
        parche.delenv("DEEPSEEK_API_KEY", raising=False)
        return crear_respondedor()


@pytest.fixture(scope="module")
def cliente(real: modulo.Respondedor) -> TestClient:
    """Cliente con el respondedor real en modo demo."""
    return _cliente(real)


def test_la_ficha_responde_con_un_turno_de_pana(cliente: TestClient) -> None:
    """Una pregunta de PRESENTADOR.md vuelve con su respuesta fija y su fuente."""
    respuesta = cliente.post(RUTA, json={"pregunta": "¿Qué es este proyecto?"})
    assert respuesta.status_code == 200
    datos = respuesta.json()
    assert datos["tema"] == "ficha"
    turno = TurnoEscena.model_validate(datos["turno"])
    assert turno.personaje == "pana"
    assert turno.id == "pana.pregunta.fija.proyecto"
    assert "Sucursal 1965" in turno.texto
    assert "Fuente:" not in turno.texto


@pytest.mark.parametrize(
    "pregunta",
    [
        "Cuéntame del proyecto",
        "Cuéntanos del proyecto",
        "Háblame del proyecto",
        "Dame un resumen del proyecto",
        "¿En qué consiste el proyecto?",
    ],
)
def test_cuentame_del_proyecto_no_cae_al_rechazo(cliente: TestClient, pregunta: str) -> None:
    """La pregunta más probable del jurado se responde con la ficha del proyecto.

    Antes caía a BM25 con un fragmento que no hablaba del proyecto y el modelo
    contestaba que no encontraba información.
    """
    datos = cliente.post(RUTA, json={"pregunta": pregunta}).json()
    assert datos["tema"] == "ficha"
    assert datos["turno"]["id"] == "pana.pregunta.fija.proyecto"


def test_por_que_deepseek_sale_de_la_ficha(cliente: TestClient) -> None:
    """Las preguntas de respaldo del pitch (docs/PITCH.md) tienen respuesta fija."""
    datos = cliente.post(RUTA, json={"pregunta": "¿Por qué DeepSeek?"}).json()
    assert datos["tema"] == "ficha"
    assert datos["turno"]["id"] == "pana.pregunta.fija.deepseek"


def test_datos_personales_no_se_procesan(cliente: TestClient) -> None:
    """Un teléfono en la pregunta recibe la frase de la Ley 1581, sin repetirlo."""
    datos = cliente.post(RUTA, json={"pregunta": "Mi celular es 3001234567, ¿me ayudan?"}).json()
    assert datos["tema"] == "datos_personales"
    assert "3001234567" not in datos["turno"]["texto"]


def test_fuera_de_tema_usa_el_rechazo(cliente: TestClient) -> None:
    """Lo que no es del proyecto vuelve con el rechazo, que la pantalla reconoce."""
    datos = cliente.post(RUTA, json={"pregunta": "¿Qué clima hace hoy en Cali?"}).json()
    assert datos["tema"] == "fuera_de_tema"
    assert datos["turno"]["id"] == "pana.pregunta.rechazo.v1"


def test_la_audiencia_no_viaja_en_la_peticion(cliente: TestClient) -> None:
    """Un campo extra (por ejemplo, `audiencia`) se rechaza: la fija el servidor."""
    respuesta = cliente.post(RUTA, json={"pregunta": "¿Qué es Pana?", "audiencia": "equipo"})
    assert respuesta.status_code == 422


@pytest.mark.parametrize("pregunta", ["", "x" * 301])
def test_largo_invalido_es_422(cliente: TestClient, pregunta: str) -> None:
    """Vacía o de más de 300 caracteres (el mismo tope de anfitrion.js)."""
    assert cliente.post(RUTA, json={"pregunta": pregunta}).status_code == 422


def test_pregunta_que_queda_vacia_es_422() -> None:
    """Si `responder_pregunta` la deja vacía al sanearla, la ruta no se cae."""

    def vacia(_pregunta: str) -> TurnoEscena:
        raise ValueError("vacía")

    assert _cliente(vacia).post(RUTA, json={"pregunta": "   "}).status_code == 422


def test_el_respondedor_se_crea_una_sola_vez(monkeypatch: pytest.MonkeyPatch) -> None:
    """La ficha y el índice se arman en la primera pregunta y se reutilizan."""
    creados: list[int] = []

    def fabrica() -> modulo.Respondedor:
        creados.append(1)
        return lambda _pregunta: (_ for _ in ()).throw(ValueError("sin uso"))

    monkeypatch.setattr(modulo, "_RESPONDEDOR", None)
    monkeypatch.setattr(modulo, "crear_respondedor", fabrica)
    primero = modulo.respondedor_compartido()
    assert modulo.respondedor_compartido() is primero
    assert creados == [1]


@pytest.mark.parametrize(
    ("identificador", "tema"),
    [
        ("pana.pregunta.fija.equipo", "ficha"),
        ("pana.pregunta.proyecto.v1", "proyecto"),
        ("pana.pregunta.rechazo.v1", "fuera_de_tema"),
        ("pana.pregunta.pii.v1", "datos_personales"),
        ("pana.pregunta.respaldo.v1", "respaldo"),
    ],
)
def test_tema_del_turno(real: modulo.Respondedor, identificador: str, tema: str) -> None:
    """El tema que ve la pantalla sale del id del turno."""
    turno = real("¿Qué es este proyecto?").model_copy(update={"id": identificador})
    assert tema_del_turno(turno) == tema


def test_la_app_monta_la_ruta() -> None:
    """La app real expone la ruta (antes la tecla Q recibía un 404)."""
    especificacion = importlib.util.spec_from_file_location("arranque_pregunta", RAIZ / "app.py")
    assert especificacion is not None and especificacion.loader is not None
    aplicacion = importlib.util.module_from_spec(especificacion)
    especificacion.loader.exec_module(aplicacion)
    assert RUTA in aplicacion.app.openapi()["paths"]
