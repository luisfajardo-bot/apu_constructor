# Barra angosta: la navegación se pliega, las lecturas se quedan

Fecha: 2026-08-06
Rama: `feat/barra-navegacion-plegable`

## Problema

Al angostar la ventana, la barra superior **esconde las cuatro lecturas de estado**
(En línea / Insumos / APUs / IA) con `@max-[980px]:hidden`, y la navegación no se
oculta nunca (a <700px pasa a scroll horizontal). El comentario en
`web/src/components/Layout.tsx:150-152` documenta ese orden de sacrificio:

```
Orden de sacrificio al angostarse: primero el correo (decorativo),
después estas lecturas (informativas), al final el nombre de la marca.
La navegación no se oculta nunca.
```

Esa prioridad está al revés de lo que el usuario quiere. Se descubrió estrenando la
lectura "En línea": en una ventana chica desaparece justo el dato que se acaba de
agregar para mirarlo seguido.

## Decisión

**Se invierte la prioridad**: las lecturas de estado son lo que siempre se ve; la
navegación es lo que se pliega. Y "plegarse" es un desplegable de verdad, no
desaparecer: las secciones siguen alcanzables en un clic.

Alcance decidido con el usuario:

- **Solo la navegación se pliega.** Las lecturas no se ocultan ni se pliegan en ningún
  ancho. El correo, el rol y Cerrar sesión siguen con las reglas de hoy.
- **El botón muestra la sección actual**, no una hamburguesa: `[ícono] Insumos ▾`.
  Plegada, la barra sigue diciendo dónde estás — que es lo que hoy hace el subrayado.
- **El celular es un target.** No se arman APUs en un teléfono, pero se consulta, así
  que hay un escalón extra para anchos de teléfono en vez de romper la promesa de
  "lecturas siempre visibles".

## Escalera de anchos

La barra ya es un `@container` (`Layout.tsx:96`), así que todos los cortes son container
queries: ceden según el ancho real de la barra, no del viewport.

| Ancho | Qué pasa | Estado |
|---|---|---|
| >1180 | todo visible | ya existe |
| <1180 | se va el correo (decorativo) | ya existe |
| **<980** | **la navegación se pliega al desplegable** | nuevo (antes acá morían las lecturas) |
| <700 | se va el nombre "Armador de APUs" | ya existe |
| **<560** | **la barra se parte en dos filas**: marca + desplegable + rol + sesión arriba, las 4 lecturas abajo a lo ancho | nuevo |

Las cuentas que fijan los dos cortes nuevos:

- Las 4 lecturas ocupan ~340px, el botón de sección ~110px, el chip de rol ~45px,
  Cerrar sesión ~90px, la marca ~160px, más los `gap`. Con la navegación desplegada en
  línea eso pasa de 980px: de ahí el primer corte.
- Sin el nombre de la marca (que ya se va a <700px) el resto convive hasta ~560px. Abajo
  de eso no hay ancho que reparta, y ahí la barra crece de 54px a dos filas en vez de
  esconder algo. Es la única forma honesta de cumplir "siempre visibles" en 390px.

## El desplegable

`<details>` / `<summary>` **nativo**, sin JS de apertura:

- `<summary>` ya es enfocable, responde a Enter y Espacio, y expone el estado
  expandido/colapsado a lectores de pantalla sin `aria-*` a mano.
- El `<summary>` muestra el ícono de la sección actual + su nombre + un chevron. Si
  ninguna ruta calza (no debería pasar dentro del Layout autenticado), dice `Secciones`.
- Adentro, las 5 secciones en columna, conservando el separador del grupo Admin que ya
  se dibuja hoy y la marca de la sección activa.
- La sección actual se calcula desde `useLocation().pathname` con el mismo criterio que
  `NavLink`: el link con `end: false` (Corridas) matchea también sus rutas anidadas
  (`/corridas/123`), los demás exigen igualdad.

**Cierre:** un `useEffect` sobre `location.pathname` cierra el `<details>` al navegar.

