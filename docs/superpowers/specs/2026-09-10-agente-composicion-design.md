# Agente de composición asistida de APUs — fase 0 + fase 1: el expediente

> Evoluciona la composición generativa (`dominio/compose.py` + `dominio/ai_assist.py`)
> hacia un agente técnico acotado. **No toca el matcher, no toca el armado, no toca el
> motor de precios.** La IA sigue sin ver dinero y sigue proponiendo, nunca aplicando.

## 1. Cómo funciona hoy la composición

### El camino real, punta a punta

```
POST /corridas                        → encola; el worker arma determinísticamente, SIN IA
POST /corridas/{id}/revision/stream   → la IA audita fila por fila → veredicto por fila
     └─ SOLO si el veredicto es `sin_apu` aparece el botón "Componer"
POST /corridas/{id}/componer/{seq}    → UNA llamada a la IA → propuesta efímera
     └─ "Crear APU con esto" → DialogoAgregarApu prellenado → autoria.crear_apu
     └─ el APU creado se auto-asigna a la fila (TablaItems.tsx::apuCompuesto)
```

El **esqueleto que el usuario pidió ya existe**: el matching no lo toca la IA
(`assemble.py:88-101`), la IA no guarda nada, el alta pasa por `autoria.py`, el motor de
precios está aparte. Lo que falta no es la arquitectura del flujo, sino la **profundidad
técnica de los pasos de interpretación, evidencia, explicación y validación**.

### Los siete huecos, medidos

**1. La puerta de entrada está mal colocada.** `TablaItems.tsx:656`:

```ts
const ofreceComponer = puedeAplicar && v.dictamen === "sin_apu";
```

Sin correr la revisión con IA —que cuesta N llamadas sobre *toda* la corrida— no existe
el botón Componer, ni siquiera en una fila con `apu_codigo = NULL`.

**2. Nada se persiste.** La propuesta vive en el `useState` de `DialogoComposicion.tsx`.
Recargar la página la pierde. No hay tabla, no hay historial, no hay trazabilidad, no se
registra modelo ni versión de prompt. El doble clic lo frena un `useRef` en el navegador,
no el servidor.

**3. El contrato es de dos campos.** `_COMPOSE_SCHEMA` (`ai_assist.py:78-98`) pide
`{insumo_codigo, rendimiento}` por componente y `{confianza, justificacion}` globales.
No hay función del insumo, ni origen, ni referencias, ni hipótesis productiva, ni fórmula,
ni nivel de evidencia. **No hay nada que validar porque no hay nada que declarar.**

**4. La validación son dos condiciones.** `ai_assist.py:180-184`:

```python
if cod in codigos_validos and rend > 0:
```

Eso es todo. No se verifica unidad, ni duplicados, ni coherencia manual/mecánico, ni
recursos esenciales, ni rango contra antecedentes. Y `assemble.py:150` agrega un
`if not cands: continue` que **descarta componentes en silencio**: la IA propone ocho
insumos, el usuario ve cinco, y nadie le dice por qué faltan tres.

**5. La confianza es la que se pone el modelo a sí mismo.** `ai_assist.py:187` la toma
cruda del JSON y `DialogoComposicion.tsx:159` la pinta como `{Math.round(confianza*100)}%`.
Un número inventado por el modelo, mostrado con precisión de porcentaje.

**6. La recuperación es solo texto.** `compose.py:38-66`: candidatos del matcher (top 8)
→ sus insumos, más `search_insumos_por_palabras` con tokens de ≥4 letras, ordenado por
`similarity(descripcion, nombre)`, recortado a 40. **No mira unidad, ni grupo, ni turno,
ni método.** Una "EXCAVACIÓN MANUAL" traerá como ejemplo principal una "EXCAVACIÓN
MECÁNICA" si el nombre se parece más.

**7. La propuesta es de solo lectura.** El diálogo muestra una tabla; no se puede editar
un rendimiento, borrar un componente ni agregar uno. Las únicas salidas son "Crear APU
con esto" y "Descartar". Y no hay preguntas: el modelo *tiene* que producir algo, aunque
la descripción diga "SUMINISTRO E INSTALACIÓN DE TUBERÍA" sin diámetro ni material.

## 2. Qué se conserva sin cambios

- **La frontera de privacidad.** `privacy.safe_json` es un punto de paso duro,
  `_FORBIDDEN_KEYS` está mantenido, y su limitación real —mira nombres de clave, no
  valores— está documentada donde toca. Los payloads nuevos se cuelgan de ahí.
- **El matcher y el armado.** `matching.py` y `assemble.py` no cambian de comportamiento.
  El único cambio en `assemble.py` es **retirar** `generar_composicion`, cuya lógica se
  muda al orquestador nuevo con el contrato nuevo.
- **`pricing.py`.** Único módulo que ve dinero. El agente no lo importa, no lo llama y no
  lo conoce.
