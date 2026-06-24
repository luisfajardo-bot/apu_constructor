from apu_tool.datos.almacen import Almacen
from apu_tool.nucleo.models import Insumo
from apu_tool.datos import seed


def test_dedup_por_codigo_y_nombre(tmp_path):
    """insert_insumos conserva dos insumos del mismo código si difieren en nombre,
    y colapsa los que son idénticos en (código, nombre)."""
    a = Almacen(tmp_path / "p.db", tmp_path / "a.db")
    a.reset()
    a.precios.insert_insumos([
        Insumo("4513", "DUCTO PVC D=3", "ML", "MAT", 16925, "PRECIO IDU"),
        Insumo("4513", "BASE GRANULAR", "M3", "MAT", 190300, "PRECIO IDU"),
        Insumo("4513", "ducto   pvc  d=3", "ML", "MAT", 99999, "OTRA"),  # idéntico normalizado -> se ignora
    ])
    cands = a.precios.get_candidatos("4513")
    assert len(cands) == 2
    ducto = [c for c in cands if c.nombre == "DUCTO PVC D=3"][0]
    assert ducto.precio == 16925   # ganó la primera ocurrencia, no la de 99999
