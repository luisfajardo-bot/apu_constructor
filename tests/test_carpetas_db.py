from apu_tool.nucleo.models import Carpeta, CorridaMeta


def test_carpeta_dataclass_defaults():
    c = Carpeta(id=None, nombre="Calle 13", parent_id=None, creada_en="2026-07-09")
    assert c.parent_id is None
    assert c.creado_por is None


def test_corrida_meta_tiene_carpeta_id():
    m = CorridaMeta(id=None, creada_en="2026-07-09", archivo="x.xlsx",
                    turno_def="DIURNO", use_ai=False, estado="armando")
    assert m.carpeta_id is None
