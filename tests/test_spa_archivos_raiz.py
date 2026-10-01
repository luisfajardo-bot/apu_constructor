"""La ruta comodín de la SPA sirve los archivos reales de la raíz de web/dist.

Antes devolvía index.html para TODO lo que no fuera /api ni /assets, incluido
/favicon.ico: el navegador recibía HTML en vez de la imagen y mostraba el ícono por
defecto. Ningún favicon se vio nunca en producción.
"""
from fastapi.testclient import TestClient

from apu_tool.datos.almacen import Almacen
from apu_tool.servicio import app as app_module


def _cliente(tmp_path, monkeypatch):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<html>app</html>", encoding="utf-8")
    (dist / "favicon-32.png").write_bytes(b"\x89PNG\r\n\x1a\nfalso")
    (tmp_path / "secreto.txt").write_text("contenido secreto", encoding="utf-8")
    monkeypatch.setattr(app_module, "WEB_DIST", dist)
    alm = Almacen(precios_path=tmp_path / "p.db", apus_path=tmp_path / "a.db",
                  corridas_path=tmp_path / "c.db")
    alm.init_schema()
    return TestClient(app_module.create_app(almacen=alm))


def test_un_archivo_real_de_dist_se_sirve_como_archivo(tmp_path, monkeypatch):
    r = _cliente(tmp_path, monkeypatch).get("/favicon-32.png")
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/png"
    assert r.content.startswith(b"\x89PNG")


def test_una_ruta_de_la_app_sigue_dando_index(tmp_path, monkeypatch):
    cli = _cliente(tmp_path, monkeypatch)
    for ruta in ("/", "/corridas", "/corridas/12", "/no-existe.png"):
        r = cli.get(ruta)
        assert r.status_code == 200 and r.text == "<html>app</html>", ruta


def test_no_se_sale_de_dist(tmp_path, monkeypatch):
    cli = _cliente(tmp_path, monkeypatch)
    for ruta in ("/../secreto.txt", "/%2e%2e/secreto.txt", "/..%2fsecreto.txt"):
        assert "secreto" not in cli.get(ruta).text, ruta
