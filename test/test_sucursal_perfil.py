"""Pruebas sin red de la memoria de perfil de la Sucursal.

Cubren las reglas de deteccion, el aislamiento por `perfil_id`, la ruta
`perfil`, la exclusion de la cache, los mensajes mixtos y las garantias de
privacidad. El store siempre es un `InMemoryStore` o un doble; nunca se abre
`data/asistente/perfil.sqlite` ni se llama a un modelo real.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

import pytest
from langgraph.store.memory import InMemoryStore
from langgraph.store.sqlite import SqliteStore
from test_sucursal_preguntar import (
    PREGUNTA_BOVEDA,
    RESPUESTA_BOVEDA,
    ModeloGuion,
    contar_cache,
    fragmento,
    make_config,
    preparar,
)

from banco_occidente_corpus.arqueo.experimentos import cargar_preguntas_fase2
from banco_occidente_corpus.sucursal.ajustes import ConfiguracionSucursal
from banco_occidente_corpus.sucursal.costo import CacheRespuestas, GastoDiario
from banco_occidente_corpus.sucursal.digiturno import ContadorTurnos, clasificar
from banco_occidente_corpus.sucursal.grafo import (
    DependenciasGrafo,
    crear_grafo,
    responder_turno,
)
from banco_occidente_corpus.sucursal.perfil import (
    MENSAJE_PERFIL_INACTIVO,
    AlmacenPerfil,
    detectar_intencion,
    huella_perfil,
    normalizar_perfil_id,
)
from banco_occidente_corpus.sucursal.preguntar import (
    PiezasGrafo,
    ServicioPreguntas,
    construir_piezas,
)


def preguntar_con_perfil(
    cliente: Any,
    pregunta: str,
    hilo: str,
    perfil_id: str = "",
) -> Any:
    """Envía una pregunta a la API con el `perfil_id` indicado."""
    cuerpo: dict[str, str] = {"pregunta": pregunta, "thread_id": hilo}
    if perfil_id:
        cuerpo["perfil_id"] = perfil_id
    return cliente.post("/api/preguntar", json=cuerpo)


class StoreEspia(InMemoryStore):
    """Store en memoria que registra las llamadas a `put` y `search`."""

    def __init__(self) -> None:
        """Inicializa el store y las listas de llamadas."""
        super().__init__()
        self.puts: list[tuple[tuple[str, ...], str, dict[str, Any]]] = []
        self.busquedas: list[tuple[str, ...]] = []

    def put(
        self,
        namespace: tuple[str, ...],
        key: str,
        value: dict[str, Any],
        index: Any = None,
        *,
        ttl: Any = None,
    ) -> None:
        """Registra y delega el guardado en el store en memoria."""
        self.puts.append((tuple(namespace), key, dict(value)))
        super().put(namespace, key, value, index, ttl=ttl)

    def search(self, namespace_prefix: tuple[str, ...], **kwargs: Any) -> list[Any]:
        """Registra y delega la búsqueda en el store en memoria."""
        self.busquedas.append(tuple(namespace_prefix))
        return super().search(namespace_prefix, **kwargs)


class CacheRegistro:
    """Caché que apunta sus accesos sin fallar, para comprobar ausencias."""

    def __init__(self) -> None:
        """Arranca sin accesos."""
        self.llamadas: list[str] = []

    def obtener(self, clave: str) -> dict[str, Any] | None:
        """Registra la consulta y devuelve un fallo."""
        self.llamadas.append(f"obtener:{clave}")
        return None

    def guardar(self, clave: str, respuesta: Any) -> None:
        """Registra el guardado."""
        self.llamadas.append(f"guardar:{clave}")


def dependencias_sin_modelo(fragmentos: list[Any] | None = None) -> DependenciasGrafo:
    """Arma dependencias mínimas para probar el grafo sin red."""
    return DependenciasGrafo(
        recuperador=_RecuperadorFalso(fragmentos or []),
        filas=(),
        modelo=None,
        contador=ContadorTurnos(),
    )


class _RecuperadorFalso:
    """Recuperador que devuelve una lista fija y registra la consulta."""

    def __init__(self, fragmentos: list[Any]) -> None:
        """Guarda los fragmentos que se devolverán."""
        self._fragmentos = list(fragmentos)
        self.consultas: list[str] = []

    def buscar(self, consulta: str, k: int = 5) -> list[Any]:
        """Devuelve hasta `k` fragmentos y anota la consulta."""
        self.consultas.append(consulta)
        return self._fragmentos[:k]


def servicio_con_cache(
    tmp_path: Path,
    cache: Any,
    *,
    modelo: ModeloGuion | None = None,
    fragmentos: list[Any] | None = None,
    store: Any = None,
) -> tuple[ServicioPreguntas, DependenciasGrafo]:
    """Crea un servicio con un store y una caché inyectados."""
    config = make_config(tmp_path)
    indice = tmp_path / "data/boveda/indice.json"
    indice.parent.mkdir(parents=True, exist_ok=True)
    indice.write_text(
        '{"modelo": "nomic", "prefijos": true, "alcance": "base", '
        '"fragmentos": 10, "dimension": 768}',
        encoding="utf-8",
    )
    dependencias = DependenciasGrafo(
        recuperador=_RecuperadorFalso(fragmentos or []),
        filas=(),
        modelo=modelo,
        contador=ContadorTurnos(),
    )
    grafo = crear_grafo(
        dependencias,
        tmp_path / "data/asistente/memoria.sqlite",
        store=store or InMemoryStore(),
    )
    ajustes = ConfiguracionSucursal(tope_diario_usd=0.2, cache_ttl_segundos=60, demo=False)
    servicio = ServicioPreguntas(
        config,
        ajustes,
        GastoDiario(tmp_path / "data/asistente/gasto.sqlite"),
        cache=cache,
        piezas=lambda: PiezasGrafo(dependencias, grafo),
    )
    return servicio, dependencias


def test_soy_x_solo_captura_nombres_propios() -> None:
    """«soy X» no confunde roles, lugares ni ocupaciones con un nombre."""
    assert detectar_intencion("soy cliente") is None
    assert detectar_intencion("soy de Cali") is None
    assert detectar_intencion("soy estudiante") is None
    assert detectar_intencion("soy ana") is None
    assert detectar_intencion("Soy Cliente") is None
    assert detectar_intencion("Soy De Cali") is None
    assert detectar_intencion("Soy Estudiante") is None
    assert detectar_intencion("Soy Ingeniera") is None
    assert detectar_intencion("Soy Médico") is None
    assert detectar_intencion("Soy Abogada") is None
    assert detectar_intencion("soy cliente de Banco de Occidente") is None
    assert detectar_intencion("¿trabajo en el banco?") is None
    assert detectar_intencion("¿Y trabajo en el banco?") is None

    intencion = detectar_intencion("soy Ana")
    assert intencion is not None
    assert [(dato.campo, dato.valor) for dato in intencion.guardar] == [("nombre", "Ana")]

    explicita = detectar_intencion("me llamo ana")
    assert explicita is not None
    assert explicita.guardar[0].valor == "ana"

    empresa = detectar_intencion("trabajo en Carvajal")
    assert empresa is not None
    assert empresa.guardar[0].campo == "empresa"
    assert empresa.guardar[0].valor == "Carvajal"


def test_digiturno_conserva_las_letras_b_t_x_para_el_perfil() -> None:
    """El perfil puro usa B/perfil y el mixto conserva la letra del residual."""
    puro = clasificar("me llamo Ana")
    mixto = clasificar("me llamo Ana, ¿qué es un CDT?")
    falso = clasificar("soy cliente")

    assert (puro.letra, puro.motivo) == ("B", "perfil")
    assert (mixto.letra, mixto.motivo) == ("B", "perfil:defecto")
    assert mixto.motivo_residual == "defecto"
    assert falso.motivo != "perfil"


def test_perfil_id_invalido_queda_inactivo() -> None:
    """Un identificador vacío, con controles o demasiado largo no se usa."""
    assert normalizar_perfil_id("  ") == ""
    assert normalizar_perfil_id("ana\x00") == ""
    assert normalizar_perfil_id("x" * 129) == ""
    assert normalizar_perfil_id("  ana  ") == "ana"


def test_almacen_perfil_usa_put_y_search_del_base_store() -> None:
    """La envoltura guarda con put y consulta con search en su namespace."""
    store = StoreEspia()
    almacen = AlmacenPerfil(store)
    perfil = huella_perfil("ana")

    datos = almacen.guardar(perfil, {"nombre": "Ana", "empresa": "Carvajal"})

    assert datos["nombre"] == "Ana"
    assert store.puts[0][0] == ("perfil", perfil)
    assert store.puts[0][1] == "datos"
    assert store.busquedas and store.busquedas[-1] == ("perfil", perfil)
    assert almacen.leer(perfil)["empresa"] == "Carvajal"

    almacen.borrar(perfil)
    assert almacen.leer(perfil) == {}


def test_sqlite_store_persiste_entre_conexiones(tmp_path: Path) -> None:
    """El perfil sobrevive al cierre de la conexión y a un SqliteStore nuevo."""
    ruta = tmp_path / "perfil.sqlite"
    perfil = huella_perfil("ana")

    primera = sqlite3.connect(str(ruta), check_same_thread=False, isolation_level=None)
    try:
        AlmacenPerfil(SqliteStore(primera)).guardar(
            perfil,
            {"nombre": "Ana", "empresa": "Carvajal"},
        )
    finally:
        primera.close()

    segunda = sqlite3.connect(str(ruta), check_same_thread=False, isolation_level=None)
    try:
        store = SqliteStore(segunda)
        encontrados = store.search(("perfil", perfil), limit=1)
        assert encontrados
        assert encontrados[0].value == {
            "nombre": "Ana",
            "empresa": "Carvajal",
        }
        assert "actualizado" not in encontrados[0].value
        assert AlmacenPerfil(store).leer(perfil)["nombre"] == "Ana"
    finally:
        segunda.close()


def test_el_grafo_recibe_el_store_y_guarda_el_perfil(tmp_path: Path) -> None:
    """`crear_grafo(store=...)` inyecta el store y el nodo guarda con put."""
    store = StoreEspia()
    dependencias = dependencias_sin_modelo()
    grafo = crear_grafo(
        dependencias,
        tmp_path / "data/asistente/memoria.sqlite",
        store=store,
    )

    estado = responder_turno(
        grafo,
        dependencias,
        "trabajo en Carvajal",
        "hilo-store",
        huella_perfil("ana"),
    )

    assert estado["turno"]["motivo"] == "perfil"
    assert store.puts
    assert store.puts[0][0] == ("perfil", huella_perfil("ana"))
    assert store.puts[0][2]["empresa"] == "Carvajal"


def test_dos_perfiles_no_comparten_respuesta_de_donde_trabajo(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Ana y Beto preguntan lo mismo y cada uno recibe su empresa."""
    escenario = preparar(monkeypatch, tmp_path)

    preguntar_con_perfil(escenario.cliente, "trabajo en Carvajal", "hilo-ana", "ana")
    preguntar_con_perfil(escenario.cliente, "trabajo en Sura", "hilo-beto", "beto")

    ana = preguntar_con_perfil(escenario.cliente, "¿Dónde trabajo?", "hilo-ana-2", "ana").json()
    beto = preguntar_con_perfil(escenario.cliente, "¿Dónde trabajo?", "hilo-beto-2", "beto").json()

    assert ana["ruta"] == "perfil"
    assert beto["ruta"] == "perfil"
    assert "Carvajal" in ana["respuesta"]
    assert "Sura" in beto["respuesta"]
    assert "Sura" not in ana["respuesta"]
    assert "Carvajal" not in beto["respuesta"]
    assert ana["tokens_entrada"] == 0
    assert ana["tokens_salida"] == 0
    assert ana["cache"] is False
    assert contar_cache(escenario) == 0


