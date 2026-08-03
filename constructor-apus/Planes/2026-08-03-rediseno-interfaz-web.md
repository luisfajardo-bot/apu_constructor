> Espejo automático — no editar aquí. Fuente: `docs/superpowers/plans/2026-08-03-rediseno-interfaz-web.md`

# Rediseño visual de la interfaz web — plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reemplazar el tema por defecto de shadcn por un sistema de diseño propio
—«instrumento de medición»— y eliminar los 29 hex a mano de los 5 archivos que todavía
usan objetos `styles: React.CSSProperties`.

**Architecture:** Todo baja por tokens CSS. Se cambia `index.css` una vez y las cinco
pantallas que ya usan Tailwind heredan la paleta sin tocarlas. Las cuatro que tienen hex a
mano se migran a esos mismos tokens. Cero cambios de backend y cero cambios de
comportamiento.

**Tech Stack:** Tailwind v4 (`@theme inline`), tokens oklch, shadcn/Radix (`components/ui/`),
`lucide-react` (ya instalado), `@fontsource-variable/*` 5.3.0 (recién instalado), vitest 4.

**Spec:** `docs/superpowers/specs/2026-08-03-rediseno-interfaz-web-design.md`

## Global Constraints

- **Invariante #1**: esto es capa de presentación. No se toca `privacy.py`, `pricing.py`,
  `report.py`, ni ningún payload hacia la IA. El backend se **lee** (la CSP), nunca se modifica.
- **Cero cambios de comportamiento.** Ni un handler, ni una llamada a la API, ni un texto
  visible al usuario. Un `git diff` de una migración solo puede mostrar estilos y estructura.
  Si un texto cambia, es un bug de la migración.
- **Español** en nombres, comentarios y mensajes de usuario.
- **Nada de CDN.** `seguridad_headers.py:22-30` es `default-src 'self'` sin `font-src` y
  `style-src 'self' 'unsafe-inline'` sin `fonts.googleapis.com`. Cualquier recurso externo
  anda en `vite dev` y falla en Render. Las fuentes se sirven de `dist/assets`.
- **Sin sombras.** La jerarquía se da con hairline (`--border`) y superficie (`--card`/`--muted`).
- **Los 11 diálogos nativos** (`window.prompt`/`confirm`) **quedan nativos**. El reemplazo se
  revirtió el 2026-08-03 (`389357a`) y sigue esperando el error de consola.
- **Densidad**: se conserva. Topbar 36px, cuerpo 13px, tablas densas intactas.
- Al terminar cada task: `npm run test`, `npm run build` (**es `tsc -b`, no `tsc --noEmit`**),
  `npm run lint`. Los tres en verde antes de commitear.
- **Los tests de vitest no validan color, tipografía, radio ni foco visible.** Son red
  anti-regresión de comportamiento. La validación visual es el navegador, y va antes del push.

## Estructura de archivos

| archivo | qué pasa | responsabilidad después |
|---|---|---|
| `web/src/index.css` | reescribir tokens | **única** fuente de color, radio y tipografía |
| `web/index.html` | 1 línea | `lang="es"` |
| `web/src/main.tsx` | +2 imports | cargar las fuentes auto-hospedadas |
| `web/src/components/Layout.tsx` | reescribir | shell: riel de estado + nav. Sin objeto `styles` |
| `web/src/components/Layout.test.tsx` | ampliar | rol admin (ya) + riel + `aria-current` |
| `web/src/pages/Login.tsx` | migrar | idéntico funcionalmente, sin hex |
| `web/src/pages/DefinirClave.tsx` | migrar | idem |
| `web/src/pages/CorridasInicio.tsx` | migrar | idem |
| `web/src/pages/MisCorridas.tsx` | migrar | idem, + badges a tokens semánticos |
| `scripts/verificar_contraste.py` | **crear** | verifica los tokens del CSS contra WCAG |

Ningún otro archivo se toca. `Insumos`, `Apus`, `Corrida`, `Auditoria`, `Usuarios`, las dos
tablas densas y los 6 diálogos heredan por token.

## Tabla de traducción hex → token

Es el mapa que usan las tasks 4-6. **No inventar mapeos fuera de esta tabla**; si aparece un
hex que no está acá, pararse y preguntar.

