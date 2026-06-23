-- Esquema canónico de precios.db — catálogo de insumos y libro de precios.
-- SQL portable (SQLite hoy; Postgres luego). Cargado por apu_tool/datos/precios_db.py.

CREATE TABLE IF NOT EXISTS insumos (
    codigo TEXT PRIMARY KEY,
    nombre TEXT NOT NULL,
    unidad TEXT,
    grupo  TEXT
);

CREATE TABLE IF NOT EXISTS insumo_precios (
    -- SQLite autollena un INTEGER PRIMARY KEY (rowid); sin AUTOINCREMENT para portar limpio.
    -- Postgres: id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY
    id            INTEGER PRIMARY KEY,
    codigo        TEXT NOT NULL,
    precio        REAL NOT NULL,
    fuente        TEXT,
    clasificacion TEXT,          -- 'publico' | 'interno'
    fecha         TEXT,          -- ISO (YYYY-MM-DD)
    vigente       INTEGER NOT NULL DEFAULT 1,
    FOREIGN KEY (codigo) REFERENCES insumos(codigo)
);

CREATE TABLE IF NOT EXISTS meta (
    clave TEXT PRIMARY KEY,
    valor TEXT
);

CREATE INDEX IF NOT EXISTS idx_precio_cod ON insumo_precios(codigo, vigente);
