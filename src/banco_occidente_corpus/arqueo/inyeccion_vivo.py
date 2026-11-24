"""Corre el catálogo de inyección contra el agente real de OpenClaw (tarea 3.5).

Envía cada ataque de `config/evaluacion/inyeccion.toml` al gateway de OpenClaw
con el contrato de `agente-openclaw` (decisión 2 del diseño) y evalúa la
respuesta con `arqueo.inyeccion`:

```http
POST http://127.0.0.1:18789/v1/chat/completions
Authorization: Bearer ${OPENCLAW_GATEWAY_TOKEN}

{"model": "openclaw:pana", "user": "eval:<corrida>:<ataque>", "messages": [...]}
```

Reglas de la corrida:

- Solo habla con `127.0.0.1` o `localhost`: el gateway escucha en loopback y
  esta herramienta no sale a internet. Una URL de otro host se rechaza.
- El token se lee de `OPENCLAW_GATEWAY_TOKEN` y nunca se imprime ni se guarda.
- Cada ataque va en una sesión nueva (`eval:<corrida>:<id>`), sin historial y
  separada de las sesiones de WhatsApp (`wa:<huella>`): un ataque no contamina
  al siguiente ni la memoria de un invitado.
- Sin reintentos. Un error del gateway queda como `error:<Tipo>` y el ataque
  cuenta como no superado, para revisarlo.
- El informe no guarda el texto de las respuestas.

Uso:

```powershell
uv run python -m banco_occidente_corpus.arqueo.inyeccion_vivo --simulado
uv run python -m banco_occidente_corpus.arqueo.inyeccion_vivo
uv run python -m banco_occidente_corpus.arqueo.inyeccion_vivo --escribir-doc
```

`--simulado` no abre la red: responde con una negativa fija para probar la
cadena completa y no escribe nada. `--escribir-doc` pega la tabla en la sección
«Resultados» de `docs/INYECCION.md`.
"""

from __future__ import annotations

import argparse
import os
import secrets
import sys
import tomllib
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx

from ..config import PROJECT_ROOT
from .inyeccion import (
    RUTA_ATAQUES,
    SALIDA_JSON,
    Ataque,
    Responder,
    Resultado,
    cargar_ataques,
    correr,
    guardar_informe,
    tabla_markdown,
)

#: Configuración del gateway, si ya está en el repositorio (tarea 1.2 de Nayla).
RUTA_CONFIG: Path = PROJECT_ROOT / "config" / "openclaw.toml"
#: Documento donde se pegan los resultados.
RUTA_DOC: Path = PROJECT_ROOT / "docs" / "INYECCION.md"
#: Variable de entorno con el token del gateway.
VARIABLE_TOKEN = "OPENCLAW_GATEWAY_TOKEN"
#: Valores del contrato cuando no hay `config/openclaw.toml`.
BASE_URL_DEFECTO = "http://127.0.0.1:18789"
MODELO_DEFECTO = "openclaw:pana"
TIMEOUT_DEFECTO = 30.0
#: Prefijo de las sesiones de evaluación (las de WhatsApp usan `wa:`).
PREFIJO_SESION = "eval"
#: Hosts permitidos: el gateway solo escucha en loopback.
HOSTS_LOOPBACK: frozenset[str] = frozenset({"127.0.0.1", "localhost", "::1"})
#: Respuestas del modelo que no son un cierre normal.
FINES_VALIDOS: frozenset[str | None] = frozenset({"stop", None})
USER_AGENT = "Sucursal1965-evaluacion-inyeccion/1.0"
ENCABEZADO_RESULTADOS = "## Resultados"
#: Negativa fija del modo simulado.
NEGATIVA_SIMULADA = (
    "No puedo hacer eso. Solo te doy información general del Banco de Occidente "
    "y simulaciones orientativas; la decisión final es de un asesor."
)


class ErrorGateway(RuntimeError):
    """El gateway no devolvió una respuesta válida."""


@dataclass(frozen=True, slots=True)
class ConfigGateway:
    """Lo necesario para hablar con el gateway, sin el token."""

    base_url: str = BASE_URL_DEFECTO
    modelo: str = MODELO_DEFECTO
    timeout_segundos: float = TIMEOUT_DEFECTO


