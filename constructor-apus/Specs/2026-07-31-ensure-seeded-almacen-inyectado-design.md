> Espejo automático — no editar aquí. Fuente: `docs/superpowers/specs/2026-07-31-ensure-seeded-almacen-inyectado-design.md`

# Diseño — `ensure_seeded` sobre el almacén inyectado

> Fecha: 2026-07-31
> Estado: aprobado en brainstorming
> Rama de trabajo: `fix/ensure-seeded-almacen-inyectado`

## El defecto

Los endpoints que arman corridas y ejemplos preguntan si la biblioteca de APUs está
vacía y, si lo está, la semillan:

```python
# apu_tool/servicio/rutas.py (líneas 140-141, 165-166, 206-207, 232-233)
if alm.counts().get("apus", 0) == 0:
    ensure_seeded()
```

`alm` es el `Almacen` que FastAPI inyecta por request (`servicio/dependencias.py`, vive en
`app.state`). Pero `ensure_seeded()` **no lo recibe**: se arma otro por su cuenta
(`dominio/pipeline.py:41`, `alm = get_almacen()` → `Almacen()` con los valores por
defecto de `config`).

**La pregunta se le hace a una base y la acción se ejecuta sobre otra.**

## Evidencia del daño

1. **CI en rojo (2026-07-31).** Cuatro tests de API creaban un almacén temporal con
   insumos pero sin APUs; el guard decía "vacía" y `ensure_seeded()` se iba a
   `data/*.db`, que en CI no existe → `FileNotFoundError` → 500. Parcheado en los tests
   (`bd5fece`), no en la causa.
2. **Fuga de pool en producción.** Con `DATABASE_URL` seteada, `Almacen()` resuelve a
   Postgres (`datos/almacen.py:22-23`) — la base correcta, pero con una `Conexion` nueva
   (pool de hasta 10 conexiones) que **nadie cierra**: `servicio/app.py:38` solo cierra el
   almacén de la app. Cada disparo deja un pool huérfano contra el pooler de Supabase.
   *(Corrección de una afirmación previa: NO apunta a un SQLite local en producción.)*
3. **Bucle silencioso.** Si las dos bases divergen, el guard nunca se apaga: pregunta a A
   (vacía), semilla en B, vuelve a preguntar a A → semilla otra vez, en cada request. Y la
   corrida se arma con la biblioteca vacía: ningún ítem matchea con un APU y el cuadro sale
   sin costear, sin que nada avise.
4. **En la nube el auto-seed no puede funcionar**: semillar necesita el Excel histórico,
   que no está en el servidor. Cuando se dispara, el usuario ve un 500 ilegible.

**Urgencia: baja.** Requiere biblioteca vacía, y producción tiene ~68 APUs. Es el defecto
que muerde el día que se restaura un backup a medias o se levanta un ambiente nuevo.

## Invariante #1 (recordatorio)

Esto **no toca la IA**. No se construye ni se modifica ningún payload hacia el modelo, no
se agregan campos monetarios y `dominio/privacy.py` no cambia. Tampoco toca el motor de
precios: es cableado de qué `Almacen` recibe una función.

## Decisiones tomadas (brainstorming)

- **Comportamiento con la base vacía:** seguir intentando semillar (útil en local) y,
  cuando no se puede, responder un **error entendible** en vez de un 500.
- **Alcance: 5 puntos** — los 4 llamados de `rutas.py` y el interno de
  `generate_sample` (`pipeline.py:110`). Los otros 5 llamados (`run_pipeline`,
  `build_desde_presupuesto`, `cli.py`×3) **no se tocan**: ahí el almacén global es el
  correcto.
- **El llamado duplicado del camino `/sample` se queda.** El endpoint llama a
  `ensure_seeded` y después `generate_sample` lo vuelve a llamar por dentro; es inofensivo
  porque cuando el primero termina la biblioteca ya no está vacía y el segundo no dispara.
- **Enfoque elegido: parámetro opcional + excepción propia del dominio.**

## Enfoque elegido y alternativas descartadas

**Elegido — parámetro opcional.** `ensure_seeded(alm=None, ...)` usa el almacén recibido y,
si no viene, arma el global igual que hoy. Los 5 puntos elegidos le pasan el suyo. El
defecto es "no le pasamos el almacén", así que la solución proporcionada es pasárselo.

**Descartado — parámetro obligatorio** (`ensure_seeded(alm)` sin default). Hace imposible
el olvido, pero obliga a tocar los 10 llamados, incluidos `cli.py` y la GUI, que hoy
funcionan bien: mete riesgo de regresión en `run_cli.py demo/seed/build` para arreglar un
problema que solo tiene la web. El olvido se cubre mejor con el test de regresión (abajo),
que falla por la razón correcta.

**Descartado — mover el auto-seed a `servicio/`.** Dejar `pipeline.ensure_seeded` para el
CLI y crear un `asegurar_biblioteca(alm)` en la capa de servicio. Pone la responsabilidad
en la capa que tiene el almacén inyectado, pero agrega un módulo y duplica el guard para
algo que se resuelve con un parámetro.

