# CLAUDE.md

Guía para trabajar en este repositorio. Léela antes de modificar código.

## Qué es

**Armador de APUs** (Análisis de Precios Unitarios) de obra civil. Toma una lista de
licitación, reutiliza el histórico de la empresa para armar los APUs, y entrega un
**cuadro resumen** que compara **precio contractual** vs **precio de costo**.

## Invariante #1 — la IA nunca ve dinero (NO LA ROMPAS)

La IA solo decide la **estructura** de los APUs (qué insumos, qué rendimiento).
**Nunca** debe recibir precios, costos ni totales.

- Todo payload que salga hacia la IA pasa por `apu_tool/privacy.py::assert_no_money`,
  que recorre la estructura y **lanza `PrivacyViolation`** si encuentra un campo
  monetario. Preferimos *fallar* a *filtrar*.
- Lo que la IA recibe son los tipos `DePriced*` de `apu_tool/nucleo/models.py`, sin campos de precio.
- Solo `apu_tool/dominio/pricing.py` y `apu_tool/dominio/report.py` tocan dinero, y jamás se pasan a la IA.

Si agregas una llamada a la IA, construye el payload con helpers de `apu_tool/dominio/privacy.py` y
serialízalo con `privacy.safe_json(...)`. Si agregas un campo monetario nuevo,
añádelo a `_FORBIDDEN_KEYS` en `apu_tool/dominio/privacy.py`.

## Comandos

```bash
pip install -r requirements.txt

python run_cli.py demo      # semilla + ejemplo + cuadro resumen (todo)
python run_cli.py seed      # semillar las bases desde el Excel histórico
python run_cli.py seed --force  # re-semillar (borra datos mantenidos Y listas NP, sin Excel del que recuperarlas)
python run_cli.py build <licitacion.xlsx>
python run_cli.py status
python run_cli.py db price <codigo>     # precio vigente + historial de un insumo
python run_cli.py db update-price <codigo> <precio> [--fuente ...]
python run_gui.py           # interfaz tkinter

python -m pytest tests/ -q  # pruebas
```

La IA se activa solo si existe `ANTHROPIC_API_KEY`. **El armado nunca la usa**: es
determinístico y corre igual. Sin la llave lo que no hay es revisión ni composición a
pedido (el botón queda deshabilitado; el endpoint responde 503) — y no hay fallback
determinístico para la revisión a propósito: sería el matcher auditándose a sí mismo.
Modelo por defecto: `claude-sonnet-5`
(`apu_tool/config.py::AI_MODEL`, se cambia con la env `APU_AI_MODEL`). Si lo
cambias, el modelo debe soportar pensamiento adaptativo, `effort` y salida
estructurada: es lo que pide `dominio/ai_assist.py`.

## Arquitectura (flujo)

```
Excel histórico ──seed──► SQLite/Postgres (precios, apus, corridas, perfiles, auditoría)
entidad IDU ──► previsualiza (NO persiste) ──► usuario aprueba ──┐
lista licitación ─────────────────────────────────────────────────┴► encola ──► worker
   arma (reanudable) ──► confirma usuario ──► motor de precios
                                                          └─► cuadro resumen (Excel)
corrida armada ──► revisión con IA (sin dinero) ──► propone veredicto ──► confirma usuario
fila sin APU ──► composición con IA (sin dinero) ──► validación determinística
                                    └─► confianza calculada ──► aprueba usuario ──► autoria.crear_apu

Interfaces sobre el mismo pipeline (dominio/pipeline.py):
  interfaz/{cli,gui}.py (local) · servicio/ (FastAPI, 72 endpoints) + web/ (React) para multiusuario
```

`apu_tool/config.py` es transversal, fuera de cualquier paquete: rutas, umbrales de
matching, modelo de IA, clasificación de precios.

### `apu_tool/nucleo/` — tipos y utilidades puras (sin dependencias de otras capas)

| Módulo | Responsabilidad |
|--------|-----------------|
| `models.py`   | tipos del dominio; vistas `DePriced*` SIN dinero |
| `redondeo.py` | redondeo a la unidad (peso) en multiplicaciones monetarias |
| `relevancia.py` | orden por relevancia de una búsqueda + scorer `similarity` |
| `texto.py`    | normalización de texto compartida |

### `apu_tool/datos/` — persistencia (**toda** la persistencia pasa por aquí)

| Módulo | Responsabilidad |
|--------|-----------------|
| `repositorio.py`  | contratos de almacenamiento (`Protocol`), por dominio |
| `precios_db.py`   | SQLite de `precios.db` (catálogo + precios) |
| `apus_db.py`      | SQLite de `apus.db` (biblioteca de APUs) |
| `carpetas_db.py`  | SQLite de carpetas de corridas |
| `corridas_db.py`  | SQLite de `corridas.db` (estado de corridas en curso) |
| `composiciones_db.py` | SQLite del expediente de composición (vive en `corridas.db`, repo aparte por dominio, como `carpetas_db.py`) |
| `auditoria_db.py` | SQLite de auditoría (`seguridad.db`) |
| `perfiles_db.py`  | SQLite de perfiles (identidad + rol) |
| `almacen.py`      | fachada que agrupa los repos SQLite/Postgres |
| `seed.py`         | ingesta Excel histórico → bases |
| `correcciones.py` | correcciones de código aplicadas al semillar |
| `migracion_pg.py` | migración SQLite → Postgres (Supabase); corridas NO se migran |
| `pg/`             | backend Postgres (espejo 1:1 de los `*_db.py`, para la nube) |

