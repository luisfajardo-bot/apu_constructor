# Smoke test — Listas de precios / APUs de No Previstos (NP)

Verificación manual en el navegador, sobre la app **en producción**. Ejecutable por
alguien que no conoce el proyecto: todo lo necesario está acá.

---

## 1. Qué se está probando y por qué importa

La app arma **APUs** (Análisis de Precios Unitarios) de obra civil y entrega un cuadro que
compara precio contractual vs. precio de costo.

Durante una obra aparecen actividades **no previstas (NP)** que no estaban en el
presupuesto pero hay que cobrarlas. Se costean con **precios distintos**, acordados para
esa obra. La feature nueva son las **listas de precios** (tarifas): el precio de un insumo
ahora es *por lista*. Existe la lista `Principal` (el catálogo de la empresa, intocable) y
una lista por obra de NP (p. ej. `NP Calle 13`). Una corrida **elige su lista al crearse y
ya no la puede cambiar**.

**El invariante que hay que verificar (es lo más importante de todo el test):** si un
insumo **no tiene tarifa en la lista NP**, su costo debe quedar en **$0 con una alerta
visible**. NO debe caer al precio de la lista Principal ni a ningún precio histórico.
Usar el precio de Principal en un no previsto significaría cobrarle al cliente con la
tarifa equivocada sin que nadie se entere — un error de dinero silencioso. Que ese $0 con
alerta aparezca es un ÉXITO del test, no una falla.

**Estado:** la lógica está cubierta por 665 tests automáticos, pero ninguno ejercita
navegador → API → base de datos real: los del backend corren contra SQLite y los del
frontend con `fetch` mockeado. Eso es lo que falta y lo que hace este runbook.

Documento hermano: `docs/listas-precios-np.md` explica la feature y el despliegue; este
solo verifica que funciona.

---

## 2. Antes de empezar

**Necesitás:**
- La app en **https://armador-apus.onrender.com** (producción, hospedada en Render).
- Un usuario con rol **editor** o **admin**. Con rol `consulta` no se pueden crear listas
  ni importar precios, y el test se corta en el paso 2. **Las credenciales las provee el
  dueño del proyecto; no están en este documento ni en el repositorio.**
- Ojo: es la app **de producción**, con el catálogo real de la empresa. Respetá las reglas
  de abajo al pie de la letra.
- Nada más: los dos archivos Excel que hacen falta se descargan **desde la app misma**
  (hay botones de "Descargar plantilla"). No fabriques Excels a mano.

**Reglas que NO se pueden romper:**
1. **No corras `seed` ni `seed --force`** ni ningún comando de re-semillado. Borra las
   listas de precios cargadas a mano y no hay de dónde recuperarlas.
2. **No edites precios con la lista `Principal` seleccionada.** Principal es el catálogo
   real de la empresa (~8000 insumos). Todo lo que escribas en este test va en la lista
   NP de prueba.
3. **Las listas de precios NO se pueden borrar** (está así a propósito: una corrida
   guarda su lista y borrarla dejaría corridas sin tarifa). Lo que crees queda para
   siempre en el selector. Por eso:
   - **Opción preferida:** hacé el test con la lista de una obra NP real, si ya existe.
   - **Si no:** nombrala `ZZ SMOKE TEST` y avisá al dueño del proyecto; después se puede
     **renombrar** (eso sí está permitido) cuando llegue la obra real.
4. Las **corridas** sí se pueden borrar: la que crees para el test, borrala al final.

---

## 3. Paso a paso

Anotá para cada paso: **OK** / **FALLA** + qué viste. Sacá captura de los pasos 4, 6 y 7.

### Paso 1 — Entrar y mirar la barra superior
1. Iniciá sesión.
2. En la barra de arriba hay un texto tipo `N insumos · M APUs · IA: ...`.

**Esperado:** carga sin errores y los números son > 0.
**Anotá el número de insumos**, se usa en el paso 8.

---

### Paso 2 — Crear la lista de precios
1. Andá a la pestaña **Insumos**.
2. Arriba hay un selector de lista (placeholder **"Lista de precios"**); debe estar en
   **Principal**.
