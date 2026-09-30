CREATE SCHEMA IF NOT EXISTS seguridad;
CREATE TABLE IF NOT EXISTS seguridad.perfiles (
    user_id   TEXT PRIMARY KEY,
    email     TEXT NOT NULL,
    rol       TEXT NOT NULL CHECK (rol IN ('admin','editor','consulta')),
    estado    TEXT NOT NULL CHECK (estado IN ('activo','inactivo')),
    nombre    TEXT,
    creado_en TEXT
);

CREATE TABLE IF NOT EXISTS seguridad.auditoria (
    id           BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    ts           TEXT NOT NULL,           -- ISO 8601 UTC (TEXT como el resto de fechas del proyecto)
    user_id      TEXT,
    user_email   TEXT,
    rol          TEXT NOT NULL,
    accion       TEXT NOT NULL,
    entidad_tipo TEXT NOT NULL,
    entidad_id   TEXT,
    antes        JSONB,
    despues      JSONB,
    contexto     JSONB
);
CREATE INDEX IF NOT EXISTS idx_auditoria_ts ON seguridad.auditoria(ts);
CREATE INDEX IF NOT EXISTS idx_auditoria_entidad ON seguridad.auditoria(entidad_tipo, entidad_id);
CREATE INDEX IF NOT EXISTS idx_auditoria_user ON seguridad.auditoria(user_id);

-- Espejo de db/seguridad.sql::nota (ver ahí el porqué de vivir en este schema).
CREATE TABLE IF NOT EXISTS seguridad.nota (
    id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    entidad     TEXT NOT NULL CHECK (entidad IN ('insumo','apu')),
    clave       TEXT NOT NULL,
    etiqueta    TEXT NOT NULL,
    texto       TEXT NOT NULL,
    autor_id    TEXT NOT NULL,
    autor_email TEXT NOT NULL,
    creada_en   TEXT NOT NULL,
    editada_en  TEXT,
    borrada     INTEGER NOT NULL DEFAULT 0,
    responde_a  BIGINT
);
CREATE INDEX IF NOT EXISTS idx_nota_duenio ON seguridad.nota(entidad, clave);
CREATE INDEX IF NOT EXISTS idx_nota_creada ON seguridad.nota(creada_en);

-- Espejo de db/seguridad.sql::nota_mencion.
CREATE TABLE IF NOT EXISTS seguridad.nota_mencion (
    nota_id   BIGINT NOT NULL,
    user_id   TEXT NOT NULL,
    creada_en TEXT NOT NULL,
    leida_en  TEXT,
    UNIQUE (nota_id, user_id)
);
CREATE INDEX IF NOT EXISTS idx_mencion_user ON seguridad.nota_mencion(user_id, leida_en);
