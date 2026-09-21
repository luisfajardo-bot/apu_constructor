"""
Contratos de almacenamiento, separados por dominio.

Hoy los implementan PreciosDB y ApusDB (SQLite). Mañana, un backend de nube
(p. ej. Postgres) implementa estos mismos Protocols y el resto del programa no cambia.
"""
from __future__ import annotations

from typing import Iterable, Optional, Protocol, runtime_checkable

from apu_tool.nucleo.models import (
    AjusteProyecto, Apu, ApuComponent, Carpeta, ClaseTransporte, ComposicionRow,
    CorridaItemRow, CorridaMeta, DePricedApu, EventoAuditoria, Insumo, ListaPrecios,
    ParametrosProyecto, Perfil,
)


class CorridaEliminada(Exception):
    """Se intentó agregar un ítem a una corrida que ya no existe (la borraron o se
    reseteó durante el armado). Señala que el armado debe cancelarse limpio, en vez
    de propagar un error de integridad de la base."""

    def __init__(self, corrida_id: int):
        super().__init__(f"La corrida {corrida_id} fue eliminada durante el armado.")
        self.corrida_id = corrida_id


class ArmadoDuplicado(Exception):
    """Ya hay un armado a medias del MISMO archivo en la MISMA carpeta.

    Lo frena el índice único parcial `ux_corrida_armando_archivo` (los estados
    'armando' y 'armado_detenido'), no una comprobación previa: las dos peticiones de
    un doble clic llegan a milisegundos de distancia, las dos leerían "no hay
    ninguna" y las dos encolarían tres horas de armado del mismo Excel.

    `corrida_id` es la corrida que YA existe, para llevar al usuario ahí en vez de
    dejarlo reintentando. Es opcional porque esta capa ve la violación pero no los
    estados que la definen (viven en el servicio, en `ARMANDO_O_A_MEDIAS`): lo
    completa `servicio.corridas.crear_corrida_encolada`.
    """

    def __init__(self, archivo: str, corrida_id: Optional[int] = None):
        self.archivo = archivo
        self.corrida_id = corrida_id
        cola = (f" (corrida {corrida_id}): te llevamos a esa en vez de armar el mismo "
                f"archivo dos veces." if corrida_id else ": esperá a que termine.")
        super().__init__(f"Ya hay un armado en curso de «{archivo}» en esta carpeta"
                         + cola)


class VersionYaExiste(Exception):
    """Se intentó escribir una versión de composición que ya está.

    La levanta el índice único `ux_composicion_version`, no una comprobación previa:
    las dos peticiones de un doble clic leerían la misma versión vigente y las dos
    creerían estar escribiendo la siguiente. El servicio la traduce a un 409.
    """

    def __init__(self, corrida_id: int, seq: int, version: int):
        super().__init__(f"La composición {corrida_id}/{seq} ya tiene la versión "
                         f"{version}: alguien más la cambió mientras trabajabas.")
        self.corrida_id, self.seq, self.version = corrida_id, seq, version


