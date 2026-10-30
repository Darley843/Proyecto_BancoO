"""Pruebas sin red de la capa delgada scripts/scrape_empresa.py."""

from __future__ import annotations

import argparse
import importlib.util
import inspect
import sys
from pathlib import Path
from types import ModuleType

import pytest

from banco_occidente_corpus.config import PROJECT_ROOT, Config, load_config
from banco_occidente_corpus.live_capture import LiveCapture, LiveStage
from banco_occidente_corpus.net import BlockedError, Response, RobotsGuard
from banco_occidente_corpus.panel import Metric

RAIZ = Path(__file__).resolve().parents[1]
RUTA_SCRIPT = RAIZ / "scripts" / "scrape_empresa.py"


def _cargar_script() -> ModuleType:
    """Importa el script como módulo, sin ejecutar ``main``."""
    spec = importlib.util.spec_from_file_location("scrape_empresa", RUTA_SCRIPT)
    assert spec is not None and spec.loader is not None
    modulo = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = modulo
    spec.loader.exec_module(modulo)
    return modulo


scrape = _cargar_script()
BASE = load_config().site.base_url.rstrip("/")


def _config() -> Config:
    """Configuración real con el sitemap apuntando a la URL de prueba."""
    config = load_config()
    config.site.sitemap_url = f"{BASE}/sitemap.xml"
    config.crawl.max_sitemap_depth = 2
    return config


def _ok(texto: str, content_type: str = "text/html") -> Response:
    """Respuesta 200 sin red."""
    return Response(
        url="",
        status=200,
        text=texto,
        content=texto.encode(),
        content_type=content_type,
        elapsed=0.01,
    )


def _error(url: str, status: int) -> Response:
    """Respuesta de error HTTP sin red."""
    return Response(
        url=url,
        status=status,
        text="",
        content=b"",
        content_type="text/html",
        elapsed=0.01,
        error=f"HTTP {status}",
    )


def _urlset(urls: list[str]) -> str:
    """Construye un ``urlset`` de sitemap con las URLs indicadas."""
    locs = "".join(f"<url><loc>{url}</loc></url>" for url in urls)
    return f'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{locs}</urlset>'


def _sitemap_index(urls: list[str]) -> str:
    """Construye un ``sitemapindex`` con los sitemaps indicados."""
    locs = "".join(f"<sitemap><loc>{url}</loc></sitemap>" for url in urls)
    return (
        f'<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{locs}</sitemapindex>'
    )


class ClienteFalso:
    """Doble de ``HttpClient``: responde por URL y anota las peticiones."""

    def __init__(
        self,
        respuestas: dict[str, Response | Exception],
        *,
        por_defecto: Response | Exception | None = None,
    ) -> None:
        """Guarda las respuestas y el comportamiento ante una URL no prevista."""
        self.respuestas = respuestas
        self.por_defecto = por_defecto
        self.pedidas: list[str] = []
        self.cerrado = False
        self.delay = 1.5

    def get(self, url: str, *, accept: str | None = None) -> Response:
        """Devuelve la respuesta registrada o lanza la excepción registrada."""
        self.pedidas.append(url)
        valor = self.respuestas.get(url, self.por_defecto)
        if valor is None:
            raise AssertionError(f"URL inesperada en la prueba: {url}")
        if isinstance(valor, Exception):
            raise valor
        return valor

    def get_optional(self, url: str) -> Response | None:
        """Igual que ``get``, pero devuelve ``None`` ante ``BlockedError``."""
        try:
            return self.get(url)
        except BlockedError:
            return None

    def close(self) -> None:
        """Anota que el cliente se cerró."""
        self.cerrado = True

    def __enter__(self) -> ClienteFalso:
        """Soporta el uso con ``with``."""
        return self

    def __exit__(self, *exc: object) -> None:
        """Cierra el cliente al salir del bloque ``with``."""
        self.close()


def test_out_por_defecto_esta_fuera_de_data() -> None:
    """La demo escribe en .demo/ y nunca en el corpus real."""
    assert Path(".demo/scrape_empresa") == scrape.DEFAULT_OUT
    assert not scrape._dentro_de(scrape.DEFAULT_OUT, PROJECT_ROOT / "data")

    args = scrape.build_parser().parse_args([])
    assert args.out == Path(".demo/scrape_empresa")
    assert args.limit == 5
    assert args.delay == pytest.approx(1.5)


