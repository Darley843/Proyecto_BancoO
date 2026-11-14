"""Pruebas sin red de `POST /api/preguntar/stream`: etapas, final, errores y memoria.

Reutilizan los dobles de `test_sucursal_preguntar` (grafo real con modelo y
recuperador falsos) para comprobar que el streaming entrega un evento por nodo
y cierra con el mismo cuerpo que `POST /api/preguntar`.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from test_sucursal_preguntar import (
    PREGUNTA_BOVEDA,
    PREGUNTA_RECHAZO,
    PREGUNTA_TABLERO,
    RESPUESTA_BOVEDA,
    URL,
    ModeloGuion,
    RecuperadorFalso,
    fragmento,
    preparar,
    uso_modelo,
)

from banco_occidente_corpus.boveda.tipos import Fragmento
from banco_occidente_corpus.sucursal.api import PreguntarRespuesta
from banco_occidente_corpus.sucursal.preguntar import ErrorSucursal
from banco_occidente_corpus.sucursal.transmision import (
    ETAPAS,
    GrafoConAvance,
    MensajeTurno,
    TransmisionTurno,
    evento_de_tarea,
)
from banco_occidente_corpus.tablero.tipos import Fila

#: Campos que cambian en cada turno y no se comparan entre rutas.
VOLATILES = {"turno_numero", "tiempo_s"}


def leer_eventos(texto: str) -> list[tuple[str, dict[str, Any]]]:
    """Convierte el cuerpo SSE en una lista de `(evento, datos)`."""
    eventos: list[tuple[str, dict[str, Any]]] = []
    for bloque in texto.strip().split("\n\n"):
        nombre = ""
        datos = ""
        for linea in bloque.splitlines():
            if linea.startswith("event: "):
                nombre = linea.removeprefix("event: ")
            elif linea.startswith("data: "):
                datos = linea.removeprefix("data: ")
        eventos.append((nombre, json.loads(datos)))
    return eventos


def preguntar_stream(
    cliente: TestClient,
    pregunta: str,
    hilo: str = "ses-1",
    perfil_id: str = "",
) -> Any:
    """Envía una pregunta a la ruta de streaming y devuelve la respuesta HTTP."""
    cuerpo: dict[str, str] = {"pregunta": pregunta, "thread_id": hilo}
    if perfil_id:
        cuerpo["perfil_id"] = perfil_id
    return cliente.post("/api/preguntar/stream", json=cuerpo)


def etapas(eventos: list[tuple[str, dict[str, Any]]]) -> list[tuple[str, str]]:
    """Devuelve `(nodo, estado)` de los eventos `etapa`, en orden."""
    return [(datos["nodo"], datos["estado"]) for nombre, datos in eventos if nombre == "etapa"]


def test_boveda_transmite_un_evento_por_nodo(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """La ruta de la Bóveda emite inicio y fin de cada nodo y cierra con `final`."""
    modelo = ModeloGuion([RESPUESTA_BOVEDA])
    escenario = preparar(monkeypatch, tmp_path, modelo=modelo, fragmentos=[fragmento()])

    respuesta = preguntar_stream(escenario.cliente, PREGUNTA_BOVEDA, "hilo-b")
    eventos = leer_eventos(respuesta.text)

    assert respuesta.status_code == 200
    assert respuesta.headers["content-type"].startswith("text/event-stream")
    assert respuesta.headers["cache-control"] == "no-cache"
    assert etapas(eventos) == [
        ("reformular", "en_curso"),
        ("reformular", "hecho"),
        ("digiturno", "en_curso"),
        ("digiturno", "hecho"),
        ("boveda", "en_curso"),
        ("boveda", "hecho"),
        ("redactar", "en_curso"),
        ("redactar", "hecho"),
    ]
    nombres = [nombre for nombre, _ in eventos]
    assert nombres[-1] == "final"
    assert nombres.count("final") == 1
    digiturno = [d for n, d in eventos if n == "etapa" and d["nodo"] == "digiturno"][-1]
    assert digiturno["etapa"] == "router"
    assert digiturno["detalle"]["ruta"] == "boveda"
    boveda = [d for n, d in eventos if n == "etapa" and d["nodo"] == "boveda"][-1]
    assert boveda["detalle"] == {"fragmentos": 1}

    final = eventos[-1][1]
    assert set(final) == set(PreguntarRespuesta.model_fields)
    assert final["turno"] == "B"
    assert final["respuesta"] == RESPUESTA_BOVEDA
    assert final["fuentes"][0]["url"] == fragmento().url
    assert final["costo_usd"] > 0


def test_las_etapas_no_llevan_la_pregunta_ni_el_hilo(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Solo el evento `final` lleva la respuesta; las etapas no copian texto del cliente."""
    modelo = ModeloGuion([RESPUESTA_BOVEDA])
    escenario = preparar(monkeypatch, tmp_path, modelo=modelo, fragmentos=[fragmento()])

    eventos = leer_eventos(preguntar_stream(escenario.cliente, PREGUNTA_BOVEDA, "hilo-p").text)

    for nombre, datos in eventos:
        if nombre != "etapa":
            continue
        crudo = json.dumps(datos, ensure_ascii=False)
        assert PREGUNTA_BOVEDA not in crudo
        assert "hilo-p" not in crudo
        assert "1965" not in crudo
        assert datos["etapa"] in {etapa for etapa, _ in ETAPAS.values()}


