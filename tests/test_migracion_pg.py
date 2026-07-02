import os
import pytest

pytestmark = pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"),
    reason="sin TEST_DATABASE_URL")


def _sembrar_sqlite(tmp_path):
    from apu_tool.datos.precios_db import PreciosDB
    from apu_tool.datos.apus_db import ApusDB
    from apu_tool.nucleo.models import Apu, ApuComponent, Insumo
    p = PreciosDB(tmp_path / "precios.db"); p.init_schema()
    a = ApusDB(tmp_path / "apus.db"); a.init_schema()
    iid = p.crear_insumo(Insumo("6140", "ACERO", "KG", "MAT", 3500.0, "PRECIO IDU"))
    p.set_precio_por_id(iid, 3700.0, "COMPRAS 2026")  # genera historial (2 filas)
    a.crear_apu(Apu("A1", "EXCAVACION", "M3", "DIURNO", "MT"),
                [ApuComponent("A1", "DIURNO", "6140", "ACERO", "KG", 0.5, 3500.0)])
    return tmp_path / "precios.db", tmp_path / "apus.db"


def test_migracion_traslada_y_verifica(tmp_path):
    from apu_tool.datos.pg.conexion import Conexion, ejecutar_script
    from apu_tool.datos import migracion_pg
    sp, sa = _sembrar_sqlite(tmp_path)
    cx = Conexion(os.environ["TEST_DATABASE_URL"])
    try:
        with cx.connection() as conn:
            for f in ("precios.sql", "apus.sql", "corridas.sql"):
                from apu_tool import config
                conn.execute("DROP SCHEMA IF EXISTS precios CASCADE")
                conn.execute("DROP SCHEMA IF EXISTS apus CASCADE")
                conn.execute("DROP SCHEMA IF EXISTS corridas CASCADE")
            for f in ("precios.sql", "apus.sql", "corridas.sql"):
                ejecutar_script(conn, (config.PROJECT_ROOT / "db" / "pg" / f).read_text("utf-8"))
        res = migracion_pg.migrar_catalogo(sp, sa, cx)
        assert res["insumos"] == 1
        assert res["precios"] == 2      # historial preservado
        assert res["apus"] == 1
        assert res["componentes"] == 1
        ver = migracion_pg.verificar(sp, sa, cx)
        assert ver["ok"] is True
        # el precio vigente y el linkage se conservan
        from apu_tool.datos.pg.precios_pg import PreciosPg
        cand = PreciosPg(cx).get_candidatos("6140")
        assert cand[0].precio == 3700.0
    finally:
        cx.cerrar()


def test_migrar_catalogo_es_idempotente(tmp_path):
    from apu_tool.datos.pg.conexion import Conexion, ejecutar_script
    from apu_tool.datos import migracion_pg
    from apu_tool import config
    sp, sa = _sembrar_sqlite(tmp_path)
    cx = Conexion(os.environ["TEST_DATABASE_URL"])
    try:
        with cx.connection() as conn:
            conn.execute("DROP SCHEMA IF EXISTS precios CASCADE")
            conn.execute("DROP SCHEMA IF EXISTS apus CASCADE")
        with cx.connection() as conn:
            for f in ("precios.sql", "apus.sql"):
                ejecutar_script(conn, (config.PROJECT_ROOT / "db" / "pg" / f).read_text("utf-8"))
        res1 = migracion_pg.migrar_catalogo(sp, sa, cx)
        res2 = migracion_pg.migrar_catalogo(sp, sa, cx)  # 2ª vez: no debe romper
        # migrar_catalogo cuenta filas de ORIGEN procesadas (no filas realmente
        # insertadas): con ON CONFLICT DO NOTHING la 2ª pasada procesa lo mismo
        # (mismos counts) pero NO inserta nada. La idempotencia real —que la BD
        # no se duplique— se comprueba con verificar(): destino == origen.
        assert res2 == res1
        ver = migracion_pg.verificar(sp, sa, cx)
        assert ver["ok"], ver["detalle"]  # sin duplicados tras dos corridas
        # counts de origen estables
        assert res1["insumos"] == 1
        assert res1["precios"] == 2
        assert res1["apus"] == 1
        assert res1["componentes"] == 1
    finally:
        cx.cerrar()
