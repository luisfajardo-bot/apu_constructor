-- Esquema Postgres de precios (Supabase). Equivalente a db/precios.sql.
CREATE SCHEMA IF NOT EXISTS precios;

CREATE TABLE IF NOT EXISTS precios.insumos (
    id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    codigo      TEXT NOT NULL,
    nombre      TEXT NOT NULL,
    nombre_norm TEXT NOT NULL,
    unidad      TEXT,
    grupo       TEXT,
    UNIQUE (codigo, nombre_norm)
);
CREATE INDEX IF NOT EXISTS idx_insumo_cod ON precios.insumos(codigo);

CREATE TABLE IF NOT EXISTS precios.insumo_precios (
    id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    insumo_id     BIGINT NOT NULL REFERENCES precios.insumos(id) ON DELETE CASCADE,
    precio        DOUBLE PRECISION NOT NULL,
    fuente        TEXT,
    clasificacion TEXT,
    fecha         TEXT,
    vigente       INTEGER NOT NULL DEFAULT 1,
    creado_por    TEXT
);
CREATE INDEX IF NOT EXISTS idx_precio_ins ON precios.insumo_precios(insumo_id, vigente);

CREATE TABLE IF NOT EXISTS precios.meta (
    clave TEXT PRIMARY KEY,
    valor TEXT
);

-- Esquema Postgres de apus (Supabase). Equivalente a db/apus.sql.
CREATE SCHEMA IF NOT EXISTS apus;

CREATE TABLE IF NOT EXISTS apus.apus (
    codigo TEXT NOT NULL,
    shift  TEXT NOT NULL,
    nombre TEXT NOT NULL,
    unidad TEXT,
    grupo  TEXT,
    PRIMARY KEY (codigo, shift)
);
CREATE INDEX IF NOT EXISTS idx_apus_nombre ON apus.apus(nombre);

CREATE TABLE IF NOT EXISTS apus.apu_componentes (
    apu_codigo            TEXT NOT NULL,
    shift                 TEXT NOT NULL,
    seq                   INTEGER NOT NULL,
    insumo_codigo         TEXT,
    insumo_nombre         TEXT,
    unidad                TEXT,
    rendimiento           DOUBLE PRECISION,
    precio_unitario_hist  DOUBLE PRECISION,
    PRIMARY KEY (apu_codigo, shift, seq),
    FOREIGN KEY (apu_codigo, shift) REFERENCES apus.apus(codigo, shift)
);
CREATE INDEX IF NOT EXISTS idx_comp_apu ON apus.apu_componentes(apu_codigo, shift);

CREATE TABLE IF NOT EXISTS apus.meta (
    clave TEXT PRIMARY KEY,
    valor TEXT
);

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
    creado_por    TEXT
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
    candidatos_json  TEXT
);
CREATE INDEX IF NOT EXISTS ix_corrida_item ON corridas.corrida_item(corrida_id, seq);