@runtime_checkable
class RepositorioPrecios(Protocol):
    def init_schema(self) -> None: ...
    def reset(self) -> None: ...
    def insert_insumos(self, insumos: Iterable[Insumo]) -> int: ...
    def crear_insumo(self, insumo: Insumo, conn=None, creado_por: Optional[str] = None,
                     lista_id: Optional[int] = None) -> int: ...
    def get_candidatos(self, codigo: str, lista_id: Optional[int] = None) -> list[Insumo]: ...
    def get_candidatos_bulk(self, codigos: Iterable[str],
                            lista_id: Optional[int] = None) -> dict[str, list[Insumo]]:
        """Como get_candidatos pero para muchos códigos en UNA consulta (optimización).
        Devuelve {codigo: [candidatos...]} con la misma semántica que llamarlo 1x1."""
        ...
    def get_insumo_por_id(self, insumo_id: int,
                          lista_id: Optional[int] = None) -> Optional[Insumo]: ...
    def set_precio(self, codigo: str, precio: float, fuente: str = "",
                   fecha: Optional[str] = None, nombre: Optional[str] = None) -> None: ...
    def set_precio_por_id(self, insumo_id: int, precio: float, fuente: str = "",
                          fecha: Optional[str] = None, conn=None,
                          creado_por: Optional[str] = None,
                          lista_id: Optional[int] = None) -> None: ...
    def price_history(self, codigo: str, nombre: Optional[str] = None,
                      lista_id: Optional[int] = None) -> list[dict]: ...
    def list_insumos(self, q=None, grupo=None, fuente=None,
                     clasificacion: Optional[str] = None,
                     limit: int = 100, offset: int = 0,
                     lista_id: Optional[int] = None,
                     sin_precio: bool = False) -> tuple[list[Insumo], int]:
        """Catálogo COMPLETO con el precio vigente en `lista_id` (None = Principal).
        Los insumos sin tarifa en esa lista vienen con precio 0 y `sin_precio=True`.
        `sin_precio=True` es excluyente con `fuente` y `clasificacion` (ValueError)."""
        ...
    def grupos(self) -> list[str]: ...
    def fuentes(self, lista_id: Optional[int] = None) -> list[str]: ...
    def set_oculto(self, insumo_id: int, oculto: bool, conn=None) -> None:
        """Marca (o desmarca) un insumo como oculto — no se borra, solo se filtra
        de list_insumos/search_insumos*/grupos/fuentes."""
        ...
    def todos_no_ocultos(self) -> list[tuple[int, str, str]]:
        """(id, codigo, nombre) de todos los insumos con oculto=false."""
        ...
    def identidades_en_conflicto(self, codigo: str,
                                 nombre_norm: str) -> list[tuple[str, str, bool]]:
        """`(codigo, nombre, oculto)` de los insumos cuyo código O `nombre_norm` coincide.

        Los dos lados del chequeo de duplicados del alta (`servicio/autoria.py`) en una
        sola consulta. Incluye los ocultos a propósito: `get_candidatos` no filtra
        `oculto`, o sea que el motor de precios los ve, y un código repetido con uno
        oculto deja el cruce igual de ambiguo que con uno visible."""
        ...
    def search_insumos(self, texto: str, limit: int = 20) -> list[Insumo]: ...
    def search_insumos_por_palabras(self, palabras: list[str],
                                    limit: int = 60) -> list[Insumo]: ...

    def counts(self) -> dict[str, int]:
        """`insumos` (todas las filas), `insumo_precios` y `insumos_visibles`.

        `insumos` incluye los ocultos: lo usan los guards de seed. `insumos_visibles`
        excluye `oculto = 1` y es la que se le muestra al usuario."""
        ...
    def set_meta(self, clave: str, valor: str) -> None: ...
    def get_meta(self) -> dict[str, str]: ...
    def descripcion(self) -> str:
        """Identidad legible del backend (para `status`), agnóstica de SQLite/Postgres."""
        ...

    # --- listas de precios (tarifas). La id config.LISTA_PRINCIPAL_ID es 'Principal' ---
    def listar_listas(self) -> list[ListaPrecios]: ...
    def get_lista(self, lista_id: int) -> Optional[ListaPrecios]: ...
    def crear_lista(self, nombre: str, creado_por: Optional[str] = None,
                    conn=None) -> int:
        """Crea una lista. ValueError si el nombre está vacío o ya existe (sin
        distinguir mayúsculas)."""
        ...
    def renombrar_lista(self, lista_id: int, nombre: str, conn=None) -> None:
        """ValueError si la lista no existe, si el nombre choca, o si es la Principal
        (intocable: es el ancla del invariante lista_id=None == Principal)."""
        ...


