import asyncio

from apu_tool.datos.almacen import Almacen
from apu_tool.servicio.app import create_app
from apu_tool.servicio.limites import LimiteSubida
from fastapi.testclient import TestClient


def _app(tmp_path):
    alm = Almacen(precios_path=tmp_path / "p.db", apus_path=tmp_path / "a.db",
                  corridas_path=tmp_path / "c.db")
    alm.init_schema()
    return create_app(almacen=alm)


def test_subida_sobre_limite_da_413(tmp_path, monkeypatch):
    monkeypatch.setenv("APU_MAX_UPLOAD_MB", "1")   # límite 1 MB para el test
    cli = TestClient(_app(tmp_path))
    grande = b"x" * (2 * 1024 * 1024)              # 2 MB > 1 MB
    r = cli.post("/api/insumos/importar/preview",
                 files={"archivo": ("grande.xlsx", grande,
                                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
    assert r.status_code == 413, r.text


class _Req:
    def __init__(self, headers, method="POST", path="/api/insumos/importar/preview"):
        self.headers = headers
        self.method = method
        self.url = type("U", (), {"path": path})()


def _dispatch(headers, method="POST", path="/api/insumos/importar/preview"):
    mw = LimiteSubida(app=None, max_bytes=15 * 1024 * 1024)
    async def call_next(_req):
        return "PASO"
    return asyncio.run(mw.dispatch(_Req(headers, method, path), call_next))


def test_post_sin_content_length_da_411():
    r = _dispatch({})   # POST a /api sin Content-Length
    assert getattr(r, "status_code", None) == 411


def test_get_sin_content_length_pasa():
    assert _dispatch({}, method="GET", path="/api/corridas") == "PASO"


def test_post_con_content_length_pasa():
    assert _dispatch({"content-length": "100"}) == "PASO"
