"""El auto-seed trabaja sobre la base del request, no sobre una que se arma sola.

`ensure_seeded()` se construía su propio `Almacen()` con las rutas por defecto de
`config`, así que el guard (`alm.counts()["apus"] == 0`) preguntaba por una base y el
seed escribía en otra. Consecuencias reales: 4 tests de API en rojo en CI (bd5fece), un
pool de conexiones huérfano por disparo en producción, y la posibilidad de armar una
corrida contra una biblioteca vacía sin que nada avise.

Ver docs/superpowers/specs/2026-07-31-ensure-seeded-almacen-inyectado-design.md
"""
import pytest

from apu_tool.datos.almacen import Almacen
from apu_tool.dominio import pipeline


def _alm_vacio(tmp_path) -> Almacen:
    """Almacén temporal SIN insumos ni APUs: es la condición que dispara el auto-seed
    (`ensure_seeded` solo semilla si las dos cuentas están en cero)."""
    alm = Almacen(precios_path=tmp_path / "p.db", apus_path=tmp_path / "a.db",
                  corridas_path=tmp_path / "c.db")
    alm.init_schema()
    return alm


def test_ensure_seeded_semilla_sobre_el_almacen_recibido(tmp_path, monkeypatch):
    alm = _alm_vacio(tmp_path)
    recibidos = []

    def fake_seed(almacen, **kwargs):
        recibidos.append(almacen)
        return {"apus": 0, "insumos": 0}

    monkeypatch.setattr(pipeline, "seed", fake_seed)

    pipeline.ensure_seeded(alm)

    assert recibidos, "no se llamó a seed"
    assert recibidos[0] is alm, "seed recibió otro almacén, no el que se le pasó"


def test_ensure_seeded_sin_almacen_usa_el_global(tmp_path, monkeypatch):
    """El default sigue existiendo: es lo que usan CLI y GUI, y no debe cambiar."""
    global_alm = _alm_vacio(tmp_path)
    monkeypatch.setattr(pipeline, "get_almacen", lambda: global_alm)
    recibidos = []
    monkeypatch.setattr(pipeline, "seed",
                        lambda almacen, **kw: (recibidos.append(almacen),
                                               {"apus": 0, "insumos": 0})[1])

    pipeline.ensure_seeded()

    assert recibidos[0] is global_alm


def test_sin_excel_historico_levanta_biblioteca_vacia(tmp_path, monkeypatch):
    """Sin fuente de la que semillar, el error tiene que ser explícito y del dominio.

    Antes salía un `FileNotFoundError` crudo que la API devolvía como 500.
    """
    monkeypatch.delenv("APU_SOURCE_XLSX", raising=False)   # detect_source_xlsx() -> None
    alm = _alm_vacio(tmp_path)

    with pytest.raises(pipeline.BibliotecaVacia) as exc:
        pipeline.ensure_seeded(alm)

    assert "biblioteca de APUs está vacía" in str(exc.value)


def test_biblioteca_poblada_no_semilla(tmp_path, monkeypatch):
    """No-regresión: con APUs en la biblioteca, ni se intenta semillar."""
    from apu_tool.nucleo.models import Apu
    alm = _alm_vacio(tmp_path)
    alm.apus.insert_apus([Apu("A1", "EXCAVACION", "M3", "DIURNO", "MT")])

    def explota(*a, **kw):
        raise AssertionError("no debía llamar a seed")

    monkeypatch.setattr(pipeline, "seed", explota)

    assert pipeline.ensure_seeded(alm)["apus"] == 1