### `apu_tool/dominio/` — motor de negocio (`pricing.py` es el **único** que ve dinero)

| Módulo | Responsabilidad |
|--------|-----------------|
| `licitacion.py`          | lectura de la lista de entrada + generador de ejemplo |
| `presupuesto.py`         | lectura del Formulario 1 del IDU: capítulos, validación y conciliación |
| `entrada.py`             | registro entidad → lector de presupuesto (único punto de despacho) |
| `matching.py`            | matcher determinístico (fuzzy, sin dependencias externas) |
| `cruce.py`               | cruce insumo-de-APU ↔ insumo-de-catálogo por código+nombre |
| `compose.py`             | candidatos de insumos para el agente de composición + `rendimientos_observados()` (rango del insumo en la biblioteca) |
| `composicion.py`         | contrato del agente de composición: vocabularios cerrados, dataclasses, parseo tolerante del JSON del modelo |
| `validacion_composicion.py` | validador determinístico de una propuesta de composición + confianza calculada por la plataforma |
| `privacy.py`             | frontera de precios para la IA (invariante #1) |
| `ai_assist.py`           | IA acotada (Anthropic SDK): propone una composición a pedido (no compone; el usuario aprueba) |
| `composicion_agente.py`  | orquestador del agente de composición (hermano de `revision.py`): `recuperar()`, `evaluar()`, `componer()` (eventos SSE) |
| `revision.py`            | revisión con IA de una corrida ya armada (propone, no aplica) |
| `assemble.py`            | orquestador por ítem |
| `pricing.py`             | motor de costos (**ÚNICO** que ve dinero) |
| `alertas.py`             | alertas de costeo (por qué un ítem necesita revisión) |
| `transporte.py`          | distancias de acarreo por proyecto + ajustes de composición |
| `report.py`              | cuadro resumen en Excel |
| `report_categorizado.py` | cuadro resumen agrupado por capítulos de presupuesto |
| `integridad.py`          | chequeo de integridad del vínculo APU↔insumo |
| `pipeline.py`            | orquestación de alto nivel (la usan CLI, GUI y el servicio web) |

### `apu_tool/servicio/` — API web (FastAPI)

| Módulo | Responsabilidad |
|--------|-----------------|
| `app.py`               | arma la app FastAPI: monta `/api`, sirve `web/dist`, middlewares de seguridad |
| `rutas.py`             | el único `APIRouter`; todos los endpoints HTTP (delega a los módulos de abajo) |
| `dependencias.py`      | inyección de dependencias (el `Almacen` vive en `app.state`) |
| `esquemas.py`          | DTOs del contrato HTTP |
| `auth.py`              | autenticación (Supabase Auth) + autorización por rol |
| `limites.py`           | límite de tamaño de subida + rate limiting |
| `seguridad_headers.py` | middleware de headers de seguridad (HSTS, CSP, etc.) |
| `corridas.py`          | lógica de servicio de corridas (armado en vivo, revisión con IA) |
| `composicion.py`       | lógica de servicio del agente de composición (hermano de `corridas.py`): recuperar, generar (SSE), editar, aprobar, rechazar |
| `insumos.py`           | lógica de servicio para editar insumos |
| `insumos_ocultos.py`   | insumos ocultos: eco de un APU, sin uso real (no se borran) |
| `listas.py`            | listas de precios (tarifas): Principal + una por obra de NP |
| `autoria.py`           | alta de insumos/APUs nuevos |
| `subapus.py`           | migración: marca componentes que son sub-APU |
| `apus.py`              | lectura de la biblioteca de APUs |
| `carpetas.py`          | reglas de carpetas de corridas |
| `transporte.py`        | distancias del proyecto, impacto y clasificación de acarreos |
| `ajustes.py`           | ajustes puntuales de composición por proyecto |
| `usuarios.py`          | gestión de usuarios (solo Admin) |
| `auditoria.py`         | servicio de auditoría (registro + lectura paginada) |
| `supabase_admin.py`    | cliente de la Admin API de Supabase Auth |
| `plantillas.py`        | plantillas `.xlsx` para importadores |
| `presencia.py`         | quién está usando la app ahora (dict en memoria, sin DB) |

### `apu_tool/interfaz/` — puntos de entrada

| Módulo | Responsabilidad |
|--------|-----------------|
| `cli.py` | línea de comandos |
| `gui.py` | interfaz gráfica (Tkinter) |

## Convenciones

- **Persistencia aislada en `apu_tool/datos/`.** No metas SQL crudo en otros módulos. Esto
  permite migrar a Postgres/nube reemplazando una sola capa (plan: local primero,
  nube después).
- **Español** en nombres de dominio, comentarios y mensajes de usuario.
- **Sin dependencias pesadas:** el matcher usa stdlib (`difflib`); `openpyxl` para
  Excel; `anthropic` es opcional.
- **Determinismo del costo:** el costo de un APU se calcula llamando al precio
  vigente del insumo (`apu_tool/dominio/pricing.py`); el precio histórico embebido es solo respaldo.
- **Turno** DIURNO/NOCTURNO es parte de la clave de un APU y de su composición.

## Datos

- **Excel fuente:** `OBRA-Calle 13-LOTE SL5-...xlsx` (no se modifica; solo se lee).
  Pestañas clave: `APUS` (composición + turno), `listado_insumos_idu` (precios),
  `insumos_apus_especificos`, `listado_apus_idu_especiales`.
- **Bases locales:** `data/precios.db` (catálogo de precios e insumos) y
  `data/apus.db` (biblioteca de APUs y composiciones) — ambas SQLite, generadas con
  `seed`. El precio del insumo vive separado de su identidad: actualizarlo
  (`db update-price`) no toca los APUs, que toman el precio vigente al costear.
  El contrato de almacenamiento está en `datos/repositorio.py` (Protocol) para que un
  backend de nube sea un reemplazo limpio.
- **Listas de precios (tarifas).** El precio de un insumo es *por lista*: la lista
  `Principal` (id 1, `config.LISTA_PRINCIPAL_ID`, intocable — no se renombra ni se
  borra) es la del catálogo, y cada obra de No Previstos (NP) puede tener la suya
  (tabla `lista_precios`, columna `insumo_precios.lista_id NOT NULL DEFAULT 1`). Una
  corrida elige su lista **al crearse** (`corrida.lista_precios_id`, sin FK) y no la
  cambia — no existe ningún `set_lista`. Costeando contra una lista que no es
  Principal, un insumo sin tarifa **no** cae al precio histórico embebido: queda en
  $0 con alerta explícita (`calidad_cruce = sin_precio_lista`), porque usar el
  histórico sería cobrar el no previsto con la tarifa contractual sin que nadie se
  entere. Si el insumo existe pero le falta precio en el catálogo (Principal), se
  costea con el histórico pero con alerta (`sin_precio_catalogo`) — antes era un
  underbid silencioso. API: `GET/POST /api/listas-precios`, `PATCH
  /api/listas-precios/{id}` (sin DELETE, a propósito).
- **Distancias por proyecto.** Una carpeta de nivel 1 ES un proyecto y puede fijar sus
  distancias de acarreo (`botadero`, `mezclas`, `granulares`) y, **por categoría**, si hay
  peaje y cuánto vale (`proyecto_parametros`: `peaje_{categoria}_{aplica,valor}`, con los
  accesores `params.peaje_aplica(cat)` / `params.peaje_valor(cat)`), más ajustes puntuales
  de composición (`proyecto_ajuste`, que ganan sobre la regla). El rendimiento efectivo de un componente de acarreo es
  `volumen × km_del_proyecto`, con el volumen clasificado una vez por componente en
  `componente_transporte` (las filas M3-KM de la biblioteca). Se aplica en
  `PricingEngine.components()`, el único punto de paso; la biblioteca NO se toca y cada
  proyecto costea el mismo APU distinto. Sin parámetros ni ajustes, el costeo es idéntico
  al de siempre. Un componente M3-KM sin clasificar NO se reescala y sale con alerta —
  también si vive dentro de un sub-APU, caso en el que la alerta dice en qué sub-APU está.
  La identidad de un componente es **código + nombre**: 6 de los 9 códigos de transporte
  tienen homónimo en el catálogo.
- **El peaje es de la caseta, no del proyecto.** La fila `INT3 PEAJE` no tiene categoría
  propia: la hereda del acarreo M3-KM de SU APU (`transporte.categoria_del_peaje`). Medido
  sobre la biblioteca real, los 31 APUs con peaje tienen acarreos de una sola categoría
  (22 granulares, 9 mezclas), así que no hay ambigüedad. Si no se puede determinar
  (acarreo sin clasificar, o dos categorías), el peaje se costea con el **catálogo** —
  igual que antes de la feature — y el ítem alerta «peaje del proyecto no aplicado»:
  preferimos avisar a cobrar la caseta equivocada en silencio. La fila se **quita** si su
  categoría dice que no hay peaje, o si las **tres** lo dicen y no se pudo determinar la
  categoría (un APU cuyo único componente es el peaje no tiene acarreo del que heredar: la
  unanimidad es la traducción fiel del peaje único que había antes). `pricing.py` necesita
  saber de qué APU viene la fila, así que `cost_component` recibe la clave del APU
  **explícita** — `_visitando[-1]` la tiene por casualidad y apoyarse en eso es una trampa.
- **Veredicto de la revisión.** El dictamen por fila se guarda en
  `corrida_item.revision_json` (los dos backends) y se **borra solo en cualquier confirm**
  de la fila, cambie el APU o no: `corridas.actualizar_eleccion` escribe `revision_json=NULL`,
  así que "Confirmar el APU actual" también lo borra (es conservador a propósito: se pierde
  una justificación, no se gana una mentira). Hay un **segundo** punto de paso:
  `corridas.set_costo_manual`, porque poner el costo a mano también es un confirm de la
  fila y el veredicto hablaba de una fila que ya no es esta. Además el
  veredicto guarda `apu_evaluado`, el APU que la fila tenía cuando la IA la evaluó, y
  `_vista_item` **no manda** el veredicto si ya no coincide con el `apu_codigo` de hoy: la
  revisión corre por minutos sobre filas leídas al abrir el request, así que un
  `set_revision` puede llegar después de una reasignación. Un veredicto sobre otro APU no
  dice nada del actual. Es caché, no verdad: se puede volver a revisar cuando sea.
- **Expediente de composición.** Cuando una fila queda sin APU, el usuario puede pedirle a
  la IA una propuesta de composición; el expediente vive en la tabla `composicion`
  (`corridas.db` / schema `corridas`, repo `datos/composiciones_db.py` +
  `datos/pg/composiciones_pg.py`) y es **append-only por versión**: cada generación,
  edición, aprobación o rechazo escribe una fila nueva, nunca actualiza una existente.
  La `version` la manda el **llamador** (`version_base + 1`), no un `MAX+1` calculado
  adentro — si se calculara adentro, dos clics seguidos sacarían el mismo número y el
  índice único (`UNIQUE(corrida_id, seq, version)`, la protección del doble clic) no
  protegería nada; con la versión explícita el segundo choca y el servicio devuelve 409.
  `actividad_json` guarda la vista **des-monetizada** (`privacy.licitacion_item_to_dict`,
  sin `precio_contractual`) y no el `LicitacionItem` crudo — así toda la fila es limpia y
  se puede reinyectar como evidencia más adelante sin filtrarla de nuevo; es la lección de
  `plan_json` aplicada antes de tropezar. El expediente **es caché y no verdad**: la FK
  apunta a `corrida`, no a `corrida_item`, y el `seq` se reusa (borrar la última línea y
  agregar otra le da el mismo `seq` que tenía la borrada), así que una versión vigente
  puede hablar de **otra actividad**. La protección es la misma que `revision_json` con
  `apu_evaluado`: el servicio compara la `descripcion` guardada contra la de la fila de
  hoy y descarta el expediente si no coincide — no se borra nada, y se puede volver a
  componer cuando sea. La composición **no se borra ni se invalida** cuando la fila
  cambia de APU (al revés de `revision_json`): es un expediente con trabajo humano
  adentro, no un veredicto barato. La **confianza** (`alta|media|baja|insuficiente`) la
  calcula `validacion_composicion.calcular_confianza` con señales observables —
  `incertidumbre_declarada` (la del modelo) se guarda **aparte**, en columna propia, y no
  entra en el cálculo. Aprobar pasa por `servicio/autoria.py::crear_apu` (mismas reglas
  de unicidad, gemelo día/noche y auditoría que cualquier alta) y sella la versión como
  `aprobada` con el `apu_codigo` creado — dos archivos SQLite sin transacción común, así
  que si el sellado falla después de crear el APU, la fila queda sin asignarlo (mensaje
  accionable, nunca silencio).
- **Costo puesto a mano.** `corrida_item.costo_manual` (los dos backends) es el costo
  unitario que declaró una persona para una fila: lo escribe el botón "Igualar costo al
  contractual", que copia el `precio_contractual` de las filas marcadas. Es para los
  **proyectos especiales** — actividades globales que valen lo que dice el contrato y a las
  que armarles el APU no paga. Es una **copia de una vez**, no un vínculo: si cambia el
  contractual, el costo se queda y el margen ≠ 0 se ve. `_costear_row` sale temprano cuando
  está puesta (no consulta el catálogo), `seqs_sin_apu` deja pasar esas filas y
  `alertas_costeo` las marca siempre ("costo puesto a mano"), así que salen en la hoja
  ALERTAS y el DESGLOSE muestra la actividad de la licitación en vez del
  `"(sin base — armar manual)"` del matcher. La `explicacion` del matcher sigue apareciendo
  en ALERTAS a propósito: que no hubiera nada parecido en la biblioteca es justamente por lo
  que se costeó a mano. Se **borra sola** en `actualizar_eleccion`: armar el APU de verdad y
  asignarlo devuelve la fila al costeo normal. Igualar a un contractual ≤ 0 (o NaN) se
  rechaza (regla "nada en $0"), y el candado exige `> 0` y no `is not None` para no depender
  de que su único llamador se porte bien.
  Además del botón por selección, un **umbral** lo hace en lote
  (`POST /api/corridas/{id}/igualar-umbral`): iguala las filas candidatas —en $0 (sin
  APU, o con APU pero sin precio de insumos) y con `contractual_total` que no pase el
  techo que pone el usuario— para priorizar, porque en una licitación de 1000-2000
  actividades un puñado se lleva casi todo el presupuesto y armarle el APU a la cola
  larga no mueve la evaluación. La previa la calcula el frontend
  (`web/src/lib/umbralCosto.ts`, espejo de `_candidata_umbral`) sobre los ítems que ya
  viajaron, pero `igualar_por_umbral` **recalcula** la candidatura en el servidor y
  devuelve en `salteadas` lo que cambió desde la previa — el mismo candado que
  `apu_evaluado` y que `rebuscar/aplicar`: el cliente dice cuáles quiere, no qué se
  escribe. El reverso es `POST /api/corridas/{id}/quitar-costo-manual`: borra el
  `costo_manual` y devuelve la fila a `new` **si no tiene APU** —así vuelve a entrar al
  re-match, que es lo que esa fila necesita—; **si tiene APU el status no se toca**.
  Degradarlo a `review` reexponía al re-match una fila que una persona había
  confirmado, justo lo que este mismo documento prohíbe más abajo. La contrapartida es
  conocida y se acepta: como `set_costo_manual` fuerza `confirmed` y no se guarda el
  status previo, una fila que era `auto` vuelve de igualar→quitar como `confirmed`. Es
  un ascenso, no una degradación, y es la dirección conservadora. Sin vuelta atrás, un
  techo mal puesto se arreglaría fila por fila armando APUs que justamente no querías
  armar. Endpoints: `POST
  /api/corridas/{id}/igualar-costo`, `.../igualar-umbral` y `.../quitar-costo-manual`,
  los tres rol `editor` — más estricto que sus vecinos a propósito, porque declaran
  dinero.
- **Volver a buscar APU.** El match corre una vez, al armar; los APUs creados después
  son invisibles para la corrida (costear sí sigue la biblioteca, matchear no). El botón
  **Volver a buscar APU** (`POST /api/corridas/{id}/rebuscar`, rol `consulta`) re-corre
  el matcher del armado sobre las filas que NO están `confirmed`, muestra qué cambiaría
  con costo y margen, y `.../rebuscar/aplicar` escribe solo los `seq` marcados. Usa
  `Matcher.candidates(..., escaneo_completo=False)`: la vía rápida del índice invertido
  es **exacta para asignar** —`similarity` es `0.4·secuencia + 0.6·jaccard`, así que un
  APU sin tokens en común tope en 0,40 y el mínimo para asignar es 0,55—, y baja el costo
  de 42 ms a 0,2 ms por fila, que es lo que hace que el botón sea síncrono sobre 1939
  líneas. Aplicar **recalcula la propuesta en el servidor** y saltea lo que cambió desde
  la previa (mismo candado que `apu_evaluado` en la revisión: el cliente no dicta qué APU
  se escribe). La fila queda con el status del matcher (`auto`/`review`), **no**
  `confirmed`: aprobar la asignación no es auditar la fila, y por eso escribe con
  `actualizar_eleccion` y no con `confirmar_items`, que pisaría la confianza con 1.0.
  En la previa vienen **marcadas solas** las filas en $0 (`marcar_por_defecto`, lo decide
  el backend), **menos** las que tienen un expediente de composición en curso
  (`COMPOSICION_EN_CURSO`): asignarles un APU hace desaparecer el botón "Componer" de la
  tabla y deja el borrador humano fuera de alcance, así que esas se marcan a mano y el
  diálogo lo avisa. Quién las tiene sale de `composiciones.estados_vigentes(corrida_id)`,
  en lote y no fila por fila.
- **Armar APU desde una fila.** El botón **Armar APU** del panel de una fila sale
  siempre (rol editor, corrida no congelada) y ofrece tres puntos de partida: duplicar el
  APU asignado, partir de otro que busques, o desde cero con el nombre, la unidad y el
  `codigo_sugerido` de la actividad ya puestos. Antes solo existía "Duplicar este APU y
  usarlo aquí", que exigía que la fila YA tuviera APU — o sea que faltaba justo en la
  fila que más lo necesita. Lo nuevo es `components/corrida/DialogoArmarApu.tsx`, que
  solo elige el punto de partida: el alta sigue siendo `DialogoAgregarApu` (822 líneas,
  tres consumidores), cuyos modos `crear` y `duplicar` con `inicial` ya hacían lo que
  hacía falta y solo les faltaba llamador. Al crear, el APU queda asignado a la fila y la
  fila `confirmed`, igual que duplicar.
- **Armado reanudable.** Las licitaciones reales traen 1000-2000 ítems y el armado
  tarda de 1 a 3 horas; las instancias de Render (plan free) viven 18-30 minutos, así
  que corriendo dentro de la petición HTTP **no terminaba nunca**. Ahora `POST
  /api/corridas` **encola y devuelve al instante**, y un hilo del proceso web
  (`servicio/armador.py`) consume la cola. **La cola vive en la base**: una corrida en
  `estado='armando'` ES un trabajo pendiente, así que un reinicio no pierde nada — al
  arrancar, la instancia ve el mismo trabajo que dejó la anterior. Las líneas ya
  interpretadas del Excel se guardan en `corrida.plan_json` al crear (el archivo subido
  no se persiste, y sin eso no habría forma de saber qué falta armar; por eso `plan_json`
  está en `_FORBIDDEN_KEYS`: lleva `precio_contractual` adentro). Se reanuda en
  `max_seq + 1`. El worker **reclama** la corrida con un `UPDATE ... WHERE` atómico y
  late cada `ARMADO_LATIDO_S`: durante un deploy la instancia nueva arranca mientras la
  vieja drena, y sin reclama las dos armarían la misma corrida. Un ítem que revienta
  deja una fila sin APU y el armado sigue; `MAX_FALLOS_SEGUIDOS_ARMADO` fallos seguidos
  cortan (un fallo aislado es un ítem malo, una racha es el entorno). Superado
  `ARMADO_MAX_INTENTOS`, la corrida pasa a `armado_detenido` con el motivo y un botón
  para reintentar. **Un archivo no puede tener dos armados a medias en la misma
  carpeta** (`ux_corrida_armando_archivo`, índice único parcial): es la protección del
  doble clic, y es un índice y no un `if` porque las dos peticiones de un doble clic
  llegan con milisegundos de diferencia.
- **Entidad de origen y capítulos (ruta IDU).** Al crear una corrida se elige la
  **entidad** (`nucleo/models.py::EntidadOrigen`: IDU, METRO_BOGOTA, INVIAS,
  OTRA_PUBLICA, PRIVADA, NO_IDENTIFICADA). `dominio/entrada.py` es el **único** punto de
  despacho —un diccionario `entidad → lector`, no una jerarquía de clases—; hoy solo IDU
  tiene lector especializado y el resto usa el importador genérico **a propósito**.
  Con IDU, `POST /api/corridas/previsualizar` lee el Formulario 1, detecta capítulos y
  actividades y devuelve el resumen **sin escribir nada**; la corrida se crea recién
  cuando el usuario aprueba, y `POST /api/corridas` exige `confirmada=true` **y relee y
  revalida el archivo** (el flag es lo que dice el cliente, no una prueba).
  La procedencia se guarda en **`corrida.origen_json`** (una sola columna, como
  `plan_json`): entidad, formato, hoja, versión del parser, quién confirmó y la
  conciliación. `NULL` en toda corrida anterior — eso es "sin clasificación por
  capítulo", no un error, y **no se inventan capítulos retroactivamente**. Lleva dinero
  adentro (la conciliación), así que está en `_FORBIDDEN_KEYS` igual que `plan_json`.
  El capítulo de cada actividad **no tiene tabla**: viaja dentro de `item_json` y
  `plan_json` (`LicitacionItem.capitulo_codigo` / `capitulo_nombre`), que es donde ya
  viajaba `categoria`.
- **Las dos bases del contractual.** En la ruta IDU, `precio_contractual` es el **valor
  unitario CON AIU** (col K del Formulario 1), que es el que concilia exacto con el
  `VALOR TOTAL` y con los subtotales del Excel. El básico sin AIU viaja aparte en
  `precio_contractual_sin_aiu` y se muestra en columna propia, en la web y en el cuadro.
  Ojo: el costo interno **no lleva AIU**, así que la diferencia contra el contractual
  incluye el A.I.U. Medido sobre el archivo de referencia (1939 actividades):
  158.456.072.140 con AIU, 123.871.215.068 sin AIU.
- **Salidas:** `salidas/` (cuadros) y `ejemplos/` (licitaciones de ejemplo).
- Fuentes de precio: `PRECIO IDU` se trata como **público**; el resto
  (`COSTO INTERNO`, `COMPRAS…`, etc.) como **interno/confidencial**
  (`config.PUBLIC_PRICE_SOURCES`).
- **El importador de insumos protege lo interno de lo público, no al revés.** La
  importación en lote (`POST /api/insumos/importar[/preview]`) declara su
  `fuente_import` (obligatoria, se estampa en todas las filas del archivo; la columna
  `fuente` del Excel se ignora). Si esa fuente clasifica como pública
  (`config.classify_price_source`), no pisa un insumo que ya tiene precio interno:
  esas filas quedan en el balde `protegida` del preview y no se escriben
  (`servicio/autoria.py::_protegida`). Al revés —una importación interna sobre un
  precio público— sí se aplica, a propósito (ver "No hacer").

## Pruebas

`tests/` cubre la frontera de privacidad, el matcher, la ingesta, el motor de
precios y el orquestador. Corre `pytest` antes de dar algo por terminado.

## No hacer

- No le pases dinero a la IA (invariante #1). Ojo: `assert_no_money` mira **nombres de
  clave**, no valores, así que nunca metas en un payload texto generado por el motor de
  costos (alertas, explicaciones del pricing) — ahí el monto viaja dentro del string.
- No metas la IA en el armado. Arma el programa; la IA audita después
  (`dominio/revision.py`) y siempre propone: aplicar es del usuario.
- No emitas un cuadro con filas sin APU **ni costo declarado**: el candado de
  `congelar`/`generar_cuadro` (`seqs_sin_apu`) está para eso, no lo esquives. Una fila con
  `costo_manual` positivo sí pasa, a propósito (ver "Costo puesto a mano"), y no pasa
  callada. Ojo: el candado es **de la web**, no global — `pipeline.py` (CLI/GUI) llama
  `write_report` sin pasar por `seqs_sin_apu`, y ahí el hueco se ve en la hoja `ALERTAS`
  del cuadro, no en una puerta trabada. Si lo haces global, el punto de paso es
  `pipeline.py`.
- **Issue conocido, sin arreglar:** `congelar` y las escrituras de costo a mano pueden
  cruzarse. `congelar` lee las filas una vez y escribe los snapshots de TODAS antes de
  marcar `modo='congelada'`; si una escritura entra a mitad de ese bucle, la foto queda
  mixta (unas filas en $0, las siguientes al contractual) y `generar_cuadro` la emite.
  `_exigir_editable` no lo puede ver: el modo todavía es `activa`. Es preexistente
  —`confirmar_items` tiene la misma carrera— pero el umbral es la primera escritura
  masiva de un solo clic, así que la ventana pasó de rara a plausible. Si lo arreglás,
  el punto de paso es `congelar`, no los llamadores.
- No saques una corrida de `estado='armando'` con un `set_estado` pelado: ese estado
  **es la cola** del worker de armado (`servicio/armador.py`). Sacarla de ahí la deja a
  medio armar, sin nadie que la retome y sin error que mirar. Los únicos caminos de
  salida son `finalizar_armado` (el worker, al terminar o rendirse) y `reencolar_armado`
  (el botón de reintentar). Si escribís `estado`, guardá con `estado == "finalizada"`
  como ya hacen los puntos que hoy lo tocan.
- No toques las líneas de una corrida con el plan a medias (`armando` o
  `armado_detenido`): mientras el armado no termine, el espacio de `seq` es del armador.
  `agregar_items` y `borrar_items` ya lo rechazan por `_plan_a_medias`. Agregar una
  línea ahí le roba el `seq` a un ítem del plan y ese ítem **nunca se arma**, sin dejar
  rastro; borrar las últimas hace retroceder el punto de reanudación.
- No emitas un cuadro de una corrida a medio armar: `seqs_sin_apu` **no puede verlo**
  (mira las filas que existen, y las que faltan armar no existen), así que el candado
  es `ArmadoIncompleto` y vive en `_exigir_armado_completo`. Sin él, una corrida
  detenida en 290 de 1939 emite un cuadro de 290 líneas que se ve entero.
- No calcules el resumen por capítulo en dos lados.
  `dominio/report_categorizado.py::resumen_por_capitulo` es la **ÚNICA** función que
  suma por capítulo: la consumen la API (`vista_corrida["capitulos"]`), la web (que solo
  pinta) y las dos hojas de Excel. El frontend no suma dinero.
- No crees una corrida de la ruta IDU sin `confirmada=true`, y no confíes en ese flag:
  el endpoint **relee y revalida** el archivo, porque el cliente puede mentir.
- No le inventes reglas de formato a Metro, INVÍAS ni a las demás entidades. Están en el
  registro de `dominio/entrada.py` apuntando al importador genérico **a propósito**: no
  hay un archivo real medido que justifique otra cosa.
- No metas una `Advertencia` del parser en un payload hacia la IA. Su `detalle` es texto
  libre y lleva **montos adentro** («El Excel dice 67.153 y el recálculo da 67.154»);
  `assert_no_money` mira nombres de clave, no valores. Misma trampa que las alertas de
  costeo.
- No agregues un tipo a `presupuesto.TIPOS_ADVERTENCIA` que nadie emita: hay un test que
  compara el vocabulario contra los `Advertencia(...)` que el módulo construye de
  verdad. Un tipo que nadie dispara es una promesa vacía que el frontend pinta igual.
- No edites el Excel fuente ni borres `data/`, `salidas/`, `ejemplos/`.
- No dupliques lógica de orquestación: reúsala desde `pipeline.py`.
- No hagas que una lista que no sea Principal caiga al precio histórico ni al de
  Principal: el respaldo silencioso es justo lo que esta feature evita.
- No borres listas de precios: una corrida guarda su `lista_precios_id` sin FK, y
  `seed --force` ya las destruye sin poder recuperarlas del Excel (ver Comandos).
- No metas la distancia de un proyecto dentro de la biblioteca (ni editando el APU ni
  duplicándolo): para eso están `proyecto_parametros` y `proyecto_ajuste`. La distancia es
  del sitio, no del APU.
- No hagas que un peaje sin categoría determinable se borre ni se cobre con el valor de
  otra categoría. Se costea con el catálogo y alerta. La única excepción es la unanimidad
  (las tres categorías en «no hay peaje»), y existe para no perder el comportamiento del
  peaje único que había antes.
- No confíes en el código de un insumo de transporte para clasificarlo: 6 de los 9 códigos
  tienen homónimo en el catálogo. Siempre código + nombre.
- Ojo: `seed --force` borra `componente_transporte` (igual que las listas NP) y hay que
  reclasificar las filas M3-KM. Los dos backends se comportan igual a propósito: el espejo
  Postgres hace `DROP SCHEMA apus CASCADE`.
- No le ofrezcas al modelo, en el esquema JSON de la composición, un valor que el
  validador rechaza siempre. El esquema acota `tipo` a `["insumo"]` y saca `sub_apu` de
  `funcion` **a propósito**, aunque el vocabulario del contrato (`dominio/composicion.py`)
  los tenga: con la lista blanca filtrada esas dos opciones son trampas garantizadas —
  el validador las rechaza siempre. Lo que el modelo no puede expresar, no lo puede errar.
- No uses la `incertidumbre_declarada` del modelo como confianza de una composición. La
  confianza la calcula `validacion_composicion.calcular_confianza` con señales
  observables y guarda su desglose (`confianza_motivos`) aparte; hay un test que falla si
  el número que declara el modelo mueve el nivel.
- No conviertas una regla de validación de composición discutible en error bloqueante.
  **La prueba:** si esta regla se dispara, ¿qué hace el usuario para que deje de
  dispararse? Si la respuesta no está entre los campos editables de la mesa de revisión,
  es advertencia, no error. Esta fase lo hizo mal dos veces antes de escribirlo acá: el
  techo de rendimiento (imposible de bajar si la actividad es global de verdad) y
  `TIPO_INCOHERENTE` en su dirección inofensiva (`funcion` no se edita en la mesa).
- No re-derives la lista blanca de una composición al revalidar (`PUT` de una edición
  humana). Solo **crece**: partí de la persistida (`antecedentes_json.codigos_permitidos`)
  y ampliala con lo que agregó una persona. Un `recuperar` fresco puede devolver menos
  códigos que la generación original (un insumo nuevo desplaza a otro fuera del tope, o
  alguien lo oculta) y dejaría sin autorizar un componente que el modelo propuso bien.
- No hagas simétrico el candado del importador de insumos ni le agregues una casilla
  de "forzar". Una importación cuya fuente clasifique como pública (`PRECIO IDU`) no
  pisa un precio interno: esas filas van al balde `protegida` del preview y no se
  escriben (`servicio/autoria.py::_protegida`, embudo único en `_upsert_o_invalida`).
  Al revés sí se puede, y es a propósito: una tanda pública es masiva y automática
  (miles de filas del visor del IDU), una interna es curada y deliberada. Si hay que
  cambiar un interno, se edita por insumo, que ya se puede. Ojo con el término
  `not ins.sin_precio`: sin él, una importación pública contra una lista de NP recién
  creada queda bloqueada entera, porque sin tarifa en esa lista `fuente_precio` es
  `""` (LEFT JOIN) y `""` clasifica como interno.
- No le devuelvas al archivo el mando sobre la etiqueta de fuente. La fuente la
  declara la importación (`fuente_import`, `Form(...)` obligatorio en
  `POST /api/insumos/importar/preview` y `/importar`) y se estampa en TODAS las
  filas (`servicio/autoria.py::_filas_insumos`); la columna `fuente` del Excel se
  ignora. El `fuente_nueva = f["fuente"] or ins.fuente_precio` que había antes
  (`_cambio_upsert`) dejaba el precio nuevo con la etiqueta vieja: un precio del IDU
  rotulado `COSTO INTERNO`, tratado como confidencial por `config.classify_price_source`
  sin que nada lo avisara.
- No conviertas en "listo" el aviso de clasificación del diálogo de importación
  (`DialogoImportarInsumos.tsx`). `classify_price_source` es fail-open: `PRECIO IDU
  2026` clasifica **interno** y el candado no se dispara. La protección es que el
  diálogo **muestre** cómo se clasificó la fuente (`clasificacion_import` del preview)
  antes de aplicar, no que el sistema adivine que quisiste decir `PRECIO IDU`. Un
  matching difuso ahí sería una fuente nueva de sorpresas.
- No hagas que volver a buscar APU toque una fila `confirmed`, ni le agregues un
  "forzar". Una persona resolvió esa fila; el re-match no la pisa. Las de `costo_manual`
  caen ahí solas (`set_costo_manual` las deja `confirmed`), y eso es el candado, no una
  casualidad: si algún día el costo a mano dejara de confirmar la fila, un re-match se
  lo llevaría puesto.
- No refresques candidatos fila por fila. `set_candidatos` es por lote a propósito: crear
  un APU puede cambiar la lista de cientos de filas, y contra Supabase eso es el N+1 que
  este repo ya pagó una vez. Lo mismo con `composiciones.estados_vigentes`.
- No hagas que la previa de volver a buscar marque sola una fila con composición en curso.
  El expediente no se borra (es append-only), pero apenas la fila tiene `apu_codigo` el
  botón "Componer" desaparece de la tabla (`TablaItems.tsx`) y el borrador queda
  inalcanzable salvo por URL. El candado es contra el gesto masivo ("marcar todas"), no
  contra la decisión: marcarla a mano y aplicar sigue funcionando, a propósito.
- No pongas texto de usuario en un atributo JSX partido en dos líneas
  (`title="...\n   ...")`. El salto y la indentación del código entran al tooltip tal
  cual. Va como expresión: `title={"..." + "..."}`. Ya pasó dos veces en esta misma
  feature.
- No dejes que el cliente dicte qué filas iguala el umbral: `igualar_por_umbral`
  **recalcula** la candidatura sobre una vista fresca y saltea lo que cambió, igual
  que el candado de `apu_evaluado` y el de `rebuscar/aplicar`. Sin eso, una pestaña
  vieja pisa un APU recién asignado con una copia del contractual y encima deja la
  fila `confirmed`, o sea fuera del alcance de volver a buscar APU. Con diez filas
  eso se ve; con mil quinientas no.
- No hagas que el umbral mire los filtros de la tabla: el techo es una decisión de
  presupuesto, no de vista, así que el diálogo trabaja sobre la corrida entera a
  propósito.
- No llames `umbral` a secas al campo del techo: es dinero y va en `_FORBIDDEN_KEYS`
  como `umbral_contractual`; `umbral` chocaría con los umbrales de matching, que
  **no** son dinero, y un falso positivo ahí volaría un payload legítimo hacia la IA.
- No dejes igualar o quitar el costo a mano con el plan a medias (`armando` o
  `armado_detenido`). Las filas que faltan armar no existen todavía, así que un
  "5,3% del contrato" ahí es el 5,3% de 290 líneas de 1939: una mentira. Mismo
  candado que `agregar_items`/`borrar_items` y que `_exigir_rebuscable`
  (`servicio/corridas.py::_exigir_editable`, que usan `igualar_costo_al_contractual`,
  `igualar_por_umbral` y `quitar_costo_manual`).
