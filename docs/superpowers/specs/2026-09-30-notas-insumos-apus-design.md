# Notas en insumos y APUs (con menciones y respuestas)

**Fecha:** 2026-09-30 · **Rama:** `feat/notas` · **Estado:** diseño aprobado

## Para qué

Dejar contexto humano pegado a un insumo o a un APU sin ensuciar las tablas:
«Precio extraído de la cotización de Ferretería X, 2026-09», «precio de nuevos
negocios», «rendimiento medido en obra Calle 13». Lo que la fuente (`PRECIO IDU` /
`COSTO INTERNO`) no alcanza a decir.

## Alcance por fases

Cada fase se despliega sola y queda usable.

| Fase | Trae |
|---|---|
| **1. Notas + pestaña Notas** | Hilo plano de notas por insumo y por APU; columna con ícono; panel para leer/escribir/editar/borrar; pestaña Notas (solo Admin). |
| **2. Menciones** | `@usuario` en el texto; campanita con menciones sin leer. |
| **3. Respuestas** | Responder una nota (hilo de un nivel). |

Fuera de alcance: notas en la corrida y en el cuadro resumen (Excel), correo de aviso
(depende del SMTP pendiente), notas por lista de precios (una nota es del insumo, se ve
igual en todas las listas).

## Modelo de datos (Fase 1, con lo de las fases 2-3 ya previsto)

Tabla **`nota`** en `seguridad.db` (y su espejo en el schema de seguridad de Postgres),
junto a `perfiles` y `auditoria`. No vive en `precios.db`/`apus.db` **a propósito**:
`seed --force` reescribe esas dos bases y se llevaría las notas.

| Columna | Tipo | Nota |
|---|---|---|
| `id` | INTEGER PK | |
| `entidad` | TEXT NOT NULL | `insumo` \| `apu` (CHECK) |
| `clave` | TEXT NOT NULL | identidad estable del dueño (ver abajo) |
| `etiqueta` | TEXT NOT NULL | cómo se muestra el dueño («4520 · DUCTO PVC…», «4859 · NOCTURNO · …»), fijada al crear |
| `texto` | TEXT NOT NULL | no vacío tras `strip`; tope 4000 caracteres |
| `autor_id` | TEXT NOT NULL | `user_id` |
| `autor_email` | TEXT NOT NULL | desnormalizado (se lee sin cruzar perfiles) |
| `creada_en` | TEXT NOT NULL | ISO 8601 UTC |
| `editada_en` | TEXT | NULL = nunca editada |
| `borrada` | INTEGER NOT NULL DEFAULT 0 | borrado suave |
| `responde_a` | INTEGER | NULL en Fase 1; la usa la Fase 3 |

Índices: `(entidad, clave)` y `(creada_en)`.

**Clave del dueño** (enlace blando, sin FK, como `insumo_codigo` en `apu_componentes`):
- Insumo: `codigo + "|" + nombre_norm` (`nucleo/texto.py::normalizar`). No el `id`: los
  códigos se repiten y el `id` no sobrevive a un reseed.
- APU: `codigo + "|" + shift`. Diurno y nocturno (`4859` / `4859 N`) tienen notas propias.

Una nota cuyo dueño desaparece (APU borrado) queda huérfana: no se ve en las tablas,
sí en la pestaña Notas con su `etiqueta`. No se borra nada solo. (No se marca «ya no
existe»: exigiría cruzar cada página de notas contra ~8000 insumos; YAGNI.)

**Borrado suave:** `DELETE` marca `borrada=1`. El texto queda en la fila y en Auditoría.
Existe para la Fase 3: una nota borrada con respuestas se muestra «(nota borrada)» y sus
respuestas siguen en pie.

## Persistencia

Repo nuevo `datos/notas_db.py` + `datos/pg/notas_pg.py`, contrato en
`datos/repositorio.py` (Protocol), expuesto en `Almacen` como `alm.notas`. Métodos:

- `crear(entidad, clave, texto, autor_id, autor_email) -> int`
- `listar(entidad, clave) -> list[Nota]` (no borradas, orden cronológico)
- `get(id) -> Nota | None`
- `editar(id, texto)` / `borrar(id)`
- `resumen_por_claves(entidad, claves) -> dict[clave, (n, ultima_texto)]` — **una
  consulta por página**, nunca una por fila (el N+1 que este repo ya pagó con Supabase).
- `buscar(entidad=None, autor_id=None, q=None, limit, offset) -> (list[Nota], total)` —
  para la pestaña Notas.

Migración: `CREATE TABLE IF NOT EXISTS` al boot en los dos backends (mismo patrón que las
columnas nuevas de corridas); en Postgres, archivo nuevo en `db/pg/` + política RLS como
el resto del schema.

## API (Fase 1)

| Método | Ruta | Rol | Qué |
|---|---|---|---|
| GET | `/api/notas?entidad=&clave=` | consulta | notas de un dueño |
| POST | `/api/notas` | editor | crea `{entidad, clave, texto}` |
| PATCH | `/api/notas/{id}` | editor | edita; **solo el autor** (403 si no) |
| DELETE | `/api/notas/{id}` | editor | borra; **el autor o un Admin** (403 si no) |
| GET | `/api/notas/todas?entidad=&autor=&q=&limit=&offset=` | admin | pestaña Notas |

