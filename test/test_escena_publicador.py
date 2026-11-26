"""Pruebas sin red del publicador de la escena en vivo.

Contrato: `docs/ESCENA_EN_VIVO.md` §4–§7. Las pruebas usan ``tmp_path`` y el
interruptor ``ESCENA_EN_VIVO``; nunca tocan ``data/escena/`` real.
"""

from __future__ import annotations

import json
import logging
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from banco_occidente_corpus.escena import en_vivo
from banco_occidente_corpus.escena.contratos import TurnoEscena


def _turno(orden: int = 1, *, personaje: str = "pana", texto: str | None = None) -> TurnoEscena:
    """Arma un turno mínimo válido para la lista."""
    return TurnoEscena(
        id=f"vivo.{orden}.v1",
        orden=orden,
        personaje=personaje,  # type: ignore[arg-type]
        texto=texto or f"Turno {orden} de la escena.",
        origen="reglas",
    )


def _ruta(tmp_path: Path) -> Path:
    """Devuelve una lista de prueba dentro de una carpeta que aún no existe."""
    return tmp_path / "escena" / "en_vivo.jsonl"


def _encender(monkeypatch: pytest.MonkeyPatch) -> None:
    """Enciende el interruptor de la escena en vivo."""
    monkeypatch.setenv("ESCENA_EN_VIVO", "1")


