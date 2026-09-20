# Smoke test — Armar APU desde una fila

Rama `feat/armar-apu-desde-corrida`. **Sin pushear hasta que esto esté completo.**

Acá el smoke pesa más que en la feature anterior: no es un botón que se agrega, es un
flujo de UI nuevo de punta a punta (elección → alta precargada → asignación) y **cambia
un camino que ya usabas**. Lo automatizado (1447 pytest, 387 vitest, build limpio) no
puede ver que el alta abra bien, que los campos lleguen precargados, ni que el diálogo
no se cierre solo.

---

## 0. Levantar la app

**Desde tu propia terminal**, no desde un agente:

```bash
cd "C:/Users/luis.fajardo/Downloads/intento_plan"
python scripts/servidor_local.py
```

**Si el puerto 8000 está ocupado** (Docker Desktop lo toma), usá otro:

```bash
SUPABASE_URL=$(grep -E "^VITE_SUPABASE_URL=" web/.env.local | cut -d= -f2- | tr -d '\r') \
APU_ADMIN_EMAILS=luisfajardo@indugravas.com \
python -m uvicorn apu_tool.servicio.app:app --host 127.0.0.1 --port 8010
```

El frontend usa `/api` relativo, así que el puerto da igual. Antes de empezar:
`cd web && npm run build`, y **Ctrl+Shift+R** en el navegador — si no, seguís con el JS
viejo en memoria y parece que nada cambió.

---

## 1. El caso que antes no existía: fila SIN APU

Podés reusar `ejemplos/smoke-rebuscar.xlsx` (tres actividades que quedan sin APU) o
cualquier corrida tuya con filas en $0.

- [ ] Desplegar una fila **sin APU** (el chevron) → aparece el botón **Armar APU**.
      *Antes acá no había ningún botón: este es el punto de toda la feature.*
- [ ] Apretarlo → se abre la ventana de elección, con la descripción de la actividad
      arriba, y **sin** la opción "Duplicar el APU asignado" (no hay ninguno que duplicar).
- [ ] Elegir **Desde cero** → el alta abre con **nombre** = la descripción de la actividad
      y **unidad** = la de la actividad. Si la corrida vino de un presupuesto IDU, el
      **código** también viene puesto.
- [ ] Completar la composición y crear → el diálogo se cierra, la fila queda con ese APU,
      **costeada** (ya no en $0) y con badge **`confirmado`**.

---

## 2. La fila que YA tiene APU

- [ ] Desplegar una fila **con APU** → el botón dice **Armar APU** (ya no "Duplicar este
      APU y usarlo aquí").
- [ ] Apretarlo → ahora sí aparecen **las tres** opciones, con "Duplicar el APU asignado"
      arriba y mostrando el código y el nombre del que tiene.
- [ ] **Duplicar el APU asignado** → el alta abre con la composición **real** del APU (con
      sus sub-APUs si los tiene) y un código derivado (el `-2`).
- [ ] Crear → la fila queda con el APU nuevo. *Este es el camino que ya usabas: tiene que
      funcionar exactamente igual que antes.*

---

## 3. Partir de otro APU

- [ ] En cualquier fila, **Armar APU** → escribir en el buscador de "Partir de otro APU".
- [ ] Elegir uno → el alta abre con **ese** APU (su nombre, su unidad, su composición), no
      con el de la fila.

---

## 4. Lo que jsdom no ve

- [ ] **El diálogo no se cierra solo.** Abrí la elección, esperá unos segundos, movete.
- [ ] **Cancelar** en la elección cierra y no pasa nada más.
- [ ] Si el APU de origen no se puede leer (difícil de forzar; si no podés, saltalo):
      sale un aviso y **te quedás en la elección**, no se abre el alta a medias.
- [ ] Los textos se leen bien y **ninguno te habla de vos** ("quieres", no "querés").
- [ ] El alta abre por encima de la elección sin superponerse raro ni dejar dos ventanas.

---

## 5. Los candados

- [ ] **Congelar** la corrida → el botón **Armar APU** desaparece.
- [ ] **Activarla** → vuelve.
- [ ] Con rol **consulta** (si podés probar con otro usuario) → no está.

---

## 6. Que no se rompió lo de al lado

- [ ] **Componer** (la mesa con IA) sigue apareciendo en las filas sin APU, igual que antes.
- [ ] **Cambiar APU** sigue funcionando.
- [ ] **Volver a buscar APU** (la feature anterior) sigue funcionando: creá un APU desde
      acá y comprobá que el botón lo encuentra para otras filas parecidas.

---

## Resultados

_(completar mientras se corre)_

| Bloque | Resultado |
|---|---|
| 1. Fila SIN APU (el caso nuevo) | |
| 2. Fila con APU (el camino de siempre) | |
| 3. Partir de otro APU | |
| 4. Lo que jsdom no ve | |
| 5. Los candados | |
| 6. Que no se rompió lo de al lado | |

**Problemas encontrados:**

**Veredicto:** ☐ listo para mergear · ☐ hay que arreglar