@runtime_checkable
class RepositorioApus(Protocol):
    def init_schema(self) -> None: ...
    def reset(self) -> None: ...
    def insert_apus(self, apus: Iterable[Apu]) -> int: ...
    def insert_components(self, comps: Iterable[ApuComponent]) -> int: ...
    def crear_apu(self, apu: Apu, componentes: list[ApuComponent], conn=None) -> None: ...
    def editar_apu(self, apu: Apu, componentes: list[ApuComponent], conn=None) -> None:
        """Edita cabecera (nombre/unidad/grupo) y REEMPLAZA la composición de un APU
        existente. Identidad (codigo, shift) inmutable. ValueError si no existe."""
        ...
    def borrar_apu(self, codigo: str, shift: str, conn=None) -> bool:
        """Borra componentes + cabecera de un APU. False si no existía."""
        ...
    def list_apus(self, q: Optional[str] = None, grupo: Optional[str] = None,
                  shift: Optional[str] = None, limit: int = 100,
                  offset: int = 0) -> tuple[list[Apu], int]: ...
    def all_apus(self) -> list[Apu]: ...
    def apu_index(self) -> list[tuple[str, str, str]]: ...
    def get_apu(self, codigo: str, shift: str) -> Optional[Apu]: ...
    def search_apus(self, texto: str, limit: int = 20) -> list[Apu]: ...
    def grupos(self) -> list[str]: ...
    def get_components(self, apu_codigo: str, shift: str) -> list[ApuComponent]: ...
    def get_components_bulk(self, claves: Iterable[tuple[str, str]]
                            ) -> dict[tuple[str, str], list[ApuComponent]]:
        """Como get_components pero para muchos (codigo, shift) en UNA consulta.
        Devuelve {(codigo, shift): [componentes...]} para las claves halladas."""
        ...
    def rendimientos_por_insumo(self, codigos: Iterable[str]
                                ) -> dict[str, list[tuple[str, float]]]:
        """(unidad, rendimiento) con que cada insumo aparece en la biblioteca."""
        ...
    def component_counts(self) -> dict[tuple[str, str], int]: ...
    def componentes_subapu_candidatos(self) -> list[dict]:
        """Componentes tipo='insumo' cuyo código es un APU (candidatos a sub-APU)."""
        ...
    def set_componente_subapu(self, apu_codigo: str, shift: str, seq: int,
                              ref_shift: str, conn=None) -> None:
        """Marca un componente como sub-APU (tipo='apu') con su turno de referencia."""
        ...
    def pares_insumo_en_uso(self) -> list[tuple[str, str]]:
        """(insumo_codigo, insumo_nombre) distintos de cada componente tipo='insumo'."""
        ...
    def get_depriced_apu(self, codigo: str, shift: str) -> Optional[DePricedApu]: ...
    def get_clasificacion_transporte(self) -> list[ClaseTransporte]:
        """Clasificación de los componentes de acarreo (categoría + volumen)."""
        ...
    def set_clasificacion_transporte(self, filas: Iterable[ClaseTransporte],
                                     conn=None,
                                     actualizado_por: Optional[str] = None) -> int: ...
    def componentes_transporte_candidatos(self) -> list[dict]:
        """Filas M3-KM de la biblioteca con su APU dueño, para clasificar."""
        ...
    def componentes_para_integridad(self) -> list[tuple[str, str]]:
        """(insumo_codigo, insumo_nombre) de cada componente con código no vacío.
        Para el chequeo de integridad APU→insumo, sin SQL crudo en el dominio."""
        ...
    def counts(self) -> dict[str, int]: ...
    def set_meta(self, clave: str, valor: str) -> None: ...
    def get_meta(self) -> dict[str, str]: ...
    def descripcion(self) -> str:
        """Identidad legible del backend (para `status`), agnóstica de SQLite/Postgres."""
        ...