def _buscar_clave(datos: dict[str, Any], clave: str) -> Any:
    """Busca una clave en la raíz del TOML o en sus tablas de primer nivel."""
    if clave in datos:
        return datos[clave]
    for valor in datos.values():
        if isinstance(valor, dict) and clave in valor:
            return valor[clave]
    return None


def cargar_config(ruta: Path | None = None) -> ConfigGateway:
    """Lee `config/openclaw.toml` si existe; si no, usa los valores del contrato.

    Args:
        ruta: archivo TOML alternativo.

    Returns:
        URL base, modelo y tiempo máximo del gateway.
    """
    archivo = RUTA_CONFIG if ruta is None else Path(ruta)
    if not archivo.exists():
        return ConfigGateway()
    with archivo.open("rb") as fh:
        datos = tomllib.load(fh)
    base_url = _buscar_clave(datos, "base_url")
    modelo = _buscar_clave(datos, "modelo")
    timeout = _buscar_clave(datos, "timeout_segundos")
    return ConfigGateway(
        base_url=str(base_url) if base_url else BASE_URL_DEFECTO,
        modelo=str(modelo) if modelo else MODELO_DEFECTO,
        timeout_segundos=float(timeout) if timeout else TIMEOUT_DEFECTO,
    )


def validar_loopback(base_url: str) -> str:
    """Comprueba que la URL apunta al propio computador y la normaliza.

    Args:
        base_url: URL base del gateway.

    Returns:
        La URL sin barra final.

    Raises:
        ValueError: si el esquema no es http(s) o el host no es loopback.
    """
    partes = urlsplit(base_url)
    if partes.scheme not in {"http", "https"}:
        raise ValueError(f"Esquema no permitido en la URL del gateway: «{partes.scheme}»")
    if (partes.hostname or "") not in HOSTS_LOOPBACK:
        raise ValueError("El gateway debe estar en 127.0.0.1 o localhost")
    return base_url.rstrip("/")


def extraer_texto(cuerpo: Any) -> str:
    """Saca el texto de `choices[0].message.content` o falla.

    Args:
        cuerpo: JSON devuelto por el gateway.

    Returns:
        El texto de la respuesta.

    Raises:
        ErrorGateway: si falta el texto, está vacío o el cierre es anómalo.
    """
    try:
        opcion = cuerpo["choices"][0]
        texto = opcion["message"]["content"]
    except (KeyError, IndexError, TypeError) as error:
        raise ErrorGateway("Respuesta sin choices[0].message.content") from error
    if opcion.get("finish_reason") not in FINES_VALIDOS:
        raise ErrorGateway(f"finish_reason anómalo: {opcion.get('finish_reason')}")
    if not isinstance(texto, str) or not texto.strip():
        raise ErrorGateway("Respuesta vacía")
    return texto


def responder_gateway(
    config: ConfigGateway,
    token: str,
    *,
    corrida: str | None = None,
    cliente: httpx.Client | None = None,
) -> Responder:
    """Arma la función `responder` que `correr` usa para cada ataque.

    Args:
        config: URL, modelo y tiempo máximo del gateway.
        token: token del gateway (no se imprime ni se guarda).
        corrida: identificador de la corrida; por defecto, uno aleatorio.
        cliente: cliente HTTP alternativo (en las pruebas, con `MockTransport`).

    Returns:
        Una función que envía un ataque y devuelve el texto del agente.

    Raises:
        ValueError: si falta el token o la URL no es loopback.
    """
    if not token.strip():
        raise ValueError(f"Falta {VARIABLE_TOKEN}")
    url = validar_loopback(config.base_url) + "/v1/chat/completions"
    sello = corrida or secrets.token_hex(4)
    http = cliente or httpx.Client(timeout=config.timeout_segundos)
    encabezados = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "User-Agent": USER_AGENT,
    }

    def responder(ataque: Ataque) -> str:
        cuerpo = {
            "model": config.modelo,
            "user": f"{PREFIJO_SESION}:{sello}:{ataque.id}",
            "messages": [{"role": "user", "content": ataque.mensaje}],
        }
        respuesta = http.post(url, json=cuerpo, headers=encabezados)
        if respuesta.status_code != 200:
            raise ErrorGateway(f"HTTP {respuesta.status_code}")
        return extraer_texto(respuesta.json())

    return responder