| hex | usos | va a | por qué |
|---|---|---|---|
| `#1a1a2e` como **fondo** | topbar, botón primario | `bg-primary` + `text-primary-foreground` | — |
| `#1a1a2e` como **texto** | títulos, valor de input | `text-foreground` | — |
| `#2d3748` | texto fuerte | `text-foreground` | — |
| `#e2e8f0` sobre oscuro | texto de topbar | `text-primary-foreground` | — |
| `#e2e8f0` como borde | paneles, separadores | `border-border` | hairline decorativo |
| `#4a5568` | etiquetas de campo | `text-foreground` + `font-medium` | una etiqueta se tiene que leer |
| `#718096` | meta, fechas | `text-muted-foreground` | hoy 4.02:1 → pasa a 5.74:1 |
| `#a0aec0` | subtítulos, ayuda | `text-muted-foreground` | **hoy 2.26:1, falla WCAG** |
| `#cbd5e0` | borde de `<input>` | `border-input` | **hoy 1.49:1, falla WCAG 1.4.11** |
| `#f7f7f8`, `#f0f4f8` | fondos de pantalla | `bg-background` | — |
| `#edf2f7` | fondo de nav activa | `bg-muted` | — |
| `#ffffff`, `#fff` | paneles, tarjetas | `bg-card` | — |
| `#4a90d9`, `#3182ce`, `#2b6cb0` | enlaces, acento | `text-ring` / `border-rail` | **`#4a90d9` hoy 3.34:1, falla** |
| `#c53030`, `#b91c1c`, `#9b2c2c` | error | `text-destructive` | — |
| `#fed7d7`, `#feb2b2` | fondo de error | `bg-destructive-surface` | — |
| `#c6f6d5` / `#276749` | estado positivo | `bg-margen-pos-surface` / `text-margen-pos` | — |
| `#bee3f8` / `#2a4365` | estado info/congelada | `bg-info-surface` / `text-info` | — |
| `#fefcbf` / `#b7791f` / `#744210` | por revisar | `bg-revisar-surface` / `text-revisar` | — |
| `#5a5f78`, `#8fb3e8` | separador y rol en topbar | `text-primary-foreground/50` y `/80` | sobre fondo oscuro |

---

### Task 0: Mockup navegable — sin tocar la app

Se aprueba la dirección **antes** de que exista un solo archivo del proyecto modificado. El
2026-08-03 se desplegó un cambio visual con 145 tests verdes y falló en el navegador.

**Files:**
- Create: `<scratchpad>/mockup-instrumento.html` (fuera del repo, no se commitea)

- [ ] **Step 1: Armar el HTML autocontenido**

Un solo archivo con los tokens de la Task 1 inline, las dos fuentes embebidas como
`data:font/woff2;base64` (desde
`web/node_modules/@fontsource-variable/inter-tight/files/inter-tight-latin-wght-normal.woff2`
y el equivalente de `jetbrains-mono`), y tres pantallas maquetadas con datos de ejemplo:
el shell con el riel de estado y la nav, la tabla de una corrida con la barra de totales, y
el login. Sin JS de la app: es una maqueta estática.

- [ ] **Step 2: Publicarlo como Artifact y esperar aprobación**

**Gate:** no se arranca la Task 1 hasta que el usuario apruebe la dirección. Si la rechaza,
se ajusta el mockup —que no cuesta nada— en vez de rehacer 6 archivos.

- [ ] **Step 3: Sin commit**

El mockup vive en el scratchpad. No entra al repo.

---

### Task 1: Tokens y escala de radios

**Files:**
- Modify: `web/src/index.css:10-127`
- Create: `scripts/verificar_contraste.py`

**Interfaces:**
- Produces: los tokens que consumen todas las tasks siguientes — `--foreground`,
  `--muted-foreground`, `--border`, `--input`, `--primary`, `--ring`, `--rail`, y los
  semánticos `--revisar`, `--margen-pos`, `--margen-neg`, `--info` con su `-surface` y su
  `-foreground`. Y las utilidades Tailwind que se derivan de ellos vía `@theme inline`:
  `text-rail`, `bg-revisar-surface`, `text-margen-neg`, etc.

- [ ] **Step 1: Escribir el script de verificación de contraste**

`scripts/verificar_contraste.py`. Lee los `oklch(...)` de `web/src/index.css`, los convierte
a sRGB y verifica los pares contra WCAG 2.1. Sale con código 1 si alguno falla, así que
sirve de prueba ejecutable.