@runtime_checkable
class RepositorioCorridas(Protocol):
    def init_schema(self) -> None: ...
    def reset(self) -> None: ...
    def crear_corrida(self, meta: CorridaMeta) -> int:
        """Crea la corrida y devuelve su id. Lanza `ArmadoDuplicado` si ya hay un
        armado a medias del mismo `archivo` en la misma `carpeta_id` (lo decide el
        índice, no una consulta previa: ver la excepción)."""
        ...
    def guardar_items(self, corrida_id: int, items: list[CorridaItemRow]) -> int: ...
    def agregar_item(self, corrida_id: int, fila: CorridaItemRow) -> None:
        """Inserta un ítem (armado incremental). Lanza CorridaEliminada si la
        corrida ya no existe."""
        ...
    def borrar_items(self, corrida_id: int, seqs: Iterable[int], conn=None) -> int:
        """Borra los ítems indicados y devuelve cuántos borró. Los seq que no existen
        se ignoran. NO renumera lo que queda: el seq es identidad (URL del ítem y clave
        del snapshot), así que renumerar casaría snapshots con la línea equivocada."""
        ...
    def get_corrida(self, corrida_id: int) -> Optional[CorridaMeta]: ...
    def get_items(self, corrida_id: int) -> list[CorridaItemRow]: ...
    def get_item(self, corrida_id: int, seq: int) -> Optional[CorridaItemRow]: ...
    def actualizar_eleccion(self, corrida_id: int, seq: int, *, status: str,
                            apu_codigo: Optional[str], apu_nombre: str, unidad: str,
                            shift: str, origen: str, confianza: float,
                            explicacion: str, componentes: list[dict]) -> None:
        """Cambia el APU elegido de una fila. BORRA su revisión y su costo puesto a
        mano: el veredicto hablaba del APU anterior, y el costo a mano ya no manda
        porque la fila volvió a tener una composición real."""
        ...
    def set_candidatos(self, corrida_id: int,
                       candidatos: dict[int, list[dict]]) -> None:
        """Refresca la lista de candidatos de varias filas, {seq: candidatos}.

        NO toca el APU elegido, ni el veredicto, ni el costo puesto a mano: refrescar
        candidatos no es cambiar de APU, y por eso no pasa por `actualizar_eleccion`,
        que borra los dos.

        Es por lote (no fila por fila) por la misma razón que `set_costo_manual`: crear
        un APU puede cambiar la lista de cientos de filas, y contra Postgres eso serían
        cientos de round-trips. Un dict vacío no escribe nada."""
        ...
    def set_cuadro(self, corrida_id: int, path: str) -> None: ...
    def set_estado(self, corrida_id: int, estado: str) -> None: ...
    def set_duracion(self, corrida_id: int, duracion_ms: int) -> None: ...
    def set_modo(self, corrida_id: int, modo: str) -> None: ...
    def set_nombre(self, corrida_id: int, nombre: str) -> None: ...
    def set_snapshot(self, corrida_id: int, seq: int, payload: dict) -> None: ...
    def get_snapshots(self, corrida_id: int) -> dict[int, dict]: ...
    def set_revision(self, corrida_id: int, seq: int, payload: Optional[dict]) -> None:
        """Veredicto de la IA de una fila. payload=None lo borra."""
        ...
    def set_costo_manual(self, corrida_id: int, costos: dict[int, float], conn=None) -> None:
        """Costo unitario puesto a mano, {seq: costo}, y la fila queda `confirmed`.

        Poner el costo a mano ES un confirm, así que también borra `revision_json`
        (el veredicto hablaba de una fila que ya no es esta), la misma razón por la
        que lo borra `actualizar_eleccion`. Y `actualizar_eleccion` a su vez BORRA
        `costo_manual`: si la fila cambia de APU, manda el APU."""
        ...
    def limpiar_costo_manual(self, corrida_id: int, seqs: list[int], conn=None) -> None:
        """Borra el costo puesto a mano y devuelve la fila al costeo normal.

        Es el reverso de `set_costo_manual`, y va por lote por la misma razón: el
        umbral puede tocar cientos de filas de una. Una lista vacía no escribe nada.

        El status vuelve a `new` si la fila no tiene APU (que es exactamente lo que
        era: así la deja `assemble.py` cuando no hay match) y a `review` si lo tiene.
        No guardamos el status previo y no hace falta adivinarlo: `review` —«mírala»—
        es la verdad honesta para una fila que sí tiene match.

        NO toca `revision_json`: `set_costo_manual` ya lo había borrado y no hay
        veredicto que restaurar."""
        ...
    def set_plan(self, corrida_id: int, plan_json: str, conn=None) -> None:
        """Guarda las líneas ya interpretadas del Excel. Única fuente de qué falta
        armar: el archivo subido no se persiste."""
        ...
    def get_plan(self, corrida_id: int) -> Optional[str]:
        """El plan crudo, o None si la corrida no existe o no tiene."""
        ...
    def set_origen(self, corrida_id: int, origen_json: str, conn=None) -> None:
        """De dónde salió el presupuesto (entidad, hoja, parser, conciliación).

        Se escribe UNA vez, justo después de crear la corrida, por la misma razón que
        `set_plan`: no ensucia el INSERT de los dos backends con una columna opcional.
        """
        ...

    def get_origen(self, corrida_id: int) -> Optional[str]:
        """El JSON crudo del origen, o None si la corrida es anterior a la ruta IDU."""
        ...

    def max_seq(self, corrida_id: int) -> int:
        """El `seq` más alto ya armado, o -1 si no hay ninguno. El worker reanuda en
        `max_seq + 1`. Se usa el MÁXIMO y no la cantidad: con una fila borrada en el
        medio, contar reanudaría sobre un seq que ya existe."""
        ...

    def reclamar_armado(self, instancia: str, ahora: str,
                        limite_vencimiento: str) -> Optional[int]:
        """Toma la corrida en 'armando' más vieja que nadie esté armando, y devuelve
        su id (None si no hay ninguna). Sube `intentos`.

        ES UN SOLO UPDATE CONDICIONAL, no un "leo y después escribo": durante un
        deploy la instancia nueva arranca mientras la vieja todavía drena, y sin
        atomicidad las dos armarían la misma corrida. `corrida_item` NO tiene
        UNIQUE(corrida_id, seq) —llega en una tarea posterior—, así que hoy nada
        detecta las filas duplicadas después del hecho: esta reclama es la única
        defensa que hay.

        `limite_vencimiento` es el ISO por debajo del cual una reclama se considera
        muerta (ahora - config.ARMADO_TTL_RECLAMA_S, constante de una tarea posterior;
        todavía no existe).

        OJO: el vencimiento se mide con el reloj del que llama, no con el de la base.
        Una instancia adelantada le puede robar una reclama viva a otra, y un latido
        con hora futura deja la corrida intocable hasta que el tiempo real la alcance.
        En Render los relojes van por NTP y esto no se ve; si algún día molesta, el
        arreglo es tomar `now()` de la base en vez de recibir los ISO de afuera."""
        ...

    def latir_armado(self, corrida_id: int, ahora: str,
                     instancia: Optional[str] = None) -> bool:
        """Refresca `armando_desde` para que la reclama no venza mientras se trabaja.

        Con `instancia` solo late si esa instancia SIGUE siendo la dueña (ver el
        fencing de `finalizar_armado`); con None late igual, sea de quien sea.

        Devuelve si el UPDATE aplicó, y eso es el AVISO: el fencing impide que un
        worker desplazado pise al dueño nuevo, pero no lo entera de que lo
        desplazaron. Un `False` acá es la forma barata (cada tanto, no por ítem) de
        que un worker que perdió la reclama se dé cuenta y pare limpio, en vez de
        seguir armando en paralelo durante horas."""
        ...

    def finalizar_armado(self, corrida_id: int, estado: str,
                         duracion_ms: Optional[int] = None,
                         error: Optional[str] = None,
                         instancia: Optional[str] = None) -> bool:
        """Fija `estado`, libera la reclama y guarda la duración o el motivo.

        Con `estado='en_revision'` o `'armado_detenido'` saca la corrida de la cola
        (es el único camino de salida junto con `reencolar_armado`). El worker
        también la llama con `estado='armando'` tras un fallo que no es de un ítem:
        ahí la corrida SIGUE en la cola, solo se suelta la reclama para que se pueda
        reintentar de inmediato en vez de esperar el TTL. `intentos` no se toca, así
        que el tope sigue aplicando.

        `duracion_ms=None` significa "no la sé", NO "borrala": la duración vieja
        queda. `error` sí se pisa siempre, incluso con None: terminar bien tiene que
        limpiar el motivo del intento que falló.

        `instancia` es el FENCING y es opcional. Si viene, el UPDATE solo aplica
        mientras esa instancia siga siendo la dueña (`armando_por`): en un deploy de
        Render el worker viejo sigue armando mientras drena, su reclama vence, el
        nuevo la toma, y sin esto el viejo le soltaría la reclama al dueño legítimo
        (con `estado='armando'` es peor: una tercera instancia la reclama y quedan
        dos armando la misma corrida). Es opcional porque el camino sincrónico
        (`construir_corrida`, el de CLI y GUI) crea y arma en el acto, sin worker y
        sin reclama: ahí no hay dueño que verificar. El worker siempre la pasa.

        Devuelve si el UPDATE aplicó: `False` con `instancia` significa que la reclama
        ya no es tuya (ver `latir_armado`).

        Con `estado='armado_detenido'` pasá SIEMPRE el `error`: una corrida detenida
        sin motivo no le dice a nadie qué se rompió ni si vale la pena reanudarla, y
        el motivo tiene que quedar visible."""
        ...

    def reencolar_armado(self, corrida_id: int) -> None:
        """Vuelve a poner la corrida en la cola desde cero: 'armando', intentos en 0,
        sin error y sin reclama. Lo usa el endpoint de reanudar a mano."""
        ...

    def posicion_en_cola(self, corrida_id: int) -> int:
        """Cuántas corridas en 'armando' son más viejas que esta. 0 = es la próxima."""
        ...

    def set_carpeta(self, corrida_id: int, carpeta_id: int, conn=None) -> None: ...
    def listar_corridas(self) -> list[CorridaMeta]: ...
    def eliminar_corrida(self, corrida_id: int, conn=None) -> bool: ...
    def counts(self) -> dict[str, int]: ...

    def contar_items_por_apu(self, apu_codigo: str) -> int:
        """Nº de ítems de corrida que referencian este apu_codigo (aviso al borrar)."""
        ...


