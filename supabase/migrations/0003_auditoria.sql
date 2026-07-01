-- Registro de auditoría append-only. Vive en el schema seguridad (junto a perfiles).
CREATE SCHEMA IF NOT EXISTS seguridad;

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

-- Defensa en profundidad: RLS habilitada SIN policies (FastAPI usa service_role, que hace bypass).
ALTER TABLE seguridad.auditoria ENABLE ROW LEVEL SECURITY;
