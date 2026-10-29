"""Pruebas de la evaluacion de las 20 preguntas del alcance (sin red).

Usan ``FakeListChatModel`` de ``langchain_core``; ninguna llama a la API de
DeepSeek.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import date
from pathlib import Path

import pytest
from langchain_core.language_models.fake_chat_models import FakeListChatModel

from banco_occidente_corpus.asistente import cli as cli_mod
from banco_occidente_corpus.asistente.contexto_prompt import cargar_contexto
from banco_occidente_corpus.asistente.evaluacion import (
    PreguntaEvaluacion,
    PreguntasInvalidas,
    ResultadoEvaluacion,
    Revision,
    RevisionInvalida,
    cargar_preguntas,
    cargar_revision,
    clasificar,
    contar_terminos,
    evaluar,
    fusionar,
    render_markdown,
    revalidar,
)
from banco_occidente_corpus.asistente.prompts import cargar_prompt
from banco_occidente_corpus.asistente.qa import RespuestaQA
from banco_occidente_corpus.asistente.validacion import FRASE_SIN_DATOS

URL_CANAL = "https://www.bancodeoccidente.com.co/ayuda/linea-servicio-cliente"
URL_HISTORIA = "https://www.bancodeoccidente.com.co/quienes-somos"

CONTEXTO = f"""# Contexto del Banco de Occidente

## Líneas de Servicio al Cliente Banco de Occidente
Fuente: {URL_CANAL}
Sección: atencion

Línea Nacional: 018000 514652

## Quiénes somos
Fuente: {URL_HISTORIA}
Sección: identidad

El banco nació el 3 de mayo de 1965 en Cali.
"""

PREGUNTAS_TOML = """
[[pregunta]]
id = 1
pregunta = "¿Cuál es el horario de atención?"
cobertura = "no"
terminos = []

