"""Pruebas sin red de `POST /api/preguntar`: rutas, caché, gasto, demo y logs.

Usan `TestClient` con el grafo y el modelo simulados: no llaman a DeepSeek, a
Ollama ni al sitio del banco.
"""

from __future__ import annotations

import importlib.util
import json
import logging
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from fastapi.testclient import TestClient
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage

from banco_occidente_corpus.asistente.contexto_prompt import CanalOficial
from banco_occidente_corpus.asistente.validacion import FRASE_SIN_DATOS
from banco_occidente_corpus.boveda.tipos import Fragmento, Recuperador
from banco_occidente_corpus.config import Config, Paths
from banco_occidente_corpus.sucursal.ajustes import ConfiguracionSucursal
from banco_occidente_corpus.sucursal.api import PreguntarRespuesta
from banco_occidente_corpus.sucursal.costo import CacheRespuestas, GastoDiario
from banco_occidente_corpus.sucursal.digiturno import (
    Clasificador,
    ContadorTurnos,
    clasificador_deepseek,
)
from banco_occidente_corpus.sucursal.grafo import (
    DependenciasGrafo,
    crear_grafo,
    registrar_turno,
)
from banco_occidente_corpus.sucursal.preguntar import (
    PiezasGrafo,
    ServicioPreguntas,
    construir_piezas,
    requiere_modelo,
)
from banco_occidente_corpus.tablero.tipos import Fila, escribir_filas, ruta_tablero

RAIZ = Path(__file__).resolve().parents[1]
URL = "https://www.bancodeoccidente.com.co/documents/d/guest/tarifas-persona-1"
URL_CANAL = "https://www.bancodeoccidente.com.co/ayuda/linea-servicio-cliente"
CONCEPTO = "Cuota de manejo tarjeta débito"
PREGUNTA_BOVEDA = "¿En qué año se fundó el Banco de Occidente?"
PREGUNTA_TABLERO = "cuota de manejo"
PREGUNTA_RECHAZO = "¿En qué acciones me recomiendas invertir?"
RESPUESTA_BOVEDA = f"El Banco de Occidente fue fundado en 1965 en Cali [1].\n\nFuentes:\n- {URL}"
RESPUESTA_SIN_DATOS = f"{FRASE_SIN_DATOS}."
TEXTO_FRAGMENTO = "El Banco de Occidente fue fundado en 1965 en Cali y es parte del Grupo Aval."


class RecuperadorFalso:
    """Recuperador en memoria que devuelve los fragmentos configurados."""

    def __init__(self, fragmentos: list[Fragmento]) -> None:
        """Guarda los fragmentos que devolverá cada búsqueda."""
        self._fragmentos = fragmentos
        self.consultas: list[str] = []

    def buscar(self, consulta: str, k: int = 5) -> list[Fragmento]:
        """Devuelve hasta `k` fragmentos y registra la consulta."""
        self.consultas.append(consulta)
        return self._fragmentos[:k]


class ModeloGuion:
    """Modelo falso que devuelve respuestas en orden y registra los mensajes."""

    def __init__(
        self,
        respuestas: list[str],
        usos: list[dict[str, int]] | None = None,
    ) -> None:
        """Carga las respuestas y, si se dan, el uso de cada llamada."""
        self.respuestas = list(respuestas)
        self.usos = list(usos) if usos is not None else None
        self.llamadas: list[list[BaseMessage]] = []
        self.opciones: list[dict[str, Any]] = []

    def invoke(self, mensajes: list[BaseMessage], **opciones: Any) -> AIMessage:
        """Registra la llamada y devuelve la siguiente respuesta con su uso."""
        self.llamadas.append(list(mensajes))
        self.opciones.append(dict(opciones))
        uso = (
            self.usos.pop(0)
            if self.usos is not None
            else {"input_tokens": 120, "output_tokens": 40, "total_tokens": 160}
        )
        return AIMessage(content=self.respuestas.pop(0), usage_metadata=uso)


def uso_modelo(entrada: int, salida: int) -> dict[str, int]:
    """Uso sintético de una llamada al modelo en el formato de `usage_metadata`."""
    return {
        "input_tokens": entrada,
        "output_tokens": salida,
        "total_tokens": entrada + salida,
    }


@dataclass
class Escenario:
    """Contexto de una prueba: cliente, rutas, dobles y acumulados."""

    cliente: TestClient
    config: Config
    gasto: GastoDiario
    cache: CacheRespuestas
    dependencias: DependenciasGrafo
    grafo: Any
    modelo: ModeloGuion | None


