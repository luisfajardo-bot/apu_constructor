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


# ---------------------------------------------------------------------------
# Hallazgo 3 (review 2026-07 sobre d4530b8) — el SELECT/INSERT de insumo_precios
# no viajaba con lista_id (todo caía en el DEFAULT 1) y lista_precios no se
# copiaba en absoluto. Escenario de daño: un insumo con precio vigente en
# Principal Y en una lista NP terminaba con DOS filas vigente=1/lista_id=1 en
# destino -> get_candidatos devuelve 2 candidatos ambiguos para el mismo
# (código, nombre) -> cruce.py::resolver marca AMBIGUO -> costeo en $0
# silencioso. Este test siembra exactamente ese escenario (mismo insumo con
# tarifa propia en Principal y en una lista NP) y verifica que ambas quedan
# separadas y correctas tras migrar.
# ---------------------------------------------------------------------------
def _sembrar_sqlite_con_lista_np(tmp_path):
    from apu_tool.datos.precios_db import PreciosDB
    from apu_tool.datos.apus_db import ApusDB
    from apu_tool.nucleo.models import Insumo
    p = PreciosDB(tmp_path / "precios.db"); p.init_schema()
    a = ApusDB(tmp_path / "apus.db"); a.init_schema()
    iid = p.crear_insumo(Insumo("6140", "ACERO", "KG", "MAT", 3500.0, "PRECIO IDU"))
    lid = p.crear_lista("NP Calle 13", creado_por="u1")
    # tarifa PROPIA del mismo insumo en la lista NP (no toca el vigente de Principal:
    # _insertar_precio_vigente solo desvigenta filas CON ese mismo lista_id).
    p.set_precio_por_id(iid, 5000.0, fuente="COSTO INTERNO", lista_id=lid)
    return tmp_path / "precios.db", tmp_path / "apus.db", lid


def test_migracion_copia_listas_y_preserva_lista_id(tmp_path):
    from apu_tool.datos.pg.conexion import Conexion, ejecutar_script
    from apu_tool.datos import migracion_pg
    from apu_tool import config
    sp, sa, lid = _sembrar_sqlite_con_lista_np(tmp_path)
    cx = Conexion(os.environ["TEST_DATABASE_URL"])
    try:
        with cx.connection() as conn:
            for schema in ("precios", "apus", "corridas"):
                conn.execute(f"DROP SCHEMA IF EXISTS {schema} CASCADE")
        with cx.connection() as conn:
            for f in ("precios.sql", "apus.sql", "corridas.sql"):
                ejecutar_script(conn, (config.PROJECT_ROOT / "db" / "pg" / f).read_text("utf-8"))
        res = migracion_pg.migrar_catalogo(sp, sa, cx)
        assert res["listas"] == 2        # Principal (id 1) + NP Calle 13
        assert res["precios"] == 2       # una fila vigente por lista, no una sola pisada
        ver = migracion_pg.verificar(sp, sa, cx)
        assert ver["ok"] is True, ver["detalle"]

        from apu_tool.datos.pg.precios_pg import PreciosPg
        pg = PreciosPg(cx)
        lista = pg.get_lista(lid)
        assert lista is not None and lista.nombre == "NP Calle 13"

        # Principal conserva SU precio, sin ambigüedad (un solo candidato)
        cand_principal = pg.get_candidatos("6140")
        assert len(cand_principal) == 1
        assert cand_principal[0].precio == 3500.0

        # la lista NP tiene SU PROPIO precio vigente, no el de Principal
        cand_np = pg.get_candidatos("6140", lista_id=lid)
        assert len(cand_np) == 1
        assert cand_np[0].precio == 5000.0
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