def responder_simulado(_ataque: Ataque) -> str:
    """Negativa fija, para probar la corrida sin gateway ni red."""
    return NEGATIVA_SIMULADA


def bloque_resultados(resultados: Sequence[Resultado], *, modelo: str, fecha: date) -> str:
    """Texto de la sección «Resultados» de `docs/INYECCION.md`.

    Args:
        resultados: resultados de la corrida.
        modelo: modelo del gateway que respondió.
        fecha: día de la corrida.

    Returns:
        La sección completa, con su encabezado.
    """
    return (
        f"{ENCABEZADO_RESULTADOS}\n\n"
        f"Corrida del {fecha.isoformat()} contra el agente `{modelo}` del gateway de\n"
        "OpenClaw. Cada ataque va en una sesión nueva; el informe completo, sin textos\n"
        "de respuesta, queda en `data/evaluacion/inyeccion.json`. Comando:\n\n"
        "```powershell\n"
        "uv run python -m banco_occidente_corpus.arqueo.inyeccion_vivo --escribir-doc\n"
        "```\n\n"
        f"{tabla_markdown(resultados)}"
    )


def escribir_resultados(texto_doc: str, bloque: str) -> str:
    """Reemplaza la sección «Resultados» (hasta la siguiente `## `) por `bloque`.

    Args:
        texto_doc: contenido actual del documento.
        bloque: sección nueva, con su encabezado.

    Returns:
        El documento con la sección reemplazada, o con la sección al final si
        no existía.
    """
    lineas = texto_doc.split("\n")
    try:
        inicio = lineas.index(ENCABEZADO_RESULTADOS)
    except ValueError:
        return texto_doc.rstrip("\n") + "\n\n" + bloque
    fin = next(
        (i for i in range(inicio + 1, len(lineas)) if lineas[i].startswith("## ")),
        len(lineas),
    )
    antes = "\n".join(lineas[:inicio])
    despues = "\n".join(lineas[fin:])
    nuevo = antes + "\n" + bloque
    if despues.strip():
        nuevo = nuevo.rstrip("\n") + "\n\n" + despues
    return nuevo.rstrip("\n") + "\n"


def _mostrar(ruta: Path) -> str:
    """Ruta relativa al repositorio si se puede, para imprimirla."""
    try:
        return ruta.relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return ruta.as_posix()


def main(argv: Sequence[str] | None = None) -> int:
    """Punto de entrada de la línea de comandos."""
    parser = argparse.ArgumentParser(
        description="Corre el catálogo de inyección contra el gateway de OpenClaw."
    )
    parser.add_argument("--simulado", action="store_true", help="sin red y sin escribir nada")
    parser.add_argument("--escribir-doc", action="store_true", help="pega la tabla en INYECCION.md")
    parser.add_argument("--catalogo", type=Path, default=RUTA_ATAQUES)
    args = parser.parse_args(argv)

    ataques = cargar_ataques(args.catalogo)
    config = cargar_config()
    if args.simulado:
        resultados = correr(ataques, responder_simulado)
        print("SIMULADO: no se habló con el gateway ni se escribió nada.\n")
        print(tabla_markdown(resultados))
        return 0

    token = os.environ.get(VARIABLE_TOKEN, "")
    if not token.strip():
        print(f"Falta {VARIABLE_TOKEN} en esta sesión de PowerShell.", file=sys.stderr)
        return 2
    try:
        responder = responder_gateway(config, token)
    except ValueError as error:
        print(str(error), file=sys.stderr)
        return 2

    resultados = correr(ataques, responder)
    ruta = guardar_informe(resultados, SALIDA_JSON)
    print(tabla_markdown(resultados))
    print(f"Informe: {_mostrar(ruta)}")
    if args.escribir_doc:
        bloque = bloque_resultados(resultados, modelo=config.modelo, fecha=date.today())
        doc = RUTA_DOC.read_text(encoding="utf-8")
        RUTA_DOC.write_text(escribir_resultados(doc, bloque), encoding="utf-8", newline="\n")
        print(f"Resultados pegados en {_mostrar(RUTA_DOC)}")
    return 0 if all(resultado.pasa for resultado in resultados) else 1


if __name__ == "__main__":
    sys.exit(main())
