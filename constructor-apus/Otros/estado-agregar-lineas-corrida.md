> Espejo automático — no editar aquí. Fuente: `docs/estado-agregar-lineas-corrida.md`

# Estado — agregar líneas a una corrida activa

Rama `feat/agregar-lineas-corrida`, sacada de `master` (2026-08-18). No toca nada del PR
de Google: `servicio/auth.py`, `datos/perfiles*`, `pages/Login.tsx` quedan intactos.

- Spec: `docs/superpowers/specs/2026-08-18-agregar-lineas-corrida-design.md`
- Plan: `docs/superpowers/plans/2026-08-18-agregar-lineas-corrida.md`

## Qué hace

Sobre una corrida en modo `activa`:

1. **Agregar una línea a mano** (descripción, unidad, cantidad, precio contractual, turno).
2. **Agregar por Excel** solo las actividades que faltaron, con vista previa que avisa
   cuáles ya están en la corrida (por descripción normalizada) antes de aplicar.
3. **Borrar las líneas marcadas**, desde la barra de selección de la tabla.

Las líneas nuevas pasan por el **mismo camino que el armado inicial** (`_armar_fila`), con
el `use_ai` y la lista de precios que la corrida guardó al crearse.

## Estado

Terminada y verde. Verificación en serie del 2026-08-18:

```
pytest tests/ -q      → 749 passed, 15 skipped, 1 warning (slowapi, preexistente)
npm run test -- --run → 44 archivos, 191 pruebas
npm run build         → OK (tsc -b + vite)
```

Sin migración de esquema: `borrar_items` usa solo columnas que ya existen.

**Falta el smoke test en navegador.** Nada se desplegó: la rama no es `master`.

## Decisiones que no se pueden romper

- El `seq` **nunca** se renumera. Es la clave del `snapshot_json` y de la URL del ítem;
  renumerar casaría el snapshot con la línea equivocada. Borrar deja huecos, y los huecos
  no se reusan (`agregar_items` sigue desde `max(seq)+1`).
- La vista previa **avisa** duplicados, no los filtra. Aplicar agrega todo lo que trae el
  archivo: saltear en silencio es la sorpresa que este repo evita.
- Agregar/borrar en una corrida `finalizada` la devuelve a `en_revision` (el cuadro emitido
  ya no dice la verdad). Corrida congelada → 409.
- **No se puede agregar mientras la corrida está `armando`.** El armador asigna los `seq`
  con `enumerate()` precalculado y `agregar_items` con `max(seq)+1`: agregar a mitad
  escribía un `seq` duplicado en silencio (`corrida_item` no tiene índice UNIQUE) y el
  cuadro contaba la actividad dos veces. Lo encontró la revisión final, no el plan.
- El borrado va por `POST /corridas/{cid}/items/borrar`, no `DELETE`: `apiDelete` del
  frontend no manda cuerpo.
- Rol `consulta` en los 4 endpoints, igual que confirmar / congelar / eliminar corrida.

## Smoke test — por dónde empezar

1. **Borrar líneas.** Es el único camino que nunca corrió contra Postgres real: marcar 2
   líneas → `Borrar` → confirmar. Después verificar que el evento `corrida.borrar_items`
   aparezca en el visor de auditoría (esa fila prueba que la transacción funcionó).
2. **La plantilla trae 2 filas de EJEMPLO.** Si se baja la plantilla y no se borran, se
   agregan como actividades reales. La previa las muestra: mirar la lista antes de aplicar.
3. **Agregar con un filtro de columna puesto:** la línea nueva puede caer fuera del filtro
   y parecer que no pasó nada. Mirar el contador `n_items` de la barra de totales.
4. **Línea nueva en una corrida de NP:** tiene que salir en $0 **con alerta**
   (`sin_precio_lista`), nunca con el precio histórico.
5. **"Marcar todas" + `Borrar`** vacía la corrida en dos clics. Probar que una corrida
   vacía todavía abre y que `Descargar cuadro` no explota con 0 ítems.
6. **Congelada:** no debe aparecer ni `Agregar líneas` ni la barra de selección. Una
   corrida `finalizada` reabierta debe mostrar `en_revision` en el encabezado.

## Menores conocidos (revisión final: pueden esperar)

- `agregar_items` no es atómico: si el lote falla a mitad, las líneas previas quedan. El
  arreglo natural es usar `guardar_items` (un `executemany` que ya existe en los dos
  backends), que de paso baja los N round-trips a Supabase a uno.
- No atrapa `CorridaEliminada` si borran la corrida a mitad del lote → 500, sin corromper.
- La previa no detecta duplicados **dentro del mismo archivo**, solo contra lo que ya está
  en la corrida (las lista a las dos, así que el usuario las ve).
- `preview_agregar` devuelve `modo` y el diálogo no lo usa.
- La previa no tiene tope propio de filas (la acota el límite de 15 MB de subida).
- Los inputs de cantidad/precio tienen `min="0"` y el DTO `Field(ge=0)`, pero la vía
  preexistente del Excel (`read_licitacion`) sigue aceptando negativos: hueco viejo,
  repo-wide, fuera del alcance de esta rama.

## Incidente asociado (cerrado)

Durante este trabajo, dos corridas de un test nuevo escribieron fixtures contra la Supabase
de **producción**: `config.db_backend()` devuelve `'postgres'` con solo que exista
`DATABASE_URL` en el entorno, y ahí `Almacen` **ignora** los paths SQLite que el test le
pasa. En esa máquina la variable estaba exportada apuntando a producción.

- **Arreglo de raíz:** fixture autouse `_nunca_postgres_del_entorno` en `tests/conftest.py`
  (borra `DATABASE_URL`/`APU_DB_BACKEND` en cada test) + su centinela en
  `tests/test_config_endurecimiento.py`. Los tests de Postgres no se ven afectados: usan
  `TEST_DATABASE_URL` y construyen su propia `Conexion`.
- **Limpieza de producción: hecha.** Se borraron 11 corridas basura, el APU `A1`/DIURNO con
  sus 14 componentes, el insumo `100` y la lista "NP Calle 13". Totales verificados después:
  insumos 8159, precios 8226, apus 1272, componentes 5652, corridas 18, ítems 5677.
- **Pendiente:** rotar la contraseña de esa base.
- El fixture es de scope función: código a nivel de import o una fixture de sesión que abra
  DB seguiría viendo la variable. Fuera de `tests/`, verificar
  `config.db_backend() == "sqlite"` antes de correr cualquier script contra datos locales.

## Hueco que dejó al descubierto

El plan daba por hecho que `tests/test_repositorios_contrato.py` falla si un método de
persistencia falta en un backend. **Es falso:** solo cubre Precios y Apus. `CorridasPg` no
tenía ninguna prueba en el repo, y producción corre solo Postgres. Se agregó la comparación
`CorridasDB` vs `CorridasPg` a `tests/test_paridad_backends.py` (firmas, sin servidor).