3. Al lado hay un botón para crear lista (tooltip: *"Crear una lista de precios nueva
   (p. ej. tarifa de una obra No Prevista)"*). Hacé clic y poné el nombre acordado en el
   punto 2.3 de arriba.

**Esperado:**
- La lista se crea y **queda seleccionada automáticamente**.
- Aparece una **franja ámbar** que dice literalmente:
  *"Editando la lista **NOMBRE**. Los precios que cambies aquí NO afectan la lista
  Principal."*
- Aparece también el botón de renombrar (tooltip: *"Renombrar la lista de precios
  seleccionada"*).

**Si falla:** si no aparece la franja ámbar, **detené el test y reportá**. Sin ese aviso
alguien puede editar el catálogo real creyendo que edita la tarifa de la obra.

---

### Paso 3 — Comprobar que la lista arranca sin tarifas
1. Con la lista NP seleccionada, buscá el filtro/botón **"Sin precio"** (tooltip:
   *"Insumos sin tarifa en la lista seleccionada"*) y activalo.

**Esperado:** la tabla muestra insumos (todos, o casi todos: la lista nueva no tiene
tarifas todavía). En la columna de precio esos insumos se ven en **`—`**, no en `$0`.

**Elegí acá un insumo cualquiera y anotá su código y su nombre exacto.** Lo vas a usar en
el paso 5. Anotá también qué precio tiene ese mismo insumo en **Principal**: cambiá el
selector a Principal, buscalo por código, anotá el precio, y **volvé a la lista NP**.

---

### Paso 4 — Importar 2-3 precios en la lista NP
1. Con la **lista NP seleccionada** (verificá la franja ámbar), abrí el diálogo
   **"Importar insumos (crear + actualizar precios)"**.
2. Hacé clic en **"Descargar plantilla"**. Se baja un `.xlsx` con las columnas correctas.
3. Llená la plantilla con **2 o 3 filas**, y que **una de ellas sea el insumo que anotaste
   en el paso 3**, con un precio **claramente distinto** al que tiene en Principal (por
   ejemplo, si en Principal vale 350.000, poné 555.555 — un número inventado y fácil de
   reconocer a simple vista).
4. Subí el archivo. El diálogo muestra una previsualización con secciones
   ("Actualizar precio", "Ambiguas", "No encontradas"). Revisá que tus filas caigan en
   **"Actualizar precio"** y confirmá.

**Esperado:**
- Reporta las filas actualizadas y **sin errores**.
- En la tabla, con la **lista NP** seleccionada, ese insumo ahora muestra **555.555**.

**Verificación crítica (hacela sí o sí):** cambiá el selector a **Principal** y buscá el
mismo insumo. **Debe seguir con su precio original** (el que anotaste en el paso 3), NO
555.555.
**Si en Principal aparece 555.555 → FALLA GRAVE, detené todo y reportá:** significa que
cargar la tarifa de una obra pisó el catálogo real de la empresa.

Volvé a dejar el selector en la **lista NP**.

📸 Captura: la tabla en NP con 555.555 y la tabla en Principal con el precio original.

---

### Paso 5 — Armar una corrida contra la lista NP
1. Andá a **Mis corridas** (o la pantalla de armado) y descargá la **plantilla de
   licitación** (hay un botón para eso).
2. Llenala con **2 o 3 ítems** de actividades cualesquiera (descripción, unidad, cantidad,
   precio contractual, turno DIURNO). Que las descripciones se parezcan a actividades que
   ya existan en la biblioteca de APUs, para que el sistema las reconozca.
3. Creá una corrida nueva: elegí/creá una carpeta, subí el Excel y — **esto es el punto
   del test** — en el campo **"Lista de precios"** elegí tu **lista NP** (por defecto
   viene en Principal). Armá.

**Esperado:**
- La corrida se arma sin error.
- Al abrirla, se ve un indicador con el **nombre de tu lista NP** (si dijera Principal, o
  no mostrara nada, es una falla).

**Si el campo "Lista de precios" no aparece al crear la corrida → FALLA, reportá.** Es
inmutable: no se puede corregir después.

---

### Paso 6 — LA verificación que importa: $0 con alerta, no el precio de Principal
Abrí la corrida y mirá el detalle de los ítems (los insumos que componen cada APU).

**Esperado (los tres a la vez):**
1. Los insumos que **no tienen tarifa** en tu lista NP salen en **$0**.
2. Cada uno de esos trae la alerta **"Sin tarifa en la lista"** (texto literal).
3. **Ninguno** de esos insumos muestra el precio que tiene en Principal.

**Si un insumo sin tarifa en la lista NP aparece con un precio > 0 → FALLA GRAVE, reportá
de inmediato con captura.** Es exactamente el error que esta feature vino a evitar:
cobrar el no previsto con la tarifa contractual sin que nadie se entere.

Si además alguno de tus ítems usa el insumo del paso 4, ese sí debe costear con
**555.555** (tu tarifa NP), no con el precio de Principal.

📸 Captura del detalle con los $0 y la alerta "Sin tarifa en la lista".

---

### Paso 7 — Descargar el cuadro y revisar la hoja INFO
1. Desde la corrida, generá/descargá el **cuadro resumen** (Excel).
2. Abrilo y andá a la hoja **`INFO`**.

**Esperado:** hay una fila **`Lista de precios`** con el **nombre de tu lista NP**.
**Si dice `Principal` o la fila no existe → FALLA, reportá.** Sin eso, un cuadro de no
previstos no deja rastro de con qué tarifa se emitió.

📸 Captura de la hoja INFO.

---

### Paso 8 — La barra superior cuenta lo visible
Volvé a la pestaña **Insumos**, dejá el selector en **Principal** y **sin ningún filtro**
aplicado (ni "Sin precio", ni grupo, ni fuente, ni búsqueda).

**Esperado:** el total de insumos que muestra la tabla coincide con el número de insumos
del chip de la barra superior (el que anotaste en el paso 1).

*Contexto: hay varios cientos de insumos ocultos — códigos que eran eco de un APU sin uso
real (en la base local del dueño: 990 ocultos de 8157, o sea 7167 visibles; en producción
el número puede diferir, no lo compares contra estos). Antes el chip mostraba el total con
ocultos y la tabla mostraba menos; desde el 2026-07-31 los dos deben decir **lo mismo**. Lo
que se verifica es que coincidan entre sí, no que den un número puntual. Si difieren,
reportá los dos.*

---

### Paso 9 — Limpieza
1. **Borrá la corrida** de prueba (se puede borrar desde el listado).
2. **La lista de precios NO se puede borrar.** Si la creaste como `ZZ SMOKE TEST`,
   dejala y avisá en el reporte que quedó pendiente de renombrar o de reutilizar.
3. **No** deshagas los precios de la lista NP: viven solo en esa lista y no afectan a
   nadie más.

---

## 4. Cómo reportar

Devolvé esta tabla llena, con las capturas de los pasos 4, 6 y 7:

| Paso | Qué verifica | OK / FALLA | Qué viste |
|------|--------------|-----------|-----------|
| 1 | Barra superior carga; nº insumos anotado | | |
| 2 | Crear lista + franja ámbar | | |
| 3 | Lista nueva arranca sin tarifas (`—`) | | |
| 4 | Import escribe en NP y **no** toca Principal | | |
| 5 | Corrida creada con la lista NP, y se ve | | |
| 6 | **$0 + "Sin tarifa en la lista"**, sin precio de Principal | | |
| 7 | Hoja `INFO` con la fila `Lista de precios` | | |
| 8 | Chip = total de la tabla de Insumos | | |

**Severidad:**
- Pasos **4 y 6** son de dinero: si fallan, es **crítico** y hay que frenar el uso de la
  feature para no previstos hasta arreglarlo.
- Pasos **2, 5 y 7** son de trazabilidad: importantes, no bloqueantes para un solo caso
  vigilado a mano.
- Paso **8** es cosmético.

Incluí en el reporte: nombre de la lista que creaste (queda permanente), código del
insumo que usaste y su precio en Principal vs. en NP, y si borraste la corrida.
