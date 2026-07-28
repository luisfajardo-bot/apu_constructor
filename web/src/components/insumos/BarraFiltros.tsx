import { useEffect, useState } from "react";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { getGrupos, getFuentes } from "@/api/insumos";
import type { ListaPrecios } from "@/lib/tipos";

export interface FiltrosState {
  q: string;
  grupo: string;
  fuente: string;
  clasificacion: string;
  lista: number;
  sinPrecio: boolean;
  offset: number;
}

interface BarraFiltrosProps {
  filtros: FiltrosState;
  listas: ListaPrecios[];
  total: number;
  limit: number;
  onChange: (f: Partial<FiltrosState>) => void;
}

export function BarraFiltros({ filtros, listas, total, limit, onChange }: BarraFiltrosProps) {
  const [grupos, setGrupos] = useState<string[]>([]);
  const [fuentes, setFuentes] = useState<string[]>([]);
  const [inputQ, setInputQ] = useState(filtros.q);

  useEffect(() => {
    getGrupos().then(setGrupos).catch(() => {});
  }, []);

  // Las fuentes son un atributo de la fila de precio de CADA lista: hay que
  // recargarlas cuando la lista activa cambia (si no, se ven las de la anterior).
  useEffect(() => {
    getFuentes(filtros.lista).then(setFuentes).catch(() => {});
  }, [filtros.lista]);

  // Debounce q
  useEffect(() => {
    const t = setTimeout(() => {
      if (inputQ !== filtros.q) onChange({ q: inputQ, offset: 0 });
    }, 300);
    return () => clearTimeout(t);
  }, [inputQ, filtros.q, onChange]);

  const hasPrev = filtros.offset > 0;
  const hasNext = filtros.offset + limit < total;
  const page = Math.floor(filtros.offset / limit) + 1;
  const totalPages = Math.max(1, Math.ceil(total / limit));

  return (
    <div className="flex flex-wrap gap-2 items-center px-3 py-2 border-b bg-muted/30">
      <Select
        value={String(filtros.lista)}
        onValueChange={(v) =>
          onChange({ lista: Number(v), fuente: "", clasificacion: "", sinPrecio: false, offset: 0 })
        }
      >
        <SelectTrigger size="sm" className="w-44 text-xs">
          <SelectValue placeholder="Lista de precios" />
        </SelectTrigger>
        <SelectContent>
          {listas.map((l) => (
            <SelectItem key={l.id} value={String(l.id)}>
              {l.nombre}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>

      <Input
        className="h-7 w-48 text-xs"
        placeholder="Buscar código / nombre…"
        value={inputQ}
        onChange={(e) => setInputQ(e.target.value)}
      />

      <Select
        value={filtros.grupo || "__all__"}
        onValueChange={(v) => onChange({ grupo: v === "__all__" ? "" : v, offset: 0 })}
      >
        <SelectTrigger size="sm" className="w-36 text-xs">
          <SelectValue placeholder="Todos los grupos" />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="__all__">Todos los grupos</SelectItem>
          {grupos.map((g) => (
            <SelectItem key={g} value={g}>
              {g}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>

      <Select
        value={filtros.fuente || "__all__"}
        onValueChange={(v) => onChange({ fuente: v === "__all__" ? "" : v, offset: 0 })}
      >
        <SelectTrigger size="sm" className="w-36 text-xs" disabled={filtros.sinPrecio}>
          <SelectValue placeholder="Todas las fuentes" />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="__all__">Todas las fuentes</SelectItem>
          {fuentes.map((f) => (
            <SelectItem key={f} value={f}>
              {f}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>

      <Select
        value={filtros.clasificacion || "__all__"}
        onValueChange={(v) =>
          onChange({ clasificacion: v === "__all__" ? "" : v, offset: 0 })
        }
      >
        <SelectTrigger size="sm" className="w-32 text-xs" disabled={filtros.sinPrecio}>
          <SelectValue placeholder="Clasificación" />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="__all__">Público + Interno</SelectItem>
          <SelectItem value="publico">Solo público</SelectItem>
          <SelectItem value="interno">Solo interno</SelectItem>
        </SelectContent>
      </Select>

      <Button
        size="xs"
        variant={filtros.sinPrecio ? "default" : "outline"}
        disabled={Boolean(filtros.fuente || filtros.clasificacion)}
        title="Insumos sin tarifa en la lista seleccionada"
        onClick={() => onChange({ sinPrecio: !filtros.sinPrecio, offset: 0 })}
      >
        Sin precio
      </Button>

      <span className="ml-auto text-xs text-muted-foreground">
        {total} insumos · pág. {page}/{totalPages}
      </span>

      <Button
        size="xs"
        variant="outline"
        disabled={!hasPrev}
        onClick={() => onChange({ offset: Math.max(0, filtros.offset - limit) })}
      >
        ‹ Ant.
      </Button>
      <Button
        size="xs"
        variant="outline"
        disabled={!hasNext}
        onClick={() => onChange({ offset: filtros.offset + limit })}
      >
        Sig. ›
      </Button>
    </div>
  );
}
