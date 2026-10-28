"""Cliente HTTP con reintentos, backoff y cortesia con el servidor."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

import httpx

from .config import Config

RETRY_STATUS = {408, 425, 429, 500, 502, 503, 504}

#: Minimo de cortesia entre peticiones. robots.txt del banco no declara
#: Crawl-delay: el valor es una decision del proyecto y no se puede bajar.
MIN_DELAY_SECONDS = 1.5


class BlockedError(RuntimeError):
    """El sitio rechaza la peticion (403/429) de forma persistente."""


class FaltaContacto(ValueError):
    """``site.contact`` esta vacio: no se puede enviar el header ``From``."""


@dataclass(slots=True)
class Response:
    """Respuesta HTTP simplificada que devuelve ``HttpClient.get``."""

    url: str
    status: int
    text: str
    content_type: str
    elapsed: float
    error: str | None = None
    content: bytes = b""

    @property
    def ok(self) -> bool:
        """True si la respuesta trae contenido util (2xx y sin error)."""
        return 200 <= self.status < 300 and self.error is None


class HttpClient:
    """Envoltorio de httpx que aplica UA, timeout, reintentos y pausas."""

    def __init__(self, config: Config, *, delay: float | None = None) -> None:
        """Crea el cliente aplicando UA, `From`, timeout y el minimo de cortesia.

        Falla con ``FaltaContacto`` si ``site.contact`` esta vacio: toda
        peticion del proyecto debe identificarse con el header ``From``.
        """
        if not config.site.contact.strip():
            raise FaltaContacto(
                "config/site.toml necesita site.contact (correo academico) para el "
                "header From; el proyecto no hace peticiones sin identificarse."
            )
        self.config = config
        requested = config.crawl.delay_seconds if delay is None else delay
        # El minimo se impone aqui, en el unico punto por el que pasa toda
        # peticion HTTP: ni el CLI ni una config relajada pueden bajarlo.
        self.delay = max(MIN_DELAY_SECONDS, float(requested))
        self._requests = 0
        self._last_request = 0.0
        self.client = httpx.Client(
            http2=True,
            follow_redirects=True,
            timeout=config.crawl.timeout_seconds,
            headers=self._headers(),
        )

    def _headers(self) -> dict[str, str]:
        """Headers de un navegador real + identificacion academica en `From`."""
        headers = {
            "User-Agent": self.config.site.user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": f"{self.config.site.language},es;q=0.9,en;q=0.5",
            "Accept-Encoding": "gzip, deflate, br",
        }
        headers["From"] = self.config.site.contact.strip()
        return headers

    def __enter__(self) -> HttpClient:
        """Permite usar el cliente con ``with``."""
        return self

    def __exit__(self, *exc: object) -> None:
        """Cierra la conexion al salir del bloque ``with``."""
        self.close()

    def close(self) -> None:
        """Cierra el cliente httpx subyacente."""
        self.client.close()

    def _wait(self) -> None:
        """Aplica la cortesia: nunca dos peticiones seguidas sin pausa."""
        if self._last_request:
            missing = self.delay - (time.monotonic() - self._last_request)
            if missing > 0:
                time.sleep(missing)
        self._requests += 1
        every = self.config.crawl.pause_every
        if every and self._requests % every == 0:
            time.sleep(self.config.crawl.pause_seconds)

    def get(self, url: str, *, accept: str | None = None) -> Response:
        """Descarga ``url`` respetando la cortesia, con reintentos y backoff.

        Devuelve un ``Response`` (con ``error`` para 4xx) o lanza
        ``BlockedError`` si tras los reintentos el sitio sigue rechazando.
        """
        headers = {"Accept": accept} if accept else None
        last_error = "sin intentos"
        attempts = max(1, self.config.crawl.max_retries)

        for attempt in range(1, attempts + 1):
            self._wait()
            started = time.monotonic()
            try:
                response = self.client.get(url, headers=headers)
            except httpx.HTTPError as exc:  # red, DNS, timeout
                # Tambien cuenta como peticion: la pausa siguiente se mide desde aqui.
                self._last_request = time.monotonic()
                last_error = f"{type(exc).__name__}: {exc}"
                response = None
            else:
                self._last_request = time.monotonic()
                elapsed = self._last_request - started
                if response.status_code in RETRY_STATUS:
                    last_error = f"HTTP {response.status_code}"
                elif response.status_code >= 400:
                    return Response(
                        url=str(response.url),
                        status=response.status_code,
                        text="",
                        content_type=response.headers.get("content-type", ""),
                        elapsed=elapsed,
                        error=f"HTTP {response.status_code}",
                    )
                else:
                    return Response(
                        url=str(response.url),
                        status=response.status_code,
                        text=response.text,
                        content=response.content,
                        content_type=response.headers.get("content-type", ""),
                        elapsed=elapsed,
                    )

            if attempt < attempts:
                time.sleep(min(2**attempt, 20))

        raise BlockedError(
            f"{url} respondio {last_error} tras {attempts} intentos. "
            "Si es 403 persistente, el sitio esta bloqueando la red actual "
            "(VPN, datacenter o WAF de CloudFront): prueba desde una conexion "
            "residencial colombiana. El proyecto no usa navegadores para "
            "sortear el WAF."
        )

    def get_optional(self, url: str) -> Response | None:
        """Igual que get(), pero devuelve None en vez de lanzar BlockedError."""
        try:
            return self.get(url)
        except BlockedError:
            return None


def build_client(config: Config, *, delay: float | None = None) -> HttpClient:
    """Crea un ``HttpClient`` para el pipeline (atajo de ``HttpClient(config)``)."""
    return HttpClient(config, delay=delay)


def describe_status(status: int) -> str:
    """Traduce un codigo HTTP a una etiqueta legible para los reportes."""
    return {
        200: "ok",
        301: "redirigido",
        403: "bloqueado",
        404: "no existe",
        429: "rate limit",
    }.get(status, f"HTTP {status}")


def response_headers(response: Any) -> dict[str, str]:  # pragma: no cover - auxiliar
    """Headers de una respuesta httpx como ``dict`` (vacio si no tiene)."""
    return dict(getattr(response, "headers", {}) or {})


class RobotsGuard:
    """Consulta ``robots.txt`` por host antes de descargar una URL.

    Lee el ``robots.txt`` de cada host una sola vez con el mismo ``HttpClient``
    (cortesia, UA y ``From`` incluidos). Si no se puede leer, no bloquea: la
    norma de robots trata un archivo ausente como "todo permitido".
    """

    def __init__(self, client: HttpClient, user_agent: str) -> None:
        """Guarda el cliente y el User-Agent con el que se evaluan las reglas."""
        self.client = client
        self.user_agent = user_agent
        self._parsers: dict[str, RobotFileParser | None] = {}

    def _parser(self, url: str) -> RobotFileParser | None:
        """Parser del host de ``url``, descargado la primera vez que se pide."""
        parts = urlsplit(url)
        host = f"{parts.scheme}://{parts.netloc}".lower()
        if host not in self._parsers:
            response = self.client.get_optional(f"{host}/robots.txt")
            parser: RobotFileParser | None = None
            if response is not None and response.ok:
                parser = RobotFileParser()
                parser.parse(response.text.splitlines())
            self._parsers[host] = parser
        return self._parsers[host]

    def allowed(self, url: str) -> bool:
        """True si ``robots.txt`` del host permite descargar ``url``."""
        parser = self._parser(url)
        return parser is None or parser.can_fetch(self.user_agent, url)
