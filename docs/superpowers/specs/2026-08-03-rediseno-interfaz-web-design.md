# Diseño — rediseño visual de la interfaz web ("instrumento de medición")

> Fecha: 2026-08-03
> Estado: aprobado en brainstorming
> Rama de trabajo: `feat/rediseno-interfaz-web`

## El problema

La web «se ve como un diseño genérico de Claude». No es una impresión vaga: son tres
causas mecánicas, todas verificadas en el código.

**1. Los tokens de `web/src/index.css` son el tema por defecto de shadcn, literal.**
`--primary: oklch(0.205 0 0)`, `--muted: oklch(0.97 0 0)`, `--border: oklch(0.922 0 0)`…
**croma 0 en todos.** Es lo que escribe `npx shadcn init` sin una sola decisión propia.

**2. Hay dos sistemas de estilo compitiendo.** Cinco archivos usan objetos
`styles: Record<string, React.CSSProperties>` con hex a mano; el resto usa Tailwind. Los
tokens semánticos solo los consumen los primitivos de `ui/`.

```
style={} inline por archivo:     hex distintos en esos 5 archivos: 29
  MisCorridas.tsx        59        #1a1a2e ×16  #e2e8f0 ×14  #4a5568 ×11
  CorridasInicio.tsx     26        #cbd5e0 ×9   #718096 ×6   #2d3748 ×5
  Layout.tsx             16        #f7f7f8 ×4   #c53030 ×4   #a0aec0 ×4
  Login.tsx              15        #bee3f8 ×3   #276749 ×3   #4a90d9 ×2 …
  DefinirClave.tsx       11
```

**3. El color de significado es ad-hoc.** «Por revisar», «congelada» y «margen negativo»
no tienen token: cada pantalla los reinventa con `bg-amber-100`, `bg-blue-100`,
`text-green-700`, `text-red-600` sueltos, o con hex (`#bee3f8`, `#c6f6d5`, `#feb2b2`,
`#b7791f`, `#276749`, `#744210` en `MisCorridas`).

Detalles menores del mismo cuadro: la tipografía es `system-ui` 13px sin escala;
`Apus.tsx:216` dibuja un chevron con `<path>` a mano teniendo `lucide-react` instalado;
`<html lang="en">` en una app en español.

### Dos defectos de accesibilidad que entran en el alcance

Ratios calculados con WCAG 2.1 sobre los valores actuales:

| par | ratio | mínimo | qué es |
|---|---|---|---|
| `#a0aec0` sobre `#ffffff` | **2.26:1** | 4.5:1 | «Usa tu correo de la empresa.» (`Login.tsx:133`) |
| `#4a90d9` sobre `#ffffff` | **3.34:1** | 4.5:1 | «¿Olvidaste tu contraseña?» (`Login.tsx:168`) |

Y **el foco es invisible en las dos pantallas de autenticación**: `Login.tsx:150` y
`DefinirClave.tsx:122` hacen `outline: "none"`, y `grep -c focus` da **0** en los cuatro
archivos con hex. Quien navegue con teclado no ve dónde está parado al ingresar. Es la
categoría CRÍTICA #1 de la tabla de prioridades de ui-ux-pro-max (`focus-states`).

Los dos se corrigen **sin código nuevo**: los primitivos de `ui/` ya traen
`focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50`
(`ui/button.tsx:8`); basta con que las páginas los usen y que `--ring` valga algo visible.

## Decisiones tomadas (brainstorming)

**Dirección visual: «instrumento de medición».** Grafito + un solo acento frío. Hairlines
en vez de sombras, radio casi 0, cifras tabulares en mono, micro-etiquetas en mayúscula.
Los cálidos y el verde quedan **reservados** para significado de dinero.

Se descartaron: «Obra» (gris industrial + naranja `#EA580C`) porque el naranja cae en el
matiz ~45 y competiría con el ámbar de «por revisar» (~75) — la única señal que no puede
fallar; y «consola oscura», porque la app es light-only, el bloque `.dark` está inerte y
habría que diseñar **y validar** dos temas.

