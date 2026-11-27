"""Pruebas de la ruta ``/api/escena/en-vivo`` (sin red ni archivos reales).

La ruta es de solo lectura: se comprueba el filtro por ``desde``, el tope de
200, la lista vacía cuando el interruptor está apagado, el registro corrupto que
se ignora, el ``422`` de un ``desde`` inválido y el ``no-store``. El lector se
inyecta: ninguna prueba abre la lista real.
"""

from __future__ import annotations

import importlib.util
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from banco_occidente_corpus.canal.escena_vivo import EscenaVivo
from banco_occidente_corpus.config import PROJECT_ROOT
from banco_occidente_corpus.escena.api_en_vivo import LIMITE, crear_router_en_vivo
from banco_occidente_corpus.escena.contratos import OrigenTurno, PersonajeEscena, TurnoEscena

#: Raíz del repositorio, para cargar ``app.py`` por ruta.
RAIZ = Path(__file__).resolve().parents[1]

#: Ruta real de la lista, para comprobar que la ruta no la crea ni la toca.
RUTA_LISTA = PROJECT_ROOT / "data" / "escena" / "en_vivo.jsonl"


@dataclass
class LectorEspia:
    """Lector de doble que filtra en memoria y recuerda las llamadas."""

    registros: tuple[dict[str, Any], ...] = ()
    llamadas: list[tuple[int, int]] = field(default_factory=list)

    def __call__(
        self,
        desde: int,
        *,
        limite: int = LIMITE,
    ) -> tuple[tuple[Mapping[str, Any], ...], int]:
        """Devuelve los registros con ``seq > desde`` y el último ``seq``."""
        self.llamadas.append((desde, limite))
        nuevos = tuple(registro for registro in self.registros if registro["seq"] > desde)
        ultimo = max([desde, *(registro["seq"] for registro in nuevos)])
        return nuevos, ultimo


def _registro(
    seq: int,
    *,
    personaje: PersonajeEscena = "pana",
    origen: OrigenTurno = "canal",
    texto: str = "hola",
) -> dict[str, Any]:
    """Construye un registro válido de la lista."""
    turno = TurnoEscena(
        id=f"vivo.{seq}.v1",
        orden=0,
        personaje=personaje,
        texto=texto,
        origen=origen,
    )
    return {
        "seq": seq,
        "ts": "2026-11-26T15:05:00.123+00:00",
        "origen": "canal",
        "turno": turno.model_dump(mode="json"),
    }


def _cliente(lector: LectorEspia | None = None, escena: EscenaVivo | None = None) -> TestClient:
    """Monta la ruta con el lector y la ranura indicados."""
    app = FastAPI()
    app.include_router(crear_router_en_vivo(lector, escena))
    return TestClient(app)


def test_desde_filtra_y_ultimo_avanza() -> None:
    """Solo llegan los turnos con ``seq > desde`` y el cursor avanza."""
    lector = LectorEspia(registros=(_registro(3), _registro(5), _registro(7)))

    respuesta = _cliente(lector).get("/api/escena/en-vivo?desde=5")

    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    assert [turno["seq"] for turno in cuerpo["turnos"]] == [7]
    assert cuerpo["ultimo"] == 7
    assert lector.llamadas == [(5, LIMITE)]


def test_el_tope_es_de_doscientos_turnos() -> None:
    """La ruta pide siempre el máximo del contrato."""
    lector = LectorEspia()

    _cliente(lector).get("/api/escena/en-vivo")

    assert lector.llamadas == [(0, 200)]


def test_sin_interruptor_la_lista_esta_vacia(monkeypatch: pytest.MonkeyPatch) -> None:
    """Con ``ESCENA_EN_VIVO`` ausente no se lee la lista."""
    monkeypatch.delenv("ESCENA_EN_VIVO", raising=False)

    respuesta = _cliente().get("/api/escena/en-vivo?desde=9")

    assert respuesta.status_code == 200
    assert respuesta.json() == {"turnos": [], "ultimo": 9}


def test_el_registro_corrupto_se_ignora() -> None:
    """Un registro inválido no tumba la ruta ni se repite en cada sondeo."""
    valido = _registro(4)
    sin_ts = {"seq": 6, "origen": "canal", "turno": valido["turno"]}
    origen_raro = {**valido, "seq": 8, "origen": "otro"}
    lector = LectorEspia(registros=(valido, sin_ts, origen_raro))

    respuesta = _cliente(lector).get("/api/escena/en-vivo")

    cuerpo = respuesta.json()
    assert respuesta.status_code == 200
    assert [turno["seq"] for turno in cuerpo["turnos"]] == [4]
    assert cuerpo["ultimo"] == 8


