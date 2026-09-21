"""
Acceso a corridas.db (SQLite): estado de aplicación de un armado en progreso.

Implementa RepositorioCorridas. Guarda DECISIONES y ESTRUCTURA, nunca dinero
derivado (el costo se recalcula con el precio vigente). El único valor monetario
que persiste es el precio_contractual de entrada, embebido en item_json.
"""
from __future__ import annotations

import json
import logging
import sqlite3
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path
from typing import Iterator, Optional

from apu_tool import config
from apu_tool.datos.repositorio import ArmadoDuplicado, CorridaEliminada
from apu_tool.nucleo.models import CorridaItemRow, CorridaMeta, LicitacionItem

logger = logging.getLogger(__name__)

SCHEMA_PATH = config.PROJECT_ROOT / "db" / "corridas.sql"


def _load_schema() -> str:
    return SCHEMA_PATH.read_text(encoding="utf-8")


def _json_o_none(crudo):
    """Texto JSON -> dict. None si está vacío o si no parsea.

    Tolerante a propósito: una corrida con basura en la columna no puede impedir que se
    abra "Mis corridas". El origen es metadato de procedencia, no verdad operativa.
    """
    if not crudo:
        return None
    try:
        return json.loads(crudo)
    except (ValueError, TypeError):
        return None


