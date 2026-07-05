-- Esquema Postgres de corridas (Supabase). Equivalente a db/corridas.sql.
CREATE SCHEMA IF NOT EXISTS corridas;

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
    modo          TEXT NOT NULL DEFAULT 'activa'
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

-- Migración idempotente para bases existentes (CorridasPg.init_schema corre este script en cada boot).
ALTER TABLE corridas.corrida ADD COLUMN IF NOT EXISTS modo TEXT NOT NULL DEFAULT 'activa';
ALTER TABLE corridas.corrida_item ADD COLUMN IF NOT EXISTS snapshot_json TEXT;
