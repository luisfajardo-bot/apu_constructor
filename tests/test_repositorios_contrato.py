from apu_tool.datos.repositorio import RepositorioPrecios, RepositorioApus

def test_protocols_existen():
    # son Protocols con métodos esperados
    assert hasattr(RepositorioPrecios, "get_insumo")
    assert hasattr(RepositorioPrecios, "set_precio")
    assert hasattr(RepositorioApus, "get_components")
    assert hasattr(RepositorioApus, "get_depriced_apu")