```python
"""Verifica que los tokens de color de web/src/index.css cumplan WCAG 2.1.

No es un test de vitest a propósito: jsdom no resuelve variables CSS ni calcula
contraste. Esto lee el CSS de verdad y hace la cuenta."""
from __future__ import annotations

import math
import re
import sys
from pathlib import Path

CSS = Path(__file__).resolve().parent.parent / "web" / "src" / "index.css"

# (texto, fondo, mínimo, descripción). 4.5 para texto, 3.0 para bordes de
# componente y elementos gráficos (WCAG 1.4.11).
PARES = [
    ("foreground", "background", 4.5, "texto principal"),
    ("foreground", "card", 4.5, "texto sobre tarjeta"),
    ("muted-foreground", "background", 4.5, "texto secundario"),
    ("muted-foreground", "card", 4.5, "texto secundario sobre tarjeta"),
    ("primary-foreground", "primary", 4.5, "texto sobre el primario oscuro"),
    ("input", "card", 3.0, "borde de campo"),
    ("input", "background", 3.0, "borde de campo sobre el fondo"),
    ("ring", "background", 3.0, "anillo de foco"),
    ("ring", "card", 3.0, "anillo de foco sobre tarjeta"),
    ("rail", "card", 3.0, "riel de la nav activa"),
    ("revisar", "revisar-surface", 4.5, "«por revisar»"),
    ("margen-pos", "margen-pos-surface", 4.5, "margen positivo"),
    ("margen-neg", "margen-neg-surface", 4.5, "margen negativo"),
    ("info", "info-surface", 4.5, "congelada / info"),
    ("destructive", "card", 4.5, "texto de error"),
]


def oklch_a_srgb(L: float, C: float, h: float) -> tuple[float, float, float]:
    a, b = C * math.cos(math.radians(h)), C * math.sin(math.radians(h))
    l_, m_, s_ = (L + 0.3963377774 * a + 0.2158037573 * b,
                  L - 0.1055613458 * a - 0.0638541728 * b,
                  L - 0.0894841775 * a - 1.2914855480 * b)
    l, m, s = l_ ** 3, m_ ** 3, s_ ** 3
    canales = (4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s,
               -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s,
               -0.0041960863 * l - 0.7034186147 * m + 1.7076147010 * s)

    def codificar(c: float) -> float:
        c = max(0.0, min(1.0, c))
        return 12.92 * c if c <= 0.0031308 else 1.055 * c ** (1 / 2.4) - 0.055

    return tuple(codificar(c) for c in canales)


def luminancia(rgb: tuple[float, float, float]) -> float:
    def lineal(c: float) -> float:
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (lineal(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contraste(x, y) -> float:
    a, b = luminancia(x), luminancia(y)
    return (max(a, b) + 0.05) / (min(a, b) + 0.05)


def leer_tokens(texto: str) -> dict[str, tuple[float, float, float]]:
    """Toma solo el bloque :root — el .dark se verifica aparte cuando exista tema oscuro."""
    raiz = re.search(r":root\s*\{(.*?)\n\}", texto, re.S)
    if raiz is None:
        raise SystemExit("No encontré el bloque :root en index.css")
    tokens: dict[str, tuple[float, float, float]] = {}
    for nombre, cuerpo in re.findall(r"--([\w-]+):\s*oklch\(([^)]+)\)", raiz.group(1)):
        partes = cuerpo.replace("/", " ").split()
        if len(partes) >= 3:
            tokens[nombre] = (float(partes[0]), float(partes[1]), float(partes[2]))
    return tokens


def main() -> int:
    tokens = leer_tokens(CSS.read_text(encoding="utf-8"))
    rgb = {k: oklch_a_srgb(*v) for k, v in tokens.items()}
    fallas = 0
    for texto, fondo, minimo, que in PARES:
        if texto not in rgb or fondo not in rgb:
            print(f"  FALTA  --{texto} o --{fondo} no está en :root ({que})")
            fallas += 1
            continue
        r = contraste(rgb[texto], rgb[fondo])
        ok = r >= minimo
        fallas += 0 if ok else 1
        print(f"  {r:5.2f}:1  min {minimo}  {'OK ' if ok else 'MAL'}  {que}")
    print(f"\n{len(PARES) - fallas}/{len(PARES)} pares cumplen WCAG 2.1")
    return 1 if fallas else 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Correrlo y verlo FALLAR**

Run: `python scripts/verificar_contraste.py`
Expected: FALLA. Con el CSS actual, `--input` y `--border` son el mismo valor
(`oklch(0.922 0 0)` = 1.28:1 sobre `--card`) y no existe ninguno de los semánticos ni
`--rail`. Deben salir varios `MAL` y varios `FALTA`, y código de salida 1.

- [ ] **Step 3: Reescribir el bloque `:root` de `web/src/index.css`**

Reemplazar `:root { ... }` (líneas 10-44) por:

```css
/* ── Sistema de diseño: «instrumento de medición» ─────────────────────────────
   DOS familias de color con trabajos distintos. No las mezcles:

     ESTRUCTURA (frío, croma bajo)  → superficies, texto, bordes, foco, nav.
     SIGNIFICADO (reservado)        → SOLO dinero y estado. Nunca decoración.

   Si agregás un color cálido o verde para que "quede lindo", rompés la única
   señal que no puede fallar: que el usuario vea de un golpe qué hay que revisar
   y qué margen es negativo. Los matices están separados a propósito —
   interacción 225, info 250, positivo 155, revisar 75, negativo 25.

   Todos los pares los verifica `python scripts/verificar_contraste.py`. */
