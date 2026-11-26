"""Pruebas del núcleo de preguntas del público a Pana (tarea 6.15).

Todo se prueba con dobles: la ficha, el recuperador BM25, la Ventanilla, el
modelo y el auditor se inyectan. No se abre red, no se crea un cliente real de
DeepSeek y no se toca Ollama ni Qdrant.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from decimal import Decimal
from inspect import signature
from pathlib import Path
from typing import Any

import pytest
from langchain_core.messages import AIMessage, BaseMessage

from banco_occidente_corpus.asistente.rag import neutralizar
from banco_occidente_corpus.asistente.validacion import contar_palabras
from banco_occidente_corpus.escena.contratos import (
    CifraEscena,
    FuenteCifra,
    HallazgoEscena,
    TurnoEscena,
    VeredictoAuditor,
)
from banco_occidente_corpus.escena.pregunta import (
    PII,
    RECHAZO,
    RESPALDO,
    EntradaFija,
    FichaPreguntas,
    LimitesPregunta,
    RespuestaVentanilla,
    cargar_ficha,
    cargar_limites_pregunta,
    responder_pregunta,
)
from banco_occidente_corpus.escena.proyecto import (
    FragmentoProyecto,
    RecuperadorBM25Proyecto,
    crear_recuperador_proyecto,
    es_pregunta_del_proyecto,
)

#: Referencia del fragmento de proyecto de las pruebas.
REFERENCIA_PROYECTO = "CONSTITUTION.md#base-de-datos-vectorial"


class ModeloFalso:
    """Modelo de chat que devuelve textos encolados o falla a propósito."""

    def __init__(
        self,
        respuestas: Sequence[str] = (),
        *,
        error: BaseException | None = None,
    ) -> None:
        """Guarda las respuestas y el error que debe lanzar `invoke`.

        Args:
            respuestas: textos que devuelve, en orden.
            error: excepción que lanza en la primera llamada; si falta, responde.
        """
        self.respuestas = list(respuestas)
        self.error = error
        self.llamadas = 0

    def invoke(self, mensajes: Sequence[BaseMessage], **_: Any) -> AIMessage:
        """Devuelve la siguiente respuesta o lanza el error configurado."""
        self.llamadas += 1
        if self.error is not None:
            raise self.error
        return AIMessage(content=self.respuestas.pop(0))


class RecuperadorFalso:
    """Recuperador de proyecto que devuelve los fragmentos ya decididos."""

    def __init__(self, fragmentos: Sequence[FragmentoProyecto] = ()) -> None:
        """Guarda los fragmentos que devolverá cada búsqueda."""
        self.fragmentos = list(fragmentos)
        self.llamadas: list[str] = []

    def buscar(self, consulta: str, k: int = 3) -> list[FragmentoProyecto]:
        """Registra la consulta y devuelve hasta `k` fragmentos."""
        self.llamadas.append(consulta)
        return self.fragmentos[:k]


class VentanillaFalsa:
    """Ventanilla inyectable que devuelve una respuesta fija o falla."""

    def __init__(
        self,
        respuesta: RespuestaVentanilla | None = None,
        *,
        error: BaseException | None = None,
    ) -> None:
        """Guarda la respuesta y el error opcional."""
        self.respuesta = respuesta
        self.error = error
        self.llamadas: list[str] = []

    def __call__(self, pregunta: str) -> RespuestaVentanilla | None:
        """Registra la pregunta y devuelve la respuesta o lanza el error."""
        self.llamadas.append(pregunta)
        if self.error is not None:
            raise self.error
        return self.respuesta


def _ficha() -> FichaPreguntas:
    """Ficha de prueba con dos respuestas fijas, sin las 17 de la 6.14."""
    return FichaPreguntas(
        entradas=(
            EntradaFija(
                id="alcance",
                variantes=("¿cuántas preguntas tiene el alcance?", "¿cuántas preguntas hay?"),
                respuesta="El alcance tiene 20 preguntas.",
                fuente="docs/ALCANCE.md#las-20-preguntas-del-alcance",
                cifras=(
                    CifraEscena(
                        etiqueta="preguntas del alcance",
                        valor=Decimal("20"),
                        valor_legible="20",
                        unidad="veces",
                        fuente=FuenteCifra(
                            tipo="documento",
                            referencia="docs/ALCANCE.md#las-20-preguntas-del-alcance",
                        ),
                    ),
                ),
            ),
            EntradaFija(
                id="pana",
                variantes=("¿quién es Pana?", "¿qué personaje es Pana?"),
                respuesta="Pana es el anfitrión ficticio de la escena.",
                fuente="docs/ESCENA.md#los-rostros",
            ),
        )
    )


def _fragmento(
    *,
    puntaje: float = 1.2,
    texto: str = "Qdrant local en data/boveda/qdrant desde 2026, colección boveda.",
) -> FragmentoProyecto:
    """Fragmento de proyecto con la referencia que citan las pruebas."""
    return FragmentoProyecto(
        ruta="CONSTITUTION.md",
        ancla="base-de-datos-vectorial",
        titulo="Base de datos vectorial",
        texto=texto,
        puntaje=puntaje,
    )


def _cifra_tasa() -> CifraEscena:
    """Cifra de tasa del Tablero para la respuesta de la Ventanilla."""
    return CifraEscena(
        etiqueta="tasa de libre inversión",
        valor=Decimal("0.2817"),
        valor_legible="28,17 % E.A.",
        unidad="porcentaje_ea",
        fuente=FuenteCifra(
            tipo="gold",
            referencia="data/gold/tasas/tasas-personas-2026-11.jsonl#libre_inversion",
        ),
    )


def _auditor_conforme(turno: TurnoEscena) -> VeredictoAuditor:
    """Auditor que no encuentra nada."""
    return VeredictoAuditor(
        veredicto="conforme",
        hallazgos=(),
        turnos_revisados=(turno.id,),
        reglas=(),
    )


def _auditor_objeta(turno: TurnoEscena) -> VeredictoAuditor:
    """Auditor que objeta por una cifra inventada."""
    return VeredictoAuditor(
        veredicto="objeta",
        hallazgos=(
            HallazgoEscena(
                codigo="cifra_inventada",
                turno_id=turno.id,
                detalle="La cifra no está en la fuente.",
                gravedad="alta",
            ),
        ),
        turnos_revisados=(turno.id,),
        reglas=("cifra_inventada",),
    )


def test_fija_responde_guion_fijo_sin_modelo() -> None:
    """Una pregunta de la ficha se responde literal, sin modelo y sin fuente hablada."""
    modelo = ModeloFalso(["no debería llamarse"])
    recuperador = RecuperadorFalso()
    ventanilla = VentanillaFalsa()

    turno = responder_pregunta(
        "¿cuántas preguntas tiene el alcance?",
        ficha=_ficha(),
        recuperador=recuperador,
        ventanilla=ventanilla,
        modelo=modelo,
    )

    assert turno.origen == "guion_fijo"
    assert turno.personaje == "pana"
    assert turno.texto == "El alcance tiene 20 preguntas."
    assert "Fuente:" not in turno.texto
    assert turno.subtitulo == (
        "El alcance tiene 20 preguntas. Fuente: docs/ALCANCE.md#las-20-preguntas-del-alcance"
    )
    assert turno.cifras[0].fuente.tipo == "documento"
    assert modelo.llamadas == 0
    assert recuperador.llamadas == []
    assert ventanilla.llamadas == []


def test_proyecto_resume_con_fuente_documento_y_sin_fuente_hablada() -> None:
    """El paso 2 usa BM25, el modelo y deja la cita en el subtítulo, no en la voz."""
    modelo = ModeloFalso(["Usamos Qdrant desde 2026 para la colección local."])
    recuperador = RecuperadorFalso([_fragmento()])

    turno = responder_pregunta(
        "¿por qué usaron Qdrant?",
        ficha=_ficha(),
        recuperador=recuperador,
        ventanilla=VentanillaFalsa(),
        modelo=modelo,
    )

    assert turno.origen == "llm"
    assert "Fuente:" not in turno.texto
    assert turno.subtitulo == f"{turno.texto} Fuente: {REFERENCIA_PROYECTO}"
    assert modelo.llamadas == 1
    assert recuperador.llamadas == ["¿por qué usaron Qdrant?"]
    assert any(
        cifra.fuente.tipo == "documento" and cifra.fuente.referencia == REFERENCIA_PROYECTO
        for cifra in turno.cifras
    )


@pytest.mark.parametrize(
    ("ruta", "pregunta"),
    [
        ("T", "¿cuál es la tasa de libre inversión?"),
        ("B", "¿qué productos ofrece el banco?"),
    ],
)
def test_banco_usa_la_ventanilla(ruta: str, pregunta: str) -> None:
    """Una pregunta del banco pasa por la Ventanilla y conserva su origen."""
    ventanilla = VentanillaFalsa(
        RespuestaVentanilla(
            texto="La tasa de libre inversión está entre 20,56 % y 28,17 % E.A.",
            ruta=ruta,  # type: ignore[arg-type]
            origen="reglas",
            cifras=(_cifra_tasa(),),
            fuente="data/gold/tasas/tasas-personas-2026-11.jsonl#libre_inversion",
        )
    )
    recuperador = RecuperadorFalso()

    turno = responder_pregunta(
        pregunta,
        ficha=_ficha(),
        recuperador=recuperador,
        ventanilla=ventanilla,
        modelo=ModeloFalso(["no debería llamarse"]),
    )

    assert turno.origen == "reglas"
    assert "Fuente:" not in turno.texto
    assert turno.subtitulo is not None and "Fuente: data/gold/tasas" in turno.subtitulo
    assert turno.cifras[0].fuente.tipo == "gold"
    assert ventanilla.llamadas == [pregunta]
    assert recuperador.llamadas == []


def test_fuera_de_dominio_responde_la_frase_fija() -> None:
    """La ruta X de la Ventanilla no se repite: Pana usa el rechazo fijo."""
    ventanilla = VentanillaFalsa(
        RespuestaVentanilla(texto="París es la capital de Francia.", ruta="X")
    )

    turno = responder_pregunta(
        "¿cuál es la capital de Francia?",
        ficha=_ficha(),
        recuperador=RecuperadorFalso(),
        ventanilla=ventanilla,
        modelo=ModeloFalso(["no debería llamarse"]),
    )

    assert turno.origen == "reglas"
    assert turno.texto == RECHAZO
    assert "Francia" not in turno.texto
    assert turno.cifras == ()
    assert ventanilla.llamadas == ["¿cuál es la capital de Francia?"]


def test_precedencia_fija_antes_que_banco() -> None:
    """Si la ficha coincide, no se consulta la Ventanilla aunque la pregunta mencione el banco."""
    ventanilla = VentanillaFalsa(
        RespuestaVentanilla(texto="Respuesta del banco", ruta="B", origen="llm")
    )

    turno = responder_pregunta(
        "¿cuántas preguntas tiene el alcance?",
        ficha=_ficha(),
        recuperador=RecuperadorFalso([_fragmento()]),
        ventanilla=ventanilla,
        modelo=ModeloFalso(["no debería llamarse"]),
    )

    assert turno.origen == "guion_fijo"
    assert ventanilla.llamadas == []


def test_precedencia_proyecto_antes_que_banco() -> None:
    """Si la pregunta mezcla proyecto y banco, gana el paso 2 y no se consulta la Ventanilla."""
    ventanilla = VentanillaFalsa(
        RespuestaVentanilla(texto="La tasa es 28,17 % E.A.", ruta="T", origen="llm")
    )

    turno = responder_pregunta(
        "¿por qué usaron Qdrant y cuál es la tasa?",
        ficha=_ficha(),
        recuperador=RecuperadorFalso([_fragmento()]),
        ventanilla=ventanilla,
        modelo=ModeloFalso(["Usamos Qdrant por los filtros y la colección local."]),
    )

    assert turno.origen == "llm"
    assert "Qdrant" in turno.texto
    assert ventanilla.llamadas == []


def test_puntaje_bajo_sigue_al_paso_siguiente_sin_inventar() -> None:
    """Si BM25 no supera el mínimo, la pregunta sigue a la Ventanilla."""
    ventanilla = VentanillaFalsa(
        RespuestaVentanilla(
            texto="La tasa de libre inversión está en el Tablero.",
            ruta="T",
            origen="reglas",
            fuente="los productos y tasas del banco, en el Tablero",
        )
    )

    turno = responder_pregunta(
        "¿por qué usaron Qdrant?",
        ficha=_ficha(),
        recuperador=RecuperadorFalso([_fragmento(puntaje=0.1)]),
        ventanilla=ventanilla,
        modelo=ModeloFalso(["no debería llamarse"]),
    )

    assert turno.origen == "reglas"
    assert turno.texto == "La tasa de libre inversión está en el Tablero."
    assert ventanilla.llamadas == ["¿por qué usaron Qdrant?"]


def test_corpus_del_proyecto_esta_acotado_al_repositorio(tmp_path: Path) -> None:
    """Solo se indexan los tres archivos de la raíz y los .md de docs/."""
    (tmp_path / "README.md").write_text("# README\n\nEl proyecto usa Qdrant.", encoding="utf-8")
    (tmp_path / "AGENTS.md").write_text("# AGENTS\n\nContexto del repositorio.", encoding="utf-8")
    (tmp_path / "CONSTITUTION.md").write_text(
        "# CONSTITUTION\n\n## Bóveda\n\nQdrant y el corpus.", encoding="utf-8"
    )
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "guia.md").write_text("# Guía\n\nEl Arqueo mide el RAG.", encoding="utf-8")
    (docs / "nota.txt").write_text("Qdrant fuera del corpus.", encoding="utf-8")
    (tmp_path / "fuera.md").write_text("# Fuera\n\nNo debe indexarse.", encoding="utf-8")
    datos = tmp_path / "data"
    datos.mkdir()
    (datos / "otro.md").write_text("# Otro\n\nTampoco debe indexarse.", encoding="utf-8")

    recuperador = RecuperadorBM25Proyecto(
        raiz=tmp_path,
        rutas=(
            "README.md",
            "AGENTS.md",
            "CONSTITUTION.md",
            "docs",
            "fuera.md",
            "data/otro.md",
            "../fuera.md",
        ),
    )
    antes = {ruta.relative_to(tmp_path).as_posix() for ruta in tmp_path.rglob("*")}
    assert recuperador.rutas_indexadas() == (
        "README.md",
        "AGENTS.md",
        "CONSTITUTION.md",
        "docs/guia.md",
    )
    recuperador.buscar("Qdrant", k=3)
    despues = {ruta.relative_to(tmp_path).as_posix() for ruta in tmp_path.rglob("*")}
    assert antes == despues


def test_crear_recuperador_proyecto_por_defecto_no_sale_del_repositorio() -> None:
    """El recuperador por defecto solo lee rutas del repositorio y no escribe."""
    recuperador = crear_recuperador_proyecto()
    assert "README.md" in recuperador.rutas_indexadas()
    assert "CONSTITUTION.md" in recuperador.rutas_indexadas()
    assert all(not ruta.startswith("..") for ruta in recuperador.rutas_indexadas())


def test_modelo_que_falla_usa_el_respaldo() -> None:
    """Un fallo del modelo devuelve la frase fija con origen reglas y sin cifras."""
    modelo = ModeloFalso(error=RuntimeError("sin red"))

    turno = responder_pregunta(
        "¿por qué usaron Qdrant?",
        ficha=_ficha(),
        recuperador=RecuperadorFalso([_fragmento()]),
        ventanilla=VentanillaFalsa(),
        modelo=modelo,
    )

    assert turno.origen == "reglas"
    assert turno.texto == RESPALDO
    assert turno.cifras == ()
    assert "Fuente:" not in turno.texto
    assert modelo.llamadas == 1


def test_auditor_que_objeta_usa_el_respaldo_y_deja_los_hallazgos() -> None:
    """Una objeción alta reemplaza el texto y adjunta el hallazgo, sin color."""
    turno = responder_pregunta(
        "¿cuántas preguntas tiene el alcance?",
        ficha=_ficha(),
        recuperador=RecuperadorFalso(),
        ventanilla=VentanillaFalsa(),
        auditor=_auditor_objeta,
        modelo=ModeloFalso(["no debería llamarse"]),
    )

    assert turno.origen == "reglas"
    assert turno.texto == RESPALDO
    assert turno.hallazgos[0].codigo == "cifra_inventada"
    assert turno.hallazgos[0].gravedad == "alta"


def test_auditor_conforme_adjunta_su_veredicto_sin_cambiar_el_texto() -> None:
    """Un auditor conforme no altera el turno."""
    turno = responder_pregunta(
        "¿cuántas preguntas tiene el alcance?",
        ficha=_ficha(),
        recuperador=RecuperadorFalso(),
        ventanilla=VentanillaFalsa(),
        auditor=_auditor_conforme,
    )

    assert turno.origen == "guion_fijo"
    assert turno.texto == "El alcance tiene 20 preguntas."
    assert turno.hallazgos == ()


def test_publico_con_dato_personal_recibe_el_rechazo_de_pii() -> None:
    """Al público no se le repite el teléfono: recibe una frase fija."""
    turno = responder_pregunta(
        "mi teléfono es 300 123 4567, ¿cuál es la tasa?",
        ficha=_ficha(),
        recuperador=RecuperadorFalso(),
        ventanilla=VentanillaFalsa(),
        modelo=ModeloFalso(["no debería llamarse"]),
        audiencia="publico",
    )

    assert turno.origen == "reglas"
    assert turno.texto == PII
    assert "300" not in turno.texto


def test_audiencia_por_defecto_es_publico_y_no_viene_del_cliente() -> None:
    """Sin audiencia explícita se aplica la PII pública, como fija el servidor."""
    assert signature(responder_pregunta).parameters["audiencia"].default == "publico"

    turno = responder_pregunta(
        "mi teléfono es 300 123 4567, ¿cuál es la tasa?",
        ficha=_ficha(),
        recuperador=RecuperadorFalso(),
        ventanilla=VentanillaFalsa(),
        modelo=ModeloFalso(["no debería llamarse"]),
    )

    assert turno.origen == "reglas"
    assert turno.texto == PII


def test_equipo_no_pasa_por_la_regla_de_pii() -> None:
    """El equipo puede preguntar con un correo sin que Pana rechace el turno."""
    turno = responder_pregunta(
        "¿por qué Qdrant? mi correo es prueba@example.com",
        ficha=_ficha(),
        recuperador=RecuperadorFalso([_fragmento()]),
        ventanilla=VentanillaFalsa(),
        modelo=ModeloFalso(["Usamos Qdrant por los filtros."]),
        audiencia="equipo",
    )

    assert turno.origen == "llm"
    assert "Qdrant" in turno.texto


def test_equipo_descarta_el_hallazgo_dato_personal() -> None:
    """El auditor no convierte un nombre del equipo en una objeción para el equipo."""

    def auditor_pii(turno: TurnoEscena) -> tuple[HallazgoEscena, ...]:
        return (
            HallazgoEscena(
                codigo="dato_personal",
                turno_id=turno.id,
                detalle="Correo del equipo en la respuesta.",
                gravedad="alta",
            ),
        )

    turno = responder_pregunta(
        "¿por qué Qdrant? mi correo es prueba@example.com",
        ficha=_ficha(),
        recuperador=RecuperadorFalso([_fragmento()]),
        ventanilla=VentanillaFalsa(),
        auditor=auditor_pii,
        modelo=ModeloFalso(["Usamos Qdrant por los filtros."]),
        audiencia="equipo",
    )

    assert turno.origen == "llm"
    assert turno.hallazgos == ()


def test_texto_del_modelo_se_recorta_a_40_palabras_sin_fuente() -> None:
    """El tope de palabras se aplica al texto hablado y no a la línea Fuente."""
    modelo = ModeloFalso(["palabra " * 80])

    turno = responder_pregunta(
        "¿por qué usaron Qdrant?",
        ficha=_ficha(),
        recuperador=RecuperadorFalso([_fragmento()]),
        ventanilla=VentanillaFalsa(),
        modelo=modelo,
        limites=LimitesPregunta(max_palabras=40),
    )

    assert contar_palabras(turno.texto) <= 40
    assert "Fuente:" not in turno.texto


def test_registro_mide_el_tiempo_sin_guardar_pregunta_ni_respuesta(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """El registro deja ruta, origen y milisegundos, nunca el texto del público."""
    with caplog.at_level(logging.INFO, logger="banco_occidente_corpus.escena.pregunta"):
        responder_pregunta(
            "¿cuál es la capital de Francia?",
            ficha=_ficha(),
            recuperador=RecuperadorFalso(),
            ventanilla=VentanillaFalsa(RespuestaVentanilla(texto="", ruta="X")),
            modelo=ModeloFalso(["no debería llamarse"]),
        )

    mensajes = [registro.getMessage() for registro in caplog.records]
    assert any(
        "evento=escena_pregunta" in mensaje and "ms=" in mensaje and "ruta=rechazo" in mensaje
        for mensaje in mensajes
    )
    assert all("Francia" not in mensaje for mensaje in mensajes)


def test_cargar_limites_pregunta_del_toml() -> None:
    """Los límites salen de `[preguntas]` y respetan el tope de 40 palabras."""
    limites = cargar_limites_pregunta()

    assert limites.max_palabras == 40
    assert limites.tiempo_total_segundos == 8.0
    assert limites.tiempo_llamada_segundos == 4.0
    assert limites.puntaje_minimo == 0.9


def test_cargar_ficha_sin_fijas_devuelve_solo_las_frases(tmp_path: Path) -> None:
    """La ficha vacía de la 6.14 conserva las frases fijas y el umbral."""
    archivo = tmp_path / "escena.toml"
    archivo.write_text(
        "\n".join(
            (
                "[preguntas]",
                "umbral_fijo = 0.7",
                f'rechazo = "{RECHAZO}"',
                f'respaldo = "{RESPALDO}"',
                f'pii = "{PII}"',
            )
        ),
        encoding="utf-8",
    )

    ficha = cargar_ficha(archivo, raiz=tmp_path)

    assert ficha.entradas == ()
    assert ficha.umbral_fijo == 0.7
    assert ficha.rechazo == RECHAZO


def test_cargar_ficha_descarta_la_fuente_que_no_existe(tmp_path: Path) -> None:
    """Una entrada cuya fuente no existe no se carga."""
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "guia.md").write_text("# Guía\n\nQdrant.", encoding="utf-8")
    archivo = tmp_path / "escena.toml"
    archivo.write_text(
        "\n".join(
            (
                "[preguntas]",
                "[[preguntas.fijas]]",
                'id = "buena"',
                'variantes = ["¿por qué Qdrant?"]',
                'respuesta = "Usamos Qdrant por los filtros."',
                'fuente = "docs/guia.md#qdrant"',
                "[[preguntas.fijas]]",
                'id = "mala"',
                'variantes = ["¿qué es el Arqueo?"]',
                'respuesta = "El Arqueo mide el RAG."',
                'fuente = "docs/no-existe.md#arqueo"',
            )
        ),
        encoding="utf-8",
    )

    ficha = cargar_ficha(archivo, raiz=tmp_path)

    assert [entrada.id for entrada in ficha.entradas] == ["buena"]


def test_las_palabras_de_codigo_y_repositorio_entran_al_paso_2() -> None:
    """El profesor puede preguntar por código, diagramas, ramas y tokens."""
    preguntas = (
        "¿Cómo está organizado el código?",
        "¿Qué es un token en git?",
        "¿Muéstrame los pull requests?",
        "¿Tienen un diagrama de arquitectura?",
        "¿Usan pruebas automáticas?",
    )

    for pregunta in preguntas:
        assert es_pregunta_del_proyecto(pregunta), pregunta


def test_es_pregunta_del_proyecto_distingue_banco_y_proyecto() -> None:
    """La señal léxica evita que una pregunta de tasa entre al paso 2."""
    assert es_pregunta_del_proyecto("¿por qué usaron Qdrant?")
    assert es_pregunta_del_proyecto("¿cómo construyeron el corpus?")
    assert not es_pregunta_del_proyecto("¿cuánto cuesta la cuota de la tarjeta?")
    assert not es_pregunta_del_proyecto("¿cuál es la capital de Francia?")


def test_las_palabras_nuevas_del_proyecto_entran_al_paso_2() -> None:
    """Las palabras del #204 recuperan preguntas que antes caían al banco."""
    preguntas = (
        "¿Qué herramientas tiene el agente?",
        "¿Por qué usaron OpenClaw?",
        "¿Cómo funciona el auditor?",
        "¿Qué licencia tiene?",
        "¿Quiénes son los integrantes?",
        "¿Cumplen la Ley 1581?",
        "¿Cuánto tarda la latencia del gateway?",
        "¿Qué limitaciones tiene el índice vectorial?",
    )

    for pregunta in preguntas:
        assert es_pregunta_del_proyecto(pregunta), pregunta