class CorridasDB:
    """Backend SQLite de corridas. Implementa RepositorioCorridas."""

    def __init__(self, path: Path | str = config.CORRIDAS_DB_PATH):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def init_schema(self) -> None:
        with self.connect() as conn:
            conn.executescript(_load_schema())
            cols = {r["name"] for r in conn.execute("PRAGMA table_info(corrida)").fetchall()}
            if "duracion_ms" not in cols:
                conn.execute("ALTER TABLE corrida ADD COLUMN duracion_ms INTEGER")
            if "modo" not in cols:
                conn.execute("ALTER TABLE corrida ADD COLUMN modo TEXT NOT NULL DEFAULT 'activa'")
            if "carpeta_id" not in cols:
                conn.execute("ALTER TABLE corrida ADD COLUMN carpeta_id INTEGER "
                             "REFERENCES carpeta(id) ON DELETE RESTRICT")
            if "nombre" not in cols:
                conn.execute("ALTER TABLE corrida ADD COLUMN nombre TEXT")
            if "lista_precios_id" not in cols:
                conn.execute("ALTER TABLE corrida ADD COLUMN lista_precios_id INTEGER")
            if "plan_json" not in cols:
                conn.execute("ALTER TABLE corrida ADD COLUMN plan_json TEXT")
            if "origen_json" not in cols:
                conn.execute("ALTER TABLE corrida ADD COLUMN origen_json TEXT")
            if "intentos" not in cols:
                conn.execute("ALTER TABLE corrida ADD COLUMN intentos INTEGER NOT NULL DEFAULT 0")
            if "ultimo_error" not in cols:
                conn.execute("ALTER TABLE corrida ADD COLUMN ultimo_error TEXT")
            if "armando_por" not in cols:
                conn.execute("ALTER TABLE corrida ADD COLUMN armando_por TEXT")
            if "armando_desde" not in cols:
                conn.execute("ALTER TABLE corrida ADD COLUMN armando_desde TEXT")
            # Backfill idempotente: corridas viejas muestran su archivo hasta renombrarse.
            conn.execute("UPDATE corrida SET nombre = archivo "
                         "WHERE nombre IS NULL OR nombre = ''")
            icols = {r["name"] for r in conn.execute("PRAGMA table_info(corrida_item)").fetchall()}
            if "snapshot_json" not in icols:
                conn.execute("ALTER TABLE corrida_item ADD COLUMN snapshot_json TEXT")
            if "revision_json" not in icols:
                conn.execute("ALTER TABLE corrida_item ADD COLUMN revision_json TEXT")
            if "costo_manual" not in icols:
                conn.execute("ALTER TABLE corrida_item ADD COLUMN costo_manual REAL")
            sc = conn.execute("SELECT id FROM carpeta WHERE nombre='Sin clasificar' "
                              "AND parent_id IS NULL").fetchone()
            if sc is None:
                import datetime as _dt
                cur = conn.execute(
                    "INSERT INTO carpeta (nombre, parent_id, creada_en) VALUES (?, NULL, ?)",
                    ("Sin clasificar", _dt.datetime.now().isoformat(timespec="seconds")))
                sc_id = int(cur.lastrowid)
            else:
                sc_id = int(sc["id"])
            conn.execute("UPDATE corrida SET carpeta_id=? WHERE carpeta_id IS NULL", (sc_id,))
            self._crear_indice_seq(conn)
            self._crear_indice_armado(conn)

    def _crear_indice_seq(self, conn: sqlite3.Connection) -> None:
        """El índice único de (corrida_id, seq), fuera del script del esquema.

        Va aparte y con `try` porque una base vieja puede traer duplicados de armados
        muertos: ahí el índice no se puede crear, y eso NO puede impedir que la app
        arranque — se quedaría sin servicio hasta que alguien limpie a mano. Se grita
        en el log con la consulta para encontrarlos.

        Lo llaman `init_schema` Y `reset`: son los dos caminos que dejan el esquema
        listo, y si solo lo hiciera uno, un `seed --force` borraría la protección sin
        que nadie se entere.
        """
        try:
            conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS ux_corrida_item_seq "
                         "ON corrida_item(corrida_id, seq)")
        except sqlite3.IntegrityError:
            logger.error(
                "No se pudo crear ux_corrida_item_seq: hay (corrida_id, seq) "
                "duplicados. El armado reanudable no esta protegido hasta "
                "limpiarlos. Consulta: SELECT corrida_id, seq, COUNT(*) FROM "
                "corrida_item GROUP BY 1,2 HAVING COUNT(*) > 1;")

    def _crear_indice_armado(self, conn: sqlite3.Connection) -> None:
        """Un solo armado a medias por (carpeta, archivo): el que frena el doble clic.

        PARCIAL (`WHERE estado IN (...)`) porque solo mientras el plan está a medias
        el archivo está tomado: cuando el armado termina, volver a subir la misma
        lista es legítimo (cambió un precio, se rearma). Los dos estados son los
        mismos de `servicio.corridas.ARMANDO_O_A_MEDIAS`; van acá como literal porque
        es SQL — si allá se agrega un estado, hay que tocar este índice también.

        Mismo trato no-fatal que `_crear_indice_seq`, y por lo mismo: una base que ya
        traiga dos armados del mismo archivo no puede impedir que la app arranque. Y
        también lo llaman `init_schema` Y `reset`, porque un `seed --force` que se
        olvidara de crearlo dejaría el doble clic suelto sin que nadie se entere.
        """
        try:
            conn.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS ux_corrida_armando_archivo "
                "ON corrida(carpeta_id, archivo) "
                "WHERE estado IN ('armando', 'armado_detenido')")
        except sqlite3.IntegrityError:
            logger.error(
                "No se pudo crear ux_corrida_armando_archivo: hay (carpeta_id, "
                "archivo) duplicados entre los armados a medias. El doble clic no "
                "esta protegido hasta limpiarlos. Consulta: SELECT carpeta_id, "
                "archivo, COUNT(*) FROM corrida WHERE estado IN ('armando', "
                "'armado_detenido') GROUP BY 1,2 HAVING COUNT(*) > 1;")

    def reset(self) -> None:
        with self.connect() as conn:
            for t in ("corrida_item", "corrida", "carpeta"):
                conn.execute(f"DROP TABLE IF EXISTS {t}")
            conn.executescript(_load_schema())
            self._crear_indice_seq(conn)
            self._crear_indice_armado(conn)

    # ---- escritura ----
    _INSERT_ITEM_SQL = (
        "INSERT INTO corrida_item "
        "(corrida_id, seq, item_json, status, apu_codigo, apu_nombre, unidad, "
        " shift, origen, confianza, explicacion, componentes_json, candidatos_json) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)")

    @staticmethod
    def _item_tuple(corrida_id: int, it: CorridaItemRow) -> tuple:
        return (corrida_id, it.seq, json.dumps(asdict(it.item), ensure_ascii=False),
                it.status, it.apu_codigo, it.apu_nombre, it.unidad, it.shift,
                it.origen, it.confianza, it.explicacion,
                json.dumps(it.componentes, ensure_ascii=False),
                json.dumps(it.candidatos, ensure_ascii=False))

    def _insert_corrida(self, conn: sqlite3.Connection, meta: CorridaMeta) -> int:
        cur = conn.execute(
            "INSERT INTO corrida (creada_en, archivo, turno_def, use_ai, estado, "
            "cuadro_path, duracion_ms, modo, carpeta_id, nombre, lista_precios_id) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (meta.creada_en, meta.archivo, meta.turno_def,
             None if meta.use_ai is None else int(meta.use_ai),
             meta.estado, meta.cuadro_path, meta.duracion_ms, meta.modo,
             meta.carpeta_id, meta.nombre, meta.lista_precios_id))
        return int(cur.lastrowid)

    def crear_corrida(self, meta: CorridaMeta) -> int:
        try:
            with self.connect() as conn:
                return self._insert_corrida(conn, meta)
        except sqlite3.IntegrityError as e:
            # Solo el UNIQUE: una FK rota (carpeta que no existe) también es
            # IntegrityError y no tiene nada que ver con el doble clic. Postgres las
            # distingue por clase (UniqueViolation); acá hay que mirar el código de
            # error. El único UNIQUE que este INSERT puede violar es el del armado
            # duplicado: la PK es autoincremental.
            if e.sqlite_errorname != "SQLITE_CONSTRAINT_UNIQUE":
                raise
            raise ArmadoDuplicado(meta.archivo) from e

    def guardar_items(self, corrida_id: int, items: list[CorridaItemRow]) -> int:
        rows = [self._item_tuple(corrida_id, it) for it in items]
        with self.connect() as conn:
            conn.executemany(self._INSERT_ITEM_SQL, rows)
        return len(rows)

    def agregar_item(self, corrida_id: int, fila: CorridaItemRow) -> None:
        """Inserta un ítem (armado incremental: se persiste cada APU al armarlo).

        Si la corrida ya no existe (la borraron o se reseteó durante el armado), el
        INSERT viola la FK; se traduce a ``CorridaEliminada`` para que la capa de
        servicio cancele el armado limpio en vez de propagar el error de integridad.

        Un ``seq`` repetido (``ux_corrida_item_seq``) es harina de otro costal: la
        corrida SIGUE existiendo, así que decir ``CorridaEliminada`` sería un mensaje
        falso. Se distingue por ``sqlite_errorname`` (no por el texto del mensaje,
        que no está garantizado) y se deja propagar tal cual: mejor un error crudo
        que uno mentiroso.
        """
        try:
            with self.connect() as conn:
                conn.execute(self._INSERT_ITEM_SQL, self._item_tuple(corrida_id, fila))
        except sqlite3.IntegrityError as e:
            if getattr(e, "sqlite_errorname", "") == "SQLITE_CONSTRAINT_FOREIGNKEY":
                raise CorridaEliminada(corrida_id) from e
            raise

    def borrar_items(self, corrida_id: int, seqs, conn=None) -> int:
        lista = [int(s) for s in seqs]
        if not lista:
            return 0
        marcas = ",".join("?" * len(lista))
        sql = f"DELETE FROM corrida_item WHERE corrida_id=? AND seq IN ({marcas})"
        params = (int(corrida_id), *lista)
        if conn is not None:
            return conn.execute(sql, params).rowcount
        with self.connect() as c:
            return c.execute(sql, params).rowcount

    def actualizar_eleccion(self, corrida_id: int, seq: int, *, status: str,
                            apu_codigo: Optional[str], apu_nombre: str, unidad: str,
                            shift: str, origen: str, confianza: float,
                            explicacion: str, componentes: list[dict]) -> None:
        with self.connect() as conn:
            conn.execute(
                # El APU cambió: el veredicto de la IA hablaba del anterior, y un costo
                # puesto a mano ya no manda (la fila volvió a tener composición real).
                # Se borran acá, el único punto por el que pasa un cambio del APU elegido.
                "UPDATE corrida_item SET status=?, apu_codigo=?, apu_nombre=?, unidad=?, "
                "shift=?, origen=?, confianza=?, explicacion=?, componentes_json=?, "
                "revision_json=NULL, costo_manual=NULL "
                "WHERE corrida_id=? AND seq=?",
                (status, apu_codigo, apu_nombre, unidad, shift, origen, confianza,
                 explicacion, json.dumps(componentes, ensure_ascii=False),
                 corrida_id, seq))

    def set_candidatos(self, corrida_id: int,
                       candidatos: dict[int, list[dict]]) -> None:
        """Ver el contrato en repositorio.py."""
        if not candidatos:
            return
        filas = [(json.dumps(c, ensure_ascii=False), int(corrida_id), int(s))
                 for s, c in candidatos.items()]
        with self.connect() as conn:
            conn.executemany(
                "UPDATE corrida_item SET candidatos_json=? "
                "WHERE corrida_id=? AND seq=?", filas)

    def set_cuadro(self, corrida_id: int, path: str) -> None:
        with self.connect() as conn:
            conn.execute("UPDATE corrida SET cuadro_path=? WHERE id=?", (path, corrida_id))

    def set_estado(self, corrida_id: int, estado: str) -> None:
        with self.connect() as conn:
            conn.execute("UPDATE corrida SET estado=? WHERE id=?", (estado, corrida_id))

    def set_duracion(self, corrida_id: int, duracion_ms: int) -> None:
        with self.connect() as conn:
            conn.execute("UPDATE corrida SET duracion_ms=? WHERE id=?",
                         (int(duracion_ms), int(corrida_id)))

    def set_modo(self, corrida_id: int, modo: str) -> None:
        with self.connect() as conn:
            conn.execute("UPDATE corrida SET modo=? WHERE id=?", (modo, int(corrida_id)))

    def set_nombre(self, corrida_id: int, nombre: str) -> None:
        with self.connect() as conn:
            conn.execute("UPDATE corrida SET nombre=? WHERE id=?",
                         (nombre, int(corrida_id)))

    def set_carpeta(self, corrida_id: int, carpeta_id: int, conn=None) -> None:
        sql = "UPDATE corrida SET carpeta_id=? WHERE id=?"
        params = (int(carpeta_id), int(corrida_id))
        if conn is not None:
            conn.execute(sql, params); return
        with self.connect() as c:
            c.execute(sql, params)

    def set_snapshot(self, corrida_id: int, seq: int, payload: dict) -> None:
        with self.connect() as conn:
            conn.execute(
                "UPDATE corrida_item SET snapshot_json=? WHERE corrida_id=? AND seq=?",
                (json.dumps(payload, ensure_ascii=False), int(corrida_id), int(seq)))

    def get_snapshots(self, corrida_id: int) -> dict[int, dict]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT seq, snapshot_json FROM corrida_item "
                "WHERE corrida_id=? AND snapshot_json IS NOT NULL", (int(corrida_id),)).fetchall()
        return {r["seq"]: json.loads(r["snapshot_json"]) for r in rows}

    def set_revision(self, corrida_id: int, seq: int, payload: Optional[dict]) -> None:
        """Guarda (o borra, con payload=None) el veredicto de la IA de una fila."""
        with self.connect() as conn:
            conn.execute(
                "UPDATE corrida_item SET revision_json=? WHERE corrida_id=? AND seq=?",
                (None if payload is None else json.dumps(payload, ensure_ascii=False),
                 int(corrida_id), int(seq)))

    def set_costo_manual(self, corrida_id: int, costos: dict[int, float], conn=None) -> None:
        """Fija el costo unitario a mano de varias filas y las deja en `confirmed`.

        `costos` es {seq: costo}. Es UNA acción del usuario ("estas filas las resuelvo
        así"), así que es una escritura por lote: el status va junto porque la fila
        quedó resuelta a propósito y seguir contándola en "en revisión" mentiría en
        los totales. Poner el costo a mano ES un confirm, por la misma razón que lo
        es `actualizar_eleccion`: borra `revision_json` porque el veredicto hablaba
        de una fila que ya no es esta."""
        if not costos:
            return
        filas = [(float(c), int(corrida_id), int(s)) for s, c in costos.items()]
        sql = ("UPDATE corrida_item SET costo_manual=?, status='confirmed', "
               "revision_json=NULL "
               "WHERE corrida_id=? AND seq=?")
        if conn is not None:
            conn.executemany(sql, filas)
            return
        with self.connect() as c:
            c.executemany(sql, filas)

    def set_plan(self, corrida_id: int, plan_json: str, conn=None) -> None:
        sql = "UPDATE corrida SET plan_json=? WHERE id=?"
        if conn is not None:
            conn.execute(sql, (plan_json, int(corrida_id)))
            return
        with self.connect() as c:
            c.execute(sql, (plan_json, int(corrida_id)))

    def get_plan(self, corrida_id: int) -> Optional[str]:
        with self.connect() as conn:
            r = conn.execute("SELECT plan_json FROM corrida WHERE id=?",
                             (int(corrida_id),)).fetchone()
        return r["plan_json"] if r else None

    def set_origen(self, corrida_id: int, origen_json: str, conn=None) -> None:
        """Guarda el origen de importación. Se escribe UNA vez, al crear la corrida.

        Escritura aparte y no dentro del INSERT, por la misma razón que `set_plan`: no
        ensucia el `crear_corrida` de los dos backends con una columna opcional.
        """
        sql = "UPDATE corrida SET origen_json=? WHERE id=?"
        if conn is not None:
            conn.execute(sql, (origen_json, int(corrida_id)))
            return
        with self.connect() as c:
            c.execute(sql, (origen_json, int(corrida_id)))

    def get_origen(self, corrida_id: int) -> Optional[str]:
        """El JSON crudo del origen, o None si la corrida es anterior a la ruta IDU."""
        with self.connect() as conn:
            r = conn.execute("SELECT origen_json FROM corrida WHERE id=?",
                             (int(corrida_id),)).fetchone()
        return r["origen_json"] if r else None

    def max_seq(self, corrida_id: int) -> int:
        with self.connect() as conn:
            r = conn.execute("SELECT MAX(seq) AS m FROM corrida_item WHERE corrida_id=?",
                             (int(corrida_id),)).fetchone()
        return -1 if (r is None or r["m"] is None) else int(r["m"])

    # ---- la cola del armado (corrida.estado == 'armando' ES la cola) ----
    def reclamar_armado(self, instancia: str, ahora: str,
                        limite_vencimiento: str) -> Optional[int]:
        with self.connect() as conn:
            r = conn.execute(
                "SELECT id FROM corrida "
                " WHERE estado='armando' "
                "   AND (armando_desde IS NULL OR armando_desde < ?) "
                # El desempate `, id ASC` no lo puede cazar ningún test: con dos
                # corridas del mismo segundo, el orden de un empate es INDEFINIDO y
                # los dos motores hoy devuelven el de inserción, que da la misma
                # respuesta. Está igual porque "indefinido" cambia con el plan, un
                # índice nuevo o una versión de Postgres, y `posicion_en_cola` promete
                # el MISMO orden: sin el desempate, la pantalla puede decir un puesto
                # y la reclama servir otro. No lo borres porque "ningún test lo cubre".
                " ORDER BY creada_en ASC, id ASC LIMIT 1",
                (limite_vencimiento,)).fetchone()
            if r is None:
                return None
            cid = int(r["id"])
            # El WHERE se repite entero: entre el SELECT y el UPDATE otro worker pudo
            # haberla reclamado. Si rowcount es 0, la perdimos y no devolvemos nada.
            # Volvemos con las manos vacías aunque quede más cola atrás, a propósito:
            # el worker cicla y en la vuelta siguiente agarra la que sigue. Reintentar
            # acá sería un bucle de reintentos escondido adentro de un método de datos.
            cur = conn.execute(
                "UPDATE corrida "
                "   SET armando_por=?, armando_desde=?, intentos=intentos+1 "
                " WHERE id=? AND estado='armando' "
                "   AND (armando_desde IS NULL OR armando_desde < ?)",
                (instancia, ahora, cid, limite_vencimiento))
            return cid if cur.rowcount > 0 else None

    # Fencing: con `instancia` el UPDATE solo aplica si esa instancia SIGUE siendo la
    # dueña. Sin esto, un worker viejo que ya perdió la reclama (venció durante un
    # deploy) le suelta la del dueño nuevo. Opcional porque el camino sincrónico
    # (CLI/GUI) arma sin que nadie haya reclamado: ahí no hay dueño que verificar.
    @staticmethod
    def _fencing(instancia: Optional[str]) -> tuple[str, list[str]]:
        return ("", []) if instancia is None else (" AND armando_por=?", [instancia])

    def latir_armado(self, corrida_id: int, ahora: str,
                     instancia: Optional[str] = None) -> bool:
        dueno, extra = self._fencing(instancia)
        with self.connect() as conn:
            cur = conn.execute(f"UPDATE corrida SET armando_desde=? WHERE id=?{dueno}",
                               [ahora, int(corrida_id)] + extra)
            return cur.rowcount > 0

    def finalizar_armado(self, corrida_id: int, estado: str,
                         duracion_ms: Optional[int] = None,
                         error: Optional[str] = None,
                         instancia: Optional[str] = None) -> bool:
        dueno, extra = self._fencing(instancia)
        with self.connect() as conn:
            cur = conn.execute(
                # COALESCE en la duración y no en el error a propósito: duracion_ms=None
                # es "no la sé" (la de antes vale), error=None es "ya no hay error".
                "UPDATE corrida "
                "   SET estado=?, armando_por=NULL, armando_desde=NULL, "
                "       duracion_ms=COALESCE(?, duracion_ms), ultimo_error=? "
                f" WHERE id=?{dueno}",
                [estado, duracion_ms, error, int(corrida_id)] + extra)
            return cur.rowcount > 0

    def reencolar_armado(self, corrida_id: int) -> None:
        with self.connect() as conn:
            conn.execute(
                "UPDATE corrida "
                "   SET estado='armando', intentos=0, ultimo_error=NULL, "
                "       armando_por=NULL, armando_desde=NULL "
                " WHERE id=?", (int(corrida_id),))

    def posicion_en_cola(self, corrida_id: int) -> int:
        with self.connect() as conn:
            r = conn.execute(
                # Mismo criterio de orden que la reclama (creada_en, id): si acá se
                # desempatara distinto, la pantalla diría un puesto y se serviría otro.
                "SELECT COUNT(*) AS n FROM corrida "
                " WHERE estado='armando' AND (creada_en, id) < "
                "       (SELECT creada_en, id FROM corrida WHERE id=?)",
                (int(corrida_id),)).fetchone()
        return int(r["n"])      # un COUNT(*) sin GROUP BY siempre trae exactamente 1 fila

    # ---- lectura ----
    def _row_to_item(self, r: sqlite3.Row) -> CorridaItemRow:
        return CorridaItemRow(
            seq=r["seq"], item=LicitacionItem(**json.loads(r["item_json"])),
            status=r["status"], apu_codigo=r["apu_codigo"],
            apu_nombre=r["apu_nombre"] or "", unidad=r["unidad"] or "",
            shift=r["shift"] or "", origen=r["origen"] or "historico",
            confianza=r["confianza"] or 0.0, explicacion=r["explicacion"] or "",
            componentes=json.loads(r["componentes_json"] or "[]"),
            candidatos=json.loads(r["candidatos_json"] or "[]"),
            revision=(json.loads(r["revision_json"]) if r["revision_json"] else None),
            costo_manual=(None if r["costo_manual"] is None else float(r["costo_manual"])))

    def _row_to_meta(self, r: sqlite3.Row) -> CorridaMeta:
        return CorridaMeta(
            id=r["id"], creada_en=r["creada_en"], archivo=r["archivo"],
            turno_def=r["turno_def"],
            use_ai=None if r["use_ai"] is None else bool(r["use_ai"]),
            estado=r["estado"], cuadro_path=r["cuadro_path"],
            duracion_ms=r["duracion_ms"], modo=(r["modo"] or "activa"),
            carpeta_id=(r["carpeta_id"] if "carpeta_id" in r.keys() else None),
            nombre=((r["nombre"] if "nombre" in r.keys() else None) or r["archivo"]),
            lista_precios_id=(r["lista_precios_id"] if "lista_precios_id" in r.keys() else None),
            intentos=(r["intentos"] if "intentos" in r.keys() else 0) or 0,
            ultimo_error=(r["ultimo_error"] if "ultimo_error" in r.keys() else None),
            armando_por=(r["armando_por"] if "armando_por" in r.keys() else None),
            armando_desde=(r["armando_desde"] if "armando_desde" in r.keys() else None),
            origen=_json_o_none(
                r["origen_json"] if "origen_json" in r.keys() else None))

    # Columnas explícitas y NO `SELECT *`: `plan_json` pesa ~400 KB en una corrida de
    # 1900 ítems y este listado trae TODAS las corridas. Con `*`, abrir "Mis corridas"
    # arrastraría decenas de MB que nadie mira.
    _COLS_META = ("id, creada_en, archivo, turno_def, use_ai, estado, cuadro_path, "
                  "duracion_ms, modo, carpeta_id, nombre, lista_precios_id, "
                  "intentos, ultimo_error, armando_por, armando_desde, origen_json")

    def get_corrida(self, corrida_id: int) -> Optional[CorridaMeta]:
        with self.connect() as conn:
            # `_COLS_META` y no `SELECT *`: `plan_json` son ~400 KB en una corrida de
            # 1900 ítems, y esta lectura corre en CADA poll de la pantalla mientras
            # arma (~4,8 MB/min por pestaña abierta, ~860 MB en un armado de 3 h) para
            # que `_row_to_meta` lo tire sin mirarlo. En Supabase eso es egress que se
            # paga. El total de líneas del plan se cuenta en el servicio, una vez.
            r = conn.execute(f"SELECT {self._COLS_META} FROM corrida WHERE id=?",
                             (corrida_id,)).fetchone()
        return self._row_to_meta(r) if r else None

    def listar_corridas(self) -> list[CorridaMeta]:
        with self.connect() as conn:
            rows = conn.execute(
                f"SELECT {self._COLS_META} FROM corrida "
                "ORDER BY creada_en DESC, id DESC").fetchall()
        return [self._row_to_meta(r) for r in rows]

    def eliminar_corrida(self, corrida_id: int, conn=None) -> bool:
        if conn is not None:
            cur = conn.execute("DELETE FROM corrida WHERE id=?", (int(corrida_id),))
            return cur.rowcount > 0
        with self.connect() as c:
            cur = c.execute("DELETE FROM corrida WHERE id=?", (int(corrida_id),))
            return cur.rowcount > 0

    def get_items(self, corrida_id: int) -> list[CorridaItemRow]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM corrida_item WHERE corrida_id=? ORDER BY seq",
                (corrida_id,)).fetchall()
        return [self._row_to_item(r) for r in rows]

    def get_item(self, corrida_id: int, seq: int) -> Optional[CorridaItemRow]:
        with self.connect() as conn:
            r = conn.execute(
                "SELECT * FROM corrida_item WHERE corrida_id=? AND seq=?",
                (corrida_id, seq)).fetchone()
        return self._row_to_item(r) if r else None

    def counts(self) -> dict[str, int]:
        with self.connect() as conn:
            return {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                    for t in ("corrida", "corrida_item")}

    def contar_items_por_apu(self, apu_codigo: str) -> int:
        with self.connect() as conn:
            return conn.execute(
                "SELECT COUNT(*) FROM corrida_item WHERE apu_codigo = ?",
                (str(apu_codigo),)).fetchone()[0]