:root {
  /* Radios explícitos, NO calc(): con --radius chico, calc(--radius - 4px) daba
     valores negativos y el navegador descartaba la regla. */
  --radius: 0.125rem;

  /* ── Estructura ── */
  --background: oklch(0.985 0.003 255);
  --foreground: oklch(0.235 0.020 258);
  --card: oklch(1 0 0);
  --card-foreground: oklch(0.235 0.020 258);
  --popover: oklch(1 0 0);
  --popover-foreground: oklch(0.235 0.020 258);
  --primary: oklch(0.255 0.021 258);
  --primary-foreground: oklch(0.975 0.003 255);
  --secondary: oklch(0.962 0.005 255);
  --secondary-foreground: oklch(0.255 0.021 258);
  --muted: oklch(0.962 0.005 255);
  --muted-foreground: oklch(0.500 0.016 258);
  /* --accent es la superficie de HOVER en el vocabulario de shadcn, no el color
     de marca. Si le pones el cian, cada hover:bg-accent se vuelve celeste. */
  --accent: oklch(0.945 0.008 255);
  --accent-foreground: oklch(0.255 0.021 258);
  --border: oklch(0.900 0.008 255);   /* hairline decorativo: divisores */
  --input: oklch(0.640 0.014 255);    /* borde de COMPONENTE: 3:1, WCAG 1.4.11 */
  --ring: oklch(0.520 0.105 225);     /* foco */
  --rail: oklch(0.560 0.115 225);     /* riel de la nav activa */

  /* ── Significado: dinero y estado ── */
  --destructive: oklch(0.505 0.185 25);
  --destructive-foreground: oklch(0.985 0 0);
  --destructive-surface: oklch(0.955 0.020 25);
  --revisar: oklch(0.470 0.115 75);
  --revisar-surface: oklch(0.960 0.028 75);
  --margen-pos: oklch(0.470 0.105 155);
  --margen-pos-surface: oklch(0.958 0.026 155);
  --margen-neg: oklch(0.505 0.185 25);
  --margen-neg-surface: oklch(0.955 0.020 25);
  --info: oklch(0.470 0.110 250);
  --info-surface: oklch(0.958 0.022 250);

  /* Series de datos: sin uso hoy (no hay gráficos). Se dejan porque los
     primitivos de shadcn las referencian. */
  --chart-1: oklch(0.520 0.105 225);
  --chart-2: oklch(0.470 0.105 155);
  --chart-3: oklch(0.470 0.110 250);
  --chart-4: oklch(0.470 0.115 75);
  --chart-5: oklch(0.505 0.185 25);

  --sidebar: oklch(0.975 0.004 255);
  --sidebar-foreground: oklch(0.235 0.020 258);
  --sidebar-primary: oklch(0.255 0.021 258);
  --sidebar-primary-foreground: oklch(0.975 0.003 255);
  --sidebar-accent: oklch(0.945 0.008 255);
  --sidebar-accent-foreground: oklch(0.255 0.021 258);
  --sidebar-border: oklch(0.900 0.008 255);
  --sidebar-ring: oklch(0.520 0.105 225);
}
```

En el bloque `.dark` (líneas 46-79) aplicar la **misma** paleta a otra luminancia: fondo
`oklch(0.165 0.014 258)`, superficies `oklch(0.215 0.016 258)`, texto
`oklch(0.965 0.003 255)`, y los semánticos con L≈0.72 y su `-surface` con L≈0.28. La app
sigue siendo light-only; se mantiene coherente para no dejar deuda a medias.

En `@theme inline` (líneas 81-118): radios explícitos y los tokens nuevos expuestos como
utilidades.

```css
  --radius-sm: 1px;
  --radius-md: 2px;
  --radius-lg: 3px;
  --radius-xl: 4px;
  --color-rail: var(--rail);
  --color-destructive-surface: var(--destructive-surface);
  --color-revisar: var(--revisar);
  --color-revisar-surface: var(--revisar-surface);
  --color-margen-pos: var(--margen-pos);
  --color-margen-pos-surface: var(--margen-pos-surface);
  --color-margen-neg: var(--margen-neg);
  --color-margen-neg-surface: var(--margen-neg-surface);
  --color-info: var(--info);
  --color-info-surface: var(--info-surface);
```

- [ ] **Step 4: Correr el script y verlo PASAR**

Run: `python scripts/verificar_contraste.py`
Expected: `15/15 pares cumplen WCAG 2.1`, código de salida 0.

- [ ] **Step 5: La suite y el build siguen verdes**

Run: `cd web && npm run test && npm run build && npm run lint`
Expected: 128 passed, build OK, oxlint 0. Cambiar tokens no puede romper un test de
comportamiento; si alguno se cae, es que asertaba sobre una clase de color y hay que
mirarlo, no silenciarlo.

- [ ] **Step 6: Commit**

```bash
git add web/src/index.css scripts/verificar_contraste.py
git commit -m "feat(web): tokens propios en vez del tema por defecto de shadcn

Separa estructura (frío, croma bajo) de significado (reservado para dinero y
estado), con los matices separados para que no compitan. Separa --border
(hairline decorativo) de --input (borde de componente, 3:1 por WCAG 1.4.11):
hoy son el mismo valor y el borde de los campos está en 1.49:1.

Los radios pasan a ser explícitos: calc(var(--radius) - 4px) daba negativos.

scripts/verificar_contraste.py lee el CSS de verdad y verifica los 15 pares.
No es un test de vitest a propósito: jsdom no calcula contraste."
```

---

### Task 2: Tipografía auto-hospedada

**Files:**
- Modify: `web/src/main.tsx` (+2 imports), `web/src/index.css` (`@theme`), `web/index.html` (1 línea)
- Ya instalado: `@fontsource-variable/inter-tight@5.3.0`, `@fontsource-variable/jetbrains-mono@5.3.0`

**Interfaces:**
- Consumes: los tokens de la Task 1.
- Produces: `--font-sans` y `--font-mono`, o sea las utilidades `font-sans` y `font-mono`
  que ya usan las tablas densas (`text-xs font-mono tabular-nums`).

- [ ] **Step 1: Importar las fuentes en `web/src/main.tsx`**

Arriba de todo, antes de `./index.css`:

```ts
// Auto-hospedadas a propósito: la CSP de producción es default-src 'self' sin
// font-src (apu_tool/servicio/seguridad_headers.py), así que el CDN de Google
// andaría en `vite dev` —que no manda CSP— y fallaría en Render. Vite las
// empaqueta en dist/assets y las sirve el mismo origen.
import "@fontsource-variable/inter-tight";
import "@fontsource-variable/jetbrains-mono";
```

- [ ] **Step 2: Declararlas en `@theme` de `web/src/index.css`**

```css
  --font-sans: "Inter Tight Variable", ui-sans-serif, system-ui, sans-serif;
  --font-mono: "JetBrains Mono Variable", ui-monospace, Consolas, monospace;
