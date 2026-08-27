"""
Motor de precios determinístico.

Es el ÚNICO módulo que toca dinero. Toma un APU (su composición de insumos con
rendimientos) y calcula el costo unitario, llamando a los precios de la base de
insumos. Idea central del usuario: los APUs siempre llaman al precio vigente del
insumo; si el insumo no está en el catálogo, se usa el precio histórico embebido
en la composición como respaldo.

Este módulo NO se le pasa nunca a la IA.
"""
from __future__ import annotations

from apu_tool import config
from apu_tool.datos.almacen import Almacen
from apu_tool.dominio import cruce, transporte
from apu_tool.nucleo.models import (
    ApuComponent, CostedComponent,
    CALIDAD_SIN_PRECIO_CATALOGO, CALIDAD_SIN_PRECIO_LISTA,
    FUENTE_SIN_PRECIO_LISTA, FUENTE_SIN_RESPALDO,
)
from apu_tool.nucleo.redondeo import mul_redondeado


class PricingEngine:
    def __init__(self, almacen: Almacen, lista_id: int | None = None,
                 contexto: "transporte.ContextoProyecto | None" = None):
        self.alm = almacen
        # Normalizada UNA vez: dentro del motor la lista es siempre un int concreto,
        # así que no hay dos nociones de "Principal" (comparar el crudo contra None
        # se contradecía con el int() que hace la capa de datos ante un lista_id="1").
        # None => Principal (comportamiento de hoy).
        self._lista_id = config.LISTA_PRINCIPAL_ID if lista_id is None else int(lista_id)
        self._cache: dict[str, list] = {}          # codigo -> list[Insumo] candidatos
        self._comp_cache: dict[tuple, list] = {}   # (codigo, shift) -> list[ApuComponent]
        # Memo (codigo, shift) -> costo_unitario, POR INSTANCIA (no global).
        # Supone grafo de sub-APUs ACÍCLICO (los datos reales no tienen ciclos):
        # con un ciclo, el valor cacheado depende del camino de la primera pasada
        # (el borde que cerró el ciclo cayó a histórico). Aceptable porque un ciclo
        # es un error de datos; la guarda de ciclos garantiza terminación igual.
        self._apu_cost_cache: dict[tuple, float] = {}
        # Desviaciones del proyecto (distancias, peaje, ajustes). None = biblioteca
        # tal cual: el costeo es idéntico al de antes de esta feature.
        self._ctx = None if (contexto is None or contexto.vacio) else contexto
        # (apu, shift) -> códigos de acarreo que no se pudieron reescalar; los lee
        # alertas.py para avisar en vez de costear con la distancia equivocada.
        self._sin_distancia: dict[tuple[str, str], tuple[str, ...]] = {}

    @property
    def lista_id(self) -> int:
        """Solo lectura: mutarla con los cachés calientes mezclaría precios de una
        lista con la política de respaldo de otra, dando un total plausible y
        equivocado (una convención no basta; ver hallazgo de la revisión)."""
        return self._lista_id

    def _respalda_con_historico(self) -> bool:
        """Solo la lista Principal usa el precio histórico embebido como respaldo.

        En una lista de obra (NP) ese histórico es una tarifa CONTRACTUAL: usarlo
        sería costear el no previsto con el precio equivocado en silencio. Preferimos
        el $0 con alerta explícita (regla de negocio: nada en $0 pasa desapercibido)."""
        return self._lista_id == config.LISTA_PRINCIPAL_ID

    def _candidatos(self, codigo: str) -> list:
        if not codigo:
            return []
        if codigo not in self._cache:
            # SIEMPRE con el kwarg: en el único módulo que ve dinero, "qué es
            # Principal" lo decide `_lista_id` (normalizado en __init__), no el
            # default del callee. Ver `_precargar_lote`, que ya lo hacía así.
            self._cache[codigo] = self.alm.precios.get_candidatos(
                codigo, lista_id=self._lista_id)
        return self._cache[codigo]

    def sin_distancia(self, apu_codigo: str, shift: str) -> tuple[str, ...]:
        """Componentes de acarreo que el proyecto no pudo reescalar en este APU
        **ni en su árbol de sub-APUs**.

        El árbol importa: la distancia al botadero vive DENTRO del sub-APU de
        escombros, así que un pendiente de ahí tiene que alertar en el ítem que lo
        usa — si no, el ítem se costea con la distancia de la biblioteca y nadie se
        entera. Recorre `_comp_cache`, que ya tiene el árbol del costeo."""
        faltan: list[str] = []
        vistos: set[tuple[str, str]] = set()
        pendiente = [(apu_codigo, shift)]
        while pendiente:
            clave = pendiente.pop()
            if clave in vistos:                  # corta ciclos de sub-APUs
                continue
            vistos.add(clave)
            faltan.extend(self._sin_distancia.get(clave, ()))
            for comp in self._comp_cache.get(clave, ()):
                if (comp.tipo or "insumo") == "apu" and comp.insumo_codigo:
                    pendiente.append((comp.insumo_codigo, comp.ref_shift or comp.shift))
        # dedup preservando el orden de aparición
        return tuple(dict.fromkeys(faltan))

    def claves_cargadas(self) -> list[tuple[str, str]]:
        """(código, turno) de todo lo que hay en el caché de composiciones, incluido
        el cierre de sub-APUs que trajo `precargar`. Lo usa la tabla de impacto para
        recorrer el árbol sin duplicar la BFS. Un APU sin composición (borrado o
        inexistente) no cuenta: no hay árbol que recorrer ahí."""
        return sorted(k for k, comps in self._comp_cache.items() if comps)

    @property
    def contexto(self):
        """Solo lectura: las desviaciones se fijan al construir el motor. Con los
        cachés calientes, cambiarlas mezclaría composiciones de dos proyectos y daría
        un total plausible y equivocado (mismo criterio que `lista_id`)."""
        return self._ctx

    def _efectivos(self, codigo: str, shift: str, crudos: list) -> list:
        """Composición EFECTIVA del proyecto (regla de transporte + ajustes).

        Se aplica ANTES de cachear, así el costeo, el memo de sub-APUs y la
        precarga en lote ven todos la misma composición: un solo camino."""
        if self._ctx is None or not crudos:
            # Sin composición no hay nada que desviar: un ajuste no puede INVENTAR
            # un APU. Si no, un APU borrado de la biblioteca dejaría de caer al
            # respaldo de `_costear_row` y costearía solo lo agregado, en silencio.
            return crudos
        pend = transporte.pendientes(crudos, codigo, shift, self._ctx.params,
                                     self._ctx.clasificacion)
        if pend:
            self._sin_distancia[(codigo, shift)] = pend
        return transporte.aplicar(crudos, codigo, shift, self._ctx.params,
                                  self._ctx.clasificacion, self._ctx.ajustes)

    def components(self, codigo: str, shift: str) -> list:
        """Composición EFECTIVA de un APU, cacheada por (codigo, shift). Si
        `precargar` la trajo en lote, no toca la base."""
        clave = (codigo, shift)
        if clave not in self._comp_cache:
            self._comp_cache[clave] = self._efectivos(
                codigo, shift, self.alm.apus.get_components(codigo, shift))
        return self._comp_cache[clave]

    def precargar(self, claves_top) -> None:
        """Precarga en LOTE la composición del árbol de APUs (claves_top + cierre de
        sub-APUs) y los precios de todos sus insumos, en pocas consultas. Es puramente
        una optimización de I/O: llena los cachés que `components`/`_candidatos` ya usan,
        así el costeo posterior no cambia de resultado, solo evita el N+1 de round-trips.

        FAIL-SAFE: si el prefetch en lote falla por lo que sea (p.ej. un backend sin
        soporte batch), se descartan las cargas parciales y el costeo sigue con las
        consultas individuales (camino probado). Nunca rompe ni cambia el costo."""
        try:
            self._precargar_lote(claves_top)
        except Exception:
            self._comp_cache.clear()
            self._cache.clear()
            self._sin_distancia.clear()

    def _precargar_lote(self, claves_top) -> None:
        pendientes = {(str(c), s) for c, s in claves_top if c}
        while pendientes:
            cargados = self.alm.apus.get_components_bulk(list(pendientes))
            siguientes: set = set()
            for clave in pendientes:
                comps = self._efectivos(clave[0], clave[1], cargados.get(clave, []))
                self._comp_cache[clave] = comps
                for comp in comps:
                    if (comp.tipo or "insumo") == "apu" and comp.insumo_codigo:
                        sub = (comp.insumo_codigo, comp.ref_shift or comp.shift)
                        if sub not in self._comp_cache:
                            siguientes.add(sub)
            pendientes = siguientes
        codigos_ins = {comp.insumo_codigo for comps in self._comp_cache.values()
                       for comp in comps
                       if (comp.tipo or "insumo") != "apu" and comp.insumo_codigo}
        for cod, cands in self.alm.precios.get_candidatos_bulk(
                codigos_ins, lista_id=self._lista_id).items():
            self._cache.setdefault(cod, cands)

    def cost_component(self, comp: ApuComponent, _visitando: tuple = ()) -> CostedComponent:
        if (comp.tipo or "insumo") == "apu":
            return self._cost_subapu(comp, _visitando)
        if self._ctx is not None and transporte.es_peaje(comp):
            valor = self._ctx.params.peaje_valor
            if valor:                      # 0/None => sigue el camino normal del catálogo
                return CostedComponent(
                    insumo_codigo=comp.insumo_codigo, insumo_nombre=comp.insumo_nombre,
                    unidad=comp.unidad, rendimiento=comp.rendimiento,
                    precio_unitario=float(valor), fuente_precio="peaje del proyecto",
                    costo=mul_redondeado(comp.rendimiento, float(valor)),
                    calidad_cruce="exacto", tipo="insumo", ref_shift="")
        r = cruce.resolver(self._candidatos(comp.insumo_codigo), comp.insumo_nombre)
        calidad = r.calidad.value
        if r.insumo is not None and not r.insumo.sin_precio:     # EXACTO o APROXIMADO, con tarifa
            # `not sin_precio` (no `precio > 0`): una tarifa de $0 puesta a propósito
            # (material del cliente) es un DATO, no una ausencia, y debe seguir
            # delatándose por la regla dura del $0 en alertas.py, no confundirse aquí
            # con "no hay fila de precio en esta lista".
            precio, fuente = r.insumo.precio, r.insumo.fuente_precio
        elif r.insumo is not None and self._respalda_con_historico():
            # Encontrado, pero SIN fila de precio en Principal (estado inalcanzable
            # antes de esta feature: insert_insumos/crear_insumo siempre escribían
            # fila en Principal). Seguimos usando el histórico para no dejar el total
            # en $0, pero con una calidad que SÍ alerta.
            precio, fuente, calidad = (
                comp.precio_unitario_hist, "histórico", CALIDAD_SIN_PRECIO_CATALOGO)
        elif self._respalda_con_historico():                    # AMBIGUO/HUERFANO en Principal
            precio, fuente = comp.precio_unitario_hist, "histórico"
        else:                                                   # lista NP: señal, no un número
            precio, fuente, calidad = 0.0, FUENTE_SIN_PRECIO_LISTA, CALIDAD_SIN_PRECIO_LISTA
        costo = mul_redondeado(comp.rendimiento, precio)
        return CostedComponent(
            insumo_codigo=comp.insumo_codigo, insumo_nombre=comp.insumo_nombre,
            unidad=comp.unidad, rendimiento=comp.rendimiento,
            precio_unitario=precio, fuente_precio=fuente, costo=costo,
            calidad_cruce=calidad, tipo="insumo", ref_shift="")

    def _fallback_historico(self, comp: ApuComponent, sub_shift: str, calidad: str) -> CostedComponent:
        """Respaldo de un sub-APU que no se puede costear por su árbol (ciclo o sin
        composición). En Principal usa `comp.precio_unitario_hist`; en una lista NP ese
        histórico es tarifa contractual, así que queda en 0 y lo delata la alerta.
        La `calidad` estructural (ciclo / apu_vacio) se CONSERVA: el problema real no es
        que falte el precio, es que el árbol está mal.

        FUENTE en la rama NP: "sin respaldo", no "sin precio en lista" — un sub-APU
        con ciclo o sin composición no puede tener tarifa en NINGUNA lista, así que
        decir "en lista" sería falso en la columna FUENTE del Excel."""
        if self._respalda_con_historico():
            precio, fuente = comp.precio_unitario_hist, "histórico"
        else:
            precio, fuente = 0.0, FUENTE_SIN_RESPALDO
        return CostedComponent(
            insumo_codigo=comp.insumo_codigo, insumo_nombre=comp.insumo_nombre,
            unidad=comp.unidad, rendimiento=comp.rendimiento,
            precio_unitario=precio, fuente_precio=fuente,
            costo=mul_redondeado(comp.rendimiento, precio), calidad_cruce=calidad,
            tipo="apu", ref_shift=sub_shift)

    def _cost_subapu(self, comp: ApuComponent, visitando: tuple) -> CostedComponent:
        sub_shift = comp.ref_shift or comp.shift
        clave = (comp.insumo_codigo, sub_shift)
        if clave in visitando:                                  # ciclo -> respaldo histórico
            return self._fallback_historico(comp, sub_shift, "ciclo")
        if not self.components(comp.insumo_codigo, sub_shift):   # sub-APU SIN composición -> histórico
            return self._fallback_historico(comp, sub_shift, "apu_vacio")
        unit = self._costo_unitario_apu(comp.insumo_codigo, sub_shift, visitando + (clave,))
        return CostedComponent(
            insumo_codigo=comp.insumo_codigo, insumo_nombre=comp.insumo_nombre,
            unidad=comp.unidad, rendimiento=comp.rendimiento,
            precio_unitario=unit, fuente_precio="APU",
            costo=mul_redondeado(comp.rendimiento, unit), calidad_cruce="apu",
            tipo="apu", ref_shift=sub_shift)

    def _costo_unitario_apu(self, codigo: str, shift: str, visitando: tuple) -> float:
        clave = (codigo, shift)
        if clave in self._apu_cost_cache:                       # memoización por pasada
            return self._apu_cost_cache[clave]
        comps = self.components(codigo, shift)
        total = sum(self.cost_component(c, visitando).costo for c in comps)
        self._apu_cost_cache[clave] = total
        return total

    def cost_components(self, comps: list[ApuComponent],
                        _visitando: tuple = ()) -> tuple[list[CostedComponent], float]:
        costed = [self.cost_component(c, _visitando) for c in comps]
        total = sum(c.costo for c in costed)
        return costed, total

    def cost_apu(self, apu_codigo: str, shift: str) -> tuple[list[CostedComponent], float]:
        comps = self.components(apu_codigo, shift)
        seed = ((apu_codigo, shift),)                           # detecta auto-referencia nivel 1
        costed = [self.cost_component(c, seed) for c in comps]
        return costed, sum(c.costo for c in costed)
