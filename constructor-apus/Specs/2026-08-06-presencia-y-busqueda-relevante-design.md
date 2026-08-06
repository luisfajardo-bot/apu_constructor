> Espejo automático — no editar aquí. Fuente: `docs/superpowers/specs/2026-08-06-presencia-y-busqueda-relevante-design.md`

# Presencia en línea + búsqueda ordenada por relevancia

Fecha: 2026-08-06
Rama: `feat/presencia-y-busqueda-relevante`

Dos features independientes que no comparten un solo archivo. Van en la misma rama
por comodidad de merge y smoke test, en dos fases separadas.

---

## Feature 1 — Ver quién está usando la app

### Problema

La app es multiusuario en producción (Render + Supabase) y no hay forma de saber si
alguien más está conectado ahora mismo.

### Alcance decidido

- **Solo quién está conectado.** No qué pantalla está mirando, no aviso de colisión.
- **Todos los usuarios ven la lista** (consulta / editor / admin), no solo Admin.

### Enfoque elegido: `dict` en memoria del proceso

Se descartaron:

- **Tabla `presencia` en la DB**: migración dual-backend + un write a Supabase por
  usuario por minuto, para un dato que caduca en 90 segundos.
- **SSE / WebSocket**: manejo de conexiones y reconexión; Render free corta conexiones
  largas. El beneficio sobre un poll de 45 s es nulo para este dato.

### Diseño

```
apu_tool/servicio/presencia.py     (nuevo, sin DB)
apu_tool/servicio/rutas.py         (GET /api/presencia)
web/src/api/presencia.ts           (cliente del endpoint)
web/src/components/Layout.tsx      (poll 45 s + una <Lectura> más en la barra)
```

**`servicio/presencia.py`**

```python
VENTANA_S = 90.0

_vistos: dict[str, tuple[float, str, str]] = {}   # user_id -> (ts, email, nombre)

def marcar(perfil, *, ahora: float | None = None) -> None
def en_linea(*, ahora: float | None = None) -> list[dict]   # [{user_id, email, nombre}]
```

- `marcar` se llama **dentro del propio endpoint** `GET /api/presencia`, no en
  `auth.usuario_actual`. El latido ES el poll (abajo), así que marcar en el endpoint
  alcanza y `auth.py` no se toca: presencia no se acopla a la autenticación, y el
  endpoint queda testeable — los tests overridean la dependencia `usuario_actual`, así
  que un `marcar` metido ahí adentro no se ejecutaría en ninguna prueba.
- `en_linea` filtra `ts > ahora - VENTANA_S` y ordena por `nombre or email`.
- `ahora` es parámetro inyectable para que el test no dependa del reloj.
- Ceiling documentado en el módulo:
  `# ponytail: dict en el proceso — si algún día hay 2 instances, cada uno ve su mitad; upgrade = tabla presencia`.

**Endpoint**