@runtime_checkable
class RepositorioCarpetas(Protocol):
    def crear(self, nombre: str, parent_id: Optional[int] = None,
              creado_por: Optional[str] = None, conn=None) -> int: ...
    def get(self, carpeta_id: int) -> Optional[Carpeta]: ...
    def listar(self) -> list[Carpeta]: ...
    def renombrar(self, carpeta_id: int, nombre: str, conn=None) -> None: ...
    def mover(self, carpeta_id: int, parent_id: Optional[int], conn=None) -> None: ...
    def eliminar(self, carpeta_id: int, conn=None) -> bool: ...
    def contar_hijas(self, carpeta_id: int) -> int: ...
    def contar_corridas(self, carpeta_id: int) -> int: ...

    def get_parametros(self, carpeta_id: int) -> Optional[ParametrosProyecto]:
        """Distancias/peaje del proyecto. None = sin definir (costeo de siempre)."""
        ...
    def set_parametros(self, params: ParametrosProyecto, conn=None,
                       actualizado_por: Optional[str] = None) -> None: ...
    def listar_ajustes(self, carpeta_id: int) -> list[AjusteProyecto]: ...
    def crear_ajuste(self, ajuste: AjusteProyecto, conn=None,
                     creado_por: Optional[str] = None) -> int: ...
    def borrar_ajuste(self, carpeta_id: int, ajuste_id: int, conn=None) -> bool: ...


