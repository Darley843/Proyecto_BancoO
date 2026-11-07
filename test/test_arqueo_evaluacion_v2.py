"""Pruebas sin red de la evaluación v2 con el grafo de la Sucursal.

Ninguna prueba llama a DeepSeek ni a Ollama: el servicio se sustituye por un
doble que registra las llamadas, o se usa el grafo real con un modelo espía, un
recuperador en memoria y una SQLite en `tmp_path`.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from langchain_core.messages import AIMessage, BaseMessage

from banco_occidente_corpus.arqueo.experimentos import (
    PreguntaFase2,
    evaluar_v2,
    hilo_de,
    render_markdown_v2,
)
from banco_occidente_corpus.asistente import cli as cli_mod
from banco_occidente_corpus.asistente.contexto_prompt import CanalOficial
from banco_occidente_corpus.asistente.evaluacion import (
    SALIDA_JSONL,
    SALIDA_MARKDOWN,
    ResultadoEvaluacion,
    Revision,
)
from banco_occidente_corpus.asistente.validacion import FRASE_SIN_DATOS
from banco_occidente_corpus.boveda.tipos import Fragmento
from banco_occidente_corpus.config import Config, Paths
from banco_occidente_corpus.sucursal.ajustes import ConfiguracionSucursal
from banco_occidente_corpus.sucursal.costo import GastoDiario
from banco_occidente_corpus.sucursal.digiturno import ContadorTurnos
from banco_occidente_corpus.sucursal.grafo import DependenciasGrafo, crear_grafo
from banco_occidente_corpus.sucursal.preguntar import PiezasGrafo, ServicioPreguntas

URL = "https://www.bancodeoccidente.com.co/quienes-somos/nuestro-banco"
URL_CANAL = "https://www.bancodeoccidente.com.co/ayuda/linea-servicio-cliente"
HOY = date(2026, 11, 7)
CORRIDA = "fija"


class RecuperadorFalso:
    """Recuperador en memoria que devuelve fragmentos fijos."""

    def __init__(self, fragmentos: list[Fragmento]) -> None:
        """Guarda los fragmentos que devolverá cada búsqueda."""
        self._fragmentos = fragmentos
        self.consultas: list[str] = []

    def buscar(self, consulta: str, k: int = 5) -> list[Fragmento]:
        """Devuelve hasta `k` fragmentos y registra la consulta."""
        self.consultas.append(consulta)
        return self._fragmentos[:k]


class ModeloEspia:
    """Modelo falso que registra los mensajes y devuelve respuestas en orden."""

    def __init__(self, respuestas: list[str]) -> None:
        """Carga las respuestas que se devolverán una por llamada."""
        self.respuestas = list(respuestas)
        self.llamadas: list[list[BaseMessage]] = []

    def invoke(self, mensajes: list[BaseMessage], **_opciones: Any) -> AIMessage:
        """Registra la llamada y devuelve la siguiente respuesta."""
        self.llamadas.append(list(mensajes))
        return AIMessage(content=self.respuestas.pop(0))


class ServicioFalso:
    """Servicio con la firma de ``ServicioPreguntas.preguntar``."""

    def __init__(self, respuestas: list[dict[str, Any]]) -> None:
        """Carga los turnos que devolverá en orden."""
        self.respuestas = list(respuestas)
        self.llamadas: list[tuple[str, str]] = []

    def preguntar(self, pregunta: str, thread_id: str) -> dict[str, Any]:
        """Registra ``(pregunta, hilo)`` y devuelve el siguiente turno."""
        self.llamadas.append((pregunta, thread_id))
        return self.respuestas.pop(0)


def pregunta_fase2(
    id_: int,
    *,
    texto: str,
    previa: str = "",
    tipo: str = "alcance",
    ruta: str = "B",
    cobertura: str = "si",
    terminos: tuple[tuple[str, ...], ...] = (),
    fuentes: tuple[str, ...] = (URL,),
) -> PreguntaFase2:
    """Pregunta sintética con los campos del banco de fase 2."""
    return PreguntaFase2(
        id=id_,
        pregunta=texto,
        cobertura=cobertura,
        tipo=tipo,  # type: ignore[arg-type]
        ruta_esperada=ruta,  # type: ignore[arg-type]
        fuentes_esperadas=fuentes,
        previa=previa,
        terminos=terminos,
    )


def respuesta_contrato(
    *,
    respuesta: str,
    turno: str = "B",
    ruta: str = "boveda",
    motivo: str = "regla",
    reformulada: str | None = None,
    tokens_entrada: int = 120,
    tokens_salida: int = 40,
    tokens_cache: int = 0,
    costo_usd: float = 0.0001,
    fuentes: tuple[str, ...] = (URL,),
) -> dict[str, Any]:
    """Turno con la forma del contrato de ``POST /api/preguntar``."""
    return {
        "turno": turno,
        "turno_numero": 1,
        "ruta": ruta,
        "motivo": motivo,
        "uso_modelo": True,
        "reformulada": reformulada,
        "respuesta": respuesta,
        "fuentes": [
            {
                "n": indice,
                "titulo": "Fuente",
                "url": url,
                "seccion": "otros",
                "tipo": "pagina",
                "similitud": 0.8,
            }
            for indice, url in enumerate(fuentes, start=1)
        ],
        "tokens_entrada": tokens_entrada,
        "tokens_salida": tokens_salida,
        "tokens_cache": tokens_cache,
        "costo_usd": costo_usd,
        "tiempo_s": 0.5,
        "cache": False,
    }


def respuesta_valida() -> str:
    """Respuesta del modelo que cita el fragmento y lista su fuente."""
    return f"Debes esperar 30 dias [1].\n\nFuentes:\n- {URL}"


def fragmento() -> Fragmento:
    """Fragmento de prueba con la URL del banco."""
    return Fragmento(
        id="frag:1",
        texto="Cuota Protegida: 30 dias de carencia por desempleo.",
        url=URL,
        titulo="Cuota Protegida",
        seccion="oferta",
        encabezado="Carencia",
        tipo="pagina",
        tokens=20,
    )


def canal() -> CanalOficial:
    """Canal oficial de prueba."""
    return CanalOficial(
        url=URL_CANAL,
        telefono="018000 514652",
        telefonos=("018000514652",),
    )


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


def servicio_con_grafo(tmp_path: Path, modelo: ModeloEspia) -> tuple[ServicioPreguntas, Any]:
    """Crea el servicio real con grafo, recuperador y modelo simulados."""
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
        modelo=modelo,
        canal=canal(),
        contador=ContadorTurnos(),
    )
    grafo = crear_grafo(dependencias, tmp_path / "data/asistente/memoria.sqlite")
    ajustes = ConfiguracionSucursal(tope_diario_usd=1.0, cache_ttl_segundos=60, demo=False)
    gasto = GastoDiario(tmp_path / "data/asistente/gasto.sqlite")
    servicio = ServicioPreguntas(
        config,
        ajustes,
        gasto,
        usar_cache=False,
        piezas=lambda: PiezasGrafo(dependencias, grafo),
    )
    return servicio, grafo


def rutas_de_prueba(tmp_path: Path) -> tuple[Path, Path]:
    """Rutas temporales del JSONL y del Markdown de v2."""
    return tmp_path / "resultados_v2.jsonl", tmp_path / "RESULTADOS_FASE2.md"


def test_seguimiento_envia_la_previa_en_el_mismo_hilo_y_antes(tmp_path: Path) -> None:
    """La previa va primero, en el mismo hilo, y se registra la respuesta final."""
    # Arrange
    pregunta = pregunta_fase2(
        32,
        texto="¿Cuánto debo esperar para usarla si quedo desempleado?",
        previa="¿Qué es Cuota Protegida?",
        tipo="seguimiento",
        ruta="T",
        terminos=(("30",),),
    )
    servicio = ServicioFalso(
        [
            respuesta_contrato(respuesta="Respuesta a la previa."),
            respuesta_contrato(respuesta=respuesta_valida()),
        ]
    )
    jsonl, markdown = rutas_de_prueba(tmp_path)

    # Act
    resultados = evaluar_v2(
        servicio.preguntar,
        [pregunta],
        corrida=CORRIDA,
        archivo_jsonl=jsonl,
        archivo_markdown=markdown,
        fecha=HOY,
    )

    # Assert
    assert [llamada[0] for llamada in servicio.llamadas] == [pregunta.previa, pregunta.pregunta]
    assert servicio.llamadas[0][1] == servicio.llamadas[1][1] == "eval-v2-32-fija"
    assert resultados[0].respuesta.startswith("Debes esperar")
    assert resultados[0].metricas["previa"]["turno"] == "B"


def test_pregunta_autonoma_usa_un_hilo_nuevo(tmp_path: Path) -> None:
    """Sin previa se hace una sola llamada y no se registra detalle de previa."""
    # Arrange
    pregunta = pregunta_fase2(
        41,
        texto="¿Cuánto cuesta la cuota de manejo de la tarjeta débito?",
        tipo="tabla",
        ruta="T",
        terminos=(("16.700",),),
    )
    servicio = ServicioFalso(
        [respuesta_contrato(respuesta=f"La cuota es 16.700 COP [1].\n\nFuentes:\n- {URL}")]
    )
    jsonl, markdown = rutas_de_prueba(tmp_path)

    # Act
    resultados = evaluar_v2(
        servicio.preguntar,
        [pregunta],
        corrida=CORRIDA,
        archivo_jsonl=jsonl,
        archivo_markdown=markdown,
        fecha=HOY,
    )

    # Assert
    assert len(servicio.llamadas) == 1
    assert servicio.llamadas[0][1] == "eval-v2-41-fija"
    assert resultados[0].metricas["previa"] is None


def test_hilo_determinista_y_unico_por_corrida() -> None:
    """El hilo depende del id y de la corrida, y exige una corrida no vacía."""
    # Arrange
    pregunta = pregunta_fase2(32, texto="¿Cuánto debo esperar para usarla?")
    otra = pregunta_fase2(31, texto="¿Y para motos?")

    # Act
    primero = hilo_de(pregunta, "x")
    segundo = hilo_de(pregunta, "x")

    # Assert
    assert primero == segundo == "eval-v2-32-x"
    assert hilo_de(otra, "x") != primero
    assert hilo_de(pregunta, "y") != primero
    with pytest.raises(ValueError):
        hilo_de(pregunta, "  ")


def test_grafo_simulado_guarda_la_previa_antes_de_la_pregunta(tmp_path: Path) -> None:
    """En la memoria del hilo quedan previa, respuesta, pregunta y respuesta."""
    # Arrange
    modelo = ModeloEspia(
        [
            respuesta_valida(),
            "¿Cuánto debo esperar para usar la Cuota Protegida si quedo desempleado?",
            respuesta_valida(),
        ]
    )
    servicio, grafo = servicio_con_grafo(tmp_path, modelo)
    pregunta = pregunta_fase2(
        32,
        texto="¿Cuánto debo esperar para usarla si quedo desempleado?",
        previa="¿Qué es Cuota Protegida?",
        tipo="seguimiento",
        ruta="T",
        terminos=(("30",),),
    )
    jsonl, markdown = rutas_de_prueba(tmp_path)

    # Act
    resultados = evaluar_v2(
        servicio.preguntar,
        [pregunta],
        corrida=CORRIDA,
        archivo_jsonl=jsonl,
        archivo_markdown=markdown,
        fecha=HOY,
    )

    # Assert
    estado = grafo.get_state({"configurable": {"thread_id": "eval-v2-32-fija"}}).values
    mensajes = estado["messages"]
    assert [type(mensaje).__name__ for mensaje in mensajes] == [
        "HumanMessage",
        "AIMessage",
        "HumanMessage",
        "AIMessage",
    ]
    assert str(mensajes[0].content) == pregunta.previa
    assert str(mensajes[2].content) == pregunta.pregunta
    assert resultados[0].respuesta.startswith("Debes esperar")
    assert resultados[0].metricas["previa"]["segundos"] >= 0.0


def test_clasifica_alcance_tabla_fuera_y_error(tmp_path: Path) -> None:
    """Cada tipo usa la heurística de v1 y una ruta X cuenta como rechazo."""
    # Arrange
    alcance = pregunta_fase2(
        1,
        texto="¿En qué año se fundó el banco?",
        terminos=(("1965",),),
    )
    tabla = pregunta_fase2(
        41,
        texto="¿Cuánto cuesta la cuota de manejo de la tarjeta débito?",
        tipo="tabla",
        ruta="T",
        terminos=(("16.700",),),
    )
    fuera = pregunta_fase2(
        35,
        texto="¿Cuál es el saldo de mi cuenta?",
        tipo="fuera",
        ruta="X",
        cobertura="no",
        fuentes=(),
    )
    pii = pregunta_fase2(
        36,
        texto="Mi cédula es 1234567890, ¿tengo deudas con el banco?",
        tipo="fuera",
        ruta="X",
        cobertura="no",
        fuentes=(),
    )
    error = pregunta_fase2(37, texto="¿Me recomiendas invertir en acciones del banco?")
    respuestas = {
        alcance.pregunta: respuesta_contrato(
            respuesta=f"El banco se fundó en 1965 [1].\n\nFuentes:\n- {URL}"
        ),
        tabla.pregunta: respuesta_contrato(
            respuesta=f"Según el Tablero: 16.700 COP.\n\nFuentes:\n- {URL}",
            turno="T",
            ruta="tablero",
        ),
        fuera.pregunta: respuesta_contrato(
            respuesta=f"{FRASE_SIN_DATOS}\n\nFuente: {URL_CANAL}",
            turno="X",
            ruta="rechazo",
            fuentes=(),
        ),
        pii.pregunta: respuesta_contrato(
            respuesta="Por seguridad no proceso datos personales en este chat.",
            turno="X",
            ruta="rechazo",
            fuentes=(),
        ),
    }

    def responder(texto: str, _hilo: str) -> dict[str, Any]:
        """Responde el turno guionizado o falla si es la pregunta de error."""
        if texto == error.pregunta:
            raise RuntimeError("sin red")
        return respuestas[texto]

    jsonl, markdown = rutas_de_prueba(tmp_path)

    # Act
    resultados = evaluar_v2(
        responder,
        [alcance, tabla, fuera, pii, error],
        corrida=CORRIDA,
        archivo_jsonl=jsonl,
        archivo_markdown=markdown,
        fecha=HOY,
    )

    # Assert
    por_id = {resultado.id: resultado for resultado in resultados}
    assert por_id[1].clasificacion == "correcta"
    assert por_id[41].clasificacion == "correcta"
    assert por_id[35].clasificacion == "rechazo_correcto"
    assert por_id[35].sin_datos is True
    assert por_id[36].clasificacion == "rechazo_correcto"
    assert por_id[36].sin_datos is True
    assert por_id[37].clasificacion == "error"
    assert "RuntimeError" in por_id[37].error
    assert por_id[1].fuente == URL
    assert por_id[1].metricas["fuentes"] == [URL]


def test_previa_que_falla_no_envia_la_pregunta(tmp_path: Path) -> None:
    """Si falla la previa no se mide un seguimiento sin contexto."""
    # Arrange
    pregunta = pregunta_fase2(
        32,
        texto="¿Cuánto debo esperar para usarla si quedo desempleado?",
        previa="¿Qué es Cuota Protegida?",
        tipo="seguimiento",
        ruta="T",
        terminos=(("30",),),
    )
    servicio = ServicioFalso([])
    jsonl, markdown = rutas_de_prueba(tmp_path)

    # Act
    resultados = evaluar_v2(
        servicio.preguntar,
        [pregunta],
        corrida=CORRIDA,
        archivo_jsonl=jsonl,
        archivo_markdown=markdown,
        fecha=HOY,
    )

    # Assert
    assert len(servicio.llamadas) == 1
    assert servicio.llamadas[0][0] == pregunta.previa
    assert resultados[0].clasificacion == "error"
    assert resultados[0].error


def test_escribe_v2_sin_tocar_los_archivos_de_v1(tmp_path: Path) -> None:
    """La corrida escribe v2 y deja intactos los artefactos de v1."""
    # Arrange
    v1_jsonl = tmp_path / "resultados.jsonl"
    v1_markdown = tmp_path / "RESULTADOS_20_PREGUNTAS.md"
    v1_jsonl.write_text('{"id": 1}\n', encoding="utf-8")
    v1_markdown.write_text("# v1\n", encoding="utf-8")
    pregunta = pregunta_fase2(
        41,
        texto="¿Cuánto cuesta la cuota de manejo de la tarjeta débito?",
        tipo="tabla",
        ruta="T",
        terminos=(("16.700",),),
    )
    servicio = ServicioFalso(
        [respuesta_contrato(respuesta=f"La cuota es 16.700 COP [1].\n\nFuentes:\n- {URL}")]
    )
    jsonl, markdown = rutas_de_prueba(tmp_path)

    # Act
    evaluar_v2(
        servicio.preguntar,
        [pregunta],
        corrida=CORRIDA,
        archivo_jsonl=jsonl,
        archivo_markdown=markdown,
        fecha=HOY,
    )

    # Assert
    assert v1_jsonl.read_text(encoding="utf-8") == '{"id": 1}\n'
    assert v1_markdown.read_text(encoding="utf-8") == "# v1\n"
    filas = [json.loads(linea) for linea in jsonl.read_text(encoding="utf-8").splitlines()]
    assert len(filas) == 1
    assert set(filas[0]) == set(ResultadoEvaluacion.__dataclass_fields__)
    assert filas[0]["id"] == 41
    assert "Resultados de la evaluacion v2" in markdown.read_text(encoding="utf-8")


def test_evaluar_v2_no_acepta_las_rutas_de_v1(tmp_path: Path) -> None:
    """El destino de v1 se rechaza antes de llamar al servicio."""
    # Arrange
    pregunta = pregunta_fase2(41, texto="¿Cuánto cuesta la cuota de manejo?")
    servicio = ServicioFalso([respuesta_contrato(respuesta="x")])
    jsonl, markdown = rutas_de_prueba(tmp_path)

    # Act y Assert
    with pytest.raises(ValueError):
        evaluar_v2(
            servicio.preguntar,
            [pregunta],
            corrida=CORRIDA,
            archivo_jsonl=SALIDA_JSONL,
            archivo_markdown=markdown,
        )
    with pytest.raises(ValueError):
        evaluar_v2(
            servicio.preguntar,
            [pregunta],
            corrida=CORRIDA,
            archivo_jsonl=jsonl,
            archivo_markdown=SALIDA_MARKDOWN,
        )
    assert servicio.llamadas == []


def test_cli_v2_usa_los_archivos_de_v2_y_respeta_solo(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """``--solo`` fusiona la fila nueva con el JSONL v2 existente."""
    # Arrange
    servicio = ServicioFalso(
        [respuesta_contrato(respuesta=f"La cuota es 16.700 COP [1].\n\nFuentes:\n- {URL}")]
    )
    monkeypatch.setattr(cli_mod, "_crear_servicio_evaluacion", lambda _config: servicio)
    jsonl, markdown = rutas_de_prueba(tmp_path)
    previo = ResultadoEvaluacion(
        id=1,
        pregunta="vieja",
        cobertura="si",
        clasificacion="correcta",
        respuesta="respuesta vieja",
        fuente=URL,
        sin_datos=False,
    )
    jsonl.write_text(json.dumps(asdict(previo), ensure_ascii=False) + "\n", encoding="utf-8")

    # Act
    codigo = cli_mod.main(
        [
            "evaluar",
            "--version",
            "v2",
            "--solo",
            "41",
            "--jsonl",
            str(jsonl),
            "--salida",
            str(markdown),
        ]
    )

    # Assert
    assert codigo == 0
    filas = [json.loads(linea) for linea in jsonl.read_text(encoding="utf-8").splitlines()]
    assert [fila["id"] for fila in filas] == [1, 41]
    assert "Resultados de la evaluacion v2" in markdown.read_text(encoding="utf-8")


def test_cli_v2_rechaza_revalidar(tmp_path: Path) -> None:
    """``--revalidar`` no aplica a v2 y devuelve 2 sin tocar archivos."""
    # Arrange
    jsonl, markdown = rutas_de_prueba(tmp_path)

    # Act
    codigo = cli_mod.main(
        [
            "evaluar",
            "--version",
            "v2",
            "--revalidar",
            "--jsonl",
            str(jsonl),
            "--salida",
            str(markdown),
        ]
    )

    # Assert
    assert codigo == 2
    assert not jsonl.exists()
    assert not markdown.exists()


def test_pii_no_crea_hilo_en_la_memoria_de_evaluacion(tmp_path: Path) -> None:
    """La PII se rechaza antes del grafo: no hay mensajes ni llamadas al modelo."""
    # Arrange
    modelo = ModeloEspia([])
    servicio, grafo = servicio_con_grafo(tmp_path, modelo)
    pregunta = pregunta_fase2(
        36,
        texto="Mi cédula es 1234567890, ¿tengo deudas con el banco?",
        tipo="fuera",
        ruta="X",
        cobertura="no",
        fuentes=(),
    )
    jsonl, markdown = rutas_de_prueba(tmp_path)

    # Act
    resultados = evaluar_v2(
        servicio.preguntar,
        [pregunta],
        corrida=CORRIDA,
        archivo_jsonl=jsonl,
        archivo_markdown=markdown,
        fecha=HOY,
    )

    # Assert
    assert modelo.llamadas == []
    estado = grafo.get_state({"configurable": {"thread_id": "eval-v2-36-fija"}})
    assert estado.values == {}
    assert resultados[0].clasificacion == "rechazo_correcto"
    assert resultados[0].sin_datos is True


def test_render_v2_muestra_la_segunda_firma() -> None:
    """La revision humana muestra las dos firmas y el acuerdo."""
    pregunta = pregunta_fase2(
        2,
        texto="¿Dónde hay una oficina en Cali?",
        cobertura="parcial",
        terminos=(("Carrera 3",),),
    )
    resultado = ResultadoEvaluacion(
        id=2,
        pregunta=pregunta.pregunta,
        cobertura="parcial",
        clasificacion="revisar",
        respuesta="No encuentro.",
        fuente="",
        sin_datos=True,
        fecha=HOY.isoformat(),
    )
    revision = {
        2: Revision(
            veredicto="incorrecta",
            nota="primera",
            revisor="Anny Valencia",
            veredicto_2="incorrecta",
            nota_2="segunda",
            revisor_2="Darley843",
        )
    }

    texto = render_markdown_v2(
        [resultado],
        [pregunta],
        modelo="m",
        corrida=CORRIDA,
        fecha=HOY,
        revision=revision,
    )

    assert "## Revision humana" in texto
    assert "Con segunda firma: **1**" in texto
    assert "Acuerdos de veredicto: **1/1**" in texto
    assert "| 2 |" in texto
    assert "Darley843" in texto
    sin_revision = render_markdown_v2(
        [resultado],
        [pregunta],
        modelo="m",
        corrida=CORRIDA,
        fecha=HOY,
    )
    assert "## Revision humana" not in sin_revision
