"""Pruebas de la voz masculina de Don Gota en la escena.

Don Gota debe sonar con voz de hombre, distinta de la de Pana y nunca con una
voz de mujer. La preferencia vive en ``config/escena.toml [voces]`` y
``app/web/voz.js`` la aplica buscando por fragmento del nombre, sin distinguir
mayúsculas ni tildes. Las pruebas de selección ejecutan ``voz.js`` con Node y
una lista de voces simulada; no necesitan navegador ni red.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tomllib
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
WEB = RAIZ / "app" / "web"
NODE = shutil.which("node")
requiere_node = pytest.mark.skipif(NODE is None, reason="Node no está instalado")


def _ejecutar(programa: str) -> dict:
    """Ejecuta un programa de Node contra ``app/web/voz.js`` y lee su JSON."""
    assert NODE
    url = (WEB / "voz.js").as_uri()
    salida = subprocess.run(
        [NODE, "--input-type=module", "-e", programa.replace("URL_VOZ", json.dumps(url))],
        capture_output=True,
        encoding="utf-8",
        timeout=30,
        check=True,
    )
    return json.loads(salida.stdout)


def test_la_preferencia_de_don_gota_esta_en_el_toml_y_en_voz_js() -> None:
    """La config y el JS no se separan: Jorge → Raul, y el Piper ya configurado."""
    datos = tomllib.loads((RAIZ / "config" / "escena.toml").read_text(encoding="utf-8"))
    preferencia = datos["voces"]["don_gota"]
    assert preferencia == ["Jorge", "Raul"]
    with (RAIZ / "config" / "voz.toml").open("rb") as fh:
        voz = tomllib.load(fh)
    assert datos["voces"]["piper_don_gota"] == voz["personajes"]["don_gota"]["modelo"]

    codigo = (WEB / "voz.js").read_text(encoding="utf-8")
    assert f"const PREFERENCIA_DON_GOTA = Object.freeze({json.dumps(preferencia)});" in codigo
    pana = voz["personajes"]["pana"]["navegador"]
    assert f'const VOZ_PANA = "{pana}";' in codigo
    assert "voiceschanged" in codigo
    assert 'normalize("NFD")' in codigo


_PROGRAMA_SELECCION = """
const voces = [];
const oyentes = new Set();
const locuciones = [];

class UtteranceFalsa {
  constructor(texto) {
    this.text = texto;
    this.voice = null;
    this.pitch = 1;
    this.rate = 1;
    this.lang = "";
  }
}

const sintesis = {
  getVoices: () => voces,
  addEventListener: (tipo, fn) => {
    if (tipo === "voiceschanged") oyentes.add(fn);
  },
  removeEventListener: (tipo, fn) => {
    if (tipo === "voiceschanged") oyentes.delete(fn);
  },
  cancel: () => {},
  speak: (locucion) => {
    locuciones.push({
      texto: locucion.text,
      voz: locucion.voice?.name ?? null,
      pitch: locucion.pitch,
      rate: locucion.rate,
      lang: locucion.lang,
    });
  },
};

function cambiarVoces(lista) {
  voces.length = 0;
  voces.push(...lista);
  for (const fn of [...oyentes]) fn();
}

globalThis.window = {
  speechSynthesis: sintesis,
  SpeechSynthesisUtterance: UtteranceFalsa,
  setTimeout,
  clearTimeout,
};
globalThis.fetch = async (url) => {
  if (url === "/api/voz/personajes") {
    return {
      ok: true,
      json: async () => ({
        personajes: {
          pana: {
            motor: "navegador",
            piper: true,
            navegador: { voz: "Gonzalo", tono: 1.15, velocidad: 1.0 },
          },
          don_gota: {
            motor: "navegador",
            piper: false,
            navegador: { voz: "", tono: 0.6, velocidad: 0.9 },
          },
        },
      }),
    };
  }
  throw new Error("No se esperaba una petición de audio.");
};

const voz = (nombre, idioma = "es-MX") => ({ name: nombre, lang: idioma, localService: true });
const completa = [
  voz("Microsoft Gonzalo Online (Natural) - Spanish (Mexico)"),
  voz("Microsoft Jorge Online (Natural) - Spanish (Mexico)"),
  voz("Microsoft Raul - Spanish (Mexico)"),
  voz("Microsoft Salome Online (Natural) - Spanish (Colombia)"),
  voz("Microsoft Dalia - Spanish (Mexico)"),
];
const ultima = () => locuciones[locuciones.length - 1];

const { decirComo } = await import(URL_VOZ);

cambiarVoces(completa);
const sonidoJorge = await decirComo("don_gota", "Le presto ya mismo.");
const gotaJorge = ultima();

cambiarVoces(completa.filter((v) => !v.name.includes("Jorge")));
const sonidoRaul = await decirComo("don_gota", "Le presto ya mismo.");
const gotaRaul = ultima();

cambiarVoces([
  voz("Microsoft Gonzalo Online (Natural) - Spanish (Mexico)"),
  voz("Microsoft RAÚL - Spanish (Mexico)"),
]);
await decirComo("don_gota", "Le presto ya mismo.");
const gotaTilde = ultima();

cambiarVoces(completa);
await decirComo("pana", "Hola, soy Pana.");
const pana = ultima();

cambiarVoces([
  voz("Microsoft Gonzalo Online (Natural) - Spanish (Mexico)"),
  voz("Microsoft Salome Online (Natural) - Spanish (Colombia)"),
  voz("Microsoft Dalia - Spanish (Mexico)"),
]);
await decirComo("don_gota", "Le presto ya mismo.");
const gotaMujeres = ultima();

