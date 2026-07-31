import os
import pytest

pytestmark = pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"),
    reason="sin TEST_DATABASE_URL")


@pytest.fixture()
def precios_pg():
    from apu_tool import config
    from apu_tool.datos.pg.conexion import Conexion, ejecutar_script
    from apu_tool.datos.pg.precios_pg import PreciosPg
    cx = Conexion(os.environ["TEST_DATABASE_URL"])
    with cx.connection() as conn:
        conn.execute("DROP SCHEMA IF EXISTS precios CASCADE")
        ejecutar_script(conn, (config.PROJECT_ROOT / "db" / "pg" / "precios.sql").read_text("utf-8"))
    repo = PreciosPg(cx)
    yield repo
    cx.cerrar()


def test_insert_y_candidato(precios_pg):
    from apu_tool.nucleo.models import Insumo
    n = precios_pg.insert_insumos([
        Insumo("6140", "ACERO 60000 PSI", "KG", "MATERIAL", 3500.0, "PRECIO IDU")])
    assert n == 1
    cands = precios_pg.get_candidatos("6140")
    assert len(cands) == 1
    assert cands[0].precio == 3500.0


def test_counts_visibles_excluye_ocultos(precios_pg):
    """Espejo del SQLite: el chip cuenta visibles y el guard de seed sigue viendo el
    total. En Postgres `oculto` es BOOLEAN (no INTEGER como en SQLite), así que este
    caso también fija que la comparación del WHERE es la correcta para este backend."""
    from apu_tool.nucleo.models import Insumo
    precios_pg.insert_insumos([
        Insumo("1", "UNO", "UN", "MAT", 100.0, "PRECIO IDU"),
        Insumo("2", "DOS", "UN", "MAT", 100.0, "PRECIO IDU")])
    iid = precios_pg.get_candidatos("1")[0].id
    precios_pg.set_oculto(iid, True)

    c = precios_pg.counts()
    assert c["insumos_visibles"] == 1
    assert c["insumos"] == 2
