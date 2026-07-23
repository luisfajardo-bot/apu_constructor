-- Esquema Postgres de corridas (Supabase). Equivalente a db/corridas.sql.
CREATE SCHEMA IF NOT EXISTS corridas;

CREATE TABLE IF NOT EXISTS corridas.carpeta (
    id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    nombre        TEXT NOT NULL,
    parent_id     BIGINT REFERENCES corridas.carpeta(id) ON DELETE RESTRICT,
    creada_en     TEXT NOT NULL,
    creado_por    TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_carpeta_hermanas
    ON corridas.carpeta(COALESCE(parent_id, 0), nombre);

CREATE TABLE IF NOT EXISTS corridas.corrida (
    id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    creada_en     TEXT NOT NULL,
    archivo       TEXT NOT NULL,
    turno_def     TEXT NOT NULL,
    use_ai        SMALLINT,
    estado        TEXT NOT NULL,
    cuadro_path   TEXT,
    duracion_ms   INTEGER,
    creado_por    TEXT,
    modo          TEXT NOT NULL DEFAULT 'activa',
    carpeta_id    BIGINT REFERENCES corridas.carpeta(id) ON DELETE RESTRICT,
    nombre        TEXT
);

CREATE TABLE IF NOT EXISTS corridas.corrida_item (
    id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    corrida_id    BIGINT NOT NULL REFERENCES corridas.corrida(id) ON DELETE CASCADE,
    seq           INTEGER NOT NULL,
    item_json     TEXT NOT NULL,
    status        TEXT NOT NULL,
    apu_codigo    TEXT,
    apu_nombre    TEXT,
    unidad        TEXT,
    shift         TEXT,
    origen        TEXT,
    confianza     DOUBLE PRECISION,
    explicacion   TEXT,
    componentes_json TEXT,
    candidatos_json  TEXT,
    snapshot_json    TEXT
);
CREATE INDEX IF NOT EXISTS ix_corrida_item ON corridas.corrida_item(corrida_id, seq);

-- Migración idempotente para bases existentes.
ALTER TABLE corridas.corrida ADD COLUMN IF NOT EXISTS modo TEXT NOT NULL DEFAULT 'activa';
ALTER TABLE corridas.corrida_item ADD COLUMN IF NOT EXISTS snapshot_json TEXT;
ALTER TABLE corridas.corrida ADD COLUMN IF NOT EXISTS carpeta_id BIGINT
    REFERENCES corridas.carpeta(id) ON DELETE RESTRICT;
ALTER TABLE corridas.corrida ADD COLUMN IF NOT EXISTS nombre TEXT;
UPDATE corridas.corrida SET nombre = archivo WHERE nombre IS NULL OR nombre = '';

-- Bootstrap "Sin clasificar" + backfill de corridas sin carpeta (idempotente).
INSERT INTO corridas.carpeta (nombre, creada_en)
    SELECT 'Sin clasificar', to_char(now(), 'YYYY-MM-DD"T"HH24:MI:SS')
    WHERE NOT EXISTS (SELECT 1 FROM corridas.carpeta
                      WHERE nombre = 'Sin clasificar' AND parent_id IS NULL);
UPDATE corridas.corrida SET carpeta_id =
    (SELECT id FROM corridas.carpeta WHERE nombre='Sin clasificar' AND parent_id IS NULL)
    WHERE carpeta_id IS NULL;
