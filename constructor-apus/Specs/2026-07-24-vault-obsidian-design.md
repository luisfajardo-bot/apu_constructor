> Espejo automático — no editar aquí. Fuente: `docs/superpowers/specs/2026-07-24-vault-obsidian-design.md`

# Diseño — Vault de Obsidian auto-mantenida (constructor-apus/)

> Fecha: 2026-07-24
> Estado: propuesto (aprobado en brainstorming; pendiente de revisión del spec escrito)
> Rama de trabajo sugerida: `feat/vault-obsidian`

## Objetivo

El proyecto acumuló 34 planes, 38 specs, `ARQUITECTURA.md`, dos auditorías y un runbook
en `docs/`, más `README.md`/`CLAUDE.md` en la raíz — todo navegable como archivos sueltos
pero sin una vista conjunta, buscable y enlazada. El usuario ya creó una vault de
Obsidian vacía en `constructor-apus/`. Este proyecto la puebla con una reorganización de
lo que ya existe y deja la actualización **automatizada para siempre**: cada vez que se
agregue o cambie un spec/plan/doc, la vault se pone al día sola, sin depender de que
alguien (humano o agente) se acuerde de hacerlo a mano.

## Decisiones tomadas (brainstorming)

- **Ubicación:** `constructor-apus/` en la raíz del repo — la vault que el usuario ya
  creó con Obsidian. Se construye sobre ella; no se usa `docs/` como vault ni se mueve
  nada de ahí.
- **Alcance de contenido:** reorganizar lo que ya existe (specs, planes, arquitectura,
  auditorías, runbook, README, CLAUDE.md). Explícitamente **no** memoria del proyecto ni
  bitácora de commits.
- **Naturaleza del contenido:** espejo autogenerado, no la fuente de verdad. Cada nota
  copiada lleva un aviso de una línea ("no editar aquí, fuente: ..."); la fuente real
  sigue siendo `docs/` y la raíz del repo.
- **Disparador de actualización:** hook de git `pre-commit`, versionado en `.githooks/`.
  Determinístico — no depende de que Claude "se acuerde" de actualizar la vault al
  cerrar una tarea.
- **Navegación interna:** wikilinks de Obsidian (`[[nota]]`), porque todo el contenido
  vive dentro de la vault — habilita grafo y backlinks reales.

## Estructura de la vault

```
constructor-apus/
├── Índice.md                     ← home autogenerado (reemplaza Bienvenido.md)
├── Arquitectura/
│   └── ARQUITECTURA.md           ← espejo
├── Proyecto/
│   ├── README.md                 ← espejo del README.md de la raíz del repo
│   └── CLAUDE.md                 ← espejo del CLAUDE.md de la raíz del repo
├── Auditorías/
│   ├── auditoria-codigo-2026-07-01.md   ← espejo
│   └── auditoria-codigo-2026-07-08.md   ← espejo
├── Runbooks/
│   └── runbook-correo-resend-smtp.md    ← espejo
├── Specs/
│   └── *.md                      ← espejo de docs/superpowers/specs/ (38 archivos hoy)
├── Planes/
│   └── *.md                      ← espejo de docs/superpowers/plans/ (34 archivos hoy)
└── Otros/
    └── *.md                      ← catch-all: cualquier .md suelto en docs/ que no
                                     matchee ninguno de los patrones anteriores
```

## Componentes

### `scripts/actualizar_vault.py`

- Solo librería estándar (sin dependencias nuevas).
- **Espejo de archivos individuales** (README, CLAUDE, ARQUITECTURA, auditorías,
  runbook): copia el contenido fuente, antepone un aviso de una línea, escribe solo si
  el contenido resultante cambió.
- **Espejo de carpetas** (`Specs/`, `Planes/`): en cada corrida se limpia y se
  regenera completo, para que un archivo borrado o renombrado en la fuente no deje un
  huérfano en la vault.
- **Genera `Índice.md`:**
  - Título de cada nota = primer encabezado `# ` del archivo fuente (fallback: nombre
    de archivo legible).
  - Fecha = prefijo `YYYY-MM-DD` del nombre de archivo.
  - Tablas de Specs y Planes ordenadas por fecha descendente (fecha | título | link).
    No se intenta emparejar spec↔plan automáticamente (ver "Fuera de alcance").
  - Secciones fijas: Arquitectura, Proyecto, Auditorías, Runbooks.
  - Sección "Otros" para cualquier `.md` directamente en `docs/` (sin recursar en
    subcarpetas) que no matchee un patrón conocido (`auditoria-*.md`, `runbook-*.md`,
    `ARQUITECTURA.md`) — para no perder nada silenciosamente si aparece un tipo de doc
    nuevo. `docs/superpowers/plans/` y `docs/superpowers/specs/` ya están cubiertas
    aparte por `Planes/`/`Specs/`; el `.html` de arquitectura no se espeja (solo se
    mirrorean archivos `.md`).
- **Determinístico e idempotente:** correrlo dos veces sin cambios en las fuentes
  produce el mismo resultado byte a byte (necesario para que el hook no genere ruido
  en cada commit).
- **Limpieza inicial:** borra `Bienvenido.md` si todavía existe (ya cumplió su
  propósito).

### `.githooks/pre-commit`

- Corre `python scripts/actualizar_vault.py`; si el script falla, aborta el commit
  (falla fuerte, no silenciosa — igual que el resto del proyecto prefiere fallar a
  filtrar/omitir).
- `git add constructor-apus` para que los archivos regenerados viajen en el mismo
  commit — no hay commits separados de "actualicé la vault".
- Requiere una vez por clon: `git config core.hooksPath .githooks` (se documenta en
  el README; ya se aplica en este repo local como parte de la implementación).

### `.gitignore`

- Se agrega `constructor-apus/.obsidian/workspace.json` (y `workspace-mobile.json`):
  es estado de UI local (tabs abiertas, último archivo activo) que cambia en cada
  sesión de Obsidian y no aporta nada versionado.
- El resto de `.obsidian/` (plugins activos, apariencia, grafo) sí se versiona —
  es config compartida y estable.

## Pruebas

- `tests/test_actualizar_vault.py`, corriendo el script contra un árbol de archivos
  de prueba (`tmp_path`), verifica:
  - Los espejos se crean con el aviso de cabecera y el contenido correcto.
  - `Índice.md` contiene las secciones y links esperados, ordenados por fecha.
  - Idempotencia: correr el script dos veces sin cambiar las fuentes produce una
    salida idéntica.
  - Limpieza de huérfanos: si un archivo fuente desaparece, su espejo se borra en la
    siguiente corrida.
  - Un `.md` suelto en `docs/` sin patrón conocido cae en "Otros", no se pierde.
- Se corre `pytest` completo como parte de verificar la feature (junto con la suite
  existente), según la convención del proyecto.

## Fuera de alcance (YAGNI)

- Memoria del proyecto y bitácora de commits en la vault (decidido explícitamente que
  no, en el brainstorming).
- Emparejar automáticamente cada spec con su plan: varios slugs no coinciden
  exactamente (p. ej. `frontend-api-web` vs `frontend-web-p1`); listarlos por separado
  y ordenados por fecha es más simple y no arriesga un emparejamiento incorrecto.
- Plugins de Obsidian más allá de los core ya habilitados por default — no se instala
  nada de la comunidad.
- Sincronización bidireccional (editar una nota espejo en la vault y que se refleje de
  vuelta en `docs/`) — es de solo lectura por diseño; la fuente de verdad sigue siendo
  `docs/` y la raíz del repo.