def test_apagado_no_crea_la_carpeta_ni_el_archivo(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Sin ESCENA_EN_VIVO no se toca nada, ni siquiera la carpeta."""
    monkeypatch.delenv("ESCENA_EN_VIVO", raising=False)
    ruta = _ruta(tmp_path)
    assert en_vivo.publicar_turnos((_turno(),), origen="herramienta", ruta=ruta) == ()
    assert not ruta.parent.exists()


@pytest.mark.parametrize("valor", ["0", "", "true", "sí"])
def test_solo_el_valor_uno_enciende_la_escritura(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    valor: str,
) -> None:
    """Cualquier valor distinto de 1 deja la lista sin crear."""
    monkeypatch.setenv("ESCENA_EN_VIVO", valor)
    ruta = _ruta(tmp_path)
    assert en_vivo.publicar_turnos((_turno(),), origen="herramienta", ruta=ruta) == ()
    assert not ruta.exists()


def test_encendido_escribe_una_linea_por_turno_con_seq_consecutivo(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Un lote de cuatro turnos deja cuatro líneas con el mismo ts y seq seguidos."""
    _encender(monkeypatch)
    ruta = _ruta(tmp_path)
    turnos = tuple(_turno(orden, personaje="don_gota") for orden in range(1, 5))

    seqs = en_vivo.publicar_turnos(turnos, origen="herramienta", ruta=ruta)

    assert len(seqs) == 4
    assert list(seqs) == list(range(seqs[0], seqs[0] + 4))
    lineas = ruta.read_text(encoding="utf-8").splitlines()
    assert len(lineas) == 4
    registros = [json.loads(linea) for linea in lineas]
    assert {registro["ts"] for registro in registros} == {registros[0]["ts"]}
    assert all(registro["origen"] == "herramienta" for registro in registros)
    assert [registro["turno"]["personaje"] for registro in registros] == ["don_gota"] * 4
    assert "\r" not in ruta.read_text(encoding="utf-8")


def test_dos_hilos_publican_sin_repetir_seq_ni_corromper_lineas(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Cuatro hilos comparten el candado del proceso y no se pisan."""
    _encender(monkeypatch)
    ruta = _ruta(tmp_path)

    def publicar(desde: int) -> list[int]:
        """Publica un lote de diez turnos desde un orden propio."""
        turnos = tuple(_turno(desde + posicion) for posicion in range(10))
        return list(en_vivo.publicar_turnos(turnos, origen="herramienta", ruta=ruta))

    with ThreadPoolExecutor(max_workers=4) as ejecutor:
        lotes = list(ejecutor.map(publicar, (100, 200, 300, 400)))

    seqs = [seq for lote in lotes for seq in lote]
    assert len(seqs) == 40
    assert len(set(seqs)) == 40
    registros, ultimo = en_vivo.leer_turnos(0, limite=100, ruta=ruta)
    assert len(registros) == 40
    assert ultimo == max(seqs)
    assert [registro["seq"] for registro in registros] == sorted(seqs)


def test_dos_procesos_publican_sin_repetir_seq_ni_corromper_lineas(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Dos procesos con el bloqueo del sistema no repiten seq."""
    _encender(monkeypatch)
    ruta = _ruta(tmp_path)
    script = """
import json
import sys
from pathlib import Path

from banco_occidente_corpus.escena.contratos import TurnoEscena
from banco_occidente_corpus.escena.en_vivo import publicar_turnos

ruta = Path(sys.argv[1])
turnos = tuple(
    TurnoEscena(
        id=f"proceso.{posicion}.v1",
        orden=posicion,
        personaje="pana",
        texto=f"Turno {posicion} del proceso.",
        origen="reglas",
    )
    for posicion in range(8)
)
print(json.dumps(publicar_turnos(turnos, origen="herramienta", ruta=ruta)))
"""
    procesos = [
        subprocess.Popen(  # noqa: S603 - intérprete del propio entorno de pruebas
            [sys.executable, "-c", script, str(ruta)],
            cwd=Path(__file__).resolve().parents[1],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for _ in range(2)
    ]
    for proceso in procesos:
        salida, error = proceso.communicate(timeout=60)
        assert proceso.returncode == 0, error
        assert json.loads(salida)

    registros, _ = en_vivo.leer_turnos(0, limite=100, ruta=ruta)
    seqs = [int(registro["seq"]) for registro in registros]
    assert len(seqs) == 16
    assert len(set(seqs)) == 16
    assert seqs == sorted(seqs)


def test_un_turno_con_pii_no_se_publica(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """El publicador es la última barrera y solo registra el código, no el dato."""
    _encender(monkeypatch)
    ruta = _ruta(tmp_path)
    con_correo = _turno(1, texto="Escríbeme a ana@example.com para el préstamo.")
    con_telefono = _turno(2, texto="Mi celular es 300 123 4567, llámame.")
    limpio = _turno(3, texto="Don Gota cobra 20 % mensual.")

    with caplog.at_level(logging.DEBUG):
        seqs = en_vivo.publicar_turnos(
            (con_correo, con_telefono, limpio),
            origen="herramienta",
            ruta=ruta,
        )

    assert len(seqs) == 1
    texto = ruta.read_text(encoding="utf-8")
    assert "ana@example.com" not in texto
    assert "300 123 4567" not in texto
    assert "pii" in caplog.text
    assert "ana@example.com" not in caplog.text
    assert "300 123 4567" not in caplog.text


def test_los_telefonos_publicos_permitidos_si_se_publican(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """El canal puede dejar pasar los teléfonos oficiales del banco."""
    _encender(monkeypatch)
    ruta = _ruta(tmp_path)
    turno = _turno(1, texto="Llámanos a la Línea 6012345678 del banco.")

    assert en_vivo.publicar_turnos((turno,), origen="canal", ruta=ruta) == ()
    assert (
        len(
            en_vivo.publicar_turnos(
                (turno,),
                origen="canal",
                permitidos=("6012345678",),
                ruta=ruta,
            )
        )
        == 1
    )


def test_un_turno_invalido_se_descarta_y_el_resto_sigue(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Un turno que no valida con TurnoEscena no entra; los válidos sí."""
    _encender(monkeypatch)
    ruta = _ruta(tmp_path)
    invalido = {"id": "", "orden": 1, "personaje": "pana", "texto": "x", "origen": "reglas"}

    seqs = en_vivo.publicar_turnos(
        (invalido, _turno(2)),  # type: ignore[arg-type]
        origen="herramienta",
        ruta=ruta,
    )

    assert len(seqs) == 1
    assert len(ruta.read_text(encoding="utf-8").splitlines()) == 1


def test_una_escritura_fallida_devuelve_vacio_sin_lanzar(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Si la ruta no se puede abrir, el publicador no rompe a quien lo llama."""
    _encender(monkeypatch)
    carpeta = tmp_path / "soy-una-carpeta"
    carpeta.mkdir()

    assert en_vivo.publicar_turnos((_turno(),), origen="herramienta", ruta=carpeta) == ()


def test_lector_devuelve_solo_los_nuevos_desde_un_seq(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """`desde` filtra, `ultimo` avanza y un lote vacío devuelve el mismo cursor."""
    _encender(monkeypatch)
    ruta = _ruta(tmp_path)
    primero = en_vivo.publicar_turnos((_turno(1), _turno(2)), origen="herramienta", ruta=ruta)
    segundo = en_vivo.publicar_turnos((_turno(3),), origen="herramienta", ruta=ruta)

    registros, ultimo = en_vivo.leer_turnos(primero[-1], ruta=ruta)

    assert [registro["seq"] for registro in registros] == [segundo[0]]
    assert ultimo == segundo[0]
    assert en_vivo.leer_turnos(ultimo, ruta=ruta) == ((), ultimo)


def test_lector_ignora_lineas_corruptas_y_a_medias(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Una línea truncada o inválida no avanza el cursor ni rompe la lectura."""
    _encender(monkeypatch)
    ruta = _ruta(tmp_path)
    seqs = en_vivo.publicar_turnos((_turno(1), _turno(2)), origen="herramienta", ruta=ruta)
    with ruta.open("a", encoding="utf-8", newline="\n") as archivo:
        archivo.write('{"seq": 99, "ts": "2026-11-26T15:05:00+00:00"\n')
        archivo.write("no es json\n")
        archivo.write('{"seq": "x", "ts": "2026-11-26T15:05:00+00:00", "origen": "canal"}\n')

    registros, ultimo = en_vivo.leer_turnos(0, ruta=ruta)

    assert [registro["seq"] for registro in registros] == list(seqs)
    assert ultimo == seqs[-1]


def test_lector_respeta_el_limite_y_no_crea_el_archivo(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """El lector no crea nada y devuelve como máximo el límite pedido."""
    _encender(monkeypatch)
    ruta = _ruta(tmp_path)
    en_vivo.publicar_turnos((_turno(1), _turno(2), _turno(3)), origen="herramienta", ruta=ruta)

    registros, ultimo = en_vivo.leer_turnos(0, limite=2, ruta=ruta)
    assert len(registros) == 2
    assert ultimo == int(registros[-1]["seq"])

    ausente = tmp_path / "no" / "existe.jsonl"
    assert en_vivo.leer_turnos(0, ruta=ausente) == ((), 0)
    assert not ausente.parent.exists()


def test_el_interruptor_se_consulta_en_cada_publicacion(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Apagar la variable entre dos llamadas detiene la segunda escritura."""
    _encender(monkeypatch)
    ruta = _ruta(tmp_path)
    assert len(en_vivo.publicar_turnos((_turno(1),), origen="herramienta", ruta=ruta)) == 1

    monkeypatch.setenv("ESCENA_EN_VIVO", "0")
    assert en_vivo.publicar_turnos((_turno(2),), origen="herramienta", ruta=ruta) == ()
    assert len(ruta.read_text(encoding="utf-8").splitlines()) == 1


def test_la_escena_solo_tiene_un_archivo_hermano_de_bloqueo(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """La escritura deja un único archivo de bloqueo junto a la lista."""
    _encender(monkeypatch)
    ruta = _ruta(tmp_path)
    en_vivo.publicar_turnos((_turno(1),), origen="herramienta", ruta=ruta)
    assert (ruta.parent / en_vivo.NOMBRE_BLOQUEO).is_file()
    assert sorted(nombre.name for nombre in ruta.parent.iterdir()) == sorted(
        [ruta.name, en_vivo.NOMBRE_BLOQUEO]
    )


def test_el_bloqueo_ocupado_descarta_el_lote_sin_esperar_de_mas(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Si otro proceso tiene el bloqueo, el lote se descarta y la respuesta sigue."""
    _encender(monkeypatch)
    ruta = _ruta(tmp_path)
    monkeypatch.setattr(en_vivo, "_tomar_bloqueo", lambda _ruta: None)

    assert en_vivo.publicar_turnos((_turno(1),), origen="herramienta", ruta=ruta) == ()
    assert not ruta.exists()


def test_el_lote_publica_despues_de_un_bloqueo_liberado(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """El candado global de los hilos no deja estados a medias."""
    _encender(monkeypatch)
    ruta = _ruta(tmp_path)
    en_vivo.publicar_turnos((_turno(1),), origen="herramienta", ruta=ruta)

    def publicar() -> int:
        """Publica un turno desde otro hilo."""
        return len(en_vivo.publicar_turnos((_turno(2),), origen="herramienta", ruta=ruta))

    hilo = threading.Thread(target=publicar)
    hilo.start()
    hilo.join(timeout=10)
    assert not hilo.is_alive()
    assert len(ruta.read_text(encoding="utf-8").splitlines()) == 2