- `POST` valida que el dueño exista hoy (insumo por código+nombre, APU por código+turno):
  400 si no. Una nota sobre algo inexistente es una nota perdida desde el día uno.
- Cada escritura registra en Auditoría (`nota.crear`, `nota.editar`, `nota.borrar`, con
  texto antes/después), en la misma transacción de `seguridad.db`.
- Los listados existentes suman dos campos por fila, sin endpoint nuevo:
  `GET /api/insumos` y `GET /api/apus` → `tiene_notas: bool`, `ultima_nota: str`
  (primeros 120 caracteres, para el tooltip), vía `resumen_por_claves`.

## Frontend (Fase 1)

- **Columna nueva** (angosta, sin título o con ícono) en `TablaInsumos` y en la tabla de
  `Apus.tsx`: ícono `MessageSquare` de lucide. **Vacío** (gris, contorno) sin notas;
  **pintado** (relleno, color de acento) con notas. Sin número. `title` = `ultima_nota`.
  Clic → abre el panel. Visible para todos los roles.
- **`DialogoNotas`** (componente nuevo, compartido por las dos tablas y la pestaña):
  encabezado con el dueño (código · nombre · turno), lista cronológica (autor, fecha,
  «(editada)»), caja de texto + «Agregar nota» (solo editor/admin). En las notas propias:
  «Editar» (edición en línea) y «Borrar» (con confirmación). Admin ve «Borrar» en todas.
  Al cerrar tras un cambio, la tabla recarga para repintar el ícono.
- **Pestaña Notas** (`pages/Notas.tsx`, ruta `/notas`, en el grupo de Admin del
  `Layout` junto a Usuarios y Auditoría): tabla densa con fecha, autor, tipo, dueño y
  texto (recortado); filtros por tipo y autor, buscador de texto, paginado. Clic en una
  fila → `DialogoNotas` de ese dueño.

## Fase 2: menciones

- Tabla **`nota_mencion`** (`nota_id`, `user_id`, `leida_en` NULL = sin leer),
  `UNIQUE(nota_id, user_id)`, en `seguridad.db`.
- En la caja de texto, `@` abre la lista de **usuarios activos** (perfiles, nombre o
  email). Escoger uno inserta `@Nombre`. El cliente manda `menciones: [user_id]` junto al
  texto; el servidor las valida contra perfiles activos (ignora las que no) y **no** las
  deduce parseando el texto.
- Editar resincroniza: menciones nuevas → aviso nuevo; quitadas → se borra su fila.
  Mencionarse a uno mismo no genera aviso. Borrar la nota borra sus avisos.
- **Campanita** en la barra superior con el conteo sin leer. El conteo **viaja en la
  respuesta de `GET /api/presencia`** (`menciones_sin_leer`), que la barra ya consulta
  cada 45 s con `fetch` directo: **no se agrega ningún sondeo nuevo** (regla: ningún
  poll de fondo con `apiGet`, que desloguea ante cualquier 401).
- Abrir la campanita → `GET /api/menciones` (lista: quién, cuándo, dueño, recorte del
  texto). Clic → abre `DialogoNotas` del dueño y marca leída
  (`POST /api/menciones/{nota_id}/leida`). Botón «Marcar todas como leídas».
- El nombre se pinta resaltado en la nota (el cliente conoce los `user_id` mencionados).

## Fase 3: respuestas

- Una respuesta es una `nota` con `responde_a = <id de la nota raíz>`, misma entidad y
  clave. Solo un nivel: responder a una respuesta cuelga de la raíz.
- El panel muestra cada raíz con sus respuestas indentadas debajo y un botón «Responder».
- Una raíz borrada con respuestas se muestra «(nota borrada)»; sin respuestas, no se ve.
- `tiene_notas` cuenta raíces y respuestas no borradas.

## Invariante #1 (IA sin dinero)

Las notas son texto libre y pueden llevar montos («cotización a $45.000»).
**Nunca** van en un payload hacia la IA. Se agregan `nota`, `notas` y `ultima_nota` a
`privacy._FORBIDDEN_KEYS`, para que un payload que las lleve **falle** en vez de
filtrarse. Verificado: hoy ningún payload hacia la IA usa esas claves (las `nota` de
carpetas y de `proyecto_ajuste` no viajan a la IA, y quedan cubiertas de paso).

## Errores

- Texto vacío o > 4000 → 400. Dueño inexistente → 400. Nota inexistente o borrada →
  404. Editar ajeno / borrar ajeno sin ser Admin → 403. Rol consulta escribiendo → 403.
- El panel muestra el mensaje del servidor en un toast y no pierde lo escrito.

## Pruebas

- Contrato del repo contra los dos backends (SQLite siempre; Postgres con
  `TEST_DATABASE_URL`), incluido `resumen_por_claves`.
- Servicio/API: permisos (editor crea; otro editor no edita ni borra; Admin borra;
  consulta no escribe; `/notas/todas` solo Admin), dueño inexistente, auditoría escrita.
- Que `seed --force` no borre las notas.
- Que `GET /api/insumos` resuelva el resumen en una consulta para toda la página.
- Privacidad: `assert_no_money` rechaza un payload con `nota`.
- Frontend: ícono vacío/pintado, flujo agregar → editar → borrar, botones según rol,
  pestaña oculta para no-Admin.
- Navegador antes de cada push (receta de la prueba de fuentes: app real sobre copia de
  `data/`, sesión simulada, playwright-core en el scratchpad).
