import { useEffect, useRef, useState } from "react";
import { listarApus } from "@/api/autoria";
import type { ApuResumen } from "@/lib/tipos";

const inputCls =
  "h-8 w-full rounded border border-border bg-transparent px-2 py-1 text-xs outline-none focus-visible:border-ring focus-visible:ring-2 focus-visible:ring-ring/40";

interface BuscadorApuProps {
  onElegir: (apu: ApuResumen) => void;
  disabled?: boolean;
  placeholder?: string;
}

export default function BuscadorApu({
  onElegir,
  disabled = false,
  placeholder = "Buscar APU por código / nombre…",
}: BuscadorApuProps) {
  const [q, setQ] = useState("");
  const [resultados, setResultados] = useState<ApuResumen[]>([]);
  const [abierto, setAbierto] = useState(false);
  const [buscando, setBuscando] = useState(false);
  const boxRef = useRef<HTMLDivElement>(null);

  // Cerrar al hacer clic fuera
  useEffect(() => {
    function onDoc(e: MouseEvent) {
      if (boxRef.current && !boxRef.current.contains(e.target as Node)) {
        setAbierto(false);
      }
    }
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, []);

  // Debounce de la búsqueda
  useEffect(() => {
    if (q.trim() === "") {
      setResultados([]);
      return;
    }
    let cancelado = false;
    setBuscando(true);
    const t = setTimeout(async () => {
      try {
        const res = await listarApus({ q: q.trim(), limit: 15 });
        if (!cancelado) {
          setResultados(res.items);
          setAbierto(true);
        }
      } catch {
        if (!cancelado) setResultados([]);
      } finally {
        if (!cancelado) setBuscando(false);
      }
    }, 250);
    return () => {
      cancelado = true;
      clearTimeout(t);
    };
  }, [q]);

  function elegir(apu: ApuResumen) {
    onElegir(apu);
    setQ("");
    setResultados([]);
    setAbierto(false);
  }

  return (
    <div ref={boxRef} className="relative">
      <input
        className={inputCls}
        placeholder={placeholder}
        value={q}
        disabled={disabled}
        onChange={(e) => setQ(e.target.value)}
        onFocus={() => {
          if (resultados.length > 0) setAbierto(true);
        }}
      />
      {abierto && (
        <div className="absolute z-20 mt-1 w-full max-h-52 overflow-auto rounded border bg-popover shadow-md">
          {buscando && (
            <p className="px-2 py-1.5 text-[11px] text-muted-foreground">buscando…</p>
          )}
          {!buscando && resultados.length === 0 && q.trim() !== "" && (
            <p className="px-2 py-1.5 text-[11px] text-muted-foreground">Sin resultados</p>
          )}
          {resultados.map((apu) => (
            <button
              key={`${apu.codigo}@@${apu.turno}`}
              type="button"
              onClick={() => elegir(apu)}
              className="flex w-full items-baseline gap-2 px-2 py-1 text-left text-xs hover:bg-muted"
            >
              <span className="font-mono text-[11px] text-muted-foreground">{apu.codigo}</span>
              <span className="rounded bg-muted px-1 text-[10px] text-muted-foreground">
                {apu.turno}
              </span>
              <span className="truncate">{apu.nombre}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
