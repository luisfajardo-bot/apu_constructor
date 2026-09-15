import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { crearCorrida, crearSample, corridaEnCurso, previsualizarCorrida }
  from "@/api/corridas";
import { listarCarpetas, crearCarpeta } from "@/api/carpetas";
import { listarListas } from "@/api/listas";
import PreviaIdu from "@/components/corrida/PreviaIdu";
import { ENTIDADES, LISTA_PRINCIPAL_ID, type CarpetaNodo, type Entidad,
  type ListaPrecios, type PreviaPresupuesto } from "@/lib/tipos";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

export default function CorridasInicio() {
  const navigate = useNavigate();
  const fileRef = useRef<HTMLInputElement>(null);
  const [cargando, setCargando] = useState(false);
  // Gemelo de `cargando` en un ref porque el candado tiene que valer YA, no en el
  // próximo render: un Enter sostenido (o un doble clic rápido) dispara dos submits
  // antes de que React vuelva a pintar, y los dos leerían `cargando === false`.
  // Antes esto no se notaba porque el botón tardaba HORAS en volver; ahora vuelve al
  // instante y el segundo envío encolaría otro armado del mismo Excel.
  const enVuelo = useRef(false);
  const [nombre, setNombre] = useState("");
  const [nombreTocado, setNombreTocado] = useState(false);

  // La entidad decide qué lector usa el backend y si hay que confirmar la estructura.
  const [entidad, setEntidad] = useState<Entidad>("NO_IDENTIFICADA");
  // La previa vive ACÁ, no en el servidor: el archivo sigue en el <input> y se reenvía
  // al aprobar. Sin borrador que expirar, y sin corrida a medio crear si cierran la
  // pestaña. Por eso "Cancelar" solo tiene que poner esto en null.
  const [previa, setPrevia] = useState<PreviaPresupuesto | null>(null);
  const requiereConfirmacion = entidad === "IDU";

  // Carpetas
  const [carpetas, setCarpetas] = useState<CarpetaNodo[]>([]);
  const [nivel1Id, setNivel1Id] = useState<number | null>(null);
  const [nivel2Id, setNivel2Id] = useState<number | null>(null);

  // Lista de precios: se fija al crear la corrida y ya no se puede cambiar
  // después, así que este formulario es el único momento de acertar.
  const [listaId, setListaId] = useState<number>(LISTA_PRINCIPAL_ID);
  const [listas, setListas] = useState<ListaPrecios[]>([]);

  useEffect(() => {
    listarListas().then(setListas).catch(() => {});
  }, []);

  const carpetaDestino: number | null =
    nivel2Id !== null ? nivel2Id : nivel1Id !== null ? nivel1Id : null;

  async function cargarCarpetas(): Promise<CarpetaNodo[]> {
    const arbol = await listarCarpetas();
    setCarpetas(arbol);
    return arbol;
  }

  useEffect(() => {
    cargarCarpetas().catch(() => {
      toast.error("No se pudieron cargar las carpetas");
    });
  }, []);

  const hijas: CarpetaNodo[] =
    nivel1Id !== null
      ? (carpetas.find((c) => c.id === nivel1Id)?.hijas ?? [])
      : [];

  function handleNivel1Change(e: React.ChangeEvent<HTMLSelectElement>) {
    const val = e.target.value;
    setNivel1Id(val ? Number(val) : null);
    setNivel2Id(null);
  }

  function handleNivel2Change(e: React.ChangeEvent<HTMLSelectElement>) {
    const val = e.target.value;
    setNivel2Id(val ? Number(val) : null);
  }

  async function handleCrearCarpeta() {
    const nombre = window.prompt(
      nivel1Id !== null
        ? "Nombre de la nueva subcarpeta"
        : "Nombre de la nueva carpeta"
    );
    if (!nombre || !nombre.trim()) return;
    try {
      const nueva = await crearCarpeta(nombre.trim(), nivel1Id);
      const arbol = await cargarCarpetas();
      // Auto-select the new folder as destination
      if (nivel1Id !== null) {
        // Created a subfolder under the current level-1
        setNivel2Id(nueva.id);
      } else {
        // Created a new level-1 folder; select it
        const nodo = arbol.find((c) => c.id === nueva.id);
        if (nodo) {
          setNivel1Id(nueva.id);
          setNivel2Id(null);
        }
      }
    } catch {
      toast.error("No se pudo crear la carpeta");
    }
  }

  function stripExt(name: string): string {
    const i = name.lastIndexOf(".");
    return (i > 0 ? name.slice(0, i) : name).trim();
  }

  function handleArchivoChange(e: React.ChangeEvent<HTMLInputElement>) {
    const f = e.target.files?.[0];
    setPrevia(null);   // otro archivo: la previa vieja ya no describe nada
    if (f && !nombreTocado) setNombre(stripExt(f.name));
  }

  /** Encola y navega. Todo lo que crea corridas pasa por acá para que el candado
   *  contra el doble envío y el rescate del 409 sean uno solo, no dos copias. */
  async function encolar(pedir: () => Promise<{ id: number }>, respaldo: string) {
    if (enVuelo.current) return;      // segundo submit del mismo tirón: se ignora
    enVuelo.current = true;
    setCargando(true);
    try {
      const c = await pedir();
      navigate(`/corridas/${c.id}`);
    } catch (err) {
      // El 409 del armado duplicado NO es un error del usuario: es el mismo armado
      // que acaba de pedir. Se lo lleva ahí en vez de dejarlo con un cartel rojo.
      const yaExiste = corridaEnCurso(err);
      if (yaExiste !== null) {
        toast.warning("Ese archivo ya se está armando; te llevamos a esa corrida.");
        navigate(`/corridas/${yaExiste}`);
      } else {
        toast.error(err instanceof Error ? err.message : respaldo);
      }
    } finally {
      enVuelo.current = false;
      setCargando(false);
    }
  }

  /** El formulario como FormData. Uno solo para previsualizar y para crear: si fueran
   *  dos, el archivo que se aprueba podría no ser el que se previsualizó. */
  function armarForm(archivo: File, confirmada: boolean): FormData {
    const form = new FormData();
    form.append("archivo", archivo);
    form.append("carpeta_id", String(carpetaDestino));
    form.append("nombre", nombre.trim());
    form.append("entidad", entidad);
    if (confirmada) form.append("confirmada", "true");
    if (listaId !== LISTA_PRINCIPAL_ID) form.append("lista_id", String(listaId));
    return form;
  }

  /** El archivo elegido, o null avisando qué falta. Los dos caminos (previsualizar y
   *  aprobar) validan lo mismo, así que la comprobación vive en un solo lugar. */
  function archivoElegido(): File | null {
    if (carpetaDestino == null) {
      toast.error("Elige una carpeta");
      return null;
    }
    const f = fileRef.current?.files?.[0];
    if (!f) {
      toast.error("Selecciona un archivo .xlsx o .csv");
      return null;
    }
    return f;
  }

  async function handleArmar(e: React.FormEvent) {
    e.preventDefault();
    const archivo = archivoElegido();
    if (!archivo) return;
    if (!requiereConfirmacion) {
      await encolar(() => crearCorrida(armarForm(archivo, false)),
                    "Error al crear la corrida");
      return;
    }
    // Ruta IDU: primero se muestra lo que se detectó. No se crea nada todavía.
    if (enVuelo.current) return;
    enVuelo.current = true;
    setCargando(true);
    try {
      setPrevia(await previsualizarCorrida(armarForm(archivo, false)));
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "No se pudo leer el archivo");
    } finally {
      enVuelo.current = false;
      setCargando(false);
    }
  }

  async function handleAprobar() {
    const archivo = archivoElegido();
    if (!archivo) return;
    await encolar(() => crearCorrida(armarForm(archivo, true)),
                  "Error al crear la corrida");
  }

  async function handleEjemplo() {
    await encolar(crearSample, "Error al crear corrida de ejemplo");
  }

  return (
    <div className={(previa ? "max-w-[900px]" : "max-w-[400px]") + " px-7 py-6"}>
      <h2 className="mb-4 text-[15px] font-semibold tracking-[-0.01em]">Nueva corrida</h2>
      <form onSubmit={handleArmar} className="flex flex-col gap-3">
        {/* Entidad: decide el lector del backend. Nativo como los demás selects de esta
            pantalla — los tests usan fireEvent.change y getByRole("option"), que no
            funcionan contra el Select de Radix. */}
        <div className={CLASE_CAMPO}>
          <label className={CLASE_ETIQUETA} htmlFor="entidad">
            Entidad o fuente del presupuesto
          </label>
          <select
            id="entidad"
            value={entidad}
            onChange={(e) => { setEntidad(e.target.value as Entidad); setPrevia(null); }}
            disabled={cargando}
            className={CLASE_SELECT}
          >
            {ENTIDADES.map((e) => (
              <option key={e.valor} value={e.valor}>{e.etiqueta}</option>
            ))}
          </select>
          {requiereConfirmacion && (
            <p className="mt-0.5 text-[11px] text-muted-foreground">
              Se lee el Formulario 1 de Presupuesto Oficial y se confirma la estructura
              antes de armar.
            </p>
          )}
        </div>

        {/* Archivo */}
        <div className={CLASE_CAMPO}>
          <label className={CLASE_ETIQUETA} htmlFor="archivo">
            Archivo de licitación
          </label>
          <input
            id="archivo"
            ref={fileRef}
            type="file"
            accept=".xlsx,.csv"
            onChange={handleArchivoChange}
            disabled={cargando}
            className="rounded-sm text-xs text-foreground file:mr-2 file:cursor-pointer file:rounded-md file:border file:border-input file:bg-card file:px-2 file:py-1 file:text-xs file:font-medium file:text-foreground hover:file:bg-muted focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring disabled:opacity-50"
          />
        </div>

        {/* Nombre */}
        <div className={CLASE_CAMPO}>
          <label className={CLASE_ETIQUETA} htmlFor="nombre">
            Nombre
          </label>
          <Input
            id="nombre"
            type="text"
            value={nombre}
            onChange={(e) => { setNombre(e.target.value); setNombreTocado(true); }}
            placeholder="Nombre de la corrida"
            disabled={cargando}
            className="text-xs"
          />
        </div>

        {/* Carpeta */}
        <div className={CLASE_CAMPO}>
          <label className={CLASE_ETIQUETA} htmlFor="carpeta-nivel1">
            Carpeta{" "}
            <span className="text-destructive" title="Obligatorio">
              *
            </span>
          </label>
          <div className="flex flex-wrap items-center gap-1.5">
            {/* Los <select> quedan NATIVOS a propósito. Los 7 tests de esta pantalla usan
                fireEvent.change() y getByRole("option"), que no funcionan contra el Select
                de Radix — no es un componente <select>. Se estilizan con tokens. */}
            <select
              id="carpeta-nivel1"
              value={nivel1Id ?? ""}
              onChange={handleNivel1Change}
              disabled={cargando}
              className={CLASE_SELECT}
            >
              <option value="">— Elegir carpeta —</option>
              {carpetas.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.nombre}
                </option>
              ))}
            </select>
            {hijas.length > 0 && (
              <select
                id="carpeta-nivel2"
                value={nivel2Id ?? ""}
                onChange={handleNivel2Change}
                disabled={cargando}
                className={CLASE_SELECT}
              >
                <option value="">— (ninguna) —</option>
                {hijas.map((h) => (
                  <option key={h.id} value={h.id}>
                    {h.nombre}
                  </option>
                ))}
              </select>
            )}
            <Button
              type="button"
              variant="outline"
              size="xs"
              disabled={cargando}
              onClick={handleCrearCarpeta}
            >
              + Carpeta
            </Button>
          </div>
        </div>

        {/* Lista de precios: visible (no "avanzado"), porque es inmutable
            tras crear la corrida — este es el único momento de acertar. */}
        <div className={CLASE_CAMPO}>
          <label className={CLASE_ETIQUETA} htmlFor="lista">
            Lista de precios
          </label>
          <select
            id="lista"
            value={listaId}
            onChange={(e) => setListaId(Number(e.target.value))}
            disabled={cargando}
            className={CLASE_SELECT}
          >
            {listas.map((l) => (
              <option key={l.id} value={l.id}>{l.nombre}</option>
            ))}
          </select>
          {/* El aviso está al lado de DOS botones y solo aplica a uno: "Usar ejemplo"
              pega a /api/sample, que no recibe lista_id — el ejemplo es una demo
              construida sobre Principal (sus contractuales son costo_Principal * (1+margen),
              ver pipeline.py::generate_sample). Sorprendió en el smoke test de producción
              del 2026-08-03, así que se dice explícitamente. Sin <strong> a propósito: el
              <p> queda como un solo nodo de texto y getByText() lo encuentra entero. */}
          {listaId !== LISTA_PRINCIPAL_ID && (
            <p className="mt-0.5 text-[11px] text-revisar">
              Se aplica al armar y no se puede cambiar después. «Usar ejemplo» usa Principal.
            </p>
          )}
        </div>

        {/* Botones */}
        <div className="mt-0.5 flex gap-2">
          {/* Solo `cargando` (evita el doble-submit). NO se deshabilita por falta de
              carpeta: `handleArmar` ya avisa con un toast, y un botón deshabilitado sin
              explicación deja al usuario sin salida — pasó en el smoke test de
              producción del 2026-08-03, donde ese guard volvía inalcanzable al propio
              mensaje. El backend valida igual: carpeta_id es Form(...) obligatorio y
              rutas.py rechaza con 400 una carpeta inexistente.
              Y ahora el deshabilitado SE VE gris: antes usaba estilo inline y el
              disabled:opacity-50 del primitivo no llegaba a aplicarse. */}
          <Button type="submit" disabled={cargando}>
            {cargando
              ? (requiereConfirmacion ? "Leyendo…" : "Armando…")
              : (requiereConfirmacion ? "Previsualizar" : "Armar")}
          </Button>
          <Button type="button" variant="outline" disabled={cargando} onClick={handleEjemplo}>
            Usar ejemplo
          </Button>
        </div>
      </form>

      {previa && (
        <PreviaIdu
          previa={previa}
          cargando={cargando}
          onAprobar={handleAprobar}
          onCancelar={() => setPrevia(null)}
          onCambiarArchivo={() => { setPrevia(null); fileRef.current?.click(); }}
        />
      )}
    </div>
  );
}

const CLASE_CAMPO = "flex flex-col gap-1";
const CLASE_ETIQUETA = "text-xs font-medium";
const CLASE_SELECT =
  "h-8 rounded-md border border-input bg-card px-2 text-xs text-foreground outline-none " +
  "focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 " +
  "disabled:cursor-not-allowed disabled:opacity-50";
