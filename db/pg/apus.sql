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
    tipo                  TEXT NOT NULL DEFAULT 'insumo',
    ref_shift             TEXT,
    PRIMARY KEY (apu_codigo, shift, seq),
    FOREIGN KEY (apu_codigo, shift) REFERENCES apus.apus(codigo, shift)
);
CREATE INDEX IF NOT EXISTS idx_comp_apu ON apus.apu_componentes(apu_codigo, shift);

ALTER TABLE apus.apu_componentes ADD COLUMN IF NOT EXISTS tipo TEXT NOT NULL DEFAULT 'insumo';
ALTER TABLE apus.apu_componentes ADD COLUMN IF NOT EXISTS ref_shift TEXT;

CREATE TABLE IF NOT EXISTS apus.meta (
    clave TEXT PRIMARY KEY,
    valor TEXT
);
