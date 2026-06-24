"""Lanza la app web (FastAPI + estáticos del frontend) y abre el navegador.

Un solo proceso. Si el frontend está compilado (web/dist), se sirve en la raíz;
mientras tanto el navegador abre /docs (el contrato de la API).
"""
from __future__ import annotations

import threading
import webbrowser

import uvicorn

from apu_tool import config

HOST = "127.0.0.1"
PORT = 8000
WEB_DIST = config.PROJECT_ROOT / "web" / "dist"


def _url() -> str:
    base = f"http://{HOST}:{PORT}"
    # Sin frontend compilado todavía no hay página en la raíz: abrir el contrato.
    return base + ("/" if WEB_DIST.exists() else "/docs")


def _abrir() -> None:
    webbrowser.open(_url())


def main() -> None:
    config.ensure_dirs()
    print(f"Armador de APUs — web en http://{HOST}:{PORT}")
    print(f"  Contrato de la API (Swagger): http://{HOST}:{PORT}/docs")
    if not WEB_DIST.exists():
        print("  (Frontend aún no compilado: la raíz / responde 404 hasta que exista web/dist.)")
    threading.Timer(1.0, _abrir).start()
    uvicorn.run("apu_tool.servicio.app:app", host=HOST, port=PORT, reload=False)


if __name__ == "__main__":
    raise SystemExit(main())
