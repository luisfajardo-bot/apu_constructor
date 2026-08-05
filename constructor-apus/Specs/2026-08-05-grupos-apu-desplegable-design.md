> Espejo automático — no editar aquí. Fuente: `docs/superpowers/specs/2026-08-05-grupos-apu-desplegable-design.md`

# Grupo del APU como desplegable (vocabulario cerrado)

Fecha: 2026-08-05

## Problema

El campo **Grupo** de la cabecera de un APU es un `<input>` de texto libre
(`DialogoAgregarApu.tsx:332`) y además es **obligatorio** para guardar
(`DialogoAgregarApu.tsx:216`). O sea: cualquiera que edite uno de los 1179 APUs que
hoy tienen `grupo=''` está forzado a escribir un grupo a mano, sin ver qué escribieron
los demás. De ahí salen las variantes.

El catálogo de insumos ya muestra a dónde lleva eso: **161 grupos distintos**, con
mayúsculas, tildes y nombres de contrato mezclados.

## Alcance

- El Grupo del APU pasa a ser un **desplegable cerrado** al crear, editar y duplicar
  un APU.
- El vocabulario arranca con 10 capítulos de obra y **los Admin pueden agregar** más.
- Un editor no puede inventar un grupo nuevo desde la pantalla.

Fuera de alcance: renombrar un grupo en masa; tocar los grupos de **insumos** (otro
campo, otro problema).

## Dónde vive el vocabulario

**No hay tabla nueva.** El desplegable es la unión de:

1. una lista base sembrada en `config.py`, y
2. los grupos que ya usa algún APU (`SELECT DISTINCT grupo FROM apus`).

Se descartó copiar el patrón `lista_precios` (tabla + DDL en los dos backends +
servicio con auditoría + GET/POST/PATCH): son ~300 líneas en 8 archivos y un `.sql`
que hay que aplicar a mano en Supabase — y el `0005_lista_precios_rls.sql` todavía
está pendiente de aplicarse en producción.

La unión, además, tiene dos propiedades que la tabla no tendría:

- **Se autolimpia**: un grupo con typo que quede sin ningún APU desaparece solo del
  desplegable. La tabla, siguiendo el patrón `lista_precios`, no tendría DELETE, así
  que el typo se quedaría para siempre.
- **Un Admin crea un grupo escribiéndolo** al guardar el APU; desde ese momento lo ve
  todo el mundo. Si cancela el diálogo no se creó nada, que es lo correcto.

Lo que se pierde y se acepta: no se puede renombrar un grupo sin editar los APUs que
lo usan.

### Lista base

En `config.py`:

```python
GRUPOS_APU_BASE: tuple[str, ...] = (
    "PAVIMENTOS",
    "REDES DE ACUEDUCTO",
    "REDES DE ALCANTARILLADO Y DRENAJE",
    "REDES ELÉCTRICAS",
    "REDES TELEFÓNICAS Y DATOS",
    "CONCRETO Y ACERO PARA ESTRUCTURAS",
    "EXCAVACIONES Y RELLENOS",
    "ANDENES Y SARDINELES",
    "SEÑALIZACIÓN",
    "MOBILIARIO URBANO Y PAISAJISMO",
)
```

Sale de los grupos de insumos que el propio catálogo ya usa como capítulos.
`config.py` ya es el hogar de este tipo de constante transversal
(`PUBLIC_PRICE_SOURCES`, umbrales de matching).

## Backend

- `datos/repositorio.py` — al `Protocol` de APUs: `def grupos(self) -> list[str]: ...`
- `datos/apus_db.py` y `datos/pg/apus_pg.py` — espejo exacto de
  `precios_db.py:418::grupos()`:
  `SELECT DISTINCT grupo FROM apus WHERE grupo IS NOT NULL AND grupo <> '' ORDER BY grupo`
  (en Postgres, `apus.apus`).
- `servicio/apus.py` — el vocabulario, con dedup insensible a tildes/mayúsculas
  usando `nucleo/texto.py::normalizar` (mismo criterio que `listas.py`); gana la
  ortografía de `config`:

  ```python
  def grupos(alm: Almacen) -> list[str]:
      """Vocabulario de grupos de APU: la lista base ∪ los grupos en uso."""
      vistos = {normalizar(g): g for g in alm.apus.grupos()}
      vistos.update({normalizar(g): g for g in config.GRUPOS_APU_BASE})
      return sorted(vistos.values())
  ```

- `servicio/rutas.py` — `GET /api/apus/grupos` con `requiere_rol("consulta")`, al
  lado de `GET /apus`. No hay colisión de rutas: `/apus/{codigo}/{turno}` son dos
  segmentos.

### Por qué el backend NO valida el vocabulario

Decisión explícita: `crear_apu` / `editar_apu` **no** cambian. El vocabulario se
cierra en la pantalla (el `<select>` no deja tipear) y no en la API.

Razones:

