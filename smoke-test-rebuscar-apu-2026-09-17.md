# Smoke test — Volver a buscar APU

Rama `feat/rebuscar-apu-corrida`. **Sin pushear hasta que esto esté completo.**

Lo automatizado ya pasó (1437 pytest, 379 vitest, build limpio). Lo que sigue es lo que
jsdom **no** puede ver: que el diálogo no se cierre solo, que el shift+clic funcione con
un mouse de verdad, que los textos se lean, y que el flujo completo contra el backend
real haga lo que promete. Es la lección de la rama del `DialogoTexto`: 145 tests verdes y
un modal que se cerraba solo en el navegador.

---

## 0. Levantar la app

**Desde tu propia terminal**, no desde un agente (un servidor interactivo tiene que vivir
en una sesión que no se mate sola):

```bash
cd "C:/Users/luis.fajardo/Downloads/intento_plan"
python scripts/servidor_local.py
```

Ese script ya resuelve `SUPABASE_URL` (la lee de `web/.env.local`) y `APU_ADMIN_EMAILS`.
Sin esas dos, el login rebota con 401 en todo `/api`.

El frontend ya está compilado (`web/dist` al día). Si volvés a tocar algo del front:
`cd web && npm run build` y después **Ctrl+Shift+R** en el navegador — si no, seguís
ejecutando el JS viejo en memoria y parece que el cambio no se aplicó.

Nada de lo que hagas acá llega a producción: los datos salen de `data/*.db` en esta
máquina. La identidad sí es la real (el mismo Supabase), así que entrás con tu cuenta.

---

## 1. Preparar la corrida

Subí `ejemplos/smoke-rebuscar.xlsx` como corrida nueva (entidad: la genérica, no IDU).

Son tres actividades inventadas a propósito: **pantalla acústica**, **barrera vegetal en
guadua** y **banca en concreto polimérico**. Verifiqué contra la biblioteca real (1182
APUs) que las tres quedan sin match — el mejor parecido es 20 %, 19 % y 29 %, bien debajo
del 55 % que hace falta para asignar.

- [ ] Las **tres** filas quedan en `(sin base — armar manual)`, en $0, con badge de sin APU.

Si alguna sale con APU, pará: la biblioteca local cambió y el smoke no prueba lo que cree.

---

## 2. El caso principal: APU creado desde la pestaña APUs

- [ ] Pestaña **APUs** → crear un APU nuevo, nombre **`PANTALLA ACUSTICA MODULAR EN
      ALUMINIO PERFORADO H=3.00M`** (igual que la fila 1), turno DIURNO, con uno o dos
      insumos que tengan precio.
- [ ] Volver a la corrida. **Sin recargar la página**, apretar **Volver a buscar APU**.
- [ ] Se abre el diálogo y muestra **1 de 3 líneas revisadas cambiarían de APU**.
- [ ] La fila viene **marcada sola**, con el APU propuesto, el parecido (~100 %) y el
      **costo y margen** que quedarían. El margen tiene que dar
      `precio contractual − costo`, no cualquier número.
- [ ] **Aplicar** → el diálogo se cierra, sale el toast "1 línea reasignada", y la fila
      de la tabla queda con el APU, costeada, con badge **`auto`** (NO `confirmado`).
- [ ] Las otras dos filas siguen intactas, sin APU.

---

## 3. El otro camino: duplicar un APU desde la corrida

Este es el que originalmente disparó la feature.

- [ ] En la fila 2 (barrera vegetal), usar **Cambiar APU** para asignarle cualquier APU,
      y después **duplicarlo** desde esa misma fila con un nombre parecido al de la
      actividad. (El duplicar ya asigna el APU nuevo a *esa* fila.)
- [ ] Apretar **Volver a buscar APU** otra vez.
- [ ] La fila 3 (banca) **no** debería cambiar: nada se parece. El diálogo tiene que
      decir **"Ninguna actividad encontró un APU mejor que el que ya tiene."**

---

## 4. Lo que jsdom no ve — mirá esto con atención

- [ ] **El diálogo NO se cierra solo.** Abrilo, esperá unos segundos, movete por la
      tabla. Tiene que quedarse abierto hasta que aprietes Cerrar o Aplicar.
- [ ] **Shift+clic marca en rango.** Con al menos 3 propuestas: clic en la primera, luego
      shift+clic en la tercera → se marcan las tres. Y **no** te tiene que quedar la
      tabla con texto resaltado en azul (ese bug ya apareció una vez en el diálogo de
      conflictos del import).
- [ ] **Marcar todas** marca y desmarca todo.
- [ ] **Mientras aplica**, el botón Cerrar queda deshabilitado y el de Aplicar dice
      "Aplicando…".
- [ ] **El tooltip del botón** se lee de corrido, sin saltos de línea raros en el medio.
- [ ] Con **cientos de filas** (si tenés una corrida real a mano), el diálogo scrollea y
      no se come la pantalla: la tabla tiene tope de 60 % del alto.

---

## 5. Los candados

- [ ] **Congelar** la corrida → el botón **Volver a buscar APU** desaparece.
- [ ] **Activarla** de nuevo → vuelve a aparecer.
- [ ] Con rol **consulta** (si podés probar con otro usuario) → el botón no está.
- [ ] Una fila que ya **confirmaste** a mano **no** aparece nunca en la previa, aunque
      exista un APU que le calce mejor.
- [ ] Una fila con **costo igualado al contractual** tampoco aparece.

---

## 6. La composición a medias

- [ ] En una fila sin APU, pedir una **composición** con IA (necesita
      `ANTHROPIC_API_KEY` en la terminal del servidor) y dejarla **sin aprobar**.
- [ ] **Volver a buscar APU** → esa fila aparece en la previa **desmarcada**, con el chip
      **"composición a medias"**, y el subtítulo lo menciona.
- [ ] Marcarla a mano y aplicar **sí** funciona: el candado es contra el gesto masivo
      distraído, no contra la decisión explícita.

Si no tenés API key a mano, este bloque se puede saltar — está cubierto por tests
automáticos —, pero decilo acá abajo.

---

## Resultados — 2026-09-18

Corrido por Luis Fajardo contra el servidor local (`127.0.0.1:8010`; el 8000 estaba
tomado por Docker Desktop). Assets verificados contra `web/dist` antes de empezar, así
que no se probó código viejo.

| Bloque | Resultado |
|---|---|
| 1. Preparar la corrida | OK |
| 2. APU desde la pestaña APUs | OK |
| 3. Duplicar desde la corrida | OK |
| 4. Lo que jsdom no ve | OK |
| 5. Los candados | OK |
| 6. Composición a medias | No corrido: sin `ANTHROPIC_API_KEY` en la terminal del servidor. Cubierto por tests automáticos (servicio + diálogo). |

**Problemas encontrados:** ninguno.

**Veredicto:** ☑ listo para mergear · ☐ hay que arreglar