def test_tablero_responde_con_plantilla_en_streaming(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """El Tablero avisa que respondió sin modelo y no pasa por la Bóveda."""
    escenario = preparar(monkeypatch, tmp_path, fragmentos=[fragmento()])

    eventos = leer_eventos(preguntar_stream(escenario.cliente, PREGUNTA_TABLERO, "hilo-t").text)

    nodos = [nodo for nodo, estado in etapas(eventos) if estado == "hecho"]
    assert nodos == ["reformular", "digiturno", "tablero", "redactar"]
    tablero = [d for n, d in eventos if n == "etapa" and d["nodo"] == "tablero"][-1]
    assert tablero["detalle"] == {"filas": 1, "plantilla": True}
    final = eventos[-1][1]
    assert final["turno"] == "T"
    assert final["uso_modelo"] is False


def test_saludo_muestra_la_cortesia_sin_busqueda(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Un saludo pasa por el nodo de cortesía y nunca por la Bóveda (criterio 2.3)."""
    escenario = preparar(monkeypatch, tmp_path, fragmentos=[fragmento()])

    eventos = leer_eventos(preguntar_stream(escenario.cliente, "Hola", "hilo-hola").text)

    nodos = [nodo for nodo, estado in etapas(eventos) if estado == "hecho"]
    assert "boveda" not in nodos
    assert "cortesia" in nodos
    digiturno = [d for n, d in eventos if n == "etapa" and d["nodo"] == "digiturno"][-1]
    assert digiturno["detalle"]["ruta"] == "cortesia"
    assert "Cortesía" in digiturno["texto"]
    cortesia = [d for n, d in eventos if n == "etapa" and d["nodo"] == "cortesia"][-1]
    assert "0 tokens" in cortesia["texto"]
    assert eventos[-1][1]["ruta"] == "cortesia"


def test_pregunta_mixta_muestra_las_dos_fuentes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """La ruta mixta avisa cuántas filas y fragmentos aportó cada fuente."""
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
        modelo=ModeloGuion([respuesta], usos=[uso_modelo(180, 60)]),
        filas=[fila_gold],
        fragmentos=[beneficios],
    )

    eventos = leer_eventos(
        preguntar_stream(
            escenario.cliente,
            "¿Qué beneficios tiene la Credencial Gold y cuánto cuesta su cuota de manejo?",
            "hilo-mixto",
        ).text
    )

    digiturno = [d for n, d in eventos if n == "etapa" and d["nodo"] == "digiturno"][-1]
    assert digiturno["detalle"]["ruta"] == "mixta"
    mixto = [d for n, d in eventos if n == "etapa" and d["nodo"] == "mixto"][-1]
    assert mixto["etapa"] == "buscando"
    assert mixto["detalle"] == {"filas": 1, "fragmentos": 1}
    assert eventos[-1][1]["ruta"] == "mixta"


def test_final_igual_a_la_ruta_clasica(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """El evento `final` trae el mismo cuerpo que `POST /api/preguntar`."""
    escenario = preparar(monkeypatch, tmp_path, fragmentos=[fragmento()])

    clasica = escenario.cliente.post(
        "/api/preguntar", json={"pregunta": PREGUNTA_RECHAZO, "thread_id": "hilo-1"}
    ).json()
    final = leer_eventos(preguntar_stream(escenario.cliente, PREGUNTA_RECHAZO, "hilo-2").text)[-1]

    assert final[0] == "final"
    sin_volatiles = {k: v for k, v in final[1].items() if k not in VOLATILES}
    assert sin_volatiles == {k: v for k, v in clasica.items() if k not in VOLATILES}
    assert final[1]["turno_numero"] == clasica["turno_numero"] + 1


def test_rechazos_previos_usan_el_json_de_siempre(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Pregunta vacía y falta de hilo responden 422 con el contrato, sin SSE."""
    escenario = preparar(monkeypatch, tmp_path)

    vacia = preguntar_stream(escenario.cliente, "   ", "hilo-v")
    sin_hilo = preguntar_stream(escenario.cliente, PREGUNTA_BOVEDA, "")

    assert vacia.status_code == 422
    assert vacia.json()["error"]["codigo"] == "pregunta_vacia"
    assert sin_hilo.status_code == 422
    assert sin_hilo.json()["error"]["codigo"] == "thread_id_ausente"


def test_indice_ausente_devuelve_503(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Sin índice la ruta responde 503 antes de abrir el streaming."""
    escenario = preparar(monkeypatch, tmp_path)
    (tmp_path / "data/boveda/indice.json").unlink()

    respuesta = preguntar_stream(escenario.cliente, PREGUNTA_BOVEDA, "hilo-i")

    assert respuesta.status_code == 503
    assert respuesta.json()["error"]["codigo"] == "indice_no_listo"


class RecuperadorRoto(RecuperadorFalso):
    """Recuperador que falla, para simular un corte a mitad del turno."""

    def buscar(self, consulta: str, k: int = 5) -> list[Fragmento]:
        """Lanza un error como si Ollama se hubiera caído."""
        raise RuntimeError("ollama no responde")


def test_fallo_a_mitad_del_turno_cierra_con_evento_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Si un nodo falla, el streaming cierra con `error` y no filtra el detalle."""
    modelo = ModeloGuion([RESPUESTA_BOVEDA])
    escenario = preparar(monkeypatch, tmp_path, modelo=modelo, fragmentos=[fragmento()])
    # Las dependencias son un dataclass congelado; se cambia el recuperador
    # después de compilar el grafo para simular que Ollama se cae a mitad del turno.
    object.__setattr__(escenario.dependencias, "recuperador", RecuperadorRoto([]))

    respuesta = preguntar_stream(escenario.cliente, PREGUNTA_BOVEDA, "hilo-e")
    eventos = leer_eventos(respuesta.text)

    assert respuesta.status_code == 200
    assert eventos[-1][0] == "error"
    assert eventos[-1][1]["error"]["codigo"] == "error_interno"
    assert "ollama" not in respuesta.text
    assert ("boveda", "en_curso") in etapas(eventos)
    assert ("boveda", "hecho") not in etapas(eventos)


def test_el_turno_queda_en_la_memoria_del_hilo(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Un turno atendido por streaming queda guardado en el `checkpointer`."""
    modelo = ModeloGuion([RESPUESTA_BOVEDA])
    escenario = preparar(monkeypatch, tmp_path, modelo=modelo, fragmentos=[fragmento()])

    preguntar_stream(escenario.cliente, PREGUNTA_BOVEDA, "hilo-m")
    estado = escenario.grafo.get_state({"configurable": {"thread_id": "hilo-m"}})

    contenidos = [mensaje.content for mensaje in estado.values["messages"]]
    assert contenidos == [PREGUNTA_BOVEDA, RESPUESTA_BOVEDA]


def test_acierto_de_cache_solo_envia_final(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Una respuesta de la caché no ejecuta nodos: llega directo el `final`."""
    modelo = ModeloGuion([RESPUESTA_BOVEDA])
    escenario = preparar(monkeypatch, tmp_path, modelo=modelo, fragmentos=[fragmento()])

    preguntar_stream(escenario.cliente, PREGUNTA_BOVEDA, "hilo-c1")
    eventos = leer_eventos(preguntar_stream(escenario.cliente, PREGUNTA_BOVEDA, "hilo-c2").text)

    assert [nombre for nombre, _ in eventos] == ["final"]
    assert eventos[0][1]["cache"] is True


class GrafoEspia:
    """Grafo falso que registra si lo llamaron con `invoke` o con `stream`."""

    def __init__(self) -> None:
        """Empieza sin llamadas."""
        self.llamadas: list[str] = []

    def invoke(self, entrada: Any, config: Any = None) -> dict[str, Any]:
        """Registra la llamada y devuelve un estado mínimo."""
        self.llamadas.append("invoke")
        return {"respuesta": "ok"}

    def get_state(self, config: Any) -> str:
        """Responde algo reconocible para probar la delegación."""
        return "estado-real"


def test_sin_oyente_la_envoltura_usa_invoke() -> None:
    """La ruta clásica sigue llamando a `invoke`; lo demás se delega igual."""
    espia = GrafoEspia()
    envoltura = GrafoConAvance(espia)

    assert envoltura.invoke({"pregunta": "x"}, config={}) == {"respuesta": "ok"}
    assert espia.llamadas == ["invoke"]
    assert envoltura.get_state({}) == "estado-real"
    assert envoltura.grafo_real is espia


def test_evento_de_tarea_ignora_nodos_internos_y_errores() -> None:
    """Solo los nodos públicos generan etapas; un nodo con error no."""
    assert evento_de_tarea({"name": "__start__", "input": {}}) is None
    assert evento_de_tarea({"name": "boveda", "error": "x", "result": None}) is None
    inicio = evento_de_tarea({"name": "digiturno", "input": {}})
    assert inicio is not None
    assert inicio["estado"] == "en_curso"
    assert inicio["etapa"] == "router"


def test_mensaje_como_sse() -> None:
    """El mensaje sale con `event:`, `data:` en JSON y una línea en blanco."""
    mensaje = MensajeTurno("etapa", {"texto": "Bóveda"})

    assert mensaje.como_sse() == 'event: etapa\ndata: {"texto":"Bóveda"}\n\n'


def test_transmision_entrega_el_error_del_servicio() -> None:
    """Un `ErrorSucursal` del servicio viaja con su estado HTTP y su código."""

    def atender() -> dict[str, Any]:
        """Falla como lo haría el tope diario."""
        raise ErrorSucursal(429, "tope_alcanzado", "Se alcanzó el tope.")

    transmision = TransmisionTurno(atender).iniciar()
    primero = transmision.siguiente()

    assert primero is not None
    assert primero.tipo == "error"
    assert primero.estado_http == 429
    assert primero.datos == {
        "error": {"codigo": "tope_alcanzado", "mensaje": "Se alcanzó el tope."}
    }
    assert transmision.siguiente() is None


def test_streaming_muestra_la_etapa_de_perfil(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """El nodo perfil se ve como etapa `memoria` y cierra con ruta perfil."""
    escenario = preparar(monkeypatch, tmp_path)

    respuesta = preguntar_stream(
        escenario.cliente,
        "trabajo en Carvajal",
        "hilo-perfil-stream",
        "ana",
    )
    eventos = leer_eventos(respuesta.text)

    assert respuesta.status_code == 200
    assert ("perfil", "en_curso") in etapas(eventos)
    assert ("perfil", "hecho") in etapas(eventos)
    perfil = [datos for nombre, datos in eventos if nombre == "etapa" and datos["nodo"] == "perfil"]
    assert perfil[-1]["etapa"] == "memoria"
    assert perfil[-1]["detalle"] == {"perfil": True, "guardado": True}

    final = eventos[-1][1]
    assert final["ruta"] == "perfil"
    assert final["turno"] == "B"
    assert final["uso_modelo"] is False
    assert final["fuentes"] == []
    assert "Carvajal" not in json.dumps(perfil, ensure_ascii=False)
