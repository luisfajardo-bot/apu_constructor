CREATE TABLE IF NOT EXISTS perfiles (
    user_id   TEXT PRIMARY KEY,
    email     TEXT NOT NULL,
    rol       TEXT NOT NULL CHECK (rol IN ('admin','editor','consulta')),
    estado    TEXT NOT NULL CHECK (estado IN ('activo','inactivo')),
    nombre    TEXT,
    creado_en TEXT
);

CREATE TABLE IF NOT EXISTS auditoria (
    id           INTEGER PRIMARY KEY,     -- rowid SQLite; sin AUTOINCREMENT (porta a Postgres)
    ts           TEXT NOT NULL,           -- ISO 8601 UTC
    user_id      TEXT,                    -- actor; NULL = sistema (CLI/seed)
    user_email   TEXT,
    rol          TEXT NOT NULL,
    accion       TEXT NOT NULL,
    entidad_tipo TEXT NOT NULL,
    entidad_id   TEXT,
    antes        TEXT,                    -- JSON (estado previo)
    despues      TEXT,                    -- JSON (estado nuevo)
    contexto     TEXT                     -- JSON ({origen, lote_id, archivo, ...})
);
CREATE INDEX IF NOT EXISTS idx_auditoria_ts ON auditoria(ts);
CREATE INDEX IF NOT EXISTS idx_auditoria_entidad ON auditoria(entidad_tipo, entidad_id);
CREATE INDEX IF NOT EXISTS idx_auditoria_user ON auditoria(user_id);
