CREATE TABLE IF NOT EXISTS carpeta (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  nombre        TEXT NOT NULL,
  parent_id     INTEGER REFERENCES carpeta(id) ON DELETE RESTRICT,
  creada_en     TEXT NOT NULL,
  creado_por    TEXT
);
-- Unicidad de hermanas: no dos carpetas con el mismo nombre bajo el mismo padre
-- (incluida la raíz; NULL se normaliza a 0 porque UNIQUE trata los NULL como distintos).
CREATE UNIQUE INDEX IF NOT EXISTS ux_carpeta_hermanas
  ON carpeta(COALESCE(parent_id, 0), nombre);

CREATE TABLE IF NOT EXISTS corrida (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  creada_en     TEXT NOT NULL,
  archivo       TEXT NOT NULL,
  turno_def     TEXT NOT NULL,
  use_ai        INTEGER,
  estado        TEXT NOT NULL,
  cuadro_path   TEXT,
  duracion_ms   INTEGER,
  modo          TEXT NOT NULL DEFAULT 'activa',
  carpeta_id    INTEGER REFERENCES carpeta(id) ON DELETE RESTRICT,
  nombre        TEXT,
  -- Tarifa de la corrida. NULL = Principal. Sin FK: lista_precios vive en precios.db,
  -- otro archivo SQLite (mismo trato que corrida_item.apu_codigo). La integridad se
  -- cuida no borrando listas (la API no expone DELETE).
  lista_precios_id INTEGER,
  -- Las líneas ya interpretadas del Excel, en orden. Única fuente de qué falta armar:
  -- el archivo subido no se guarda. OJO: lleva `precio_contractual` dentro, o sea
  -- DINERO, así que esta columna nunca puede viajar en un payload hacia la IA
  -- (invariante #1). El guardián `privacy.assert_no_money` mira nombres de clave.
  plan_json     TEXT,
  -- De dónde salió el presupuesto: entidad, formato, hoja, versión del parser, quién
  -- confirmó la estructura y la conciliación contra el Excel. NULL en toda corrida
  -- anterior a la ruta IDU: eso es "sin clasificación por capítulo", no un error.
  -- OJO: lleva la conciliación —o sea DINERO— adentro, así que esta columna nunca
  -- puede viajar en un payload hacia la IA. Está en privacy._FORBIDDEN_KEYS.
  origen_json   TEXT,
  intentos      INTEGER NOT NULL DEFAULT 0,
  ultimo_error  TEXT,
  armando_por   TEXT,
  armando_desde TEXT
);

CREATE TABLE IF NOT EXISTS corrida_item (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  corrida_id    INTEGER NOT NULL REFERENCES corrida(id) ON DELETE CASCADE,
  seq           INTEGER NOT NULL,
  item_json     TEXT NOT NULL,
  status        TEXT NOT NULL,
  apu_codigo    TEXT,
  apu_nombre    TEXT,
  unidad        TEXT,
  shift         TEXT,
  origen        TEXT,
  confianza     REAL,
  explicacion   TEXT,
  componentes_json TEXT,
  candidatos_json  TEXT,
  snapshot_json    TEXT,
  -- Veredicto de la IA revisora sobre el APU de esta fila. NULL = nunca revisada.
  revision_json    TEXT,
  -- Costo unitario declarado por una persona (proyectos especiales: la actividad vale
  -- lo que dice el contrato y armarle el APU no paga). NULL = costeo normal desde la
  -- composición. Se borra en actualizar_eleccion: si la fila cambia de APU, manda el APU.
  costo_manual     REAL
);

CREATE INDEX IF NOT EXISTS ix_corrida_item ON corrida_item(corrida_id, seq);

-- Expediente de composición asistida: una fila POR VERSIÓN (append-only). La vigente
-- es la de mayor `version`; el historial de correcciones es la tabla entera.
-- SIN dinero a propósito: `actividad_json` guarda la vista des-monetizada del ítem
-- (sin precio_contractual), así la fila completa se puede reinyectar en un payload
-- hacia la IA. No hay columna para razonamiento del modelo.
CREATE TABLE IF NOT EXISTS composicion (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  corrida_id      INTEGER NOT NULL REFERENCES corrida(id) ON DELETE CASCADE,
  seq             INTEGER NOT NULL,
  version         INTEGER NOT NULL,
  estado          TEXT NOT NULL,
  actividad_json  TEXT NOT NULL,
  ficha_json      TEXT,
  propuesta_json  TEXT,
  validacion_json TEXT,
  confianza       TEXT,
  confianza_json  TEXT,
  antecedentes_json TEXT,
  modelo          TEXT,
  prompt_version  TEXT,
  apu_codigo      TEXT,
  apu_turno       TEXT,
  autor           TEXT,
  creada_en       TEXT NOT NULL,
  motivo          TEXT
);
-- La protección del doble clic, y por eso es un índice y no un `if`: las dos
-- peticiones de un doble clic llegan con milisegundos de diferencia y las dos leerían
-- la misma versión vigente. Mismo criterio que ux_corrida_armando_archivo.
CREATE UNIQUE INDEX IF NOT EXISTS ux_composicion_version
  ON composicion(corrida_id, seq, version);
-- Sin índice secundario sobre (corrida_id, seq): `ux_composicion_version` ya lo cubre
-- por prefijo izquierdo, y las dos únicas consultas del repo filtran por esas dos
-- columnas y ordenan por `version`, que es exactamente su forma.
