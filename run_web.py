"""Lanza la app web (FastAPI + estáticos del frontend) y abre el navegador.

Un solo proceso. El frontend (web/dist) se sirve si fue compilado; mientras tanto
la API responde en /api y /docs muestra el contrato.
"""
from __future__ import annotations

import threading
import webbrowser

import uvicorn

from apu_tool import config

URL = "http://127.0.0.1:8000"


def _abrir() -> None:
    webbrowser.open(URL)


def main() -> None:
    config.ensure_dirs()
    threading.Timer(1.0, _abrir).start()
    uvicorn.run("apu_tool.servicio.app:app", host="127.0.0.1", port=8000, reload=False)


if __name__ == "__main__":
    raise SystemExit(main())
