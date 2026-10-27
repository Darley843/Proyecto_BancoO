"""Videos de YouTube: descubrimiento, subtitulos y transcripcion a Gold."""

from __future__ import annotations

import html
import json
import logging
import re
from pathlib import Path
from urllib.parse import parse_qs, urljoin, urlsplit

import yaml
from bs4 import BeautifulSoup

from .config import Config
from .utils import estimate_tokens, page_slug, read_jsonl, sha256_text, utc_now, write_jsonl

log = logging.getLogger(__name__)

CHANNEL_URL = "https://www.youtube.com/@BancodeOccidenteCol/videos"
SUBTITLE_LANGS = ["es.*", "es"]


def _video_id(url: str) -> str | None:
    parts = urlsplit(url)
    if "youtu.be" in parts.netloc:
        return parts.path.strip("/").split("/")[0] or None
    if "youtube.com" in parts.netloc:
        if parts.path.startswith("/watch"):
            value = parse_qs(parts.query).get("v")
            return value[0] if value else None
        if parts.path.startswith("/shorts/"):
            return parts.path.split("/")[2] or None
    return None


def _ytdlp():
    try:
        from yt_dlp import YoutubeDL
    except ImportError as exc:  # pragma: no cover - extra opcional
        raise RuntimeError("yt-dlp no esta instalado. Ejecuta: uv sync --extra media") from exc
    return YoutubeDL


def discover_videos(config: Config, *, channel_limit: int = 30) -> list[dict]:
    """Une los videos enlazados en el sitio con los del canal oficial."""
    base = config.site.base_url.rstrip("/") + "/"
    found: dict[str, dict] = {}

    for html_path in sorted(config.paths.raw_html.glob("*.html")):
        soup = BeautifulSoup(html_path.read_text(encoding="utf-8", errors="replace"), "lxml")
        for anchor in soup.select("a[href]"):
            href = anchor.get("href")
            if not isinstance(href, str) or not href:
                continue
            url = urljoin(base, href)
            video_id = _video_id(url)
            if not video_id:
                continue
            title = " ".join(anchor.get_text(" ", strip=True).split())[:160]
            found.setdefault(
                video_id,
                {
                    "id": video_id,
                    "url": f"https://www.youtube.com/watch?v={video_id}",
                    "titulo": title or video_id,
                    "fuente": "sitio",
                    "canal": None,
                    "duracion": None,
                    "upload_date": None,
                },
            )

    YoutubeDL = _ytdlp()
    options = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "extract_flat": "in_playlist",
        "playlistend": channel_limit,
    }
    try:
        with YoutubeDL(options) as ydl:
            info = ydl.extract_info(CHANNEL_URL, download=False)
        for entry in (info or {}).get("entries", []) or []:
            video_id = entry.get("id")
            if not video_id:
                continue
            found.setdefault(
                video_id,
                {
                    "id": video_id,
                    "url": f"https://www.youtube.com/watch?v={video_id}",
                    "titulo": entry.get("title") or video_id,
                    "fuente": "canal",
                    "canal": entry.get("channel") or "Banco de Occidente",
                    "duracion": entry.get("duration"),
                    "upload_date": None,
                },
            )
    except Exception as exc:  # noqa: BLE001 - YouTube puede fallar sin bloquear el resto
        log.warning("No se pudo listar el canal: %s", exc)

    rows = sorted(found.values(), key=lambda row: row["titulo"].lower())
    write_jsonl(config.paths.videos_urls, rows)
    return rows


def _find_subtitle(directory: Path, video_id: str) -> Path | None:
    candidates = sorted(directory.glob(f"{video_id}*.vtt"))
    return candidates[0] if candidates else None