- **`autoria.py`.** El alta de APUs no se toca: sus reglas de unicidad, gemelo día/noche,
  sub-APUs y auditoría siguen siendo el único camino a la biblioteca.
- **El patrón de `revision.py`.** El agente es su **hermano**, no un framework: una
  fachada con una única puerta al SDK (sustituible en tests sin mockear `anthropic`), un
  orquestador que emite eventos, y degradado explícito cuando el JSON viene ilegible.
- **El patrón de migración dual-backend**: `db/*.sql` + `db/pg/*.sql` con
  `CREATE TABLE IF NOT EXISTS` / `ADD COLUMN IF NOT EXISTS`, aplicado al boot.

## 3. Qué se amplía

| Archivo | Estado | Responsabilidad |
|---|---|---|
| `dominio/composicion.py` | **nuevo** | tipos del contrato y parseo tolerante, sin dependencias de otras capas |
| `dominio/composicion_agente.py` | **nuevo** | orquestador `componer()`, transiciones de estado |
| `dominio/validacion_composicion.py` | **nuevo** | validador determinístico + confianza calculada |
| `dominio/compose.py` | ampliado | el retriever sigue igual (fase 3 lo cambia) + `rendimientos_observados()` |
| `dominio/ai_assist.py` | ampliado | `ApuAdvisor.componer()` con el esquema v2 + `PROMPT_VERSION` |
| `dominio/privacy.py` | ampliado | helpers de payload para el agente |
| `dominio/assemble.py` | reducido | se retira `generar_composicion` |
| `datos/composiciones_db.py`, `datos/pg/composiciones_pg.py` | **nuevos** | tabla nueva en `corridas.db` / schema `corridas`, repo aparte |
| `datos/repositorio.py`, `datos/almacen.py` | ampliados | Protocol + wiring |
| `servicio/composicion.py` | **nuevo** | lógica de servicio, hermano de `corridas.py` |
| `servicio/rutas.py`, `servicio/esquemas.py` | ampliados | 5 endpoints + DTOs |
| `web/src/pages/Composicion.tsx`, `web/src/api/composicion.ts` | **nuevos** | la mesa de revisión |
| `web/src/components/corrida/TablaItems.tsx` | ampliado | la puerta de entrada nueva (fase 0) |
| `web/src/components/corrida/DialogoComposicion.tsx` | **borrado** | lo reemplaza la página |

**Por qué un repo aparte y no seis métodos en `corridas_db.py`:** `corridas_db.py` ya
tiene 511 líneas, y el precedente del repo es exactamente este — `carpetas_db.py` son 98
líneas con su propio repo aunque las carpetas vivan en `corridas.db`. La separación es
por **dominio**, no por archivo de base.

## 4. La máquina de estados

De los diez estados sugeridos quedan **seis persistidos**, porque cuatro no son estados:

| Sugerido | Qué es en realidad |
|---|---|
| `pendiente` | la **ausencia** de fila; no se persiste una fila para decir que no hay nada |
| `analizando`, `recuperando_antecedentes` | **etapas dentro de una generación** → eventos SSE |
| `validada` | un **campo** de la validación (`valido: bool`), no un estado |

```
        ┌──────────── generar ────────────┐
        ▼                                 │
  [generando] ──falla──► [error] ─────────┘
        │
        └──ok──► [propuesta] ──editar+guardar──► [editada] ──┐
                     │  ▲                            │  ▲    │
                     │  └────── regenerar ───────────┘  └────┘
                     │
          ┌──────────┴──────────┐
     rechazar               aprobar
          ▼                      ▼
    [rechazada]             [aprobada]   (guarda apu_codigo + turno)
```

Cada transición escribe una **fila nueva** (append-only por versión). La vigente es la de
mayor `version`. La fase 2 inserta `requiere_informacion` entre `generando` y `propuesta`;
nada más cambia.

## 5. Qué usa IA y qué es determinístico

| Etapa | Quién |
|---|---|
| Recuperar insumos candidatos y APUs de referencia | **Python** (`compose.py`) |
| Calcular rendimientos observados de la biblioteca | **Python** |
| Proponer componentes, funciones, hipótesis y justificaciones | **IA — una llamada, `effort: medium`** |
| Recalcular toda la aritmética | **Python** (el número del modelo se ignora si no cuadra) |
| Validar | **Python** |
| Calcular la confianza | **Python** |
| Crear el APU | **Python + humano** (`autoria.crear_apu`) |
| Costear | **Python** (`pricing.py`, que el agente jamás toca) |

**Una sola llamada a la IA por generación**, igual que hoy. Las etapas múltiples de la
fase 2 son llamadas adicionales, no un rediseño.

## 6. Contratos JSON

### 6.1 Lo que la IA recibe

