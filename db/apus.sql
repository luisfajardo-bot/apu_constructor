-- Esquema canónico de apus.db — biblioteca histórica de APUs.
-- SQL portable (SQLite hoy; Postgres luego). Cargado por apu_tool/datos/apus_db.py.

CREATE TABLE IF NOT EXISTS apus (
    codigo TEXT NOT NULL,
    shift  TEXT NOT NULL,
    nombre TEXT NOT NULL,
    unidad TEXT,
    grupo  TEXT,
    PRIMARY KEY (codigo, shift)
);

CREATE TABLE IF NOT EXISTS apu_componentes (
    apu_codigo            TEXT NOT NULL,
    shift                 TEXT NOT NULL,
    seq                   INTEGER NOT NULL,
    insumo_codigo         TEXT,   -- enlace BLANDO a precios.db: se valida en la app, sin FK
    insumo_nombre         TEXT,   -- nombre desnormalizado (respaldo si falta el código)
    unidad                TEXT,
    rendimiento           REAL,
    precio_unitario_hist  REAL,
    tipo                  TEXT NOT NULL DEFAULT 'insumo',   -- 'insumo' | 'apu' (sub-APU)
    ref_shift             TEXT,                             -- turno del sub-APU si tipo='apu'
    PRIMARY KEY (apu_codigo, shift, seq),
    FOREIGN KEY (apu_codigo, shift) REFERENCES apus(codigo, shift)
);

CREATE TABLE IF NOT EXISTS meta (
    clave TEXT PRIMARY KEY,
    valor TEXT
);

CREATE INDEX IF NOT EXISTS idx_comp_apu    ON apu_componentes(apu_codigo, shift);
CREATE INDEX IF NOT EXISTS idx_apus_nombre ON apus(nombre);

-- Clasificación de los componentes de acarreo: qué categoría son y cuántos m3
-- esponjados mueven por unidad de APU. El rendimiento efectivo de un proyecto es
-- volumen * km_del_proyecto. Tabla APARTE de apu_componentes a propósito: esa la
-- reescriben seed/autoría/importadores con seq nuevo en cada semillado.
CREATE TABLE IF NOT EXISTS componente_transporte (
    apu_codigo      TEXT NOT NULL,
    shift           TEXT NOT NULL,
    insumo_codigo   TEXT NOT NULL,
    insumo_nombre   TEXT NOT NULL,   -- identidad real: codigo + nombre
    categoria       TEXT NOT NULL,   -- botadero | mezclas | granulares
    volumen         REAL NOT NULL,
    km_base         REAL,
    actualizado_en  TEXT NOT NULL,
    actualizado_por TEXT,
    PRIMARY KEY (apu_codigo, shift, insumo_codigo)
);
