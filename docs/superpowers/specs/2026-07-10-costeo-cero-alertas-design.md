# Costeo en $0 nunca mudo + regla "nada en 0" — diseño

Fecha: 2026-07-10
Estado: aprobado (pendiente revisión de spec)

## Problema

El cuadro entregable puede **subvaluar el costo en silencio**, lo que sobreestima
el margen y expone a licitar por debajo del costo. Dos caminos (auditoría
2026-07-08, CR-1 y CR-2):

- **CR-1** — Un insumo con cruce `ambiguo`/`huerfano` o sin precio vigente cae al
  precio histórico embebido, que muchas veces es 0 (y en el respaldo de corrida
  está forzado a `0.0`). La línea cuesta $0. La señal `calidad_cruce` solo aparece
  en la hoja DESGLOSE, **nunca en el RESUMEN** que se entrega.
- **CR-2** — Un componente sub-APU (`tipo="apu"`) cuya composición está vacía al
  turno resuelto suma $0, se memoiza y se devuelve como costo normal
  (`fuente="APU"`), **sin caída al histórico** y con aspecto benigno.

## Regla de negocio

**Nada puede costar $0. Un precio/costo en $0 es SIEMPRE una alerta, sin
excepción.** Si un material lo pone el cliente (o el costo real sería cero), se
registra en **1**, nunca en 0. (Ver memoria `regla-nada-en-cero`.)

## Alcance

Defensa en **dos capas**:

1. **Guard de entrada** — rechazar `precio <= 0` en las escrituras de precio del
   usuario. NO se toca seed/ingesta ni el repositorio (el histórico puede traer
   0s; esos los atrapa la capa 2, y no queremos romper el bootstrap).
2. **Alerta de costeo** — el $0 (y otros cruces dudosos) se hace **visible** en el
   RESUMEN + ALERTAS de ambos reportes y en la vista web de la corrida. El cuadro
   se sigue generando (marcar y seguir, no bloquear).

Fuera de alcance: bloquear la generación del cuadro; el bug de edición en lote
(CR-3, se hace aparte); reclasificar los 0s ya sembrados (se editan a mano, ahora
forzados a > 0).

## Diseño

### Capa 1 — Guard de entrada (`precio > 0`)

Mensaje único: **"El precio debe ser mayor que 0. Usa 1 si el ítem no tiene costo
(p. ej. material del cliente)."**

- `apu_tool/servicio/insumos.py::aplicar_cambios` (~línea 47): cambiar
  `if precio < 0` por `if precio <= 0` con el mensaje nuevo.
- `apu_tool/servicio/autoria.py::crear_insumo` (~línea 38-40): igual.
- `apu_tool/servicio/autoria.py::aplicar_importar_insumos`: una fila cuyo precio
  resultante sea `<= 0` (nuevo insumo, o update con `tiene_precio` y precio `<= 0`)
  se agrega a `errores` con el mensaje y **no** se aplica (respeta el
  partial-success del import). Un update con `tiene_precio=False` no toca el precio
  (sigue igual).
- CLI `db update-price` (`apu_tool/interfaz/cli.py`): validar `precio > 0` antes de
  llamar a `set_precio`; si no, salir con error claro.
- **No** se guarda en `datos/` (repos, seed): el guard es de servicio/CLI. La
  suite de seed y el catálogo histórico no cambian de comportamiento.

### Capa 2 — Alerta de costeo

**Motor (`apu_tool/dominio/pricing.py`) — único cambio de comportamiento:**
`_cost_subapu` detecta composición vacía al turno resuelto
(`components(codigo, sub_shift)` vacío) → **cae al `precio_unitario_hist` embebido**
(igual que la rama de ciclo) y marca `calidad_cruce="apu_vacio"`. Si el histórico
también es 0, el costo queda en 0 y lo atrapa `alertas_costeo` como "en $0". El
resto del motor queda idéntico; los ítems que hoy costean bien no cambian.

**Nuevo valor de `calidad_cruce`:** `apu_vacio` (se suma a
`exacto | aproximado | ambiguo | huerfano | apu | ciclo`). Documentar en el
docstring del campo en `apu_tool/nucleo/models.py::CostedComponent`.

**Función pura de detección — `apu_tool/dominio/alertas.py` (módulo nuevo):**

```python
def alertas_costeo(a: AssembledApu) -> list[str]:
    """Motivos por los que un ítem necesita revisión de costo. Lista vacía = sin
    alerta. Vive del lado con dinero; NUNCA entra al payload de la IA."""
```

