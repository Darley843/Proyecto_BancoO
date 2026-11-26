"""Manda un mensaje al webhook del canal en modo ``falso``, dentro del proceso.

Ensaya la escena en vivo **sin Meta, sin túnel y sin abrir puertos**: construye
la app con el ``TestClient`` de FastAPI, firma el cuerpo con el App Secret y
recorre la misma cadena que en producción (firma, extracción, despachador,
consentimiento, entrevista, motor). ``EnviadorFalso`` registra la respuesta en
``data/asistente/whatsapp.sqlite`` y, con ``ESCENA_EN_VIVO=1`` y
``ESCENA_CODIGO`` en la sesión, el canal publica los turnos de la escena.

Es el mismo mecanismo de ``make simular``, pero para un mensaje suelto.

Orden para la escena: ``hola``, el botón ``Acepto`` y después
``ESCENA <código de cuatro dígitos>``.

Uso:

    uv run python scripts/mandar_falso.py "hola"
    uv run python scripts/mandar_falso.py --boton consent:acepto Acepto
    uv run python scripts/mandar_falso.py "ESCENA 1965"
    uv run python scripts/mandar_falso.py "¿cuál es la tasa de libre inversión?"

Si no hay ``WHATSAPP_APP_SECRET`` en el entorno, el script inventa uno para esta
corrida; la app se crea en el mismo proceso, así que la firma coincide. Si hay
``WHATSAPP_ID_SALT`` cargada se respeta; si no, se inventa una y el número entra
por la ventana de ``[evento]``, no por la lista de huellas. El número por
defecto es ficticio y no lleva datos de nadie.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import secrets
import sys
import time
from pathlib import Path
from types import ModuleType

from fastapi.testclient import TestClient

from banco_occidente_corpus.canal.firma import calcular_firma
from banco_occidente_corpus.simulador.payloads import payload_boton, payload_texto

#: Número ficticio de la prueba; cámbialo con ``--numero``.
NUMERO = "573001112233"


def _cargar_app() -> ModuleType:
    """Carga ``app.py`` por ruta, porque la carpeta ``app/`` tapa el módulo.

    Returns:
        El módulo de arranque, con ``crear_app`` disponible.
    """
    raiz = Path(__file__).resolve().parents[1]
    especificacion = importlib.util.spec_from_file_location("arranque_ensayo", raiz / "app.py")
    if especificacion is None or especificacion.loader is None:
        raise RuntimeError("no se pudo cargar app.py")
    modulo = importlib.util.module_from_spec(especificacion)
    especificacion.loader.exec_module(modulo)
    return modulo


def main(argv: list[str] | None = None) -> int:
    """Construye, firma y entrega el mensaje; devuelve el código de salida.

    Args:
        argv: argumentos de la línea de órdenes; por defecto ``sys.argv``.

    Returns:
        ``0`` si el webhook respondió 200; ``1`` en cualquier otro caso.
    """
    parser = argparse.ArgumentParser(description="Mensaje al webhook del canal, sin red.")
    parser.add_argument("texto", nargs="?", default="", help="texto del mensaje")
    parser.add_argument("--numero", default=NUMERO, help="número en E.164 sin '+'")
    parser.add_argument(
        "--boton",
        nargs=2,
        metavar=("ID", "TITULO"),
        help="manda una respuesta de botón en vez de texto",
    )
    argumentos = parser.parse_args(argv)

    if not argumentos.boton and not argumentos.texto:
        parser.error("falta el texto o un --boton")

    os.environ.setdefault("WHATSAPP_MODO", "falso")
    secreto = os.getenv("WHATSAPP_APP_SECRET", "").strip() or secrets.token_hex(16)
    os.environ["WHATSAPP_APP_SECRET"] = secreto
    os.environ.setdefault("WHATSAPP_ID_SALT", secrets.token_hex(16))

    marca = int(time.time())
    if argumentos.boton:
        datos = payload_boton(
            argumentos.numero,
            argumentos.boton[0],
            argumentos.boton[1],
            marca_tiempo=marca,
        )
    else:
        datos = payload_texto(argumentos.numero, argumentos.texto, marca_tiempo=marca)

    cuerpo = json.dumps(datos).encode("utf-8")
    cabeceras = {
        "Content-Type": "application/json",
        "X-Hub-Signature-256": calcular_firma(cuerpo, secreto),
    }
    arranque = _cargar_app()
    with TestClient(arranque.crear_app()) as cliente:
        respuesta = cliente.post("/webhooks/whatsapp", content=cuerpo, headers=cabeceras)

    print(f"{respuesta.status_code} {respuesta.text}")
    if respuesta.status_code != 200:
        print(
            "Revisa que el número entre por la ventana de [evento] o tenga huella, "
            "y que ESCENA_EN_VIVO esté en 1 (con ESCENA_CODIGO en la sesión) "
            "para publicar en la lista.",
            file=sys.stderr,
        )
    return 0 if respuesta.status_code == 200 else 1


if __name__ == "__main__":
    raise SystemExit(main())
