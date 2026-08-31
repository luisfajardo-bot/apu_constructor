"""Endpoint de revisión: SSE, rol, corrida congelada, persistencia del veredicto."""
from apu_tool.datos.almacen import Almacen
from apu_tool.dominio import revision
from apu_tool.nucleo.models import (
    Apu, ApuComponent, CorridaItemRow, CorridaMeta, Insumo, LicitacionItem,
)
from apu_tool.servicio import corridas as svc
from apu_tool.servicio.app import create_app
from tests.conftest import cliente


def _cliente_api(tmp_path):
    a = Almacen(precios_path=tmp_path / "p.db", apus_path=tmp_path / "a.db",
                corridas_path=tmp_path / "c.db")
    a.init_schema()
    a.precios.insert_insumos([Insumo("4279", "CUADRILLA", "HR", "MO", 40000, "PRECIO IDU")])
    a.apus.insert_apus([Apu("100", "EXCAVACION MANUAL", "M3", "DIURNO", "MOV"),
                        Apu("200", "EXCAVACION MECANICA", "M3", "DIURNO", "MOV")])
    a.apus.insert_components([
        ApuComponent("100", "DIURNO", "4279", "CUADRILLA", "HR", 1.0, 40000),
        ApuComponent("200", "DIURNO", "4279", "CUADRILLA", "HR", 0.4, 40000)])
    return cliente(create_app(almacen=a), rol="admin"), a


def _corrida_armada(alm) -> int:
    """Dos filas, las dos con el APU 100 asignado y el 200 como candidato."""
    cid = alm.corridas.crear_corrida(CorridaMeta(
        id=None, creada_en="2026-08-31T10:00:00", archivo="x.xlsx", turno_def="DIURNO",
        use_ai=None, estado="en_revision", cuadro_path=None, nombre="x"))
    for seq, desc in enumerate(("EXCAVACION MANUAL", "EXCAVACION A MAQUINA")):
        alm.corridas.agregar_item(cid, CorridaItemRow(
            seq=seq,
            item=LicitacionItem(item=str(seq + 1), descripcion=desc, unidad="M3",
                                cantidad=10, precio_contractual=1000, shift="DIURNO"),
            status="auto", apu_codigo="100", apu_nombre="EXCAVACION MANUAL",
            unidad="M3", shift="DIURNO", origen="historico", confianza=0.9,
            explicacion="", componentes=[],
            candidatos=[{"apu_codigo": "200", "apu_nombre": "EXCAVACION MECANICA",
                         "score": 0.7, "motivo": ""}]))
    return cid


class _RevisorDoble(revision.Revisor):
    """Sustituye la ÚNICA puerta al SDK (`_pedir`): sin red y sin API key.

    `enabled=False` en el super para que no intente armar el cliente de anthropic;
    después se fuerza a True porque `_pedir` ya no lo usa."""

    def __init__(self, respuestas):
        super().__init__(enabled=False)
        self.enabled = True
        self.respuestas = list(respuestas)

    def _pedir(self, system, schema, payload, effort):
        return self.respuestas.pop(0)


def _doble_cambiar():
    """Barrido marca las dos filas; la profundización manda cambiar al APU 200."""
    profundo = {"dictamen": "cambiar", "apu_sugerido": "200",
                "turno_sugerido": "DIURNO", "confianza": 0.8,
                "justificacion": "La actividad es mecánica."}
    return _RevisorDoble([
        {"filas": [{"seq": 0, "resultado": "revisar"}, {"seq": 1, "resultado": "revisar"}]},
        profundo, profundo])


def test_stream_persiste_los_veredictos(tmp_path, monkeypatch):
    cli, alm = _cliente_api(tmp_path)
    cid = _corrida_armada(alm)
    monkeypatch.setattr(svc, "Revisor", lambda: _doble_cambiar())

    r = cli.post(f"/api/corridas/{cid}/revision/stream")
    assert r.status_code == 200, r.text
    assert "event: done" in r.text

    filas = alm.corridas.get_items(cid)
    assert [f.revision["dictamen"] for f in filas] == ["cambiar", "cambiar"]
    assert filas[0].revision["apu_sugerido"] == "200"
    assert filas[0].revision["nivel"] == "profundo"


def test_congelada_no_se_revisa(tmp_path, monkeypatch):
    cli, alm = _cliente_api(tmp_path)
    cid = _corrida_armada(alm)
    alm.corridas.set_modo(cid, "congelada")
    monkeypatch.setattr(svc, "Revisor", lambda: _doble_cambiar())

    r = cli.post(f"/api/corridas/{cid}/revision/stream")
    assert r.status_code == 409, r.text
    assert alm.corridas.get_items(cid)[0].revision is None