@pytest.mark.parametrize(
    "ruta",
    [
        "data",
        "data/raw",
        "data/gold/pages",
        "data/../data/x",
        "DATA/raw",
        str(PROJECT_ROOT / "data" / "pages"),
    ],
)
def test_rechaza_out_dentro_de_data(ruta: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """Cualquier variante de ruta dentro de data/ es un error de uso."""
    monkeypatch.chdir(PROJECT_ROOT)
    with pytest.raises(argparse.ArgumentTypeError, match="data/"):
        scrape._out_path(ruta)


def test_acepta_out_fuera_de_data(tmp_path: Path) -> None:
    """.demo/, build/ y una carpeta temporal son destinos válidos."""
    assert scrape._out_path(".demo/prueba") == Path(".demo/prueba")
    assert scrape._out_path("build/prueba") == Path("build/prueba")
    assert scrape._out_path(str(tmp_path / "salida")) == tmp_path / "salida"


def test_main_rechaza_out_de_data_antes_de_la_red(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """El rechazo ocurre al parsear, sin abrir cliente HTTP."""
    monkeypatch.chdir(PROJECT_ROOT)
    monkeypatch.setattr(
        scrape,
        "HttpClient",
        lambda *_args, **_kwargs: pytest.fail("no debe abrirse un cliente HTTP"),
    )

    with pytest.raises(SystemExit) as excinfo:
        scrape.main(["--out", "data/raw/x"])

    assert excinfo.value.code == 2


@pytest.mark.parametrize("valor", ["1.4", "0", "-2"])
def test_rechaza_delay_menor_al_minimo(valor: str) -> None:
    """Por debajo de 1,5 s es error de uso, igual que en el CLI del proyecto."""
    with pytest.raises(argparse.ArgumentTypeError, match="minimo es 1.5"):
        scrape._delay(valor)


@pytest.mark.parametrize("valor", ["1.5", "2", "10"])
def test_acepta_delay_suficiente(valor: str) -> None:
    """1,5 s y superiores son válidos."""
    assert scrape._delay(valor) == pytest.approx(float(valor))


@pytest.mark.parametrize("valor", ["0", "-1"])
def test_rechaza_limite_no_positivo(valor: str) -> None:
    """El tope de páginas debe ser al menos uno."""
    with pytest.raises(argparse.ArgumentTypeError, match="mayor o igual a 1"):
        scrape._limite(valor)


def test_descubre_hasta_el_limite_y_respeta_filtros_y_robots() -> None:
    """Se detiene al juntar --limit URLs y no lee los sitemaps restantes."""
    config = _config()
    robots = "User-agent: *\nDisallow: /privado\n"
    child1 = _urlset(
        [
            f"{BASE}/cuentas",
            f"{BASE}/privado/informe",
            f"{BASE}/documents/catalogo.pdf",
            f"{BASE}/login",
            "https://otro.example/pagina",
            f"{BASE}/tarjetas",
        ]
    )
    child2 = _urlset([f"{BASE}/no-debe-leerse"])
    indice = _sitemap_index([f"{BASE}/sitemap-1.xml", f"{BASE}/sitemap-2.xml"])
    cliente = ClienteFalso(
        {
            f"{BASE}/robots.txt": _ok(robots, "text/plain"),
            f"{BASE}/sitemap.xml": _ok(indice, "application/xml"),
            f"{BASE}/sitemap-1.xml": _ok(child1, "application/xml"),
            f"{BASE}/sitemap-2.xml": _ok(child2, "application/xml"),
        }
    )
    guard = RobotsGuard(cliente, config.site.user_agent)  # type: ignore[arg-type]

    seleccion = scrape.recolectar_urls(cliente, guard, config, 2)  # type: ignore[arg-type]

    assert seleccion.urls == (f"{BASE}/cuentas", f"{BASE}/tarjetas")
    assert seleccion.sitemaps == 2
    assert f"{BASE}/sitemap-2.xml" not in cliente.pedidas
    assert f"{BASE}/privado/informe" not in cliente.pedidas
    assert f"{BASE}/documents/catalogo.pdf" not in cliente.pedidas


def test_403_en_el_sitemap_detiene_el_descubrimiento() -> None:
    """Un 403 no se reintenta y no sugiere cambiar de red."""
    config = _config()
    cliente = ClienteFalso(
        {
            f"{BASE}/robots.txt": _ok("User-agent: *\nAllow: /\n", "text/plain"),
            f"{BASE}/sitemap.xml": _error(f"{BASE}/sitemap.xml", 403),
        }
    )
    guard = RobotsGuard(cliente, config.site.user_agent)  # type: ignore[arg-type]

    with pytest.raises(scrape.SitioBloqueado) as excinfo:
        scrape.recolectar_urls(cliente, guard, config, 5)  # type: ignore[arg-type]

    mensaje = str(excinfo.value)
    assert "403" in mensaje
    assert "residencial" not in mensaje
    assert "VPN" not in mensaje


def test_main_se_detiene_ante_429_sin_sugerir_otra_red(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Un 429 persistente termina con el mensaje neutro del proyecto."""
    bloqueo = BlockedError(
        "respondio HTTP 429 tras 3 intentos. Prueba desde una conexion residencial."
    )
    cliente = ClienteFalso({}, por_defecto=bloqueo)
    monkeypatch.setattr(scrape, "HttpClient", lambda *_args, **_kwargs: cliente)

    codigo = scrape.main(["--limit", "1", "--out", str(tmp_path / "salida")])

    assert codigo == 3
    salida = capsys.readouterr().out
    assert "403/429" in salida
    assert "residencial" not in salida
    assert "VPN" not in salida


def test_main_imprime_el_resumen_y_la_ruta_de_gold(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Al terminar muestra las etapas y una página Gold generada."""
    url = f"{BASE}/cuentas"
    page = tmp_path / "salida/gold/pages/cuentas.md"
    page.parent.mkdir(parents=True)
    page.write_text("---\nfuente: demo\n---\n\nContenido.\n", encoding="utf-8")
    captura = LiveCapture(
        workdir=tmp_path / "salida",
        urls=(url,),
        stages=(
            LiveStage(
                key="gold",
                title="Enriquecer Gold",
                detail="1 documento con frontmatter + corpus.jsonl",
                metrics=(Metric("Documentos", "1"),),
            ),
        ),
        corpus=({"id": "cuentas"},),
        page_path=page,
    )
    cliente = ClienteFalso({})
    monkeypatch.setattr(scrape, "HttpClient", lambda *_args, **_kwargs: cliente)
    monkeypatch.setattr(
        scrape,
        "recolectar_urls",
        lambda *_args, **_kwargs: scrape.Seleccion((url,), 1),
    )
    monkeypatch.setattr(scrape, "run_capture", lambda *_args, **_kwargs: captura)

    codigo = scrape.main(["--limit", "1", "--out", str(tmp_path / "salida")])

    assert codigo == 0
    salida = capsys.readouterr().out
    assert "Resumen por etapa" in salida
    assert "Enriquecer Gold" in salida
    assert f"Gold: {page}" in salida


def test_script_sin_cabecera_pep723() -> None:
    """El script se ejecuta con el entorno del proyecto, sin metadatos PEP 723."""
    texto = RUTA_SCRIPT.read_text(encoding="utf-8")
    assert not texto.startswith("# /// script")


def test_funciones_y_clases_documentadas() -> None:
    """Toda función y clase pública del script tiene docstring."""
    for name, obj in inspect.getmembers(scrape):
        if getattr(obj, "__module__", None) != scrape.__name__:
            continue
        if inspect.isfunction(obj) or inspect.isclass(obj):
            assert inspect.getdoc(obj), name


def test_dobles_de_prueba_documentados() -> None:
    """Los métodos públicos del doble de prueba también tienen docstring."""
    for name, obj in inspect.getmembers(ClienteFalso, inspect.isfunction):
        assert inspect.getdoc(obj), f"ClienteFalso.{name}"
