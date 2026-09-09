"""Backend Postgres de corridas. Implementa RepositorioCorridas. Port de corridas_db.py."""
from __future__ import annotations

import json
import logging
from dataclasses import asdict
from typing import Optional

import psycopg

from apu_tool import config
from apu_tool.datos.pg.conexion import Conexion, ejecutar_script
from apu_tool.datos.repositorio import CorridaEliminada
from apu_tool.nucleo.models import CorridaItemRow, CorridaMeta, LicitacionItem

logger = logging.getLogger(__name__)

SCHEMA_PATH = config.PROJECT_ROOT / "db" / "pg" / "corridas.sql"


class CorridasPg:
    def __init__(self, cx: Conexion):
        self.cx = cx

    def init_schema(self) -> None:
        self.cx.ejecutar_migracion(SCHEMA_PATH.read_text(encoding="utf-8"))
        self._crear_indice_seq()

    def _crear_indice_seq(self) -> None:
        """El índice único de (corrida_id, seq), fuera del script del esquema.

        En su PROPIA conexión a propósito: si el CREATE falla, Postgres aborta la
        transacción entera y cualquier sentencia posterior en la MISMA conexión
        fallaría también, sin tener nada que ver. Aislado acá, la falla no ensucia
        nada más.

        Va aparte y con `try` porque una base vieja puede traer duplicados de armados
        muertos: ahí el índice no se puede crear, y eso NO puede impedir que la app
        arranque. Lo llaman `init_schema` Y `reset`: son los dos caminos que dejan el
        esquema listo, y si solo lo hiciera uno, un `seed --force` borraría la
        protección sin que nadie se entere.
        """
        try:
            with self.cx.connection() as conn:
                conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS ux_corrida_item_seq "
                             "ON corridas.corrida_item(corrida_id, seq)")
        except psycopg.errors.UniqueViolation:
            logger.error(
                "No se pudo crear ux_corrida_item_seq: hay (corrida_id, seq) "
                "duplicados. El armado reanudable no esta protegido hasta "
                "limpiarlos. Consulta: SELECT corrida_id, seq, COUNT(*) FROM "
                "corridas.corrida_item GROUP BY 1,2 HAVING COUNT(*) > 1;")

    def reset(self) -> None:
        with self.cx.connection() as conn:
            conn.execute("DROP SCHEMA IF EXISTS corridas CASCADE")
            ejecutar_script(conn, SCHEMA_PATH.read_text(encoding="utf-8"))
        self._crear_indice_seq()

    _INSERT_ITEM_SQL = (
        "INSERT INTO corridas.corrida_item "
        "(corrida_id, seq, item_json, status, apu_codigo, apu_nombre, unidad, "
        " shift, origen, confianza, explicacion, componentes_json, candidatos_json) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)")

    @staticmethod
    def _item_tuple(corrida_id: int, it: CorridaItemRow) -> tuple:
        return (corrida_id, it.seq, json.dumps(asdict(it.item), ensure_ascii=False),
                it.status, it.apu_codigo, it.apu_nombre, it.unidad, it.shift,
                it.origen, it.confianza, it.explicacion,
                json.dumps(it.componentes, ensure_ascii=False),
                json.dumps(it.candidatos, ensure_ascii=False))

    def _insert_corrida(self, conn, meta: CorridaMeta) -> int:
        cur = conn.execute(
            "INSERT INTO corridas.corrida (creada_en, archivo, turno_def, use_ai, estado, "
            "cuadro_path, duracion_ms, modo, carpeta_id, nombre, lista_precios_id) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id",
            (meta.creada_en, meta.archivo, meta.turno_def,
             None if meta.use_ai is None else int(meta.use_ai),
             meta.estado, meta.cuadro_path, meta.duracion_ms, meta.modo,
             meta.carpeta_id, meta.nombre, meta.lista_precios_id))
        return int(cur.fetchone()["id"])

    def crear_corrida(self, meta: CorridaMeta) -> int:
        with self.cx.connection() as conn:
            return self._insert_corrida(conn, meta)

    def guardar_items(self, corrida_id: int, items: list[CorridaItemRow]) -> int:
        rows = [self._item_tuple(corrida_id, it) for it in items]
        with self.cx.connection() as conn, conn.cursor() as cur:
            cur.executemany(self._INSERT_ITEM_SQL, rows)
        return len(rows)

    def agregar_item(self, corrida_id: int, fila: CorridaItemRow) -> None:
        try:
            with self.cx.connection() as conn:
                conn.execute(self._INSERT_ITEM_SQL, self._item_tuple(corrida_id, fila))
        except psycopg.errors.ForeignKeyViolation as e:
            raise CorridaEliminada(corrida_id) from e

    def borrar_items(self, corrida_id: int, seqs, conn=None) -> int:
        lista = [int(s) for s in seqs]
        if not lista:
            return 0
        sql = "DELETE FROM corridas.corrida_item WHERE corrida_id=%s AND seq = ANY(%s)"
        params = (int(corrida_id), lista)
        if conn is not None:
            return conn.execute(sql, params).rowcount
        with self.cx.connection() as c:
            return c.execute(sql, params).rowcount

    def actualizar_eleccion(self, corrida_id: int, seq: int, *, status: str,
                            apu_codigo: Optional[str], apu_nombre: str, unidad: str,
                            shift: str, origen: str, confianza: float,
                            explicacion: str, componentes: list[dict]) -> None:
        with self.cx.connection() as conn:
            conn.execute(
                # El APU cambió: el veredicto de la IA hablaba del anterior, y un costo
                # puesto a mano ya no manda (la fila volvió a tener composición real).
                # Se borran acá, el único punto por el que pasa un cambio del APU elegido.
                "UPDATE corridas.corrida_item SET status=%s, apu_codigo=%s, apu_nombre=%s, "
                "unidad=%s, shift=%s, origen=%s, confianza=%s, explicacion=%s, "
                "componentes_json=%s, revision_json=NULL, costo_manual=NULL "
                "WHERE corrida_id=%s AND seq=%s",
                (status, apu_codigo, apu_nombre, unidad, shift, origen, confianza,
                 explicacion, json.dumps(componentes, ensure_ascii=False),
                 corrida_id, seq))

    def set_cuadro(self, corrida_id: int, path: str) -> None:
        with self.cx.connection() as conn:
            conn.execute("UPDATE corridas.corrida SET cuadro_path=%s WHERE id=%s",
                         (path, corrida_id))

    def set_estado(self, corrida_id: int, estado: str) -> None:
        with self.cx.connection() as conn:
            conn.execute("UPDATE corridas.corrida SET estado=%s WHERE id=%s",
                         (estado, corrida_id))

    def set_duracion(self, corrida_id: int, duracion_ms: int) -> None:
        with self.cx.connection() as conn:
            conn.execute("UPDATE corridas.corrida SET duracion_ms=%s WHERE id=%s",
                         (int(duracion_ms), int(corrida_id)))

    def set_modo(self, corrida_id: int, modo: str) -> None:
        with self.cx.connection() as conn:
            conn.execute("UPDATE corridas.corrida SET modo=%s WHERE id=%s",
                         (modo, int(corrida_id)))

    def set_nombre(self, corrida_id: int, nombre: str) -> None:
        with self.cx.connection() as conn:
            conn.execute("UPDATE corridas.corrida SET nombre=%s WHERE id=%s",
                         (nombre, int(corrida_id)))

    def set_carpeta(self, corrida_id: int, carpeta_id: int, conn=None) -> None:
        sql = "UPDATE corridas.corrida SET carpeta_id=%s WHERE id=%s"
        params = (int(carpeta_id), int(corrida_id))
        if conn is not None:
            conn.execute(sql, params); return
        with self.cx.connection() as c:
            c.execute(sql, params)

    def set_snapshot(self, corrida_id: int, seq: int, payload: dict) -> None:
        with self.cx.connection() as conn:
            conn.execute(
                "UPDATE corridas.corrida_item SET snapshot_json=%s WHERE corrida_id=%s AND seq=%s",
                (json.dumps(payload, ensure_ascii=False), int(corrida_id), int(seq)))

    def get_snapshots(self, corrida_id: int) -> dict[int, dict]:
        with self.cx.connection() as conn:
            rows = conn.execute(
                "SELECT seq, snapshot_json FROM corridas.corrida_item "
                "WHERE corrida_id=%s AND snapshot_json IS NOT NULL", (int(corrida_id),)).fetchall()
        return {r["seq"]: json.loads(r["snapshot_json"]) for r in rows}

    def set_revision(self, corrida_id: int, seq: int, payload: Optional[dict]) -> None:
        """Guarda (o borra, con payload=None) el veredicto de la IA de una fila."""
        with self.cx.connection() as conn:
            conn.execute(
                "UPDATE corridas.corrida_item SET revision_json=%s "
                "WHERE corrida_id=%s AND seq=%s",
                (None if payload is None else json.dumps(payload, ensure_ascii=False),
                 int(corrida_id), int(seq)))

    def set_costo_manual(self, corrida_id: int, costos: dict[int, float], conn=None) -> None:
        """Fija el costo unitario a mano de varias filas y las deja en `confirmed`.
        `costos` es {seq: costo}. Poner el costo a mano ES un confirm: borra
        `revision_json` (ver el docstring del contrato en repositorio.py)."""
        if not costos:
            return
        filas = [(float(c), int(corrida_id), int(s)) for s, c in costos.items()]
        sql = ("UPDATE corridas.corrida_item SET costo_manual=%s, status='confirmed', "
               "revision_json=NULL "
               "WHERE corrida_id=%s AND seq=%s")
        if conn is not None:
            with conn.cursor() as cur:
                cur.executemany(sql, filas)
            return
        with self.cx.connection() as c, c.cursor() as cur:
            cur.executemany(sql, filas)

    def set_plan(self, corrida_id: int, plan_json: str, conn=None) -> None:
        sql = "UPDATE corridas.corrida SET plan_json=%s WHERE id=%s"
        if conn is not None:
            conn.execute(sql, (plan_json, int(corrida_id)))
            return
        with self.cx.connection() as c:
            c.execute(sql, (plan_json, int(corrida_id)))

    def get_plan(self, corrida_id: int) -> Optional[str]:
        with self.cx.connection() as conn:
            r = conn.execute("SELECT plan_json FROM corridas.corrida WHERE id=%s",
                             (int(corrida_id),)).fetchone()
        return r["plan_json"] if r else None

    def max_seq(self, corrida_id: int) -> int:
        with self.cx.connection() as conn:
            r = conn.execute(
                "SELECT MAX(seq) AS m FROM corridas.corrida_item WHERE corrida_id=%s",
                (int(corrida_id),)).fetchone()
        return -1 if (r is None or r["m"] is None) else int(r["m"])

    # ---- la cola del armado (corrida.estado == 'armando' ES la cola) ----
    def reclamar_armado(self, instancia: str, ahora: str,
                        limite_vencimiento: str) -> Optional[int]:
        with self.cx.connection() as conn:
            r = conn.execute(
                "SELECT id FROM corridas.corrida "
                " WHERE estado='armando' "
                "   AND (armando_desde IS NULL OR armando_desde < %s) "
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
            # En READ COMMITTED (lo que usa Supabase) esto alcanza: si el otro worker
            # ya tomó el lock de la fila, este UPDATE espera y, al soltarse, Postgres
            # RE-EVALÚA el WHERE contra la versión nueva —que ya tiene armando_desde
            # fresco— y no la toca. El perdedor sale con rowcount 0, sin sumar intentos.
            cur = conn.execute(
                "UPDATE corridas.corrida "
                "   SET armando_por=%s, armando_desde=%s, intentos=intentos+1 "
                " WHERE id=%s AND estado='armando' "
                "   AND (armando_desde IS NULL OR armando_desde < %s)",
                (instancia, ahora, cid, limite_vencimiento))
            return cid if cur.rowcount > 0 else None

    # Fencing: con `instancia` el UPDATE solo aplica si esa instancia SIGUE siendo la
    # dueña. Sin esto, un worker viejo que ya perdió la reclama (venció durante un
    # deploy) le suelta la del dueño nuevo. Opcional porque el camino sincrónico
    # (CLI/GUI) arma sin que nadie haya reclamado: ahí no hay dueño que verificar.
    @staticmethod
    def _fencing(instancia: Optional[str]) -> tuple[str, list[str]]:
        return ("", []) if instancia is None else (" AND armando_por=%s", [instancia])

    def latir_armado(self, corrida_id: int, ahora: str,
                     instancia: Optional[str] = None) -> bool:
        dueno, extra = self._fencing(instancia)
        with self.cx.connection() as conn:
            cur = conn.execute(
                f"UPDATE corridas.corrida SET armando_desde=%s WHERE id=%s{dueno}",
                [ahora, int(corrida_id)] + extra)
            return cur.rowcount > 0

    def finalizar_armado(self, corrida_id: int, estado: str,
                         duracion_ms: Optional[int] = None,
                         error: Optional[str] = None,
                         instancia: Optional[str] = None) -> bool:
        dueno, extra = self._fencing(instancia)
        with self.cx.connection() as conn:
            cur = conn.execute(
                # COALESCE en la duración y no en el error a propósito: duracion_ms=None
                # es "no la sé" (la de antes vale), error=None es "ya no hay error".
                # Sin cast a propósito: psycopg manda el NULL sin tipo y Postgres lo
                # resuelve por el otro brazo del COALESCE (integer). Verificado contra
                # un Postgres real; poner ::integer sería una diferencia sin motivo.
                "UPDATE corridas.corrida "
                "   SET estado=%s, armando_por=NULL, armando_desde=NULL, "
                "       duracion_ms=COALESCE(%s, duracion_ms), ultimo_error=%s "
                f" WHERE id=%s{dueno}",
                [estado, duracion_ms, error, int(corrida_id)] + extra)
            return cur.rowcount > 0

    def reencolar_armado(self, corrida_id: int) -> None:
        with self.cx.connection() as conn:
            conn.execute(
                "UPDATE corridas.corrida "
                "   SET estado='armando', intentos=0, ultimo_error=NULL, "
                "       armando_por=NULL, armando_desde=NULL "
                " WHERE id=%s", (int(corrida_id),))

    def posicion_en_cola(self, corrida_id: int) -> int:
        with self.cx.connection() as conn:
            r = conn.execute(
                # Mismo criterio de orden que la reclama (creada_en, id): si acá se
                # desempatara distinto, la pantalla diría un puesto y se serviría otro.
                # La comparación de tuplas contra una subconsulta de una sola fila es
                # la misma forma en los dos motores; con la corrida inexistente da NULL
                # y no cuenta nada, igual que en SQLite.
                "SELECT COUNT(*) AS n FROM corridas.corrida "
                " WHERE estado='armando' AND (creada_en, id) < "
                "       (SELECT creada_en, id FROM corridas.corrida WHERE id=%s)",
                (int(corrida_id),)).fetchone()
        return int(r["n"])      # un COUNT(*) sin GROUP BY siempre trae exactamente 1 fila

    # ---- lectura ----
    def _row_to_item(self, r) -> CorridaItemRow:
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

    def _row_to_meta(self, r) -> CorridaMeta:
        return CorridaMeta(
            id=r["id"], creada_en=r["creada_en"], archivo=r["archivo"],
            turno_def=r["turno_def"],
            use_ai=None if r["use_ai"] is None else bool(r["use_ai"]),
            estado=r["estado"], cuadro_path=r["cuadro_path"],
            duracion_ms=r["duracion_ms"], modo=(r["modo"] or "activa"),
            carpeta_id=r["carpeta_id"],
            nombre=(r["nombre"] or r["archivo"]),
            lista_precios_id=r.get("lista_precios_id"),
            intentos=r.get("intentos") or 0,
            ultimo_error=r.get("ultimo_error"),
            armando_por=r.get("armando_por"),
            armando_desde=r.get("armando_desde"))

    # Columnas explícitas y NO `SELECT *`: `plan_json` pesa ~400 KB en una corrida de
    # 1900 ítems y este listado trae TODAS las corridas. Con `*`, abrir "Mis corridas"
    # arrastraría decenas de MB que nadie mira.
    _COLS_META = ("id, creada_en, archivo, turno_def, use_ai, estado, cuadro_path, "
                  "duracion_ms, modo, carpeta_id, nombre, lista_precios_id, "
                  "intentos, ultimo_error, armando_por, armando_desde")

    def get_corrida(self, corrida_id: int) -> Optional[CorridaMeta]:
        with self.cx.connection() as conn:
            # Mismo motivo que en SQLite: `plan_json` son ~400 KB y esta lectura
            # corre en cada poll mientras arma, para tirarlo. Acá el egress se paga.
            r = conn.execute(f"SELECT {self._COLS_META} FROM corridas.corrida WHERE id=%s",
                             (corrida_id,)).fetchone()
        return self._row_to_meta(r) if r else None

    def listar_corridas(self) -> list[CorridaMeta]:
        with self.cx.connection() as conn:
            rows = conn.execute(
                f"SELECT {self._COLS_META} FROM corridas.corrida "
                "ORDER BY creada_en DESC, id DESC").fetchall()
        return [self._row_to_meta(r) for r in rows]

    def eliminar_corrida(self, corrida_id: int, conn=None) -> bool:
        if conn is not None:
            cur = conn.execute("DELETE FROM corridas.corrida WHERE id=%s", (int(corrida_id),))
            return cur.rowcount > 0
        with self.cx.connection() as c:
            cur = c.execute("DELETE FROM corridas.corrida WHERE id=%s", (int(corrida_id),))
            return cur.rowcount > 0

    def get_items(self, corrida_id: int) -> list[CorridaItemRow]:
        with self.cx.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM corridas.corrida_item WHERE corrida_id=%s ORDER BY seq",
                (corrida_id,)).fetchall()
        return [self._row_to_item(r) for r in rows]

    def get_item(self, corrida_id: int, seq: int) -> Optional[CorridaItemRow]:
        with self.cx.connection() as conn:
            r = conn.execute(
                "SELECT * FROM corridas.corrida_item WHERE corrida_id=%s AND seq=%s",
                (corrida_id, seq)).fetchone()
        return self._row_to_item(r) if r else None

    def counts(self) -> dict[str, int]:
        with self.cx.connection() as conn:
            return {t: conn.execute(f"SELECT COUNT(*) AS n FROM corridas.{t}").fetchone()["n"]
                    for t in ("corrida", "corrida_item")}

    def contar_items_por_apu(self, apu_codigo: str) -> int:
        with self.cx.connection() as conn:
            return conn.execute(
                "SELECT COUNT(*) AS n FROM corridas.corrida_item WHERE apu_codigo = %s",
                (str(apu_codigo),)).fetchone()["n"]