Reglas (una entrada por motivo, texto legible con código/nombre del componente):
- **Cualquier componente con `costo <= 0` o `precio_unitario <= 0` → "en $0"**
  (regla dura, siempre).
- `calidad_cruce == "ambiguo"` → "cruce ambiguo".
- `calidad_cruce == "huerfano"` → "sin insumo en catálogo".
- `calidad_cruce == "apu_vacio"` → "sub-APU sin composición".
- `calidad_cruce == "ciclo"` → "ciclo de sub-APUs".

El $0 se lee del número (no se sobreescribe `calidad_cruce` del insumo), así el
DESGLOSE conserva la calidad del cruce. No se agrega un motivo separado por
`fuente_precio == "histórico"`: cae al respaldo justo cuando el cruce es
`ambiguo`/`huerfano` (ya cubierto) o cuando el precio es ≤ 0 (cubierto por "en
$0"), así que sería redundante y ruidoso.

**Superficie — reusan `alertas_costeo`:**

- `apu_tool/dominio/report.py`:
  - `_build_resumen`: nueva prioridad de resaltado — si `alertas_costeo(a)` no está
    vacía → `_ALERT_FILL` (color propio, p. ej. naranja fuerte, distinto del rojo
    de margen negativo y del amarillo de review); luego `margen_total < 0` → rojo;
    luego review/new → amarillo.
  - `_build_alertas`: incluir también los ítems con `alertas_costeo` no vacía,
    listando los motivos (unir con "; "). Ajustar el "Sin alertas" para que solo
    aparezca si no hay alertas de estado **ni** de costeo.
- `apu_tool/dominio/report_categorizado.py`: mismos dos cambios (mismo patrón de
  RESUMEN + `_build_alertas`).
- `apu_tool/servicio/corridas.py::_vista_item`: agregar
  `"alertas_costeo": alertas_costeo(ens)` (lista). `_totales`: agregar
  `"n_alertas_costeo": <nº de ítems con alerta de costeo>`. El frontend lo usa para
  marcar la fila y mostrar el conteo (cambio de front, se detalla en el plan).

## Modelo de datos / contratos

- `CostedComponent.calidad_cruce`: nuevo valor posible `apu_vacio` (solo doc; el
  campo ya es `str`). Sin migración de BD.
- Vista de corrida (`_vista_item`/`_totales`): campos nuevos `alertas_costeo`
  (lista, por ítem) y `n_alertas_costeo` (total). Aditivo; no rompe consumidores.
- `web/src/lib/tipos.ts`: agregar `alertas_costeo?: string[]` a `ItemCuadro` y
  `n_alertas_costeo?: number` a los totales (detalle en el plan).

## Privacidad (Invariante #1)

`alertas_costeo` opera sobre `AssembledApu`/`CostedComponent` (lado con dinero) y
solo se usa en report/corridas hacia el equipo. **No entra al payload de la IA.**
No se agregan campos monetarios a las vistas `DePriced*` ni a `_FORBIDDEN_KEYS`.

## Pruebas

- `tests/` nuevo para `alertas_costeo`: $0 en insumo → "en $0"; `ambiguo`/
  `huerfano`/`apu_vacio`/`ciclo` → su motivo; un insumo `ambiguo` con histórico
  > 0 → **solo** "cruce ambiguo" (sin motivo extra de respaldo); ítem limpio →
  lista vacía.
- `pricing`: sub-APU con composición vacía → cae a histórico + `apu_vacio`
  (con histórico > 0 y con histórico = 0 → sigue en $0). Los tests de costeo
  existentes deben quedar idénticos (sin regresión).
- `report` / `report_categorizado`: RESUMEN resalta la fila con alerta de costeo;
  ALERTAS lista los motivos de costeo además de los de estado.
- Vista de corrida: `_vista_item` expone `alertas_costeo`; `_totales` cuenta
  `n_alertas_costeo`.
- Guard de entrada: `aplicar_cambios`, `crear_insumo`, import (fila `<= 0` → error)
  y CLI `db update-price` rechazan `precio <= 0`.
- Suite completa (`pytest -q` + tests del front) verde antes de dar por terminado.

## Fuera de alcance

- Bloquear la generación del cuadro cuando hay alertas (se decidió "marcar y
  seguir").
- CR-3 (edición en lote que corrompe precio/fuente al paginar).
- Reclasificar o limpiar los precios en $0 ya sembrados desde el histórico.
