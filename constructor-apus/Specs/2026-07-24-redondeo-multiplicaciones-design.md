> Espejo automático — no editar aquí. Fuente: `docs/superpowers/specs/2026-07-24-redondeo-multiplicaciones-design.md`

# Diseño — Redondeo a la unidad en multiplicaciones

> Fecha: 2026-07-24
> Estado: propuesto (aprobado en brainstorming; pendiente de revisión del spec escrito)
> Rama de trabajo sugerida: `feat/redondeo-multiplicaciones`

## Objetivo

El negocio no trabaja con decimales en dinero. Hoy el costeo multiplica con `float`
(p. ej. `rendimiento × precio`, `costo_unitario × cantidad`) y el redondeo a peso solo
ocurre al mostrar (`cop()` en el frontend); los valores calculados/persistidos arrastran
decimales. Este proyecto redondea **el resultado de cada multiplicación monetaria a la
unidad (peso) más cercana**, en el cálculo mismo, de modo que nunca haya decimales en
costos ni totales.

## Decisiones tomadas (brainstorming)

- **Granularidad:** se redondea el resultado de **cada** multiplicación, no solo los
  totales finales ("siempre que hay multiplicaciones").
- **Unidad y modo:** a la **unidad (peso) entera** más cercana, con **medio hacia
  arriba** (`1312.5 → 1313`, `0.5 → 1`). **No** el `round()` de Python (redondeo de
  banquero, `1312.5 → 1312`).
- **Choque con "nada en $0":** si un producto es **positivo** pero redondearía a 0, se
  fija en **1**. Un $0 genuino (precio 0 / rendimiento 0) queda en 0 y lo sigue marcando
  la alerta de costeo existente (no se suprime).
- **Alcance:** ambos lados — **costo y contractual**. `contractual_total =
  precio_contractual × cantidad` también se redondea.
- **Dónde vive:** un helper puro central, con **gemelo** en backend (Python) y frontend
  (TS), para que el diálogo editable y el costeo den el mismo número.

## Invariante #1 (recordatorio)

Esta feature **no toca la IA**. Solo cambia aritmética de dinero, que vive en
`pricing.py`/`report.py`/`models.py` — módulos que nunca se le pasan a la IA. No hay
payload nuevo hacia la IA; `privacy.py` no se toca.

## Helper central (regla única)

`mul_redondeado(a, b) -> int`:

1. `p = a * b`
2. `r = floor(p + 0.5)` — redondeo a la unidad más cercana, medio hacia arriba
   (el dominio es no-negativo: costos, precios y cantidades ≥ 0).
3. Si `p > 0` y `r == 0` → devuelve **1** (nada en $0 por redondeo).
4. Si `p == 0` → devuelve **0** (0 genuino; lo captura la alerta de costeo existente).

- Backend: `apu_tool/dominio/redondeo.py` (puro, sin I/O, testeable).
- Frontend: gemelo en `web/src/lib/redondeo.ts` con la misma semántica
  (`Math.round` en JS ya es medio-hacia-+∞: `Math.round(1312.5)=1313`, `Math.round(0.5)=1`;
  se envuelve con la regla del mínimo-1).

## Dónde se aplica (inventario de multiplicaciones)

- **`apu_tool/dominio/pricing.py`** (3 sitios):
  - `cost_component` (insumo): `costo = mul_redondeado(rendimiento, precio)`.
  - `_cost_subapu`: `costo = mul_redondeado(rendimiento, unit)` (unit = costo unitario del
    sub-APU, ya entero por ser suma de enteros).
  - `_fallback_historico`: `costo = mul_redondeado(rendimiento, precio_hist)`.
- **Costo unitario del APU** = `sum(costos de componentes)`: es una **suma** de enteros
  → queda entero. No es multiplicación; no se redondea aparte.
- **`apu_tool/nucleo/models.py` (AssembledApu)**:
  - `costo_total = mul_redondeado(costo_unitario, cantidad)`.
  - `contractual_total = mul_redondeado(precio_contractual, cantidad)`.
- **Frontend `web/src/lib/costoApu.ts`**: el total en vivo del diálogo editable calcula
  cada componente con `mul_redondeado` → coincide con el costeo del backend.

**No se tocan** (no son multiplicaciones):
- Sumas: costo unitario del APU, totales agregados de la corrida.
- Restas: `margen_unitario`, `margen_total` (si sus operandos ya son enteros, el
  resultado es entero).
- División: `margen_pct` (es un porcentaje; se muestra con decimales, p. ej. `8.1%`).

## Interacción con "nada en $0"

El mínimo-1 entra **solo** cuando el producto es positivo y el redondeo lo llevaría a 0.
Un $0 legítimo (precio faltante, material del cliente, rendimiento 0) sigue igual y lo
captura la alerta de costeo (`alertas.py`) como hoy. No suprimimos alertas reales; solo
evitamos que el redondeo **cree** un $0 falso.

## Corridas congeladas (snapshots)

Los `snapshot_json` de corridas ya congeladas son fotos inmutables (cotizaciones
emitidas) — **no se re-redondean**. Se leen tal cual se guardaron. Las corridas que se
congelen a partir de este cambio usan los valores ya redondeados.

## Pruebas

- **Unit del helper** (`tests/test_redondeo.py`): medio-hacia-arriba (`0.5→1`,
  `1312.5→1313`, `1312.4→1312`); mínimo-1 si positivo (`0.3→1`); 0 genuino queda 0
  (`0.0→0`); casos con entero exacto sin cambio (`1.0*350000→350000`).
- **Pricing** (`tests/`): costo de componente redondeado; sub-APU redondeado; suma de
  componentes entera.
- **Report / corrida**: `costo_total`, `contractual_total`, márgenes derivados de
  enteros; actualizar los valores esperados de los tests existentes cuyo producto tenía
  fracción (los que ya daban entero no cambian).
- **Frontend** (`web/src/lib/redondeo.test.ts`, `costoApu.test.ts`): helper + total en
  vivo del diálogo con redondeo por componente.

## Fuera de alcance (YAGNI)

- Redondear restas/divisiones o el `margen_pct`.
- Re-redondear datos históricos / snapshots congelados.
- Cambiar el redondeo de display (`cop()`), que seguirá funcionando sobre valores ya
  enteros.
