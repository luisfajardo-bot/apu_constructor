CREATE TABLE IF NOT EXISTS corrida (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  creada_en     TEXT NOT NULL,
  archivo       TEXT NOT NULL,
  turno_def     TEXT NOT NULL,
  use_ai        INTEGER,
  estado        TEXT NOT NULL,
  cuadro_path   TEXT
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
  candidatos_json  TEXT
);

CREATE INDEX IF NOT EXISTS ix_corrida_item ON corrida_item(corrida_id, seq);