def test_demo_completa_mantiene_el_perfil_entre_hilos(tmp_path: Path) -> None:
    """Con el servicio completo en demo, otro hilo del mismo perfil ve Carvajal."""
    config = make_config(tmp_path)
    indice = tmp_path / "data/boveda/indice.json"
    indice.parent.mkdir(parents=True, exist_ok=True)
    indice.write_text(
        '{"modelo": "nomic", "prefijos": true, "alcance": "base", '
        '"fragmentos": 10, "dimension": 768}',
        encoding="utf-8",
    )
    ajustes = ConfiguracionSucursal(tope_diario_usd=0.2, cache_ttl_segundos=60, demo=True)
    piezas = construir_piezas(
        config,
        ajustes,
        crear_recuperador_boveda=lambda: _RecuperadorFalso([]),
        ruta_memoria=tmp_path / "data/asistente/memoria.sqlite",
        ruta_perfil=tmp_path / "data/asistente/perfil.sqlite",
    )
    servicio = ServicioPreguntas(
        config,
        ajustes,
        GastoDiario(tmp_path / "data/asistente/gasto.sqlite"),
        piezas=lambda: piezas,
    )

    guardado = servicio.preguntar(
        "me llamo Ana y trabajo en Carvajal",
        "hilo-ana",
        "ana-demo",
    )
    consulta = servicio.preguntar(
        "¿Dónde trabajo?",
        "hilo-otro",
        "ana-demo",
    )

    assert "Ana" in guardado["respuesta"]
    assert "Carvajal" in guardado["respuesta"]
    assert consulta["ruta"] == "perfil"
    assert "Carvajal" in consulta["respuesta"]
    assert consulta["tokens_entrada"] == 0
    assert consulta["tokens_salida"] == 0
    assert consulta["uso_modelo"] is False
    assert consulta["cache"] is False