def fetch_videos(
    config: Config, *, limit: int | None = None, force: bool = False
) -> dict[str, int]:
    """Descarga metadatos y subtitulos en espanol (sin bajar el video)."""
    rows = list(read_jsonl(config.paths.videos_urls))
    if not rows:
        rows = discover_videos(config)
    if limit:
        rows = rows[:limit]

    cached = {
        row.get("id"): row
        for row in read_jsonl(config.paths.videos_capture)
        if row.get("status") == 200
    }
    stats = {"ok": 0, "cached": 0, "failed": 0, "sin_subtitulos": 0}
    config.paths.videos_raw.mkdir(parents=True, exist_ok=True)
    YoutubeDL = _ytdlp()

    with config.paths.videos_capture.open("a", encoding="utf-8", newline="\n") as out:

        def save(record: dict) -> None:
            """Anexa un registro de captura y lo escribe de inmediato."""
            out.write(json.dumps(record, ensure_ascii=False) + "\n")
            out.flush()

        options = {
            "quiet": True,
            "no_warnings": True,
            "skip_download": True,
            "writesubtitles": True,
            "writeautomaticsub": True,
            "subtitleslangs": SUBTITLE_LANGS,
            "subtitlesformat": "vtt",
            "writeinfojson": True,
            "outtmpl": str(config.paths.videos_raw / "%(id)s.%(ext)s"),
        }

        for index, row in enumerate(rows, start=1):
            video_id = row["id"]
            if video_id in cached and not force:
                stats["cached"] += 1
                continue
            try:
                with YoutubeDL(options) as ydl:
                    info = ydl.extract_info(row["url"], download=True) or {}
            except Exception as exc:  # noqa: BLE001 - un video roto no detiene el lote
                stats["failed"] += 1
                save({**row, "status": 0, "error": str(exc)[:300], "fecha": utc_now()})
                log.warning("[%d] %s -> %s", index, video_id, str(exc)[:120])
                continue

            subtitle = _find_subtitle(config.paths.videos_raw, video_id)
            record = {
                **row,
                "titulo": info.get("title") or row.get("titulo"),
                "canal": info.get("channel") or row.get("canal"),
                "duracion": info.get("duration") or row.get("duracion"),
                "upload_date": info.get("upload_date") or row.get("upload_date"),
                "status": 200,
                "subs": subtitle.name if subtitle else None,
                "fecha": utc_now(),
                "error": None,
            }
            save(record)
            stats["ok"] += 1
            if subtitle is None:
                stats["sin_subtitulos"] += 1
                log.info("[%d] %s sin subtitulos", index, video_id)
            else:
                log.info("[%d] %s (%s)", index, video_id, subtitle.name)

    return stats


def parse_vtt(text: str) -> str:
    """Convierte VTT en parrafos legibles, sin timestamps ni duplicados."""
    lines: list[str] = []
    recent: list[str] = []
    for line in text.splitlines():
        value = line.strip()
        if (
            not value
            or value == "WEBVTT"
            or value.startswith(("NOTE", "Kind:", "Language:", "STYLE"))
        ):
            continue
        if "-->" in value or re.fullmatch(r"\d+", value):
            continue
        value = re.sub(r"<[^>]+>", "", value)
        value = html.unescape(value).strip()
        if not value or value in recent[-3:]:
            continue
        recent.append(value)
        lines.append(value)

    paragraphs: list[str] = []
    for start in range(0, len(lines), 12):
        paragraph = " ".join(lines[start : start + 12]).strip()
        if paragraph:
            paragraphs.append(paragraph)
    return "\n\n".join(paragraphs)


def extract_videos(config: Config) -> list[dict]:
    """Subtitulos -> Markdown Gold con metadatos + indice videos.jsonl."""
    captured = [row for row in read_jsonl(config.paths.videos_capture) if row.get("status") == 200]
    config.paths.videos_gold.mkdir(parents=True, exist_ok=True)
    index: list[dict] = []
    skipped = 0

    for row in captured:
        subtitle_name = row.get("subs")
        if not subtitle_name:
            skipped += 1
            continue
        subtitle = config.paths.videos_raw / subtitle_name
        if not subtitle.exists():
            skipped += 1
            continue

        body = parse_vtt(subtitle.read_text(encoding="utf-8", errors="replace"))
        if len(body) < 300:
            skipped += 1
            continue

        title = row.get("titulo") or row["id"]
        upload = str(row.get("upload_date") or "")
        date = f"{upload[:4]}-{upload[4:6]}-{upload[6:8]}" if len(upload) == 8 else None
        digest = sha256_text(body)
        slug = page_slug(row["url"], title)
        meta = {
            "fuente": row["url"],
            "titulo": title,
            "tipo": "video",
            "seccion": "presencia",
            "empresa": config.site.name,
            "fecha_captura": utc_now()[:10],
            "fecha_documento": date,
            "duracion_seg": row.get("duracion"),
            "idioma": "es",
            "tokens": estimate_tokens(body),
            "hash": digest[:8],
            "palabras": len(body.split()),
            "metodo": "yt-dlp",
            "canal": row.get("canal"),
        }
        document = (
            "---\n"
            + yaml.safe_dump(meta, allow_unicode=True, sort_keys=False, width=100).strip()
            + f"\n---\n\n# {title}\n\n{body}\n"
        )
        target = config.paths.videos_gold / f"{slug}.md"
        target.write_text(document, encoding="utf-8", newline="\n")
        index.append(
            {
                "id": slug,
                "titulo": title,
                "tipo": "video",
                "video_id": row["id"],
                "fuente": row["url"],
                "canal": row.get("canal"),
                "fecha_documento": date,
                "duracion_seg": row.get("duracion"),
                "archivo": target.relative_to(config.paths.root).as_posix(),
                "tokens": meta["tokens"],
                "idioma": "es",
                "hash": meta["hash"],
            }
        )

    write_jsonl(config.paths.videos_index, index)
    log.info("Videos Gold: %d (%d sin subtitulos)", len(index), skipped)
    return index
