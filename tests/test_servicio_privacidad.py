import json
from pathlib import Path


def test_fastapi_disponible():
    import fastapi  # noqa: F401
    import httpx    # noqa: F401


FORBIDDEN = {"precio", "costo", "valor", "margen", "price", "cost", "total",
             "precio_unitario", "precio_contractual", "fuente_precio"}


def test_servicio_no_importa_ai_assist():
    raiz = Path(__file__).resolve().parent.parent / "apu_tool" / "servicio"
    for py in raiz.glob("*.py"):
        assert "ai_assist" not in py.read_text(encoding="utf-8"), py.name


def test_estructura_persistida_no_tiene_dinero(tmp_path):
    from apu_tool.datos.almacen import Almacen
    from apu_tool.nucleo.models import Apu, ApuComponent, Insumo, LicitacionItem
    from apu_tool.servicio import corridas as svc
    alm = Almacen(precios_path=tmp_path / "p.db", apus_path=tmp_path / "a.db",
                  corridas_path=tmp_path / "c.db")
    alm.init_schema()
    alm.precios.insert_insumos([Insumo("100", "Concreto 3000 PSI", "M3",
                                       "CONCRETOS", 350000.0, "COSTO INTERNO")])
    alm.apus.insert_apus([Apu("A1", "Concreto clase D", "M3", "DIURNO", "ESTR")])
    alm.apus.insert_components([ApuComponent("A1", "DIURNO", "100",
                               "Concreto 3000 PSI", "M3", 1.05, 350000.0)])
    cid = svc.construir_corrida(alm, "lic.xlsx", [LicitacionItem(
        item="1", descripcion="Concreto clase D", unidad="M3", cantidad=10.0,
        precio_contractual=400000.0, shift="DIURNO")], "DIURNO", False)
    row = alm.corridas.get_item(cid, 0)
    for c in row.componentes:
        assert FORBIDDEN.isdisjoint(c.keys())
    for c in row.candidatos:
        assert FORBIDDEN.isdisjoint(c.keys())
