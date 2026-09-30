import { useState } from "react";
import type { Mencionable, MencionNota } from "@/lib/tipos";
import { consultaMencion, etiquetaDe, insertarMencion } from "@/lib/menciones";

interface Props {
  ariaLabel: string;
  valor: string;
  onValor: (v: string) => void;
  elegidos: MencionNota[];
  onElegidos: (e: MencionNota[]) => void;
  mencionables: Mencionable[];
  rows?: number;
  placeholder?: string;
  maxLength?: number;
  /** Hacia dónde abre la lista: "abajo" para cajas dentro de una lista con scroll. */
  abrirHacia?: "arriba" | "abajo";
}

const areaCls =
  "w-full rounded border border-border bg-transparent px-2 py-1 text-xs outline-none " +
  "focus-visible:border-ring focus-visible:ring-2 focus-visible:ring-ring/40";
const MAX_SUGERENCIAS = 6;

/** Textarea con autocompletado de @: al escribir "@be" ofrece los usuarios cuyo nombre o
 *  email contiene "be"; escoger uno escribe "@Nombre " y lo suma a los elegidos. Qué
 *  menciones valen al guardar lo decide `mencionesVigentes` (lo que siga escrito). */
export function CajaConMenciones({ ariaLabel, valor, onValor, elegidos, onElegidos,
                                   mencionables, rows = 3, placeholder, maxLength = 4000, abrirHacia = "arriba" }: Props) {
  const [consulta, setConsulta] = useState<{ inicio: number; cursor: number; q: string } | null>(null);

  const q = (consulta?.q ?? "").toLocaleLowerCase("es");
  const sugerencias = consulta
    ? mencionables
        .filter((u) => etiquetaDe(u).toLocaleLowerCase("es").includes(q) ||
                       u.email.toLocaleLowerCase("es").includes(q))
        .slice(0, MAX_SUGERENCIAS)
    : [];

  function cambiar(e: React.ChangeEvent<HTMLTextAreaElement>) {
    const v = e.target.value;
    const cursor = e.target.selectionStart ?? v.length;
    onValor(v);
    const c = consultaMencion(v, cursor);
    setConsulta(c ? { ...c, cursor } : null);
  }

  function escoger(u: Mencionable) {
    if (!consulta) return;
    const etiqueta = etiquetaDe(u);
    onValor(insertarMencion(valor, consulta.inicio, consulta.cursor, etiqueta).texto);
    if (!elegidos.some((x) => x.user_id === u.user_id)) {
      onElegidos([...elegidos, { user_id: u.user_id, nombre: etiqueta }]);
    }
    setConsulta(null);
  }

  const abiertas = sugerencias.length > 0;

  return (
    <div className="relative">
      <textarea aria-label={ariaLabel} rows={rows} className={areaCls} value={valor}
                maxLength={maxLength} placeholder={placeholder} onChange={cambiar}
                data-sugerencias={abiertas ? "si" : "no"} onBlur={() => setConsulta(null)}
                onKeyDown={(e) => { if (e.key === "Escape" && consulta) { e.stopPropagation(); setConsulta(null); } }} />
      {abiertas && (
        <div className={(abrirHacia === "abajo" ? "top-full mt-1" : "bottom-full mb-1") + " absolute left-0 z-50 w-64 rounded border border-border bg-background shadow"}>
          {sugerencias.map((u) => (
            <button key={u.user_id} type="button" aria-label={`Mencionar a ${etiquetaDe(u)}`}
                    className="block w-full px-2 py-1 text-left text-xs hover:bg-muted"
                    onMouseDown={(e) => e.preventDefault()} onClick={() => escoger(u)}>
              <span className="font-medium">{etiquetaDe(u)}</span>
              {u.nombre && <span className="ml-1 text-muted-foreground">{u.email}</span>}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
