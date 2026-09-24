from apu_tool.datos.almacen import Almacen
from apu_tool.nucleo.models import CorridaItemRow, CorridaMeta, LicitacionItem, Perfil
from apu_tool.servicio import corridas as corridas_svc
from apu_tool.servicio import usuarios as usuarios_svc
from apu_tool.servicio.supabase_admin import AdminSupabaseFake


def _alm(tmp_path):
    alm = Almacen(precios_path=tmp_path / "p.db", apus_path=tmp_path / "a.db",
                  corridas_path=tmp_path / "c.db")
    alm.init_schema()
    return alm


def _admin():
    return Perfil("admin-0", "root@obra.co", "admin", "activo")


def test_eliminar_corrida_audita(tmp_path):
    alm = _alm(tmp_path)
    cid = alm.corridas.crear_corrida(CorridaMeta(
        id=None, creada_en="x", archivo="lic.xlsx", turno_def="DIURNO",
        use_ai=False, estado="en_revision"))
    ok = corridas_svc.eliminar_corrida(alm, cid, actor=_admin())
    assert ok is True and alm.corridas.get_corrida(cid) is None
    items, total = alm.auditoria.listar(accion="corrida.eliminar")
    assert total == 1 and items[0]["antes"]["archivo"] == "lic.xlsx" and items[0]["despues"] is None


def test_eliminar_corrida_inexistente_no_audita(tmp_path):
    alm = _alm(tmp_path)
    assert corridas_svc.eliminar_corrida(alm, 999, actor=_admin()) is False
    assert alm.auditoria.listar()[1] == 0


def test_igualar_costo_audita(tmp_path):
    alm = _alm(tmp_path)
    cid = alm.corridas.crear_corrida(CorridaMeta(
        id=None, creada_en="x", archivo="lic.xlsx", turno_def="DIURNO",
        use_ai=False, estado="en_revision"))
    alm.corridas.agregar_item(cid, CorridaItemRow(
        seq=0,
        item=LicitacionItem(item="1", descripcion="PRUEBA DE CARGA", unidad="GLB",
                            cantidad=1.0, precio_contractual=92106000.0, shift="DIURNO"),
        status="new", apu_codigo=None, apu_nombre="", unidad="GLB", shift="DIURNO",
        origen="historico", confianza=0.0, explicacion="", componentes=[], candidatos=[]))
    corridas_svc.igualar_costo_al_contractual(alm, cid, [0], actor=_admin())
    items, total = alm.auditoria.listar(accion="corrida.igualar_costo")
    assert total == 1
    evento = items[0]
    assert evento["entidad_tipo"] == "corrida"
    # `despues` nombra los seqs igualados con su nuevo costo_manual.
    assert evento["despues"]["lineas"] == [{"seq": 0, "costo_manual": 92106000.0}]
    # `antes` trae el costo_manual previo (None la primera vez).
    assert evento["antes"]["lineas"] == [{"seq": 0, "costo_manual": None}]


def test_invitar_audita(tmp_path):
    alm = _alm(tmp_path)
    admin = AdminSupabaseFake(id_por_email={"nuevo@obra.co": "u-nuevo"})
    usuarios_svc.invitar(alm, admin, "nuevo@obra.co", "editor", "Nuevo", actor=_admin())
    items, total = alm.auditoria.listar(accion="usuario.invitar")
    assert total == 1 and items[0]["entidad_id"] == "u-nuevo" and items[0]["despues"]["rol"] == "editor"


def test_cambiar_rol_audita_antes_despues(tmp_path):
    alm = _alm(tmp_path)
    alm.perfiles.upsert(Perfil("u1", "a@obra.co", "consulta", "activo"))
    usuarios_svc.cambiar_rol(alm, _admin(), "u1", "editor")
    items, total = alm.auditoria.listar(accion="usuario.cambiar_rol")
    assert total == 1 and items[0]["antes"]["rol"] == "consulta" and items[0]["despues"]["rol"] == "editor"


def test_cambiar_estado_audita(tmp_path):
    alm = _alm(tmp_path)
    alm.perfiles.upsert(Perfil("u1", "a@obra.co", "admin", "activo"))
    alm.perfiles.upsert(Perfil("u2", "b@obra.co", "admin", "activo"))
    usuarios_svc.cambiar_estado(alm, _admin(), "u1", "inactivo")
    items, total = alm.auditoria.listar(accion="usuario.cambiar_estado")
    assert total == 1 and items[0]["despues"]["estado"] == "inactivo"


def test_igualar_por_umbral_deja_el_umbral_en_la_auditoria(tmp_path):
    """312 filas igualadas de a una y 312 igualadas por un techo de $500M son hechos
    distintos: el registro tiene que decir con qué regla se aplicó."""
    alm = _alm(tmp_path)
    cid = alm.corridas.crear_corrida(CorridaMeta(
        id=None, creada_en="x", archivo="lic.xlsx", turno_def="DIURNO",
        use_ai=False, estado="en_revision"))
    alm.corridas.agregar_item(cid, CorridaItemRow(
        seq=0,
        item=LicitacionItem(item="1", descripcion="PRUEBA DE CARGA", unidad="GLB",
                            cantidad=1.0, precio_contractual=1000.0, shift="DIURNO"),
        status="new", apu_codigo=None, apu_nombre="", unidad="GLB", shift="DIURNO",
        origen="historico", confianza=0.0, explicacion="", componentes=[], candidatos=[]))
    corridas_svc.igualar_por_umbral(alm, cid, 500_000_000.0, [0], actor=_admin())
    items, total = alm.auditoria.listar(accion="corrida.igualar_costo")
    assert total == 1
    assert items[0]["contexto"]["umbral_contractual"] == 500_000_000.0


def test_igualar_de_a_una_no_inventa_umbral_en_la_auditoria(tmp_path):
    """El botón de siempre no pone techo: la clave no aparece."""
    alm = _alm(tmp_path)
    cid = alm.corridas.crear_corrida(CorridaMeta(
        id=None, creada_en="x", archivo="lic.xlsx", turno_def="DIURNO",
        use_ai=False, estado="en_revision"))
    alm.corridas.agregar_item(cid, CorridaItemRow(
        seq=0,
        item=LicitacionItem(item="1", descripcion="PRUEBA DE CARGA", unidad="GLB",
                            cantidad=1.0, precio_contractual=1000.0, shift="DIURNO"),
        status="new", apu_codigo=None, apu_nombre="", unidad="GLB", shift="DIURNO",
        origen="historico", confianza=0.0, explicacion="", componentes=[], candidatos=[]))
    corridas_svc.igualar_costo_al_contractual(alm, cid, [0], actor=_admin())
    items, _ = alm.auditoria.listar(accion="corrida.igualar_costo")
    assert "umbral_contractual" not in items[0]["contexto"]
