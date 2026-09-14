import { useState, useRef, Fragment } from "react";
import { toast } from "sonner";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Button } from "@/components/ui/button";
import EstadoBadge from "@/components/corrida/EstadoBadge";
import SubApuBadge from "@/components/SubApuBadge";
import BuscadorApu from "@/components/corrida/BuscadorApu";
import CabeceraFiltros from "@/components/corrida/CabeceraFiltros";
import { DialogoAgregarApu } from "@/components/autoria/DialogoAgregarApu";
import { cop, pct } from "@/lib/moneda";
import { etiquetaCalidadCruce } from "@/lib/calidadCruce";
import {
  getItem, confirmar, confirmarLote, borrarLineas, aplicarSugerencias,
  igualarCostoAlContractual,
} from "@/api/corridas";
import { getApuDetalle } from "@/api/autoria";
import type { ItemCuadro, DetalleItem, CorridaDetalle, ApuDetalle } from "@/lib/tipos";
import { VEREDICTO_UI, etiquetaVeredicto, tituloVeredicto } from "@/lib/corridaTabla";
import type { ControlCorridaTabla } from "@/lib/corridaTabla";

interface TablaItemsProps {
  corridaId: number;
  items: ItemCuadro[];
  onConfirmado: (corridaActualizada: CorridaDetalle) => void;
  readOnly?: boolean;
  control?: ControlCorridaTabla;
  /** Rol editor: habilita crear un APU nuevo (duplicar) desde la corrida. */
  puedeEditar?: boolean;
  /** Abre la mesa de composición de esa línea. Es una prop y no un <Link> ni un
   *  useNavigate acá adentro: esta tabla se monta SIN Router en sus tests, y
   *  cualquiera de los dos reventaría con "useHref() may be used only in the
   *  context of a <Router>". Quien navega es la página, que sí está dentro. */
  onComponer?: (seq: number) => void;
}

/** ¿Esta línea puede componerse con IA?
 *
 *  Sin APU (el determinístico no encontró nada), o con el veredicto `sin_apu` de la
 *  revisión sobre una fila que sí tiene APU.
 *
 *  Una fila con el costo igualado al contractual SÍ se puede componer, y es de las
 *  que más lo necesitan: igualar era la salida cuando no había APU. Asignar uno de
 *  verdad borra el costo manual solo (`actualizar_eleccion`) y devuelve la fila al
 *  costeo normal — el sistema ya contempla ese camino. La mesa de composición avisa
 *  ahí (con `costo_a_mano` del expediente) que aprobar reemplaza el costo declarado.
 *
 *  Antes esto exigía haber corrido la revisión con IA sobre TODA la corrida para que
 *  apareciera el botón en una sola fila. */
export function ofreceComponer(it: ItemCuadro, puedeEditar: boolean): boolean {
  if (!puedeEditar) return false;
  return !it.apu_codigo || it.revision?.dictamen === "sin_apu";
}

const REVISABLE = new Set(["review", "new", "REVIEW", "NEW"]);

type EstadoExpansion = DetalleItem | "cargando" | "error";

