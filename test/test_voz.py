"""Pruebas de las voces de la escena (sin los modelos de Piper ni la red).

La síntesis se sustituye por un tono generado con numpy: se prueba la
configuración por personaje, el cambio de tono, la conversión a OGG/Opus, la
memoria, la presentación fija de Pana y los endpoints de la web.
"""

from __future__ import annotations

import io
from pathlib import Path

import numpy as np
import pytest
import soundfile
from fastapi import FastAPI
from fastapi.testclient import TestClient

from banco_occidente_corpus.voz import __main__ as muestras
from banco_occidente_corpus.voz.api import crear_router_voz
from banco_occidente_corpus.voz.presentacion import (
    TEXTO_PRESENTACION,
    es_pedido_de_presentacion,
)
from banco_occidente_corpus.voz.sintesis import (
    MAXIMO_EN_MEMORIA,
    PERSONAJES,
    ConfiguracionVoz,
    VozEscena,
    VozNoDisponible,
    VozPersonaje,
    a_ogg_opus,
    cambiar_tono,
    cargar_configuracion_voz,
    crear_voz,
    modelos_disponibles,
    remuestrear,
    sintetizador_piper,
)

RAIZ = Path(__file__).resolve().parents[1]


class TonoFalso:
    """Sintetizador falso: un tono corto y anota con qué voz se pidió."""

    def __init__(self, frecuencia: int = 22050) -> None:
        """Guarda la frecuencia y arranca la lista de llamadas vacía."""
        self.frecuencia = frecuencia
        self.llamadas: list[tuple[str, VozPersonaje]] = []

    def __call__(self, texto: str, voz: VozPersonaje) -> tuple[np.ndarray, int]:
        """Devuelve 0,1 s de un tono de 220 Hz."""
        self.llamadas.append((texto, voz))
        tiempo = np.arange(int(self.frecuencia * 0.1)) / self.frecuencia
        return (0.3 * np.sin(2 * np.pi * 220 * tiempo)).astype(np.float32), self.frecuencia


def _escena(sintetizador: TonoFalso | None = None) -> tuple[VozEscena, TonoFalso]:
    """Arma unas voces con el sintetizador falso y la configuración del repo."""
    falso = sintetizador or TonoFalso()
    config = cargar_configuracion_voz()
    return VozEscena(sintetizador=falso, personajes=config.personajes), falso


def _toml(tmp_path: Path, contenido: str) -> Path:
    """Escribe un voz.toml temporal y devuelve su ruta."""
    ruta = tmp_path / "voz.toml"
    ruta.write_text(contenido, encoding="utf-8")
    return ruta


# --- Configuración -----------------------------------------------------------


def test_config_del_repo_trae_los_seis_personajes() -> None:
    """config/voz.toml define una voz para cada personaje del contrato."""
    config = cargar_configuracion_voz(RAIZ / "config" / "voz.toml")
    assert tuple(config.personajes) == PERSONAJES
    assert config.personajes["agente_joven"].hablante == 0
    assert config.personajes["agente_banco"].modelo == "es_AR-daniela-high"
    assert config.personajes["joven"].hablante == 1


def test_config_del_repo_distingue_a_cada_personaje() -> None:
    """Ningún par de personajes suena igual (modelo, hablante, tono)."""
    config = cargar_configuracion_voz(RAIZ / "config" / "voz.toml")
    firmas = {(v.modelo, v.hablante, v.tono) for v in config.personajes.values()}
    assert len(firmas) == len(PERSONAJES)


def test_las_cinco_voces_de_la_escena_usan_modelos_distintos() -> None:
    """Los cinco personajes que hablan (todos menos el joven) no comparten modelo."""
    config = cargar_configuracion_voz(RAIZ / "config" / "voz.toml")
    hablan = [n for n in PERSONAJES if n != "joven"]
    assert len({config.personajes[n].modelo for n in hablan}) == len(hablan)


def test_sin_archivo_usa_valores_por_defecto(tmp_path: Path) -> None:
    """Si falta el TOML, todos los personajes usan la voz por defecto."""
    config = cargar_configuracion_voz(tmp_path / "no-existe.toml")
    assert config.activa
    assert set(config.personajes) == set(PERSONAJES)
    assert config.modelos() == ("es_MX-ald-medium",)


def test_personaje_que_falta_usa_la_voz_por_defecto(tmp_path: Path) -> None:
    """Un TOML con un solo personaje completa los demás."""
    ruta = _toml(tmp_path, '[personajes.pana]\nmodelo = "es_ES-davefx-medium"\n')
    config = cargar_configuracion_voz(ruta)
    assert config.personajes["pana"].modelo == "es_ES-davefx-medium"
    assert config.personajes["auditor"].modelo == "es_MX-ald-medium"