**Alcance: el mínimo que queda coherente.** Tokens, tipografía, el shell, los primitivos
de `ui/`, y migrar a tokens los 4 archivos con hex a mano. Las otras cinco pantallas
heredan la paleta sola. Se descartó tocar solo los cimientos porque dejaría `Login`,
`DefinirClave`, `CorridasInicio` y `MisCorridas` con su `#1a1a2e` chocando contra la
paleta nueva: una app mitad nueva y mitad vieja, peor que hoy.

**Tipografía auto-hospedada, no CDN.** `seguridad_headers.py:22-30` declara
`default-src 'self'` sin `font-src`, y `style-src 'self' 'unsafe-inline'` sin
`fonts.googleapis.com`. Un `<link>` al CDN de Google **funcionaría en `vite dev` (que no
manda CSP) y fallaría en Render**: exactamente el patrón «anda local, explota
desplegado». No se relaja la CSP por tipografía. Se usan dos paquetes de fontsource que
Vite empaqueta en `dist/assets`, servidos por el `app.mount("/assets", StaticFiles(...))`
de `app.py:72`, del mismo origen. Verificado: `mimetypes.guess_type('x.woff2')` →
`font/woff2` en Python 3.14.2, así que `StaticFiles` manda el tipo correcto.

## Invariante #1 (recordatorio)

No toca la IA ni el dinero. Es capa de presentación: no hay payloads hacia el modelo, ni
campos monetarios, ni cambios en `privacy.py`, `pricing.py` o `report.py`. El backend se
**lee** (la CSP) y no se modifica.

## Diseño

### Capa 1 — tokens (`web/src/index.css`)

Dos familias de color con trabajos distintos. La regla va como comentario en el CSS para
que no se rompa después:

```
ESTRUCTURA (frío, croma bajo)  →  superficies, texto, bordes, foco, nav
SIGNIFICADO (reservado)        →  solo dinero y estado. Nunca decoración.
```

Estructura:

| token | oklch | hex | contraste |
|---|---|---|---|
| `--background` | `0.985 0.003 255` | `#F9FAFC` | — |
| `--card` | `1 0 0` | `#FFFFFF` | — |
| `--foreground` | `0.235 0.020 258` | `#181E28` | 15.97:1 |
| `--muted` | `0.962 0.005 255` | `#F0F3F6` | — |
| `--muted-foreground` | `0.500 0.016 258` | `#5E646D` | 5.74:1 |
| `--border` (hairline decorativo) | `0.900 0.008 255` | `#DADEE3` | — |
| `--input` (borde de componente) | `0.640 0.014 255` | `#878D95` | 3.36:1 |
| `--primary` | `0.255 0.021 258` | `#1D232D` | — |
| `--ring` (foco) | `0.520 0.105 225` | `#007596` | 5.08:1 |
| `--rail` (nav activa) | `0.560 0.115 225` | `#0081A7` | 4.45:1 |

**`--border` y `--input` se separan** (hoy son el mismo valor, `oklch(0.922 0 0)`). WCAG
1.4.11 exige 3:1 para el borde de un componente, pero un divisor de tabla es decoración:
un solo token para las dos cosas obliga a elegir entre campos invisibles o tablas
rayadas.

Significado, con el matiz separado a propósito — interacción 225, info 250, positivo 155,
revisar 75, negativo 25:

| token | hex | contraste sobre `--card` | significa |
|---|---|---|---|
| `--revisar` | `#7F4F00` | 6.94:1 | por revisar |
| `--margen-neg` | `#B72028` | 6.47:1 | margen negativo |
| `--margen-pos` | `#196C40` | 6.48:1 | margen positivo |
| `--info` | `#215D96` | 6.81:1 | congelada |

