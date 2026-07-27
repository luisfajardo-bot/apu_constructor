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
    oculto      INTEGER NOT NULL DEFAULT 0,   -- 1 = eco de un APU sin uso real; se filtra, nunca se borra
    UNIQUE (codigo, nombre_norm)
);
CREATE INDEX IF NOT EXISTS idx_insumo_cod ON insumos(codigo);

-- Una lista = una tarifa. La id 1 es SIEMPRE 'Principal' (la siembra init_schema).
CREATE TABLE IF NOT EXISTS lista_precios (
    id         INTEGER PRIMARY KEY,
    nombre     TEXT NOT NULL UNIQUE,
    creada_en  TEXT NOT NULL,      -- ISO (YYYY-MM-DD)
    creado_por TEXT                -- user_id (NULL = sistema/migración)
);

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
    creado_por    TEXT,          -- user_id de quien fijó el precio (NULL = histórico/seed)
    lista_id      INTEGER NOT NULL DEFAULT 1 REFERENCES lista_precios(id),
    -- NOTA (drift vs. base migrada): SQLite no permite ADD COLUMN con NOT NULL DEFAULT
    -- *y* REFERENCES a la vez, así que una base preexistente recibe la columna SIN la
    -- FK (ver PreciosDB.init_schema). Misma clase de drift ya anotada en db/pg/precios.sql.
    FOREIGN KEY (insumo_id) REFERENCES insumos(id)
);

CREATE TABLE IF NOT EXISTS meta (
    clave TEXT PRIMARY KEY,
    valor TEXT
);

CREATE INDEX IF NOT EXISTS idx_precio_ins ON insumo_precios(insumo_id, vigente);
CREATE INDEX IF NOT EXISTS idx_precio_ins_lista ON insumo_precios(insumo_id, lista_id, vigente);