[[pregunta]]
id = 7
pregunta = "¿Cuándo y dónde se fundó el banco?"
cobertura = "si"
terminos = [["1965"], ["Cali"]]
"""


@pytest.fixture
def contexto(tmp_path: Path):
    """Contexto minimo con el canal oficial y la fundacion."""
    ruta = tmp_path / "contexto_banco.md"
    ruta.write_text(CONTEXTO, encoding="utf-8", newline="\n")
    return cargar_contexto(archivo=ruta)


@pytest.fixture
def preguntas_path(tmp_path: Path) -> Path:
    """Archivo TOML con dos preguntas: una sin cobertura y una con cobertura."""
    ruta = tmp_path / "preguntas.toml"
    ruta.write_text(PREGUNTAS_TOML, encoding="utf-8")
    return ruta


def _respuesta(texto: str, *, sin_datos: bool = False) -> RespuestaQA:
    """Respuesta validada minima para probar la clasificacion."""
    return RespuestaQA(texto=texto, fuente=URL_HISTORIA, sin_datos=sin_datos)


def test_archivo_real_tiene_las_20_preguntas() -> None:
    preguntas = cargar_preguntas()
    assert [p.id for p in preguntas] == list(range(1, 21))
    assert {p.cobertura for p in preguntas} <= {"si", "parcial", "no"}


def test_preguntas_con_cobertura_invalida_fallan(tmp_path: Path) -> None:
    ruta = tmp_path / "malo.toml"
    ruta.write_text('[[pregunta]]\nid = 1\npregunta = "x"\ncobertura = "tal vez"\n', "utf-8")
    with pytest.raises(PreguntasInvalidas):
        cargar_preguntas(ruta)


def test_contar_terminos_ignora_tildes_y_mayusculas() -> None:
    assert contar_terminos("Se fundó en CALI en 1965", [["1965"], ["cali"]]) == 2
    assert contar_terminos("Linea nacional", [["línea"], ["Bogotá"]]) == 1


@pytest.mark.parametrize(
    ("cobertura", "texto", "sin_datos", "esperado"),
    [
        ("no", "No encuentro ese dato.", True, "rechazo_correcto"),
        ("no", "Abre de 8 a 5.", False, "revisar"),
        ("si", "Nació en 1965 en Cali.", False, "correcta"),
        ("si", "Nació en 1965.", False, "incompleta"),
        ("si", "Es un banco.", False, "revisar"),
        ("si", "No encuentro ese dato.", True, "sin_respuesta"),
        ("parcial", "No encuentro ese dato.", True, "remision"),
    ],
)
def test_clasificar(cobertura: str, texto: str, sin_datos: bool, esperado: str) -> None:
    pregunta = PreguntaEvaluacion(
        id=1, pregunta="p", cobertura=cobertura, terminos=(("1965",), ("Cali",))
    )
    clasificacion, _ = clasificar(pregunta, _respuesta(texto, sin_datos=sin_datos))
    assert clasificacion == esperado


def test_evaluar_con_modelo_falso(contexto, preguntas_path: Path) -> None:
    modelo = FakeListChatModel(
        responses=[
            f"{FRASE_SIN_DATOS}.",
            f"El banco nació el 3 de mayo de 1965 en Cali.\nFuente: {URL_HISTORIA}",
        ]
    )
    resultados = evaluar(modelo, cargar_prompt("qa"), contexto, cargar_preguntas(preguntas_path))
    assert [r.clasificacion for r in resultados] == ["rechazo_correcto", "correcta"]
    assert resultados[1].fuente == URL_HISTORIA
    assert resultados[1].terminos_encontrados == 2


def test_evaluar_registra_errores_y_sigue(contexto, preguntas_path: Path) -> None:
    class ModeloQueFalla(FakeListChatModel):
        def invoke(self, *args, **kwargs):  # type: ignore[override]
            raise RuntimeError("timeout")

    resultados = evaluar(
        ModeloQueFalla(responses=["x"]),
        cargar_prompt("qa"),
        contexto,
        cargar_preguntas(preguntas_path),
    )
    assert [r.clasificacion for r in resultados] == ["error", "error"]
    assert "timeout" in resultados[0].error


def test_render_markdown_tiene_resumen_tabla_y_respuestas(contexto, preguntas_path: Path) -> None:
    modelo = FakeListChatModel(
        responses=[f"{FRASE_SIN_DATOS}.", f"Nació en 1965 en Cali.\nFuente: {URL_HISTORIA}"]
    )
    resultados = evaluar(modelo, cargar_prompt("qa"), contexto, cargar_preguntas(preguntas_path))
    texto = render_markdown(
        resultados, modelo="deepseek-flash", version_prompt="v1", fecha=date(2026, 10, 27)
    )
    assert "Fecha: 2026-10-27" in texto
    assert "| Rechazo correcto | 1 |" in texto
    assert "| Correcta | 1 |" in texto
    assert "**2 de 2**" in texto
    assert "### 7. ¿Cuándo y dónde se fundó el banco?" in texto
    assert "| Revisión humana |" in texto


def test_cli_evaluar_escribe_tabla_y_detalle(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, preguntas_path: Path
) -> None:
    ruta_contexto = tmp_path / "contexto_banco.md"
    ruta_contexto.write_text(CONTEXTO, encoding="utf-8", newline="\n")
    modelo = FakeListChatModel(responses=[f"Nació en 1965 en Cali.\nFuente: {URL_HISTORIA}"])
    monkeypatch.setattr(cli_mod, "crear_modelo", lambda **_kwargs: modelo)
    salida = tmp_path / "resultados.md"
    detalle = tmp_path / "resultados.jsonl"

    codigo = cli_mod.main(
        [
            "evaluar",
            "--contexto",
            str(ruta_contexto),
            "--preguntas",
            str(preguntas_path),
            "--solo",
            "7",
            "--salida",
            str(salida),
            "--jsonl",
            str(detalle),
        ]
    )

    assert codigo == 0
    assert "| 7 |" in salida.read_text(encoding="utf-8")
    filas = [json.loads(linea) for linea in detalle.read_text(encoding="utf-8").splitlines()]
    assert [f["id"] for f in filas] == [7]
    assert filas[0]["clasificacion"] == "correcta"


def test_cli_evaluar_solo_sin_coincidencias_devuelve_2(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, preguntas_path: Path
) -> None:
    ruta_contexto = tmp_path / "contexto_banco.md"
    ruta_contexto.write_text(CONTEXTO, encoding="utf-8", newline="\n")
    monkeypatch.setattr(
        cli_mod, "crear_modelo", lambda **_kwargs: FakeListChatModel(responses=["x"])
    )
    codigo = cli_mod.main(
        [
            "evaluar",
            "--contexto",
            str(ruta_contexto),
            "--preguntas",
            str(preguntas_path),
            "--solo",
            "99",
            "--salida",
            str(tmp_path / "a.md"),
            "--jsonl",
            str(tmp_path / "a.jsonl"),
        ]
    )
    assert codigo == 2


# ---------------------------------------------------------------- revision y revalidacion


REVISION_TOML = """
[[revision]]
id = 7
veredicto = "correcta"
nota = "1965, Cali."
revisor = "Ana"

