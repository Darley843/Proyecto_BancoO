"""Pruebas sin red del índice de la Bóveda: configuración, almacén y construcción.

Ninguna prueba llama a Ollama ni a DeepSeek: los embeddings se inyectan con
`DeterministicFakeEmbedding` o con un espía, y Chroma se instancia en `tmp_path`.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest
from langchain_core.embeddings import DeterministicFakeEmbedding, Embeddings

from banco_occidente_corpus.boveda.__main__ import main
from banco_occidente_corpus.boveda.almacen import ChromaAlmacen, Coincidencia
from banco_occidente_corpus.boveda.configuracion import (
    PREFIJO_CONSULTA,
    PREFIJO_DOCUMENTO,
    ConfiguracionEmbeddings,
    cargar_configuracion_embeddings,
    normalizar_base_url,
)
from banco_occidente_corpus.boveda.embeddings import (
    EmbeddingsConPrefijos,
    crear_embeddings,
    opciones_ollama,
)
from banco_occidente_corpus.boveda.fragmentos import escribir_fragmentos, ruta_fragmentos
from banco_occidente_corpus.boveda.indice import (
    ResumenIndice,
    construir_indice,
    formatear_resumen_indice,
    ruta_almacen,
    ruta_metadatos,
)
from banco_occidente_corpus.config import Config, Paths
from banco_occidente_corpus.utils import sha256_text, write_jsonl

URL = "https://www.bancodeoccidente.com.co/productos"


def make_config(tmp_path: Path) -> Config:
    """Crea una configuración aislada en tmp_path, sin tocar el corpus real."""
    return Config(
        paths=Paths(
            root=tmp_path,
            raw=tmp_path / "data/raw",
            processed=tmp_path / "data/processed",
            gold=tmp_path / "data/gold",
            knowledge=tmp_path / "data/knowledge",
        )
    )


class EspiaEmbeddings(Embeddings):
    """Proveedor de pruebas que registra el texto exacto que recibe."""

    def __init__(self, dimension: int = 3) -> None:
        self.dimension = dimension
        self.documentos: list[str] = []
        self.consultas: list[str] = []

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        self.documentos.extend(texts)
        return [[1.0] * self.dimension for _ in texts]

    def embed_query(self, text: str) -> list[float]:
        self.consultas.append(text)
        return [1.0] * self.dimension


class AlmacenFalso:
    """Almacén en memoria que cumple el protocolo de la Bóveda."""

    def __init__(self) -> None:
        self.reinicios = 0
        self.ids: list[str] = []
        self.vectores: list[list[float]] = []
        self.documentos: list[str] = []
        self.metadatos: list[dict[str, Any]] = []

    def crear(self) -> None:
        """No hace nada: el almacén ya existe en memoria."""

    def agregar(
        self,
        ids: Sequence[str],
        vectores: Sequence[Sequence[float]],
        documentos: Sequence[str],
        metadatos: Sequence[dict[str, Any]],
    ) -> None:
        """Acumula el lote recibido."""
        self.ids.extend(ids)
        self.vectores.extend([list(vector) for vector in vectores])
        self.documentos.extend(documentos)
        self.metadatos.extend(metadatos)

    def buscar(self, vector: Sequence[float], k: int = 5) -> list[Coincidencia]:
        """No implementa búsqueda: el índice solo inserta."""
        return []

    def contar(self) -> int:
        """Devuelve cuántos vectores se insertaron."""
        return len(self.ids)

    def reiniciar(self) -> None:
        """Vacía el almacén y cuenta el reinicio."""
        self.reinicios += 1
        self.ids.clear()
        self.vectores.clear()
        self.documentos.clear()
        self.metadatos.clear()


def escribir_toml(tmp_path: Path, contenido: str) -> Path:
    """Escribe un `sucursal.toml` mínimo y devuelve su ruta."""
    ruta = tmp_path / "sucursal.toml"
    ruta.write_text(contenido, encoding="utf-8")
    return ruta


def fila_fragmento(
    identificador: str, texto: str = "Cuota de manejo de la tarjeta"
) -> dict[str, Any]:
    """Construye una fila con la forma del JSONL de fragmentos."""
    return {
        "id": identificador,
        "texto": texto,
        "url": URL,
        "titulo": "Productos",
        "seccion": "oferta",
        "encabezado": "Tarjetas",
        "tipo": "pagina",
        "tokens": 8,
        "puntaje": 0.0,
    }


def chunk(
    page_id: str,
    texto: str,
    *,
    url: str = URL,
    section: str = "oferta",
    heading: str = "Tarjetas",
) -> dict[str, Any]:
    """Construye una fila de chunk con la forma que produce knowledge.py."""
    digest = sha256_text(f"{page_id}|{heading}|{texto}")
    return {
        "chunk_id": f"chk:{digest[:12]}",
        "page_id": page_id,
        "url": url,
        "section": section,
        "heading": heading,
        "level": 1,
        "text": texto,
        "tokens": 40,
        "hash": digest,
    }


def test_base_url_sin_esquema_agrega_http() -> None:
    """Un host:puerto sin esquema se interpreta como HTTP."""
    assert normalizar_base_url("127.0.0.1:11434") == "http://127.0.0.1:11434"


def test_base_url_de_bind_se_traduce_al_host_local() -> None:
    """0.0.0.0 y :: son direcciones de bind, no de destino."""
    assert normalizar_base_url("0.0.0.0:11434") == "http://127.0.0.1:11434"
    assert normalizar_base_url("[::]:11434") == "http://127.0.0.1:11434"


def test_base_url_quita_barra_final() -> None:
    """La barra final se elimina para no duplicar rutas."""
    assert normalizar_base_url("http://127.0.0.1:11434/") == "http://127.0.0.1:11434"


@pytest.mark.parametrize("valor", ["", "   ", "ftp://127.0.0.1:11434", "unix:///tmp/ollama.sock"])
def test_base_url_invalida(valor: str) -> None:
    """Esquemas no HTTP(S), sockets y valores vacíos se rechazan."""
    with pytest.raises(ValueError):
        normalizar_base_url(valor)


def test_config_lee_modelo_url_y_prefijos(tmp_path: Path) -> None:
    """La configuración sale del TOML tal como se declara."""
    ruta = escribir_toml(
        tmp_path,
        '[embeddings]\nmodelo = "nomic-embed-text-v2-moe"\n'
        'base_url = "http://127.0.0.1:11434"\nprefijos = false\n',
    )

    ajustes = cargar_configuracion_embeddings(ruta)

    assert ajustes == ConfiguracionEmbeddings(
        modelo="nomic-embed-text-v2-moe",
        base_url="http://127.0.0.1:11434",
        prefijos=False,
    )


def test_config_usa_el_entorno_si_falta_base_url(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """OLLAMA_BASE_URL cubre la ausencia de base_url en el TOML."""
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://10.0.0.5:11434")
    monkeypatch.delenv("OLLAMA_HOST", raising=False)
    ruta = escribir_toml(tmp_path, '[embeddings]\nmodelo = "nomic-embed-text-v2-moe"\n')

    ajustes = cargar_configuracion_embeddings(ruta)

    assert ajustes.base_url == "http://10.0.0.5:11434"


def test_config_prefiere_ollama_base_url_sobre_host(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """OLLAMA_BASE_URL tiene prioridad sobre OLLAMA_HOST."""
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://10.0.0.5:11434")
    monkeypatch.setenv("OLLAMA_HOST", "0.0.0.0:11434")
    ruta = escribir_toml(tmp_path, "[embeddings]\n")

    assert cargar_configuracion_embeddings(ruta).base_url == "http://10.0.0.5:11434"


def test_config_usa_ollama_host_como_respaldo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """OLLAMA_HOST se acepta como último respaldo y se normaliza."""
    monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)
    monkeypatch.setenv("OLLAMA_HOST", "0.0.0.0:11434")
    ruta = escribir_toml(tmp_path, "[embeddings]\n")

    assert cargar_configuracion_embeddings(ruta).base_url == "http://127.0.0.1:11434"


def test_config_rechaza_prefijos_no_booleanos(tmp_path: Path) -> None:
    """Un string en `prefijos` es un error de configuración, no un valor falsy."""
    ruta = escribir_toml(tmp_path, '[embeddings]\nprefijos = "si"\n')

    with pytest.raises(ValueError, match="prefijos"):
        cargar_configuracion_embeddings(ruta)


def test_config_rechaza_modelo_vacio(tmp_path: Path) -> None:
    """El modelo no puede quedar vacío."""
    ruta = escribir_toml(tmp_path, '[embeddings]\nmodelo = "  "\n')

    with pytest.raises(ValueError, match="modelo"):
        cargar_configuracion_embeddings(ruta)


def test_config_rechaza_timeout_no_positivo(tmp_path: Path) -> None:
    """El timeout debe ser un número mayor que cero."""
    ruta = escribir_toml(tmp_path, "[embeddings]\ntimeout_segundos = 0\n")

    with pytest.raises(ValueError, match="timeout"):
        cargar_configuracion_embeddings(ruta)


def test_opciones_ollama_fijan_el_timeout() -> None:
    """Toda petición a Ollama lleva un timeout explícito."""
    opciones = opciones_ollama(ConfiguracionEmbeddings(timeout=12.5))

    assert opciones["client_kwargs"] == {"timeout": 12.5}
    assert opciones["model"] == "nomic-embed-text-v2-moe"


def test_prefijos_se_aplican_a_documentos_y_consultas() -> None:
    """Con prefijos activos, el proveedor recibe los textos de nomic."""
    espia = EspiaEmbeddings()
    embeddings = EmbeddingsConPrefijos(espia, prefijos=True)

    embeddings.embed_documents(["texto uno"])
    embeddings.embed_query("¿cuál es la cuota?")

    assert espia.documentos == [f"{PREFIJO_DOCUMENTO}texto uno"]
    assert espia.consultas == [f"{PREFIJO_CONSULTA}¿cuál es la cuota?"]


def test_prefijos_desactivados_no_alteran_el_texto() -> None:
    """La bandera de configuración desactiva los prefijos para el experimento."""
    espia = EspiaEmbeddings()
    embeddings = EmbeddingsConPrefijos(espia, prefijos=False)

    embeddings.embed_documents(["texto uno"])
    embeddings.embed_query("consulta")

    assert espia.documentos == ["texto uno"]
    assert espia.consultas == ["consulta"]


def test_crear_embeddings_acepta_proveedor_inyectado() -> None:
    """El proveedor inyectado se envuelve y conserva su dimensión."""
    base = DeterministicFakeEmbedding(size=4)

    embeddings = crear_embeddings(ConfiguracionEmbeddings(prefijos=True), base=base)
    vectores = embeddings.embed_documents(["uno", "dos"])

    assert len(vectores) == 2
    assert all(len(vector) == 4 for vector in vectores)


def test_chroma_crea_la_coleccion_con_metrica_coseno(tmp_path: Path) -> None:
    """La métrica declarada al crear la colección es coseno."""
    almacen = ChromaAlmacen(tmp_path / "chroma")
    almacen.crear()

    assert almacen.metrica == "cosine"
    assert almacen.metrica_almacenada() == "cosine"


def test_chroma_persiste_entre_instancias(tmp_path: Path) -> None:
    """Un segundo almacén sobre la misma ruta ve los vectores insertados."""
    ruta = tmp_path / "chroma"
    primero = ChromaAlmacen(ruta)
    primero.agregar(["a"], [[1.0, 0.0]], ["documento a"], [{"tipo": "pagina"}])

    segundo = ChromaAlmacen(ruta)

    assert segundo.contar() == 1


def test_chroma_reiniciar_deja_la_coleccion_vacia(tmp_path: Path) -> None:
    """Reiniciar borra los vectores anteriores y conserva la métrica."""
    almacen = ChromaAlmacen(tmp_path / "chroma")
    almacen.agregar(["a"], [[1.0, 0.0]], ["documento"], [{"tipo": "pagina"}])

    almacen.reiniciar()

    assert almacen.contar() == 0
    assert almacen.metrica_almacenada() == "cosine"


def test_chroma_buscar_devuelve_similitud_coseno(tmp_path: Path) -> None:
    """La coincidencia más cercana va primero y la similitud es 1 - distancia."""
    almacen = ChromaAlmacen(tmp_path / "chroma")
    almacen.agregar(
        ["cerca", "lejos"],
        [[1.0, 0.0], [0.0, 1.0]],
        ["cerca", "lejos"],
        [{"tipo": "pagina"}, {"tipo": "pagina"}],
    )

    resultados = almacen.buscar([1.0, 0.0], k=2)

    assert resultados[0].id == "cerca"
    assert resultados[0].similitud == pytest.approx(1.0 - resultados[0].distancia)
    assert resultados[0].similitud > resultados[1].similitud


def test_chroma_rechaza_k_no_positivo(tmp_path: Path) -> None:
    """k debe ser mayor que cero."""
    almacen = ChromaAlmacen(tmp_path / "chroma")

    with pytest.raises(ValueError, match="k"):
        almacen.buscar([1.0, 0.0], k=0)


def test_indice_escribe_metadatos_y_reinicia(tmp_path: Path) -> None:
    """El índice reinicia el almacén y declara modelo, alcance y dimensión."""
    config = make_config(tmp_path)
    write_jsonl(
        ruta_fragmentos(config, "base"),
        [fila_fragmento("frag:a"), fila_fragmento("frag:b", "Apertura de cuenta")],
    )
    almacen = AlmacenFalso()
    embeddings = DeterministicFakeEmbedding(size=6)

    resumen = construir_indice(
        config,
        "base",
        configuracion=ConfiguracionEmbeddings(prefijos=True),
        embeddings=embeddings,
        almacen=almacen,
    )

    metadatos = json.loads(ruta_metadatos(config).read_text(encoding="utf-8"))
    assert metadatos == {
        "modelo": "nomic-embed-text-v2-moe",
        "prefijos": True,
        "alcance": "base",
        "fragmentos": 2,
        "dimension": 6,
    }
    assert almacen.reinicios == 1
    assert almacen.ids == ["frag:a", "frag:b"]
    assert resumen.fragmentos == 2
    assert resumen.dimension == 6
    assert resumen.ruta_almacen == ruta_almacen(config)


def test_indice_falla_si_faltan_los_fragmentos(tmp_path: Path) -> None:
    """Sin JSONL de fragmentos el error dice qué comando ejecutar."""
    config = make_config(tmp_path)

    with pytest.raises(FileNotFoundError, match="make fragmentos"):
        construir_indice(config, "base", embeddings=DeterministicFakeEmbedding(size=4))


def test_indice_base_excluye_pdf_financiero(tmp_path: Path) -> None:
    """El alcance base solo incluye PDF de producto, no estados financieros."""
    config = make_config(tmp_path)
    escribir_corpus_minimo(config)
    escribir_fragmentos(config, "base")
    almacen = AlmacenFalso()

    construir_indice(
        config,
        "base",
        configuracion=ConfiguracionEmbeddings(prefijos=False),
        embeddings=DeterministicFakeEmbedding(size=4),
        almacen=almacen,
    )

    assert any(metadatos["tipo"] == "pdf" for metadatos in almacen.metadatos)
    urls = {metadatos["url"] for metadatos in almacen.metadatos}
    assert "https://www.bancodeoccidente.com.co/balance" not in urls
    assert "https://www.bancodeoccidente.com.co/tarifas" in urls


def test_indice_completo_incluye_pdf_financiero(tmp_path: Path) -> None:
    """El alcance completo agrega el resto de PDF y los videos."""
    config = make_config(tmp_path)
    escribir_corpus_minimo(config)
    escribir_fragmentos(config, "completo")
    almacen = AlmacenFalso()

    construir_indice(
        config,
        "completo",
        configuracion=ConfiguracionEmbeddings(prefijos=False),
        embeddings=DeterministicFakeEmbedding(size=4),
        almacen=almacen,
    )

    tipos = {metadatos["tipo"] for metadatos in almacen.metadatos}
    urls = {metadatos["url"] for metadatos in almacen.metadatos}
    assert tipos == {"pagina", "pdf"}
    assert "https://www.bancodeoccidente.com.co/balance" in urls


def test_resumen_indice_menciona_rutas_y_conteo(tmp_path: Path) -> None:
    """El texto de salida incluye alcance, modelo, dimensión y rutas."""
    resumen = ResumenIndice(
        alcance="base",
        modelo="nomic-embed-text-v2-moe",
        prefijos=True,
        fragmentos=965,
        dimension=768,
        ruta_metadatos=tmp_path / "indice.json",
        ruta_almacen=tmp_path / "chroma",
    )

    texto = formatear_resumen_indice(resumen)

    assert "base" in texto
    assert "965" in texto
    assert "768" in texto
    assert str(tmp_path / "chroma") in texto


def test_cli_indice_imprime_el_resumen(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """El subcomando `indice` delega y muestra el resumen."""
    resumen = ResumenIndice(
        alcance="base",
        modelo="nomic-embed-text-v2-moe",
        prefijos=True,
        fragmentos=3,
        dimension=8,
        ruta_metadatos=tmp_path / "indice.json",
        ruta_almacen=tmp_path / "chroma",
    )
    monkeypatch.setattr(
        "banco_occidente_corpus.boveda.__main__.construir_indice",
        lambda config, alcance: resumen,
    )

    codigo = main(["indice", "--alcance", "base"])

    assert codigo == 0
    assert "Fragmentos indexados: 3" in capsys.readouterr().out


def test_cli_indice_reporta_error(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Un error de construcción devuelve 1 y explica el motivo por stderr."""

    def fallar(config: Config, alcance: str) -> ResumenIndice:
        raise FileNotFoundError("No hay fragmentos: ejecuta `make fragmentos`.")

    monkeypatch.setattr("banco_occidente_corpus.boveda.__main__.construir_indice", fallar)

    codigo = main(["indice"])

    assert codigo == 1
    assert "make fragmentos" in capsys.readouterr().err


