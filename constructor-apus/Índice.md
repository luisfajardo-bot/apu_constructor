# Índice

Vault autogenerada por `scripts/actualizar_vault.py` en cada commit — 33 planes, 39 specs. Las notas espejo no se editan aquí; la fuente de verdad sigue siendo `docs/` y la raíz del repo.

## Arquitectura y referencia

- [[Arquitectura/ARQUITECTURA|Arquitectura objetivo — Armador de APUs]]
- [[Proyecto/README|Armador de APUs — Obra Civil]]
- [[Proyecto/CLAUDE|CLAUDE.md]]
- [[Arquitectura/Mapa de módulos|Mapa de módulos — apu_tool/]]

## Auditorías

- [[Auditorías/auditoria-codigo-2026-07-01|Auditoría de código — Armador de APUs (2026-07-01)]]
- [[Auditorías/auditoria-codigo-2026-07-08|Auditoría de código — Armador de APUs (2026-07-08)]]

## Runbooks

- [[Runbooks/runbook-correo-resend-smtp|Runbook — Correo transaccional con Resend + Supabase (SMTP)]]

## Otros

- [[Otros/listas-precios-np|Listas de precios y APUs de No Previstos (NP)]]

## Specs (diseños)

| Fecha | Título |
| --- | --- |
| 2026-07-31 | [[Specs/2026-07-31-ensure-seeded-almacen-inyectado-design|Diseño — `ensure_seeded` sobre el almacén inyectado]] |
| 2026-07-27 | [[Specs/2026-07-27-ocultar-insumos-duplicados-apu-design|Diseño — Ocultar del catálogo de insumos los códigos que son APU]] |
| 2026-07-27 | [[Specs/2026-07-27-apus-np-design|Diseño — APUs para NP (No Previstos): listas de precios]] |
| 2026-07-24 | [[Specs/2026-07-24-vault-obsidian-design|Diseño — Vault de Obsidian auto-mantenida (constructor-apus/)]] |
| 2026-07-24 | [[Specs/2026-07-24-mapa-arquitectura-design|Diseño — Corrección de docs de arquitectura + mapa auto-generado de módulos]] |
| 2026-07-14 | [[Specs/2026-07-14-costo-editable-apu-design|Costo editable en el armador de APUs — diseño]] |
| 2026-07-10 | [[Specs/2026-07-10-costeo-cero-alertas-design|Costeo en $0 nunca mudo + regla "nada en 0" — diseño]] |
| 2026-07-09 | [[Specs/2026-07-09-columnas-unitarias-corrida-design|Columnas unitarias en la tabla de corrida — diseño]] |
| 2026-07-09 | [[Specs/2026-07-09-carpetas-corridas-design|Diseño — Carpetas para organizar corridas en subproyectos]] |
| 2026-07-08 | [[Specs/2026-07-08-totales-en-lista-corridas-design|Totales (contractual / costo / diferencia / margen%) en la lista de corridas — Diseño]] |
| 2026-07-06 | [[Specs/2026-07-06-subapus-ux-design|Diseño — UX de sub-APUs (editor, corrida, detalle)]] |
| 2026-07-06 | [[Specs/2026-07-06-subapus-import-design|Diseño — Detección de sub-APUs en el import de APUs]] |
| 2026-07-06 | [[Specs/2026-07-06-apus-compuestos-design|Diseño — APUs compuestos (un APU usa otros APUs como insumos)]] |
| 2026-07-05 | [[Specs/2026-07-05-filtros-orden-corrida-design|Diseño — Filtros y ordenamiento en la tabla de la corrida]] |
| 2026-07-05 | [[Specs/2026-07-05-columna-item-corrida-design|Diseño — Columna "Ítem" (código de licitación) en la tabla de la corrida]] |
| 2026-07-03 | [[Specs/2026-07-03-reasignar-apu-corrida-design|Diseño — Reasignar el APU de un ítem de corrida (buscador en la biblioteca)]] |
| 2026-07-03 | [[Specs/2026-07-03-plantillas-descarga-importadores-design|Diseño — Descarga de plantillas de importación (APUs, Insumos, Precios)]] |
| 2026-07-03 | [[Specs/2026-07-03-importador-unificado-insumos-design|Diseño — Importador unificado de insumos (upsert)]] |
| 2026-07-03 | [[Specs/2026-07-03-estados-corrida-design|Diseño — Estados de corrida (activa / congelada)]] |
| 2026-07-03 | [[Specs/2026-07-03-editar-borrar-apus-design|Diseño — Editar y borrar APUs (biblioteca)]] |
| 2026-07-02 | [[Specs/2026-07-02-fix-auditoria-important-design|Diseño — Plan B: 8 Important + Minors de la auditoría]] |
| 2026-07-02 | [[Specs/2026-07-02-fix-auditoria-critical-design|Diseño — Plan A: arreglar los 3 Critical de la auditoría]] |
| 2026-07-01 | [[Specs/2026-07-01-produccion-multiusuario-design|Diseño — Ruta a producción multiusuario del Armador de APUs]] |
| 2026-07-01 | [[Specs/2026-07-01-endurecimiento-despliegue-design|Diseño — Plan 4: Endurecimiento + despliegue]] |
| 2026-07-01 | [[Specs/2026-07-01-auth-rbac-design|Diseño — Plan 2a: Auth + RBAC (backend)]] |
| 2026-07-01 | [[Specs/2026-07-01-auth-frontend-design|Diseño — Plan 2b: Auth + RBAC (frontend)]] |
| 2026-07-01 | [[Specs/2026-07-01-auditoria-design|Diseño — Plan 3: Auditoría transaccional de mutaciones sensibles]] |
| 2026-06-30 | [[Specs/2026-06-30-autoria-base-design|Diseño — Autoría de la base: agregar insumos y APUs (etapa 3, sub-proyecto 1)]] |
| 2026-06-25 | [[Specs/2026-06-25-progreso-armado-sse-design|Diseño — Progreso del armado (log en consola + SSE)]] |
| 2026-06-25 | [[Specs/2026-06-25-matcher-optimizacion-design|Diseño — Optimización del matcher (etapa 2, sub-proyecto A)]] |
| 2026-06-25 | [[Specs/2026-06-25-cronometro-armado-design|Diseño — Cronómetro del armado (tiempo final persistido)]] |
| 2026-06-25 | [[Specs/2026-06-25-corridas-lista-vivo-composicion-design|Diseño — Corridas: turno requerido, lista "mis corridas", vivo, composición desplegable]] |
| 2026-06-25 | [[Specs/2026-06-25-armado-incremental-vivo-design|Diseño — Armado incremental + tabla en vivo (etapa 2, sub-proyecto B)]] |
| 2026-06-24 | [[Specs/2026-06-24-frontend-web-p1-design|Diseño — Frontend web (Proyecto 1: shell + corrida + edición de insumos)]] |
| 2026-06-24 | [[Specs/2026-06-24-frontend-api-web-design|Diseño — Frontend web + API (v1: armar el cuadro)]] |
| 2026-06-23 | [[Specs/2026-06-23-identidad-insumo-codigo-nombre-design|Identidad de insumo por (código + nombre) y cruce con doble verificación difusa]] |
| 2026-06-23 | [[Specs/2026-06-23-bases-separadas-fuente-de-verdad-design|Dos bases separadas, fuente de verdad (precios.db + apus.db)]] |
| 2026-06-19 | [[Specs/2026-06-19-esquema-sql-fuente-de-verdad-design|Esquema SQL como fuente de verdad]] |
| 2026-06-19 | [[Specs/2026-06-19-cuadro-categorizado-presupuesto-design|Cuadro resumen categorizado desde el presupuesto]] |