def test_sin_api_key_avisa(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    cli, alm = _cliente_api(tmp_path)
    cid = _corrida_armada(alm)

    r = cli.post(f"/api/corridas/{cid}/revision/stream")
    assert r.status_code == 409, r.text
    assert "ANTHROPIC_API_KEY" in r.json()["detail"]


def test_corrida_inexistente(tmp_path, monkeypatch):
    cli, _alm = _cliente_api(tmp_path)
    monkeypatch.setattr(svc, "Revisor", lambda: _doble_cambiar())
    assert cli.post("/api/corridas/999/revision/stream").status_code == 404


def test_la_vista_trae_el_veredicto_y_si_hay_ia(tmp_path):
    cli, alm = _cliente_api(tmp_path)
    cid = _corrida_armada(alm)
    alm.corridas.set_revision(cid, 0, {"seq": 0, "dictamen": "dudoso",
                                       "apu_sugerido": None, "turno_sugerido": None,
                                       "confianza": 0.3, "justificacion": "mirar",
                                       "nivel": "profundo"})
    body = cli.get(f"/api/corridas/{cid}").json()
    assert body["items"][0]["revision"]["dictamen"] == "dudoso"
    assert body["items"][1]["revision"] is None
    assert isinstance(body["ia_disponible"], bool)


def test_consulta_no_puede_revisar(tmp_path):
    _cli, alm = _cliente_api(tmp_path)
    cid = _corrida_armada(alm)
    consulta = cliente(create_app(almacen=alm), rol="consulta")
    assert consulta.post(f"/api/corridas/{cid}/revision/stream").status_code == 403


# --- Aplicar N sugerencias distintas en una sola llamada -----------------------

def test_aplicar_sugerencias_distintas_en_una_llamada(tmp_path):
    cli, alm = _cliente_api(tmp_path)
    cid = _corrida_armada(alm)     # seq 0 y 1, ambos con APU "100"
    r = cli.post(f"/api/corridas/{cid}/items/confirmar-lote", json={
        "seqs": [],
        "asignaciones": [
            {"seq": 0, "apu_codigo": "200", "shift": "DIURNO"},
            {"seq": 1, "apu_codigo": "100", "shift": "DIURNO"},
        ],
    })
    assert r.status_code == 200, r.text
    items = {i["seq"]: i for i in r.json()["items"]}
    assert items[0]["apu_codigo"] == "200"
    assert items[1]["apu_codigo"] == "100"


def test_asignacion_con_apu_inexistente_falla_sin_aplicar_nada(tmp_path):
    cli, alm = _cliente_api(tmp_path)
    cid = _corrida_armada(alm)
    r = cli.post(f"/api/corridas/{cid}/items/confirmar-lote", json={
        "seqs": [],
        "asignaciones": [
            {"seq": 0, "apu_codigo": "200", "shift": "DIURNO"},
            {"seq": 1, "apu_codigo": "NO_EXISTE", "shift": "DIURNO"},
        ],
    })
    assert r.status_code == 400
    v = cli.get(f"/api/corridas/{cid}").json()
    assert v["items"][0]["apu_codigo"] == "100"    # nada se aplicó a medias


def test_aplicar_borra_el_veredicto_de_esas_filas(tmp_path):
    """El APU cambió: la opinión de la IA hablaba del anterior."""
    cli, alm = _cliente_api(tmp_path)
    cid = _corrida_armada(alm)
    for seq in (0, 1):
        alm.corridas.set_revision(cid, seq, {
            "seq": seq, "dictamen": "cambiar", "apu_sugerido": "200",
            "turno_sugerido": "DIURNO", "confianza": 0.8,
            "justificacion": "es mecánica", "nivel": "profundo"})
    r = cli.post(f"/api/corridas/{cid}/items/confirmar-lote", json={
        "seqs": [],
        "asignaciones": [{"seq": 0, "apu_codigo": "200", "shift": "DIURNO"},
                         {"seq": 1, "apu_codigo": "200", "shift": "DIURNO"}],
    })
    assert r.status_code == 200, r.text
    filas = alm.corridas.get_items(cid)
    assert filas[0].revision is None and filas[1].revision is None


def test_asignaciones_gana_sobre_apu_codigo(tmp_path):
    cli, alm = _cliente_api(tmp_path)
    cid = _corrida_armada(alm)
    r = cli.post(f"/api/corridas/{cid}/items/confirmar-lote", json={
        "seqs": [0, 1], "apu_codigo": "100", "shift": "DIURNO",
        "asignaciones": [{"seq": 0, "apu_codigo": "200", "shift": "DIURNO"}],
    })
    assert r.status_code == 200, r.text
    filas = {f.seq: f for f in alm.corridas.get_items(cid)}
    assert filas[0].apu_codigo == "200"           # ganó la asignación
    assert filas[0].status == "confirmed"
    assert filas[1].status == "auto"              # `seqs` se ignoró


def test_congelada_rechaza_las_asignaciones(tmp_path):
    cli, alm = _cliente_api(tmp_path)
    cid = _corrida_armada(alm)
    alm.corridas.set_modo(cid, "congelada")
    r = cli.post(f"/api/corridas/{cid}/items/confirmar-lote", json={
        "seqs": [],
        "asignaciones": [{"seq": 0, "apu_codigo": "200", "shift": "DIURNO"}],
    })
    assert r.status_code == 409
    assert alm.corridas.get_items(cid)[0].apu_codigo == "100"


def test_asignacion_con_seq_inexistente_se_saltea(tmp_path):
    """Misma semántica que el camino viejo: el seq ajeno se saltea (404 solo si
    NINGUNO de los pedidos existe)."""
    cli, alm = _cliente_api(tmp_path)
    cid = _corrida_armada(alm)
    r = cli.post(f"/api/corridas/{cid}/items/confirmar-lote", json={
        "seqs": [],
        "asignaciones": [{"seq": 0, "apu_codigo": "200", "shift": "DIURNO"},
                         {"seq": 999, "apu_codigo": "200", "shift": "DIURNO"}],
    })
    assert r.status_code == 200, r.text
    filas = {f.seq: f for f in alm.corridas.get_items(cid)}
    assert filas[0].apu_codigo == "200" and 999 not in filas