```

Y en `@layer base`, para que toda cifra en mono quede alineada en columna:

```css
  body { @apply bg-background text-foreground font-sans; }
  /* Cifras tabulares en TODO lo monoespaciado: sin esto las columnas de dinero
     cambian de ancho al cambiar de dígito y la tabla baila. */
  .font-mono, code, kbd, samp, pre { font-variant-numeric: tabular-nums; }
```

- [ ] **Step 3: `lang="es"` en `web/index.html`**

`<html lang="en">` → `<html lang="es">`. La app está enteramente en español; con `lang="en"`
un lector de pantalla la pronuncia con fonética inglesa.

- [ ] **Step 4: Build y verificar la fuente bajo la CSP REAL**

Este es el paso que atrapa la clase de falla del 2026-08-03 y hoy no existe en el repo.

```bash
cd web && npm run build && cd ..
ls web/dist/assets/ | grep -i woff2          # deben aparecer los .woff2 empaquetados
python -m uvicorn apu_tool.servicio.app:app --port 8099 &
```

Con el server arriba, y sustituyendo `<archivo>` por el woff2 que listó el paso anterior:

```bash
curl -sI http://127.0.0.1:8099/assets/<archivo>.woff2 | grep -iE "^HTTP|content-type"
curl -sI http://127.0.0.1:8099/ | grep -i "content-security-policy"
```

Expected: `HTTP/1.1 200 OK` y `content-type: font/woff2`. La CSP tiene que seguir diciendo
`default-src 'self'` **sin** `font-src` ni dominios de Google: si la fuente carga igual, es
porque se sirve del mismo origen, que es exactamente el objetivo. Bajar el server al terminar.

- [ ] **Step 5: Suite, build y lint**

Run: `cd web && npm run test && npm run build && npm run lint`
Expected: 128 passed, build OK, oxlint 0.

- [ ] **Step 6: Commit**

```bash
git add web/src/main.tsx web/src/index.css web/index.html web/package.json web/package-lock.json
git commit -m "feat(web): Inter Tight + JetBrains Mono auto-hospedadas

Auto-hospedadas y NO por el CDN de Google: la CSP es default-src 'self' sin
font-src, así que el CDN andaría en vite dev (sin CSP) y fallaría en Render.
Vite las empaqueta en dist/assets, que ya sirve app.py con el tipo correcto
(mimetypes resuelve .woff2 -> font/woff2). 84 KB las dos, subconjunto latin.

tabular-nums en todo lo monoespaciado para que las columnas de dinero no
cambien de ancho al cambiar de dígito. Y lang=es: la app está toda en español."
```

---

### Task 3: El shell (`Layout.tsx`)

**Files:**
- Modify: `web/src/components/Layout.tsx` (reescribir; muere el objeto `styles` de 116 líneas)
- Modify: `web/src/components/Layout.test.tsx`

**Interfaces:**
- Consumes: tokens de la Task 1, fuentes de la Task 2, `getStatus()` de `@/api/corridas`,
  `useAuth()`, `puede()` de `@/components/rutas`.
- Produces: el shell. Nada lo importa salvo el router.

**Contrato que NO cambia:** `StatusResponse` sigue siendo `{insumos, apus, ia}` y
`status.insumos` **ya trae los visibles** (`rutas.py:104` manda
`c.get("insumos_visibles", ...)`). No se toca la API.

- [ ] **Step 1: Escribir los tests y verlos fallar**

Agregar a `Layout.test.tsx`, y de paso **subir el `import` al tope del archivo**: hoy está
adentro del test (`await import("./Layout")`), que es el patrón de flake ya documentado —
transformar el módulo se le cobra al presupuesto de 5 s de cada test.

```tsx
test("el riel muestra las tres lecturas por separado, no una frase", async () => {
  rol = "editor";
  render(<MemoryRouter><Layout /></MemoryRouter>);
  // Etiqueta y valor separados: antes era una sola cadena
  // "0 insumos · 0 APUs · IA: fallback", imposible de leer de un golpe.
  expect(await screen.findByText("Insumos")).not.toBeNull();
  expect(screen.getByText("APUs")).not.toBeNull();
  expect(screen.getByText("IA")).not.toBeNull();
});