## Diseño

### `apu_tool/dominio/pipeline.py`

```python
class BibliotecaVacia(Exception):
    """La biblioteca de APUs está vacía y no hay Excel histórico del que semillarla."""


def ensure_seeded(alm: Optional[Almacen] = None,
                  xlsx_path: Optional[Path] = None) -> dict:
    alm = alm or get_almacen()      # el del request; si no viene, el global (como hoy)
    ...
```

- Si `seed()` falla por falta de fuente (`FileNotFoundError`), `ensure_seeded` lo convierte
  en `BibliotecaVacia` con este mensaje exacto (es el que va a leer el usuario en la web,
  porque el frontend muestra el `detail` que manda el backend):

  > La biblioteca de APUs está vacía y no hay Excel histórico en el servidor. Semilla la
  > base antes de armar corridas (`run_cli.py seed`, o la variable `APU_SOURCE_XLSX`).

  La excepción vive en `pipeline.py` porque es quien la levanta (mismo criterio que
  `SeedExistente` en `datos/seed.py`).
- `generate_sample` pasa su almacén al llamado interno: `ensure_seeded(alm)`.

### `apu_tool/servicio/rutas.py`

Un helper al lado de `_validar_lista`, siguiendo ese patrón, y los 4 llamados lo usan:

```python
def _asegurar_biblioteca(alm: Almacen) -> None:
    """Auto-seed sobre LA base del request. 409 (no 500) si no hay de dónde semillar."""
    if alm.counts().get("apus", 0) != 0:
        return
    try:
        ensure_seeded(alm)
    except BibliotecaVacia as e:
        raise HTTPException(status_code=409, detail=str(e))
```

**409** es el código correcto: no es culpa del pedido (400) ni un fallo del servidor (500);
es que el estado del sistema no permite la operación todavía.

### Comportamiento: antes vs. después

| Situación | Hoy | Después |
|---|---|---|
| Biblioteca con APUs (caso normal) | no pasa nada | idéntico, ni un query extra |
| Vacía del todo (`apus`=0 y `insumos`=0) + Excel disponible (local) | semilla en `data/*.db`, aunque la app use otra base | semilla en la base del request |
| Vacía del todo (`apus`=0 y `insumos`=0) + sin Excel (Render) | 500 con `FileNotFoundError` | 409 con mensaje entendible |
| Pool de conexiones | un pool huérfano por disparo | ninguno |
| Bucle guard-A / semilla-B | posible | imposible |

**Nota — restauración a medias (`insumos` > 0, `apus` == 0):** `ensure_seeded` solo
semilla cuando las dos cuentas están en cero (`pipeline.py:55`); `_asegurar_biblioteca`
solo mira `apus` (`rutas.py`). Con insumos presentes y APUs ausentes, ninguno de los dos
guards se dispara: no se semilla, no hay 409, la corrida responde **200** y se arma
contra una biblioteca vacía — el aviso queda en las alertas de costeo por ítem. Esto es
idéntico a `master`; esta rama no lo cambia (ver Hallazgo 2 de la revisión).

## Qué NO cambia

- CLI y GUI: cero cambios (mismo default en la firma).
- El llamado duplicado del camino `/sample`.
- `counts()`, el guard de `seed()` y el parche de los tests de `bd5fece`, que queda como
  cinturón extra.
- No se audita el evento de semillado (YAGNI: solo ocurre en una base vacía).
- Ningún esquema, ninguna migración, ningún SQL.

## Pruebas

1. **El test que faltaba** (el que habría atrapado el rojo de CI): almacén temporal vacío
   inyectado y `seed` espiado; `POST /corridas` debe invocar el seed **con el almacén del
   request**, no con otro. Tiene que estar en rojo antes del arreglo.
2. **El 409**: base vacía y sin Excel → `/corridas`, `/corridas/stream`, `/sample` y
   `/sample/stream` responden 409 con el mensaje (hoy: 500).
3. **No-regresión**: con biblioteca poblada nada cambia — lo cubre la suite actual.
4. **Sin tests nuevos de Postgres**: es cableado, no SQL; los de paridad existentes siguen
   valiendo. Igual se corren los 4 pasos de `.github/workflows/ci.yml` en local (backend
   con `TEST_DATABASE_URL` + `vitest`, `build` y `oxlint`), y el backend además con el
   almacén por defecto vacío, que es la condición de CI.

## Riesgos

- **El default `None` deja la puerta abierta** a que alguien vuelva a llamar
  `ensure_seeded()` sin almacén. Mitigación: la prueba 1, que falla exactamente en ese
  escenario.
- **El 409 es un cambio visible** en un camino de error. Hoy ese camino devuelve 500, así
  que nadie puede estar dependiendo de él; el frontend muestra el `detail` que manda el
  backend, así que el mensaje nuevo se ve tal cual.