```json
{
  "actividad": {"item": "1.3", "descripcion": "EXCAVACION MANUAL EN MATERIAL COMUN",
                "unidad": "M3", "cantidad": 120.0, "shift": "DIURNO"},
  "insumos_disponibles": [
    {"insumo_codigo": "4279", "insumo_nombre": "CUADRILLA OFICIAL MAS AYUDANTES",
     "unidad": "HR", "grupo": "MO"}
  ],
  "apus_referencia": [ /* DePricedApu: codigo, nombre, unidad, shift, grupo, componentes[] */ ],
  "rendimientos_observados": [
    {"insumo_codigo": "4279", "unidad": "HR", "n": 14,
     "minimo": 0.40, "mediana": 0.62, "maximo": 1.10}
  ]
}
```

`actividad` sale de `privacy.licitacion_item_to_dict`, que omite `precio_contractual`
por construcción. `rendimientos_observados` es **nuevo y determinístico**: para cada
insumo candidato, en cuántos APUs de la biblioteca aparece y con qué rango. Le da al
modelo la base para declarar "copiado" o "ajustado", y al validador la base para decir
"atípico". Son cantidades físicas, no dinero. `grupo` (`MO`/`EQ`/`MAT`) entra por primera
vez: es clasificación técnica.

### 6.2 Lo que la IA devuelve

```json
{
  "componentes": [{
    "codigo": "4279",
    "tipo": "insumo",
    "funcion": "mano_de_obra",
    "rendimiento": 0.083333,
    "origen": "calculado_desde_produccion",
    "referencias": [{"apu_codigo": "3010", "turno": "DIURNO"}],
    "hipotesis": {"horas_jornada": 8, "produccion_por_jornada": 96,
                  "unidad_produccion": "m3/dia"},
    "calculo": {"operacion": "division", "numerador": 8, "denominador": 96,
                "resultado": 0.083333},
    "justificacion": "Cuadrilla usada en excavación manual de material común.",
    "nivel_evidencia": "medio",
    "advertencias": []
  }],
  "supuestos": [{"campo": "profundidad_m", "supuesto": "menor a 1,5 m",
                 "impacto": "por encima cambia el equipo y la entibación"}],
  "incertidumbre_declarada": 0.35,
  "justificacion": "Excavación manual sin entibar, cuadrilla y herramienta menor."
}
```

Vocabularios **cerrados** — enum en el esquema JSON *y* revalidados en Python, igual que
`revision.py` revalida `DICTAMENES` aunque el esquema ya lo restrinja:

| Campo | Valores |
|---|---|
| `tipo` | `insumo` · `apu` |
| `funcion` | `mano_de_obra` · `equipo` · `herramienta` · `material` · `transporte` · `subcontrato` · `sub_apu` |
| `origen` | `copiado_de_antecedente` · `ajustado_de_antecedente` · `calculado_desde_produccion` · `supuesto_tecnico` · `sin_evidencia` |
| `nivel_evidencia` | `alto` · `medio` · `bajo` |
| `calculo.operacion` | `division` · `multiplicacion` · `directo` |

