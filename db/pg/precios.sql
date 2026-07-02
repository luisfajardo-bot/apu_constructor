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
    -- NOTA (drift vs SQLite): db/precios.sql no tiene ON DELETE CASCADE. Hoy inocuo
    -- (nadie borra insumos); reconciliar ambos esquemas si se añade borrado de insumos.
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