def escribir_corpus_minimo(config: Config) -> None:
    """Crea chunks y el índice de documentos para probar los dos alcances."""
    write_jsonl(
        config.paths.knowledge_chunks_web,
        [chunk("pagina-productos", "Tarjeta de crédito con cuota de manejo de $16.700.")],
    )
    write_jsonl(
        config.paths.knowledge_chunks,
        [
            chunk(
                "pdf-tarifario",
                "Tarifario de productos y cuotas vigentes para tarjetas.",
                url="https://www.bancodeoccidente.com.co/tarifas",
            ),
            chunk(
                "pdf-balance",
                "Estado financiero consolidado con activos y pasivos del banco.",
                url="https://www.bancodeoccidente.com.co/balance",
                section="datos",
            ),
        ],
    )
    write_jsonl(
        config.paths.corpus_file,
        [{"id": "pagina-productos", "titulo": "Productos", "url": URL}],
    )
    write_jsonl(
        config.paths.documents_index,
        [
            {
                "id": "pdf-tarifario",
                "titulo": "Tarifario",
                "url": "https://www.bancodeoccidente.com.co/tarifas",
                "categoria_documento": "producto",
            },
            {
                "id": "pdf-balance",
                "titulo": "Balance",
                "url": "https://www.bancodeoccidente.com.co/balance",
                "categoria_documento": "financiero",
            },
        ],
    )