**Por qué `funcion` es rol y no actividad.** El ejemplo original usaba texto libre
(`"excavacion_y_cargue"`). Cerrarlo a **rol dentro del APU** es lo que permite que el
validador escriba reglas ("no hay ni mano de obra ni equipo", "hay cuadrilla sin
herramienta"); un texto libre no se puede validar y se vuelve un campo decorativo. La
descripción de qué hace el insumo en *esta* actividad va en `justificacion`.

**Ninguna clave del contrato es monetaria.** No hay `precio`, `costo`, `valor`, `total`
ni `monto` en ningún nivel. Es deliberado: la propuesta persistida se puede reinyectar en
un payload futuro (regenerar con contexto, fase 4) sin volver a filtrarla. Hay un test que
lo fija.

### 6.3 Lo que devuelve la plataforma

```json
{
  "corrida_id": 12, "seq": 7, "version": 3, "estado": "editada",
  "componentes": [ /* con el rendimiento ya recalculado por Python */ ],
  "validacion": {
    "valido": false,
    "errores": [],
    "advertencias": [{"codigo": "RENDIMIENTO_ATIPICO", "componente": "4279",
                      "mensaje": "0,083 HR/M3 queda 42 % por debajo del rango observado (0,40–1,10, n=14)."}],
    "metricas": {"superadas": 11, "totales": 12}
  },
  "confianza": "media",
  "confianza_motivos": [
    {"senal": "respaldo_de_componentes", "valor": "4 de 5 con antecedente vivo", "aporte": "+2"},
    {"senal": "unidad_de_antecedentes", "valor": "2 de 3 comparten M3", "aporte": "+1"},
    {"senal": "rendimientos_atipicos", "valor": "1", "aporte": "-1"},
    {"senal": "supuestos_sin_confirmar", "valor": "1", "aporte": "-1"}
  ],
  "incertidumbre_declarada": 0.35,
  "modelo": "claude-sonnet-5", "prompt_version": "composicion/v2",
  "autor": "…", "creada_en": "2026-09-10T…"
}
```

`incertidumbre_declarada` se guarda **aparte** y **no entra** en el cálculo de `confianza`.
Se muestra rotulada como dato del modelo sobre sí mismo, junto al nivel calculado.

### 6.4 Eventos del SSE

Mismo patrón que `revisar_corrida_stream` y su `_event_stream`:

```
('recuperando', {'n_insumos': 40, 'n_apus': 3})
('generando',   {})
('validando',   {})
('lista',       {'version': 3, 'confianza': 'media', 'errores': 0, 'advertencias': 1})
('error',       {'detail': '…'})
```

## 7. Datos nuevos que se persisten

Una tabla, append-only por versión, en `corridas.db` / schema `corridas`.

```sql
CREATE TABLE IF NOT EXISTS composicion (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  corrida_id      INTEGER NOT NULL REFERENCES corrida(id) ON DELETE CASCADE,
  seq             INTEGER NOT NULL,
  version         INTEGER NOT NULL,
  estado          TEXT NOT NULL,   -- generando|propuesta|editada|aprobada|rechazada|error
  actividad_json  TEXT NOT NULL,   -- privacy.licitacion_item_to_dict: SIN precio_contractual
  ficha_json      TEXT,            -- fase 2; NULL en fase 1
  propuesta_json  TEXT,            -- componentes + supuestos + justificacion + incertidumbre
  validacion_json TEXT,            -- errores + advertencias + metricas
  confianza       TEXT,            -- alta|media|baja|insuficiente
  confianza_json  TEXT,            -- el desglose de por qué
  antecedentes_json TEXT,          -- lista blanca de códigos + APUs de referencia usados
  modelo          TEXT,
  prompt_version  TEXT,
  apu_codigo      TEXT,            -- el APU creado, solo si estado='aprobada'
  apu_turno       TEXT,
  autor           TEXT,
  creada_en       TEXT NOT NULL,
  motivo          TEXT             -- el error, o la razón del rechazo
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_composicion_version
  ON composicion(corrida_id, seq, version);
CREATE INDEX IF NOT EXISTS ix_composicion ON composicion(corrida_id, seq);
```

Cuatro decisiones dentro de esa tabla:

**`actividad_json` guarda la vista des-monetizada, no el `LicitacionItem`.** Guardar el
ítem crudo metería `precio_contractual` en la tabla, y entonces la fila entera dejaría de
poder viajar hacia la IA. Guardando la vista, **toda la fila es limpia** y el historial se
puede reinyectar como evidencia en la fase 4 sin ceremonia. Es la lección que dejó
`plan_json`, aplicada antes de tropezar.

**No se guarda razonamiento del modelo.** No hay columna para `thinking` ni para cadenas
de pensamiento: solo justificaciones cortas, datos estructurados, referencias y decisiones
observables. Hay un test que verifica que el bloque de pensamiento de la respuesta del SDK
no llega a la base.

**La composición no se borra ni se invalida cuando la fila cambia de APU.** Es el opuesto
de `revision_json`, y a propósito: un veredicto es caché barata sobre un APU concreto, una
composición es un expediente con trabajo humano adentro. Si alguien le asigna un APU a la
fila, la página lo dice ("esta línea ya tiene el APU X asignado") y ofrece descartar. No
hay hook en `actualizar_eleccion`, no hay estado que se pise solo, y el historial no miente.

**`UNIQUE(corrida_id, seq, version)` es la protección del doble clic**, no un `if`. Mismo
criterio que `ux_corrida_armando_archivo`: las dos peticiones de un doble clic llegan con
milisegundos de diferencia.

## 8. Cómo se garantiza que la IA nunca vea dinero

Cinco capas, de la más estructural a la más defensiva:

1. **El tipo.** Los APUs de referencia entran como `DePricedApu`, que por construcción no
   tiene campos monetarios. Los insumos candidatos entran como `CandidateInsumo`
   (código, nombre, unidad, grupo). La actividad entra por
   `privacy.licitacion_item_to_dict`, que omite `precio_contractual`.
2. **El guardián.** Todo payload sale por `privacy.safe_json`, que llama a
   `assert_no_money` antes de serializar. **Fuera del `try`**, igual que en
   `ai_assist.compose_apu` y `revision.Revisor._pedir`: una `PrivacyViolation` no se
   convierte en "la IA no pudo componer".
3. **El contrato limpio por construcción.** Ninguna clave del esquema de respuesta es
   monetaria, así que la propuesta persistida es reinyectable sin filtrar.
4. **Ninguna herramienta de precios.** El agente no importa `pricing.py`, no llama a
   `get_candidatos` para leer precios, y su lista blanca sale del retriever, que ya
   devuelve tipos sin dinero. El módulo `servicio/composicion.py` no importa `pricing`.
5. **Los tests.** Una batería que intenta filtrar dinero por cada payload nuevo, por la
   fila persistida completa y por la respuesta HTTP.

Recordatorio operativo que hereda de `privacy.py`: **nunca meter en un payload texto
generado por el motor de costos** (mensajes de `alertas.py`, explicaciones de `pricing.py`).
`assert_no_money` mira nombres de clave, no valores; un monto dentro de un string pasa.
El agente no toca ninguno de esos textos.

## 9. Validaciones y confianza

### 9.1 El validador

`validacion_composicion.validar(propuesta, contexto) -> Validacion`. Sin IA, sin dinero,
sin motor de precios. El contexto es determinístico: lista blanca de esta generación,
catálogo (unidad y grupo por insumo), biblioteca de APUs (sub-APUs y ciclos), y los
rendimientos observados.

**Bloqueantes — impiden aprobar:**

| Código | Regla |
|---|---|
| `PROPUESTA_VACIA` | cero componentes |
| `CODIGO_NO_AUTORIZADO` | el código no estaba en la lista blanca de esta generación |
| `CODIGO_INEXISTENTE` | no existe en el catálogo (ni en la biblioteca si `tipo='apu'`) |
| `CANTIDAD_INVALIDA` | ≤ 0, `NaN` o `inf` — el motor no puede costear eso |
| `TIPO_INCOHERENTE` | `funcion = sub_apu` con `tipo ≠ apu`, o al revés |
| `COMPONENTE_DUPLICADO` | mismo `(codigo, tipo, ref_shift)` dos veces |
| `SUBAPU_INEXISTENTE` | el sub-APU no existe en ese turno |
| `SUBAPU_CICLO` | el sub-APU se referencia a sí mismo o cierra un ciclo |
| `CALCULO_IMPOSIBLE` | denominador 0, o factores no finitos |

Dos umbrales nuevos en `config.py`, junto a los del matcher y los del cruce:
`COMPOSICION_LIMITE_RENDIMIENTO` y `COMPOSICION_MIN_ANTECEDENTES` (3: por debajo no hay
rango contra el cual llamar atípico a nada).

**Por qué el techo advierte y no bloquea** (corregido tras la revisión de la tarea 3):
un APU medido en GLB o en KM lleva la cantidad de la obra adentro — 15.000 M2 de
señalización en un PMT global — y supera cualquier techo de forma legítima. Bloquearlo
dejaba la propuesta **sin ningún estado en el que se pudiera aprobar**, ni corrigiéndola
a mano, porque el `PUT` revalida. Y el techo casi no atrapaba el error que lo motivó: la
coma corrida típica (0,5 → 500) pasa por debajo sin despeinarse — eso lo atrapa
`RENDIMIENTO_ATIPICO`, que compara contra la biblioteca. Lo que sigue bloqueando es lo
que el motor no puede costear: `NaN`, infinito y todo lo que no sea positivo.

**Advertencias — se ven, no bloquean:**

| Código | Regla |
|---|---|
| `CALCULO_CORREGIDO` | Python recalculó y dio distinto; manda Python |
| `CANTIDAD_SOSPECHOSA` | por encima de `COMPOSICION_LIMITE_RENDIMIENTO` |
| `RENDIMIENTO_ATIPICO` | fuera del rango observado del mismo insumo, con `n ≥ COMPOSICION_MIN_ANTECEDENTES` |
| `SIN_ANTECEDENTES` | `n < COMPOSICION_MIN_ANTECEDENTES`, o el rango está en otra unidad que el catálogo: no hay contra qué comparar |
| `SIN_EVIDENCIA` | `origen = sin_evidencia`, o `referencias` vacío con un origen que las exige |
| `REFERENCIA_INEXISTENTE` | un `apu_codigo` de `referencias` ya no existe; se limpia |
| `FALTA_MANO_DE_OBRA` | ninguna función es `mano_de_obra` ni `equipo` |
| `FALTA_HERRAMIENTA` | hay mano de obra y no hay herramienta ni equipo |
| `METODO_INCOHERENTE` | la descripción dice manual y hay equipo pesado, o dice mecánico y no hay equipo |
| `SUPUESTO_SIN_CONFIRMAR` | hay supuestos declarados y nadie los aceptó |

El reparto sigue la regla de no convertir criterio de ingeniería discutible en bloqueo
absoluto. Bloquea lo **estructural** (el código no existe, la cantidad no es un número, el
sub-APU cicla). Advierte lo **contextual** (el rendimiento es raro, falta herramienta, el
método no cuadra): ahí un ingeniero puede tener razón contra la regla.

**Un cálculo inconsistente se corrige, no se rechaza.** Si el modelo dice `8/96 = 0.09`,
Python escribe `0.083333` y emite `CALCULO_CORREGIDO` mostrando ambos números. Tirar una
propuesta buena por una división mal hecha que sabemos arreglar sería el peor de los dos
comportamientos. Lo que **nunca** pasa es lo contrario: el número del modelo no se usa
cuando hay un `calculo` que lo contradice.

**`METODO_INCOHERENTE` en fase 1 es tosco a propósito.** Sin la ficha técnica, la
detección es por palabra clave en la descripción (`MANUAL`/`A MANO` contra
`MECANIC`/`RETRO`/`EXCAVADORA`). Por eso es advertencia y no error, y va marcada con un
`ponytail:` que apunta a la fase 3, donde la hace la ficha.

**No hay regla de unidad del componente, y es correcto.** Un borrador de este diseño
listaba una advertencia `UNIDAD_DISTINTA_DEL_CATALOGO` que resultó imposible de violar:
`ComponentePropuesto` **no tiene campo `unidad`**, así que el modelo nunca la declara —
la unidad de un insumo la pone el catálogo y punto. Tampoco tiene sentido comparar la
unidad del componente con la de la actividad: que una cuadrilla en `HR` componga una
actividad en `M3` es exactamente lo normal, porque el rendimiento *es* HR por M3. Se
eliminó de la lista en vez de implementarse; el test que la cubría no probaba nada
(`assert v.valido is True`) y se reemplazó por uno que fija que el campo no existe.

### 9.2 La confianza

Cuatro niveles: **alta · media · baja · insuficiente**. Sin porcentajes: no hay masa de
datos para sostener una escala continua, y pintar `73 %` es la falsa precisión que hoy
tenemos.

| Señal | Aporte |
|---|---|
| Proporción de componentes con antecedente vivo (`copiado`/`ajustado`/`calculado` + referencia existente) | +2 / +1 / 0 |
| APUs de referencia que comparten unidad con la actividad | +1 |
| Cantidad de antecedentes comparables | +1 si ≥ 3 |
| Dispersión de los rendimientos observados de los insumos usados | +1 estrecha / −1 muy dispersa |
| Componentes con `RENDIMIENTO_ATIPICO` | −1 cada uno |
| Componentes con `SIN_EVIDENCIA` | −1 cada uno |
| Supuestos sin confirmar | −1 cada uno |
| Todas las validaciones superadas | +1 |

Dos candados:

- **Con cualquier error bloqueante, el nivel es `insuficiente`.** Sin excepción.
- **`incertidumbre_declarada` no entra en la fórmula.** El test que lo fija: dos
  propuestas idénticas con `incertidumbre_declarada` 0.0 y 1.0 dan el mismo nivel.

El desglose (`confianza_motivos`) se guarda y se muestra desplegable bajo el nivel.

## 10. Integración con el flujo determinístico

**Fase 0 — la puerta de entrada.** En `TablaItems.tsx`, "Componer con IA" aparece cuando
la fila **no tiene `apu_codigo`**, o cuando la revisión dictaminó `sin_apu` sobre una fila
que sí lo tiene. **No aparece con `costo_manual > 0`**: esa línea ya declaró su costo (los
proyectos especiales globales) y no necesita APU. Rol `editor`.

La fase 0 **no se hace en un commit aparte**: cambiar el disparador sobre un modal que
vamos a borrar es trabajo tirado. El disparador nuevo y su destino nuevo entran juntos.

**Endpoints:**

| Método | Ruta | Rol | Qué hace |
|---|---|---|---|
| `GET` | `/corridas/{cid}/composicion/{seq}` | consulta | versión vigente + historial; es lo que hace funcionar la recarga |
| `POST` | `/corridas/{cid}/composicion/{seq}/stream` | editor | genera (SSE) y escribe una versión nueva |
| `PUT` | `/corridas/{cid}/composicion/{seq}` | editor | guarda la edición humana: versión nueva, revalidada en el servidor |
| `POST` | `/corridas/{cid}/composicion/{seq}/aprobar` | editor | crea el APU y sella la versión `aprobada` |
| `POST` | `/corridas/{cid}/composicion/{seq}/rechazar` | editor | versión `rechazada` |

**`POST /corridas/{cid}/componer/{seq}` se borra**, junto con `DialogoComposicion.tsx`.
Dejarlo sería dejar vivo un camino que salta la validación, la confianza calculada y la
persistencia: el agujero exacto que esta feature existe para tapar. La funcionalidad no se
pierde, se muda entera a la página con más encima.

**La validación vive solo en el servidor.** No hay espejo en TypeScript: las reglas son
demasiadas para mantener dos copias sincronizadas. La consecuencia visible es que las
advertencias se recalculan al **guardar**, no mientras se teclea. Es el precio correcto.

**Idempotencia.** `PUT` y `aprobar` llevan `version_base`, la versión sobre la que trabajó
el usuario. Si ya existe una mayor → `409` nombrando la actual. Un doble clic en aprobar:
la segunda petición ve `estado='aprobada'` y devuelve `409` nombrando el `apu_codigo` ya
creado. Un APU, no dos.

**Aprobar es un endpoint, no una cadena en el navegador.** Recibe
`{codigo, turno, nombre, grupo, version_base}` y llama a `autoria.crear_apu` con los
componentes de la versión vigente. No se reusa `DialogoAgregarApu` completo porque
obligaría a editar los componentes **dos veces** —en la mesa y otra vez en el alta—; se
sustituye por un diálogo pequeño que pide solo la identidad (código y grupo, que son del
humano). Los conflictos de duplicado suben tal cual desde autoría.

**Costura conocida:** `crear_apu` escribe en `apus.db` y sellar la aprobación escribe en
`corridas.db` — dos archivos SQLite, sin transacción común. Si lo segundo falla, el APU
existe y la fila no lo tiene. Es el mismo caso que hoy (`TablaItems::apuCompuesto`) y se
resuelve igual: mensaje accionable, nunca silencio.

## 11. Experiencia del usuario

Página propia en `/corridas/{id}/componer/{seq}`, densa, table-first, sin cards.

```
◄ Volver a la corrida            EXCAVACION MANUAL EN MATERIAL COMUN
                                 M3 · 120,00 · DIURNO · ítem 1.3

┌─ Confianza: MEDIA  ▾ por qué ──────────────────────────────────────┐
│  El modelo declara 35 % de incertidumbre (dato suyo, no cuenta)    │
└────────────────────────────────────────────────────────────────────┘

⚠ 1 advertencia    ✓ 11 de 12 validaciones superadas

Código │ Insumo            │ Un. │ Rend. │ Función  │ Origen    │ Rango hist.  │ Ev.  │ ⨯
4279   │ CUADRILLA OF+AY   │ HR  │[0,083]│ mano_obra│ calculado │ 0,40–1,10 ⚠ │ medio│ ⨯
6092   │ HERRAMIENTA MENOR │ GLB │[1,000]│ herram.  │ copiado   │ 1,00–1,00    │ alto │ ⨯
                                                                    + agregar componente

Supuestos:  profundidad < 1,5 m — por encima cambia el equipo y la entibación
Referencias: APU 3010 DEMOLICION PAVIMENTO (DIURNO) · APU 3044 …

[Guardar cambios]  [Regenerar]  [Rechazar]        [Aprobar y crear APU]
```

- El rendimiento se edita en línea; la justificación de cada componente se despliega en su
  fila.
- Agregar componente reusa el buscador de insumos existente y admite sub-APU.
- **Aprobar queda deshabilitado mientras haya errores bloqueantes.** Con advertencias se
  puede aprobar: el humano decide.
- Aprobar → diálogo chico de identidad (código, grupo) → se crea, se asigna a la fila,
  vuelve a la corrida.
- Recargar la página levanta la versión vigente desde la base.
- Cancelar o irse **no toca corrida, biblioteca ni catálogo**.

## 12. Riesgos técnicos

**El contrato rico puede empeorar la propuesta.** Pedir diez campos por componente en
lugar de dos le carga la atención al modelo. No hay forma de saberlo con tests unitarios:
la calidad técnica de una propuesta es criterio, no aserción. **Exige un smoke test con
actividades reales antes del merge.** Si sale mal, la palanca es partir en dos llamadas
(una técnica, una de contabilidad), que es lo que la fase 2 hace igual.

**`RENDIMIENTO_ATIPICO` puede ser ruido.** Con n=1 o n=2 el "rango" no significa nada.
Mitigado con `COMPOSICION_MIN_ANTECEDENTES` (3, en `config.py`): por debajo se emite
`SIN_ANTECEDENTES` en vez de un falso atípico.

**La confianza calculada puede ser tan arbitraria como la del modelo.** La diferencia real
no es que sea más exacta: es que es **auditable y ajustable**, porque el desglose se ve y
los pesos están en un solo sitio. Hay que calibrarla con casos reales.

**Latencia y costo por composición suben.** Más tokens de salida, mismo número de llamadas.
Es a pedido y por fila, así que el techo es bajo, pero se mide en el smoke test.

**La mesa editable y `DialogoAgregarApu` pueden divergir.** Mitigado acotando la mesa:
edita rendimientos, agrega y quita componentes, y nada más. La identidad del APU sigue
siendo del alta.

**Migración nueva en el Postgres de producción.** Se valida contra el Postgres desechable
antes de desplegar, con la receta ya registrada.

## 13. Decisiones aprobadas

Seis, reversibles pero notables, aprobadas en el brainstorming del 2026-09-10:

1. Se borra `POST /componer/{seq}` y `DialogoComposicion.tsx`.
2. `funcion` es un vocabulario cerrado de rol, no texto libre.
3. Un cálculo inconsistente se corrige (Python manda) con advertencia, no se rechaza.
4. Seis estados persistidos; `analizando` y `recuperando_antecedentes` son eventos SSE.
5. Una composición no se invalida cuando la fila cambia de APU.
6. Con advertencias se puede aprobar; solo los errores estructurales bloquean.

Más las cuatro del alcance: fase 0 + fase 1 ahora; puerta de entrada = filas sin APU más
el veredicto `sin_apu`; persistencia append-only por versión; página propia con URL; SSE
con eventos de etapa; el contrato y el validador soportan sub-APUs pero la IA todavía no
los propone.

## 14. Plan incremental

Catorce tareas, cada una con su prueba primero, en orden de dependencia. De abajo hacia
arriba: el núcleo puro se prueba sin base ni red.

| # | Tarea | Depende de |
|---|---|---|
| 1 | Contrato y tipos (`dominio/composicion.py`): dataclasses, vocabularios, parseo tolerante | — |
| 2 | `rendimientos_observados()` en `compose.py` | — |
| 3 | Validador: todas las reglas | 1, 2 |
| 4 | Confianza calculada + desglose | 3 |
| 5 | Fachada IA: `ApuAdvisor.componer`, esquema v2, `PROMPT_VERSION`, degradado | 1 |
| 6 | Privacidad: helpers de payload + batería de fugas | 1, 5 |
| 7 | Persistencia SQLite: tabla, repo, Protocol, `Almacen` | 1 |
| 8 | Persistencia Postgres + paridad de contrato | 7 |
| 9 | Orquestador `componer()`: eventos y estados | 3, 4, 5, 6, 7 |
| 10 | Servicio y endpoints: roles, 409/422/503, idempotencia, aprobar vía autoría | 9, 8 |
| 11 | Cliente: `api/composicion.ts` + tipos | 10 |
| 12 | Página `Composicion.tsx` + disparador nuevo en `TablaItems` + borrar el modal viejo | 11 |
| 13 | Documentación: `CLAUDE.md`, README, arquitectura, mapa de módulos | 12 |
| 14 | Verificación: suite completa, `npm run build` (`tsc -b`, no `--noEmit`), migración contra el Postgres desechable, **smoke test en navegador con actividades reales** | 13 |

Rama `feat/agente-composicion` desde `master`. **Sin push hasta aprobación explícita**,
porque `master` autodespliega.

**Estado previo, medido el 2026-09-10 sobre `master` (`deec22e`):**
`python -m pytest tests/ -q` → **1036 pasadas, 15 saltadas, 0 fallos** en 110 s. No hay
pruebas rotas de antes; cualquier fallo que aparezca durante la implementación es nuestro.

## 15. Cobertura de los criterios de aceptación

Esta fase cubre **32 de los 36** criterios.

| Grupo | Criterios | Dónde |
|---|---|---|
| Flujo determinístico | 1, 2, 3, 4 | `test_assemble.py` (existente) + nuevos |
| Actividad pendiente | 5, 8 | `TablaItems.test.tsx`, `test_api_composicion.py` |
| Privacidad | 9, 10, 11, 12 | `test_composicion_privacidad.py` |
| Recuperación | 15, 16 | `test_composicion_contrato.py` |
| Generación | 17, 18, 19, 20, 21 | `test_composicion_contrato.py`, `test_composicion_motor.py` |
| Validación | 22, 23, 24, 25, 26, 27 | `test_validacion_composicion.py`, `test_confianza_composicion.py` |
| Aprobación | 28, 29, 30, 31, 32 | `test_api_composicion.py` |
| Persistencia | 33, 34, 35, 36 | `test_composiciones_db.py` + contrato dual |

**Fuera de esta fase, y hay que decirlo:**

| Criterio | Por qué | Fase |
|---|---|---|
| 6 — faltan datos críticos → devuelve preguntas | no hay interpretación todavía | 2 |
| 7 — continuar tras responder sin perder contexto | ídem | 2 |
| 13 — la búsqueda prioriza unidad y método compatibles | el retriever no cambia en esta fase | 3 |
| 14 — una actividad manual no toma un antecedente mecánico | en fase 1 solo hay una advertencia tosca, no una recuperación que lo evite | 3 |

## 16. Hoja de ruta posterior

| Fase | Qué entrega | Por qué después |
|---|---|---|
| **2. Interpretación y preguntas** | ficha técnica estructurada, clasificación crítica/importante/opcional, bucle responder→regenerar, estado `requiere_informacion` | necesita el expediente de la fase 1 para persistir respuestas y supuestos |
| **3. Recuperación híbrida** | retriever v2 guiado por la ficha (unidad, familia, método, turno); estadísticas de antecedentes comparables; sub-APUs en el conjunto candidato | necesita la ficha de la fase 2 para saber por qué filtrar |
| **4. Correcciones como evidencia** | las propuestas aprobadas y corregidas se reinyectan como antecedentes | necesita historial acumulado; sin datos no sirve |

Los puntos de extensión están previstos en esta fase: `ficha_json` ya existe en la tabla
(NULL en fase 1), las etapas nuevas son eventos SSE más, `requiere_informacion` es un
estado más en la máquina, y el contrato ya distingue `tipo: 'apu'`.