cambiarVoces([]);
setTimeout(() => cambiarVoces(completa), 30);
const sonidoEspera = await decirComo("don_gota", "Le presto ya mismo.");
const gotaEspera = ultima();

console.log(JSON.stringify({
  sonidoJorge,
  gotaJorge,
  sonidoRaul,
  gotaRaul,
  gotaTilde,
  pana,
  gotaMujeres,
  sonidoEspera,
  gotaEspera,
}));
"""


@requiere_node
def test_don_gota_elige_jorge_y_sin_jorge_elige_raul() -> None:
    """Con la lista simulada de Windows/Edge, Don Gota prefiere Jorge y luego Raul."""
    datos = _ejecutar(_PROGRAMA_SELECCION)
    assert datos["sonidoJorge"] == "navegador"
    assert datos["gotaJorge"]["voz"] == ("Microsoft Jorge Online (Natural) - Spanish (Mexico)")
    assert "Jorge" in datos["gotaJorge"]["voz"]
    assert datos["sonidoRaul"] == "navegador"
    assert "Raul" in datos["gotaRaul"]["voz"]
    assert datos["gotaRaul"]["voz"] != datos["pana"]["voz"]
    assert datos["gotaTilde"]["voz"] == "Microsoft RAÚL - Spanish (Mexico)"


@requiere_node
def test_don_gota_nunca_usa_una_voz_de_mujer() -> None:
    """Si solo quedan voces de mujer, Don Gota no elige ninguna y baja el tono."""
    datos = _ejecutar(_PROGRAMA_SELECCION)
    femeninas = ("Salome", "Dalia", "Sabina", "Elena", "Sofia", "Beatriz", "Elvira")
    for caso in (datos["gotaJorge"], datos["gotaRaul"], datos["gotaMujeres"]):
        assert caso["voz"] is None or not any(nombre in caso["voz"] for nombre in femeninas)
    assert datos["gotaMujeres"]["voz"] is None
    assert datos["gotaMujeres"]["pitch"] < 0.6
    assert datos["gotaMujeres"]["rate"] < 0.9


@requiere_node
def test_pana_conserva_su_voz_y_su_tono() -> None:
    """Pana sigue con Gonzalo y sus valores de siempre."""
    datos = _ejecutar(_PROGRAMA_SELECCION)
    assert datos["pana"]["voz"] == "Microsoft Gonzalo Online (Natural) - Spanish (Mexico)"
    assert datos["pana"]["pitch"] == pytest.approx(1.15)
    assert datos["pana"]["rate"] == pytest.approx(1.0)


@requiere_node
def test_don_gota_espera_voiceschanged_si_la_lista_llega_vacia() -> None:
    """Con la lista vacía al inicio, se elige al llegar el aviso del navegador."""
    datos = _ejecutar(_PROGRAMA_SELECCION)
    assert datos["sonidoEspera"] == "navegador"
    assert "Jorge" in datos["gotaEspera"]["voz"]


_PROGRAMA_PIPER = """
const locuciones = [];
const pedidas = [];

class UtteranceFalsa {
  constructor(texto) {
    this.text = texto;
    this.voice = null;
    this.pitch = 1;
    this.rate = 1;
    this.lang = "";
  }
}

const voces = [
  { name: "Microsoft Gonzalo Online (Natural) - Spanish (Mexico)", lang: "es-MX" },
  { name: "Microsoft Jorge Online (Natural) - Spanish (Mexico)", lang: "es-MX" },
  { name: "Microsoft Raul - Spanish (Mexico)", lang: "es-MX" },
];

class AudioFalso {
  pause() {}
  play() {
    setTimeout(() => this.onended?.(), 0);
    return Promise.resolve();
  }
}

globalThis.window = {
  Audio: AudioFalso,
  speechSynthesis: {
    getVoices: () => voces,
    addEventListener: () => {},
    removeEventListener: () => {},
    cancel: () => {},
    speak: (locucion) => locuciones.push(locucion),
  },
  SpeechSynthesisUtterance: UtteranceFalsa,
  setTimeout,
  clearTimeout,
};
globalThis.fetch = async (url, opciones) => {
  if (url === "/api/voz/personajes") {
    return {
      ok: true,
      json: async () => ({
        personajes: {
          don_gota: {
            motor: "piper",
            piper: PIPER_LISTO,
            navegador: { voz: "", tono: 0.6, velocidad: 0.9 },
          },
        },
      }),
    };
  }
  pedidas.push(JSON.parse(opciones.body).texto);
  return { ok: true, blob: async () => new Blob(["ogg"]) };
};
URL.createObjectURL = () => "blob:falso";
URL.revokeObjectURL = () => {};

const { decirComo } = await import(URL_VOZ);
const sono = await decirComo("don_gota", "Le presto ya mismo.");
console.log(JSON.stringify({
  sono,
  pedidas,
  vozNavegador: locuciones[0]?.voice?.name ?? null,
}));
"""


@requiere_node
@pytest.mark.parametrize(("piper_listo", "esperado"), [(False, "navegador"), (True, "piper")])
def test_don_gota_solo_usa_piper_si_el_modelo_masculino_esta(
    piper_listo: bool, esperado: str
) -> None:
    """Sin el modelo descargado va al navegador; con él, usa el Piper ya configurado."""
    programa = _PROGRAMA_PIPER.replace("PIPER_LISTO", "true" if piper_listo else "false")
    datos = _ejecutar(programa)
    assert datos["sono"] == esperado
    assert bool(datos["pedidas"]) is piper_listo
    if not piper_listo:
        assert "Jorge" in datos["vozNavegador"]
