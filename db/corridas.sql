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
  carpeta_id    INTEGER REFERENCES carpeta(id) ON DELETE RESTRICT
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
