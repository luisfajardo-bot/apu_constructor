# Diseño — `status` del CLI y de la GUI cuentan los insumos visibles

> Fecha: 2026-07-31
> Estado: aprobado en brainstorming
> Rama de trabajo: `fix/status-cli-gui-insumos-visibles`

## El problema

`e40d0f7` hizo que el chip de la barra de la web cuente los insumos **visibles** (los que
no están ocultos), para que diera el mismo número que la tabla de Insumos. Las otras dos
superficies que muestran ese conteo quedaron con el total:

- `apu_tool/interfaz/cli.py::cmd_status` (línea 71) → `c.get('insumos', 0)`
- `apu_tool/interfaz/gui.py::_refresh_status` (línea 168) → `c['insumos']`

Hoy, en la base del usuario: la web dice **7167** y el CLI dice **8157**. Los 990 de
diferencia son los códigos ocultos (eco de un APU, sin uso real). Tres superficies, dos
números distintos para lo mismo.

## Decisiones tomadas (brainstorming)

- **Un solo número: los visibles**, igual que la web. El total con ocultos deja de estar a
  la vista (sigue disponible en `counts()["insumos"]`, que es el guard de `seed()`).
- **Los dumps crudos del diccionario de conteos NO se tocan**: `cli.py:59`
  (`print("Semillado OK:", counts)`, en `cmd_seed`) y `cli.py:230`
  (`print("  ", ensure_seeded())`, en `cmd_demo`). Son salidas de diagnóstico y, recién
  semillada la base, visibles y total coinciden (el semillado recrea el catálogo y nada
  queda oculto), así que el dump no engaña a nadie.
- **Enfoque: leer la clave inline en los dos archivos**, con la misma expresión que ya usa
  `servicio/rutas.py::status`. Descartado extraer un helper compartido
  (`nucleo/conteos.py`): es un módulo nuevo para una expresión de una línea, y el fallback
  ya vive duplicado sin dolor. Si aparece un cuarto consumidor, el helper se paga solo.

## Invariante #1 (recordatorio)

No toca la IA: no hay payloads hacia el modelo, ni campos monetarios, ni `privacy.py`.
Tampoco toca el motor de precios ni la persistencia: son dos f-strings.

## Diseño

**`apu_tool/interfaz/cli.py::cmd_status`**

```python
    # Los VISIBLES, igual que /api/status y la tabla de Insumos. El total con ocultos
    # sigue en counts()["insumos"], que es el guard de seed().
    print(f"  Insumos:        {c.get('insumos_visibles', c.get('insumos', 0))}")
```

**`apu_tool/interfaz/gui.py::_refresh_status`** — mismo criterio, misma línea de estado.

El `fallback` al total no es decorativo: protege de un `KeyError` si algún día un backend
no trae la clave. `precios_db.counts()` siempre la incluye (cae al total cuando la columna
`oculto` no existe, para bases anteriores a esa migración), y `precios_pg.counts()` también.

## Pruebas

`tests/test_cli_status.py` hoy solo verifica que `cmd_status` no crashee. Se extiende con
un test que inserta 3 insumos, oculta 1, y afirma que la salida imprime **2** y no 3.

**La GUI queda sin test**: el repo no tiene infraestructura de Tkinter (necesita display y
sería flaky en CI). El cambio es una línea de f-string; se verifica leyéndolo.

Verificación adicional: correr `python run_cli.py status` contra la base real y comprobar
que imprime 7167 (no 8157), y la suite completa con Postgres.

## Qué NO cambia

- Los dos dumps crudos de `cmd_seed` y `cmd_demo`.
- `counts()`, el guard de `seed()`, la web, el esquema, los tests existentes.
