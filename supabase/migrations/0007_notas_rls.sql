-- Defensa en profundidad: RLS SIN policies en seguridad.nota, igual que el resto
-- (0003_rls.sql). Bloquea anon/authenticated; la service_role (FastAPI) hace bypass
-- y aplica el RBAC en la API. Requiere que la tabla exista (db/pg/seguridad.sql se
-- aplica en el boot), por eso va aparte, como 0005_lista_precios_rls.sql.
-- PASO MANUAL en producción: aplicarlo en el SQL editor de Supabase tras el deploy.
ALTER TABLE seguridad.nota ENABLE ROW LEVEL SECURITY;
