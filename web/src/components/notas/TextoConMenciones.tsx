import { partesConMenciones } from "@/lib/menciones";

/** El texto de una nota con los @Nombre mencionados resaltados. */
export function TextoConMenciones({ texto, nombres }: { texto: string; nombres: string[] }) {
  return (
    <p className="mt-1 whitespace-pre-wrap">
      {partesConMenciones(texto, nombres).map((p, i) =>
        p.mencion ? (
          <span key={i} data-mencion="si" className="font-medium text-primary">{p.texto}</span>
        ) : (
          <span key={i}>{p.texto}</span>
        ),
      )}
    </p>
  );
}
