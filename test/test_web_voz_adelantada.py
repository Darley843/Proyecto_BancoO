"""Pruebas de la voz adelantada de la escena (sin silencio entre personajes).

Piper tarda en generar cada audio. Mientras suena un turno, la escena pide ya
el audio del turno siguiente (`adelantarVoz` en `app/web/voz.js`) y
`decirComo` lo reutiliza en vez de pedirlo otra vez.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
WEB = RAIZ / "app" / "web"
NODE = shutil.which("node")


def _cuerpo(codigo: str, firma: str) -> str:
    """Devuelve el cuerpo de una función de un módulo JS, hasta su cierre."""
    cuerpo = codigo[codigo.index(firma) :]
    return cuerpo[: cuerpo.index("\n}\n")]


def test_la_escena_adelanta_la_voz_del_turno_siguiente() -> None:
    """Mientras suena un turno, se pide ya el audio de Piper del que sigue."""
    codigo = (WEB / "escena" / "escena.js").read_text(encoding="utf-8")
    assert 'import { adelantarVoz, decirComo, detenerVoz } from "../voz.js";' in codigo
    decir = _cuerpo(codigo, "function decir(turno)")
    assert "adelantarSiguiente(casilla);" in decir
    adelantar = _cuerpo(codigo, "function adelantarSiguiente(casilla)")
    assert "estado.turnos[estado.indice + 1]" in adelantar
    assert 'siguiente.personaje === "joven"' in adelantar
    assert "pideVoz(siguiente.personaje, casilla)" in adelantar
    assert "adelantarVoz(siguiente.personaje, paraVoz(siguiente.texto))" in adelantar


def test_el_adelanto_vive_solo_en_memoria_y_tiene_tope() -> None:
    """Nada de storage: un `Map` en memoria con máximo de audios."""
    codigo = (WEB / "voz.js").read_text(encoding="utf-8")
    assert "const MAXIMO_ADELANTADOS = 4;" in codigo
    assert "const adelantados = new Map();" in codigo
    assert "localStorage" not in codigo
    assert "sessionStorage" not in codigo
    adelantar = _cuerpo(codigo, "export async function adelantarVoz(personaje, texto)")
    assert "adelantados.size >= MAXIMO_ADELANTADOS" in adelantar
    assert "usaPiper(ajuste, limpio)" in adelantar


_PROGRAMA = """
const pedidas = [];
class AudioFalso {
  pause() {}
  play() { setTimeout(() => this.onended?.(), 0); return Promise.resolve(); }
}
globalThis.window = { Audio: AudioFalso, setTimeout, clearTimeout };
URL.createObjectURL = () => "blob:falso";
URL.revokeObjectURL = () => {};
globalThis.fetch = async (url, opciones) => {
  if (url === "/api/voz/personajes") {
    const navegador = { voz: "", tono: 1, velocidad: 1 };
    return { ok: true, json: async () => ({ personajes: {
      don_gota: { motor: "piper", piper: true, navegador },
    } }) };
  }
  pedidas.push(JSON.parse(opciones.body).texto);
  return { ok: true, blob: async () => new Blob(["ogg"]) };
};
const voz = await import(URL_VOZ);
await voz.adelantarVoz("don_gota", "Yo le presto ya mismo.");
await voz.adelantarVoz("don_gota", "Yo le presto ya mismo.");
const sono = await voz.decirComo("don_gota", "Yo le presto ya mismo.");
const otra = await voz.decirComo("don_gota", "Sin papeles.");
console.log(JSON.stringify({ pedidas, sono, otra }));
"""


@pytest.mark.skipif(NODE is None, reason="Node no está instalado")
def test_el_audio_adelantado_se_usa_y_no_se_pide_dos_veces() -> None:
    """`adelantarVoz` pide una vez; `decirComo` reutiliza y lo que no se adelantó se pide."""
    assert NODE
    programa = _PROGRAMA.replace("URL_VOZ", json.dumps((WEB / "voz.js").as_uri()))
    salida = subprocess.run(
        [NODE, "--input-type=module", "-e", programa],
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )
    assert json.loads(salida.stdout) == {
        "pedidas": ["Yo le presto ya mismo.", "Sin papeles."],
        "sono": "piper",
        "otra": "piper",
    }