export default function TablaItems({
  corridaId,
  items,
  onConfirmado,
  readOnly = false,
  control,
  puedeEditar = false,
  onComponer,
}: TablaItemsProps) {
  // Con `control`, el padre ya entrega las filas filtradas/ordenadas y controla
  // "Solo revisión". Sin `control` (modo vivo), se mantiene el filtro local de hoy.
  const [soloRevisionLocal, setSoloRevisionLocal] = useState(false);
  const soloRevision = control ? control.soloRevision : soloRevisionLocal;
  const setSoloRevision = control ? control.setSoloRevision : setSoloRevisionLocal;
  const [expandido, setExpandido] = useState<Record<number, EstadoExpansion | undefined>>({});
  const [confirmando, setConfirmando] = useState<string | null>(null);
  const [errorConfirm, setErrorConfirm] = useState<Record<number, string>>({});
  // Duplicar el APU de un ítem: se lee el APU real de la biblioteca (la composición
  // del ítem es la costeada y no trae las marcas de sub-APU).
  const [duplicar, setDuplicar] = useState<{ seq: number; origen: ApuDetalle } | null>(null);
  // `seq` cuyo fetch de "abrir duplicar" está en vuelo, para deshabilitar SU botón.
  // Es un escalar: solo frena el doble click en la MISMA fila. Para la carrera
  // entre filas distintas (pedir duplicar en A y luego en B antes de que A
  // resuelva) hace falta saber cuál fue el ÚLTIMO pedido, y eso no puede vivir
  // en el estado: la closure async de `abrirDuplicar` vería el valor viejo (ya
  // pasó con `codigoTocado` en este mismo archivo/feature). Por eso el pedido
  // más reciente vive en un ref.
  const [cargandoDuplicar, setCargandoDuplicar] = useState<number | null>(null);
  const ultimoPedidoDuplicarRef = useRef<number | null>(null);
  // Selección para las acciones en lote. Guarda seqs, no índices: la tabla se
  // reordena y se filtra, y un índice dejaría de apuntar a la misma fila.
  const [marcadas, setMarcadas] = useState<Set<number>>(new Set());
  // Ancla del rango: guarda el SEQ, no el índice. Si el usuario cambia el filtro o
  // el orden entre el click y el Shift+click, el índice viejo apuntaría a otra fila;
  // el seq se resuelve contra el `visible` del momento.
  const anclaSeqRef = useRef<number | null>(null);

  const nPorRevisar = items.filter((it) => REVISABLE.has(it.status)).length;
  const visible = control
    ? items
    : soloRevision
      ? items.filter((it) => REVISABLE.has(it.status))
      : items;

  // Solo se actúa sobre lo que se está viendo: si el usuario marca filas y después
  // cambia el filtro, las que se fueron no se tocan (y el contador no las cuenta).
  const seleccionadas = visible.filter((it) => marcadas.has(it.seq)).map((it) => it.seq);
  const haySeleccion = seleccionadas.length > 0;
  // La selección solo existe con `control` (no en el armado en vivo, cuya tabla
  // viene del stream) y con la corrida activa.
  const seleccionable = control !== undefined && !readOnly;
  // Mismo permiso que duplicar: rol editor y corrida no congelada.
  const puedeAplicarIA = puedeEditar && !readOnly;
  // Sin una sola fila revisada la columna Veredicto estaría entera vacía, y una
  // columna vacía igual empuja el scroll horizontal: no se dibuja.
  const hayVeredicto = items.some((it) => it.revision);
  // Corrida plana: ni columna ni filtro de capítulo. La tabla queda EXACTAMENTE como
  // estaba, que es lo que mantiene verdes los tests viejos de esta pantalla.
  const hayCapitulo = items.some((it) => it.capitulo_codigo);
  // Misma razón que `hayVeredicto`: sin una sola fila que ofrezca componer la
  // columna quedaría entera vacía y aun así empujaría el scroll horizontal.
  const hayAcciones = onComponer !== undefined
    && items.some((it) => ofreceComponer(it, puedeAplicarIA));

  function alternar(idx: number, seq: number, conShift: boolean) {
    const desde = anclaSeqRef.current === null
      ? -1
      : visible.findIndex((it) => it.seq === anclaSeqRef.current);
    if (conShift && desde >= 0) {
      const [a, b] = desde <= idx ? [desde, idx] : [idx, desde];
      const rango = visible.slice(a, b + 1).map((it) => it.seq);
      setMarcadas((prev) => new Set([...prev, ...rango]));
      return;                                  // el ancla del rango no se mueve
    }
    anclaSeqRef.current = seq;
    setMarcadas((prev) => {
      const s = new Set(prev);
      if (s.has(seq)) s.delete(seq); else s.add(seq);
      return s;
    });
  }

  function marcarTodas(marcar: boolean) {
    anclaSeqRef.current = null;
    setMarcadas((prev) => {
      const s = new Set(prev);
      for (const it of visible) { if (marcar) s.add(it.seq); else s.delete(it.seq); }
      return s;
    });
  }

  function limpiarSeleccion() {
    anclaSeqRef.current = null;
    setMarcadas(new Set());
  }

  async function toggleExpand(seq: number) {
    const actual = expandido[seq];

    if (actual !== undefined) {
      // Colapsar
      setExpandido((prev) => ({ ...prev, [seq]: undefined }));
      return;
    }

    // Primer despliegue: lazy fetch
    setExpandido((prev) => ({ ...prev, [seq]: "cargando" }));
    try {
      const detalle = await getItem(corridaId, seq);
      setExpandido((prev) => ({ ...prev, [seq]: detalle }));
    } catch {
      setExpandido((prev) => ({ ...prev, [seq]: "error" }));
    }
  }

  /** Devuelve true si el ítem quedó reasignado. Los llamadores que no lo necesiten
   *  pueden ignorar el valor (el tipo de `onConfirmar` declara `void`). */
  async function handleConfirmar(
    seq: number,
    apuCodigo: string,
    shift?: string,
  ): Promise<boolean> {
    setConfirmando(apuCodigo + "@" + seq);
    setErrorConfirm((prev) => ({ ...prev, [seq]: "" }));
    try {
      const corridaActualizada = await confirmar(corridaId, seq, apuCodigo, shift);
      // Colapsar la fila y refrescar el detalle para mostrar nuevo estado
      setExpandido((prev) => ({ ...prev, [seq]: undefined }));
      onConfirmado(corridaActualizada);
      return true;
    } catch (err) {
      setErrorConfirm((prev) => ({
        ...prev,
        [seq]: err instanceof Error ? err.message : "Error al confirmar",
      }));
      return false;
    } finally {
      setConfirmando(null);
    }
  }

  const [enLote, setEnLote] = useState(false);
  // `seq` de la fila cuya sugerencia de la IA se está aplicando (null = ninguna).
  const [aplicandoIA, setAplicandoIA] = useState<number | null>(null);

  /** Asigna un APU a UNA fila y propaga la corrida recosteada. Devuelve si salió
   *  bien: el llamador que ACABA de crear el APU necesita decir algo más si el
   *  APU quedó creado pero sin asignar. */
  async function asignarA(
    it: ItemCuadro, codigo: string, turno?: string | null,
  ): Promise<boolean> {
    setAplicandoIA(it.seq);
    try {
      const actualizada = await aplicarSugerencias(corridaId, [{
        seq: it.seq,
        apu_codigo: codigo,
        ...(turno ? { shift: turno } : {}),
      }]);
      onConfirmado(actualizada);
      toast.success(`${codigo} asignado al ítem ${it.item}`);
      return true;
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "No se pudo aplicar la sugerencia.");
      return false;
    } finally {
      setAplicandoIA(null);
    }
  }

  /** Aplica el APU que sugirió la IA para ESA fila. La IA propone; acá aplica el
   *  usuario. Reusa el mismo callback de recosteo que la reasignación normal. */
  async function aplicarSugerencia(it: ItemCuadro) {
    const v = it.revision;
    if (!v || v.dictamen !== "cambiar" || !v.apu_sugerido) return;
    await asignarA(it, v.apu_sugerido, v.turno_sugerido);
  }

  /** `apu` undefined = confirmar el APU que cada línea ya tiene. */
  async function accionLote(apu?: { codigo: string; turno: string }) {
    // Sin APU explícito, las filas sin APU no tienen nada que confirmar, y las que
    // tienen costo a mano lo PERDERÍAN (el backend borra costo_manual en cualquier
    // confirm). Se filtran acá para no mandarle al backend seqs que arruinarían la
    // fila sin que el usuario lo haya pedido.
    const objetivo = apu
      ? seleccionadas
      : visible
          .filter((it) => marcadas.has(it.seq) && it.apu_codigo && !it.costo_manual)
          .map((it) => it.seq);
    if (objetivo.length === 0) {
      toast.error("Ninguna de las líneas marcadas tiene APU para confirmar (o todas tienen costo puesto a mano).");
      return;
    }
    setEnLote(true);
    try {
      // `confirmarLote` ya trata un apu_codigo/shift ausente igual que uno explícito
      // en `undefined` (arma el mismo cuerpo del POST), así que no pasarlos cuando no
      // hay APU no cambia el pedido — solo deja la llamada más clara.
      const actualizada = apu
        ? await confirmarLote(corridaId, objetivo, apu.codigo, apu.turno)
        : await confirmarLote(corridaId, objetivo);
      onConfirmado(actualizada);
      limpiarSeleccion();
      const n = objetivo.length;
      toast.success(apu
        ? `${apu.codigo} asignado a ${n} ${n === 1 ? "línea" : "líneas"}`
        : `${n} ${n === 1 ? "línea confirmada" : "líneas confirmadas"}`);
    } catch (e) {
      // La selección NO se limpia: el usuario puede reintentar sin volver a marcar.
      toast.error(e instanceof Error ? e.message : "No se pudo aplicar el cambio en lote.");
    } finally {
      setEnLote(false);
    }
  }

  /** Copia el contractual como costo en las filas marcadas (proyectos especiales). */
  async function igualarAlContractual() {
    if (seleccionadas.length === 0) return;
    setEnLote(true);
    try {
      const actualizada = await igualarCostoAlContractual(corridaId, seleccionadas);
      onConfirmado(actualizada);
      limpiarSeleccion();
      const n = actualizada.igualadas?.length ?? seleccionadas.length;
      const rechazadas = actualizada.rechazadas ?? [];
      toast.success(`${n} ${n === 1 ? "línea igualada" : "líneas igualadas"} al contractual`);
      if (rechazadas.length > 0) {
        // Nada silencioso: si no se tocó una fila, se dice por qué. `seq` es una
        // clave interna; se nombra por `item` (la columna que el usuario sí ve).
        const etiquetas = rechazadas.map((s) => {
          const it = items.find((x) => x.seq === s);
          return it ? it.item : `#${s}`;
        });
        toast.error(`Sin tocar por contractual en $0: ${etiquetas.join(", ")}`);
      }
    } catch (e) {
      // La selección NO se limpia: el usuario puede reintentar sin volver a marcar.
      toast.error(e instanceof Error ? e.message : "No se pudo igualar el costo.");
    } finally {
      setEnLote(false);
    }
  }

  /** Borrar es destructivo y no se deshace: se pregunta antes (igual que borrar
   *  una corrida en Mis corridas). */
  async function borrarSeleccionadas() {
    const n = seleccionadas.length;
    if (n === 0) return;
    const mensaje = n === 1
      ? "¿Borrar 1 línea de la corrida? No se puede deshacer."
      : `¿Borrar ${n} líneas de la corrida? No se puede deshacer.`;
    if (!window.confirm(mensaje)) return;
    setEnLote(true);
    try {
      const actualizada = await borrarLineas(corridaId, seleccionadas);
      onConfirmado(actualizada);
      limpiarSeleccion();
      toast.success(n === 1 ? "1 línea borrada" : `${n} líneas borradas`);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "No se pudo borrar las líneas.");
    } finally {
      setEnLote(false);
    }
  }

  async function abrirDuplicar(seq: number, codigo: string, turno: string) {
    ultimoPedidoDuplicarRef.current = seq;
    setCargandoDuplicar(seq);
    try {
      const origen = await getApuDetalle(codigo, turno);
      // Si mientras esperábamos el usuario pidió duplicar otra fila, este
      // resultado ya quedó superado: no lo mostramos (ganaría el pedido viejo).
      if (ultimoPedidoDuplicarRef.current !== seq) return;
      setDuplicar({ seq, origen });
    } catch {
      if (ultimoPedidoDuplicarRef.current !== seq) return;
      toast.error("No se pudo leer el APU de origen.");
    } finally {
      setCargandoDuplicar(null);
    }
  }

  async function duplicado(seq: number, codigo: string, turno: string) {
    setDuplicar(null);
    // El APU YA está creado. El diálogo ya confirmó la creación con su propio
    // toast; si la reasignación falla, hay que decirlo (no alcanza con el
    // silencio, que sugeriría que no pasó nada).
    const ok = await handleConfirmar(seq, codigo, turno);
    if (!ok) {
      toast.error(
        `APU ${codigo} creado; no se pudo asignar al ítem — asignalo con Cambiar APU.`,
      );
    }
  }

  // 1 chevron + 12 columnas de datos, más Capítulo cuando la corrida vino de un
  // presupuesto, Veredicto cuando hay alguno, Acciones cuando alguna fila ofrece
  // componer, y la de selección cuando está activa. Se mira `items` (no `visible`):
  // así la cabecera y el colSpan de las filas expandidas/vacías salen SIEMPRE del
  // mismo dato.
  const TOTAL_COLS =
    13 + (hayCapitulo ? 1 : 0) + (hayVeredicto ? 1 : 0) + (hayAcciones ? 1 : 0)
    + (seleccionable ? 1 : 0);

  return (
    <div className="flex flex-col gap-2">
      {/* Filter bar */}
      <div className="flex items-center gap-3 px-1">
        <label className="flex items-center gap-1.5 cursor-pointer select-none text-xs text-muted-foreground">
          <input
            type="checkbox"
            checked={soloRevision}
            onChange={(e) => setSoloRevision(e.target.checked)}
            className="cursor-pointer"
          />
          Solo revisión
        </label>
        {nPorRevisar > 0 && (
          <span className="rounded-full bg-amber-100 px-2 py-0.5 text-[10px] font-semibold text-amber-800">
            {nPorRevisar} por revisar
          </span>
        )}
        {control?.hayFiltros && (
          <button
            type="button"
            onClick={control.limpiar}
            className="text-[11px] text-muted-foreground underline underline-offset-2 hover:text-foreground"
          >
            Limpiar filtros
          </button>
        )}
        {seleccionable && (
          <label className="flex items-center gap-1.5 cursor-pointer select-none text-xs text-muted-foreground">
            <input
              type="checkbox"
              className="cursor-pointer"
              aria-label="Marcar todas las líneas visibles"
              checked={visible.length > 0 && seleccionadas.length === visible.length}
              onChange={(e) => marcarTodas(e.target.checked)}
            />
            Marcar todas
          </label>
        )}
        {haySeleccion && (
          <span className="text-xs font-medium text-foreground">
            {seleccionadas.length === 1
              ? "1 línea marcada"
              : `${seleccionadas.length} líneas marcadas`}
          </span>
        )}
      </div>

      {/* Dense table */}
      <Table>
        {control ? (
          <CabeceraFiltros control={control} conSeleccion={seleccionable}
                           conVeredicto={hayVeredicto} conCapitulo={hayCapitulo}
                           conAcciones={hayAcciones} />
        ) : (
          <TableHeader>
            <TableRow>
              <TableHead className="w-6 px-1" />
              <TableHead className="text-xs">Descripción</TableHead>
              <TableHead className="text-xs w-12">Und</TableHead>
              <TableHead className="text-xs w-20 text-right">Cantidad</TableHead>
              <TableHead className="text-xs w-24">Ítem</TableHead>
              {hayCapitulo && <TableHead className="text-xs w-32">Capítulo</TableHead>}
              <TableHead className="text-xs w-28">APU</TableHead>
              <TableHead className="text-xs w-20">Estado</TableHead>
              {hayVeredicto && <TableHead className="text-xs w-28">Veredicto</TableHead>}
              <TableHead className="text-xs w-28 text-right">Unit. Contractual</TableHead>
              <TableHead className="text-xs w-28 text-right">Unit. Costo</TableHead>
              <TableHead className="text-xs w-28 text-right">Total Contractual</TableHead>
              <TableHead className="text-xs w-28 text-right">Total Costo</TableHead>
              <TableHead className="text-xs w-28 text-right">Margen</TableHead>
              <TableHead className="text-xs w-16 text-right">%</TableHead>
              {hayAcciones && <TableHead className="text-xs w-24">Acciones</TableHead>}
            </TableRow>
          </TableHeader>
        )}
        <TableBody>
          {visible.map((it, idx) => {
            const estado = expandido[it.seq];
            const abierto = estado !== undefined;

            return (
              <Fragment key={it.seq}>
                <TableRow className="hover:bg-muted/40">
                  {seleccionable && (
                    <TableCell className="w-8 px-1 py-1">
                      <input
                        type="checkbox"
                        className="cursor-pointer"
                        aria-label={`Marcar ítem ${it.item}`}
                        checked={marcadas.has(it.seq)}
                        onChange={() => {}}
                        onClick={(e) => alternar(idx, it.seq, e.shiftKey)}
                      />
                    </TableCell>
                  )}
                  {/* Chevron control */}
                  <TableCell className="w-6 px-1 py-1">
                    <button
                      type="button"
                      aria-label={abierto ? "Colapsar fila" : "Expandir fila"}
                      onClick={() => toggleExpand(it.seq)}
                      className="flex items-center justify-center w-5 h-5 rounded hover:bg-muted text-muted-foreground hover:text-foreground transition-colors"
                    >
                      <svg
                        xmlns="http://www.w3.org/2000/svg"
                        viewBox="0 0 16 16"
                        fill="currentColor"
                        className={`w-3 h-3 transition-transform ${abierto ? "rotate-90" : ""}`}
                      >
                        <path
                          fillRule="evenodd"
                          d="M6.22 4.22a.75.75 0 0 1 1.06 0l3.25 3.25a.75.75 0 0 1 0 1.06l-3.25 3.25a.75.75 0 0 1-1.06-1.06L9.19 8 6.22 5.03a.75.75 0 0 1 0-1.06Z"
                          clipRule="evenodd"
                        />
                      </svg>
                    </button>
                  </TableCell>
                  <TableCell className="text-xs max-w-[240px] truncate">
                    {it.descripcion}
                  </TableCell>
                  <TableCell className="text-xs">{it.unidad}</TableCell>
                  <TableCell className="text-xs text-right font-mono">
                    {it.cantidad.toLocaleString("es-CO")}
                  </TableCell>
                  <TableCell className="text-xs font-mono">{it.item}</TableCell>
                  {hayCapitulo && (
                    <TableCell className="text-[11px]">
                      {it.capitulo_codigo &&
                        `${it.capitulo_codigo} · ${it.capitulo_nombre}`}
                    </TableCell>
                  )}
                  <TableCell className="text-xs font-mono text-muted-foreground">
                    {it.apu_codigo}
                  </TableCell>
                  <TableCell className="text-xs">
                    <EstadoBadge status={it.status} costoManual={it.costo_manual} />
                  </TableCell>
                  {hayVeredicto && (
                    <TableCell className="text-xs">
                      <CeldaVeredicto
                        item={it}
                        puedeAplicar={puedeAplicarIA}
                        aplicando={aplicandoIA === it.seq}
                        bloqueado={aplicandoIA !== null}
                        onAplicar={() => aplicarSugerencia(it)}
                      />
                    </TableCell>
                  )}
                  <TableCell className="text-xs text-right font-mono tabular-nums">
                    {cop(it.precio_contractual)}
                  </TableCell>
                  <TableCell className="text-xs text-right font-mono tabular-nums">
                    {cop(it.costo_unitario)}
                    {it.costo_manual && (
                      <span className="ml-1 rounded bg-muted px-1 text-[10px] font-sans
                                       font-medium text-muted-foreground"
                            title="Costo puesto a mano (igualado al contractual)">
                        a mano
                      </span>
                    )}
                  </TableCell>
                  <TableCell className="text-xs text-right font-mono tabular-nums">
                    {cop(it.contractual_total)}
                  </TableCell>
                  <TableCell className="text-xs text-right font-mono tabular-nums">
                    {cop(it.costo_total)}
                  </TableCell>
                  <TableCell className="text-xs text-right font-mono tabular-nums">
                    {cop(it.margen_total)}
                  </TableCell>
                  <TableCell className="text-xs text-right font-mono tabular-nums">
                    {pct(it.margen_pct)}
                  </TableCell>
                  {hayAcciones && (
                    <TableCell className="text-xs">
                      {ofreceComponer(it, puedeAplicarIA) && (
                        <Button
                          size="xs"
                          variant="outline"
                          title="Abrir la mesa de composición con IA de esta actividad (no crea nada)"
                          onClick={() => onComponer?.(it.seq)}
                        >
                          Componer
                        </Button>
                      )}
                    </TableCell>
                  )}
                </TableRow>

                {/* Inline expansion row */}
                {abierto && (
                  <TableRow key={`expand-${it.seq}`} className="bg-muted/20 hover:bg-muted/20">
                    <TableCell colSpan={TOTAL_COLS} className="px-8 py-3">
                      {estado === "cargando" && (
                        <p className="text-xs text-muted-foreground py-2">
                          cargando…
                        </p>
                      )}
                      {estado === "error" && (
                        <p className="text-xs text-destructive py-2">
                          Error al cargar el detalle.
                        </p>
                      )}
                      {estado !== "cargando" && estado !== "error" && (
                        <DetalleExpandido
                          detalle={estado}
                          seq={it.seq}
                          confirmando={confirmando}
                          errorConfirm={errorConfirm[it.seq]}
                          onConfirmar={handleConfirmar}
                          readOnly={readOnly}
                          puedeDuplicar={puedeEditar && !readOnly}
                          duplicarCargando={cargandoDuplicar === it.seq}
                          onDuplicar={abrirDuplicar}
                        />
                      )}
                    </TableCell>
                  </TableRow>
                )}
              </Fragment>
            );
          })}
          {visible.length === 0 && (
            <TableRow>
              <TableCell
                colSpan={TOTAL_COLS}
                className="text-center text-xs text-muted-foreground py-6"
              >
                No hay ítems{soloRevision ? " por revisar" : ""}.
              </TableCell>
            </TableRow>
          )}
        </TableBody>
      </Table>

      {seleccionable && haySeleccion && (
        <div className="sticky bottom-0 z-10 flex flex-wrap items-center gap-2 border-t bg-background/95 px-2 py-2 backdrop-blur">
          <span className="text-xs font-medium">
            {seleccionadas.length} {seleccionadas.length === 1 ? "línea" : "líneas"}
          </span>
          <div className="min-w-[220px] flex-1">
            <BuscadorApu
              disabled={enLote}
              onElegir={(apu) => accionLote({ codigo: apu.codigo, turno: apu.turno })}
            />
          </div>
          <Button size="xs" variant="outline" disabled={enLote} onClick={() => accionLote()}>
            {enLote ? "Aplicando…" : "Confirmar el APU actual"}
          </Button>
          {puedeEditar && (
            <Button size="xs" variant="outline" disabled={enLote}
                    onClick={igualarAlContractual}
                    title="Copia el precio contractual como costo. Para actividades globales que valen lo que dice el contrato.">
              {enLote ? "Aplicando…" : "Igualar costo al contractual"}
            </Button>
          )}
          <Button size="xs" variant="destructive" disabled={enLote}
                  onClick={borrarSeleccionadas}>
            Borrar
          </Button>
          <Button size="xs" variant="ghost" disabled={enLote} onClick={limpiarSeleccion}>
            Limpiar
          </Button>
        </div>
      )}

      {duplicar && (
        <DialogoAgregarApu
          key={`dup-${duplicar.origen.codigo}@@${duplicar.origen.turno}@@${duplicar.seq}`}
          open
          onOpenChange={(v) => { if (!v) setDuplicar(null); }}
          onCreado={(codigo, turno) => duplicado(duplicar.seq, codigo, turno)}
          modo="duplicar"
          inicial={duplicar.origen}
        />
      )}

    </div>
  );
}

