"""Pruebas sin red del almacén Qdrant y de la paridad del filtro con Chroma."""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from banco_occidente_corpus.boveda.almacen import (
    AlmacenBloqueado,
    QdrantAlmacen,
    crear_almacen_en_ruta,
    id_punto,
)


def metadatos(seccion: str = "oferta") -> dict[str, object]:
    """Metadatos mínimos de un fragmento para las pruebas del almacén."""
    return {
        "url": "https://www.bancodeoccidente.com.co/productos",
        "titulo": "Productos",
        "seccion": seccion,
        "encabezado": "Tarjetas",
        "tipo": "pagina",
        "tokens": 8,
    }


def test_qdrant_crea_coleccion_con_coseno() -> None:
    """La colección nace con métrica coseno y dimensión 768 por defecto."""
    almacen = QdrantAlmacen()
    try:
        almacen.crear()

        assert almacen.tipo == "qdrant"
        assert almacen.coleccion == "boveda"
        assert almacen.existe()
        assert almacen.metrica_almacenada() == "cosine"
        assert almacen.dimension_almacenada() == 768
        assert almacen.contar() == 0
    finally:
        almacen.cerrar()


def test_qdrant_agrega_y_cuenta_sin_duplicar() -> None:
    """El upsert no duplica un id y actualiza su vector."""
    almacen = QdrantAlmacen()
    try:
        almacen.agregar(
            ["frag:a", "frag:b", "frag:c"],
            [[1.0, 0.0], [0.0, 1.0], [1.0, 1.0]],
            ["a", "b", "c"],
            [metadatos(), metadatos(), metadatos()],
        )

        assert almacen.contar() == 3
        almacen.agregar(["frag:a"], [[0.5, 0.5]], ["a"], [metadatos()])
        assert almacen.contar() == 3
        assert almacen.vectores(["frag:a"])["frag:a"] == pytest.approx([0.70710678, 0.70710678])
    finally:
        almacen.cerrar()


def test_qdrant_buscar_ordena_por_similitud() -> None:
    """El más cercano va primero y la similitud es 1 menos la distancia."""
    almacen = QdrantAlmacen()
    try:
        almacen.agregar(
            ["cerca", "lejos"],
            [[1.0, 0.0], [0.0, 1.0]],
            ["cerca", "lejos"],
            [metadatos(), metadatos()],
        )

        resultados = almacen.buscar([1.0, 0.01], k=2)

        assert [resultado.id for resultado in resultados] == ["cerca", "lejos"]
        assert resultados[0].similitud == pytest.approx(1.0 - resultados[0].distancia)
        assert resultados[0].similitud > resultados[1].similitud
        assert resultados[0].documento == "cerca"
    finally:
        almacen.cerrar()


def test_qdrant_buscar_filtra_por_payload() -> None:
    """El filtro por sección no devuelve fragmentos de otras secciones."""
    almacen = QdrantAlmacen()
    try:
        almacen.agregar(
            ["identidad", "tarifas"],
            [[1.0, 0.0], [0.9, 0.1]],
            ["quiénes somos", "cuota de manejo"],
            [metadatos("identidad"), metadatos("tarifas")],
        )

        resultados = almacen.buscar([1.0, 0.0], k=5, filtro={"seccion": "identidad"})

        assert [resultado.id for resultado in resultados] == ["identidad"]
        assert resultados[0].metadatos["seccion"] == "identidad"
        assert resultados[0].metadatos["url"].endswith("/productos")
        assert "texto" not in resultados[0].metadatos
    finally:
        almacen.cerrar()


def test_qdrant_filtro_vacio_no_filtra() -> None:
    """Un filtro vacío se comporta como no pasar filtro."""
    almacen = QdrantAlmacen()
    try:
        almacen.agregar(
            ["a", "b"],
            [[1.0, 0.0], [0.0, 1.0]],
            ["a", "b"],
            [metadatos("identidad"), metadatos("tarifas")],
        )

        sin_filtro = almacen.buscar([1.0, 0.0], k=2)
        vacio = almacen.buscar([1.0, 0.0], k=2, filtro={})

        assert [r.id for r in sin_filtro] == [r.id for r in vacio]
    finally:
        almacen.cerrar()


def test_qdrant_vectores_por_id_original() -> None:
    """Los vectores se leen con el id de negocio, no con el UUID interno."""
    almacen = QdrantAlmacen()
    try:
        almacen.agregar(
            ["frag:a", "frag:b"],
            [[1.0, 0.0], [0.0, 1.0]],
            ["a", "b"],
            [metadatos(), metadatos()],
        )

        guardados = almacen.vectores(["frag:b", "falta", "frag:a"])

        assert set(guardados) == {"frag:a", "frag:b"}
        assert guardados["frag:b"] == pytest.approx([0.0, 1.0])
    finally:
        almacen.cerrar()