- El grupo es higiene de datos, no una invariante funcional. Un turno inválido rompe
  la identidad y el costeo del APU, y por eso `autoria.py:157` sí lo valida; un grupo
  raro no rompe nada. Validar el grupo y no el nombre ni la unidad sería teatro.
- El único cliente de la API es esta app. Saltar el `<select>` requiere pegarle a
  `POST /apus/crear` a mano, y quien puede hacerlo ya puede escribir nombres,
  unidades y composiciones arbitrarias.
- El daño máximo es **un** APU con grupo raro: se ve en la columna Grupo de la página
  de APUs, y desaparece solo del desplegable cuando ningún APU lo usa.
- Validar costaría además revisar y ajustar los ~34 sitios de test que hoy crean APUs
  con grupos como `"OC"` o `"G"`, churn ajeno a esta feature.

Techo conocido, a anotar con un comentario `ponytail:` en `servicio/apus.py`: si algún
día hay un segundo cliente de la API o el vocabulario se ensucia igual, el upgrade es
un `_validar_grupo(alm, grupo, actor)` en las dos escrituras que exija estar en el
vocabulario salvo para `rol == "admin"`.

**El importador de Excel también queda afuera**, y seguiría afuera incluso con
validación: `aplicar_importar_apus` (`autoria.py:470`) escribe con
`alm.apus.crear_apu(...)` directo. Una importación del histórico trae los grupos que
traiga. Consecuencia aceptada: esos grupos aparecen solos en el desplegable, que es la
forma orgánica de que crezca el vocabulario.

## Frontend

`web/src/components/autoria/DialogoAgregarApu.tsx`:

- El `<input>` de Grupo pasa a `<select>` con las opciones de `getGruposApu()`,
  cargadas al abrir el diálogo.
- **El valor actual siempre está entre las opciones**, aunque no esté en el
  vocabulario: si no, editar un APU viejo con `grupo='NA'` le cambiaría el grupo sin
  querer al abrir el diálogo.
- Grupo vacío → una opción placeholder deshabilitada, para que `cabeceraValida`
  (línea 216) siga bloqueando el guardado como hoy.
- Un botón **+ nuevo grupo** que pide el nombre con `window.prompt`, lo agrega a las
  opciones locales y lo deja seleccionado. `window.prompt` es el patrón de la casa para
  "crear una cosa con nombre" (7 usos entre listas, carpetas y renombrar corridas), y
  evita el modal anidado que ya rompió una vez (`DialogoTexto`, revertido).
  El grupo se persiste implícitamente al guardar el APU.
- El rol llega por una prop nueva `puedeCrearGrupo?: boolean` (default `false`), **no**
  por `useAuth()`: `lib/auth.tsx:68` hace que `useAuth()` lance fuera de
  `<AuthProvider>`, y `DialogoAgregarApu.test.tsx` y `TablaItems.test.tsx` montan el
  diálogo sin provider. Leerlo con el hook rompería esos tests — el mismo tipo de error
  que el `DialogoTexto` revertido.
- **Solo la página de APUs pasa la prop** (`Apus.tsx:41` ya tiene
  `puede(perfil?.rol, "admin")`), en sus 3 montajes del diálogo. El flujo de duplicar
  desde la corrida (`TablaItems.tsx`) no cambia: crear vocabulario mientras se costea
  una corrida no es el momento, y el grupo nuevo queda disponible en todas partes
  igual. Así la prop tiene un solo llamador.

Cuidado al implementar: agregar `getGruposApu` al módulo `@/api/autoria` obliga a
sumarlo a las factories de `vi.mock("@/api/autoria", …)` de los tests que abren el
diálogo (`DialogoAgregarApu.test.tsx`, `TablaItems.test.tsx`, `Apus.duplicar.test.tsx`),
porque esas factories listan función por función y un miembro ausente revienta al
llamarse.

`web/src/api/autoria.ts`: `getGruposApu(): Promise<string[]>`.

## Pruebas

`tests/test_apus_grupos.py` (pytest):

- el vocabulario es base ∪ en-uso, ordenado, sin string vacío;
- si un APU usa `"Pavimentos"` y la base tiene `"PAVIMENTOS"`, aparece **una** sola
  vez y con la ortografía de `config`;
- un grupo que deja de usarse desaparece del vocabulario (la autolimpieza es una
  propiedad de la que dependemos, así que va cubierta);
- el `grupos()` de los dos backends (SQLite y Postgres) da lo mismo — va con los tests
  de Postgres existentes.

Ningún test existente cambia: no se toca ninguna escritura.

`DialogoAgregarApu.test.tsx` (vitest): el select se llena desde el endpoint; el grupo
actual del APU aparece aunque no esté en el vocabulario; **+ nuevo grupo** no se
muestra con rol editor y sí con admin; guardar manda el grupo elegido.

## Verificación manual

Levantar la web en local, crear un APU (el desplegable trae los 10 capítulos), editar
uno de los que tienen grupo vacío, y con un usuario editor confirmar que no hay
**+ nuevo grupo**. El navegador va antes del push.