def test_historial_no_guarda_perfil_y_el_modelo_nunca_lo_recibe(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Ni la memoria del hilo ni las llamadas al modelo reciben Ana o Carvajal."""
    modelo = ModeloGuion(
        [
            RESPUESTA_BOVEDA,
            "¿Cuánto cuesta la cuota de manejo?",
            RESPUESTA_BOVEDA,
        ]
    )
    escenario = preparar(monkeypatch, tmp_path, modelo=modelo, fragmentos=[fragmento()])

    guardado = preguntar_con_perfil(
        escenario.cliente,
        "me llamo Ana y trabajo en Carvajal",
        "hilo-privado",
        "ana",
    ).json()
    assert "Ana" in guardado["respuesta"]
    assert "Carvajal" in guardado["respuesta"]

    preguntar_con_perfil(escenario.cliente, PREGUNTA_BOVEDA, "hilo-privado", "ana")
    seguimiento = preguntar_con_perfil(
        escenario.cliente,
        "¿Y cuánto cuesta?",
        "hilo-privado",
        "ana",
    )

    assert seguimiento.status_code == 200
    contenidos = [
        " ".join(str(mensaje.content) for mensaje in llamada) for llamada in modelo.llamadas
    ]
    assert contenidos
    assert all("Ana" not in texto and "Carvajal" not in texto for texto in contenidos)

    estado = escenario.grafo.get_state({"configurable": {"thread_id": "hilo-privado"}}).values
    historial = " ".join(str(mensaje.content) for mensaje in estado["messages"])
    assert "Ana" not in historial
    assert "Carvajal" not in historial


def test_perfil_no_consulta_ni_escribe_la_cache(tmp_path: Path) -> None:
    """Los turnos que guardan o consultan el perfil no tocan la caché."""
    cache = CacheRegistro()
    servicio, _ = servicio_con_cache(tmp_path, cache)

    guardado = servicio.preguntar("trabajo en Carvajal", "hilo-1", "ana")
    consulta = servicio.preguntar("¿Dónde trabajo?", "hilo-2", "ana")

    assert guardado["ruta"] == "perfil"
    assert consulta["ruta"] == "perfil"
    assert "Carvajal" in consulta["respuesta"]
    assert cache.llamadas == []


def test_turno_mixto_no_lee_ni_escribe_la_cache(tmp_path: Path) -> None:
    """El turno mixto que guarda perfil no consulta la caché antes del grafo."""
    cache = CacheRegistro()
    servicio, _ = servicio_con_cache(
        tmp_path,
        cache,
        modelo=ModeloGuion([RESPUESTA_BOVEDA]),
        fragmentos=[fragmento()],
    )

    respuesta = servicio.preguntar("me llamo Ana, ¿qué es un CDT?", "hilo-mixto", "ana")

    assert respuesta["ruta"] == "boveda"
    assert respuesta["motivo"].startswith("perfil")
    assert cache.llamadas == []


def test_turno_mixto_guarda_y_responde_pregunta_sin_cache(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """«me llamo Ana, trabajo en Carvajal, ¿qué es un CDT?» guarda y responde."""
    modelo = ModeloGuion([RESPUESTA_BOVEDA])
    escenario = preparar(
        monkeypatch,
        tmp_path,
        modelo=modelo,
        fragmentos=[fragmento()],
    )

    respuesta = preguntar_con_perfil(
        escenario.cliente,
        "me llamo Ana, trabajo en Carvajal, ¿qué es un CDT?",
        "hilo-mixto",
        "ana",
    )
    cuerpo = respuesta.json()

    assert respuesta.status_code == 200
    assert cuerpo["ruta"] == "boveda"
    assert cuerpo["motivo"].startswith("perfil")
    assert cuerpo["respuesta"].startswith("Listo, Ana.")
    assert "1965" in cuerpo["respuesta"]
    assert cuerpo["cache"] is False
    assert contar_cache(escenario) == 0

    llamadas = [
        " ".join(str(mensaje.content) for mensaje in llamada) for llamada in modelo.llamadas
    ]
    assert llamadas
    assert all("Ana" not in texto and "Carvajal" not in texto for texto in llamadas)
    assert any("¿qué es un CDT?" in texto for texto in llamadas)

    consulta = preguntar_con_perfil(
        escenario.cliente,
        "¿Dónde trabajo?",
        "hilo-mixto-2",
        "ana",
    ).json()
    assert "Carvajal" in consulta["respuesta"]


def test_consulta_de_perfil_con_pregunta_residual_no_cachea(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """«¿Dónde trabajo y qué es un CDT?» responde con el perfil sin cachear."""
    modelo = ModeloGuion([RESPUESTA_BOVEDA])
    escenario = preparar(monkeypatch, tmp_path, modelo=modelo, fragmentos=[fragmento()])
    preguntar_con_perfil(escenario.cliente, "trabajo en Carvajal", "hilo-consulta", "ana")

    respuesta = preguntar_con_perfil(
        escenario.cliente,
        "¿Dónde trabajo y qué es un CDT?",
        "hilo-consulta-2",
        "ana",
    ).json()

    assert "Carvajal" in respuesta["respuesta"]
    assert respuesta["ruta"] == "boveda"
    assert respuesta["cache"] is False
    assert contar_cache(escenario) == 0


def test_consulta_mixta_de_perfil_no_lee_ni_escribe_la_cache(tmp_path: Path) -> None:
    """La consulta de perfil con residual tampoco consulta la caché."""
    cache = CacheRegistro()
    servicio, _ = servicio_con_cache(
        tmp_path,
        cache,
        modelo=ModeloGuion([RESPUESTA_BOVEDA]),
        fragmentos=[fragmento()],
    )
    servicio.preguntar("trabajo en Carvajal", "hilo-consulta", "ana")

    respuesta = servicio.preguntar(
        "¿Dónde trabajo y qué es un CDT?",
        "hilo-consulta-2",
        "ana",
    )

    assert "Carvajal" in respuesta["respuesta"]
    assert respuesta["cache"] is False
    assert cache.llamadas == []


def test_consulta_de_perfil_sin_dato_tampoco_cachea(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """El mensaje de perfil sin dato no se guarda en la caché."""
    modelo = ModeloGuion([RESPUESTA_BOVEDA])
    escenario = preparar(monkeypatch, tmp_path, modelo=modelo, fragmentos=[fragmento()])

    respuesta = preguntar_con_perfil(
        escenario.cliente,
        "¿Dónde trabajo y qué es un CDT?",
        "hilo-sin-dato",
        "beto",
    ).json()

    assert "No tengo ese dato en tu perfil" in respuesta["respuesta"]
    assert respuesta["cache"] is False
    assert contar_cache(escenario) == 0


def test_checkpointer_y_cache_no_contienen_datos_de_perfil(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Los SQLite de memoria y caché no conservan nombre ni empresa."""
    escenario = preparar(monkeypatch, tmp_path)

    preguntar_con_perfil(
        escenario.cliente,
        "me llamo Ana y trabajo en Carvajal",
        "hilo-ana",
        "ana",
    )
    preguntar_con_perfil(escenario.cliente, "¿Dónde trabajo?", "hilo-otro", "ana")

    for patron in ("memoria.sqlite*", "cache.sqlite*"):
        archivos = list((tmp_path / "data/asistente").glob(patron))
        assert archivos
        for archivo in archivos:
            contenido = archivo.read_bytes()
            assert b"Ana" not in contenido, archivo.name
            assert b"Carvajal" not in contenido, archivo.name


def test_sin_perfil_id_responde_memoria_inactiva_sin_guardar(tmp_path: Path) -> None:
    """Sin `perfil_id` la ruta perfil responde corto, sin tokens y sin guardar."""
    store = StoreEspia()
    servicio, _ = servicio_con_cache(tmp_path, CacheRegistro(), store=store)

    respuesta = servicio.preguntar("me llamo Ana", "hilo-sin-perfil", "")

    assert respuesta["ruta"] == "perfil"
    assert respuesta["respuesta"] == MENSAJE_PERFIL_INACTIVO
    assert respuesta["tokens_entrada"] == 0
    assert respuesta["tokens_salida"] == 0
    assert respuesta["cache"] is False
    assert store.puts == []


def test_pii_en_mensaje_de_perfil_no_se_guarda(tmp_path: Path) -> None:
    """Si el mensaje trae PII, el rechazo ocurre antes y el store queda vacío."""
    store = StoreEspia()
    servicio, _ = servicio_con_cache(tmp_path, CacheRegistro(), store=store)

    respuesta = servicio.preguntar(
        "me llamo Ana, mi cédula es 1234567890",
        "hilo-pii-perfil",
        "ana",
    )

    assert respuesta["turno"] == "X"
    assert respuesta["ruta"] == "rechazo"
    assert store.puts == []


def test_olvida_mi_perfil_borra_los_datos(tmp_path: Path) -> None:
    """«olvida mi perfil» borra el documento y las consultas posteriores no lo ven."""
    servicio, _ = servicio_con_cache(tmp_path, CacheRegistro())
    servicio.preguntar("trabajo en Carvajal", "hilo-1", "ana")

    borrado = servicio.preguntar("olvida mi perfil", "hilo-2", "ana")
    consulta = servicio.preguntar("¿Dónde trabajo?", "hilo-3", "ana")

    assert borrado["ruta"] == "perfil"
    assert "Borré" in borrado["respuesta"]
    assert "Carvajal" not in consulta["respuesta"]


def test_cache_distingue_perfil_en_la_clave() -> None:
    """La clave defensiva no reutiliza una respuesta entre dos perfiles."""
    assert CacheRespuestas.clave("¿Dónde trabajo?", "perfil", "v2", "ana") != (
        CacheRespuestas.clave("¿Dónde trabajo?", "perfil", "v2", "beto")
    )
    assert CacheRespuestas.clave("¿Qué es un CDT?", "boveda", "v2") == (
        CacheRespuestas.clave("¿Qué es un CDT?", "boveda", "v2", "")
    )


def test_ninguna_pregunta_de_fase2_activa_el_perfil() -> None:
    """Ninguna de las 44 preguntas ni sus previas se confunde con un perfil."""
    preguntas = cargar_preguntas_fase2()
    assert len(preguntas) == 44
    for pregunta in preguntas:
        assert detectar_intencion(pregunta.pregunta) is None, pregunta.id
        if pregunta.previa:
            assert detectar_intencion(pregunta.previa) is None, pregunta.id


def test_pregunta_de_boveda_sigue_siendo_boveda(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Una pregunta normal con `perfil_id` no cambia de ruta ni de caché."""
    modelo = ModeloGuion([RESPUESTA_BOVEDA])
    escenario = preparar(monkeypatch, tmp_path, modelo=modelo, fragmentos=[fragmento()])

    cuerpo = preguntar_con_perfil(
        escenario.cliente,
        PREGUNTA_BOVEDA,
        "hilo-normal",
        "ana",
    ).json()

    assert cuerpo["ruta"] == "boveda"
    assert cuerpo["cache"] is False
    assert contar_cache(escenario) == 1