## Planes (implementación)

| Fecha | Título |
| --- | --- |
| 2026-07-27 | [[Planes/2026-07-27-listas-precios-np|Listas de precios para APUs de NP — Implementation Plan]] |
| 2026-07-14 | [[Planes/2026-07-14-costo-editable-apu|Costo editable en el armador de APUs — Implementation Plan]] |
| 2026-07-10 | [[Planes/2026-07-10-costeo-cero-alertas|Costeo en $0 nunca mudo + regla "nada en 0" — Plan de implementación]] |
| 2026-07-09 | [[Planes/2026-07-09-columnas-unitarias-corrida|Columnas unitarias en la tabla de corrida — Implementation Plan]] |
| 2026-07-09 | [[Planes/2026-07-09-carpetas-corridas|Carpetas para organizar corridas — Plan de Implementación]] |
| 2026-07-08 | [[Planes/2026-07-08-totales-lista-corridas|Totales en la lista de corridas — Plan de implementación]] |
| 2026-07-06 | [[Planes/2026-07-06-subapus-ux|UX de sub-APUs (editor + badge) — Implementation Plan]] |
| 2026-07-06 | [[Planes/2026-07-06-subapus-import|Detección de sub-APUs en el import — Implementation Plan]] |
| 2026-07-06 | [[Planes/2026-07-06-apus-compuestos|APUs compuestos (Fase 1 backend) — Implementation Plan]] |
| 2026-07-05 | [[Planes/2026-07-05-filtros-orden-corrida|Filtros por columna + ordenamiento en la tabla de la corrida — Implementation Plan]] |
| 2026-07-05 | [[Planes/2026-07-05-columna-item-corrida|Columna "Ítem" (código de licitación) en la corrida — Implementation Plan]] |
| 2026-07-03 | [[Planes/2026-07-03-reasignar-apu-corrida|Reasignar el APU de un ítem de corrida — Implementation Plan]] |
| 2026-07-03 | [[Planes/2026-07-03-plantillas-descarga-importadores|Plantillas de descarga para importadores — Implementation Plan]] |
| 2026-07-03 | [[Planes/2026-07-03-importador-unificado-insumos|Importador unificado de insumos (upsert) — Implementation Plan]] |
| 2026-07-03 | [[Planes/2026-07-03-estados-corrida|Estados de corrida (activa / congelada) — Implementation Plan]] |
| 2026-07-03 | [[Planes/2026-07-03-editar-borrar-apus|Editar y borrar APUs (biblioteca) — Implementation Plan]] |
| 2026-07-02 | [[Planes/2026-07-02-fix-auditoria-important|Fix Auditoría — 8 Important + Minors — Implementation Plan]] |
| 2026-07-02 | [[Planes/2026-07-02-fix-auditoria-critical|Fix Auditoría — 3 Critical — Implementation Plan]] |
| 2026-07-01 | [[Planes/2026-07-01-endurecimiento-despliegue|Endurecimiento + Despliegue — Plan de Implementación]] |
| 2026-07-01 | [[Planes/2026-07-01-backend-postgres-migracion|Backend Postgres + Migración de Catálogo — Implementation Plan]] |
| 2026-07-01 | [[Planes/2026-07-01-auth-rbac-backend|Plan 2a — Auth + RBAC (backend) Implementation Plan]] |
| 2026-07-01 | [[Planes/2026-07-01-auth-frontend|Plan 2b — Auth + RBAC (frontend) Implementation Plan]] |
| 2026-07-01 | [[Planes/2026-07-01-auditoria|Auditoría Transaccional — Plan de Implementación]] |
| 2026-06-30 | [[Planes/2026-06-30-autoria-base|Plan — Autoría de la base (agregar insumos y APUs)]] |
| 2026-06-25 | [[Planes/2026-06-25-progreso-armado-sse|Progreso del armado (log + SSE) — Implementation Plan]] |
| 2026-06-25 | [[Planes/2026-06-25-cronometro-armado|Cronómetro del armado — Implementation Plan]] |
| 2026-06-25 | [[Planes/2026-06-25-corridas-lista-vivo-composicion|Corridas: turno requerido, lista, vivo, composición — Implementation Plan]] |
| 2026-06-24 | [[Planes/2026-06-24-web-v1-backend-api|Web v1 — Backend (API + persistencia) Implementation Plan]] |
| 2026-06-24 | [[Planes/2026-06-24-frontend-web-p1|Frontend Web Proyecto 1 — Implementation Plan]] |
| 2026-06-23 | [[Planes/2026-06-23-identidad-insumo-codigo-nombre|Identidad de insumo por (código + nombre) — Plan de Implementación]] |
| 2026-06-23 | [[Planes/2026-06-23-bases-separadas-fuente-de-verdad|Dos bases separadas, fuente de verdad — Implementation Plan]] |
| 2026-06-19 | [[Planes/2026-06-19-esquema-sql-fuente-de-verdad|Esquema SQL como fuente de verdad — Implementation Plan]] |
| 2026-06-19 | [[Planes/2026-06-19-cuadro-categorizado-presupuesto|Cuadro categorizado desde presupuesto — Implementation Plan]] |
