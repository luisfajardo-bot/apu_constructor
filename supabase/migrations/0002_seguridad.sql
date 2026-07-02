-- Schema de seguridad: perfiles (RBAC) + auditoría. DEBE crearse antes del RLS (0003_rls.sql).
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
    ts           TEXT NOT NULL,
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
