import { FileSpreadsheet, Layers, Ruler } from "lucide-react";

/** El marco de las pantallas de entrada: panel de marca a la izquierda, formulario
 *  a la derecha. Lo usan `Login` y `DefinirClave`, que son la misma forma.
 *
 *  Sobre el contenido del panel: la referencia de diseño traía un testimonio con
 *  estrellas y una fila de logos de clientes. Acá serían inventados, así que en su
 *  lugar va lo que la app hace de verdad — que a alguien nuevo le sirve más que una
 *  reseña. Y donde la referencia ponía «Sign up» va la verdad: no hay registro
 *  abierto, el acceso lo habilita un Admin.
 *
 *  Debajo de 860px el panel desaparece y queda solo el formulario, con la marca
 *  arriba para no perder la identidad. Es `@container`, no `@media`: responde al
 *  ancho que el marco tiene, no al del viewport. */

const CAPACIDADES = [
  {
    Icono: Layers,
    titulo: "Reutiliza tu histórico",
    detalle: "Cruza cada ítem de la lista contra los APUs que ya armaste.",
  },
  {
    Icono: Ruler,
    titulo: "Costea contra la lista que elijas",
    detalle: "La Principal, o la tarifa de la obra de no previstos.",
  },
  {
    Icono: FileSpreadsheet,
    titulo: "Entrega el cuadro en Excel",
    detalle: "Precio contractual contra precio de costo, ítem por ítem.",
  },
];

/** `colorIcono` no es un detalle estético: sobre el panel grafito va
 *  `--rail-on-primary` (6.07:1 ahí), pero ese mismo cian aclarado sobre la tarjeta
 *  blanca del formulario da 2.60:1 y no llega al 3:1 de WCAG 1.4.11. Sobre claro va
 *  `--rail`, que da 4.45:1. Un solo color para los dos fondos no existe. */
function Marca({ className, colorIcono }: { className?: string; colorIcono: string }) {
  return (
    <span className={className}>
      <svg
        viewBox="0 0 16 16"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.4"
        strokeLinecap="round"
        aria-hidden
        className={`size-4 shrink-0 ${colorIcono}`}
      >
        <path d="M2 4h12" />
        <path d="M2 8h8" />
        <path d="M2 12h4" />
      </svg>
      <span className="text-sm font-semibold tracking-[-0.015em]">Armador de APUs</span>
    </span>
  );
}

export default function MarcoIngreso({ children }: { children: React.ReactNode }) {
  return (
    <div className="@container min-h-dvh">
      <div className="grid min-h-dvh grid-cols-2 text-[13px] @max-[860px]:grid-cols-1">
        {/* Panel de marca */}
        <div className="flex flex-col gap-7 bg-primary px-9 py-8 text-primary-foreground @max-[860px]:hidden">
          <Marca className="flex items-center gap-2.5" colorIcono="text-rail-on-primary" />

          <div className="flex flex-1 flex-col justify-center gap-5">
            <h1 className="max-w-[22ch] text-[clamp(26px,3.3vw,34px)] leading-[1.12] font-semibold tracking-[-0.03em] text-balance">
              Herramienta de evaluación y generación de{" "}
              <span className="border-b-[3px] border-rail-on-primary pb-px">APUs</span>.
            </h1>
            <p className="max-w-[42ch] text-[13.5px] leading-relaxed text-primary-foreground-muted">
              Toma la lista de licitación, reutiliza el histórico de la empresa para armar los
              APUs y entrega el cuadro resumen.
            </p>

            <ul className="flex flex-col rounded-sm border border-primary-border">
              {CAPACIDADES.map(({ Icono, titulo, detalle }) => (
                <li
                  key={titulo}
                  className="flex gap-3 border-t border-primary-border px-3.5 py-3 first:border-t-0"
                >
                  <Icono aria-hidden className="mt-0.5 size-3.5 shrink-0 text-rail-on-primary" />
                  <span className="flex min-w-0 flex-col gap-0.5">
                    <span className="text-[12.5px] font-semibold">{titulo}</span>
                    <span className="text-[11.5px] leading-snug text-primary-foreground-muted">
                      {detalle}
                    </span>
                  </span>
                </li>
              ))}
            </ul>
          </div>

          <div className="flex flex-col gap-2.5">
            <hr className="border-primary-border" />
            <span className="font-mono text-[9.5px] font-medium tracking-[0.14em] uppercase text-primary-foreground-muted">
              Indugravas · Uso interno
            </span>
          </div>
        </div>

        {/* Formulario */}
        <div className="flex flex-col justify-center bg-card px-9 py-8 @max-[860px]:px-6">
          <div className="mx-auto flex w-full max-w-[340px] flex-col gap-[18px]">
            <Marca
              className="mb-1 hidden items-center justify-center gap-2.5 text-foreground @max-[860px]:flex"
              colorIcono="text-rail"
            />
            {children}
          </div>
        </div>
      </div>
    </div>
  );
}
