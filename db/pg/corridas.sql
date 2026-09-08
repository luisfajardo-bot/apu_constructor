-- Esquema Postgres de corridas (Supabase). Equivalente a db/corridas.sql.
CREATE SCHEMA IF NOT EXISTS corridas;

CREATE TABLE IF NOT EXISTS corridas.carpeta (
    id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    nombre        TEXT NOT NULL,
    parent_id     BIGINT REFERENCES corridas.carpeta(id) ON DELETE RESTRICT,
    creada_en     TEXT NOT NULL,
    creado_por    TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_carpeta_hermanas
    ON corridas.carpeta(COALESCE(parent_id, 0), nombre);

CREATE TABLE IF NOT EXISTS corridas.corrida (
    id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    creada_en     TEXT NOT NULL,
    archivo       TEXT NOT NULL,
    turno_def     TEXT NOT NULL,
    use_ai        SMALLINT,
    estado        TEXT NOT NULL,
    cuadro_path   TEXT,
    duracion_ms   INTEGER,
    creado_por    TEXT,
    modo          TEXT NOT NULL DEFAULT 'activa',
    carpeta_id    BIGINT REFERENCES corridas.carpeta(id) ON DELETE RESTRICT,
    nombre        TEXT,
    -- Tarifa de la corrida. NULL = Principal. Sin FK: lista_precios vive en el
    -- catálogo de precios, mismo trato que corrida_item.apu_codigo. La integridad
    -- se cuida no borrando listas (la API no expone DELETE).
    lista_precios_id BIGINT,
    -- Las líneas ya interpretadas del Excel, en orden. Única fuente de qué falta
    -- armar: el archivo subido no se guarda. OJO: lleva `precio_contractual`, o sea
    -- DINERO; nunca puede viajar en un payload hacia la IA (invariante #1).
    plan_json     TEXT,
    intentos      INTEGER NOT NULL DEFAULT 0,
    ultimo_error  TEXT,
    armando_por   TEXT,
    armando_desde TEXT
);

CREATE TABLE IF NOT EXISTS corridas.corrida_item (
    id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    corrida_id    BIGINT NOT NULL REFERENCES corridas.corrida(id) ON DELETE CASCADE,
    seq           INTEGER NOT NULL,
    item_json     TEXT NOT NULL,
    status        TEXT NOT NULL,
    apu_codigo    TEXT,
    apu_nombre    TEXT,
    unidad        TEXT,
    shift         TEXT,
    origen        TEXT,
    confianza     DOUBLE PRECISION,
    explicacion   TEXT,
    componentes_json TEXT,
    candidatos_json  TEXT,
    snapshot_json    TEXT,
    -- Veredicto de la IA revisora sobre el APU de esta fila. NULL = nunca revisada.
    revision_json    TEXT,
    -- Costo unitario declarado por una persona (proyectos especiales: la actividad vale
    -- lo que dice el contrato y armarle el APU no paga). NULL = costeo normal desde la
    -- composición. Se borra en actualizar_eleccion: si la fila cambia de APU, manda el APU.
    costo_manual     DOUBLE PRECISION
);
CREATE INDEX IF NOT EXISTS ix_corrida_item ON corridas.corrida_item(corrida_id, seq);

-- Migración idempotente para bases existentes.
ALTER TABLE corridas.corrida ADD COLUMN IF NOT EXISTS modo TEXT NOT NULL DEFAULT 'activa';
ALTER TABLE corridas.corrida_item ADD COLUMN IF NOT EXISTS snapshot_json TEXT;
ALTER TABLE corridas.corrida_item ADD COLUMN IF NOT EXISTS revision_json TEXT;
ALTER TABLE corridas.corrida_item ADD COLUMN IF NOT EXISTS costo_manual DOUBLE PRECISION;
ALTER TABLE corridas.corrida ADD COLUMN IF NOT EXISTS carpeta_id BIGINT
    REFERENCES corridas.carpeta(id) ON DELETE RESTRICT;
ALTER TABLE corridas.corrida ADD COLUMN IF NOT EXISTS nombre TEXT;
UPDATE corridas.corrida SET nombre = archivo WHERE nombre IS NULL OR nombre = '';
ALTER TABLE corridas.corrida ADD COLUMN IF NOT EXISTS lista_precios_id BIGINT;
ALTER TABLE corridas.corrida ADD COLUMN IF NOT EXISTS plan_json TEXT;
ALTER TABLE corridas.corrida ADD COLUMN IF NOT EXISTS intentos INTEGER NOT NULL DEFAULT 0;
ALTER TABLE corridas.corrida ADD COLUMN IF NOT EXISTS ultimo_error TEXT;
ALTER TABLE corridas.corrida ADD COLUMN IF NOT EXISTS armando_por TEXT;
ALTER TABLE corridas.corrida ADD COLUMN IF NOT EXISTS armando_desde TEXT;

-- Bootstrap "Sin clasificar" + backfill de corridas sin carpeta (idempotente).
INSERT INTO corridas.carpeta (nombre, creada_en)
    SELECT 'Sin clasificar', to_char(now(), 'YYYY-MM-DD"T"HH24:MI:SS')
    WHERE NOT EXISTS (SELECT 1 FROM corridas.carpeta
                      WHERE nombre = 'Sin clasificar' AND parent_id IS NULL);
UPDATE corridas.corrida SET carpeta_id =
    (SELECT id FROM corridas.carpeta WHERE nombre='Sin clasificar' AND parent_id IS NULL)
    WHERE carpeta_id IS NULL;