@pytest.mark.parametrize(
    ("contenido", "mensaje"),
    [
        ('[personajes.villano]\nmodelo = "x"\n', "desconocidos"),
        ("[personajes.pana]\nvelocidad = 0\n", "velocidad"),
        ("[personajes.pana]\ntono = 2.5\n", "tono"),
        ("[personajes.pana]\nhablante = -1\n", "hablante"),
        ("[voz]\nlargo_maximo = 0\n", "largo_maximo"),
        ('[personajes.pana]\nmotor = "windows"\n', "motor"),
        ("[personajes.pana]\ntono_navegador = 3\n", "tono_navegador"),
        ("[personajes.pana]\nvelocidad_navegador = 0\n", "velocidad_navegador"),
    ],
)
def test_config_invalida_falla(tmp_path: Path, contenido: str, mensaje: str) -> None:
    """Valores fuera de rango o personajes inventados se rechazan."""
    with pytest.raises(ValueError, match=mensaje):
        cargar_configuracion_voz(_toml(tmp_path, contenido))


def test_motor_navegador_no_descarga_modelo(tmp_path: Path) -> None:
    """Un personaje con motor navegador no suma modelos a `make voz-modelo`."""
    ruta = _toml(
        tmp_path,
        '[personajes.pana]\nmotor = "navegador"\nmodelo = "solo-pana"\nnavegador = "Salome"\n',
    )
    config = cargar_configuracion_voz(ruta)
    assert config.personajes["pana"].navegador == "Salome"
    assert "solo-pana" not in config.modelos()


def test_voz_del_navegador_no_llama_a_piper() -> None:
    """Con motor navegador, VozEscena no sintetiza y avisa."""
    falso = TonoFalso()
    voces = VozEscena(
        sintetizador=falso,
        personajes={"pana": VozPersonaje(modelo="x", motor="navegador")},
    )
    with pytest.raises(VozNoDisponible, match="navegador"):
        voces.audio("Hola", "pana")
    assert falso.llamadas == []


def test_ruta_modelo_relativa_y_absoluta(tmp_path: Path) -> None:
    """La carpeta relativa se resuelve contra la raíz; la absoluta se respeta."""
    relativa = ConfiguracionVoz(carpeta=Path("data/modelos/voz"))
    assert relativa.ruta_modelo("m", tmp_path) == tmp_path / "data/modelos/voz/m.onnx"
    absoluta = ConfiguracionVoz(carpeta=tmp_path / "voces")
    assert absoluta.ruta_modelo("m", Path("/otra")) == tmp_path / "voces/m.onnx"


def test_modelos_sin_repetir() -> None:
    """Dos personajes con el mismo modelo lo descargan una sola vez."""
    config = cargar_configuracion_voz(RAIZ / "config" / "voz.toml")
    modelos = config.modelos()
    assert len(modelos) == len(set(modelos))
    assert "es_ES-sharvard-medium" in modelos


def test_modelos_disponibles_segun_archivos(tmp_path: Path) -> None:
    """Un personaje tiene voz solo si su .onnx existe."""
    config = ConfiguracionVoz(
        carpeta=Path("voces"),
        personajes={n: VozPersonaje(modelo=n) for n in PERSONAJES},
    )
    (tmp_path / "voces").mkdir()
    (tmp_path / "voces" / "pana.onnx").write_bytes(b"x")
    estado = modelos_disponibles(config, tmp_path)
    assert estado["pana"] is True
    assert estado["don_gota"] is False


def test_voces_apagadas() -> None:
    """Con activa = false no se crean voces y nadie tiene modelo."""
    config = ConfiguracionVoz(activa=False)
    assert crear_voz(config) is None
    assert not any(modelos_disponibles(config).values())


# --- Audio --------------------------------------------------------------------


def test_remuestrear_cambia_el_largo() -> None:
    """De 22 050 Hz a 48 000 Hz el audio crece en la misma proporción."""
    muestras = np.zeros(22050, dtype=np.float32)
    assert remuestrear(muestras, 22050, 48000).size == 48000
    assert remuestrear(muestras, 16000, 16000).size == 22050


def test_cambiar_tono_grave_alarga_y_agudo_acorta() -> None:
    """Tono < 1 estira el audio (más grave); tono > 1 lo encoge."""
    muestras = np.ones(1000, dtype=np.float32)
    assert cambiar_tono(muestras, 0.8).size == 1250
    assert cambiar_tono(muestras, 1.25).size == 800
    assert cambiar_tono(muestras, 1.0).size == 1000


def test_ogg_opus_se_puede_leer() -> None:
    """El audio sale como OGG/Opus a 48 kHz y se decodifica."""
    tiempo = np.arange(2205) / 22050
    audio = a_ogg_opus((0.2 * np.sin(2 * np.pi * 220 * tiempo)).astype(np.float32), 22050)
    assert audio.startswith(b"OggS")
    _, frecuencia = soundfile.read(io.BytesIO(audio))
    assert frecuencia == 48000


