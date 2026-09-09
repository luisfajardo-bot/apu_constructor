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
lista licitación ──► encola ──► worker arma (reanudable) ──► confirma usuario ──► motor de precios
                                                          └─► cuadro resumen (Excel)
corrida armada ──► revisión con IA (sin dinero) ──► propone veredicto ──► confirma usuario

Interfaces sobre el mismo pipeline (dominio/pipeline.py):
  interfaz/{cli,gui}.py (local) · servicio/ (FastAPI, 58 endpoints) + web/ (React) para multiusuario
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
| `presupuesto.py`         | lectura del presupuesto oficial por capítulos |
| `matching.py`            | matcher determinístico (fuzzy, sin dependencias externas) |
| `cruce.py`               | cruce insumo-de-APU ↔ insumo-de-catálogo por código+nombre |
| `compose.py`             | candidatos de insumos para composición generativa |
| `privacy.py`             | frontera de precios para la IA (invariante #1) |
| `ai_assist.py`           | IA acotada (Anthropic SDK): compone un APU a pedido |
| `revision.py`            | revisión con IA de una corrida ya armada (propone, no aplica) |
| `assemble.py`            | orquestador por ítem |
| `pricing.py`             | motor de costos (**ÚNICO** que ve dinero) |
| `alertas.py`             | alertas de costeo (por qué un ítem necesita revisión) |
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
| `corridas.py`          | lógica de servicio de corridas (armado en vivo, revisión con IA, componer) |
| `insumos.py`           | lógica de servicio para editar insumos |
| `insumos_ocultos.py`   | insumos ocultos: eco de un APU, sin uso real (no se borran) |
| `listas.py`            | listas de precios (tarifas): Principal + una por obra de NP |
| `autoria.py`           | alta de insumos/APUs nuevos |
| `subapus.py`           | migración: marca componentes que son sub-APU |
| `apus.py`              | lectura de la biblioteca de APUs |
| `carpetas.py`          | reglas de carpetas de corridas |
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
  de que su único llamador se porte bien. Endpoint: `POST /api/corridas/{id}/igualar-costo`,
  rol `editor` — más estricto que sus vecinos a propósito, porque declara dinero.
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
- **Salidas:** `salidas/` (cuadros) y `ejemplos/` (licitaciones de ejemplo).
- Fuentes de precio: `PRECIO IDU` se trata como **público**; el resto
  (`COSTO INTERNO`, `COMPRAS…`, etc.) como **interno/confidencial**
  (`config.PUBLIC_PRICE_SOURCES`).

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
- No edites el Excel fuente ni borres `data/`, `salidas/`, `ejemplos/`.
- No dupliques lógica de orquestación: reúsala desde `pipeline.py`.
- No hagas que una lista que no sea Principal caiga al precio histórico ni al de
  Principal: el respaldo silencioso es justo lo que esta feature evita.
- No borres listas de precios: una corrida guarda su `lista_precios_id` sin FK, y
  `seed --force` ya las destruye sin poder recuperarlas del Excel (ver Comandos).