def test_la_ruta_no_crea_ni_modifica_la_lista(monkeypatch: pytest.MonkeyPatch) -> None:
    """La ruta es de solo lectura: no crea el archivo ni lo cambia."""
    antes = RUTA_LISTA.read_bytes() if RUTA_LISTA.exists() else None
    monkeypatch.delenv("ESCENA_EN_VIVO", raising=False)

    _cliente().get("/api/escena/en-vivo")

    despues = RUTA_LISTA.read_bytes() if RUTA_LISTA.exists() else None
    assert despues == antes


@pytest.mark.parametrize("consulta", ["desde=-1", "desde=abc", "desde=1.5"])
def test_desde_invalido_da_422(consulta: str) -> None:
    """Un ``desde`` que no es entero no negativo responde 422."""
    respuesta = _cliente(LectorEspia()).get(f"/api/escena/en-vivo?{consulta}")

    assert respuesta.status_code == 422


def test_la_respuesta_no_se_cachea() -> None:
    """La pantalla no debe recibir una escena vieja del navegador."""
    respuesta = _cliente(LectorEspia(registros=(_registro(1),))).get("/api/escena/en-vivo")

    assert respuesta.headers["cache-control"] == "no-store"


def test_las_unicas_rutas_publicas_son_el_webhook_y_health() -> None:
    """La lista en vivo no entra en la superficie pública del túnel.

    El ``404`` real de esta ruta desde el túnel se comprueba en
    ``test/test_tunel_publico.py``; aquí se fija la lista que el arranque
    declara pública.
    """
    arranque = _arranque()

    assert frozenset({"/webhooks/whatsapp", "/health"}) == arranque.RUTAS_PUBLICAS
    assert "/api/escena/en-vivo" not in arranque.RUTAS_PUBLICAS


def _arranque() -> Any:
    """Carga ``app.py`` por ruta, porque la carpeta ``app/`` tapa el módulo."""
    spec = importlib.util.spec_from_file_location("arranque_en_vivo", RAIZ / "app.py")
    assert spec is not None
    assert spec.loader is not None
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


def test_el_lector_ve_el_desde_del_cliente() -> None:
    """El cliente decide el cursor; la ruta no lo reescribe."""
    lector = LectorEspia(registros=(_registro(10),))

    cuerpo = _cliente(lector).get("/api/escena/en-vivo?desde=10").json()

    assert cuerpo == {"turnos": [], "ultimo": 10}
    assert lector.llamadas == [(10, LIMITE)]


def test_ultimo_nunca_retrocede() -> None:
    """Si el lector devuelve un cursor menor, la ruta conserva el del cliente."""
    lector = LectorEspia(registros=())

    cuerpo = _cliente(lector).get("/api/escena/en-vivo?desde=50").json()

    assert cuerpo["ultimo"] == 50


def test_el_lector_recibe_una_ruta_de_la_lista() -> None:
    """El contrato deja el archivo en ``data/escena/en_vivo.jsonl``."""
    assert RUTA_LISTA.parent.name == "escena"
    assert RUTA_LISTA.name == "en_vivo.jsonl"
    assert isinstance(RUTA_LISTA, Path)


def test_la_convocatoria_abre_y_libera_la_ranura() -> None:
    """POST abre la convocatoria y DELETE libera al voluntario activo."""
    escena = EscenaVivo()
    cliente = _cliente(escena=escena)

    abierta = cliente.post("/api/escena/convocatoria")
    assert abierta.status_code == 200
    assert abierta.json() == {"abierta": True}
    assert escena.convocatoria_abierta() is True

    escena.activar("huella-de-prueba", destino="57000000001")
    assert escena.voluntario_activo() is not None

    liberada = cliente.delete("/api/escena/convocatoria")
    assert liberada.status_code == 200
    assert liberada.json() == {"abierta": False}
    assert escena.voluntario_activo() is None
    assert escena.convocatoria_abierta() is False


def test_sin_la_ranura_del_canal_la_convocatoria_responde_409() -> None:
    """Si el canal no arrancó, la pantalla no puede abrir la convocatoria."""
    cliente = _cliente()

    assert cliente.post("/api/escena/convocatoria").status_code == 409
    assert cliente.delete("/api/escena/convocatoria").status_code == 409
