"""Pruebas de la API de la escena (tarea 5.6), sin red ni modelo real."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from banco_occidente_corpus.escena.api import (
    EscenaPeticion,
    NegociacionPeticion,
    ServicioEscenaReal,
    crear_router_escena,
)
from banco_occidente_corpus.escena.contratos import Escena, NegociacionEscena
from banco_occidente_corpus.escena.perfiles import perfil_seguro
from banco_occidente_corpus.escena.servicio import construir_escena, construir_negociacion

DEMO = {"SUCURSAL_DEMO": "1"}


class ServicioDemo(ServicioEscenaReal):
    """Servicio real con la negociación forzada a la política determinista."""

    def escena(self, peticion: EscenaPeticion) -> Escena:
        """Arma la fase 1 sin llamar a DeepSeek."""
        perfil, modo = self._perfil(peticion)
        return construir_escena(
            perfil,
            seleccion=peticion.seleccion,
            modo=modo,
            raiz=self.raiz,
            entorno=DEMO,
        )

    def negociacion(self, peticion: NegociacionPeticion) -> NegociacionEscena:
        """Arma la fase 2 con la política determinista."""
        perfil, _ = self._perfil(peticion)
        return construir_negociacion(
            perfil,
            seleccion=peticion.seleccion,
            raiz=self.raiz,
            entorno=DEMO,
        )


@pytest.fixture(scope="module")
def cliente(tmp_path_factory: pytest.TempPathFactory) -> TestClient:
    """Cliente con la API de la escena y una carpeta de respaldo vacía."""
    salida = tmp_path_factory.mktemp("escena")
    app = FastAPI()
    app.include_router(crear_router_escena(ServicioDemo(salida=salida)))
    return TestClient(app)


def test_opciones_trae_las_cuatro_preguntas(cliente: TestClient) -> None:
    """La API expone monto, ingresos, gastos y deudas con letras A–F."""
    datos = cliente.get("/api/escena/opciones").json()
    claves = [pregunta["clave"] for pregunta in datos["preguntas"]]
    assert claves == ["monto", "ingresos", "gastos", "deudas"]
    primera = datos["preguntas"][0]["opciones"][0]
    assert primera["letra"] == "A"
    assert primera["id"]
    assert primera["texto"]


def test_perfiles_trae_los_seguros_validados(cliente: TestClient) -> None:
    """Los perfiles seguros vienen con su color esperado y su validación."""
    datos = cliente.get("/api/escena/perfiles").json()
    assert len(datos["perfiles"]) >= 3
    for perfil in datos["perfiles"]:
        assert perfil["id"]
        assert perfil["esperado"] in {"verde", "amarillo", "rojo"}
        assert len(perfil["respuestas"]) == 4


def test_voluntario_con_semilla_es_repetible(cliente: TestClient) -> None:
    """La misma semilla da la misma fila y la misma silla."""
    cuerpo = {"semilla": 11}
    primera = cliente.post("/api/escena/voluntario", json=cuerpo).json()
    segunda = cliente.post("/api/escena/voluntario", json=cuerpo).json()
    assert primera == segunda
    assert 1 <= primera["fila"] <= primera["filas"]
    assert 1 <= primera["silla"] <= primera["sillas"]


def test_voluntario_rechaza_rangos_invalidos(cliente: TestClient) -> None:
    """Filas menores que 1 se rechazan con 422."""
    respuesta = cliente.post("/api/escena/voluntario", json={"filas": 0})
    assert respuesta.status_code == 422


def test_interpretar_una_letra(cliente: TestClient) -> None:
    """Una letra válida devuelve la tarjeta y su valor."""
    respuesta = cliente.post(
        "/api/escena/interpretar",
        json={"texto": "letra A", "pregunta": "monto"},
    )
    assert respuesta.status_code == 200
    datos = respuesta.json()
    assert datos["respuesta"]["letra"] == "A"
    assert datos["ajustado"] is False


def test_interpretar_letra_fuera_de_rango(cliente: TestClient) -> None:
    """Gastos solo llega a E: la F responde 422."""
    respuesta = cliente.post(
        "/api/escena/interpretar",
        json={"texto": "letra F", "pregunta": "gastos"},
    )
    assert respuesta.status_code == 422
    assert "A–E" in respuesta.json()["detail"]


def test_interpretar_no_repite_datos_personales(cliente: TestClient) -> None:
    """Un teléfono se rechaza sin devolverlo en el mensaje."""
    respuesta = cliente.post(
        "/api/escena/interpretar",
        json={"texto": "mi celular es 300 123 4567", "pregunta": "ingresos"},
    )
    assert respuesta.status_code == 422
    assert "300" not in respuesta.text


def test_escena_con_perfil_seguro(cliente: TestClient) -> None:
    """La fase 1 se arma desde un perfil seguro."""
    respuesta = cliente.post("/api/escena", json={"perfil_id": "verde_computador"})
    assert respuesta.status_code == 200
    datos = respuesta.json()
    assert datos["modo"] == "seguro"
    assert datos["turnos"]
    assert Decimal(datos["gota"]["monto"]) == Decimal(4_000_000)


def test_escena_con_respuestas(cliente: TestClient) -> None:
    """Las respuestas A–F se resuelven en el servidor."""
    respuestas = [
        {"pregunta": "monto", "letra": "A"},
        {"pregunta": "ingresos", "letra": "B"},
        {"pregunta": "gastos", "letra": "A"},
        {"pregunta": "deudas", "letra": "A"},
    ]
    respuesta = cliente.post(
        "/api/escena",
        json={"respuestas": respuestas, "confirmado": True},
    )
    assert respuesta.status_code == 200
    assert respuesta.json()["turnos"]


def test_escena_sin_confirmar_responde_409(cliente: TestClient) -> None:
    """Sin confirmación de Pana no se construye el perfil."""
    respuesta = cliente.post(
        "/api/escena",
        json={
            "respuestas": [{"pregunta": "monto", "letra": "A"}],
            "confirmado": False,
        },
    )
    assert respuesta.status_code == 409


def test_escena_sin_perfil_ni_respuestas_responde_422(cliente: TestClient) -> None:
    """La petición vacía no adivina el perfil."""
    assert cliente.post("/api/escena", json={}).status_code == 422


def test_negociacion_con_perfil_seguro(cliente: TestClient) -> None:
    """La fase 2 trae los agentes y el veredicto del auditor."""
    respuesta = cliente.post("/api/escena/negociacion", json={"perfil_id": "verde_computador"})
    assert respuesta.status_code == 200
    datos = respuesta.json()
    assert datos["turnos"]
    assert datos["veredicto"]["veredicto"] in {"conforme", "con_observaciones", "objeta"}
    assert datos["escenarios"]


def test_proyectado_sin_archivo_responde_404(cliente: TestClient) -> None:
    """Si no se ha corrido make escena-proyectada, la pantalla sabe que falta."""
    respuesta = cliente.get("/api/escena/proyectado")
    assert respuesta.status_code == 404
    assert respuesta.json()["disponible"] is False


def test_proyectado_lee_el_json_guardado(tmp_path: Path) -> None:
    """La escena de respaldo se valida contra el contrato antes de servirla."""
    perfil = perfil_seguro("verde_computador")
    escena = construir_escena(perfil)
    (tmp_path / "proyectado.json").write_text(
        escena.model_dump_json(indent=2),
        encoding="utf-8",
    )
    app = FastAPI()
    app.include_router(crear_router_escena(ServicioDemo(salida=tmp_path)))
    cliente = TestClient(app)
    respuesta = cliente.get("/api/escena/proyectado")
    assert respuesta.status_code == 200
    assert respuesta.json()["id"] == escena.id
    assert json.loads((tmp_path / "proyectado.json").read_text(encoding="utf-8"))["turnos"]