`GET /api/presencia` con `Depends(requiere_rol("consulta"))`: `marcar(usuario)` y
devuelve `{"en_linea": [{user_id, email, nombre}, ...]}`. No toca la DB: el `Almacen`
no entra. No ve dinero (Invariante #1 intacto).

**Latido = el propio poll.** No existe endpoint de latido: pedir la lista te marca
presente. Un cliente, un timer, nada de estado extra. Consecuencia buscada: siempre
apareces en tu propia lista, así que nunca se ve vacía.

**Frontend** (`Layout.tsx`)

- `useEffect` con `setInterval` de 45 s (dos latidos dentro de la ventana de 90 s, para
  que una petición perdida no apague el punto) + una llamada inmediata al montar.
- `if (document.hidden) return;` antes de pedir: una pestaña de fondo deja de latir y
  desaparece a los 90 s. "En línea" significa usándola, no teniéndola abierta.
- Fallo de red: silencioso, como el `getStatus()` de hoy. Se conserva la última lista.
- UI: una `<Lectura etiqueta="En línea">` más, a la izquierda de Insumos/APUs/IA —
  punto verde (`bg-margen-pos`) + conteo. Los nombres van en el `title` del elemento,
  uno por línea, con `(vos)` al lado del propio (comparando contra `perfil.email`).
  Densa y sin cards, igual que el resto de la barra. Se oculta con el mismo
  `@max-[980px]:hidden` que las otras lecturas.

### Pruebas

`tests/test_presencia.py` con reloj inyectado:

- `marcar` → el usuario aparece en `en_linea`.
- `+91 s` → no aparece.
- `+45 s` + `marcar` de nuevo → sigue apareciendo.
- dos usuarios → ambos, ordenados.

Un test de la ruta (`GET /api/presencia` con el cliente de tests ya existente)
verificando que el propio request te deja en la lista.

---

## Feature 2 — Búsqueda ordenada por relevancia

### Problema

Buscar `transporte` devuelve todo lo que contenga el string, **ordenado por código**
(`ORDER BY codigo` en `apus_db.py:207` y `precios_db.py:414`). No existe noción de
relevancia en ninguna capa. Además, dos defectos del mismo `q`:

1. `q` se usa como **frase literal**: `transporte material` hace
   `LIKE '%transporte material%'` y devuelve **cero filas** (no encuentra
   "TRANSPORTE DE MATERIAL SOBRANTE").
2. En APUs el `LIKE` va contra `nombre` crudo, no normalizado (el TODO de
   `apus_db.py:188-190`): `excavacion` no encuentra "EXCAVACIÓN". En Insumos sí
   funciona, porque usan `nombre_norm`.

Los tres entran en el alcance.

### Enfoque elegido: híbrido nivel + score, rankeado en Python

Se descartaron:

- **Solo `ORDER BY` en SQL con niveles**: se paginaría gratis, pero el desempate dentro
  de un nivel sería por longitud del nombre, no por parecido.
- **Solo score de `difflib`**: penaliza nombres largos que sí son el resultado correcto
  ("TRANSPORTE DE MATERIAL SOBRANTE 20 KM" cae por debajo de "RETIRO Y TRANSPORTE").

El híbrido usa el nivel como criterio primario y el score solo para desempatar dentro
del nivel.

### Diseño

**`apu_tool/nucleo/relevancia.py`** (nuevo, puro, sin dependencias de otras capas —
donde ya vive `nucleo/texto.py`, que `datos/` importa hoy).

```python
def palabras(q: str) -> list[str]
    """normalizar(q).split() — las palabras de la consulta, sin vacías."""

def nivel(nombre, codigo, q_norm, palabras_q) -> int | None
    """Nivel de coincidencia; None si no coinciden TODAS las palabras de la consulta."""

def ordenar(filas, q, *, nombre_de, codigo_de) -> list
    """Descarta las que no coinciden y ordena por (nivel asc, score desc, codigo asc).
    Determinista. Con `q` vacía devuelve las filas tal cual."""

def similarity(a, b) -> float   # movida desde dominio/matching.py (ver abajo)
```

Los 5 niveles, con `q` normalizada (sin tildes, mayúsculas):

| Nivel | Regla | `q = "transporte"` | `q = "transporte material"` |
|---|---|---|---|
| 0 | `codigo == q` o `nombre == q` | TRANSPORTE | — |
| 1 | el nombre **empieza** con la frase; o `codigo` empieza con `q` | TRANSPORTE DE MATERIAL A 5 KM | TRANSPORTE MATERIAL SOBRANTE 20 KM |
| 2 | la frase aparece en el medio, en palabras completas | RETIRO Y TRANSPORTE DE ESCOMBROS | RETIRO: TRANSPORTE MATERIAL A 5 KM |
| 3 | **todas** las palabras aparecen completas, en cualquier orden | (colapsa en 2) | TRANSPORTE DE MATERIAL SOBRANTE |
| 4 | todas aparecen, alguna pegada dentro de otra palabra | AUTOTRANSPORTEDORA | AUTOTRANSPORTE DE MATERIALES |

Con una sola palabra el nivel 3 es idéntico al 2 y no se usa; el nivel 4 es el
substring de hoy. La comparación de "palabra completa" se hace sobre
`f" {nombre_norm} "` buscando `f" {q_norm} "`, así el borde de palabra sale gratis.

Desempate dentro del nivel: `dominio/matching.py::similarity(q, nombre)` descendente
(el scorer que ya existe: difflib + Jaccard sobre tokens, sin dependencias nuevas), y
`codigo` ascendente al final para que el orden sea determinista y la paginación estable.

**Dónde vive `similarity`.** `nucleo/relevancia.py` no puede importar
`dominio/matching.py` (núcleo no depende de otras capas), y que `datos/` importe
`dominio/` sería peor (invierte la dirección: `dominio` usa `datos`). Se mueven
`similarity`, `_tokens`, `_STOPWORDS` y `normalize` de `dominio/matching.py` a
`nucleo/relevancia.py`, y `matching.py` las reexporta con el mismo nombre
(`from apu_tool.nucleo.relevancia import normalize, similarity, _tokens`). Los cuatro
importadores actuales (`compose.py` usa `similarity` y `_tokens`, `cruce.py` usa
`similarity`, `test_matching.py` usa `normalize` y `similarity`,
`test_matching_optimizacion.py` usa `matching.similarity`) siguen funcionando sin
tocarlos, y un scorer puro es exactamente lo que va en núcleo — la misma
de-duplicación que ya se hizo con `nucleo/texto.py::normalizar`.

**APUs: el filtro por texto también se va a Python — sin columna nueva.**

La tabla `apus` tiene ~1200 filas y el repo ya la lee entera en cada corrida
(`apus_db.apu_index()` alimenta al `Matcher`). Así que con `q` presente, `list_apus`
trae las filas (con `grupo` y `turno` filtrados en SQL, que es lo que narrowea barato) y
`relevancia.ordenar` hace el filtro Y el orden:

```
list_apus(q=...) -> SELECT codigo,nombre,unidad,shift,grupo FROM apus [WHERE grupo/shift]
                 -> relevancia.ordenar(...)   # AND por palabras + acentos + relevancia
                 -> [offset:offset+limit], total = len(ordenados)
```

Esto **reemplaza la columna `nombre_norm` que el borrador de esta spec proponía
agregar a `apus`**. Entrega exactamente lo mismo (`excavacion` encuentra "EXCAVACIÓN")
y elimina: la migración dual-backend, el backfill, y los 7 sitios de escritura de la
tabla `apus` (`insert_apus`, `_crear_apu`, `editar_apu` × 2 backends + `migracion_pg`)
que había que acordarse de llenar — uno olvidado deja un APU invisible a la búsqueda,
en silencio. Y cierra el TODO de `apus_db.py:188-190` **mejor** que la columna: el
criterio deja de ser `LIKE` en SQLite vs `ILIKE` en Postgres y pasa a ser un solo
código Python compartido, imposible de divergir.

Costo: un `SELECT` de ~1200 filas × 5 columnas (~145 KB) por búsqueda de APU, contra
dos queries hoy (`COUNT` + página). Un round-trip menos, más bytes — y en la
optimización de corridas (merge `3fe2c46`) lo que dolía en Supabase eran los
round-trips secuenciales, no el tamaño de la respuesta.

**Insumos: el `WHERE` se queda en SQL** — 7167 filas visibles con JOIN a precios es
demasiado para traer entero. Una palabra = un `LIKE`, todas en `AND`, cada una contra
el nombre normalizado **o** el código (`nombre_norm` ya existe en `insumos`):

```sql
-- por cada palabra de q, en AND:
(i.nombre_norm LIKE %palabra% OR UPPER(i.codigo) LIKE %palabra%)
```

Reemplaza el `LIKE '%frase%'` de `precios_db.py:385` y `pg/precios_pg.py:329`.

**Paginación de insumos:**

```
COUNT(*) con el WHERE nuevo
  count <= relevancia.MAX_RANKEO (2000):  traer todos -> ordenar() -> [offset:offset+limit]
                                          total = len(ordenados)
  count >  relevancia.MAX_RANKEO:          camino de hoy (ORDER BY codigo, LIMIT/OFFSET en SQL)
                                          total = count
```

- El corte de 2000 es el guard de CPU y de transferencia. Solo lo cruzan consultas de
  1–2 letras, donde el parecido es ruido de todas formas.
- `total = len(ordenados)` en el camino rankeado (no el `COUNT`): el `WHERE` de SQL es
  un poco más laxo que el filtro de Python (`UPPER(codigo)` vs `normalizar(codigo)`),
  y con dos fuentes de verdad el contador podría decir 41 sobre una lista de 40. Con
  `len` siempre coinciden.
- La constante vive en `nucleo/relevancia.py`, no en `config.py`: es un techo interno,
  no una perilla de operación.
- **Sin `q` no cambia nada**, ni en APUs ni en Insumos: mismo SQL, mismo
  `ORDER BY codigo`, mismo costo, mismo `total`. El camino sin búsqueda no se toca.
- Ceiling comentado: `# ponytail: arriba de MAX_RANKEO manda el orden por código; upgrade = índice de texto (pg_trgm / FTS5)`.

### Superficies afectadas

Cambian: `GET /api/apus?q=` (página APUs + `BuscadorApu` de corrida, reasignar y
asignar en lote) y `GET /api/insumos?q=` (página Insumos + `DialogoAgregarInsumo`).
El frontend **no cambia**: ya muestra las filas en el orden que llegan.

**No se tocan**: `search_apus` / `search_insumos` (ningún cliente web los llama; solo
tests) ni `search_insumos_por_palabras` (alimenta los candidatos de composición de la
IA — otro trabajo y otra frontera; ver Invariante #1).

### Pruebas

`tests/test_relevancia.py` sobre el helper puro:

- el caso "transporte" completo, con el orden esperado de los 5 niveles;
- `transporte material` encuentra "TRANSPORTE DE MATERIAL SOBRANTE" (nivel 3);
- `excavacion` encuentra "EXCAVACIÓN" (acentos);
- empate de nivel + empate de score → gana el código menor (determinismo);
- `q` vacía o solo espacios → no reordena.

Tests de la capa de datos (SQLite y el mirror de Postgres con el recetario local) para
`list_apus` / `list_insumos`:

- con `q`: el primer resultado es el que empieza con la palabra, no el de código menor;
- `q` de dos palabras encuentra el APU/insumo que las tiene separadas;
- un APU con tildes se encuentra escribiendo sin tildes (lo que antes fallaba);
- `total` es coherente con la cantidad de filas devueltas al paginar;
- sin `q`: orden por código y `total` idénticos a hoy;
- los filtros que conviven con `q` (`grupo`, `turno` en APUs; `grupo`, `fuente`,
  `clasificacion`, `sin_precio`, `lista_id` en insumos) siguen aplicando.

### Riesgo de regresión

- Cambia el orden de resultados **solo** cuando hay `q`. Nada más cambia de forma
  observable: mismos campos, mismos filtros, misma paginación.
- **Cero cambios de esquema y cero cambios de datos.** No hay migración que revisar en
  producción antes de desplegar.
- Mover `similarity` / `_tokens` / `normalize` a `nucleo/` es puro movimiento con
  reexport: `compose.py`, `cruce.py` y los dos tests de matching importan igual. Los
  tests de matching existentes son el guard de que el scorer no cambió.
- La suite completa (647 tests) debe quedar verde, incluidos los de Postgres.

---

## Orden de implementación

1. **Fase 1 — presencia**: `presencia.py` + test, línea en `auth.py`, endpoint, cliente
   y `Layout.tsx`. Independiente de todo lo demás.
2. **Fase 2 — relevancia**: `nucleo/relevancia.py` + test primero; después la migración
   `nombre_norm` con su backfill; después los cuatro `list_*`; al final los tests de
   datos.

Verificación antes de dar por terminado: `python -m pytest tests/ -q` completo
(incluyendo Postgres con el recetario local), `npm run build` en `web/` (`tsc -b`, no
`--noEmit`), y smoke test en el navegador con la web local antes de pedir el push a
master.
