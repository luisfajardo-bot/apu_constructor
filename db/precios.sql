-- Esquema canónico de precios.db — catálogo de insumos y libro de precios.
-- SQL portable (SQLite hoy; Postgres luego). Cargado por apu_tool/datos/precios_db.py.
--
-- El código NO es único: el IDU repite códigos para insumos distintos. La identidad
-- es (codigo, nombre_norm); el precio cuelga del id interno del insumo.

CREATE TABLE IF NOT EXISTS insumos (
    id          INTEGER PRIMARY KEY,   -- rowid de SQLite; sin AUTOINCREMENT (porta a Postgres)
    codigo      TEXT NOT NULL,
    nombre      TEXT NOT NULL,
    nombre_norm TEXT NOT NULL,         -- normalizado (apu_tool/nucleo/texto.py)
    unidad      TEXT,
    grupo       TEXT,
    UNIQUE (codigo, nombre_norm)
);
CREATE INDEX IF NOT EXISTS idx_insumo_cod ON insumos(codigo);

CREATE TABLE IF NOT EXISTS insumo_precios (
    -- SQLite autollena un INTEGER PRIMARY KEY (rowid); sin AUTOINCREMENT para portar limpio.
    -- Postgres: id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY
    id            INTEGER PRIMARY KEY,
    insumo_id     INTEGER NOT NULL,
    precio        REAL NOT NULL,
    fuente        TEXT,
    clasificacion TEXT,          -- 'publico' | 'interno'
    fecha         TEXT,          -- ISO (YYYY-MM-DD)
    vigente       INTEGER NOT NULL DEFAULT 1,
    FOREIGN KEY (insumo_id) REFERENCES insumos(id)
);

CREATE TABLE IF NOT EXISTS meta (
    clave TEXT PRIMARY KEY,
    valor TEXT
);

CREATE INDEX IF NOT EXISTS idx_precio_ins ON insumo_precios(insumo_id, vigente);