def test_ogg_vacio_falla() -> None:
    """Sin muestras no hay audio."""
    with pytest.raises(VozNoDisponible):
        a_ogg_opus(np.zeros(0, dtype=np.float32), 16000)


# --- VozEscena ---------------------------------------------------------------


def test_cada_personaje_usa_su_voz() -> None:
    """El sintetizador recibe la voz configurada del personaje pedido."""
    voces, falso = _escena()
    voces.audio("Le presto ya mismo", "don_gota")
    voces.audio("Comparemos en tasa anual", "pana")
    assert falso.llamadas[0][1] == voces.personajes["don_gota"]
    assert falso.llamadas[1][1] == voces.personajes["pana"]


def test_memoria_por_personaje_y_texto() -> None:
    """El mismo texto del mismo personaje se sintetiza una vez; otro personaje no."""
    voces, falso = _escena()
    primero = voces.audio("Hola", "pana")
    assert voces.audio("  Hola ", "pana") == primero
    voces.audio("Hola", "auditor")
    assert len(falso.llamadas) == 2


def test_memoria_tiene_tope() -> None:
    """La memoria no crece más allá de MAXIMO_EN_MEMORIA."""
    voces, _ = _escena()
    for numero in range(MAXIMO_EN_MEMORIA + 5):
        voces.audio(f"frase {numero}", "joven")
    assert len(voces._memoria) == MAXIMO_EN_MEMORIA


def test_personaje_desconocido_falla() -> None:
    """Solo se aceptan los personajes del contrato."""
    voces, _ = _escena()
    with pytest.raises(ValueError, match="personaje"):
        voces.audio("Hola", "villano")


@pytest.mark.parametrize("texto", ["", "   ", "x" * 901])
def test_texto_vacio_o_largo_falla(texto: str) -> None:
    """Sin texto o con texto de más no se genera audio."""
    voces, _ = _escena()
    with pytest.raises(VozNoDisponible):
        voces.audio(texto, "pana")


def test_fallo_del_sintetizador_es_voz_no_disponible() -> None:
    """Cualquier error de Piper llega como VozNoDisponible."""

    def roto(texto: str, voz: VozPersonaje) -> tuple[np.ndarray, int]:
        """Falla siempre."""
        raise OSError("modelo dañado")

    voces = VozEscena(sintetizador=roto)
    with pytest.raises(VozNoDisponible):
        voces.audio("Hola", "pana")


def test_piper_sin_modelo_avisa(tmp_path: Path) -> None:
    """Sin el .onnx, el sintetizador de Piper pide `make voz-modelo`."""
    pytest.importorskip("piper")
    config = ConfiguracionVoz(carpeta=tmp_path)
    sintetizar = sintetizador_piper(config, tmp_path)
    with pytest.raises(VozNoDisponible, match="make voz-modelo"):
        sintetizar("Hola", VozPersonaje(modelo="no-existe"))


# --- Presentación -----------------------------------------------------------


@pytest.mark.parametrize("texto", ["Preséntate", "¿Quién eres?", "Pana, preséntate al público"])
def test_reconoce_el_pedido_de_presentacion(texto: str) -> None:
    """Las formas cortas de «preséntate» piden la presentación."""
    assert es_pedido_de_presentacion(texto)


@pytest.mark.parametrize("texto", [None, "", "hola", "¿cuál es la tasa del crédito?"])
def test_otras_preguntas_no_son_presentacion(texto: str | None) -> None:
    """Un saludo o una pregunta no dispara la presentación."""
    assert not es_pedido_de_presentacion(texto)


def test_presentacion_cabe_en_el_tope() -> None:
    """La presentación se puede leer con la voz (no pasa el tope)."""
    assert len(TEXTO_PRESENTACION) <= 900


# --- API ------------------------------------------------------------------------


def _cliente(voz: VozEscena | None, disponibles: dict[str, bool] | None = None) -> TestClient:
    """App mínima con solo el router de voz."""
    app = FastAPI()
    app.include_router(crear_router_voz(voz, disponibles))
    return TestClient(app)


def test_api_devuelve_ogg_del_personaje() -> None:
    """POST /api/voz con personaje responde audio/ogg."""
    voces, falso = _escena()
    respuesta = _cliente(voces).post("/api/voz", json={"texto": "Hola", "personaje": "auditor"})
    assert respuesta.status_code == 200
    assert respuesta.headers["content-type"] == "audio/ogg"
    assert respuesta.content.startswith(b"OggS")
    assert falso.llamadas[0][1] == voces.personajes["auditor"]


