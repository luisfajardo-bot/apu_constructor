"""Base de prueba del chat de consulta: un catálogo chico, APUs en los dos turnos, y
dos proyectos (carpetas) con corridas. La Calle 13 tiene capítulos y una fila sin APU
en REDES HUMEDAS, para probar lo parcial."""
from apu_tool.datos.almacen import Almacen
from apu_tool.nucleo.models import (
    Apu, ApuComponent, CorridaItemRow, CorridaMeta, Insumo, LicitacionItem,
)


def _fila(seq, desc, cantidad, contractual, apu=None, cap=("", "")):
    item = LicitacionItem(str(seq), desc, "M3", cantidad, contractual, "DIURNO",
                          capitulo_codigo=cap[0], capitulo_nombre=cap[1])
    return CorridaItemRow(
        seq=seq, item=item, status="auto" if apu else "new", apu_codigo=apu,
        apu_nombre=apu or "(sin base — armar manual)", unidad="M3", shift="DIURNO",
        origen="historico" if apu else "manual", confianza=0.9 if apu else 0.0,
        explicacion="", componentes=[], candidatos=[])


def _corrida(alm, nombre, carpeta_id, filas):
    cid = alm.corridas.crear_corrida(CorridaMeta(
        id=None, creada_en="2026-11-25T10:00:00", archivo=f"{nombre}.xlsx",
        turno_def="DIURNO", use_ai=None, estado="en_revision",
        carpeta_id=carpeta_id, nombre=nombre))
    alm.corridas.guardar_items(cid, filas)
    return cid


def almacen_consulta(tmp_path):
    """Devuelve (alm, ids) con ids = {insumo_tubo, insumo_cero, calle13, cali}."""
    from apu_tool import config
    # `Almacen` IGNORA las rutas si hay DATABASE_URL, y esto llama `reset()`. El guard
    # de tests/conftest.py solo protege dentro de pytest: este se defiende solo.
    assert config.db_backend() == "sqlite", "la base de prueba nunca va contra Postgres"
    alm = Almacen(tmp_path / "precios.db", tmp_path / "apus.db",
                  tmp_path / "corridas.db")
    alm.init_schema()
    alm.reset()
    alm.init_schema()
    alm.precios.insert_insumos([
        Insumo("4279", "CUADRILLA", "HR", "MO", 40000, "PRECIO IDU"),
        Insumo("6092", "HERRAMIENTA MENOR", "GLB", "EQ", 2000, "PRECIO IDU"),
        Insumo("8001", "TUBERIA PVC 6 PULG", "ML", "MAT", 35000, "COSTO INTERNO"),
        Insumo("8002", "TUBERIA PVC 8 PULG", "ML", "MAT", 0, "COSTO INTERNO"),
        # Nombre real del estilo de los 54 que disparan el detector de cifras.
        Insumo("8003", "BASCULA PESO 60.000 KG", "UN", "EQ", 900000, "COSTO INTERNO"),
    ])
    alm.apus.insert_apus([
        Apu("A1", "MEZCLA ASFALTICA MDC-19", "M3", "DIURNO", "PAVIMENTOS"),
        Apu("A1 N", "MEZCLA ASFALTICA MDC-19", "M3", "NOCTURNO", "PAVIMENTOS"),
        Apu("A2", "INSTALACION TUBERIA PVC 6", "ML", "DIURNO", "REDES"),
        Apu("A3", "ACTIVIDAD CON INSUMO HUERFANO", "UN", "DIURNO", "VARIOS"),
    ])
    alm.apus.insert_components([
        ApuComponent("A1", "DIURNO", "4279", "CUADRILLA", "HR", 0.5, 40000),
        ApuComponent("A1", "DIURNO", "6092", "HERRAMIENTA MENOR", "GLB", 1.0, 2000),
        ApuComponent("A1 N", "NOCTURNO", "4279", "CUADRILLA", "HR", 0.6, 40000),
        ApuComponent("A2", "DIURNO", "8001", "TUBERIA PVC 6 PULG", "ML", 1.0, 35000),
        ApuComponent("A3", "DIURNO", "9999", "INSUMO QUE NO EXISTE", "UN", 1.0, 100),
    ])
    calle13 = alm.carpetas.crear("CALLE 13", None)
    cali = alm.carpetas.crear("LA CALI", None)
    cali_sub = alm.carpetas.crear("PRESUPUESTO", cali)
    ids = {
        "insumo_tubo": alm.precios.search_insumos("TUBERIA PVC 6 PULG")[0].id,
        "insumo_cero": alm.precios.search_insumos("TUBERIA PVC 8 PULG")[0].id,
        "calle13": _corrida(alm, "Calle 13 lote SL5", calle13, [
            _fila(1, "MEZCLA ASFALTICA", 10, 30000, "A1", ("1", "PRELIMINARES")),
            _fila(2, "TUBERIA PVC 6", 4, 50000, "A2", ("2", "REDES HUMEDAS")),
            _fila(3, "CAMARA DE INSPECCION", 2, 10000, None, ("2", "REDES HUMEDAS")),
        ]),
        "cali": _corrida(alm, "Cali v1", cali_sub, [
            _fila(1, "MEZCLA ASFALTICA", 1, 25000, "A1")]),
    }
    return alm, ids