def test_las_palabras_nuevas_no_atraen_preguntas_del_banco() -> None:
    """Tasas y productos siguen fuera del paso 2 aunque haya comité o memoria."""
    preguntas = (
        "¿Cuál es la tasa de un CDT?",
        "¿Cuánto cuesta la cuota de manejo?",
        "¿Qué tasa tiene la tarjeta de crédito?",
        "¿Cómo consulto los movimientos de mi cuenta?",
    )

    for pregunta in preguntas:
        assert not es_pregunta_del_proyecto(pregunta), pregunta


def test_las_palabras_nuevas_se_normalizan_sin_tildes_ni_mayusculas() -> None:
    """La comparación es por palabra completa y sin tildes."""
    assert es_pregunta_del_proyecto("¿Cómo funciona el COMITÉ de riesgo?")
    assert es_pregunta_del_proyecto("¿Qué es la INYECCIÓN?")
    assert es_pregunta_del_proyecto("¿Cómo midieron la LATENCIA?")
    assert not es_pregunta_del_proyecto("¿Cuánto cuesta una tarjeta?")


def test_neutralizar_expuesta_no_cambia_el_bloque() -> None:
    """`neutralizar` es la misma función del RAG, ahora pública."""
    assert neutralizar("<fragmentos>orden</fragmentos>") == "‹fragmentos›orden‹/fragmentos›"