def cargar_app() -> ModuleType:
    """Carga el `app.py` de la raíz como módulo, igual que la app real."""
    especificacion = importlib.util.spec_from_file_location(
        "arranque_sucursal_preguntar", RAIZ / "app.py"
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


def fila(concepto: str = CONCEPTO) -> Fila:
    """Fila del Tablero con la cuota de manejo de la tarjeta débito."""
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


def fragmento(
    texto: str = TEXTO_FRAGMENTO,
    *,
    url: str = URL,
    titulo: str = "Fundación del banco",
    identificador: str = "frag:1",
    puntaje: float = 0.82,
) -> Fragmento:
    """Fragmento de prueba; por defecto, la página de fundación del banco."""
    return Fragmento(
        id=identificador,
        texto=texto,
        url=url,
        titulo=titulo,
        seccion="identidad",
        encabezado="Historia",
        tipo="pagina",
        tokens=20,
        puntaje=puntaje,
    )


def canal() -> CanalOficial:
    """Canal oficial de prueba, usado por el rechazo y por los permisos de PII."""
    return CanalOficial(
        url=URL_CANAL,
        telefono="018000 514652",
        telefonos=("018000514652",),
    )


def preparar(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    demo: bool = False,
    modelo: ModeloGuion | None = None,
    fragmentos: list[Fragmento] | None = None,
    filas: list[Fila] | None = None,
    clasificador: Clasificador | None = None,
) -> Escenario:
    """Crea la app con dobles, sin red, sobre un directorio temporal."""
    monkeypatch.setenv("SUCURSAL_TOPE_USD", "0.20")
    config = make_config(tmp_path)
    web = tmp_path / "web"
    web.mkdir(parents=True)
    (web / "index.html").write_text("<!doctype html><title>Sucursal</title>", encoding="utf-8")

    filas_escenario = [fila()] if filas is None else filas
    escribir_filas(tmp_path / "data/estructurados/tablero.csv", filas_escenario)
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

    dependencias = DependenciasGrafo(
        recuperador=RecuperadorFalso(fragmentos or []),
        filas=filas_escenario,
        modelo=modelo,
        clasificador=clasificador,
        canal=canal(),
        contador=ContadorTurnos(),
    )
    grafo = crear_grafo(dependencias, tmp_path / "data/asistente/memoria.sqlite")
    gasto = GastoDiario(tmp_path / "data/asistente/gasto.sqlite")
    cache = CacheRespuestas(tmp_path / "data/asistente/cache.sqlite", 60)
    ajustes = ConfiguracionSucursal(tope_diario_usd=0.2, cache_ttl_segundos=60, demo=demo)
    cliente = TestClient(
        cargar_app().crear_app(
            web,
            config=config,
            ajustes=ajustes,
            cache=cache,
            piezas=lambda: PiezasGrafo(dependencias, grafo),
        )
    )
    return Escenario(
        cliente=cliente,
        config=config,
        gasto=gasto,
        cache=cache,
        dependencias=dependencias,
        grafo=grafo,
        modelo=modelo,
    )


def preguntar(cliente: TestClient, pregunta: str, hilo: str = "ses-1") -> Any:
    """Envía una pregunta al endpoint y devuelve la respuesta HTTP."""
    return cliente.post("/api/preguntar", json={"pregunta": pregunta, "thread_id": hilo})


def contar_cache(escenario: Escenario) -> int:
    """Cuenta las filas guardadas en la caché de respuestas."""
    with sqlite3.connect(str(escenario.cache.ruta)) as conexion:
        fila_cache = conexion.execute("SELECT COUNT(*) FROM cache").fetchone()
    return int(fila_cache[0]) if fila_cache else 0


def test_ruta_boveda_200(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Una consulta de alcance responde por la Bóveda con fuentes y costo."""
    modelo = ModeloGuion([RESPUESTA_BOVEDA])
    escenario = preparar(monkeypatch, tmp_path, modelo=modelo, fragmentos=[fragmento()])

    respuesta = preguntar(escenario.cliente, PREGUNTA_BOVEDA, "hilo-b")
    cuerpo = respuesta.json()

    assert respuesta.status_code == 200
    assert set(cuerpo) == set(PreguntarRespuesta.model_fields)
    assert cuerpo["turno"] == "B"
    assert cuerpo["ruta"] == "boveda"
    assert cuerpo["uso_modelo"] is True
    assert cuerpo["reformulada"] is None
    assert cuerpo["cache"] is False
    assert cuerpo["fuentes"] == [
        {
            "n": 1,
            "titulo": "Fundación del banco",
            "url": URL,
            "seccion": "identidad",
            "tipo": "pagina",
            "similitud": 0.82,
        }
    ]
    assert cuerpo["tokens_entrada"] == 120
    assert cuerpo["tokens_salida"] == 40
    assert cuerpo["costo_usd"] > 0
    assert cuerpo["turno_numero"] >= 1
    assert cuerpo["tiempo_s"] >= 0


def test_ruta_tablero_200(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Una pregunta de tarifas con una fila responde con plantilla y sin modelo."""
    escenario = preparar(monkeypatch, tmp_path, fragmentos=[fragmento()])

    respuesta = preguntar(escenario.cliente, PREGUNTA_TABLERO, "hilo-t")
    cuerpo = respuesta.json()

    assert respuesta.status_code == 200
    assert cuerpo["turno"] == "T"
    assert cuerpo["ruta"] == "tablero"
    assert cuerpo["motivo"] == "tarifas"
    assert cuerpo["uso_modelo"] is False
    assert cuerpo["tokens_entrada"] == 0
    assert cuerpo["tokens_salida"] == 0
    assert cuerpo["costo_usd"] == 0.0
    assert cuerpo["respuesta"].startswith("Según el Tablero de tarifas:")
    assert cuerpo["fuentes"] == [
        {
            "n": 1,
            "titulo": CONCEPTO,
            "url": URL,
            "seccion": "otros",
            "tipo": "pdf",
            "similitud": None,
        }
    ]


def test_ruta_rechazo_200(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Una pregunta fuera de alcance responde X, sin fuentes y sin gasto."""
    escenario = preparar(monkeypatch, tmp_path, fragmentos=[fragmento()])

    respuesta = preguntar(escenario.cliente, PREGUNTA_RECHAZO, "hilo-x")
    cuerpo = respuesta.json()

    assert respuesta.status_code == 200
    assert cuerpo["turno"] == "X"
    assert cuerpo["ruta"] == "rechazo"
    assert cuerpo["motivo"] == "fuera_alcance"
    assert cuerpo["fuentes"] == []
    assert cuerpo["uso_modelo"] is False
    assert cuerpo["costo_usd"] == 0.0
    assert escenario.gasto.hoy()[0] == 0.0


def test_pregunta_vacia_devuelve_422(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Una pregunta en blanco responde el error del contrato y no gasta."""
    escenario = preparar(monkeypatch, tmp_path)

    respuesta = preguntar(escenario.cliente, "   ", "hilo-vacio")

    assert respuesta.status_code == 422
    assert respuesta.json() == {
        "error": {
            "codigo": "pregunta_vacia",
            "mensaje": "La pregunta está vacía: escribe qué quieres consultar.",
        }
    }


def test_thread_id_ausente_devuelve_422(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Sin hilo la API no puede guardar memoria y responde 422."""
    escenario = preparar(monkeypatch, tmp_path)

    respuesta = preguntar(escenario.cliente, PREGUNTA_BOVEDA, "  ")

    assert respuesta.status_code == 422
    assert respuesta.json()["error"]["codigo"] == "thread_id_ausente"


def test_indice_ausente_devuelve_503(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Sin indice.json responde 503 y ni siquiera construye el grafo."""
    monkeypatch.setenv("SUCURSAL_TOPE_USD", "0.20")
    config = make_config(tmp_path)
    web = tmp_path / "web"
    web.mkdir(parents=True)
    (web / "index.html").write_text("<!doctype html>", encoding="utf-8")
    llamadas: list[int] = []

    def fabrica() -> PiezasGrafo:
        """Falla si la API intenta construir piezas sin índice."""
        llamadas.append(1)
        raise AssertionError("no debe construirse sin índice")

    cliente = TestClient(
        cargar_app().crear_app(
            web,
            config=config,
            ajustes=ConfiguracionSucursal(demo=True),
            piezas=fabrica,
        )
    )

    respuesta = preguntar(cliente, PREGUNTA_BOVEDA, "hilo-sin-indice")

    assert respuesta.status_code == 503
    assert respuesta.json()["error"]["codigo"] == "indice_no_listo"
    assert llamadas == []


def test_sin_clave_fuera_de_demo_devuelve_503(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Sin DEEPSEEK_API_KEY el servicio responde 503 antes de tocar Ollama."""
    monkeypatch.setenv("SUCURSAL_TOPE_USD", "0.20")
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    config = make_config(tmp_path)
    web = tmp_path / "web"
    web.mkdir(parents=True)
    (web / "index.html").write_text("<!doctype html>", encoding="utf-8")
    indice = tmp_path / "data/boveda/indice.json"
    indice.parent.mkdir(parents=True)
    indice.write_text(json.dumps({"fragmentos": 10}), encoding="utf-8")
    cliente = TestClient(
        cargar_app().crear_app(
            web,
            config=config,
            ajustes=ConfiguracionSucursal(demo=False),
        )
    )

    respuesta = preguntar(cliente, PREGUNTA_BOVEDA, "hilo-sin-clave")

    assert respuesta.status_code == 503
    assert respuesta.json()["error"]["codigo"] == "sin_clave"


def test_gasto_solo_si_hubo_modelo(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """El acumulado sube con la Bóveda y no con las rutas T ni X."""
    escenario = preparar(
        monkeypatch,
        tmp_path,
        modelo=ModeloGuion([RESPUESTA_BOVEDA]),
        fragmentos=[fragmento()],
    )

    boveda = preguntar(escenario.cliente, PREGUNTA_BOVEDA, "hilo-gasto").json()
    gasto_boveda = escenario.gasto.hoy()[0]
    assert gasto_boveda == pytest.approx(boveda["costo_usd"])
    assert gasto_boveda > 0

    preguntar(escenario.cliente, PREGUNTA_TABLERO, "hilo-gasto-t")
    assert escenario.gasto.hoy()[0] == pytest.approx(gasto_boveda)

    preguntar(escenario.cliente, PREGUNTA_RECHAZO, "hilo-gasto-x")
    assert escenario.gasto.hoy()[0] == pytest.approx(gasto_boveda)


def test_seguimiento_suma_reformulacion_y_redaccion(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """La reformulación y la redacción se cobran juntas en el turno."""
    modelo = ModeloGuion(
        [RESPUESTA_BOVEDA, "¿Cuánto cuesta abrir la cuenta?", RESPUESTA_BOVEDA],
        usos=[uso_modelo(120, 40), uso_modelo(60, 10), uso_modelo(200, 50)],
    )
    escenario = preparar(monkeypatch, tmp_path, modelo=modelo, fragmentos=[fragmento()])

    primera = preguntar(escenario.cliente, PREGUNTA_BOVEDA, "hilo-suma").json()
    gasto_primera = escenario.gasto.hoy()[0]
    segunda = preguntar(escenario.cliente, "¿Y cuánto cuesta?", "hilo-suma").json()

    assert primera["costo_usd"] > 0
    assert segunda["cache"] is False
    assert segunda["reformulada"] == "¿Cuánto cuesta abrir la cuenta?"
    assert segunda["tokens_entrada"] == 260
    assert segunda["tokens_salida"] == 60
    assert segunda["uso_modelo"] is True
    assert segunda["costo_usd"] > 0
    assert escenario.gasto.hoy()[0] == pytest.approx(gasto_primera + segunda["costo_usd"])
    assert escenario.gasto.hoy()[1] == 3
    assert escenario.gasto.hoy()[2] == 480
    assert len(modelo.llamadas) == 3
    assert modelo.opciones[1]["max_tokens"] == 512


def test_clasificador_suma_su_uso(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """El clasificador de dudas y la redacción suman su uso en el comprobante."""
    modelo = ModeloGuion(
        ['{"letra": "B", "motivo": "requisitos"}', RESPUESTA_BOVEDA],
        usos=[uso_modelo(80, 20), uso_modelo(120, 40)],
    )
    escenario = preparar(
        monkeypatch,
        tmp_path,
        modelo=modelo,
        fragmentos=[fragmento()],
        clasificador=clasificador_deepseek(modelo),
    )

    cuerpo = preguntar(
        escenario.cliente, "¿qué necesito para un crédito?", "hilo-clasificador"
    ).json()

    assert cuerpo["turno"] == "B"
    assert cuerpo["uso_modelo"] is True
    assert cuerpo["tokens_entrada"] == 200
    assert cuerpo["tokens_salida"] == 60
    assert cuerpo["costo_usd"] > 0
    assert escenario.gasto.hoy()[0] == pytest.approx(cuerpo["costo_usd"])
    assert escenario.gasto.hoy()[1] == 2
    assert escenario.gasto.hoy()[2] == 260
    assert len(modelo.llamadas) == 2
    assert modelo.opciones[0]["max_tokens"] == 512


def test_frase_fija_con_tokens_cobra_y_no_cachea(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Si el modelo gastó tokens y cayó en la frase fija, se cobra y no se cachea."""
    modelo = ModeloGuion([RESPUESTA_SIN_DATOS, RESPUESTA_SIN_DATOS])
    escenario = preparar(monkeypatch, tmp_path, modelo=modelo, fragmentos=[fragmento()])

    primera = preguntar(escenario.cliente, PREGUNTA_BOVEDA, "hilo-sin-datos").json()
    gasto_primera = escenario.gasto.hoy()[0]
    segunda = preguntar(escenario.cliente, PREGUNTA_BOVEDA, "hilo-sin-datos").json()

    assert primera["respuesta"].startswith(FRASE_SIN_DATOS)
    assert primera["uso_modelo"] is True
    assert primera["tokens_entrada"] == 120
    assert primera["tokens_salida"] == 40
    assert primera["costo_usd"] > 0
    assert gasto_primera == pytest.approx(primera["costo_usd"])
    assert segunda["cache"] is False
    assert segunda["uso_modelo"] is True
    assert segunda["costo_usd"] > 0
    assert escenario.gasto.hoy()[0] == pytest.approx(gasto_primera * 2)
    assert len(modelo.llamadas) == 2
    assert contar_cache(escenario) == 0


def test_cache_hit_sin_gastar(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """La segunda pregunta idéntica sale de la caché con costo cero."""
    modelo = ModeloGuion([RESPUESTA_BOVEDA])
    escenario = preparar(monkeypatch, tmp_path, modelo=modelo, fragmentos=[fragmento()])

    primera = preguntar(escenario.cliente, PREGUNTA_BOVEDA, "hilo-cache").json()
    gasto_primera = escenario.gasto.hoy()[0]
    segunda = preguntar(escenario.cliente, PREGUNTA_BOVEDA, "hilo-cache").json()

    assert primera["cache"] is False
    assert primera["costo_usd"] > 0
    assert segunda["cache"] is True
    assert segunda["costo_usd"] == 0.0
    assert segunda["tokens_entrada"] == 0
    assert segunda["tokens_salida"] == 0
    assert segunda["tokens_cache"] == 0
    assert segunda["respuesta"] == primera["respuesta"]
    assert segunda["turno_numero"] == primera["turno_numero"] + 1
    assert escenario.gasto.hoy()[0] == pytest.approx(gasto_primera)
    assert len(modelo.llamadas) == 1


def test_seguimiento_tras_acierto_de_cache_recibe_contexto(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Tras un acierto de caché el hilo conserva pregunta y respuesta."""
    modelo = ModeloGuion([RESPUESTA_BOVEDA, PREGUNTA_TABLERO])
    escenario = preparar(monkeypatch, tmp_path, modelo=modelo, fragmentos=[fragmento()])

    primera = preguntar(escenario.cliente, PREGUNTA_BOVEDA, "hilo-memoria").json()
    acierto = preguntar(escenario.cliente, PREGUNTA_BOVEDA, "hilo-memoria").json()
    seguimiento = preguntar(escenario.cliente, "¿Y cuánto cuesta?", "hilo-memoria").json()

    assert acierto["cache"] is True
    assert len(modelo.llamadas) == 2
    mensajes = modelo.llamadas[1]
    textos = [str(mensaje.content) for mensaje in mensajes]
    assert any(PREGUNTA_BOVEDA in texto for texto in textos)
    assert any(primera["respuesta"] in texto for texto in textos)
    assert seguimiento["reformulada"] == PREGUNTA_TABLERO
    estado = escenario.grafo.get_state({"configurable": {"thread_id": "hilo-memoria"}})
    assert len(estado.values["messages"]) == 6


def test_rechazo_no_escribe_cache(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Un turno X no se cachea, aunque la pregunta se repita."""
    escenario = preparar(monkeypatch, tmp_path, fragmentos=[fragmento()])

    primera = preguntar(escenario.cliente, PREGUNTA_RECHAZO, "hilo-rechazo").json()
    segunda = preguntar(escenario.cliente, PREGUNTA_RECHAZO, "hilo-rechazo").json()

    assert primera["cache"] is False
    assert segunda["cache"] is False
    assert contar_cache(escenario) == 0


def test_tope_alcanzado_solo_para_modelo(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Con el tope agotado la Bóveda responde 429 y el Tablero y el rechazo siguen."""
    modelo = ModeloGuion([RESPUESTA_BOVEDA])
    escenario = preparar(monkeypatch, tmp_path, modelo=modelo, fragmentos=[fragmento()])
    escenario.gasto.sumar(0.5, 1_000)

    boveda = preguntar(escenario.cliente, PREGUNTA_BOVEDA, "hilo-tope")
    tablero = preguntar(escenario.cliente, PREGUNTA_TABLERO, "hilo-tope-t")
    rechazo = preguntar(escenario.cliente, PREGUNTA_RECHAZO, "hilo-tope-x")

    assert boveda.status_code == 429
    assert boveda.json()["error"]["codigo"] == "tope_alcanzado"
    assert tablero.status_code == 200
    assert tablero.json()["turno"] == "T"
    assert rechazo.status_code == 200
    assert modelo.llamadas == []


def test_modo_demo_responde_sin_modelo_ni_gasto(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """En demo la Bóveda responde con el fragmento, sin costo y sin caché."""
    escenario = preparar(monkeypatch, tmp_path, demo=True, fragmentos=[fragmento()])

    primera = preguntar(escenario.cliente, PREGUNTA_BOVEDA, "hilo-demo").json()
    segunda = preguntar(escenario.cliente, PREGUNTA_BOVEDA, "hilo-demo").json()

    assert primera["turno"] == "B"
    assert primera["uso_modelo"] is False
    assert "Modo demo" in primera["respuesta"]
    assert "fundado en 1965" in primera["respuesta"]
    assert primera["fuentes"][0]["url"] == URL
    assert primera["costo_usd"] == 0.0
    assert primera["cache"] is False
    assert segunda["cache"] is False
    assert contar_cache(escenario) == 0
    assert escenario.gasto.hoy()[0] == 0.0


def test_demo_elige_el_fragmento_de_mayor_puntaje(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """La demo cita el fragmento con más similitud aunque llegue desordenado."""
    motos = f"{URL}/creditos/motos"
    mejor = f"{URL}/nuestro-banco/historia"
    fragmentos = [
        fragmento(
            "Financia motos y vehículos con cuota fija.",
            url=motos,
            titulo="Crédito de motos",
            identificador="frag:motos",
            puntaje=0.179,
        ),
        fragmento(
            "El Banco de Occidente fue fundado en 1965 en Cali.",
            url=mejor,
            titulo="Nuestro banco",
            identificador="frag:banco",
            puntaje=0.601,
        ),
        fragmento(
            "El banco hace parte del Grupo Aval.",
            url=f"{URL}/nuestro-banco/aval",
            titulo="Grupo Aval",
            identificador="frag:aval",
            puntaje=0.592,
        ),
        fragmento(
            "Tiene presencia en Colombia.",
            url=f"{URL}/nuestro-banco/presencia",
            titulo="Presencia",
            identificador="frag:presencia",
            puntaje=0.560,
        ),
    ]
    escenario = preparar(monkeypatch, tmp_path, demo=True, fragmentos=fragmentos)

    cuerpo = preguntar(escenario.cliente, PREGUNTA_BOVEDA, "hilo-demo-top").json()

    assert "fundado en 1965" in cuerpo["respuesta"]
    assert "motos" not in cuerpo["respuesta"]
    assert [fuente["url"] for fuente in cuerpo["fuentes"]] == [mejor]
    assert cuerpo["fuentes"][0]["titulo"] == "Nuestro banco"
    assert cuerpo["fuentes"][0]["similitud"] == 0.601


def test_construir_piezas_demo_no_crea_modelo(tmp_path: Path) -> None:
    """El modo demo no construye el chat model y deja el clasificador en None."""
    llamadas: list[int] = []

    def modelo_espia() -> BaseChatModel:
        """Falla si alguien intenta crear el modelo en modo demo."""
        llamadas.append(1)
        raise AssertionError("el modo demo no crea modelo")

    def recuperador_espia() -> Recuperador:
        """Devuelve un recuperador en memoria con un fragmento."""
        return RecuperadorFalso([fragmento()])

    piezas = construir_piezas(
        make_config(tmp_path),
        ConfiguracionSucursal(demo=True),
        crear_modelo_chat=modelo_espia,
        crear_recuperador_boveda=recuperador_espia,
    )

    assert llamadas == []
    assert piezas.dependencias.modelo is None
    assert piezas.dependencias.clasificador is None
    assert (tmp_path / "data/asistente/memoria.sqlite").exists()


def test_requiere_modelo_replica_las_reglas(tmp_path: Path) -> None:
    """La estimación sigue a es_seguimiento, al digiturno y a las filas del Tablero."""
    dependencias = DependenciasGrafo(
        recuperador=RecuperadorFalso([fragmento()]),
        filas=[fila()],
        canal=canal(),
        contador=ContadorTurnos(),
    )
    ambiguas = DependenciasGrafo(
        recuperador=RecuperadorFalso([fragmento()]),
        filas=[fila(f"{CONCEPTO} {indice}") for indice in range(4)],
        canal=canal(),
        contador=ContadorTurnos(),
    )

    assert requiere_modelo(PREGUNTA_BOVEDA, dependencias) is True
    assert requiere_modelo(PREGUNTA_RECHAZO, dependencias) is False
    assert requiere_modelo(PREGUNTA_TABLERO, dependencias) is False
    # «cuota de manejo» es autónoma: no se reformula aunque haya historial.
    assert requiere_modelo(PREGUNTA_TABLERO, dependencias, con_historial=True) is False
    assert requiere_modelo("¿Y cuánto cuesta?", dependencias, con_historial=True) is True
    assert requiere_modelo(PREGUNTA_TABLERO, ambiguas) is True


def test_no_registra_la_pregunta_ni_el_hilo(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """El log del turno no incluye la pregunta, la respuesta ni el thread_id."""
    escenario = preparar(
        monkeypatch,
        tmp_path,
        modelo=ModeloGuion([RESPUESTA_BOVEDA]),
        fragmentos=[fragmento()],
    )
    caplog.set_level(logging.INFO)

    preguntar(escenario.cliente, PREGUNTA_BOVEDA, "hilo-privado-xyz")

    assert "pregunta_atendida" in caplog.text
    assert "Banco de Occidente" not in caplog.text
    assert "hilo-privado-xyz" not in caplog.text


def test_pii_no_entra_en_cache_ni_en_logs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Una pregunta con cédula se rechaza sin cachearse, sin memoria y sin log."""
    escenario = preparar(monkeypatch, tmp_path, fragmentos=[fragmento()])
    caplog.set_level(logging.INFO)
    documento = "1020304050"

    respuesta = preguntar(
        escenario.cliente, f"Mi cédula es {documento}, ¿cuál es mi saldo?", "hilo-pii"
    )

    assert respuesta.status_code == 200
    assert respuesta.json()["turno"] == "X"
    assert respuesta.json()["motivo"].startswith("pii:")
    assert respuesta.json()["fuentes"] == []
    assert contar_cache(escenario) == 0
    assert escenario.grafo.get_state({"configurable": {"thread_id": "hilo-pii"}}).values == {}
    assert documento not in caplog.text
    assert "cédula" not in caplog.text


def test_registrar_turno_en_hilo_nuevo(tmp_path: Path) -> None:
    """`registrar_turno` deja el par pregunta/respuesta en un hilo recién creado."""
    dependencias = DependenciasGrafo(
        recuperador=RecuperadorFalso([fragmento()]),
        canal=canal(),
        contador=ContadorTurnos(),
    )
    grafo = crear_grafo(dependencias, tmp_path / "memoria.sqlite")

    registrar_turno(grafo, PREGUNTA_BOVEDA, RESPUESTA_BOVEDA, "hilo-nuevo")

    estado = grafo.get_state({"configurable": {"thread_id": "hilo-nuevo"}})
    mensajes = estado.values["messages"]
    assert [str(mensaje.content) for mensaje in mensajes] == [
        PREGUNTA_BOVEDA,
        RESPUESTA_BOVEDA,
    ]


class CacheEspia:
    """Caché que falla si el servicio la consulta o la escribe."""

    def __init__(self) -> None:
        """Deja constancia de cualquier acceso inesperado."""
        self.llamadas: list[str] = []

    def obtener(self, clave: str) -> dict[str, Any] | None:
        """Falla: con `usar_cache=False` no debe consultarse."""
        self.llamadas.append(f"obtener:{clave}")
        raise AssertionError("no debía consultar la caché")

    def guardar(self, clave: str, respuesta: Any) -> None:
        """Falla: con `usar_cache=False` no debe guardarse nada."""
        self.llamadas.append(f"guardar:{clave}")
        raise AssertionError("no debía guardar en la caché")


def test_servicio_sin_cache_no_consulta_ni_guarda(tmp_path: Path) -> None:
    """Con `usar_cache=False` el servicio ni lee ni escribe la caché."""
    config = make_config(tmp_path)
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
    dependencias = DependenciasGrafo(
        recuperador=RecuperadorFalso([fragmento()]),
        filas=[],
        modelo=ModeloGuion([RESPUESTA_BOVEDA]),
        canal=canal(),
        contador=ContadorTurnos(),
    )
    grafo = crear_grafo(dependencias, tmp_path / "data/asistente/memoria.sqlite")
    cache = CacheEspia()
    servicio = ServicioPreguntas(
        config,
        ConfiguracionSucursal(tope_diario_usd=0.2, cache_ttl_segundos=60, demo=False),
        GastoDiario(tmp_path / "data/asistente/gasto.sqlite"),
        cache=cache,  # type: ignore[arg-type]
        piezas=lambda: PiezasGrafo(dependencias, grafo),
        usar_cache=False,
    )

    respuesta = servicio.preguntar(PREGUNTA_BOVEDA, "hilo-sin-cache")

    assert respuesta["cache"] is False
    assert cache.llamadas == []


def test_construir_piezas_respeta_la_ruta_de_memoria(tmp_path: Path) -> None:
    """`construir_piezas` compila el checkpointer en la ruta indicada."""
    config = make_config(tmp_path)
    escribir_filas(ruta_tablero(config), [fila()])
    ruta = tmp_path / "data/asistente/memoria_evaluacion.sqlite"

    construir_piezas(
        config,
        ConfiguracionSucursal(),
        crear_modelo_chat=lambda: ModeloGuion([]),
        crear_recuperador_boveda=lambda: RecuperadorFalso([]),
        ruta_memoria=ruta,
    )

    assert ruta.exists()
    assert not (tmp_path / "data/asistente/memoria.sqlite").exists()


def test_ruta_cortesia_200(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Un saludo responde con turno B, ruta cortesía, cero tokens y sin fuentes."""
    escenario = preparar(monkeypatch, tmp_path, fragmentos=[fragmento()])

    respuesta = preguntar(escenario.cliente, "Hola", "hilo-saludo")
    cuerpo = respuesta.json()

    assert respuesta.status_code == 200
    assert cuerpo["turno"] == "B"
    assert cuerpo["ruta"] == "cortesia"
    assert cuerpo["motivo"] == "cortesia"
    assert cuerpo["uso_modelo"] is False
    assert cuerpo["tokens_entrada"] == 0
    assert cuerpo["tokens_salida"] == 0
    assert cuerpo["costo_usd"] == 0.0
    assert cuerpo["fuentes"] == []
    assert cuerpo["respuesta"].startswith("¡Hola!")
    # No buscó en la Bóveda ni guardó la cortesía en la caché.
    assert escenario.dependencias.recuperador.consultas == []
    assert contar_cache(escenario) == 0


def test_ruta_mixta_200(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """La ruta mixta entrega la cifra del Tablero y los beneficios de la Bóveda."""
    url_beneficios = "https://www.bancodeoccidente.com.co/tarjetas-credito/credencial-gold"
    beneficios = fragmento(
        texto="La Credencial Gold ofrece salas VIP y seguros de viaje.",
        url=url_beneficios,
        titulo="Credencial Gold",
    )
    respuesta = (
        "La Credencial Gold ofrece salas VIP y seguros de viaje [2]. "
        "Su cuota de manejo es de 37.300 COP (mensual) [1].\n\n"
        f"Fuentes:\n- {URL}\n- {url_beneficios}"
    )
    modelo = ModeloGuion([respuesta], usos=[uso_modelo(180, 60)])
    fila_gold = Fila(
        concepto="Credencial Gold*",
        categoria="tarifas",
        valor="37.300",
        moneda="COP",
        recargos="",
        periodicidad="mensual",
        vigente_desde="2025-11-20",
        origen="tarifario",
        pagina="data/gold/documents/tarifas.md",
        fuente=URL,
    )
    escenario = preparar(
        monkeypatch,
        tmp_path,
        modelo=modelo,
        filas=[fila_gold],
        fragmentos=[beneficios],
    )

    respuesta_http = preguntar(
        escenario.cliente,
        "¿Qué beneficios tiene la Credencial Gold y cuánto cuesta su cuota de manejo?",
        "hilo-mixto",
    )
    cuerpo = respuesta_http.json()

    assert respuesta_http.status_code == 200
    assert cuerpo["turno"] == "T"
    assert cuerpo["ruta"] == "mixta"
    assert cuerpo["motivo"] == "mixta"
    assert cuerpo["uso_modelo"] is True
    assert {fuente["url"] for fuente in cuerpo["fuentes"]} == {URL, url_beneficios}
    assert "37.300" in cuerpo["respuesta"]
    assert cuerpo["tokens_entrada"] == 180
    assert cuerpo["costo_usd"] > 0


def test_cortesia_no_consume_tope(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Con el tope agotado, un saludo sigue respondiendo: no usa modelo."""
    escenario = preparar(monkeypatch, tmp_path, fragmentos=[fragmento()])
    escenario.gasto.sumar(1.0, 1000, llamadas=1)

    respuesta = preguntar(escenario.cliente, "buenos días", "hilo-tope")

    assert respuesta.status_code == 200
    assert respuesta.json()["ruta"] == "cortesia"
    assert respuesta.json()["costo_usd"] == 0.0
