"""Pruebas sin red del barrido de pesos y las comparaciones del Arqueo.

No se llama a Ollama ni a DeepSeek: los embeddings son `DeterministicFakeEmbedding`
y el almacen vectorial es un doble en memoria.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, cast

import pytest
from langchain_core.embeddings import DeterministicFakeEmbedding

from banco_occidente_corpus.arqueo.experimentos import (
    PESOS_BARRIDO,
    Barrido,
    DetallePregunta,
    PreguntaFase2,
    RutaPregunta,
    TipoPregunta,
    aciertos_por_revision,
    barrer_pesos,
    cargar_preguntas_fase2,
    comparar_pesos,
    comparar_versiones,
    consulta_de,
    diferencias_vectorial_directo,
    etiqueta_pesos,
    ids_por_ruta,
    medir_configuracion,
    normalizar_url,
    posicion_en_top,
    vectorial_directo,
)
from banco_occidente_corpus.arqueo.metricas import K_RECALL, hit_at_k, mrr
from banco_occidente_corpus.asistente.evaluacion import (
    Revision,
    cargar_preguntas,
)
from banco_occidente_corpus.boveda.almacen import Coincidencia
from banco_occidente_corpus.boveda.configuracion import ConfiguracionRecuperacion
from banco_occidente_corpus.boveda.tipos import Fragmento

URL_A = "https://www.bancodeoccidente.com.co/a"
URL_B = "https://www.bancodeoccidente.com.co/b"
URL_C = "https://www.bancodeoccidente.com.co/c"
URL_X = "https://www.bancodeoccidente.com.co/no-indexada"


class AlmacenFijo:
    """Almacen en memoria que devuelve el mismo orden para cualquier consulta."""

    def __init__(self, fragmentos: Sequence[Fragmento]) -> None:
        self._coincidencias = [
            Coincidencia(
                id=fragmento.id,
                documento=fragmento.texto,
                metadatos={
                    "id": fragmento.id,
                    "url": fragmento.url,
                    "titulo": fragmento.titulo,
                    "seccion": fragmento.seccion,
                    "encabezado": fragmento.encabezado,
                    "tipo": fragmento.tipo,
                    "tokens": fragmento.tokens,
                },
                distancia=0.1 * posicion,
            )
            for posicion, fragmento in enumerate(fragmentos, start=1)
        ]
        self.agregados = 0
        self.reinicios = 0
        self.busquedas = 0

    def crear(self) -> None:
        """No hace nada: el almacen ya existe en memoria."""

    def agregar(
        self,
        ids: Sequence[str],
        vectores: Sequence[Sequence[float]],
        documentos: Sequence[str],
        metadatos: Sequence[dict[str, Any]],
    ) -> None:
        """Registra que no se esperaba una insercion."""
        self.agregados += 1

    def buscar(
        self,
        vector: Sequence[float],
        k: int = 5,
        filtro: Mapping[str, Any] | None = None,
    ) -> list[Coincidencia]:
        """Devuelve el orden fijo recortado a k."""
        self.busquedas += 1
        return self._coincidencias[:k]

    def vectores(self, ids: Sequence[str]) -> dict[str, list[float]]:
        """No guarda vectores: el recuperador los calcula con sus embeddings."""
        return {}

    def contar(self) -> int:
        """Devuelve el numero de fragmentos del doble."""
        return len(self._coincidencias)

    def reiniciar(self) -> None:
        """Registra que no se esperaba un reinicio."""
        self.reinicios += 1

    def cerrar(self) -> None:
        """No hace nada: el doble vive en memoria y no tiene cliente que liberar."""


class AlmacenPorVentana(AlmacenFijo):
    """Almacen que devuelve un orden distinto segun la ventana pedida.

    Con k=5 pone la URL esperada en la primera posicion; con k=10 devuelve solo
    los diez distractores. Sirve para comprobar que hit@5 y MRR usan la busqueda
    corta y recall@10/nDCG@10 la busqueda larga.
    """

    def __init__(self, esperada: Fragmento, distractores: Sequence[Fragmento]) -> None:
        super().__init__([esperada, *distractores])
        self._esperada = esperada
        self._distractores = list(distractores)
        self.ventanas: list[int] = []

    def buscar(
        self,
        vector: Sequence[float],
        k: int = 5,
        filtro: Mapping[str, Any] | None = None,
    ) -> list[Coincidencia]:
        """Registra la ventana y devuelve el orden que corresponde a k."""
        self.busquedas += 1
        self.ventanas.append(k)
        orden = [self._esperada, *self._distractores] if k <= 5 else self._distractores
        return [
            Coincidencia(
                id=fragmento.id,
                documento=fragmento.texto,
                metadatos={
                    "id": fragmento.id,
                    "url": fragmento.url,
                    "titulo": fragmento.titulo,
                    "seccion": fragmento.seccion,
                    "encabezado": fragmento.encabezado,
                    "tipo": fragmento.tipo,
                    "tokens": fragmento.tokens,
                },
                distancia=0.1 * posicion,
            )
            for posicion, fragmento in enumerate(orden, start=1)
        ][:k]


def fragmento(identificador: str, texto: str, url: str) -> Fragmento:
    """Construye un fragmento de prueba."""
    return Fragmento(
        id=identificador,
        texto=texto,
        url=url,
        titulo="Productos",
        seccion="oferta",
        encabezado="Tarjetas",
        tipo="pagina",
        tokens=10,
    )


def pregunta(
    identificador: int,
    *,
    fuentes: tuple[str, ...],
    tipo: str = "alcance",
    ruta: str = "B",
    previa: str = "",
) -> PreguntaFase2:
    """Construye una pregunta de la fase 2 para las pruebas."""
    return PreguntaFase2(
        id=identificador,
        pregunta=f"pregunta {identificador}",
        cobertura="si",
        tipo=cast(TipoPregunta, tipo),
        ruta_esperada=cast(RutaPregunta, ruta),
        fuentes_esperadas=fuentes,
        previa=previa,
        terminos=(),
    )


def preguntas_de_prueba() -> list[PreguntaFase2]:
    """Banco minimo con las cuatro rutas y una fuente no indexada."""
    return [
        pregunta(1, fuentes=(URL_A,)),
        pregunta(2, fuentes=(URL_B,)),
        pregunta(3, fuentes=(URL_C,), tipo="tabla", ruta="T"),
        pregunta(4, fuentes=(), tipo="fuera", ruta="X"),
        pregunta(5, fuentes=(URL_A,), tipo="seguimiento", previa="previa"),
        pregunta(6, fuentes=(URL_X,)),
    ]


def fragmentos_de_prueba() -> list[Fragmento]:
    """Tres fragmentos indexados con las URL A, B y C."""
    return [
        fragmento("frag:a", "cuota de manejo", URL_A),
        fragmento("frag:b", "apertura de cuenta", URL_B),
        fragmento("frag:c", "linea de atencion", URL_C),
    ]


def barrido_de_prueba() -> Barrido:
    """Ejecuta el barrido sobre el banco y los fragmentos minimos."""
    return barrer_pesos(
        AlmacenFijo(fragmentos_de_prueba()),
        DeterministicFakeEmbedding(size=8),
        fragmentos_de_prueba(),
        preguntas_de_prueba(),
        configuracion=ConfiguracionRecuperacion(k=5, peso_vectorial=0.6, peso_bm25=0.4),
    )


def test_carga_las_44_preguntas_con_sus_conteos() -> None:
    """El banco real trae 44 preguntas y los cuatro tipos del diseno."""
    # Act
    preguntas = cargar_preguntas_fase2()

    # Assert
    assert len(preguntas) == 44
    assert len({pregunta.id for pregunta in preguntas}) == 44
    conteo = dict.fromkeys(("alcance", "tabla", "seguimiento", "fuera"), 0)
    for pregunta_fase2 in preguntas:
        conteo[pregunta_fase2.tipo] += 1
    assert conteo == {"alcance": 20, "tabla": 12, "seguimiento": 6, "fuera": 6}
    assert sum(1 for p in preguntas if p.fuentes_esperadas) == 36
    assert [p.id for p in preguntas if p.tipo == "seguimiento"] == [29, 30, 31, 32, 33, 34]


def test_cargador_v1_sigue_devolviendo_20() -> None:
    """El cargador estricto de v1 no cambia al agregar el de fase 2."""
    assert len(cargar_preguntas()) == 20


def test_seguimiento_sin_previa_falla(tmp_path: Path) -> None:
    """Una pregunta de seguimiento debe declarar la pregunta anterior."""
    # Arrange
    archivo = tmp_path / "preguntas.toml"
    archivo.write_text(
        '[[pregunta]]\nid = 1\npregunta = "sigue"\ncobertura = "si"\n'
        'tipo = "seguimiento"\nruta_esperada = "B"\nterminos = []\n'
        "fuentes_esperadas = []\n",
        encoding="utf-8",
    )

    # Act / Assert
    with pytest.raises(ValueError, match="previa"):
        cargar_preguntas_fase2(archivo)


def test_previa_fuera_de_seguimiento_falla(tmp_path: Path) -> None:
    """Solo los seguimientos llevan previa."""
    # Arrange
    archivo = tmp_path / "preguntas.toml"
    archivo.write_text(
        '[[pregunta]]\nid = 1\npregunta = "suelta"\ncobertura = "si"\n'
        'tipo = "alcance"\nruta_esperada = "B"\nterminos = []\n'
        'fuentes_esperadas = []\nprevia = "anterior"\n',
        encoding="utf-8",
    )

    # Act / Assert
    with pytest.raises(ValueError, match="previa"):
        cargar_preguntas_fase2(archivo)


def test_ids_repetidos_fallan(tmp_path: Path) -> None:
    """Dos preguntas no pueden compartir id."""
    # Arrange
    archivo = tmp_path / "preguntas.toml"
    fila = (
        '[[pregunta]]\nid = 1\npregunta = "x"\ncobertura = "si"\n'
        'tipo = "alcance"\nruta_esperada = "B"\nterminos = []\n'
        "fuentes_esperadas = []\n"
    )
    archivo.write_text(fila + fila, encoding="utf-8")

    # Act / Assert
    with pytest.raises(ValueError, match="repetidos"):
        cargar_preguntas_fase2(archivo)


def test_ruta_incompatible_con_el_tipo_falla(tmp_path: Path) -> None:
    """Una pregunta de tabla no puede apuntar a la Boveda."""
    # Arrange
    archivo = tmp_path / "preguntas.toml"
    archivo.write_text(
        '[[pregunta]]\nid = 1\npregunta = "tabla"\ncobertura = "si"\n'
        'tipo = "tabla"\nruta_esperada = "B"\nterminos = []\n'
        "fuentes_esperadas = []\n",
        encoding="utf-8",
    )

    # Act / Assert
    with pytest.raises(ValueError, match="ruta"):
        cargar_preguntas_fase2(archivo)


def test_etiqueta_de_pesos_sin_ceros_sobrantes() -> None:
    """Las etiquetas coinciden con las del reporte."""
    assert etiqueta_pesos(1.0, 0.0) == "1/0"
    assert etiqueta_pesos(0.2, 0.8) == "0.2/0.8"


def test_posicion_en_top_es_exacta_y_se_limita_a_k() -> None:
    """Solo cuenta una URL esperada dentro del top k."""
    assert posicion_en_top([URL_A, URL_B], [URL_B]) == 2
    assert posicion_en_top([URL_A], [URL_A + "/"]) is None
    assert posicion_en_top([URL_A], []) is None


def test_posicion_en_top_rechaza_k_no_positivo() -> None:
    """k debe ser positivo."""
    with pytest.raises(ValueError):
        posicion_en_top([URL_A], [URL_A], k=0)


def test_normalizar_url_ignora_mayusculas_y_barra_final() -> None:
    """La normalizacion es solo diagnostica."""
    assert normalizar_url("HTTPS://X/A/") == "https://x/a"
    assert normalizar_url("https://x/a") == normalizar_url("https://x/a/")


def test_barrido_mide_seis_configuraciones_sin_reindexar() -> None:
    """El barrido crea un recuperador por pesos pero no toca el almacen."""
    # Arrange
    almacen = AlmacenFijo(fragmentos_de_prueba())

    # Act
    barrido = barrer_pesos(
        almacen,
        DeterministicFakeEmbedding(size=8),
        fragmentos_de_prueba(),
        preguntas_de_prueba(),
        configuracion=ConfiguracionRecuperacion(k=5, peso_vectorial=0.6, peso_bm25=0.4),
    )

    # Assert
    assert len(barrido.configuraciones) == len(PESOS_BARRIDO)
    assert [c.etiqueta for c in barrido.configuraciones] == [
        etiqueta_pesos(vectorial, bm25) for vectorial, bm25 in PESOS_BARRIDO
    ]
    assert barrido.vectorial == "1/0"
    assert barrido.bm25 == "0/1"
    assert barrido.por_defecto == "0.6/0.4"
    assert almacen.agregados == 0
    assert almacen.reinicios == 0
    assert almacen.busquedas == 2 * len(PESOS_BARRIDO) * len(preguntas_de_prueba())


def test_barrido_reutiliza_las_metricas_puras() -> None:
    """hit@5 y MRR del barrido coinciden con llamar a metricas.py."""
    # Arrange
    barrido = barrido_de_prueba()
    configuracion = barrido.configuraciones[0]
    recuperadas = [list(detalle.urls[configuracion.etiqueta]) for detalle in barrido.preguntas]
    esperadas = [list(p.fuentes_esperadas) for p in preguntas_de_prueba()]

    # Act
    hit = hit_at_k(recuperadas, esperadas, k=5)
    reciproco = mrr(recuperadas, esperadas, k=5)

    # Assert
    assert configuracion.metricas.hit_at_5 == hit
    assert configuracion.metricas.mrr == reciproco
    assert configuracion.metricas.evaluables == 5
    assert configuracion.metricas.aciertos == 4
    assert configuracion.metricas.intervalo95 is not None


def test_hit_y_mrr_usan_la_busqueda_de_k_5_y_recall_la_de_k_10() -> None:
    """hit@5 y MRR se calculan con la ventana de 5, no con la de 10."""
    # Arrange
    esperada = fragmento("frag:a", "texto de la fuente esperada", URL_A)
    distractores = [
        fragmento(
            f"frag:d{posicion}",
            f"texto del distractor {posicion}",
            f"https://www.bancodeoccidente.com.co/d{posicion}",
        )
        for posicion in range(1, 11)
    ]
    almacen = AlmacenPorVentana(esperada, distractores)
    preguntas = [pregunta(1, fuentes=(URL_A,))]

    # Act
    resultado = medir_configuracion(
        almacen,
        DeterministicFakeEmbedding(size=8),
        [esperada, *distractores],
        preguntas,
        etiqueta="1/0",
        vectorial=1.0,
        bm25=0.0,
        prefijos=True,
        k=5,
    )

    # Assert
    assert almacen.ventanas == [5, K_RECALL]
    assert resultado.metricas.hit_at_5 == 1.0
    assert resultado.metricas.mrr == 1.0
    assert resultado.metricas.recall_at_10 == 0.0
    assert resultado.metricas.ndcg_at_10 == 0.0


def test_barrido_separa_boveda_tablero_y_no_indexadas() -> None:
    """Las preguntas T no cuentan en sin_tablero y la fuente ausente se avisa."""
    # Arrange
    barrido = barrido_de_prueba()

    # Act
    configuracion = barrido.configuraciones[0]
    por_tipo = configuracion.por_tipo

    # Assert
    assert ids_por_ruta(barrido, "B") == [1, 2, 5, 6]
    assert ids_por_ruta(barrido, "T") == [3]
    assert ids_por_ruta(barrido) == [1, 2, 3, 5, 6]
    assert configuracion.sin_tablero.evaluables == 4
    assert configuracion.sin_tablero.aciertos == 3
    assert por_tipo["alcance"].evaluables == 3
    assert por_tipo["tabla"].aciertos == 1
    assert por_tipo["fuera"].evaluables == 0
    assert barrido.no_indexadas == (6,)


def test_barrido_marca_diferencias_por_normalizacion_de_url() -> None:
    """Una URL que solo difiere en mayusculas y barra no acierta exactamente."""
    # Arrange
    fragmentos = [fragmento("frag:a", "cuota", "https://x/a")]
    preguntas = [pregunta(1, fuentes=("https://x/A/",))]

    # Act
    barrido = barrer_pesos(
        AlmacenFijo(fragmentos),
        DeterministicFakeEmbedding(size=8),
        fragmentos,
        preguntas,
        configuracion=ConfiguracionRecuperacion(k=5, peso_vectorial=1.0, peso_bm25=0.0),
    )

    # Assert
    assert barrido.configuraciones[0].metricas.hit_at_5 == 0.0
    assert barrido.configuraciones[0].diferencias_url == (1,)


def test_vectorial_directo_y_su_diferencia_con_el_ensemble() -> None:
    """La busqueda directa tambien devuelve las URL del almacen."""
    # Arrange
    almacen = AlmacenFijo(fragmentos_de_prueba())
    embeddings = DeterministicFakeEmbedding(size=8)
    preguntas = preguntas_de_prueba()

    # Act
    directo = vectorial_directo(almacen, embeddings, preguntas)
    barrido = barrer_pesos(
        almacen,
        embeddings,
        fragmentos_de_prueba(),
        preguntas,
        configuracion=ConfiguracionRecuperacion(k=5, peso_vectorial=1.0, peso_bm25=0.0),
    )

    # Assert
    assert directo[1] == (URL_A, URL_B, URL_C)
    assert diferencias_vectorial_directo(barrido, directo) == ()


def test_aciertos_por_revision_convierte_veredictos() -> None:
    """Correcta y rechazo correcto aciertan; parcial e incorrecta no."""
    # Arrange
    revision = {
        1: Revision(veredicto="correcta"),
        2: Revision(veredicto="rechazo_correcto"),
        3: Revision(veredicto="parcial"),
        4: Revision(veredicto="incorrecta"),
    }

    # Act
    aciertos = aciertos_por_revision(revision, [1, 2, 3, 4, 5])

    # Assert
    assert aciertos == [True, True, False, False, None]


def test_comparar_versiones_casos_b_c_empate_y_faltante() -> None:
    """McNemar distingue b, c, empate y revision faltante."""
    # Arrange
    v1 = {
        1: Revision(veredicto="correcta"),
        2: Revision(veredicto="parcial"),
        3: Revision(veredicto="correcta"),
        4: Revision(veredicto="correcta"),
    }
    v2 = {
        1: Revision(veredicto="parcial"),
        2: Revision(veredicto="correcta"),
        3: Revision(veredicto="correcta"),
    }

    # Act
    resultado = comparar_versiones(v1, v2, [1, 2, 3, 4])

    # Assert
    assert resultado.b == 1
    assert resultado.c == 1
    assert resultado.n == 2
    assert resultado.p == 1.0
    assert resultado.excluidos == 1


def test_comparar_pesos_usa_solo_preguntas_de_ruta_b() -> None:
    """La comparacion principal excluye las preguntas del Tablero."""
    # Arrange
    barrido = Barrido(
        configuraciones=(),
        preguntas=(
            detalle(1, "B", {"0.6/0.4": 1, "1/0": None}),
            detalle(2, "B", {"0.6/0.4": None, "1/0": 2}),
            detalle(3, "B", {"0.6/0.4": 1, "1/0": 2}),
            detalle(4, "T", {"0.6/0.4": None, "1/0": 1}),
        ),
        por_defecto="0.6/0.4",
        vectorial="1/0",
        bm25="0/1",
        no_indexadas=(),
    )

    # Act
    resultado = comparar_pesos(barrido)

    # Assert
    assert resultado.b == 1
    assert resultado.c == 1
    assert resultado.n == 2
    assert resultado.excluidos == 0


def detalle(
    identificador: int,
    ruta: str,
    posiciones: dict[str, int | None],
) -> DetallePregunta:
    """Construye un detalle por pregunta para las comparaciones."""
    return DetallePregunta(
        id=identificador,
        tipo="alcance" if ruta == "B" else "tabla",
        ruta_esperada=ruta,
        evaluable=True,
        fuente_indexada=True,
        posiciones=posiciones,
        urls=dict.fromkeys(posiciones, ()),
    )


def test_consulta_de_une_previa_solo_en_seguimiento() -> None:
    """Los seguimientos se buscan con la previa, como medir_recuperacion.py de la skill."""
    seguimiento = pregunta(5, fuentes=(URL_A,), tipo="seguimiento", previa="Que es la Black?")
    alcance = pregunta(6, fuentes=(URL_A,), tipo="alcance")

    assert consulta_de(seguimiento) == f"Que es la Black? {seguimiento.pregunta}"
    assert consulta_de(alcance) == alcance.pregunta