No son especulativos: `MisCorridas` ya pinta esos cuatro estados con siete hex a mano.
Cada uno lleva su par `--*-surface` (fondo tintado del badge) además del color de texto.

`--accent` / `--accent-foreground` **siguen siendo neutros**. En el vocabulario de shadcn
`--accent` es una *superficie de hover*, no el color de marca: si se le pone el cian, cada
`hover:bg-accent` de los primitivos se vuelve celeste. El acento de interacción entra por
`--ring` (que los primitivos ya consumen) y por el `--rail` nuevo.

El bloque `.dark` se actualiza en la misma pasada, con la misma paleta a otra luminancia.
La app sigue siendo light-only (no hay `ThemeProvider`); se mantiene coherente para que no
quede como deuda a medias.

### Capa 2 — escala de radios

`index.css:114-117` calcula la escala con `calc(var(--radius) - 4px)`. Con `--radius: 2px`
eso da **−2px**, CSS inválido: la regla se descarta y el elemento queda con el radio que
herede. La escala pasa a ser explícita:

```css
--radius-sm: 1px;  --radius-md: 2px;  --radius-lg: 3px;  --radius-xl: 4px;
```

Nada de sombras: la jerarquía la dan hairline y superficie.

### Capa 3 — tipografía

```
npm i @fontsource-variable/inter-tight @fontsource-variable/jetbrains-mono   # 5.3.0
```

Importadas desde `main.tsx`. En `@theme`:

```css
--font-sans: "Inter Tight Variable", ui-sans-serif, system-ui, sans-serif;
--font-mono: "JetBrains Mono Variable", ui-monospace, Consolas, monospace;
```

- Escala: `10 / 11 / 12 / 13 / 16 / 20` px.
- Micro-etiqueta reusable: 10px, mayúscula, `letter-spacing: .08em`, `--muted-foreground`.
  Es buena parte del carácter de «instrumento» y se usa en el riel de estado, las cabeceras
  de tabla y las etiquetas de campo.
- `font-variant-numeric: tabular-nums` por defecto donde se aplique `--font-mono`, para que
  las columnas de dinero no bailen.
- `<html lang="en">` → `<html lang="es">` en `web/index.html`.

### Capa 4 — el shell (`components/Layout.tsx`)

Hoy el estado es una sola cadena: `` `${status.insumos} insumos · ${status.apus} APUs · IA:
${status.ia ? "habilitada" : "fallback"}` `` (`Layout.tsx:20-22`). Pasa a **tres lecturas
discretas**, cada una con micro-etiqueta arriba y valor en mono: panel de instrumentos, no
frase. De paso `IA: fallback` deja de leerse como error — pasa a estado neutro con punto,
porque el fallback determinístico es un modo de operación válido, no una falla.

Barra lateral:
- Ícono + texto en cada ítem, de `lucide-react` (ya instalado). La guía `nav-label-icon` lo
  pide explícitamente: la nav de solo íconos daña la descubribilidad.
- La activa marcada con el riel `--rail` (hoy ya hay un `borderLeft: 3px solid #4a90d9`, se
  tokeniza) más `aria-current="page"`, que hoy no está.
- El grupo de admin (Usuarios, Auditoría) separado con su propia etiqueta de sección
  (`nav-hierarchy`, y `destructive-nav-separation` para lo que es de administración).

`height: 100vh` → `min-h-dvh` (`viewport-units`). Se conserva la densidad actual: topbar de
36px, cuerpo de 13px.

El objeto `styles` de 116 líneas desaparece, incluidos los dos `onMouseEnter`/`onMouseLeave`
que emulan un `:hover` a mano (`Layout.tsx:55-60`).

### Capa 5 — las 4 páginas con hex

Migración **mecánica**: muere el objeto `styles`, queda Tailwind + tokens, y **no cambia
ningún comportamiento**. Ni un handler, ni una llamada a la API, ni un texto de usuario.

