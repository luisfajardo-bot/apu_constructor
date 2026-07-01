-- Defensa en profundidad: habilitar RLS SIN policies en todas las tablas.
-- Bloquea anon/authenticated; la service_role (FastAPI) hace bypass de RLS.
ALTER TABLE precios.insumos            ENABLE ROW LEVEL SECURITY;
ALTER TABLE precios.insumo_precios     ENABLE ROW LEVEL SECURITY;
ALTER TABLE precios.meta               ENABLE ROW LEVEL SECURITY;
ALTER TABLE apus.apus                  ENABLE ROW LEVEL SECURITY;
ALTER TABLE apus.apu_componentes       ENABLE ROW LEVEL SECURITY;
ALTER TABLE apus.meta                  ENABLE ROW LEVEL SECURITY;
ALTER TABLE corridas.corrida           ENABLE ROW LEVEL SECURITY;
ALTER TABLE corridas.corrida_item      ENABLE ROW LEVEL SECURITY;
ALTER TABLE seguridad.perfiles         ENABLE ROW LEVEL SECURITY;