// ─── celda del veredicto de la IA ────────────────────────────────────────────
// La IA propone; quien aplica es el usuario. El botón se decide por el DICTAMEN
// (nunca por "hay apu_sugerido"): que el backend solo deje sobrevivir un código
// con dictamen `cambiar` es garantía suya, no algo de lo que dependa la interfaz.

function CeldaVeredicto({
  item, puedeAplicar, aplicando, bloqueado, onAplicar,
}: {
  item: ItemCuadro;
  puedeAplicar: boolean;
  aplicando: boolean;
  bloqueado: boolean;
  onAplicar: () => void;
}) {
  const v = item.revision;
  // Sin veredicto. NO se puede distinguir "la IA no contestó esta fila" de "esta
  // fila nunca se revisó": las dos llegan como `revision: null` y el backend no
  // guarda las no contestadas (a propósito: un "no contestada" persistido sería un
  // 5º dictamen). Así que el texto del title dice las dos posibilidades en vez de
  // afirmar una. Cuántas quedaron sin contestar lo dice el aviso final de la
  // revisión, y encontrarlas es el filtro "— sin revisar" de esta columna.
  if (!v) {
    return (
      <span className="text-muted-foreground"
        title="Sin veredicto: la IA no contestó esta fila, o la fila no se ha revisado.">
        &mdash;
      </span>
    );
  }
  const ofreceAplicar = puedeAplicar && v.dictamen === "cambiar" && !!v.apu_sugerido;
  // Componer NO vive acá: dejó de depender de que haya veredicto y se ofrece desde
  // la columna Acciones de cualquier fila sin APU (ver `ofreceComponer`).
  return (
    <span className="inline-flex items-center gap-1">
      <span
        className={`whitespace-nowrap font-medium ${VEREDICTO_UI[v.dictamen]?.cls ?? ""}`}
        title={tituloVeredicto(v)}
      >
        {etiquetaVeredicto(v.dictamen)}
      </span>
      {ofreceAplicar && (
        <Button
          size="xs"
          variant="outline"
          disabled={bloqueado}
          title={`Asignar ${v.apu_sugerido} a este ítem`}
          onClick={onAplicar}
        >
          {aplicando ? "Aplicando…" : "Aplicar"}
        </Button>
      )}
    </span>
  );
}

