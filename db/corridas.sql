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

-- Distancias de acarreo y peaje del proyecto. Una fila por carpeta de nivel 1.
-- Sin fila = comportamiento de siempre (la regla no toca nada).
CREATE TABLE IF NOT EXISTS proyecto_parametros (
  carpeta_id      INTEGER PRIMARY KEY REFERENCES carpeta(id) ON DELETE CASCADE,
  km_botadero     REAL,
  km_mezclas      REAL,
  km_granulares   REAL,
  peaje_aplica    INTEGER,    -- NULL = sin definir, 0 = no hay peaje, 1 = sí
  peaje_valor     REAL,
  actualizado_en  TEXT NOT NULL,
  actualizado_por TEXT
);

-- Excepciones de composición del proyecto. Ganan sobre la regla de transporte.
-- Solo estructura: no guarda dinero.
CREATE TABLE IF NOT EXISTS proyecto_ajuste (
  id                  INTEGER PRIMARY KEY AUTOINCREMENT,
  carpeta_id          INTEGER NOT NULL REFERENCES carpeta(id) ON DELETE CASCADE,
  apu_codigo          TEXT NOT NULL,
  shift               TEXT NOT NULL,
  accion              TEXT NOT NULL,   -- rendimiento | agregar | quitar | reemplazar
  insumo_codigo       TEXT NOT NULL,
  insumo_nombre       TEXT NOT NULL DEFAULT '',
  unidad              TEXT NOT NULL DEFAULT '',
  rendimiento         REAL,
  insumo_nuevo_codigo TEXT,
  insumo_nuevo_nombre TEXT,
  tipo                TEXT NOT NULL DEFAULT 'insumo',
  ref_shift           TEXT NOT NULL DEFAULT '',
  nota                TEXT NOT NULL DEFAULT '',
  creado_en           TEXT NOT NULL,
  creado_por          TEXT,
  UNIQUE (carpeta_id, apu_codigo, shift, accion, insumo_codigo)
);
CREATE INDEX IF NOT EXISTS ix_proyecto_ajuste ON proyecto_ajuste(carpeta_id);

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
  lista_precios_id INTEGER
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
  snapshot_json    TEXT
);

CREATE INDEX IF NOT EXISTS ix_corrida_item ON corrida_item(corrida_id, seq);