test("la nav activa se marca con aria-current", async () => {
  rol = "editor";
  render(
    <MemoryRouter initialEntries={["/insumos"]}>
      <Layout />
    </MemoryRouter>
  );
  const activa = await screen.findByRole("link", { current: "page" });
  expect(activa.textContent).toContain("Insumos");
});
```

Run: `cd web && npm run test -- Layout`
Expected: los dos nuevos FALLAN. El primero porque hoy el estado es una sola cadena
interpolada; el segundo porque `NavLink` sin `aria-current` explícito no expone
`current: "page"` a la query por rol.

- [ ] **Step 2: Reescribir `Layout.tsx`**

Estructura, sin objeto `styles`:

- **Riel de estado** (topbar `h-9 bg-primary text-primary-foreground`): la marca a la
  izquierda, y a su lado tres lecturas discretas. Cada una es
  `<Lectura etiqueta="Insumos" valor={...} />` con la etiqueta en micro-etiqueta
  (`text-[10px] uppercase tracking-[0.08em] text-primary-foreground/60`) y el valor en
  `font-mono text-xs`. La de IA no dice «fallback» como si fuera un error: punto de estado
  (`bg-primary-foreground/40` en fallback, `bg-margen-pos` con IA) más la palabra.
  Mientras carga, las tres muestran `—`, no la cadena `"cargando…"`.
- **Menú de usuario**: igual que hoy pero con `Button variant="ghost" size="xs"` para
  «Cerrar sesión», que **elimina los dos handlers `onMouseEnter`/`onMouseLeave`** que
  emulan un `:hover` a mano (`Layout.tsx:55-60`).
- **Barra lateral** (`w-40 bg-sidebar border-r border-border`): ícono + texto por ítem, de
  `lucide-react`. `Layers` Corridas, `Package` Insumos, `FileSpreadsheet` APUs, `Users`
  Usuarios, `ScrollText` Auditoría. La activa: `bg-muted font-medium text-foreground` con
  `border-l-2 border-rail` y `aria-current="page"`; la inactiva `text-muted-foreground
  border-l-2 border-transparent hover:bg-accent`.
- **Grupo de admin separado** con su propia micro-etiqueta de sección `Administración`,
  solo cuando `puede(perfil?.rol, "admin")`.
- `min-h-dvh` en vez de `height: 100vh`, y `text-[13px]` para conservar la densidad.

Preservar exactamente: la lista de links y su `end`, el filtro por rol, el
`getStatus().catch()` silencioso, `logout()`, y el `<Outlet />`.

- [ ] **Step 3: Correr los tests y verlos pasar**

Run: `cd web && npm run test -- Layout`
Expected: los 3 tests del archivo en verde (el de rol admin que ya existía, más los 2 nuevos).

- [ ] **Step 4: Suite completa, build y lint**

Run: `cd web && npm run test && npm run build && npm run lint`
Expected: 130 passed, build OK, oxlint 0.

- [ ] **Step 5: Commit**

```bash
git add web/src/components/Layout.tsx web/src/components/Layout.test.tsx
git commit -m "feat(web): el shell como riel de estado, con tokens

