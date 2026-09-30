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

-- Notas de insumos y APUs. Viven aquí y no en precios.db/apus.db a propósito: seed
-- --force reescribe esas dos bases y se llevaría las notas. `clave` es un enlace BLANDO
-- al dueño (insumo: codigo|nombre_norm, APU: codigo|TURNO), sin FK, como
-- apu_componentes.insumo_codigo. Borrado suave. `responde_a` es de la Fase 3.
CREATE TABLE IF NOT EXISTS nota (
    id          INTEGER PRIMARY KEY,     -- rowid SQLite; sin AUTOINCREMENT (porta a Postgres)
    entidad     TEXT NOT NULL CHECK (entidad IN ('insumo','apu')),
    clave       TEXT NOT NULL,
    etiqueta    TEXT NOT NULL,
    texto       TEXT NOT NULL,
    autor_id    TEXT NOT NULL,
    autor_email TEXT NOT NULL,
    creada_en   TEXT NOT NULL,           -- ISO 8601 UTC
    editada_en  TEXT,
    borrada     INTEGER NOT NULL DEFAULT 0,
    responde_a  INTEGER
);
CREATE INDEX IF NOT EXISTS idx_nota_duenio ON nota(entidad, clave);
CREATE INDEX IF NOT EXISTS idx_nota_creada ON nota(creada_en);

-- Menciones de la Fase 2: a quién avisa una nota. `leida_en` NULL = sin leer.
-- Enlace blando a perfiles (user_id de Supabase Auth), sin FK, como autor_id de nota.
CREATE TABLE IF NOT EXISTS nota_mencion (
    nota_id   INTEGER NOT NULL,
    user_id   TEXT NOT NULL,
    creada_en TEXT NOT NULL,
    leida_en  TEXT,
    UNIQUE (nota_id, user_id)
);
CREATE INDEX IF NOT EXISTS idx_mencion_user ON nota_mencion(user_id, leida_en);