def test_id_punto_es_uuid_determinista() -> None:
    """El mismo id produce siempre el mismo UUID y el payload conserva el original."""
    primero = id_punto("frag:a")
    segundo = id_punto("frag:a")

    assert primero == segundo
    assert uuid.UUID(primero).version == 5
    assert primero != id_punto("frag:b")


def test_qdrant_reiniciar_vacia_y_conserva_dimension() -> None:
    """Reiniciar deja la colección vacía y lista para otra inserción."""
    almacen = QdrantAlmacen()
    try:
        almacen.agregar(["a"], [[1.0, 0.0, 0.0, 0.0]], ["a"], [metadatos()])

        almacen.reiniciar()

        assert almacen.contar() == 0
        assert almacen.dimension_almacenada() == 4
        assert almacen.metrica_almacenada() == "cosine"
        almacen.agregar(["b"], [[0.0, 1.0, 0.0, 0.0]], ["b"], [metadatos()])
        assert almacen.contar() == 1
    finally:
        almacen.cerrar()


def test_qdrant_persiste_entre_instancias(tmp_path: Path) -> None:
    """Cerrar y volver a abrir la carpeta conserva los vectores."""
    ruta = tmp_path / "qdrant"
    primero = QdrantAlmacen(ruta)
    try:
        primero.agregar(["a"], [[1.0, 0.0]], ["a"], [metadatos()])
    finally:
        primero.cerrar()

    segundo = QdrantAlmacen(ruta)
    try:
        assert segundo.contar() == 1
        assert segundo.vectores(["a"])["a"] == pytest.approx([1.0, 0.0])
    finally:
        segundo.cerrar()


def test_qdrant_traduce_el_bloqueo_de_la_carpeta(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """El error real de Qdrant se convierte en un mensaje accionable."""

    def explota(*_args: object, **_kwargs: object) -> None:
        """Imita el RuntimeError de QdrantLocal cuando la carpeta está abierta."""
        raise RuntimeError(
            "Storage folder C:/tmp/qdrant is already accessed by another instance "
            "of Qdrant client. If you require concurrent access, use Qdrant server instead."
        )

    monkeypatch.setattr("qdrant_client.QdrantClient", explota)
    almacen = QdrantAlmacen(tmp_path / "qdrant")

    with pytest.raises(AlmacenBloqueado, match="[Cc]ierra la app"):
        almacen.crear()


def test_qdrant_doble_apertura_real(tmp_path: Path) -> None:
    """Dos clientes sobre la misma carpeta no pueden convivir."""
    ruta = tmp_path / "qdrant"
    primera = QdrantAlmacen(ruta)
    segunda = QdrantAlmacen(ruta)
    try:
        primera.crear()
        with pytest.raises(AlmacenBloqueado, match="[Cc]ierra la app"):
            segunda.crear()
    finally:
        segunda.cerrar()
        primera.cerrar()


def test_qdrant_rechaza_dimension_incoherente() -> None:
    """No se pueden mezclar dimensiones en la misma colección."""
    almacen = QdrantAlmacen()
    try:
        almacen.agregar(["a"], [[1.0, 0.0]], ["a"], [metadatos()])

        with pytest.raises(ValueError, match="dimensión"):
            almacen.agregar(["b"], [[1.0, 0.0, 0.0]], ["b"], [metadatos()])
    finally:
        almacen.cerrar()


def test_qdrant_rechaza_k_no_positivo() -> None:
    """k debe ser mayor que cero."""
    almacen = QdrantAlmacen()

    with pytest.raises(ValueError, match="k"):
        almacen.buscar([1.0, 0.0], k=0)


@pytest.mark.parametrize("tipo", ["qdrant", "chroma"])
def test_filtro_por_seccion_en_ambos_motores(tipo: str, tmp_path: Path) -> None:
    """El mismo filtro devuelve el mismo subconjunto en Qdrant y en Chroma."""
    almacen = crear_almacen_en_ruta(tmp_path / tipo, tipo)  # type: ignore[arg-type]
    try:
        almacen.agregar(
            ["identidad", "tarifas"],
            [[1.0, 0.0], [0.9, 0.1]],
            ["quiénes somos", "cuota de manejo"],
            [metadatos("identidad"), metadatos("tarifas")],
        )

        resultados = almacen.buscar([1.0, 0.0], k=5, filtro={"seccion": "identidad"})

        assert [resultado.id for resultado in resultados] == ["identidad"]
    finally:
        almacen.cerrar()