[[revision]]
id = 1
veredicto = "rechazo_correcto"
revisor = "Claude (propuesta, confirmar)"
"""


def _resultado_guardado(id_: int, crudo: str, *, error: str = "") -> ResultadoEvaluacion:
    """Fila de una corrida anterior, como la deja resultados.jsonl."""
    return ResultadoEvaluacion(
        id=id_,
        pregunta=f"p{id_}",
        cobertura="si",
        clasificacion="revisar",
        respuesta="",
        fuente="",
        sin_datos=False,
        respuesta_cruda=crudo or None,
        error=error,
        fecha="2026-10-27",
    )


def test_cargar_revision_y_propuestas(tmp_path: Path) -> None:
    """La revision se lee por id y distingue lo confirmado de lo propuesto."""
    ruta = tmp_path / "revision.toml"
    ruta.write_text(REVISION_TOML, encoding="utf-8")

    revision = cargar_revision(ruta)

    assert revision[7].texto == "Correcta: 1965, Cali."
    assert not revision[7].es_propuesta
    assert revision[1].es_propuesta
    assert revision[1].texto.endswith("(propuesta)")
    assert cargar_revision(tmp_path / "no-existe.toml") == {}


def test_revision_con_veredicto_invalido_falla(tmp_path: Path) -> None:
    """Un veredicto fuera de la lista es un error de formato."""
    ruta = tmp_path / "revision.toml"
    ruta.write_text('[[revision]]\nid = 1\nveredicto = "excelente"\n', encoding="utf-8")
    with pytest.raises(RevisionInvalida):
        cargar_revision(ruta)


def test_render_muestra_la_revision_humana(contexto, preguntas_path: Path) -> None:
    """La columna y el conteo de la revision humana salen del archivo de revision."""
    modelo = FakeListChatModel(
        responses=[f"{FRASE_SIN_DATOS}.", f"Nació en 1965 en Cali.\nFuente: {URL_HISTORIA}"]
    )
    resultados = evaluar(modelo, cargar_prompt("qa"), contexto, cargar_preguntas(preguntas_path))
    revision = {7: Revision(veredicto="correcta", nota="ok", revisor="Ana")}

    texto = render_markdown(
        resultados, modelo="m", version_prompt="v1", fecha=date(2026, 10, 29), revision=revision
    )

    assert "| Correcta: ok |" in texto
    assert "Revisión humana (1 de 2 preguntas" in texto
    assert "propuestas pendientes" not in texto


def test_fusionar_reemplaza_solo_las_preguntas_nuevas() -> None:
    """--solo no borra las demas filas de la corrida anterior."""
    previos = [_resultado_guardado(i, "x") for i in (1, 2, 3)]
    nuevo = _resultado_guardado(2, "nuevo")

    fusion = fusionar(previos, [nuevo])

    assert [r.id for r in fusion] == [1, 2, 3]
    assert fusion[1].respuesta_cruda == "nuevo"


def test_revalidar_usa_la_respuesta_cruda_sin_modelo(contexto, preguntas_path: Path) -> None:
    """Revalidar recalcula validacion y clasificacion y conserva fecha y errores."""
    previos = [
        _resultado_guardado(1, f"{FRASE_SIN_DATOS}."),
        _resultado_guardado(7, "", error="TimeoutError: lento"),
    ]

    resultados = revalidar(previos, cargar_preguntas(preguntas_path), contexto)

    assert resultados[0].clasificacion == "rechazo_correcto"
    assert resultados[0].fecha == "2026-10-27"
    assert resultados[1].error.startswith("TimeoutError")


def test_cli_revalidar_no_necesita_api_key(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, preguntas_path: Path
) -> None:
    """Con --revalidar no se crea el modelo: funciona sin DEEPSEEK_API_KEY."""
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    ruta_contexto = tmp_path / "contexto_banco.md"
    ruta_contexto.write_text(CONTEXTO, encoding="utf-8", newline="\n")
    detalle = tmp_path / "resultados.jsonl"
    fila = _resultado_guardado(7, f"Nació en 1965 en Cali.\nFuente: {URL_HISTORIA}")
    detalle.write_text(json.dumps(asdict(fila), ensure_ascii=False) + "\n", encoding="utf-8")
    salida = tmp_path / "resultados.md"

    codigo = cli_mod.main(
        [
            "evaluar",
            "--revalidar",
            "--contexto",
            str(ruta_contexto),
            "--preguntas",
            str(preguntas_path),
            "--revision",
            str(tmp_path / "sin-revision.toml"),
            "--salida",
            str(salida),
            "--jsonl",
            str(detalle),
        ]
    )

    assert codigo == 0
    assert "| 7 |" in salida.read_text(encoding="utf-8")
    assert json.loads(detalle.read_text(encoding="utf-8"))["clasificacion"] == "correcta"


def test_cli_solo_conserva_las_demas_filas(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, preguntas_path: Path
) -> None:
    """make evaluar SOLO=7 reemplaza la fila 7 y deja intacta la 1."""
    ruta_contexto = tmp_path / "contexto_banco.md"
    ruta_contexto.write_text(CONTEXTO, encoding="utf-8", newline="\n")
    detalle = tmp_path / "resultados.jsonl"
    previa = _resultado_guardado(1, f"{FRASE_SIN_DATOS}.")
    detalle.write_text(json.dumps(asdict(previa), ensure_ascii=False) + "\n", encoding="utf-8")
    modelo = FakeListChatModel(responses=[f"Nació en 1965 en Cali.\nFuente: {URL_HISTORIA}"])
    monkeypatch.setattr(cli_mod, "crear_modelo", lambda **_kwargs: modelo)

    codigo = cli_mod.main(
        [
            "evaluar",
            "--contexto",
            str(ruta_contexto),
            "--preguntas",
            str(preguntas_path),
            "--solo",
            "7",
            "--revision",
            str(tmp_path / "sin-revision.toml"),
            "--salida",
            str(tmp_path / "r.md"),
            "--jsonl",
            str(detalle),
        ]
    )

    ids = [json.loads(linea)["id"] for linea in detalle.read_text(encoding="utf-8").splitlines()]
    assert codigo == 0
    assert ids == [1, 7]