**No se agrega listener de clic-afuera.** `<details>` no lo trae, y sin él el panel
queda abierto hasta que se vuelve a tocar el `<summary>`. Comentario `ponytail:` con el
techo y el upgrade: el repo ya tiene ese patrón hecho a mano en
`web/src/components/corrida/BuscadorApu.tsx` (listener de `mousedown` en `document`) si
al probarlo en el navegador molesta.

## Los links se renderizan UNA sola vez

No hay una versión ancha y otra angosta en el DOM. El mismo `<nav>` cambia de fila
inline a panel absoluto por container query:

- ancho: `flex-row`, inline en la barra, como hoy;
- angosto: `absolute` bajo la barra, `flex-col`, oculto salvo que el `<details>` esté
  abierto.

**Cómo se expresa, sin inventar variantes:** todo se hace con el modificador `@max-[…]`
que el repo ya usa (`Layout.tsx:98,113,153,180`), nunca con un `@min-[…]` sin precedente
acá:

- el `<summary>`: `hidden @max-[980px]:flex` — no existe en la barra ancha, aparece al
  angostarse;
- el `<nav>`: clases base para la fila inline, más `@max-[980px]:absolute
  @max-[980px]:top-full @max-[980px]:flex-col …`, y la visibilidad en angosto sale del
  estado abierto/cerrado (`@max-[980px]:flex` vs `@max-[980px]:hidden`) aplicado con el
  helper `cn` que el archivo ya importa;
- las dos filas de <560px: `flex-wrap` en el contenedor de la barra y
  `@max-[560px]:basis-full @max-[560px]:justify-between` en el grupo de lecturas, para
  que caiga entero a la segunda fila y se reparta a lo ancho.

Dos razones, y la segunda es la que manda:

1. Menos código y una sola fuente de verdad para el array `links`.
2. `web/src/components/Layout.test.tsx` tiene un test anti-regresión que afirma que
   dentro de `<nav>` hay **exactamente 5 links**
   (`within(nav).getAllByRole("link")` → `["Corridas", "Insumos", "APUs", "Usuarios",
   "Auditoría"]`). Dos copias del menú lo romperían con 10, y ese test es el guard de
   que la navegación siga siendo un landmark navegable con lector de pantalla.

El `<summary>` es un `<summary>`, no un link, así que no cuenta para ese test.

## Qué se puede testear y qué no

**jsdom no implementa container queries**, así que en los tests todas las reglas
`@max-[...]` quedan inertes y **cada test ve la versión ancha**. Eso acota lo que un
test puede afirmar de verdad:

Testeable (y se testea):

- el `<summary>` existe y dice el nombre de la sección actual (`/insumos` → "Insumos");
- en una ruta anidada (`/corridas/7`) dice "Corridas" (el caso `end: false`);
- el `<nav>` sigue teniendo exactamente 5 links para un admin, en orden — el test
  anti-regresión que ya existe, sin tocarlo;
- al cambiar de ruta el `<details>` queda cerrado;
- los 4 tests de Layout que ya existen siguen pasando sin cambios de aserción.

NO testeable acá, y por lo tanto **se verifica en el navegador antes de pedir el push**:

- que a <980px la navegación efectivamente se pliegue y las lecturas se queden;
- que a <560px la barra se parta en dos filas;
- que el panel abierto no tape contenido ni se corte.

Esto es explícito por la lección del branch de `DialogoTexto`: 145 tests verdes taparon
un modal que se cerraba solo en el navegador. En cambios de UI el navegador va antes del
push.

## Fuera de alcance (hueco conocido que esto abre)

Los nombres de quién está en línea viven en un `title` (`Layout.tsx:155`), y en un
teléfono no hay hover. Al declarar el celular como target, en el teléfono la mitad
"quién" de la feature de presencia queda inalcanzable. El upgrade natural es que tocar
la lectura abra un panel con la misma mecánica que este desplegable — pero es otra
feature y no entra acá.

## No se toca

- Ninguna lectura cambia de contenido, de orden ni de estilo.
- El backend no se toca: es un cambio de una sola capa, `Layout.tsx` (más su test).
- Las reglas de <1180px (correo) y <700px (marca) se conservan tal cual.
- El array `links` y su lógica de roles (`puede(perfil?.rol, "admin")`) no cambian: el
  desplegable muestra lo mismo que la barra ancha, ni más ni menos.