def test_api_sin_personaje_usa_pana() -> None:
    """Sin personaje, habla Pana (compatibilidad con la Ventanilla)."""
    voces, falso = _escena()
    assert _cliente(voces).post("/api/voz", json={"texto": "Hola"}).status_code == 200
    assert falso.llamadas[0][1] == voces.personajes["pana"]


def test_api_personaje_invalido_es_422() -> None:
    """Un personaje fuera del contrato es un pedido inválido."""
    voces, _ = _escena()
    respuesta = _cliente(voces).post("/api/voz", json={"texto": "Hola", "personaje": "villano"})
    assert respuesta.status_code == 422


def test_api_sin_voz_es_503() -> None:
    """Con las voces apagadas, la web recibe 503 y usa el navegador."""
    respuesta = _cliente(None).post("/api/voz", json={"texto": "Hola", "personaje": "pana"})
    assert respuesta.status_code == 503
    assert respuesta.json()["error"]["codigo"] == "sin_voz"


def test_api_modelo_faltante_es_503() -> None:
    """Si Piper no tiene el modelo, la API responde 503 en vez de fallar."""

    def sin_modelo(texto: str, voz: VozPersonaje) -> tuple[np.ndarray, int]:
        """Simula que falta el .onnx."""
        raise VozNoDisponible("falta la voz")

    respuesta = _cliente(VozEscena(sintetizador=sin_modelo)).post(
        "/api/voz", json={"texto": "Hola"}
    )
    assert respuesta.status_code == 503


def test_api_personajes_segun_disponibles() -> None:
    """GET /api/voz/personajes dice qué personajes tienen voz."""
    voces, _ = _escena()
    datos = _cliente(voces, {"pana": True}).get("/api/voz/personajes").json()
    assert list(datos["personajes"]) == list(PERSONAJES)
    assert datos["personajes"]["pana"]["piper"] is True
    assert datos["personajes"]["don_gota"]["piper"] is False
    assert datos["personajes"]["don_gota"]["motor"] == "piper"
    assert datos["personajes"]["don_gota"]["navegador"]["tono"] == 0.6


def test_api_personaje_con_motor_navegador() -> None:
    """Un personaje con motor navegador no tiene Piper y avisa su voz preferida."""
    voces, _ = _escena()
    personajes = dict(voces.personajes)
    personajes["joven"] = VozPersonaje(
        modelo="x", motor="navegador", navegador="Salome", tono_navegador=1.2
    )
    voces = VozEscena(sintetizador=TonoFalso(), personajes=personajes)
    cliente = _cliente(voces)
    joven = cliente.get("/api/voz/personajes").json()["personajes"]["joven"]
    assert joven == {
        "motor": "navegador",
        "piper": False,
        "navegador": {"voz": "Salome", "tono": 1.2, "velocidad": 1.0},
    }
    respuesta = cliente.post("/api/voz", json={"texto": "Hola", "personaje": "joven"})
    assert respuesta.status_code == 503


def test_api_presentacion() -> None:
    """GET /api/pana/presentacion trae el texto fijo y si Pana tiene voz."""
    voces, _ = _escena()
    datos = _cliente(voces).get("/api/pana/presentacion").json()
    assert datos == {"texto": TEXTO_PRESENTACION, "voz": True}
    assert _cliente(None).get("/api/pana/presentacion").json()["voz"] is False


# --- Muestras (make voces-prueba) ------------------------------------------------


def test_hay_muestra_para_cada_personaje() -> None:
    """make voces-prueba tiene una frase para cada personaje."""
    assert set(muestras.MUESTRAS) == set(PERSONAJES)
    assert all(len(frase) <= 900 for frase in muestras.MUESTRAS.values())


def test_muestras_escribe_un_ogg_por_personaje(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Con voces falsas se escribe un .ogg por personaje."""
    config = ConfiguracionVoz(carpeta=tmp_path)
    voces, _ = _escena()
    monkeypatch.setattr(muestras, "cargar_configuracion_voz", lambda: config)
    monkeypatch.setattr(muestras, "crear_voz", lambda *_: voces)
    monkeypatch.setattr(muestras, "PROJECT_ROOT", tmp_path)
    assert muestras.main([]) == 0
    assert sorted(p.stem for p in (tmp_path / "muestras").glob("*.ogg")) == sorted(PERSONAJES)


def test_descargar_no_repite_modelos_presentes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Si todos los modelos ya están, no se llama a Piper."""
    config = ConfiguracionVoz(carpeta=tmp_path)
    (tmp_path / "es_MX-ald-medium.onnx").write_bytes(b"x")
    monkeypatch.setattr(muestras, "cargar_configuracion_voz", lambda: config)

    def prohibido(*_: object, **__: object) -> None:
        """La descarga no debe ejecutarse."""
        raise AssertionError("no debía descargar")

    monkeypatch.setattr(muestras.subprocess, "run", prohibido)
    assert muestras.main(["descargar"]) == 0
