-- Defensa en profundidad: RLS SIN policies en las tablas nuevas de transporte por
-- proyecto, igual que el resto (0003_rls.sql). Bloquea anon/authenticated; la
-- service_role (FastAPI) hace bypass y aplica el RBAC en la API.
-- Las tablas las crea el boot (db/pg/apus.sql, db/pg/corridas.sql), no una
-- migración numerada: por eso hace falta este archivo aparte, igual que
-- 0004_carpetas_rls.sql y 0005_lista_precios_rls.sql.
ALTER TABLE apus.componente_transporte ENABLE ROW LEVEL SECURITY;
ALTER TABLE corridas.proyecto_parametros ENABLE ROW LEVEL SECURITY;
ALTER TABLE corridas.proyecto_ajuste ENABLE ROW LEVEL SECURITY;