@runtime_checkable
class RepositorioPerfiles(Protocol):
    def init_schema(self) -> None: ...
    def reset(self) -> None: ...
    def get(self, user_id: str) -> Optional[Perfil]: ...
    def upsert(self, perfil: Perfil, conn=None) -> None: ...

    def get_por_email(self, email: str) -> list[Perfil]:
        """Perfiles con ese email (comparado en minúsculas y sin espacios).

        Devuelve una LISTA porque `perfiles.email` no es UNIQUE: puede haber 0, 1 o
        varios. Quien decide qué hacer con el caso ambiguo es `servicio/auth.py`, no
        el repositorio."""
        ...

    def reasignar_user_id(self, viejo: str, nuevo: str, conn=None) -> bool:
        """Mueve un perfil a otro `user_id` (misma fila, nueva PK). Devuelve si aplicó.

        Es lo que hace la adopción por email cuando Supabase entrega un `user_id`
        nuevo para un usuario ya invitado. Se mueve y no se duplica: dos filas del
        mismo email descuadrarían el guard del último Admin activo, que cuenta filas.

        Devuelve `True` solo si el UPDATE movió una fila (`viejo` existía). El llamador
        (`_adoptar_por_email`) audita solo si esto da `True`: sin eso, una carrera (p.ej.
        varias llamadas paralelas tras un login) escribiría N filas de auditoría para un
        solo vínculo real."""
        ...

    def listar(self) -> list[Perfil]: ...
    def set_rol(self, user_id: str, rol: str, conn=None) -> None: ...
    def set_estado(self, user_id: str, estado: str, conn=None) -> None: ...
    def contar_admins_activos(self) -> int: ...

    def set_rol_protegido(self, user_id: str, rol: str, conn=None) -> bool:
        """UPDATE atómico del rol que NO deja el sistema sin admin activo.
        Devuelve True si aplicó, False si lo bloqueó el guard (o el usuario no existe)."""
        ...

    def set_estado_protegido(self, user_id: str, estado: str, conn=None) -> bool:
        """UPDATE atómico del estado con el mismo guard de último-admin. Devuelve si aplicó."""
        ...