El estado era una sola cadena interpolada ('8157 insumos · 1204 APUs · IA:
fallback'): pasa a tres lecturas discretas con etiqueta y valor en mono. Y
'IA: fallback' deja de leerse como error — es un modo de operación válido,
así que va como punto de estado neutro.

La nav gana ícono + texto (guía nav-label-icon: la nav de solo íconos daña la
descubribilidad), aria-current que no existía, y el grupo de admin separado
con su etiqueta de sección.

Mueren el objeto styles de 116 líneas y los dos onMouseEnter/onMouseLeave que
emulaban un :hover a mano. Y el import del test sube al tope: adentro del test
era el patrón de flake ya documentado."
```

---

### Task 4: Las dos pantallas de autenticación

`Login.tsx` y `DefinirClave.tsx` juntas: son la misma forma (pantalla centrada con panel) y
un revisor las acepta o rechaza a la vez. Acá caen los tres defectos de accesibilidad.

**Files:**
- Modify: `web/src/pages/Login.tsx` (15 `style={}`), `web/src/pages/DefinirClave.tsx` (11)

**Interfaces:**
- Consumes: tokens (Task 1), `Button` e `Input` de `components/ui/`.

- [ ] **Step 1: Test de foco visible, y verlo fallar**

Crear `web/src/pages/Login.a11y.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { expect, test, vi } from "vitest";
import Login from "./Login";

vi.mock("@/lib/auth", () => ({ useAuth: () => ({ login: vi.fn() }) }));
vi.mock("@/lib/supabase", () => ({ supabase: { auth: {} } }));
vi.mock("sonner", () => ({ toast: { error: vi.fn(), success: vi.fn() } }));

test("los campos no matan el foco con outline:none inline", () => {
  // Login.tsx:150 y DefinirClave.tsx:122 hacían `outline: "none"` sin
  // reemplazo, y grep -c focus daba 0 en los dos archivos: quien entra con
  // teclado no ve dónde está parado. jsdom no dibuja el anillo, pero sí puede
  // afirmar que no queda un outline:none inline apagándolo.
  render(<MemoryRouter><Login /></MemoryRouter>);
  for (const id of ["login-email", "login-password"]) {
    const campo = document.getElementById(id) as HTMLInputElement;
    expect(campo).not.toBeNull();
    expect(campo.style.outline).toBe("");
  }
});
```

Run: `cd web && npm run test -- Login.a11y`
Expected: FALLA — `campo.style.outline` es `"none"`.

- [ ] **Step 2: Migrar las dos pantallas**

Borrar los dos objetos `styles` y expresar todo con Tailwind + tokens, según la tabla de
traducción. Los `<input>` crudos pasan a `Input` de `components/ui/`, que ya trae
`focus-visible:ring-ring`; los `<button>` a `Button` (`variant="default"` el primario,
`variant="link"` el de «¿Olvidaste tu contraseña?»).

Los tres arreglos de accesibilidad salen de la tabla, sin código extra:
`#a0aec0` (2.26:1) → `text-muted-foreground` (5.74:1); `#4a90d9` (3.34:1) → `text-ring`
(5.08:1); `#cbd5e0` (1.49:1) → `border-input` (3.36:1).

**No cambia nada más:** `onSubmit`, `login()`, `nav("/corridas", {replace:true})`, `olvide()`
con su `resetPasswordForEmail` y su `redirectTo`, los `toast`, `required`, `autoFocus`,
`autoComplete`, y **los textos tal cual**. Igual en `DefinirClave`.

- [ ] **Step 3: Correr los tests y verlos pasar**

Run: `cd web && npm run test -- Login`
Expected: el nuevo en verde y `Login.test.tsx` intacto.

- [ ] **Step 4: Suite, build, lint y contraste**

Run: `cd web && npm run test && npm run build && npm run lint && cd .. && python scripts/verificar_contraste.py`
Expected: 131 passed, build OK, oxlint 0, 15/15.

- [ ] **Step 5: Commit**

```bash
git add web/src/pages/Login.tsx web/src/pages/DefinirClave.tsx web/src/pages/Login.a11y.test.tsx
git commit -m "feat(web): autenticación con tokens; arregla 3 fallas de WCAG

Las dos pantallas de entrada tenían outline:none sin reemplazo y 0 reglas de
focus: quien entra con teclado no veía dónde estaba parado. Usan los
primitivos de ui/, que ya traen focus-visible:ring-ring.

Contrastes medidos, antes -> después:
  subtítulo        2.26:1 -> 5.74:1  (mínimo 4.5)
  enlace olvidé    3.34:1 -> 5.08:1  (mínimo 4.5)
  borde de campo   1.49:1 -> 3.36:1  (mínimo 3, WCAG 1.4.11)

Cero cambios de comportamiento: mismos handlers, mismos textos."
```

---

### Task 5: `CorridasInicio.tsx`

**Files:**
- Modify: `web/src/pages/CorridasInicio.tsx` (26 `style={}`, 410 líneas)

- [ ] **Step 1: Verificar que los tests existentes pasan ANTES de tocar**

Run: `cd web && npm run test -- CorridasInicio`
Expected: verde. Son la red anti-regresión de esta task — 6 tests que cubren el toast de
«Elige una carpeta», la precarga del nombre, el aviso de la lista y el `FormData` con
`lista_id`. No se agregan tests nuevos: la migración no agrega comportamiento.

- [ ] **Step 2: Migrar**

Borrar el objeto `styles`, expresar con Tailwind + tokens según la tabla. `input`/`select`/
`button` a los primitivos de `ui/`.

Preservar **literalmente**, porque son arreglos recientes que costaron una rama cada uno:
- `disabled={cargando}` en «Armar» — **sin** `carpetaDestino == null`. El toast
  `"Elige una carpeta"` tiene que seguir siendo alcanzable (era código muerto, `6fd5472`).
- La etiqueta `Carpeta *` con su asterisco.
- El aviso de la lista **como un solo nodo de texto**, sin `<strong>`: el test hace
  `getByText(/no se puede cambiar/i)` sobre el `<p>` entero y partirlo lo rompe.
- El `styles.btnPrimario` inline era justamente por qué el botón deshabilitado no se veía
  gris. Al pasar a `Button`, el `disabled:opacity-50` del primitivo lo resuelve.

- [ ] **Step 3: Los tests siguen verdes**

Run: `cd web && npm run test -- CorridasInicio`
Expected: los 6 en verde, sin tocarlos. Si alguno se cae, la migración cambió
comportamiento: revertir y mirar, no ajustar el test.

- [ ] **Step 4: Suite, build, lint**

Run: `cd web && npm run test && npm run build && npm run lint`
Expected: 131 passed, build OK, oxlint 0.

- [ ] **Step 5: Commit**

```bash
git add web/src/pages/CorridasInicio.tsx
git commit -m "feat(web): nueva corrida con tokens, sin los 26 estilos inline

Preserva los arreglos del smoke test: disabled={cargando} sin la carpeta (el
toast 'Elige una carpeta' tiene que seguir siendo alcanzable), 'Carpeta *', y
el aviso de la lista como un solo nodo de texto sin <strong> porque el test lo
busca entero.

De paso desaparece la razón por la que el botón deshabilitado no se veía gris:
usaba style inline, y el disabled:opacity-50 del primitivo lo resuelve."
```

---

### Task 6: `MisCorridas.tsx`

La más grande: 59 `style={}` en 655 líneas, y la única que usa los tokens semánticos.

**Files:**
- Modify: `web/src/pages/MisCorridas.tsx`

- [ ] **Step 1: Verificar que los tests existentes pasan ANTES de tocar**

Run: `cd web && npm run test -- MisCorridas`
Expected: verde. Red anti-regresión.

- [ ] **Step 2: Migrar, con los badges a tokens semánticos**

Los 7 hex de estado son la razón por la que los tokens semánticos existen:

| hex | va a |
|---|---|
| `#c6f6d5` / `#276749` | `bg-margen-pos-surface text-margen-pos` |
| `#bee3f8` / `#2a4365` | `bg-info-surface text-info` |
| `#fefcbf` / `#b7791f` / `#744210` | `bg-revisar-surface text-revisar` |
| `#fed7d7` / `#feb2b2` / `#c53030` | `bg-destructive-surface text-destructive` |

La tabla usa los primitivos de `components/ui/table.tsx`, ya usados por `Apus` e `Insumos`,
así que las tres tablas quedan iguales. Las columnas numéricas: `text-right font-mono
tabular-nums`.

Preservar: los 5 `window.prompt`/`confirm` **nativos** (mover corrida, mover carpeta,
eliminar corrida, eliminar carpeta, y el de renombrar), el breadcrumb con su navegación, el
guard de «mismo nombre → no llama a la API» de `handleRenombrar` y
`handleRenombrarCorrida`, los `e.stopPropagation()` de los handlers de fila (la fila es
clickeable), y los `toast.success` con el nombre nuevo.

- [ ] **Step 3: Los tests siguen verdes**

Run: `cd web && npm run test -- MisCorridas`
Expected: verde, sin tocarlos.

- [ ] **Step 4: Suite, build, lint, contraste**

Run: `cd web && npm run test && npm run build && npm run lint && cd .. && python scripts/verificar_contraste.py`
Expected: 131 passed, build OK, oxlint 0, 15/15.

- [ ] **Step 5: Verificar que no quedó ni un hex**

Run: `cd web/src && grep -rnE "#[0-9a-fA-F]{3,6}" --include=*.tsx pages/ components/Layout.tsx`
Expected: **sin resultados**. Los 29 hex en 0.

- [ ] **Step 6: Commit**

```bash
git add web/src/pages/MisCorridas.tsx
git commit -m "feat(web): mis corridas con tokens; los 59 estilos inline en 0

Los 7 hex de badges de estado pasan a los tokens semánticos, que existen
justamente por esta pantalla: bg-margen-pos-surface, bg-info-surface,
bg-revisar-surface, bg-destructive-surface. La tabla usa los primitivos de
ui/table, así que las tres tablas de la app quedan iguales.

Con esto no queda ni un hex a mano en pages/ ni en Layout (eran 29).
Los 5 diálogos nativos quedan nativos a propósito: el reemplazo se revirtió
el 2026-08-03 y sigue esperando el error de consola."
```

---

### Task 7: Verificación final y revisión

**Files:** ninguno (salvo lo que salga de la revisión).

- [ ] **Step 1: Los cuatro pasos de CI**

```bash
cd web && npm run test && npm run build && npm run lint && cd ..
python -m pytest tests/ -q
```
Expected: 131 passed frontend, build OK, oxlint 0, y **el backend intacto** — no se tocó
nada de Python salvo agregar un script, así que cualquier fallo ahí es una sorpresa que hay
que entender antes de seguir.

- [ ] **Step 2: Contraste sobre los valores finales**

Run: `python scripts/verificar_contraste.py`
Expected: 15/15.

- [ ] **Step 3: La fuente bajo la CSP real, otra vez**

Repetir el Step 4 de la Task 2 sobre el build final. Es el paso que atrapa «anda local,
falla desplegado».

- [ ] **Step 4: Revisión de código de toda la rama**

Usar `superpowers:requesting-code-review` sobre el diff completo contra `master`. La
revisión de la rama entera cazó, en la rama anterior, una regresión que ni las revisiones
por task ni los 145 tests vieron. Foco: que ninguna migración haya cambiado un handler, un
texto o una llamada a la API.

- [ ] **Step 5: Checklist en navegador — ANTES del push, y la hace el usuario**

Los tests no ven color, tipografía, radio ni foco. Yo no veo pixeles. Esto lo hace una
persona con `npm run dev`:

| pantalla | qué mirar |
|---|---|
| Login | Tab por los dos campos: **el anillo de foco se ve**. El subtítulo se lee. |
| Definir clave | Idem foco. |
| Nueva corrida | Sin carpeta, «Armar» avisa en rojo. El aviso menciona «Usar ejemplo». |
| Mis corridas | Badges de estado legibles. Breadcrumb. Mover/renombrar/eliminar andan. |
| Insumos, APUs, Corrida, Auditoría, Usuarios | Heredaron la paleta y **nada quedó ilegible**. |
| Toda | Las fuentes cargaron (no se ve Segoe UI). Consola sin errores. |

**Gate:** sin este checklist no se pushea. El 2026-08-03 se desplegó un cambio visual con
145 tests verdes y falló en el navegador.

- [ ] **Step 6: Cerrar la rama**

Usar `superpowers:finishing-a-development-branch`. El push a master **necesita aprobación
explícita**: master auto-despliega a producción.
