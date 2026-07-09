-- Defensa en profundidad: habilitar RLS SIN policies en corridas.carpeta,
-- igual que el resto de tablas en 0003_rls.sql. Bloquea anon/authenticated;
-- la service_role (FastAPI) hace bypass de RLS y aplica el RBAC en la API
-- (requiere_rol: crear = consulta+; renombrar/mover/borrar = editor+).
-- Requiere que corridas.carpeta exista (db/pg/corridas.sql, aplicado en boot).
ALTER TABLE corridas.carpeta ENABLE ROW LEVEL SECURITY;
