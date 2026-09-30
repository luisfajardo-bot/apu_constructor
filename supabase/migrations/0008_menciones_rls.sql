-- Defensa en profundidad: RLS SIN policies en seguridad.nota_mencion, igual que
-- 0007_notas_rls.sql. La tabla la crea el boot (db/pg/seguridad.sql).
-- PASO MANUAL en producción: aplicarlo en el SQL editor de Supabase tras el deploy.
ALTER TABLE seguridad.nota_mencion ENABLE ROW LEVEL SECURITY;