// ─── inline expand content ────────────────────────────────────────────────────

interface DetalleExpandidoProps {
  detalle: DetalleItem;
  seq: number;
  confirmando: string | null;
  errorConfirm: string | undefined;
  onConfirmar: (seq: number, apuCodigo: string, shift?: string) => void;
  readOnly: boolean;
  puedeDuplicar: boolean;
  /** El fetch de "abrir duplicar" de ESTE ítem está en vuelo: deshabilita su botón. */
  duplicarCargando: boolean;
  onDuplicar: (seq: number, codigo: string, turno: string) => void;
}

function DetalleExpandido({
  detalle,
  seq,
  confirmando,
  errorConfirm,
  onConfirmar,
  readOnly,
  puedeDuplicar,
  duplicarCargando,
  onDuplicar,
}: DetalleExpandidoProps) {
  const esRevisable = REVISABLE.has(detalle.status);

  return (
    <div className="flex flex-col gap-3">
      {/* APU header */}
      <div className="flex items-center gap-3 flex-wrap text-xs">
        <EstadoBadge status={detalle.status} costoManual={detalle.costo_manual} />
        <span className="font-mono text-muted-foreground">APU: {detalle.apu_codigo}</span>
        <span className="text-muted-foreground truncate max-w-xs">{detalle.apu_nombre}</span>
      </div>

      {/* Explicacion (review/new) */}
      {detalle.explicacion && (
        <p className="text-xs text-muted-foreground italic border-l-2 border-muted pl-2">
          {detalle.explicacion}
        </p>
      )}

      {/* Candidates (review/new only) */}
      {detalle.candidatos.length > 0 && (
        <section>
          <h4 className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground mb-1">
            Candidatos
          </h4>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="text-xs">Código</TableHead>
                <TableHead className="text-xs">Nombre</TableHead>
                <TableHead className="text-xs w-14 text-right">Score</TableHead>
                <TableHead className="text-xs">Motivo</TableHead>
                <TableHead className="text-xs w-24" />
              </TableRow>
            </TableHeader>
            <TableBody>
              {detalle.candidatos.map((c) => (
                <TableRow key={c.apu_codigo}>
                  <TableCell className="text-xs font-mono">{c.apu_codigo}</TableCell>
                  <TableCell className="text-xs max-w-[200px] truncate">
                    {c.apu_nombre}
                  </TableCell>
                  <TableCell className="text-xs text-right font-mono">
                    {(c.score * 100).toFixed(0)}%
                  </TableCell>
                  <TableCell className="text-xs text-muted-foreground max-w-[160px] truncate">
                    {c.motivo}
                  </TableCell>
                  <TableCell className="text-xs">
                    <Button
                      size="xs"
                      variant={c.apu_codigo === detalle.apu_codigo ? "default" : "outline"}
                      disabled={confirmando !== null || readOnly}
                      onClick={() => onConfirmar(seq, c.apu_codigo)}
                    >
                      {confirmando === c.apu_codigo + "@" + seq
                        ? "Confirmando…"
                        : "Elegir"}
                    </Button>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </section>
      )}

      {/* Reasignar a cualquier APU de la biblioteca (todos los ítems) */}
      {readOnly && (
        <p className="text-xs text-muted-foreground italic">
          Corrida congelada (solo lectura). Activá la corrida para modificar.
        </p>
      )}
      {!readOnly && (
        <section>
          <h4 className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground mb-1">
            Cambiar APU
          </h4>
          <BuscadorApu
            disabled={confirmando !== null || readOnly}
            onElegir={(apu) => onConfirmar(seq, apu.codigo, apu.turno)}
          />
          {puedeDuplicar && detalle.apu_codigo && (
            <div className="mt-2">
              <Button
                size="xs"
                variant="outline"
                disabled={confirmando !== null || duplicarCargando}
                onClick={() => onDuplicar(seq, detalle.apu_codigo, detalle.apu_turno)}
              >
                {duplicarCargando ? "Abriendo…" : "Duplicar este APU y usarlo aquí"}
              </Button>
            </div>
          )}
        </section>
      )}

      {errorConfirm && (
        <p className="text-xs text-destructive">{errorConfirm}</p>
      )}

      {detalle.composicion.length === 0 && detalle.costo_manual && (
        <section>
          <h4 className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground mb-1">
            Costo puesto a mano &mdash; costo unitario{" "}
            <span className="font-mono">{cop(detalle.costo_unitario)}</span>
          </h4>
          <p className="text-xs text-muted-foreground">
            Igualado al precio contractual. Asignale un APU para volver al costeo normal.
          </p>
        </section>
      )}

      {/* Composition table */}
      {detalle.composicion.length > 0 && (
        <section>
          <h4 className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground mb-1">
            Composición costeada &mdash; costo unitario{" "}
            <span className="font-mono">{cop(detalle.costo_unitario)}</span>
          </h4>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="text-xs">Insumo</TableHead>
                <TableHead className="text-xs w-12">Und</TableHead>
                <TableHead className="text-xs w-16 text-right">Rend.</TableHead>
                <TableHead className="text-xs w-24 text-right">Precio</TableHead>
                <TableHead className="text-xs w-24 text-right">Costo</TableHead>
                <TableHead className="text-xs w-16">Cruce</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {detalle.composicion.map((lin, i) => (
                <TableRow key={i}>
                  <TableCell className="text-xs max-w-[200px] truncate">
                    {lin.insumo_nombre}
                  </TableCell>
                  <TableCell className="text-xs">{lin.unidad}</TableCell>
                  <TableCell className="text-xs text-right font-mono tabular-nums">
                    {lin.rendimiento.toLocaleString("es-CO", {
                      maximumFractionDigits: 4,
                    })}
                  </TableCell>
                  <TableCell className="text-xs text-right font-mono tabular-nums">
                    {cop(lin.precio_unitario)}
                  </TableCell>
                  <TableCell className="text-xs text-right font-mono tabular-nums">
                    {cop(lin.costo)}
                  </TableCell>
                  <TableCell className="text-xs text-muted-foreground">
                    {/* usa calidad_cruce (no tipo): tipo no viaja en la corrida ni sobrevive el snapshot congelado */}
                    {lin.calidad_cruce === "apu"
                      ? <SubApuBadge />
                      : etiquetaCalidadCruce(lin.calidad_cruce)}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </section>
      )}

      {/* Confirm current APU (review/new) */}
      {esRevisable && (
        <div className="flex items-center justify-between gap-2 pt-1">
          <div className="ml-auto">
            <Button
              size="sm"
              disabled={confirmando !== null || readOnly}
              onClick={() => onConfirmar(seq, detalle.apu_codigo)}
            >
              {confirmando === detalle.apu_codigo + "@" + seq
                ? "Confirmando…"
                : `Confirmar APU actual (${detalle.apu_codigo})`}
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
