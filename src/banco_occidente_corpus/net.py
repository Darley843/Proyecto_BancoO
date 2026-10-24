"""Cliente HTTP con reintentos, backoff y cortesia con el servidor."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import httpx

from .config import Config

RETRY_STATUS = {408, 425, 429, 500, 502, 503, 504}


class BlockedError(RuntimeError):
    """El sitio rechaza la peticion (403/429) de forma persistente."""


@dataclass(slots=True)
class Response:
    url: str
    status: int
    text: str
    content_type: str
    elapsed: float
    error: str | None = None
    content: bytes = b""

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300 and self.error is None


class HttpClient:
    """Envoltorio de httpx que aplica UA, timeout, reintentos y pausas."""

    def __init__(self, config: Config, *, delay: float | None = None) -> None:
        self.config = config
        self.delay = config.crawl.delay_seconds if delay is None else delay
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
        if self.config.site.contact:
            headers["From"] = self.config.site.contact
        return headers

    def __enter__(self) -> HttpClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
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
        headers = {"Accept": accept} if accept else None
        last_error = "sin intentos"
        attempts = max(1, self.config.crawl.max_retries)

        for attempt in range(1, attempts + 1):
            self._wait()
            started = time.monotonic()
            try:
                response = self.client.get(url, headers=headers)
            except httpx.HTTPError as exc:  # red, DNS, timeout
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
            "residencial colombiana o usa --browser."
        )

    def get_optional(self, url: str) -> Response | None:
        """Igual que get(), pero devuelve None en vez de lanzar BlockedError."""
        try:
            return self.get(url)
        except BlockedError:
            return None


def build_client(config: Config, *, delay: float | None = None) -> HttpClient:
    return HttpClient(config, delay=delay)


def fetch_with_browser(url: str, config: Config) -> Response:
    """Fallback con Chromium real para paginas que exigen JavaScript."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:  # pragma: no cover - extra opcional
        raise RuntimeError(
            "Playwright no esta instalado. Ejecuta: uv sync --extra browser && "
            "uv run playwright install chromium"
        ) from exc

    started = time.monotonic()
    with sync_playwright() as p:  # pragma: no cover - requiere navegador
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            locale="es-CO",
            user_agent=config.site.user_agent,
            viewport={"width": 1366, "height": 900},
        )
        page = context.new_page()
        try:
            response = page.goto(url, wait_until="networkidle", timeout=45_000)
            status = response.status if response else 0
            html = page.content()
            return Response(
                url=page.url,
                status=status,
                text=html,
                content_type="text/html",
                elapsed=time.monotonic() - started,
                error=None if status < 400 else f"HTTP {status}",
            )
        except Exception as exc:  # noqa: BLE001 - se reporta al llamador
            return Response(
                url=url,
                status=0,
                text="",
                content_type="",
                elapsed=time.monotonic() - started,
                error=f"{type(exc).__name__}: {exc}",
            )
        finally:
            context.close()
            browser.close()


def describe_status(status: int) -> str:
    return {
        200: "ok",
        301: "redirigido",
        403: "bloqueado",
        404: "no existe",
        429: "rate limit",
    }.get(status, f"HTTP {status}")


def response_headers(response: Any) -> dict[str, str]:  # pragma: no cover - auxiliar
    return dict(getattr(response, "headers", {}) or {})
