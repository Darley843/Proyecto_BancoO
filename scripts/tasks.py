"""Tareas auxiliares del Makefile, en Python puro (funciona en Windows y Unix).

    uv run python scripts/tasks.py help
    uv run python scripts/tasks.py clean-env
    uv run python scripts/tasks.py repo
    uv run python scripts/tasks.py constitution
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAKEFILE = ROOT / "makefile"
API = "https://api.github.com"


# --------------------------------------------------------------------------- help


def cmd_help(_: argparse.Namespace) -> int:
    if not MAKEFILE.exists():
        print("No encuentro el makefile", file=sys.stderr)
        return 1

    pattern = re.compile(r"^([a-zA-Z0-9_-]+):.*?##\s*(.+)$")
    rows: list[tuple[str, str]] = []
    for line in MAKEFILE.read_text(encoding="utf-8").splitlines():
        match = pattern.match(line)
        if match:
            rows.append((match.group(1), match.group(2)))

    width = max((len(name) for name, _ in rows), default=10)
    print()
    print("  Corpus web - Banco de Occidente")
    print("  " + "-" * 52)
    for name, description in rows:
        print(f"  {name:<{width}}   {description}")
    print()
    print("  Ejemplo: make all LIMIT=100")
    print()
    return 0


# --------------------------------------------------------------------------- entorno


def cmd_clean_env(_: argparse.Namespace) -> int:
    targets = [".venv", ".pytest_cache", ".ruff_cache", ".demo"]
    for name in targets:
        path = ROOT / name
        if path.is_dir():
            shutil.rmtree(path, ignore_errors=True)
            print(f"borrado {name}")
    for path in ROOT.rglob("__pycache__"):
        shutil.rmtree(path, ignore_errors=True)
    print("entorno limpio. Recrea con: make init")
    return 0


# --------------------------------------------------------------------------- git


def _git(*args: str) -> int:
    result = subprocess.run(["git", *args], cwd=ROOT, check=False)  # noqa: S603, S607
    return result.returncode


def _token() -> str | None:
    for name in ("GITHUB_TOKEN", "GH_TOKEN"):
        value = os.getenv(name)
        if value:
            return value
    return None


def _api(method: str, path: str, token: str, payload: dict | None = None, *, raw: bool = False):
    data = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(f"{API}{path}", data=data, method=method)
    request.add_header("Authorization", f"Bearer {token}")
    request.add_header("Accept", "application/vnd.github.raw" if raw else "application/vnd.github+json")
    request.add_header("X-GitHub-Api-Version", "2022-11-28")
    if data:
        request.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310
        body = response.read()
        return response.status, body


def cmd_identity(args: argparse.Namespace) -> int:
    _git("config", "user.name", args.user)
    _git("config", "user.email", args.email)
    name = subprocess.run(
        ["git", "config", "user.name"], cwd=ROOT, capture_output=True, text=True, check=False
    ).stdout.strip()
    email = subprocess.run(
        ["git", "config", "user.email"], cwd=ROOT, capture_output=True, text=True, check=False
    ).stdout.strip()
    print(f"  user.name  = {name}")
    print(f"  user.email = {email}")
    return 0


def cmd_repo(args: argparse.Namespace) -> int:
    token = _token()
    if not token:
        print("Falta GITHUB_TOKEN (o GH_TOKEN) en el entorno.", file=sys.stderr)
        print("Crea un PAT con scope 'repo' y exportalo antes de ejecutar.", file=sys.stderr)
        return 2

    payload = {
        "name": args.repo,
        "private": True,
        "description": "Corpus web de Banco de Occidente: pipeline Medallion con uv",
        "has_issues": True,
        "has_wiki": False,
    }
    try:
        status, body = _api("POST", "/user/repos", token, payload)
        info = json.loads(body)
        print(f"Repositorio creado: {info.get('html_url')}")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")
        if exc.code == 422 and "already exists" in detail:
            print(f"El repositorio {args.repo} ya existe; se reutiliza.")
        else:
            print(f"GitHub respondio {exc.code}: {detail}", file=sys.stderr)
            return 1

    try:
        status, body = _api("GET", "/user", token)
        login = json.loads(body).get("login", args.owner)
    except urllib.error.HTTPError:
        login = args.owner

    remote = f"https://github.com/{login}/{args.repo}.git"
    _git("remote", "remove", "origin")
    _git("remote", "add", "origin", remote)
    print(f"Remoto: {remote}")
    print("Siguiente: make push")
    return 0


def cmd_constitution(args: argparse.Namespace) -> int:
    token = _token()
    if not token:
        print("Falta GITHUB_TOKEN (o GH_TOKEN) en el entorno.", file=sys.stderr)
        return 2

    candidates = [args.file, f"{args.file} (4).md", "CONSTITUTION.md"]
    for name in candidates:
        path = f"/repos/{args.owner}/{args.repo}/contents/{urllib.parse.quote(name)}"
        try:
            status, body = _api("GET", path, token, raw=True)
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                continue
            print(f"GitHub respondio {exc.code}", file=sys.stderr)
            return 1
        if status == 200 and body:
            (ROOT / "CONSTITUTION.md").write_bytes(body)
            print(f"Guardado en CONSTITUTION.md ({len(body)} bytes, origen: {name})")
            return 0

    print(
        f"No encontre la constitucion en {args.owner}/{args.repo}. "
        "Verifica el nombre del archivo o pasalo con --file.",
        file=sys.stderr,
    )
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("help", help="lista los targets del makefile").set_defaults(func=cmd_help)
    sub.add_parser("clean-env", help="borra .venv y caches").set_defaults(func=cmd_clean_env)

    identity = sub.add_parser("identity", help="configura name/email de git")
    identity.add_argument("--user", default="Darley843")
    identity.add_argument("--email", default="darley.idarraga@uao.edu.co")
    identity.set_defaults(func=cmd_identity)

    repo = sub.add_parser("repo", help="crea el repositorio en GitHub")
    repo.add_argument("--repo", default="Proyecto_BancoO")
    repo.add_argument("--owner", default="Darley843")
    repo.set_defaults(func=cmd_repo)

    constitution = sub.add_parser("constitution", help="descarga la constitucion del repo")
    constitution.add_argument("--repo", default="Proyecto_BancoO")
    constitution.add_argument("--owner", default="Darley843")
    constitution.add_argument("--file", default="CONSTITUTION.md")
    constitution.set_defaults(func=cmd_constitution)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
