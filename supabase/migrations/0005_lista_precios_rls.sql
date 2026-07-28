-- Defensa en profundidad: habilitar RLS SIN policies en precios.lista_precios,
-- igual que el resto de tablas en 0003_rls.sql. Bloquea anon/authenticated;
-- la service_role (FastAPI) hace bypass de RLS y aplica el RBAC en la API.
-- Requiere que precios.lista_precios exista (db/pg/precios.sql, aplicado en
-- boot, igual que corridas.carpeta -> ver 0004_carpetas_rls.sql): por eso
-- 0003_rls.sql, que solo cubre lo creado en las migraciones numeradas, no la
-- alcanza y hace falta este archivo aparte.
ALTER TABLE precios.lista_precios ENABLE ROW LEVEL SECURITY;