| archivo | `style={}` | qué se preserva sin tocar |
|---|---|---|
| `Login.tsx` | 15 | `onSubmit`, `olvide()` con su `resetPasswordForEmail`, `autoFocus`, `autoComplete` |
| `DefinirClave.tsx` | 11 | el flujo de definir clave completo |
| `CorridasInicio.tsx` | 26 | `handleArmar` con su `toast.error("Elige una carpeta")`, `disabled={cargando}`, el aviso de «Usar ejemplo» usa Principal |
| `MisCorridas.tsx` | 59 | los 5 `window.prompt`/`confirm` **quedan nativos** (ver abajo), mover/renombrar/eliminar, breadcrumb |

Los `<input>`/`<button>`/`<select>` crudos pasan a los primitivos de `ui/` donde el
reemplazo es 1:1. Ahí es donde los dos defectos de accesibilidad caen solos.

### Qué NO cambia

- **Backend: nada.** La CSP se lee, no se modifica. Ni un endpoint, ni un esquema.
- **Los 11 diálogos nativos** (`window.prompt`/`confirm`) siguen nativos. El reemplazo por
  `DialogoTexto` se revirtió el 2026-08-03 (`389357a`) y sigue esperando el error de
  consola; mezclarlo acá sería repetir la falla.
- Las cinco pantallas que ya usan Tailwind (`Insumos`, `Apus`, `Corrida`, `Auditoría`,
  `Usuarios`), las dos tablas densas y los 6 diálogos: **no se tocan**. Heredan la paleta
  por token.
- Ninguna llamada a la API cambia de forma.

### Fuera de alcance, explícito

Los `bg-amber-100` / `bg-blue-100` / `text-green-700` / `text-red-600` sueltos de esas
cinco pantallas **no** se reemplazan por los tokens semánticos en esta rama. Los tokens se
definen acá (los usa `MisCorridas`) y la adopción en el resto es el paso 2. Hasta entonces
esas pantallas tienen la estructura nueva y los badges con color crudo.

## Pruebas y verificación

El 2026-08-03 se desplegó un cambio 100% visual con 145 tests verdes y **falló en el
navegador**: jsdom no ve pixeles. El plan lo tiene en cuenta.

**Paso 0 — mockup antes de tocar la app.** El shell nuevo se arma como HTML autocontenido
con las fuentes embebidas y se publica como Artifact. Se aprueba o se cambia **cuando
todavía no hay ni un archivo del proyecto modificado**. Es el paso más barato para
descartar la dirección si no gusta.

Después, por task:

- Los **128 tests** de vitest verdes. Se declara explícitamente qué **no** prueban: color,
  tipografía, radio, foco visible. Sirven de red anti-regresión de comportamiento, no de
  validación visual.
- `npm run build` — es `tsc -b && vite build`, no `tsc --noEmit`. Lección de la rama de
  nombres de corrida: `--noEmit` dejó pasar un error de build.
- `oxlint` en 0.
- **La fuente bajo la CSP real**: `npm run build`, levantar uvicorn, y `curl -I` al
  `.woff2` de `dist/assets` esperando `200` y `Content-Type: font/woff2`, más el header
  `Content-Security-Policy` en la respuesta. Este paso es el que atrapa la clase de falla
  de ayer, y no existe hoy en el repo.
- **Re-correr el cálculo de contraste** sobre los valores finales del CSS, no sobre los
  propuestos. Queda como script en `scripts/` para poder repetirlo.
- **Checklist en navegador antes del push**, pantalla por pantalla: login (foco con Tab en
  los dos campos), definir clave, nueva corrida, mis corridas, y las cinco heredadas para
  confirmar que ninguna quedó ilegible.

Sin tests nuevos de vitest salvo uno: que el riel de estado del `Layout` renderice las tres
lecturas y marque la nav activa con `aria-current`. Eso sí es comportamiento, y hoy
`aria-current` no existe.