def test_generate_sample_pasa_su_almacen_al_auto_seed(tmp_path, monkeypatch):
    """`generate_sample` recibe un almacén (los endpoints le pasan el del request) y
    decide con `db_is_empty(alm)`, pero llamaba a `ensure_seeded()` sin pasarlo: misma
    divergencia guard/acción. Se corta la ejecución en el propio ensure_seeded para no
    depender de nada de lo que hace generate_sample después.
    """
    class Corte(Exception):
        pass

    recibidos = []

    def fake_ensure(alm=None, xlsx_path=None):
        recibidos.append(alm)
        raise Corte

    monkeypatch.setattr(pipeline, "ensure_seeded", fake_ensure)
    alm = _alm_vacio(tmp_path)          # 0 APUs -> db_is_empty(alm) es True

    with pytest.raises(Corte):
        pipeline.generate_sample(out_path=tmp_path / "sample.xlsx", alm=alm)

    assert recibidos == [alm], "generate_sample no le pasó su almacén a ensure_seeded"


# --------------------------------------------------------------------- nivel HTTP
from apu_tool.dominio.licitacion import write_sample_licitacion          # noqa: E402
from apu_tool.nucleo.models import LicitacionItem                        # noqa: E402
from apu_tool.servicio.app import create_app                             # noqa: E402
from tests.conftest import cliente                                       # noqa: E402

_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _cli_vacio(tmp_path, monkeypatch):
    """Cliente HTTP contra un almacén vacío y sin Excel histórico a la vista."""
    monkeypatch.delenv("APU_SOURCE_XLSX", raising=False)
    alm = _alm_vacio(tmp_path)
    return cliente(create_app(almacen=alm), rol="admin"), alm


def _xlsx_lic(tmp_path):
    p = tmp_path / "lic.xlsx"
    write_sample_licitacion(p, [LicitacionItem(
        item="1", descripcion="EXCAVACION MANUAL", unidad="M3", cantidad=10.0,
        precio_contractual=400000.0, shift="DIURNO")])
    return p


def _post_corrida(cli, tmp_path, ruta="/api/corridas"):
    obra = cli.post("/api/carpetas", json={"nombre": "Obra"}).json()
    with open(_xlsx_lic(tmp_path), "rb") as f:
        return cli.post(ruta,
                        data={"turno": "DIURNO", "use_ai": "false",
                              "carpeta_id": str(obra["id"])},
                        files={"archivo": ("lic.xlsx", f, _XLSX)})


def test_post_corridas_biblioteca_vacia_da_409(tmp_path, monkeypatch):
    cli, _ = _cli_vacio(tmp_path, monkeypatch)
    r = _post_corrida(cli, tmp_path)
    assert r.status_code == 409, r.text
    assert "biblioteca de APUs está vacía" in r.json()["detail"]


def test_post_corridas_stream_biblioteca_vacia_da_409(tmp_path, monkeypatch):
    cli, _ = _cli_vacio(tmp_path, monkeypatch)
    r = _post_corrida(cli, tmp_path, ruta="/api/corridas/stream")
    assert r.status_code == 409, r.text


def test_post_sample_biblioteca_vacia_da_409(tmp_path, monkeypatch):
    cli, _ = _cli_vacio(tmp_path, monkeypatch)
    r = cli.post("/api/sample")
    assert r.status_code == 409, r.text


def test_post_sample_stream_biblioteca_vacia_da_409(tmp_path, monkeypatch):
    cli, _ = _cli_vacio(tmp_path, monkeypatch)
    r = cli.post("/api/sample/stream")
    assert r.status_code == 409, r.text


def test_api_semilla_sobre_el_almacen_del_request(tmp_path, monkeypatch):
    """EL test que faltaba: el que habría atrapado el rojo de CI de bd5fece.

    Con un Excel disponible, el seed que dispara la API tiene que caer en la base del
    request — no en `data/*.db`, que es la del desarrollador (y en CI no existe).
    """
    cli, alm = _cli_vacio(tmp_path, monkeypatch)
    recibidos = []
    monkeypatch.setattr(pipeline, "seed",
                        lambda almacen, **kw: (recibidos.append(almacen),
                                               {"apus": 0, "insumos": 0})[1])

    _post_corrida(cli, tmp_path)

    assert recibidos, "la API no intentó semillar"
    assert recibidos[0] is alm, "semilló sobre otra base, no la del request"
