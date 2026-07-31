"""El chip de la barra superior cuenta lo mismo que muestra la pestaña de Insumos.

`/api/status` traía `counts()["insumos"]` = TODAS las filas de `insumos`, mientras que
`GET /api/insumos` filtra `oculto = 0`. Tras ocultar los ~1062 códigos que son eco de un
APU, la barra seguía diciendo 8157 y la tabla mostraba menos: dos números distintos para
lo mismo, y el operador no sabe cuál creer.

`counts()["insumos"]` NO cambia de significado a propósito: es el guard de
`datos/seed.py` y `dominio/pipeline.py::ensure_seeded` ("¿la base ya tiene datos?"). Si
excluyera los ocultos, una base con todos sus insumos ocultos parecería vacía y se
re-semillaría encima. La cuenta visible viaja en una clave nueva, `insumos_visibles`.
"""
from apu_tool.datos.almacen import Almacen
from apu_tool.nucleo.models import Insumo
from apu_tool.servicio.app import create_app
from tests.conftest import cliente


def _alm(tmp_path):
    alm = Almacen(precios_path=tmp_path / "p.db", apus_path=tmp_path / "a.db",
                  corridas_path=tmp_path / "c.db")
    alm.init_schema()
    return alm


def _tres_insumos(alm):
    ids = [alm.precios.crear_insumo(Insumo(c, n, "UN", "MAT", 100.0, "PRECIO IDU"))
           for c, n in (("1", "UNO"), ("2", "DOS"), ("3", "TRES"))]
    return ids


def test_counts_trae_insumos_visibles_sin_los_ocultos(tmp_path):
    alm = _alm(tmp_path)
    ids = _tres_insumos(alm)
    alm.precios.set_oculto(ids[0], True)

    c = alm.counts()
    assert c["insumos_visibles"] == 2
    assert c["insumos"] == 3          # el total NO cambia (guard de seed)


def test_counts_visibles_igual_al_total_de_la_pestana_de_insumos(tmp_path):
    """Mismo número en los dos lados: chip y `total` de GET /api/insumos sin filtros."""
    alm = _alm(tmp_path)
    ids = _tres_insumos(alm)
    alm.precios.set_oculto(ids[0], True)
    cli = cliente(create_app(almacen=alm), rol="consulta")

    chip = cli.get("/api/status").json()["insumos"]
    tabla = cli.get("/api/insumos").json()["total"]
    assert chip == tabla == 2


def test_base_vieja_sin_columna_oculto_no_revienta_ni_parece_vacia(tmp_path):
    """Regresión: `seed()` llama a `counts()` ANTES de `init_schema` y se come el
    `sqlite3.OperationalError` (`c = {}`), así que si `counts()` reventara por una
    columna que falta, una base vieja CON datos pasaría por vacía y `seed` la
    re-semillaría encima. `counts()` cae al total cuando no hay `oculto`.
    """
    import sqlite3
    alm = _alm(tmp_path)
    _tres_insumos(alm)
    with sqlite3.connect(tmp_path / "p.db") as conn:      # simula el esquema viejo
        conn.execute("ALTER TABLE insumos DROP COLUMN oculto")

    c = Almacen(precios_path=tmp_path / "p.db", apus_path=tmp_path / "a.db",
                corridas_path=tmp_path / "c.db").precios.counts()
    assert c["insumos"] == 3
    assert c["insumos_visibles"] == 3


def test_todos_ocultos_no_hace_parecer_vacia_la_base(tmp_path):
    """Regresión: el guard de seed mira `insumos`, no `insumos_visibles`.

    Con la cuenta visible en 0, `seed()`/`ensure_seeded()` re-semillarían encima de una
    base que sí tiene catálogo (y `seed --force` se lleva las listas de precios NP).
    """
    alm = _alm(tmp_path)
    for iid in _tres_insumos(alm):
        alm.precios.set_oculto(iid, True)

    c = alm.counts()
    assert c["insumos_visibles"] == 0
    assert c["insumos"] == 3