@runtime_checkable
class RepositorioAuditoria(Protocol):
    def registrar(self, conn, evento: EventoAuditoria) -> None:
        """Inserta un evento SOBRE la conexión dada (transaccional con la mutación).
        NUNCA abre su propia conexión."""
        ...

    def listar(self, *, user_id: Optional[str] = None, accion: Optional[str] = None,
               entidad_tipo: Optional[str] = None, desde: Optional[str] = None,
               hasta: Optional[str] = None, lote_id: Optional[str] = None,
               limit: int = 100, offset: int = 0) -> tuple[list[dict], int]:
        """Lectura paginada (abre su propia conexión). antes/despues/contexto ya
        parseados a objetos Python (dict/None). Orden ts desc."""
        ...


@runtime_checkable
class RepositorioComposiciones(Protocol):
    def agregar(self, fila: ComposicionRow, conn=None) -> None:
        """Escribe una versión NUEVA. Levanta VersionYaExiste si esa versión ya está."""
        ...

    def vigente(self, corrida_id: int, seq: int) -> Optional[ComposicionRow]:
        """La versión de mayor número, o None si nunca se compuso esta fila."""
        ...

    def historial(self, corrida_id: int, seq: int) -> list[ComposicionRow]:
        """Todas las versiones, de la más vieja a la más nueva."""
        ...

    def estados_vigentes(self, corrida_id: int) -> dict[int, str]:
        """`{seq: estado}` de la versión VIGENTE (la de mayor `version`) de cada fila
        de la corrida que tenga expediente. Las filas sin expediente no aparecen.

        En lote y no fila por fila: una corrida tiene miles de líneas y preguntar de a
        una sería el N+1 de siempre. Devuelve el estado crudo; qué estados cuentan como
        "en curso" lo decide quien llama, no el repositorio."""
        ...
